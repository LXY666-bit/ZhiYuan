from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Callable
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.errors import AppError, ErrorCode
from backend.db.models import (
    Message,
    ResearchAttachment,
    Artifact,
    ResearchClaim,
    ResearchEvidence,
    ResearchPlan,
    ResearchPlanJob,
    ResearchProject,
    ResearchRunManifest,
    ResearchUsage,
    ResearchSection,
    ResearchStep,
    Run,
    Thread,
    User,
    utcnow,
)
from backend.events.generated.run_event_v1 import RunEventType
from backend.events.journal import append_event_in_session
from backend.infra.database import SessionLocal
from backend.model_control import ModelCatalogSnapshot
from backend.research.generated.research_api_v1 import (
    ResearchPlanStepV1,
    ResearchPlanV1,
    ResearchProjectV1,
)
from backend.research.profiles import resolve_research_profile
from backend.runs.state import ACTIVE_RUN_STATUSES, RunStatus


SessionFactory = Callable[[], Session]


def _utc_isoformat(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    project: ResearchProjectV1
    run_id: str
    thread_version: int


@dataclass(frozen=True, slots=True)
class PlanJobRecord:
    id: str
    project_id: str
    status: str
    fencing_token: int
    attempts: int
    result_plan_id: str | None
    error_code: str | None
    created_at: object
    updated_at: object


class ResearchRepository:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _validate_plan_steps(
        steps: list[ResearchPlanStepV1], profile: dict, *, status_code: int
    ) -> list[ResearchPlanStepV1]:
        bounded = steps[: profile["max_steps"]]
        if len(bounded) < profile["min_steps"]:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"{profile['mode']} 模式要求 {profile['min_steps']}-{profile['max_steps']} 个步骤",
                status_code=status_code,
            )
        directions = [
            re.sub(r"\s+", " ", step.question).strip().casefold() for step in bounded
        ]
        if len(set(directions)) != len(directions):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "研究计划包含重复问题，请为每个步骤指定不同的核验方向",
                status_code=status_code,
            )
        return bounded

    @staticmethod
    def _user(db: Session, username: str) -> User:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise AppError(
                ErrorCode.AUTHENTICATION_REQUIRED, "用户不存在", status_code=401
            )
        return user

    @staticmethod
    def _owned_project(
        db: Session,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        lock: bool = False,
    ) -> tuple[ResearchProject, Thread, User]:
        query = (
            db.query(ResearchProject, Thread, User)
            .join(Thread, Thread.id == ResearchProject.thread_ref_id)
            .join(User, User.id == ResearchProject.user_id)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.tenant_id == tenant_id,
                ResearchProject.deleted_at.is_(None),
                User.username == username,
            )
        )
        if lock:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            raise AppError(
                ErrorCode.NOT_FOUND, "Research Project 不存在", status_code=404
            )
        return row

    @staticmethod
    def _latest_run(db: Session, thread_ref_id: int) -> Run | None:
        return (
            db.query(Run)
            .filter(Run.thread_ref_id == thread_ref_id, Run.channel == "research")
            .order_by(Run.created_at.desc(), Run.id.desc())
            .first()
        )

    @classmethod
    def _project_view(
        cls, db: Session, project: ResearchProject, thread: Thread
    ) -> ResearchProjectV1:
        run = cls._latest_run(db, thread.id)
        return ResearchProjectV1(
            id=project.id,
            thread_id=thread.thread_id,
            title=project.title,
            objective=project.objective,
            mode=project.mode,
            lifecycle_status=project.lifecycle_status,
            version=project.version,
            run_status=run.status if run else None,
            latest_run_id=run.id if run else None,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    @staticmethod
    def _plan_view(row: ResearchPlan) -> ResearchPlanV1:
        payload = dict(row.plan_json or {})
        return ResearchPlanV1(
            id=row.id,
            project_id=row.project_id,
            version=row.version,
            objective=str(payload.get("objective") or ""),
            steps=[
                ResearchPlanStepV1.model_validate(value)
                for value in payload.get("steps", [])
            ],
            created_at=row.created_at,
        )

    @staticmethod
    def _job_view(row: ResearchPlanJob) -> PlanJobRecord:
        return PlanJobRecord(
            id=row.id,
            project_id=row.project_id,
            status=row.status,
            fencing_token=row.fencing_token,
            attempts=row.attempts,
            result_plan_id=row.result_plan_id,
            error_code=row.error_code,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create_project(
        self,
        *,
        username: str,
        tenant_id: str,
        title: str,
        objective: str,
        mode: str,
        sources: list[str],
        output_formats: list[str],
    ) -> ResearchProjectV1:
        now = utcnow()
        project_id = f"rproj_{uuid4().hex}"
        thread_id = f"research:{uuid4().hex}"
        db = self._session_factory()
        try:
            with db.begin():
                user = self._user(db, username)
                thread = Thread(
                    user_id=user.id,
                    thread_id=thread_id,
                    kind="research",
                    status="active",
                    version=0,
                    message_count=0,
                    last_sequence=0,
                    metadata_json={"title": title, "research_project_id": project_id},
                    created_at=now,
                    updated_at=now,
                )
                db.add(thread)
                db.flush()
                project = ResearchProject(
                    id=project_id,
                    tenant_id=tenant_id,
                    user_id=user.id,
                    thread_ref_id=thread.id,
                    title=title.strip(),
                    objective=objective.strip(),
                    mode=mode,
                    lifecycle_status="draft",
                    source_config_json={"sources": sources},
                    output_format_json={"formats": output_formats},
                    current_plan_version=None,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                db.add(project)
                db.flush()
                return self._project_view(db, project, thread)
        finally:
            db.close()

    def list_projects(
        self, *, username: str, tenant_id: str
    ) -> list[ResearchProjectV1]:
        db = self._session_factory()
        try:
            rows = (
                db.query(ResearchProject, Thread)
                .join(Thread, Thread.id == ResearchProject.thread_ref_id)
                .join(User, User.id == ResearchProject.user_id)
                .filter(
                    ResearchProject.tenant_id == tenant_id,
                    ResearchProject.deleted_at.is_(None),
                    User.username == username,
                )
                .order_by(ResearchProject.updated_at.desc())
                .all()
            )
            return [self._project_view(db, project, thread) for project, thread in rows]
        finally:
            db.close()

    def get_project(
        self, *, username: str, tenant_id: str, project_id: str
    ) -> ResearchProjectV1:
        db = self._session_factory()
        try:
            project, thread, _ = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            return self._project_view(db, project, thread)
        finally:
            db.close()

    def write_plan(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        expected_project_version: int,
        steps: list[ResearchPlanStepV1],
        origin: str,
    ) -> ResearchPlanV1:
        db = self._session_factory()
        try:
            with db.begin():
                project, _thread, user = self._owned_project(
                    db,
                    username=username,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    lock=True,
                )
                if project.lifecycle_status not in {"draft", "awaiting_approval"}:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "已审批计划不可修改",
                        status_code=409,
                    )
                if project.version != expected_project_version:
                    raise AppError(
                        ErrorCode.THREAD_VERSION_CONFLICT,
                        "Research Project 版本已变化",
                        status_code=409,
                        safe_details={"current_version": project.version},
                    )
                profile = resolve_research_profile(project.mode)
                if len(steps) > profile["max_steps"]:
                    raise AppError(
                        ErrorCode.INVALID_REQUEST,
                        f"{project.mode} 模式要求 {profile['min_steps']}-{profile['max_steps']} 个步骤",
                        status_code=400,
                    )
                bounded = self._validate_plan_steps(steps, profile, status_code=400)
                version = int(project.current_plan_version or 0) + 1
                row = ResearchPlan(
                    id=f"rplan_{uuid4().hex}",
                    project_id=project.id,
                    version=version,
                    plan_json={
                        "objective": project.objective,
                        "steps": [step.model_dump(mode="json") for step in bounded],
                    },
                    origin=origin,
                    created_by_user_id=user.id,
                    created_at=utcnow(),
                )
                db.add(row)
                project.current_plan_version = version
                project.lifecycle_status = "awaiting_approval"
                project.version += 1
                project.updated_at = utcnow()
                db.flush()
                return self._plan_view(row)
        finally:
            db.close()

    def get_plan(
        self, *, username: str, tenant_id: str, project_id: str
    ) -> ResearchPlanV1:
        db = self._session_factory()
        try:
            project, _thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            if project.current_plan_version is None:
                raise AppError(
                    ErrorCode.NOT_FOUND, "Research Plan 不存在", status_code=404
                )
            row = (
                db.query(ResearchPlan)
                .filter(
                    ResearchPlan.project_id == project.id,
                    ResearchPlan.version == project.current_plan_version,
                )
                .one()
            )
            return self._plan_view(row)
        finally:
            db.close()

    def create_plan_job(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        idempotency_key: str,
        expected_project_version: int,
        model_snapshot: ModelCatalogSnapshot,
    ) -> PlanJobRecord:
        db = self._session_factory()
        try:
            with db.begin():
                project, _thread, _user = self._owned_project(
                    db,
                    username=username,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    lock=True,
                )
                existing = (
                    db.query(ResearchPlanJob)
                    .filter(
                        ResearchPlanJob.project_id == project.id,
                        ResearchPlanJob.idempotency_key == idempotency_key,
                    )
                    .first()
                )
                if existing:
                    return self._job_view(existing)
                if project.lifecycle_status == "frozen":
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "已审批项目不能生成新计划",
                        status_code=409,
                    )
                if project.version != expected_project_version:
                    raise AppError(
                        ErrorCode.THREAD_VERSION_CONFLICT,
                        "Research Project 版本已变化",
                        status_code=409,
                    )
                active = (
                    db.query(ResearchPlanJob.id)
                    .filter(
                        ResearchPlanJob.project_id == project.id,
                        ResearchPlanJob.status.in_(
                            ("pending", "running", "cancelling")
                        ),
                    )
                    .first()
                )
                if active:
                    raise AppError(
                        ErrorCode.RUN_ACTIVE, "已有活跃 Plan Job", status_code=409
                    )
                now = utcnow()
                job = ResearchPlanJob(
                    id=f"rpjob_{uuid4().hex}",
                    project_id=project.id,
                    idempotency_key=idempotency_key,
                    project_version=project.version,
                    status="pending",
                    model_catalog_hash=model_snapshot.catalog_hash,
                    model_snapshot_json=model_snapshot.model_dump(mode="json"),
                    fencing_token=0,
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
                db.add(job)
                db.flush()
                return self._job_view(job)
        finally:
            db.close()

    def get_plan_job(
        self, *, username: str, tenant_id: str, project_id: str, job_id: str
    ) -> PlanJobRecord:
        db = self._session_factory()
        try:
            project, _thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            row = (
                db.query(ResearchPlanJob)
                .filter(
                    ResearchPlanJob.id == job_id,
                    ResearchPlanJob.project_id == project.id,
                )
                .first()
            )
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND, "Plan Job 不存在", status_code=404)
            return self._job_view(row)
        finally:
            db.close()

    def cancel_plan_job(
        self, *, username: str, tenant_id: str, project_id: str, job_id: str
    ) -> PlanJobRecord:
        db = self._session_factory()
        try:
            with db.begin():
                project, _thread, _user = self._owned_project(
                    db, username=username, tenant_id=tenant_id, project_id=project_id
                )
                row = (
                    db.query(ResearchPlanJob)
                    .filter(
                        ResearchPlanJob.id == job_id,
                        ResearchPlanJob.project_id == project.id,
                    )
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise AppError(
                        ErrorCode.NOT_FOUND, "Plan Job 不存在", status_code=404
                    )
                if row.status == "pending":
                    row.status = "cancelled"
                    row.finished_at = utcnow()
                elif row.status == "running":
                    row.status = "cancelling"
                row.updated_at = utcnow()
                return self._job_view(row)
        finally:
            db.close()

    def claim_plan_job(
        self, *, worker_id: str, lease_seconds: int
    ) -> tuple[PlanJobRecord, str, str, str, list[str], dict] | None:
        db = self._session_factory()
        try:
            with db.begin():
                now = utcnow()
                query = (
                    db.query(ResearchPlanJob, ResearchProject)
                    .join(
                        ResearchProject,
                        ResearchProject.id == ResearchPlanJob.project_id,
                    )
                    .filter(
                        ResearchProject.deleted_at.is_(None),
                        (
                            (ResearchPlanJob.status == "pending")
                            | (
                                (ResearchPlanJob.status == "running")
                                & (ResearchPlanJob.lease_expires_at < now)
                            )
                        ),
                    )
                    .order_by(ResearchPlanJob.created_at.asc())
                )
                if db.get_bind().dialect.name == "postgresql":
                    query = query.with_for_update(skip_locked=True, of=ResearchPlanJob)
                row = query.first()
                if row is None:
                    return None
                job, project = row
                job.status = "running"
                job.owner_worker_id = worker_id
                job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                job.heartbeat_at = now
                job.fencing_token += 1
                job.attempts += 1
                job.started_at = job.started_at or now
                job.updated_at = now
                db.flush()
                return (
                    self._job_view(job),
                    project.title,
                    project.objective,
                    project.mode,
                    list(
                        (project.source_config_json or {}).get("sources")
                        or ["knowledge_base"]
                    ),
                    dict(job.model_snapshot_json or {}),
                )
        finally:
            db.close()

    def plan_job_cancel_requested(self, job_id: str) -> bool:
        db = self._session_factory()
        try:
            status = (
                db.query(ResearchPlanJob.status)
                .filter(ResearchPlanJob.id == job_id)
                .scalar()
            )
            return status in {"cancelling", "cancelled"}
        finally:
            db.close()

    def heartbeat_plan_job(
        self, *, job_id: str, worker_id: str, fencing_token: int, lease_seconds: int
    ) -> None:
        db = self._session_factory()
        try:
            with db.begin():
                now = utcnow()
                updated = (
                    db.query(ResearchPlanJob)
                    .filter(
                        ResearchPlanJob.id == job_id,
                        ResearchPlanJob.owner_worker_id == worker_id,
                        ResearchPlanJob.fencing_token == fencing_token,
                        ResearchPlanJob.status.in_(("running", "cancelling")),
                    )
                    .update(
                        {
                            ResearchPlanJob.heartbeat_at: now,
                            ResearchPlanJob.lease_expires_at: now
                            + timedelta(seconds=lease_seconds),
                            ResearchPlanJob.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                )
                if updated != 1:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "Plan Job ownership 已失效",
                        status_code=409,
                    )
        finally:
            db.close()

    def finish_plan_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        steps: list[ResearchPlanStepV1],
        usage_status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int = 0,
        error_code: str | None = None,
    ) -> None:
        db = self._session_factory()
        try:
            with db.begin():
                job = (
                    db.query(ResearchPlanJob)
                    .filter(
                        ResearchPlanJob.id == job_id,
                        ResearchPlanJob.owner_worker_id == worker_id,
                        ResearchPlanJob.fencing_token == fencing_token,
                    )
                    .with_for_update()
                    .first()
                )
                if job is None or job.status not in {"running", "cancelling"}:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "Plan Job ownership 已失效",
                        status_code=409,
                    )
                now = utcnow()
                db.add(
                    ResearchUsage(
                        id=f"rusage_{uuid4().hex}",
                        project_id=job.project_id,
                        run_id=None,
                        plan_job_id=job.id,
                        role="fast",
                        stage="planning",
                        attempt=job.attempts,
                        status=usage_status,
                        input_tokens=max(input_tokens, 0),
                        output_tokens=max(output_tokens, 0),
                        duration_ms=max(duration_ms, 0),
                        error_code=error_code,
                        created_at=now,
                    )
                )
                if job.status == "cancelling":
                    job.status = "cancelled"
                    job.finished_at = now
                    job.owner_worker_id = None
                    job.lease_expires_at = None
                    job.updated_at = now
                    return
                project = (
                    db.query(ResearchProject)
                    .filter(ResearchProject.id == job.project_id)
                    .with_for_update()
                    .one()
                )
                if (
                    project.version != job.project_version
                    or project.lifecycle_status == "frozen"
                ):
                    job.status = "failed"
                    job.error_code = "RESEARCH_PLAN_STALE"
                    job.finished_at = now
                    job.owner_worker_id = None
                    job.lease_expires_at = None
                    job.updated_at = now
                    return
                profile = resolve_research_profile(project.mode)
                bounded = self._validate_plan_steps(steps, profile, status_code=502)
                version = int(project.current_plan_version or 0) + 1
                plan = ResearchPlan(
                    id=f"rplan_{uuid4().hex}",
                    project_id=project.id,
                    version=version,
                    plan_json={
                        "objective": project.objective,
                        "steps": [step.model_dump(mode="json") for step in bounded],
                    },
                    origin="planner",
                    created_by_user_id=project.user_id,
                    created_at=now,
                )
                db.add(plan)
                db.flush()
                project.current_plan_version = version
                project.lifecycle_status = "awaiting_approval"
                project.version += 1
                project.updated_at = now
                job.status = "completed"
                job.result_plan_id = plan.id
                job.finished_at = now
                job.owner_worker_id = None
                job.lease_expires_at = None
                job.updated_at = now
        finally:
            db.close()

    def fail_plan_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        error_code: str,
        duration_ms: int,
    ) -> None:
        db = self._session_factory()
        try:
            with db.begin():
                job = (
                    db.query(ResearchPlanJob)
                    .filter(
                        ResearchPlanJob.id == job_id,
                        ResearchPlanJob.owner_worker_id == worker_id,
                        ResearchPlanJob.fencing_token == fencing_token,
                    )
                    .with_for_update()
                    .first()
                )
                if job is None:
                    return
                now = utcnow()
                db.add(
                    ResearchUsage(
                        id=f"rusage_{uuid4().hex}",
                        project_id=job.project_id,
                        run_id=None,
                        plan_job_id=job.id,
                        role="fast",
                        stage="planning",
                        attempt=job.attempts,
                        status="failed",
                        input_tokens=0,
                        output_tokens=0,
                        duration_ms=max(duration_ms, 0),
                        error_code=error_code,
                        created_at=now,
                    )
                )
                job.status = "cancelled" if job.status == "cancelling" else "failed"
                job.error_code = error_code
                job.error_detail_redacted = "计划生成失败，请重试。"
                job.finished_at = now
                job.owner_worker_id = None
                job.lease_expires_at = None
                job.updated_at = now
        finally:
            db.close()

    def approve(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        expected_project_version: int,
        idempotency_key: str,
        model_snapshot: ModelCatalogSnapshot,
        allow_frozen: bool = False,
    ) -> ApprovalRecord:
        db = self._session_factory()
        try:
            with db.begin():
                project, thread, user = self._owned_project(
                    db,
                    username=username,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    lock=True,
                )
                existing = (
                    db.query(Run)
                    .filter(
                        Run.thread_ref_id == thread.id,
                        Run.idempotency_key == idempotency_key,
                        Run.channel == "research",
                    )
                    .first()
                )
                if existing:
                    return ApprovalRecord(
                        self._project_view(db, project, thread),
                        existing.id,
                        thread.version,
                    )
                allowed_lifecycle = (
                    {"awaiting_approval", "frozen"}
                    if allow_frozen
                    else {"awaiting_approval"}
                )
                if (
                    project.lifecycle_status not in allowed_lifecycle
                    or project.current_plan_version is None
                ):
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "项目没有可审批计划",
                        status_code=409,
                    )
                if project.version != expected_project_version:
                    raise AppError(
                        ErrorCode.THREAD_VERSION_CONFLICT,
                        "Research Project 版本已变化",
                        status_code=409,
                    )
                if (
                    db.query(Run.id)
                    .filter(
                        Run.thread_ref_id == thread.id,
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .first()
                ):
                    raise AppError(
                        ErrorCode.RUN_ACTIVE, "该项目已有活跃 Run", status_code=409
                    )
                plan = (
                    db.query(ResearchPlan)
                    .filter(
                        ResearchPlan.project_id == project.id,
                        ResearchPlan.version == project.current_plan_version,
                    )
                    .one()
                )
                attachments = (
                    db.query(ResearchAttachment)
                    .filter(ResearchAttachment.project_id == project.id)
                    .all()
                )
                incomplete = [row.id for row in attachments if row.status != "indexed"]
                if incomplete:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "附件尚未完成索引",
                        status_code=409,
                        safe_details={"attachment_ids": incomplete},
                    )
                profile = resolve_research_profile(project.mode)
                selected_sources = list(
                    (project.source_config_json or {}).get("sources") or []
                )
                frozen_plan = {
                    **dict(plan.plan_json or {}),
                    "steps": [
                        {**dict(step), "sources": selected_sources}
                        for step in (plan.plan_json or {}).get("steps", [])
                    ],
                }
                manifest = {
                    "schema_version": 1,
                    "project_id": project.id,
                    "plan_id": plan.id,
                    "plan": frozen_plan,
                    "profile": profile,
                    "sources": project.source_config_json,
                    "output": project.output_format_json,
                    "attachment_versions": [row.version_key for row in attachments],
                    "prompt_version": "research-prompts-v1",
                    "workflow_version": "research-workflow-v1",
                    "model_catalog_hash": model_snapshot.catalog_hash,
                }
                encoded = json.dumps(
                    manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                manifest_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
                now = utcnow()
                run_id = f"run_{uuid4().hex}"
                run = Run(
                    id=run_id,
                    thread_ref_id=thread.id,
                    user_id=user.id,
                    tenant_id=tenant_id,
                    channel="research",
                    approved_tools_json=[],
                    status=RunStatus.PENDING.value,
                    idempotency_key=idempotency_key,
                    request_hash=manifest_hash,
                    model_name=model_snapshot.require("answer").model_name,
                    model_catalog_hash=model_snapshot.catalog_hash,
                    model_snapshot_json=model_snapshot.model_dump(mode="json"),
                    on_disconnect="continue",
                    multitask_strategy="reject",
                    fencing_token=1,
                    deadline_at=now
                    + timedelta(seconds=profile["writing_budget_seconds"]),
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
                    content=project.objective,
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
                db.add(
                    ResearchRunManifest(
                        run_id=run.id,
                        project_id=project.id,
                        plan_id=plan.id,
                        manifest_json=manifest,
                        manifest_hash=manifest_hash,
                        created_at=now,
                    )
                )
                project.lifecycle_status = "frozen"
                project.version += 1
                project.updated_at = now
                append_event_in_session(
                    db,
                    run=run,
                    thread_id=thread.thread_id,
                    event_type=RunEventType.RUN_CREATED,
                    data={
                        "status": run.status,
                        "user_message_id": human.id,
                        "assistant_message_id": assistant.id,
                        "multitask_strategy": "reject",
                    },
                )
                db.flush()
                return ApprovalRecord(
                    self._project_view(db, project, thread), run.id, thread.version
                )
        finally:
            db.close()

    def list_runs(
        self, *, username: str, tenant_id: str, project_id: str
    ) -> list[dict]:
        db = self._session_factory()
        try:
            project, thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            rows = (
                db.query(Run)
                .filter(Run.thread_ref_id == thread.id, Run.channel == "research")
                .order_by(Run.created_at.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "status": row.status,
                    "error_code": row.error_code,
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "created_at": row.created_at.isoformat(),
                    "finished_at": row.finished_at.isoformat()
                    if row.finished_at
                    else None,
                    "project_id": project.id,
                }
                for row in rows
            ]
        finally:
            db.close()

    def list_evidence(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        run_id: str | None = None,
    ) -> list[dict]:
        db = self._session_factory()
        try:
            _project, thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            target = run_id or getattr(self._latest_run(db, thread.id), "id", None)
            if target is None:
                return []
            if (
                not db.query(Run.id)
                .filter(Run.id == target, Run.thread_ref_id == thread.id)
                .first()
            ):
                raise AppError(
                    ErrorCode.NOT_FOUND, "Research Run 不存在", status_code=404
                )
            rows = (
                db.query(ResearchEvidence)
                .filter(ResearchEvidence.run_id == target)
                .order_by(ResearchEvidence.citation_number.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "citation": f"E{row.citation_number}",
                    "source_kind": row.source_kind,
                    "title": row.title,
                    "content": row.content,
                    "source_uri": row.source_uri,
                    "domain": row.domain,
                    "quality_score": float(row.quality_score),
                    "captured_at": row.captured_at.isoformat(),
                }
                for row in rows
            ]
        finally:
            db.close()

    def list_steps(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        run_id: str | None = None,
    ) -> list[dict]:
        db = self._session_factory()
        try:
            _project, thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            target = run_id or getattr(self._latest_run(db, thread.id), "id", None)
            if target is None:
                return []
            if (
                not db.query(Run.id)
                .filter(Run.id == target, Run.thread_ref_id == thread.id)
                .first()
            ):
                raise AppError(
                    ErrorCode.NOT_FOUND, "Research Run 不存在", status_code=404
                )
            rows = (
                db.query(ResearchStep)
                .filter(ResearchStep.run_id == target)
                .order_by(ResearchStep.position.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "step_key": row.step_key,
                    "position": row.position,
                    "status": row.status,
                    "evidence_count": int(
                        (row.detail_json or {}).get("evidence_count", 0)
                    ),
                    "evidence_ids": [
                        value
                        for value in (row.detail_json or {}).get("evidence_ids", [])
                        if isinstance(value, str)
                    ],
                    "source_stats": dict(
                        (row.detail_json or {}).get("source_stats") or {}
                    ),
                    "started_at": _utc_isoformat(row.started_at)
                    if row.started_at
                    else None,
                    "finished_at": _utc_isoformat(row.finished_at)
                    if row.finished_at
                    else None,
                    "updated_at": _utc_isoformat(row.updated_at),
                }
                for row in rows
            ]
        finally:
            db.close()

    def list_sections(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        run_id: str | None = None,
    ) -> list[dict]:
        db = self._session_factory()
        try:
            _project, thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            target = run_id or getattr(self._latest_run(db, thread.id), "id", None)
            if target is None:
                return []
            if (
                not db.query(Run.id)
                .filter(Run.id == target, Run.thread_ref_id == thread.id)
                .first()
            ):
                raise AppError(
                    ErrorCode.NOT_FOUND, "Research Run 不存在", status_code=404
                )
            rows = (
                db.query(ResearchSection)
                .filter(ResearchSection.run_id == target)
                .order_by(ResearchSection.position.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "section_key": row.section_key,
                    "position": row.position,
                    "title": row.title,
                    "status": row.status,
                    "content_markdown": row.content_markdown,
                    "evidence_ids": list(row.evidence_ids_json or []),
                    "revision_count": row.revision_count,
                }
                for row in rows
            ]
        finally:
            db.close()

    def list_claims(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        run_id: str | None = None,
    ) -> list[dict]:
        db = self._session_factory()
        try:
            _project, thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            target = run_id or getattr(self._latest_run(db, thread.id), "id", None)
            if target is None:
                return []
            if (
                not db.query(Run.id)
                .filter(Run.id == target, Run.thread_ref_id == thread.id)
                .first()
            ):
                raise AppError(
                    ErrorCode.NOT_FOUND, "Research Run 不存在", status_code=404
                )
            rows = (
                db.query(ResearchClaim)
                .filter(ResearchClaim.run_id == target)
                .order_by(ResearchClaim.created_at.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "claim_key": row.claim_key,
                    "text": row.text,
                    "verdict": row.verdict,
                    "reason": row.reason,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        finally:
            db.close()

    def list_artifacts(
        self, *, username: str, tenant_id: str, project_id: str
    ) -> list[dict]:
        db = self._session_factory()
        try:
            project, _thread, user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            rows = (
                db.query(Artifact)
                .filter(
                    Artifact.tenant_id == tenant_id,
                    Artifact.user_id == user.id,
                    Artifact.owner_type == "research_project",
                    Artifact.owner_id == project.id,
                )
                .order_by(Artifact.created_at.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "logical_type": row.logical_type,
                    "state": row.state,
                    "version": row.version,
                    "parent_artifact_id": row.parent_artifact_id,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "media_type": row.media_type,
                    "filename": row.filename,
                    "created_at": row.created_at.isoformat(),
                    "download_url": f"/api/artifacts/{row.id}",
                }
                for row in rows
            ]
        finally:
            db.close()

    def metrics(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        run_id: str | None = None,
    ) -> dict:
        db = self._session_factory()
        try:
            project, thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            run_ids = [
                row[0]
                for row in db.query(Run.id)
                .filter(Run.thread_ref_id == thread.id, Run.channel == "research")
                .all()
            ]
            if run_id is not None:
                if run_id not in run_ids:
                    raise AppError(
                        ErrorCode.NOT_FOUND, "Research Run 不存在", status_code=404
                    )
                run_ids = [run_id]
            usage = (
                db.query(
                    func.coalesce(func.sum(ResearchUsage.input_tokens), 0),
                    func.coalesce(func.sum(ResearchUsage.output_tokens), 0),
                    func.count(ResearchUsage.id),
                    func.coalesce(func.sum(ResearchUsage.duration_ms), 0),
                )
                .filter(ResearchUsage.project_id == project.id)
                .filter(ResearchUsage.run_id.in_(run_ids) if run_id else True)
                .one()
            )
            run = None
            if run_id is not None:
                run = db.query(Run).filter(Run.id == run_id).one()
            now = utcnow()
            elapsed_ms = 0
            if run is not None and run.started_at is not None:
                elapsed_ms = max(
                    0,
                    int(
                        ((run.finished_at or now) - run.started_at).total_seconds()
                        * 1000
                    ),
                )
            return {
                "run_count": len(run_ids),
                "evidence_count": db.query(func.count(ResearchEvidence.id))
                .filter(ResearchEvidence.run_id.in_(run_ids))
                .scalar()
                if run_ids
                else 0,
                "claim_count": db.query(func.count(ResearchClaim.id))
                .filter(ResearchClaim.run_id.in_(run_ids))
                .scalar()
                if run_ids
                else 0,
                "section_count": db.query(func.count(ResearchSection.id))
                .filter(ResearchSection.run_id.in_(run_ids))
                .scalar()
                if run_ids
                else 0,
                "input_tokens": int(usage[0]),
                "output_tokens": int(usage[1]),
                "model_calls": int(usage[2]),
                "duration_ms": int(usage[3]),
                "elapsed_ms": elapsed_ms,
            }
        finally:
            db.close()

    def clone_project(
        self, *, username: str, tenant_id: str, project_id: str
    ) -> ResearchProjectV1:
        db = self._session_factory()
        try:
            project, _thread, _user = self._owned_project(
                db, username=username, tenant_id=tenant_id, project_id=project_id
            )
            return self.create_project(
                username=username,
                tenant_id=tenant_id,
                title=f"{project.title}（副本）",
                objective=project.objective,
                mode=project.mode,
                sources=list((project.source_config_json or {}).get("sources") or []),
                output_formats=list(
                    (project.output_format_json or {}).get("formats") or ["markdown"]
                ),
            )
        finally:
            db.close()

    def soft_delete(self, *, username: str, tenant_id: str, project_id: str) -> None:
        db = self._session_factory()
        try:
            with db.begin():
                project, thread, _user = self._owned_project(
                    db,
                    username=username,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    lock=True,
                )
                if (
                    db.query(Run.id)
                    .filter(
                        Run.thread_ref_id == thread.id,
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .first()
                ):
                    raise AppError(
                        ErrorCode.RUN_ACTIVE, "项目仍有活跃 Run", status_code=409
                    )
                project.deleted_at = utcnow()
                project.version += 1
                thread.status = "archived"
        finally:
            db.close()


research_repository = ResearchRepository()
