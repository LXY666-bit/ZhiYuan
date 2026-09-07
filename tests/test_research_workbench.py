from __future__ import annotations

import asyncio
import tempfile
import hashlib
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.artifacts.service import ArtifactService
from backend.core.errors import AppError
from backend.db.models import (
    Artifact,
    Base,
    ResearchRunManifest,
    ResearchStep,
    ResearchPlanJob,
    ResearchUsage,
    Run,
    RunCheckpoint,
    Thread,
    User,
    utcnow,
)
from backend.model_control import (
    ModelRole,
    ModelRuntimeSpec,
    build_model_catalog_snapshot,
)
from backend.research.generated.research_api_v1 import ResearchPlanStepV1
from backend.research.attachments import AttachmentBuild, ResearchAttachmentIndexer
from backend.research.artifact_revision import ResearchArtifactRevisionService
from backend.research.planner import ResearchPlanner
from backend.research.profiles import resolve_research_profile
from backend.research.query_policy import (
    build_web_query,
    filter_objective_evidence,
    resolve_research_target,
)
from backend.research.repository import ResearchRepository
from backend.research.source_quality import rank_web_evidence
from backend.research.workflow import ResearchWorkflowRunner
from backend.runs.repository import RunRepository
from backend.threads.repository import ThreadRepository
from backend.web_research.runtime import build_web_research_runtime
from backend.core.settings import get_settings


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(User(username="alice", password_hash="unused", role="user"))
        db.add(User(username="bob", password_hash="unused", role="admin"))
    return factory


def _snapshot():
    assignments = {}
    for role in (ModelRole.ANSWER, ModelRole.FAST, ModelRole.GRADER):
        assignments[role] = ModelRuntimeSpec(
            profile_id="model_" + hashlib.sha256(role.value.encode()).hexdigest()[:32],
            profile_version=1,
            display_name=role.value,
            model_name=f"test-{role.value}",
            timeout_seconds=30,
            supports_stream=True,
            supports_structured_output=True,
        )
    return build_model_catalog_snapshot(assignments)


def _steps():
    return [
        ResearchPlanStepV1(
            step_key="step-1",
            title="事实",
            question="核验知渊的核心事实",
            sources=["knowledge_base"],
        ),
        ResearchPlanStepV1(
            step_key="step-2",
            title="结论",
            question="总结知渊的限制",
            sources=["knowledge_base"],
        ),
    ]


def test_project_plan_approval_is_one_atomic_canonical_run(session_factory):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="知渊调研",
        objective="研究知渊",
        mode="quick",
        sources=["knowledge_base", "web"],
        output_formats=["markdown"],
    )
    assert project.lifecycle_status == "draft"
    plan = repository.write_plan(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=project.version,
        steps=_steps(),
        origin="user",
    )
    awaiting = repository.get_project(
        username="alice", tenant_id="default", project_id=project.id
    )
    approved = repository.approve(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=awaiting.version,
        idempotency_key="approve-v1",
        model_snapshot=_snapshot(),
    )
    repeated = repository.approve(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=awaiting.version,
        idempotency_key="approve-v1",
        model_snapshot=_snapshot(),
    )
    assert approved.run_id == repeated.run_id
    assert approved.project.lifecycle_status == "frozen"
    with session_factory() as db:
        run = db.query(Run).filter(Run.id == approved.run_id).one()
        thread = db.query(Thread).filter(Thread.id == run.thread_ref_id).one()
        manifest = (
            db.query(ResearchRunManifest)
            .filter(ResearchRunManifest.run_id == run.id)
            .one()
        )
        assert run.channel == "research"
        assert thread.kind == "research"
        assert manifest.plan_id == plan.id
        assert manifest.manifest_json["profile"]["mode"] == "quick"
        assert [
            step["sources"] for step in manifest.manifest_json["plan"]["steps"]
        ] == [["knowledge_base", "web"], ["knowledge_base", "web"]]
        assert run.last_event_sequence == 1


def test_plan_rejects_duplicate_research_directions(session_factory):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="重复方向",
        objective="比较 pgvector、Milvus 和 Qdrant",
        mode="quick",
        sources=["web"],
        output_formats=["markdown"],
    )
    repeated = "研究对象：pgvector、Milvus 和 Qdrant"
    with pytest.raises(AppError) as raised:
        repository.write_plan(
            username="alice",
            tenant_id="default",
            project_id=project.id,
            expected_project_version=project.version,
            steps=[
                ResearchPlanStepV1(
                    step_key="step-1",
                    title="性能",
                    question=repeated,
                    sources=["web"],
                ),
                ResearchPlanStepV1(
                    step_key="step-2",
                    title="成本",
                    question=repeated,
                    sources=["web"],
                ),
            ],
            origin="user",
        )

    assert raised.value.code == "INVALID_REQUEST"
    assert "重复问题" in raised.value.message


def test_research_threads_are_hidden_from_chat_list(session_factory):
    repository = ResearchRepository(session_factory)
    repository.create_project(
        username="alice",
        tenant_id="default",
        title="研究",
        objective="研究对象",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    threads = ThreadRepository(session_factory)
    threads.create_thread(username="alice", thread_id="chat-visible", title="聊天")
    assert [item.thread_id for item in threads.list_thread_summaries("alice")] == [
        "chat-visible"
    ]


def test_controlled_shutdown_requeues_same_research_run_only_with_checkpoint(
    session_factory,
):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="恢复测试",
        objective="验证同一个 canonical Run 恢复",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    repository.write_plan(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=project.version,
        steps=_steps(),
        origin="user",
    )
    current = repository.get_project(
        username="alice", tenant_id="default", project_id=project.id
    )
    approved = repository.approve(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=current.version,
        idempotency_key="recover-v1",
        model_snapshot=_snapshot(),
    )
    with session_factory.begin() as db:
        run = db.query(Run).filter(Run.id == approved.run_id).one()
        run.status = "running"
        run.owner_worker_id = "worker-a"
        run.fencing_token = 3
        db.add(
            RunCheckpoint(
                run_id=run.id,
                thread_ref_id=run.thread_ref_id,
                user_id=run.user_id,
                checkpoint_id=f"{run.id}:research",
                state_json={"thread_id": run.id, "stage": "sections"},
                next_nodes_json=["write_sections"],
            )
        )

    released = RunRepository(session_factory).release_research_for_recovery(
        run_id=approved.run_id,
        worker_id="worker-a",
        fencing_token=3,
    )
    assert released.id == approved.run_id
    assert released.status == "pending"
    with session_factory() as db:
        run = db.query(Run).filter(Run.id == approved.run_id).one()
        assert run.owner_worker_id is None
        assert run.lease_expires_at is None


def test_orphan_recovery_resumes_checkpoint_and_interrupts_legacy_run(session_factory):
    research = ResearchRepository(session_factory)
    approved_runs = []
    for suffix in ("recoverable", "legacy"):
        project = research.create_project(
            username="alice",
            tenant_id="default",
            title=f"恢复测试 {suffix}",
            objective=f"验证 {suffix} Research Run",
            mode="quick",
            sources=["knowledge_base"],
            output_formats=["markdown"],
        )
        research.write_plan(
            username="alice",
            tenant_id="default",
            project_id=project.id,
            expected_project_version=project.version,
            steps=_steps(),
            origin="user",
        )
        current = research.get_project(
            username="alice", tenant_id="default", project_id=project.id
        )
        approved_runs.append(
            research.approve(
                username="alice",
                tenant_id="default",
                project_id=project.id,
                expected_project_version=current.version,
                idempotency_key=f"orphan-{suffix}",
                model_snapshot=_snapshot(),
            ).run_id
        )
    now = utcnow()
    with session_factory.begin() as db:
        rows = db.query(Run).filter(Run.id.in_(approved_runs)).all()
        for index, run in enumerate(rows, 1):
            run.status = "running"
            run.owner_worker_id = f"dead-worker-{index}"
            run.fencing_token = index
            run.lease_expires_at = now - timedelta(seconds=1)
        recoverable = next(row for row in rows if row.id == approved_runs[0])
        db.add(
            RunCheckpoint(
                run_id=recoverable.id,
                thread_ref_id=recoverable.thread_ref_id,
                user_id=recoverable.user_id,
                checkpoint_id=f"{recoverable.id}:research",
                state_json={"thread_id": recoverable.id, "stage": "sections"},
                next_nodes_json=["write_sections"],
            )
        )

    recovered = RunRepository(session_factory).reconcile_orphans(now=now)
    assert set(recovered) == set(approved_runs)
    with session_factory() as db:
        resumed = db.query(Run).filter(Run.id == approved_runs[0]).one()
        interrupted = db.query(Run).filter(Run.id == approved_runs[1]).one()
        assert resumed.status == "pending"
        assert resumed.owner_worker_id is None
        assert interrupted.status == "failed"
        assert interrupted.error_code == "RUN_INTERRUPTED"


def test_project_ownership_is_not_bypassed_by_admin_role(session_factory):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="研究",
        objective="研究对象",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    with pytest.raises(AppError) as raised:
        repository.get_project(
            username="bob", tenant_id="default", project_id=project.id
        )
    assert raised.value.status_code == 404


def test_run_metrics_and_steps_are_scoped_to_the_selected_research_run(session_factory):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="运行可观测性",
        objective="展示研究步骤和本次运行用量",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    repository.write_plan(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=project.version,
        steps=_steps(),
        origin="user",
    )
    current = repository.get_project(
        username="alice", tenant_id="default", project_id=project.id
    )
    approved = repository.approve(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=current.version,
        idempotency_key="observable-run",
        model_snapshot=_snapshot(),
    )
    now = utcnow()
    with session_factory.begin() as db:
        run = db.query(Run).filter(Run.id == approved.run_id).one()
        run.status = "succeeded"
        run.started_at = now - timedelta(seconds=4)
        run.finished_at = now
        db.add(
            ResearchStep(
                id="rstep_observable",
                run_id=run.id,
                step_key="step-1",
                position=1,
                status="completed",
                detail_json={
                    "evidence_count": 3,
                    "evidence_ids": ["rev_1", "rev_2", "rev_3"],
                },
                started_at=run.started_at,
                finished_at=now,
                updated_at=now,
            )
        )
        db.add(
            ResearchUsage(
                id="rusage_observable",
                project_id=project.id,
                run_id=run.id,
                plan_job_id=None,
                role="answer",
                stage="writer:step-1",
                attempt=1,
                status="completed",
                input_tokens=120,
                output_tokens=45,
                duration_ms=3200,
                error_code=None,
                created_at=now,
            )
        )
    steps = repository.list_steps(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        run_id=approved.run_id,
    )
    metrics = repository.metrics(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        run_id=approved.run_id,
    )
    run_record = RunRepository(session_factory).get(
        username="alice", run_id=approved.run_id
    )
    assert steps == [
        {
            "id": "rstep_observable",
            "run_id": approved.run_id,
            "step_key": "step-1",
            "position": 1,
            "status": "completed",
            "evidence_count": 3,
            "evidence_ids": ["rev_1", "rev_2", "rev_3"],
            "source_stats": {},
            "started_at": f"{(now - timedelta(seconds=4)).isoformat()}Z",
            "finished_at": f"{now.isoformat()}Z",
            "updated_at": f"{now.isoformat()}Z",
        }
    ]
    assert run_record.started_at == f"{(now - timedelta(seconds=4)).isoformat()}Z"
    assert run_record.finished_at == f"{now.isoformat()}Z"
    assert metrics["input_tokens"] == 120
    assert metrics["output_tokens"] == 45
    assert metrics["model_calls"] == 1
    assert metrics["duration_ms"] == 3200
    assert metrics["elapsed_ms"] >= 4000


def test_artifact_draft_is_atomic_singleton_and_download_is_owned(session_factory):
    with tempfile.TemporaryDirectory() as directory:
        service = ArtifactService(session_factory, root=Path(directory))
        first = service.write(
            tenant_id="default",
            user_id=1,
            owner_type="research_project",
            owner_id="rproj_owner",
            logical_type="report_markdown",
            state="draft",
            content=b"first",
            media_type="text/markdown",
            filename="report.md",
            run_id=None,
        )
        second = service.write(
            tenant_id="default",
            user_id=1,
            owner_type="research_project",
            owner_id="rproj_owner",
            logical_type="report_markdown",
            state="draft",
            content=b"second",
            media_type="text/markdown",
            filename="report.md",
            run_id=None,
        )
        assert first.id == second.id
        record, path = service.get_owned(
            username="alice", tenant_id="default", artifact_id=first.id
        )
        assert path.read_bytes() == b"second"
        assert record.sha256 != first.sha256
        with pytest.raises(AppError) as raised:
            service.get_owned(username="bob", tenant_id="default", artifact_id=first.id)
        assert raised.value.status_code == 404
        with session_factory() as db:
            assert db.query(Artifact).count() == 1


def test_artifact_final_versions_form_parent_chain_and_reject_traversal(
    session_factory,
):
    with tempfile.TemporaryDirectory() as directory:
        service = ArtifactService(session_factory, root=Path(directory))
        first = service.write(
            tenant_id="default",
            user_id=1,
            owner_type="research_project",
            owner_id="rproj_owner",
            logical_type="report_markdown",
            state="final",
            content=b"v1",
            media_type="text/markdown",
            filename="report.md",
        )
        second = service.write(
            tenant_id="default",
            user_id=1,
            owner_type="research_project",
            owner_id="rproj_owner",
            logical_type="report_markdown",
            state="final",
            content=b"v2",
            media_type="text/markdown",
            filename="report.md",
        )
        assert second.version == 2
        assert second.parent_artifact_id == first.id
        with pytest.raises(AppError):
            service.read_storage_key("../outside.md")


def test_markdown_edit_explicitly_rebuilds_pdf_for_markdown_only_project(
    session_factory, tmp_path
):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="Artifact 编辑",
        objective="验证 Markdown 与 PDF 版本链",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    repository.write_plan(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=project.version,
        steps=_steps(),
        origin="user",
    )
    current = repository.get_project(
        username="alice", tenant_id="default", project_id=project.id
    )
    repository.approve(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=current.version,
        idempotency_key="artifact-edit-run",
        model_snapshot=_snapshot(),
    )
    artifacts = ArtifactService(session_factory, root=tmp_path)
    initial_markdown = artifacts.write(
        tenant_id="default",
        user_id=1,
        owner_type="research_project",
        owner_id=project.id,
        logical_type="report_markdown",
        state="final",
        content=b"# v1",
        media_type="text/markdown",
        filename="research-report.md",
    )
    initial_pdf = artifacts.write(
        tenant_id="default",
        user_id=1,
        owner_type="research_project",
        owner_id=project.id,
        logical_type="report_pdf",
        state="final",
        content=b"%PDF-v1",
        media_type="application/pdf",
        filename="research-report.pdf",
    )
    created = ResearchArtifactRevisionService(
        session_factory=session_factory, artifacts=artifacts
    ).revise_markdown(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        markdown="# v2\n\n编辑后的研究报告 [E1]。",
        rebuild_pdf=True,
    )
    by_type = {row["logical_type"]: row for row in created}
    assert by_type["report_markdown"]["version"] == 2
    assert by_type["report_markdown"]["parent_artifact_id"] == initial_markdown.id
    assert by_type["report_pdf"]["version"] == 2
    assert by_type["report_pdf"]["parent_artifact_id"] == initial_pdf.id
    assert by_type["report_pdf"]["size_bytes"] > len(b"%PDF-v1")


def test_research_artifact_delete_requires_ownership_and_preserves_version_chain(
    session_factory, tmp_path
):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="交付物删除",
        objective="验证交付物删除边界",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    repository.write_plan(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=project.version,
        steps=_steps(),
        origin="user",
    )
    current = repository.get_project(
        username="alice", tenant_id="default", project_id=project.id
    )
    approved = repository.approve(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        expected_project_version=current.version,
        idempotency_key="artifact-delete-run",
        model_snapshot=_snapshot(),
    )
    artifacts = ArtifactService(session_factory, root=tmp_path)
    revisions = ResearchArtifactRevisionService(
        session_factory=session_factory, artifacts=artifacts
    )
    running = artifacts.write(
        tenant_id="default",
        user_id=1,
        owner_type="research_project",
        owner_id=project.id,
        logical_type="report_markdown",
        state="draft",
        content=b"draft",
        media_type="text/markdown",
        filename="research-report.md",
        run_id=approved.run_id,
    )
    with pytest.raises(AppError) as active:
        revisions.delete_artifact(
            username="alice",
            tenant_id="default",
            project_id=project.id,
            artifact_id=running.id,
        )
    assert active.value.code == "RUN_ACTIVE"

    with session_factory.begin() as db:
        db.query(Run).filter(Run.id == approved.run_id).one().status = "succeeded"
    _record, running_path = artifacts.get_owned(
        username="alice", tenant_id="default", artifact_id=running.id
    )
    revisions.delete_artifact(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        artifact_id=running.id,
    )
    assert not running_path.exists()

    first = artifacts.write(
        tenant_id="default",
        user_id=1,
        owner_type="research_project",
        owner_id=project.id,
        logical_type="report_markdown",
        state="final",
        content=b"v1",
        media_type="text/markdown",
        filename="research-report.md",
    )
    second = artifacts.write(
        tenant_id="default",
        user_id=1,
        owner_type="research_project",
        owner_id=project.id,
        logical_type="report_markdown",
        state="final",
        content=b"v2",
        media_type="text/markdown",
        filename="research-report.md",
    )
    with pytest.raises(AppError) as ownership:
        revisions.delete_artifact(
            username="bob",
            tenant_id="default",
            project_id=project.id,
            artifact_id=first.id,
        )
    assert ownership.value.status_code == 404
    revisions.delete_artifact(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        artifact_id=first.id,
    )
    with session_factory() as db:
        child = db.query(Artifact).filter(Artifact.id == second.id).one()
        assert child.parent_artifact_id is None
        assert db.query(Artifact).filter(Artifact.id == first.id).first() is None


def test_plan_job_idempotency_lease_fencing_and_planner_usage(session_factory):
    repository = ResearchRepository(session_factory)
    project = repository.create_project(
        username="alice",
        tenant_id="default",
        title="研究",
        objective="研究知渊",
        mode="quick",
        sources=["knowledge_base"],
        output_formats=["markdown"],
    )
    job = repository.create_plan_job(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        idempotency_key="plan-key",
        expected_project_version=project.version,
        model_snapshot=_snapshot(),
    )
    repeated = repository.create_plan_job(
        username="alice",
        tenant_id="default",
        project_id=project.id,
        idempotency_key="plan-key",
        expected_project_version=project.version,
        model_snapshot=_snapshot(),
    )
    assert repeated.id == job.id
    first = repository.claim_plan_job(worker_id="worker-1", lease_seconds=30)
    assert first is not None
    with session_factory.begin() as db:
        row = db.query(ResearchPlanJob).filter(ResearchPlanJob.id == job.id).one()
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
    second = repository.claim_plan_job(worker_id="worker-2", lease_seconds=30)
    assert second is not None and second[0].fencing_token > first[0].fencing_token
    with pytest.raises(AppError):
        repository.finish_plan_job(
            job_id=job.id,
            worker_id="worker-1",
            fencing_token=first[0].fencing_token,
            steps=_steps(),
            usage_status="completed",
        )
    repository.finish_plan_job(
        job_id=job.id,
        worker_id="worker-2",
        fencing_token=second[0].fencing_token,
        steps=_steps(),
        usage_status="completed",
        input_tokens=17,
        output_tokens=9,
    )
    with session_factory() as db:
        usage = db.query(ResearchUsage).one()
        assert usage.run_id is None
        assert usage.plan_job_id == job.id
        assert (usage.input_tokens, usage.output_tokens) == (17, 9)


def test_tavily_key_is_transport_local_and_not_in_repr():
    secret = "tavily-secret-for-test"
    settings = get_settings().model_copy(deep=True)
    settings.web_research.enabled = True
    settings.web_research.tavily_api_key = SecretStr(secret)
    runtime = build_web_research_runtime(settings)
    assert secret not in repr(runtime)
    assert secret not in repr(runtime.search_adapter)
    assert runtime.search_adapter._client.api_key == secret


def test_attachment_retrieval_uses_full_frozen_scope_filter():
    captured = {}

    class Store:
        def with_collection(self, collection):
            captured["collection"] = collection
            return self

        def dense_retrieve(self, _vector, *, top_k, filter_expr):
            captured["top_k"] = top_k
            captured["filter"] = filter_expr
            return []

    class Token:
        cancelled = False

    snapshot = type("Snapshot", (), {"tenant_id": "tenant-a"})()
    with (
        patch(
            "backend.indexing.embedding.embedding_service.embed_query",
            return_value=[0.1],
        ),
        patch("backend.indexing.milvus_client.get_milvus_store", return_value=Store()),
    ):
        rows = ResearchWorkflowRunner._retrieve_attachments(
            snapshot,
            Token(),
            "query",
            (
                "research_collection",
                "rproj_1",
                ["ratt_1", "ratt_2"],
                ["rattv_1", "rattv_2"],
            ),
            5,
        )
    assert rows == []
    assert captured["collection"] == "research_collection"
    expression = captured["filter"]
    assert 'tenant_id == "tenant-a"' in expression
    assert 'knowledge_base_id == "research:rproj_1"' in expression
    assert "ratt_1" in expression and "ratt_2" in expression
    assert "rattv_1" in expression and "rattv_2" in expression


def test_attachment_index_attempt_cleans_exact_version_before_rebuild(tmp_path):
    events = []
    source = tmp_path / "attachment.md"
    source.write_text("research attachment", encoding="utf-8")
    build = AttachmentBuild(
        job_id="rattjob_1",
        fencing_token=1,
        attachment_id="ratt_1",
        project_id="rproj_1",
        tenant_id="default",
        version_key="rattv_1",
        filename="attachment.md",
        storage_key=source.name,
        vector_collection="research_collection",
    )

    class Repository:
        def claim(self, **_kwargs):
            return build

        def heartbeat(self, *_args, **_kwargs):
            return True

        def finish(self, _build, **kwargs):
            events.append(("finish", kwargs["success"]))

    class Loader:
        def load_document(self, *_args, **_kwargs):
            events.append("load")
            return [{"chunk_level": 3, "page_content": "evidence"}]

    class Writer:
        collection_initialized = False

        def build_version_scope(self, **_kwargs):
            return "scope"

        def ensure_versioned_collection(self, collection_name):
            events.append(("ensure", collection_name))
            self.collection_initialized = True

        def delete_by_version(self, scope):
            assert self.collection_initialized
            events.append(("delete", scope))

        def write_versioned_documents(self, _documents, **_kwargs):
            events.append("write")
            return "receipt"

        def verify_receipt(self, _receipt):
            return SimpleNamespace(exact=True)

    settings = SimpleNamespace(
        storage=SimpleNamespace(research_attachment_dir=tmp_path)
    )
    with patch("backend.research.attachments.get_settings", return_value=settings):
        worked = ResearchAttachmentIndexer(
            repository=Repository(), loader=Loader(), writer=Writer()
        ).run_once(worker_id="worker", lease_seconds=30)

    assert worked is True
    assert events == [
        ("ensure", "research_collection"),
        ("delete", "scope"),
        "load",
        "write",
        ("finish", True),
    ]


def test_profiles_keep_fixed_budgets_and_concurrency():
    quick = resolve_research_profile("quick")
    standard = resolve_research_profile("standard")
    deep = resolve_research_profile("deep")
    assert (quick["max_evidence"], standard["max_evidence"], deep["max_evidence"]) == (
        12,
        30,
        50,
    )
    assert (
        quick["section_concurrency"],
        standard["section_concurrency"],
        deep["section_concurrency"],
    ) == (3, 5, 6)
    assert (
        quick["model_timeout_seconds"],
        standard["model_timeout_seconds"],
        deep["model_timeout_seconds"],
    ) == (180, 360, 720)
    assert (
        quick["writing_budget_seconds"],
        standard["writing_budget_seconds"],
        deep["writing_budget_seconds"],
    ) == (360, 600, 1200)
    assert (quick["max_rounds"], standard["max_rounds"], deep["max_rounds"]) == (
        1,
        2,
        2,
    )
    assert "web_search_depth" not in quick
    assert "web_authentication" not in quick
    with patch("backend.research.workflow.time.monotonic", return_value=10.0):
        assert ResearchWorkflowRunner._model_deadline(500, standard) == 370.0


@pytest.mark.asyncio
async def test_deep_profile_starts_all_six_sections_concurrently(monkeypatch):
    profile = resolve_research_profile("deep")
    steps = [
        {
            "step_key": f"step-{position}",
            "title": f"章节 {position}",
            "question": f"核验方向 {position}",
            "sources": ["web"],
        }
        for position in range(1, 7)
    ]

    class Store:
        def load_manifest(self, _run_id):
            return {
                "project_id": "rproj_concurrency",
                "plan": {"steps": steps},
                "profile": profile,
                "output": {"formats": ["markdown"]},
            }

        def write_section_and_draft(self, **_kwargs):
            return None

        def finalize_artifacts(self, **_kwargs):
            return None

    class Token:
        def append_partial(self, _content):
            return None

    runner = ResearchWorkflowRunner(store=Store())
    active = 0
    maximum_active = 0
    all_started = asyncio.Event()
    release = asyncio.Event()

    async def research_section(**kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        if active == len(steps):
            all_started.set()
        await release.wait()
        active -= 1
        step = kwargs["step"]
        return (
            kwargs["position"],
            step["step_key"],
            step["title"],
            "章节正文",
            [],
            False,
            0,
            SimpleNamespace(claim="结论", verdict="supported", reason="证据充分"),
        )

    monkeypatch.setattr(runner, "_research_section", research_section)
    snapshot = SimpleNamespace(
        run=SimpleNamespace(id="run_concurrency", fencing_token=1),
        user_text="并发研究",
        user_db_id=1,
        tenant_id="default",
    )
    task = asyncio.create_task(
        runner._run_workflow(snapshot=snapshot, token=Token(), worker_id="worker")
    )
    try:
        await asyncio.wait_for(all_started.wait(), timeout=2)
    finally:
        release.set()
        await task

    assert maximum_active == 6


def test_planner_turns_generic_repeated_questions_into_distinct_search_directions():
    objective = (
        "比较 PostgreSQL pgvector、Milvus 和 Qdrant 在 10 万、1000 万和 1 亿级"
        "向量规模下的性能、扩展能力、运维复杂度和成本。"
    )
    generic = "研究对象：PostgreSQL pgvector、Milvus 和 Qdrant"

    class Model:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            return SimpleNamespace(
                steps=[
                    ResearchPlanStepV1(
                        step_key="ignored-1",
                        title="规模与性能基线",
                        question=generic,
                        sources=["web"],
                    ),
                    ResearchPlanStepV1(
                        step_key="ignored-2",
                        title="混合检索与扩展能力",
                        question=generic,
                        sources=["web"],
                    ),
                    ResearchPlanStepV1(
                        step_key="ignored-3",
                        title="运维成本与选型建议",
                        question=generic,
                        sources=["web"],
                    ),
                ]
            )

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake-planner", timeout_seconds=30)

    class Executor:
        def call(self, operation, *, context):
            assert context.deadline == 40.0
            return operation()

    result = ResearchPlanner(
        models=Models(), executor=Executor(), clock=lambda: 10.0
    ).generate(
        objective=objective,
        title="企业 RAG 向量库选型",
        mode="quick",
        sources=["web"],
        model_snapshot=_snapshot(),
        cancellation=lambda: False,
    )

    questions = [step.question for step in result.steps]
    queries = [build_web_query(objective, question) for question in questions]
    assert result.usage_status == "completed"
    assert len(set(questions)) == len(questions) == 3
    assert len(set(queries)) == len(queries) == 3
    assert all(objective in question for question in questions)
    assert all(step.title in step.question for step in result.steps)


def test_generated_plan_applies_every_selected_source_to_every_step():
    class Model:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            return SimpleNamespace(
                steps=[
                    ResearchPlanStepV1(
                        step_key="ignored-1",
                        title="事实核验",
                        question="核验采购标准的核心事实",
                        sources=["knowledge_base"],
                    ),
                    ResearchPlanStepV1(
                        step_key="ignored-2",
                        title="约束分析",
                        question="分析采购标准的约束",
                        sources=["web"],
                    ),
                ]
            )

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake-planner", timeout_seconds=30)

    class Executor:
        def call(self, operation, *, context):
            return operation()

    result = ResearchPlanner(models=Models(), executor=Executor()).generate(
        objective="研究政府采购标准",
        title="采购需求研究",
        mode="quick",
        sources=["knowledge_base", "web"],
        model_snapshot=_snapshot(),
        cancellation=lambda: False,
    )

    assert [step.sources for step in result.steps] == [
        ["knowledge_base", "web"],
        ["knowledge_base", "web"],
    ]


@pytest.mark.asyncio
async def test_knowledge_retrieval_runs_in_worker_without_an_event_loop(monkeypatch):
    from backend.rag import pipeline

    class Graph:
        def invoke(self, _state):
            return {
                "docs": [
                    {
                        "content": "采购标准证据",
                        "metadata": {"chunk_id": "chunk-1", "filename": "标准.pdf"},
                    }
                ]
            }

    monkeypatch.setattr(pipeline, "checkpointless_rag_graph", Graph())
    snapshot = SimpleNamespace(
        username="alice",
        tenant_id="default",
        model_snapshot=_snapshot(),
        run=SimpleNamespace(thread_id="research-thread"),
    )

    rows = await asyncio.to_thread(
        ResearchWorkflowRunner._retrieve_knowledge,
        snapshot,
        SimpleNamespace(cancelled=False),
        "核验采购标准",
    )

    assert [(item["stable_key"], item["source_kind"]) for item in rows] == [
        ("chunk-1", "knowledge_base")
    ]


def test_numeric_year_does_not_discard_chinese_objective_evidence():
    evidence = [
        {
            "title": "台式计算机政府采购需求标准",
            "content": "规定了普通办公场景的性能和安全要求。",
        }
    ]

    kept, dropped = filter_objective_evidence(
        evidence,
        "根据《台式计算机政府采购需求标准（2023年版）》设计采购方案",
    )

    assert len(kept) == 1
    assert kept[0]["title"] == evidence[0]["title"]
    assert kept[0]["metadata"]["objective_policy_applied"] is False
    assert dropped == 0


@pytest.mark.asyncio
async def test_writer_receives_original_objective_and_specific_section_question():
    captured = {}
    objective = "只比较 pgvector、Milvus 和 Qdrant 的性能与成本"
    question = "规模与性能基线：分别核验三者在 1000 万向量下的查询性能"

    class Model:
        def invoke(self, messages):
            captured["prompt"] = messages[0]["content"]
            return SimpleNamespace(content="只依据证据形成的章节 [E1]。")

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake-writer", timeout_seconds=30)

    class Executor:
        def call(self, operation, *, context):
            assert context.cancellation() is False
            return operation()

    runner = ResearchWorkflowRunner(models=Models(), executor=Executor())
    text, _input_tokens, _output_tokens = await runner._write_section(
        SimpleNamespace(user_text=objective, model_snapshot=_snapshot()),
        SimpleNamespace(cancelled=False),
        "规模与性能基线",
        question,
        [SimpleNamespace(citation_number=1, title="官方性能资料", content="证据正文")],
        resolve_research_profile("quick"),
    )

    assert text.endswith("[E1]。")
    assert f"原始研究目标：{objective}" in captured["prompt"]
    assert f"本章问题：{question}" in captured["prompt"]
    assert "不得把研究目标未列出的对象加入候选对比表" in captured["prompt"]


@pytest.mark.asyncio
async def test_frozen_plan_retrieval_adds_step_title_to_legacy_generic_question(
    monkeypatch,
):
    captured = {}
    objective = "比较 pgvector、Milvus 和 Qdrant 的性能、运维和成本"
    runner = ResearchWorkflowRunner()

    def retrieve_web(_token, received_objective, received_question, _limit):
        captured["objective"] = received_objective
        captured["question"] = received_question
        return []

    class Token:
        cancelled = False

        async def checkpoint(self):
            return None

    monkeypatch.setattr(runner, "_retrieve_web", retrieve_web)
    await runner._retrieve(
        SimpleNamespace(
            user_text=objective, channel="research", run=SimpleNamespace(id="run")
        ),
        Token(),
        {
            "title": "运维成本与选型建议",
            "question": f"围绕研究目标“{objective}”：研究对象：pgvector、Milvus 和 Qdrant",
            "sources": ["web"],
        },
        resolve_research_profile("quick"),
        gap_lock=asyncio.Lock(),
        gap_budget=[0],
    )

    assert captured["objective"] == objective
    assert captured["question"].startswith("运维成本与选型建议：")


@pytest.mark.asyncio
async def test_retrieval_reports_source_candidates_filters_and_errors(monkeypatch):
    runner = ResearchWorkflowRunner()

    def retrieve_knowledge(*_args):
        raise RuntimeError("knowledge unavailable")

    def retrieve_web(*_args):
        return [
            {
                "stable_key": "web-alpha",
                "source_kind": "web",
                "title": "Alpha 官方说明",
                "content": "Alpha 的采购能力说明",
                "source_uri": "https://example.com/alpha",
                "relevance_score": 0.9,
            },
            {
                "stable_key": "web-other",
                "source_kind": "web",
                "title": "其他产品",
                "content": "与研究目标无关",
                "source_uri": "https://example.org/other",
                "relevance_score": 0.8,
            },
        ]

    class Token:
        cancelled = False

        async def checkpoint(self):
            return None

    monkeypatch.setattr(runner, "_retrieve_knowledge", retrieve_knowledge)
    monkeypatch.setattr(runner, "_retrieve_web", retrieve_web)
    evidence, errors, source_stats = await runner._retrieve(
        SimpleNamespace(
            user_text="研究 Alpha 2023 采购能力",
            channel="research",
            run=SimpleNamespace(id="run-source-stats"),
        ),
        Token(),
        {
            "title": "能力核验",
            "question": "核验 Alpha 的采购能力",
            "sources": ["knowledge_base", "web"],
        },
        resolve_research_profile("quick"),
        gap_lock=asyncio.Lock(),
        gap_budget=[0],
    )

    assert [item["stable_key"] for item in evidence] == ["web-alpha"]
    assert errors == [("research.knowledge_base", "RESEARCH_KNOWLEDGE_SOURCE_DEGRADED")]
    assert source_stats == {
        "knowledge_base": {
            "candidate_count": 0,
            "evidence_count": 0,
            "filtered_count": 0,
            "error_count": 1,
        },
        "web": {
            "candidate_count": 2,
            "evidence_count": 1,
            "filtered_count": 1,
            "error_count": 0,
        },
    }


def test_report_section_removes_only_a_duplicate_plan_title():
    body = ResearchWorkflowRunner._without_duplicate_title(
        "核心功能与架构事实核验",
        "## 核心功能与架构事实核验\n\n### 已核验事实\n\n- 有直接证据支持。",
    )

    assert body == "### 已核验事实\n\n- 有直接证据支持。"
    assert (
        ResearchWorkflowRunner._without_duplicate_title(
            "核心功能与架构事实核验", "### 关键限制\n\n证据不足。"
        )
        == "### 关键限制\n\n证据不足。"
    )


@pytest.mark.asyncio
async def test_research_runner_executes_langgraph_with_run_id_identity():
    calls = {}

    class Store:
        def completed_result(self, _run_id):
            return None

        def uses_postgres(self):
            return False

        def load_manifest(self, run_id):
            calls["manifest_run_id"] = run_id
            return {
                "project_id": "rproj_graph",
                "plan": {"steps": []},
                "profile": {},
                "output": {"formats": ["markdown"]},
            }

        def finalize_artifacts(self, **kwargs):
            calls["final_run_id"] = kwargs["run_id"]

    class Token:
        def append_partial(self, content):
            calls["partial"] = content

    snapshot = SimpleNamespace(
        run=SimpleNamespace(id="run_graph_identity", fencing_token=1),
        user_text="研究图测试",
        user_db_id=1,
        tenant_id="default",
    )
    result = await ResearchWorkflowRunner(store=Store()).run(
        snapshot=snapshot,
        token=Token(),
        worker_id="worker-graph",
    )
    assert calls["manifest_run_id"] == "run_graph_identity"
    assert calls["final_run_id"] == "run_graph_identity"
    assert result.startswith("# 研究图测试")


def test_target_policy_rejects_wrong_repository_and_domain_quota():
    target = resolve_research_target("研究 GitHub 仓库 openai/zhiyuan")
    assert target is not None and target.key == "openai/zhiyuan"
    kept, dropped = filter_objective_evidence(
        [
            {
                "title": "ZhiYuan",
                "source_uri": "https://github.com/openai/zhiyuan",
                "content": "openai/zhiyuan",
            },
            {
                "title": "Other",
                "source_uri": "https://github.com/else/other",
                "content": "else/other",
            },
        ],
        "研究 GitHub 仓库 openai/zhiyuan",
    )
    assert len(kept) == 1 and dropped == 1
    ranked = rank_web_evidence(
        [
            {
                "title": "ZhiYuan one",
                "source_uri": "https://github.com/openai/zhiyuan/a",
                "content": "openai/zhiyuan",
                "relevance_score": 0.9,
            },
            {
                "title": "ZhiYuan two",
                "source_uri": "https://github.com/openai/zhiyuan/b",
                "content": "openai/zhiyuan",
                "relevance_score": 0.8,
            },
            {
                "title": "ZhiYuan three",
                "source_uri": "https://github.com/openai/zhiyuan/c",
                "content": "openai/zhiyuan",
                "relevance_score": 0.7,
            },
        ],
        objective="研究 GitHub 仓库 openai/zhiyuan",
        limit=3,
        per_domain=2,
    )
    assert len(ranked) == 2
