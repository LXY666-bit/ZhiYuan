from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from uuid import uuid4

from backend.model_control import ModelCatalogSnapshot
from backend.research.planner import ResearchPlanner, research_planner
from backend.research.repository import (
    PlanJobRecord,
    ResearchRepository,
    research_repository,
)


logger = logging.getLogger(__name__)


class ResearchPlanJobDispatcher:
    def __init__(
        self,
        *,
        repository: ResearchRepository = research_repository,
        planner: ResearchPlanner = research_planner,
        worker_id: str | None = None,
        poll_seconds: float = 0.5,
        lease_seconds: int = 120,
        heartbeat_seconds: int = 20,
    ) -> None:
        self.repository = repository
        self.planner = planner
        self.worker_id = (
            worker_id
            or f"research-plan-{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"
        )
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="research-plan-dispatcher")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            claimed = await asyncio.to_thread(
                self.repository.claim_plan_job,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if claimed is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except TimeoutError:
                    pass
                continue
            await self._execute(claimed)

    async def _execute(
        self,
        claimed: tuple[PlanJobRecord, str, str, str, list[str], dict],
    ) -> None:
        job, title, objective, mode, sources, snapshot_json = claimed
        started = time.monotonic()
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(job.id, job.fencing_token, heartbeat_stop),
            name=f"research-plan-heartbeat:{job.id}",
        )
        try:
            snapshot = ModelCatalogSnapshot.model_validate(snapshot_json)
            result = await asyncio.to_thread(
                self.planner.generate,
                objective=objective,
                title=title,
                mode=mode,
                sources=sources,
                model_snapshot=snapshot,
                cancellation=lambda: (
                    self._stop.is_set()
                    or self.repository.plan_job_cancel_requested(job.id)
                ),
            )
            await asyncio.to_thread(
                self.repository.finish_plan_job,
                job_id=job.id,
                worker_id=self.worker_id,
                fencing_token=job.fencing_token,
                steps=result.steps,
                usage_status=result.usage_status,
                duration_ms=max(int((time.monotonic() - started) * 1000), 0),
                error_code=result.error_code,
            )
        except Exception as exc:
            logger.exception("Research Plan Job failed job_id=%s", job.id)
            await asyncio.to_thread(
                self.repository.fail_plan_job,
                job_id=job.id,
                worker_id=self.worker_id,
                fencing_token=job.fencing_token,
                error_code=str(getattr(exc, "code", "RESEARCH_PLAN_FAILED")),
                duration_ms=max(int((time.monotonic() - started) * 1000), 0),
            )
        finally:
            heartbeat_stop.set()
            await heartbeat

    async def _heartbeat(
        self, job_id: str, fencing_token: int, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_seconds)
                return
            except TimeoutError:
                try:
                    await asyncio.to_thread(
                        self.repository.heartbeat_plan_job,
                        job_id=job_id,
                        worker_id=self.worker_id,
                        fencing_token=fencing_token,
                        lease_seconds=self.lease_seconds,
                    )
                except Exception:
                    logger.exception(
                        "Research Plan Job heartbeat failed job_id=%s", job_id
                    )
                    return


research_plan_dispatcher = ResearchPlanJobDispatcher()
