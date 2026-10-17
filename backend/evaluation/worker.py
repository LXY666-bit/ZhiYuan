from __future__ import annotations

import logging
import os
import socket
from threading import Event, Thread
from uuid import uuid4

from backend.core.errors import (
    AppError,
    PublicError,
    public_error_from_exception,
    serialize_public_error,
)
from backend.core.settings import AppSettings, get_settings
from backend.env import PROJECT_ROOT
from backend.evaluation.contracts import ClaimedRagEvaluationJob
from backend.evaluation.rag import (
    RagEvalObservationBundle,
    RagEvalReport,
    evaluate_rag,
    evaluate_rag_partial,
)
from backend.evaluation.rag_adapters import profile_fingerprint, rag_source_fingerprint
from backend.evaluation.repository import (
    RagEvaluationRepository,
    rag_evaluation_repository,
)
from backend.evaluation.runtime import RagEvaluationRuntime, rag_evaluation_runtime


logger = logging.getLogger(__name__)


class RagEvaluationWorker:
    """Lease-owning serial worker for persistent RAG Evaluation Jobs."""

    def __init__(
        self,
        *,
        repository: RagEvaluationRepository = rag_evaluation_repository,
        runtime: RagEvaluationRuntime = rag_evaluation_runtime,
        settings: AppSettings | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.runtime = runtime
        self.settings = settings or get_settings()
        prefix = self.settings.worker.evaluation_worker_id or "rag-evaluation"
        self.worker_id = worker_id or (
            f"{prefix}-{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:12]}"
        )
        self._active_case_id: str | None = None

    def run_once(self) -> bool:
        worker_settings = self.settings.worker
        claimed = self.repository.claim_next(
            worker_id=self.worker_id,
            lease_seconds=worker_settings.evaluation_lease_seconds,
        )
        if claimed is None:
            self.repository.worker_heartbeat(
                worker_id=self.worker_id,
                status="running",
                metadata={"active_job_id": ""},
            )
            return False

        heartbeat_stop = Event()
        heartbeat_error = Event()
        heartbeat = Thread(
            target=self._heartbeat_loop,
            args=(claimed, heartbeat_stop, heartbeat_error),
            name=f"rag-evaluation-heartbeat:{claimed.job.id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            self._execute_claimed(claimed, heartbeat_error)
            return True
        except BaseException as exc:
            if self.repository.cancel_requested(claimed.job.id):
                self.repository.finish_cancelled(
                    job_id=claimed.job.id,
                    worker_id=self.worker_id,
                    fencing_token=claimed.job.fencing_token,
                )
                return True
            public_error = public_error_from_exception(exc)
            partial_report = None
            try:
                partial_report = self._partial_report(claimed, public_error)
            except Exception:
                logger.exception(
                    "RAG evaluation partial report could not be built job_id=%s",
                    claimed.job.id,
                )
            try:
                self.repository.fail_job(
                    job_id=claimed.job.id,
                    worker_id=self.worker_id,
                    fencing_token=claimed.job.fencing_token,
                    error_code=str(public_error.code),
                    error_detail_redacted=serialize_public_error(public_error),
                    case_id=self._active_case_id,
                    report=partial_report,
                )
            except Exception:
                logger.exception(
                    "RAG evaluation failure could not be persisted job_id=%s",
                    claimed.job.id,
                )
            logger.warning(
                "RAG evaluation job failed job_id=%s error_code=%s",
                claimed.job.id,
                public_error.code,
            )
            return True
        finally:
            self._active_case_id = None
            heartbeat_stop.set()
            heartbeat.join(timeout=max(worker_settings.evaluation_heartbeat_seconds, 1))

    def _execute_claimed(
        self,
        claimed: ClaimedRagEvaluationJob,
        heartbeat_error: Event,
    ) -> None:
        manifest = claimed.job.execution_manifest
        if manifest is None:
            raise AppError(
                "RAG_EVALUATION_SNAPSHOT_MISSING",
                "旧评测任务缺少检索快照，请重新创建",
                status_code=409,
            )
        if manifest.rag_source_fingerprint != rag_source_fingerprint(PROJECT_ROOT):
            raise AppError(
                "RAG_EVALUATION_SOURCE_CHANGED",
                "评测代码已变化，请重新创建任务",
                status_code=409,
            )
        case_index = {case.id: case for case in claimed.dataset.dataset.cases}
        while True:
            if heartbeat_error.is_set():
                raise RuntimeError("RAG evaluation worker lost job ownership")
            if self.repository.cancel_requested(claimed.job.id):
                self.repository.finish_cancelled(
                    job_id=claimed.job.id,
                    worker_id=self.worker_id,
                    fencing_token=claimed.job.fencing_token,
                )
                return
            case_record = self.repository.claim_case(
                job_id=claimed.job.id,
                worker_id=self.worker_id,
                fencing_token=claimed.job.fencing_token,
            )
            if case_record is None:
                break
            self._active_case_id = case_record.case_id
            case = case_index.get(case_record.case_id)
            if case is None:
                raise RuntimeError("RAG Evaluation Case is missing from its Dataset")
            execution = self.runtime.execute_case(
                job_id=claimed.job.id,
                case=case,
                model_snapshot=claimed.job.model_snapshot,
                retrieval_snapshot=manifest.retrieval_snapshot,
                timeout_seconds=self.settings.worker.evaluation_case_timeout_seconds,
                cancellation=lambda: (
                    heartbeat_error.is_set()
                    or self.repository.cancel_requested(claimed.job.id)
                ),
            )
            self.repository.complete_case(
                job_id=claimed.job.id,
                case_id=case.id,
                worker_id=self.worker_id,
                fencing_token=claimed.job.fencing_token,
                observation=execution.observation,
                generated_answer=execution.generated_answer,
                judge_reason=execution.judge_reason,
                judge=execution.judge,
                retrieved_identities=execution.retrieved_identities,
                duration_ms=execution.duration_ms,
            )
            self._active_case_id = None

        if self.repository.cancel_requested(claimed.job.id):
            self.repository.finish_cancelled(
                job_id=claimed.job.id,
                worker_id=self.worker_id,
                fencing_token=claimed.job.fencing_token,
            )
            return

        observations = self.repository.observations(claimed.job.id)
        baseline = self.repository.baseline_report(claimed.job.baseline_job_id)
        report = evaluate_rag(
            claimed.dataset.dataset,
            RagEvalObservationBundle(
                dataset_fingerprint=claimed.dataset.fingerprint,
                observations=observations,
            ),
            claimed.job.gate_policy,
            baseline=baseline,
            metadata=self._report_metadata(claimed),
        )
        self.repository.finish_job(
            job_id=claimed.job.id,
            worker_id=self.worker_id,
            fencing_token=claimed.job.fencing_token,
            report=report,
        )

    def _heartbeat_loop(
        self,
        claimed: ClaimedRagEvaluationJob,
        stop_event: Event,
        error_event: Event,
    ) -> None:
        interval = self.settings.worker.evaluation_heartbeat_seconds
        while not stop_event.wait(interval):
            try:
                self.repository.heartbeat(
                    job_id=claimed.job.id,
                    worker_id=self.worker_id,
                    fencing_token=claimed.job.fencing_token,
                    lease_seconds=self.settings.worker.evaluation_lease_seconds,
                )
                self.repository.worker_heartbeat(
                    worker_id=self.worker_id,
                    status="running",
                    metadata={"active_job_id": claimed.job.id},
                )
            except Exception:
                error_event.set()
                logger.exception(
                    "RAG evaluation heartbeat failed job_id=%s",
                    claimed.job.id,
                )
                return

    def _report_metadata(self, claimed: ClaimedRagEvaluationJob) -> dict:
        safe_models = {
            role.value: {
                "profile_id": spec.profile_id,
                "profile_version": spec.profile_version,
                "model_name": spec.model_name,
            }
            for role, spec in claimed.job.model_snapshot.assignments.items()
        }
        manifest = claimed.job.execution_manifest
        retrieval_index_ids = [manifest.retrieval_snapshot.index_id] if manifest else []
        return {
            "adapter": "persistent_rag_evaluation_worker",
            "provenance": "live_rag",
            "job_id": claimed.job.id,
            "model_catalog_hash": claimed.job.model_catalog_hash,
            "models": safe_models,
            "retrieval_index_ids": retrieval_index_ids,
            "rag_source_fingerprint": claimed.job.execution_manifest.rag_source_fingerprint
            if claimed.job.execution_manifest
            else None,
            "retrieval_snapshot_fingerprint": profile_fingerprint(
                claimed.job.execution_manifest.model_dump(mode="json")[
                    "retrieval_snapshot"
                ]
            )
            if claimed.job.execution_manifest
            else None,
            "judge_schema_version": 1,
        }

    def _partial_report(
        self,
        claimed: ClaimedRagEvaluationJob,
        error: PublicError,
    ) -> RagEvalReport:
        observations = tuple(
            case.observation
            for case in self.repository.list_cases(claimed.job.id)
            if case.observation is not None
        )
        metadata = self._report_metadata(claimed)
        metadata.update(
            {
                "completed_case_count": len(observations),
                "failure": {
                    "code": str(error.code),
                    "stage": error.stage or "worker",
                },
            }
        )
        return evaluate_rag_partial(
            claimed.dataset.dataset,
            RagEvalObservationBundle(
                dataset_fingerprint=claimed.dataset.fingerprint,
                observations=observations,
            ),
            claimed.job.gate_policy,
            metadata=metadata,
        )

    def run_forever(self, stop_event: Event) -> None:
        self.repository.worker_heartbeat(
            worker_id=self.worker_id,
            status="starting",
        )
        try:
            while not stop_event.is_set():
                worked = self.run_once()
                if not worked:
                    stop_event.wait(self.settings.worker.evaluation_poll_seconds)
        finally:
            self.repository.worker_heartbeat(
                worker_id=self.worker_id,
                status="stopped",
            )


__all__ = ["RagEvaluationWorker"]
