"""DataQa 持久化 seam：问题、Run 绑定与结果写入同事务完成。"""

from __future__ import annotations

from contextlib import closing

from dataclasses import dataclass
from datetime import UTC, timedelta
from decimal import Decimal
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.core.errors import AppError, ErrorCode
from backend.db.models import DataQaQuery, Message, Run, Thread, User, utcnow
from backend.dataqa.contracts import DataQaQueryV1
from backend.events.generated.run_event_v1 import RunEventType
from backend.events.journal import append_event_in_session
from backend.infra.database import SessionLocal
from backend.model_control import ModelCatalogSnapshot
from backend.runs.repository import RunRepository, hash_run_request
from backend.runs.state import RunStatus, TERMINAL_RUN_STATUSES

SessionFactory = Callable[[], Session]

DATAQA_BUDGET_SECONDS = 600


@dataclass(frozen=True, slots=True)
class QueryCreateRecord:
    query: DataQaQueryV1
    run_id: str


class DataQaRepository:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ 读

    @staticmethod
    def _user(db: Session, username: str) -> User:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise AppError(
                ErrorCode.AUTHENTICATION_REQUIRED, "用户不存在", status_code=401
            )
        if user.role != "admin":
            raise AppError(
                ErrorCode.PERMISSION_DENIED, "管理员权限不足", status_code=403
            )
        return user

    def _owned_query(
        self, db: Session, *, username: str, tenant_id: str, query_id: str
    ) -> DataQaQuery:
        self._user(db, username)
        row = (
            db.query(DataQaQuery)
            .join(User, User.id == DataQaQuery.user_id)
            .filter(
                DataQaQuery.id == query_id,
                DataQaQuery.tenant_id == tenant_id,
                User.username == username,
            )
            .first()
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "问数查询不存在", status_code=404)
        return row

    @classmethod
    def _view(cls, db: Session, row: DataQaQuery) -> DataQaQueryV1:
        run = db.get(Run, row.run_id) if row.run_id else None
        analysis = (
            db.query(Run)
            .filter(
                Run.thread_ref_id == row.thread_ref_id,
                Run.channel == "dataqa",
                Run.id != row.run_id,
            )
            .order_by(Run.created_at.desc(), Run.id.desc())
            .first()
        )
        status = (
            "failed"
            if run is None
            else {
                "succeeded": "completed",
                "failed": "failed",
                "cancelled": "failed",
                "pending": "pending",
                "queued": "pending",
            }.get(run.status, "running")
        )
        return DataQaQueryV1(
            id=row.id,
            question=row.question,
            status=status,  # type: ignore[arg-type]
            run_id=row.run_id,
            error_code=run.error_code if run else row.error_code,
            analysis_run_id=analysis.id if analysis else None,
            analysis_status=analysis.status if analysis else None,
            analysis_error_code=analysis.error_code if analysis else None,
            version=row.version,
            created_at=row.created_at.isoformat() if row.created_at else "",
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
            result=row.result_json if status == "completed" else None,  # type: ignore[arg-type]
        )

    def get_query(
        self, *, username: str, tenant_id: str, query_id: str
    ) -> DataQaQueryV1:
        with closing(self._session_factory()) as db:
            row = self._owned_query(
                db, username=username, tenant_id=tenant_id, query_id=query_id
            )
            return self._view(db, row)

    def list_queries(
        self, *, username: str, tenant_id: str, limit: int = 50
    ) -> list[DataQaQueryV1]:
        with closing(self._session_factory()) as db:
            user = self._user(db, username)
            rows = (
                db.query(DataQaQuery)
                .filter(
                    DataQaQuery.tenant_id == tenant_id,
                    DataQaQuery.user_id == user.id,
                )
                .order_by(DataQaQuery.created_at.desc(), DataQaQuery.id.desc())
                .limit(limit)
                .all()
            )
            return [self._view(db, row) for row in rows]

    def load_by_run(self, run_id: str) -> DataQaQuery | None:
        with closing(self._session_factory()) as db:
            return (
                db.query(DataQaQuery)
                .join(Run, Run.thread_ref_id == DataQaQuery.thread_ref_id)
                .filter(Run.id == run_id, Run.channel == "dataqa")
                .first()
            )

    # ------------------------------------------------------------------ 写

    def freeze_grounding(
        self,
        *,
        run_id: str,
        worker_id: str,
        fencing_token: int,
        semantic_schema_hash: str,
        candidate_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the exact compact schema once so retries keep their scope."""
        with closing(self._session_factory()) as db:
            with db.begin():
                row = self._owned_execution(db, run_id, worker_id, fencing_token)
                if row.candidate_schema_json is not None:
                    return dict(row.candidate_schema_json)
                row.semantic_schema_hash = semantic_schema_hash
                row.candidate_schema_json = candidate_schema
                row.version += 1
                row.updated_at = utcnow()
                return dict(candidate_schema)

    def create_query(
        self,
        *,
        username: str,
        tenant_id: str,
        question: str,
        idempotency_key: str,
        model_snapshot: ModelCatalogSnapshot,
    ) -> QueryCreateRecord:
        with closing(self._session_factory()) as db:
            with db.begin():
                user = self._user(db, username)
                existing = (
                    db.query(DataQaQuery)
                    .filter(
                        DataQaQuery.user_id == user.id,
                        DataQaQuery.idempotency_key == idempotency_key,
                    )
                    .first()
                )
                if existing is not None:
                    if existing.question != question or existing.tenant_id != tenant_id:
                        raise AppError(
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "幂等键对应不同请求",
                            status_code=409,
                        )
                    return QueryCreateRecord(
                        self._view(db, existing), str(existing.run_id)
                    )
                now = utcnow()
                query_id = f"qa_{uuid4().hex}"
                thread_id = f"thread_dataqa_{uuid4().hex}"
                thread = Thread(
                    user_id=user.id,
                    thread_id=thread_id,
                    kind="dataqa",
                    status="active",
                    version=0,
                    message_count=0,
                    last_sequence=0,
                    metadata_json={"title": question[:80], "dataqa_query_id": query_id},
                    created_at=now,
                    updated_at=now,
                )
                db.add(thread)
                db.flush()
                run_id = f"run_{uuid4().hex}"
                request_hash = hash_run_request(question, channel="dataqa")
                run = Run(
                    id=run_id,
                    thread_ref_id=thread.id,
                    user_id=user.id,
                    tenant_id=tenant_id,
                    channel="dataqa",
                    approved_tools_json=[],
                    status=RunStatus.PENDING.value,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    model_name=model_snapshot.require("fast").model_name,
                    model_catalog_hash=model_snapshot.catalog_hash,
                    model_snapshot_json=model_snapshot.model_dump(mode="json"),
                    on_disconnect="continue",
                    multitask_strategy="reject",
                    fencing_token=1,
                    deadline_at=now + timedelta(seconds=DATAQA_BUDGET_SECONDS),
                    input_tokens=0,
                    output_tokens=0,
                    cost=Decimal("0"),
                    created_at=now,
                    updated_at=now,
                )
                db.add(run)
                db.flush()
                human = Message(
                    thread_ref_id=thread.id,
                    run_id=run.id,
                    client_message_id=f"{run.id}:user",
                    sequence=thread.last_sequence + 1,
                    message_type="human",
                    content=question,
                    status="completed",
                    timestamp=now,
                    updated_at=now,
                )
                assistant = Message(
                    thread_ref_id=thread.id,
                    run_id=run.id,
                    client_message_id=f"{run.id}:assistant",
                    sequence=thread.last_sequence + 2,
                    message_type="ai",
                    content="",
                    status="streaming",
                    timestamp=now,
                    updated_at=now,
                )
                db.add_all((human, assistant))
                db.flush()
                thread.last_sequence += 2
                thread.message_count += 2
                thread.version += 2
                thread.updated_at = now
                run.user_message_id = human.id
                run.assistant_message_id = assistant.id
                run.fencing_token = thread.version
                query = DataQaQuery(
                    id=query_id,
                    tenant_id=tenant_id,
                    user_id=user.id,
                    thread_ref_id=thread.id,
                    run_id=run.id,
                    idempotency_key=idempotency_key,
                    question=question,
                    status="pending",
                    result_json=None,
                    error_code=None,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                db.add(query)
                db.flush()
                append_event_in_session(
                    db,
                    run=run,
                    thread_id=thread.thread_id,
                    event_type=RunEventType.RUN_CREATED,
                    data={
                        "status": run.status,
                        "channel": "dataqa",
                        "query_id": query_id,
                    },
                )
                view = DataQaQueryV1(
                    id=query.id,
                    question=query.question,
                    status="pending",
                    run_id=run.id,
                    error_code=None,
                    version=1,
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                    result=None,
                )
                return QueryCreateRecord(view, run.id)

    @staticmethod
    def _owned_execution(
        db: Session, run_id: str, worker_id: str, fencing_token: int
    ) -> DataQaQuery:
        # Match the canonical finalizer's Run-first lock order.
        run = db.query(Run).filter(Run.id == run_id).with_for_update().first()
        if run is None:
            raise AppError(ErrorCode.RUN_NOT_FOUND, "Run 不存在", status_code=404)
        lease = run.lease_expires_at
        if lease is not None and lease.tzinfo is None:
            lease = lease.replace(tzinfo=UTC)
        if (
            run.channel != "dataqa"
            or run.status != RunStatus.RUNNING.value
            or run.owner_worker_id != worker_id
            or run.fencing_token != fencing_token
            or lease is None
            or lease <= utcnow().replace(tzinfo=UTC)
        ):
            raise AppError(
                ErrorCode.RUN_STATE_CONFLICT, "问数执行权已失效", status_code=409
            )
        user = db.get(User, run.user_id)
        if user is None or user.role != "admin":
            raise AppError(
                ErrorCode.PERMISSION_DENIED, "管理员权限不足", status_code=403
            )
        row = (
            db.query(DataQaQuery)
            .filter(DataQaQuery.thread_ref_id == run.thread_ref_id)
            .with_for_update()
            .first()
        )
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, "问数查询不存在", status_code=404)
        return row

    def mark_running(self, *, run_id: str, worker_id: str, fencing_token: int) -> None:
        with closing(self._session_factory()) as db:
            with db.begin():
                row = self._owned_execution(db, run_id, worker_id, fencing_token)
                if row.run_id == run_id:
                    row.status = "running"
                    row.updated_at = utcnow()

    def complete_query(
        self,
        *,
        run_id: str,
        worker_id: str,
        fencing_token: int,
        result: dict[str, Any],
        content: str,
    ) -> None:
        """Stage the result; only the canonical finalizer publishes terminal state/message."""
        with closing(self._session_factory()) as db:
            with db.begin():
                row = self._owned_execution(db, run_id, worker_id, fencing_token)
                if row.result_json is not None:
                    return
                row.result_json = result
                row.version += 1
                row.updated_at = utcnow()

    def create_analysis(
        self,
        *,
        username: str,
        tenant_id: str,
        query_id: str,
        idempotency_key: str,
        model_snapshot: ModelCatalogSnapshot,
    ) -> QueryCreateRecord:
        with closing(self._session_factory()) as db:
            row = self._owned_query(
                db, username=username, tenant_id=tenant_id, query_id=query_id
            )
            view = self._view(db, row)
            if view.status != "completed" or view.result is None:
                raise AppError(
                    ErrorCode.RUN_STATE_CONFLICT,
                    "查询尚未完成，无法生成分析",
                    status_code=409,
                )
            if view.result.analysis is not None:
                return QueryCreateRecord(view, view.analysis_run_id or str(row.run_id))
            thread = db.get(Thread, row.thread_ref_id)
            if thread is None:
                raise AppError(
                    ErrorCode.NOT_FOUND, "问数 Thread 不存在", status_code=404
                )
            thread_id = thread.thread_id
        reservation = RunRepository(self._session_factory).reserve(
            username=username,
            thread_id=thread_id,
            message="生成数据分析",
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
            channel="dataqa",
            request_hash=hash_run_request(
                f"dataqa-analysis:{query_id}", tenant_id=tenant_id, channel="dataqa"
            ),
            model_snapshot=model_snapshot,
            model_name=model_snapshot.require("answer").model_name,
            multitask_strategy="reject",
            on_disconnect="continue",
        )
        return QueryCreateRecord(
            self.get_query(username=username, tenant_id=tenant_id, query_id=query_id),
            reservation.run.id,
        )

    def delete_query(self, *, username: str, tenant_id: str, query_id: str) -> bool:
        """Serialize deletion with new Run reservations without inverting Run locks."""
        with closing(self._session_factory()) as db:
            with db.begin():
                row = self._owned_query(
                    db, username=username, tenant_id=tenant_id, query_id=query_id
                )
                thread = (
                    db.query(Thread)
                    .filter(Thread.id == row.thread_ref_id)
                    .with_for_update()
                    .first()
                )
                # Do not wait on an active Run's lock while holding its Thread lock:
                # the canonical finalizer acquires Run before Thread.
                active = (
                    db.query(Run)
                    .filter(
                        Run.thread_ref_id == row.thread_ref_id,
                        Run.status.not_in(TERMINAL_RUN_STATUSES),
                    )
                    .first()
                )
                if active is not None:
                    raise AppError(
                        ErrorCode.RUN_ACTIVE,
                        "问数仍在执行，请等待完成后再删除",
                        status_code=409,
                        safe_details={
                            "active_run_id": active.id,
                            "active_run_status": active.status,
                        },
                    )
                db.delete(row)
                if thread is not None:
                    db.delete(thread)
                return True


dataqa_repository = DataQaRepository()
