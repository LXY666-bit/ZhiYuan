from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.providers.core import ProviderCode, ProviderError
from backend.research.profiles import resolve_research_profile
from backend.research.workflow import ResearchWorkflowRunner


class Token:
    cancelled = False

    async def checkpoint(self):
        pass


def snapshot():
    return SimpleNamespace(
        user_text="核验 Alpha 的部署成本",
        channel="research",
        model_snapshot=None,
        tenant_id="default",
        run=SimpleNamespace(id="run", fencing_token=1),
    )


@pytest.mark.asyncio
async def test_sources_start_together_and_keep_healthy_results(monkeypatch):
    loop = asyncio.get_running_loop()
    both_started = asyncio.Event()
    release = threading.Event()
    lock = threading.Lock()
    entered = 0
    runner = ResearchWorkflowRunner()

    def source(kind):
        def retrieve(*_args, **_kwargs):
            nonlocal entered
            with lock:
                entered += 1
                if entered == 2:
                    loop.call_soon_threadsafe(both_started.set)
            release.wait(2)
            if kind == "knowledge_base":
                raise RuntimeError("controlled source failure")
            return [
                {
                    "stable_key": "alpha",
                    "source_kind": "web",
                    "title": "Alpha",
                    "content": "Alpha 部署成本",
                }
            ]

        return retrieve

    monkeypatch.setattr(runner, "_retrieve_knowledge", source("knowledge_base"))
    monkeypatch.setattr(runner, "_retrieve_web", source("web"))
    task = asyncio.create_task(
        runner._retrieve(
            snapshot(),
            Token(),
            {"sources": ["knowledge_base", "web"]},
            resolve_research_profile("quick"),
            gap_lock=asyncio.Lock(),
            gap_budget=[0],
        )
    )
    try:
        await asyncio.wait_for(both_started.wait(), 0.5)
    finally:
        release.set()
        rows, errors, stats = await task
    assert [row["stable_key"] for row in rows] == ["alpha"]
    assert errors == [("research.knowledge_base", "RESEARCH_KNOWLEDGE_SOURCE_DEGRADED")]
    assert stats["web"]["evidence_count"] == 1


@pytest.mark.asyncio
async def test_writer_deadline_cancels_inflight_model_instead_of_waiting_for_transport():
    cancelled = asyncio.Event()

    class Model:
        async def ainvoke(self, _messages, **_kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake", timeout_seconds=300)

    runner = ResearchWorkflowRunner(models=Models())
    profile = {**resolve_research_profile("deep"), "model_timeout_seconds": 0.02}
    with pytest.raises(ProviderError) as error:
        await runner._write_section(
            snapshot(),
            Token(),
            "成本",
            "核验成本",
            [SimpleNamespace(citation_number=1, title="价格", content="Alpha 价格")],
            profile,
        )
    assert error.value.code == ProviderCode.PROVIDER_TIMEOUT
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revise", "writer_failure"), [(False, False), (True, False), (False, True)]
)
async def test_deep_chapter_only_spends_calls_on_available_draft_and_required_revision(
    monkeypatch,
    revise,
    writer_failure,
):
    calls = []

    class Model:
        def __init__(self, schema=None):
            self.schema = schema

        def with_structured_output(self, schema, *, method):
            return Model(schema)

        def invoke(self, _messages):
            calls.append(self.schema.__name__ if self.schema else "writer")
            if self.schema is None:
                return SimpleNamespace(content="Alpha 部署成本为 500 元 [E1]。")
            needs_revision = revise and len(calls) == 2
            return {
                "claim": "Alpha 部署成本为 500 元",
                "verdict": "unsupported" if needs_revision else "supported",
                "reason": "价格材料支持。",
                "needs_revision": needs_revision,
                "issues": ["修正价格"] if needs_revision else [],
            }

        async def ainvoke(self, messages, **_kwargs):
            return self.invoke(messages)

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake", timeout_seconds=30)

    class Store:
        def completed_section(self, *_args):
            return None

        def load_manifest(self, *_args):
            return {"project_id": "project"}

        def step_started(self, **_kwargs):
            pass

        def step_completed(self, **_kwargs):
            return [
                SimpleNamespace(
                    id="evidence",
                    citation_number=1,
                    title="价格",
                    content="Alpha 部署成本为 500 元。",
                )
            ]

        def set_step_phase(self, **_kwargs):
            pass

        def record_usage(self, **_kwargs):
            pass

        def warning(self, **_kwargs):
            pass

    runner = ResearchWorkflowRunner(store=Store(), models=Models())

    async def retrieve(*_args, **_kwargs):
        return [{"stable_key": "alpha"}], [], {}

    monkeypatch.setattr(runner, "_retrieve", retrieve)
    if writer_failure:

        async def failed_writer(*_args, **_kwargs):
            raise TimeoutError

        monkeypatch.setattr(runner, "_write_section", failed_writer)
    result = await runner._research_section(
        snapshot=snapshot(),
        token=Token(),
        worker_id="worker",
        position=1,
        step={"step_key": "costs", "title": "成本"},
        profile=resolve_research_profile("deep"),
        evidence_lock=asyncio.Lock(),
        gap_lock=asyncio.Lock(),
        gap_budget=[0],
        project_id="project",
    )
    if writer_failure:
        assert result[5]
        assert result[-1].verdict == "insufficient"
        assert "没有可供核验的有效正文" in result[-1].reason
        assert calls == []
        return
    assert not result[5]
    assert result[-1].verdict == "supported"
    assert result[6] == int(revise)
    assert calls == ["writer", "SectionReviewDecision"] * (2 if revise else 1)


@pytest.mark.asyncio
async def test_slow_source_expires_without_discarding_fast_evidence(monkeypatch):
    release = threading.Event()
    received = []
    runner = ResearchWorkflowRunner()

    def slow(token, *_args, **_kwargs):
        received.append(token)
        release.wait(2)
        return [{"stable_key": "late", "source_kind": "web", "title": "Alpha"}]

    def fast(*_args, **_kwargs):
        return [
            {
                "stable_key": "ready",
                "source_kind": "knowledge_base",
                "title": "Alpha",
                "content": "Alpha 部署成本",
            }
        ]

    monkeypatch.setattr(runner, "_retrieve_web", slow)
    monkeypatch.setattr(runner, "_retrieve_knowledge", fast)
    profile = {**resolve_research_profile("quick"), "source_timeout_seconds": 0.05}
    try:
        rows, errors, stats = await runner._retrieve(
            snapshot(),
            Token(),
            {"sources": ["knowledge_base", "web"]},
            profile,
            gap_lock=asyncio.Lock(),
            gap_budget=[0],
        )
        assert [row["stable_key"] for row in rows] == ["ready"]
        assert errors == [("research.web", "RESEARCH_WEB_SOURCE_TIMEOUT")]
        assert stats["web"]["error_count"] == 1
        assert received[0].cancelled
    finally:
        release.set()


@pytest.mark.asyncio
async def test_parallel_chapters_share_one_run_owned_document_snapshot(monkeypatch):
    resolved = []
    observed = []
    frozen_scope = object()
    runner = ResearchWorkflowRunner()

    def resolve(**kwargs):
        resolved.append(kwargs["tenant_id"])
        return frozen_scope

    def retrieve(*_args, **kwargs):
        observed.append(kwargs["retrieval_snapshot"])
        return []

    monkeypatch.setattr(runner, "_resolve_knowledge_scope", resolve)
    monkeypatch.setattr(runner, "_retrieve_knowledge", retrieve)
    profile = {
        **resolve_research_profile("deep"),
        "retrieval_deadline": asyncio.get_running_loop().time() + 2,
        "source_gate": asyncio.Semaphore(2),
        "knowledge_scope": {"task": None},
    }
    await asyncio.gather(
        *(
            runner._retrieve_source(
                source="knowledge_base",
                snapshot=snapshot(),
                token=Token(),
                question="成本",
                profile=profile,
                attachment_scope=None,
            )
            for _ in range(2)
        )
    )
    assert resolved == ["default"]
    assert observed == [frozen_scope, frozen_scope]


@pytest.mark.asyncio
async def test_recovered_run_keeps_original_deadline_instead_of_restarting_budget(
    monkeypatch,
):
    captured = []

    class Store:
        def load_manifest(self, _run_id):
            return {
                "profile": resolve_research_profile("deep"),
                "project_id": "project",
                "plan": {"steps": [{"step_key": "scope"}]},
            }

        def write_section_and_draft(self, **_kwargs):
            pass

        def finalize_artifacts(self, **_kwargs):
            pass

    runner = ResearchWorkflowRunner(store=Store())
    request = snapshot()
    request.run.deadline_at = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    request.user_db_id = 1
    started = asyncio.get_running_loop().time()

    async def section(**kwargs):
        captured.append(kwargs["profile"]["run_deadline"])
        return (
            1,
            "scope",
            "范围",
            "证据缺口",
            [],
            True,
            0,
            SimpleNamespace(claim="缺口", verdict="insufficient", reason="缺少材料"),
        )

    monkeypatch.setattr(runner, "_research_section", section)
    await runner._run_workflow(
        snapshot=request,
        token=SimpleNamespace(append_partial=lambda _text: None),
        worker_id="worker",
    )
    assert started < captured[0] <= started + 5.1
