from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.research.profiles import resolve_research_profile
from backend.research.query_policy import filter_objective_evidence
from backend.research.workflow import ResearchWorkflowRunner


class Token:
    cancelled = False

    async def checkpoint(self):
        return None

    def append_partial(self, _content):
        return None


class Store:
    def __init__(self):
        self.usage = []
        self.warnings = []

    def record_usage(self, **kwargs):
        self.usage.append(kwargs)

    def warning(self, **kwargs):
        self.warnings.append(kwargs)

    def load_manifest(self, _run_id):
        return {"project_id": "project"}

    def set_step_phase(self, **_kwargs):
        return None


def snapshot():
    return SimpleNamespace(
        run=SimpleNamespace(id="run", fencing_token=1, owner_worker_id="worker"),
        model_snapshot=None,
        user_text="比较企业知识库检索方案的成本与效果",
        user_db_id=1,
        tenant_id="default",
    )


def test_chinese_objective_filters_unrelated_evidence():
    kept, dropped = filter_objective_evidence(
        [
            {"title": "养花技巧", "content": "盆栽应当适量浇水。"},
            {"title": "盆栽成本", "content": "养花的成本与效果可以优化。"},
            {"title": "企业知识库", "content": "知识库检索方案需要评估索引成本。"},
        ],
        "比较企业知识库检索方案的成本与效果",
    )
    assert [item["title"] for item in kept] == ["企业知识库"]
    assert dropped == 2


def test_repository_comparison_keeps_evidence_for_each_target():
    kept, dropped = filter_objective_evidence(
        [
            {"title": "Alpha", "source_uri": "https://github.com/acme/alpha"},
            {"title": "Beta", "source_uri": "https://github.com/acme/beta"},
            {"title": "Other", "source_uri": "https://github.com/acme/alpha-unrelated"},
        ],
        "比较 https://github.com/acme/alpha 和 https://github.com/acme/beta",
    )
    assert [item["title"] for item in kept] == ["Alpha", "Beta"]
    assert dropped == 1


@pytest.mark.asyncio
async def test_verifier_failure_never_marks_a_claim_supported():
    class Models:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("simulated provider failure")

    store = Store()
    runner = ResearchWorkflowRunner(store=store, models=Models())
    decision = await runner._verify_claim(
        snapshot=snapshot(),
        token=Token(),
        worker_id="worker",
        project_id="project",
        step_key="scope",
        markdown="没有得到证据支持的断言。",
        evidence=[SimpleNamespace(citation_number=1, content="无关材料。")],
        degraded=False,
        profile=resolve_research_profile("quick"),
    )
    assert decision.verdict == "insufficient"
    assert store.usage[-1]["status"] == "failed"
    assert store.warnings[-1]["code"] == "RESEARCH_VERIFIER_DEGRADED"


@pytest.mark.asyncio
async def test_combined_review_receives_evidence_content_not_only_citation_ids():
    captured = []

    class Model:
        def with_structured_output(self, _schema, *, method):
            return self

        async def ainvoke(self, messages, **_kwargs):
            captured.append(messages[0]["content"])
            return {
                "needs_revision": False,
                "issues": [],
                "claim": "每月成本为 100 元",
                "verdict": "unsupported",
                "reason": "官方价格为 500 元",
            }

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake", timeout_seconds=30)

    class Executor:
        async def acall(self, operation, *, context):
            return await operation()

    runner = ResearchWorkflowRunner(store=Store(), models=Models(), executor=Executor())
    await runner._verify_claim(
        snapshot=snapshot(),
        token=Token(),
        worker_id="worker",
        step_key="scope",
        project_id="project",
        degraded=False,
        markdown="每月成本为 100 元 [E1]。",
        evidence=[
            SimpleNamespace(citation_number=1, content="官方价格为每月 500 元。")
        ],
        profile=resolve_research_profile("standard"),
    )
    assert "官方价格为每月 500 元" in captured[0]


@pytest.mark.asyncio
async def test_finished_chapter_is_persisted_before_slow_chapter_and_survives_cancel(
    monkeypatch,
):
    first_saved = asyncio.Event()
    slow_started = asyncio.Event()
    release = asyncio.Event()
    saved = []

    class WorkflowStore(Store):
        def load_manifest(self, _run_id):
            return {
                "project_id": "project",
                "plan": {"steps": [{"step_key": "fast"}, {"step_key": "slow"}]},
                "profile": resolve_research_profile("quick"),
            }

        def write_section_and_draft(self, **kwargs):
            saved.append(kwargs)
            if kwargs["section_key"] == "fast":
                loop.call_soon_threadsafe(first_saved.set)

    loop = asyncio.get_running_loop()
    runner = ResearchWorkflowRunner(store=WorkflowStore())

    async def section(**kwargs):
        key = kwargs["step"]["step_key"]
        if key == "slow":
            slow_started.set()
            await release.wait()
        return (
            kwargs["position"],
            key,
            key,
            f"{key} 正文",
            [],
            False,
            0,
            SimpleNamespace(claim=key, verdict="insufficient", reason="证据不足"),
        )

    monkeypatch.setattr(runner, "_research_section", section)
    task = asyncio.create_task(
        runner._run_workflow(snapshot=snapshot(), token=Token(), worker_id="worker")
    )
    try:
        await asyncio.wait_for(slow_started.wait(), 2)
        await asyncio.wait_for(first_saved.wait(), 2)
        assert saved[0]["section_key"] == "fast"
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("body", ["没有引用的事实。", "事实 [E999]。"])
def test_missing_or_unknown_citations_are_disclosed(body):
    checked, invalid = ResearchWorkflowRunner._validate_citations(
        body, [SimpleNamespace(citation_number=1)]
    )
    assert invalid
    assert "引用提示" in checked
    assert "[E999]" not in checked


@pytest.mark.asyncio
async def test_gap_analysis_uses_existing_material_and_stops_when_sufficient():
    captured = []

    class Model:
        def with_structured_output(self, _schema, *, method):
            return self

        async def ainvoke(self, messages, **_kwargs):
            captured.append(messages[0]["content"])
            return {"needs_research": False, "question": ""}

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake", timeout_seconds=30)

    class Executor:
        async def acall(self, operation, *, context):
            return await operation()

    store = Store()
    runner = ResearchWorkflowRunner(store=store, models=Models(), executor=Executor())
    question = await runner._find_gap(
        snapshot=snapshot(),
        token=Token(),
        question="核验知识库成本",
        evidence=[{"title": "价格", "content": "每月 500 元，支持 10 万条文档。"}],
        profile=resolve_research_profile("standard"),
    )
    assert question is None
    assert "每月 500 元" in captured[0]
    assert "遗漏关键比较对象" in captured[0]
    assert store.usage[-1]["stage"] == "gap_analysis"


@pytest.mark.asyncio
async def test_synthesis_failure_preserves_sections_and_reports_degradation():
    class Models:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("offline synthesis unavailable")

    store = Store()
    runner = ResearchWorkflowRunner(store=store, models=Models())
    text = await runner._synthesize(
        snapshot=snapshot(),
        token=Token(),
        worker_id="worker",
        project_id="project",
        sections=["已保存章节 [E1]"],
        evidence=[SimpleNamespace(citation_number=1, content="材料")],
        claims=[],
        profile=resolve_research_profile("quick"),
    )
    assert "综合编辑未完成" in text
    assert store.usage[-1]["status"] == "failed"
    assert store.warnings[-1]["code"] == "RESEARCH_SYNTHESIS_DEGRADED"


@pytest.mark.asyncio
async def test_synthesis_keeps_unresolved_claims_visible_when_editor_omits_them():
    class Model:
        async def ainvoke(self, _messages, **_kwargs):
            return SimpleNamespace(content="方案值得考虑 [E1]。")

    class Models:
        def get(self, *_args, **_kwargs):
            return Model()

        def describe(self, *_args, **_kwargs):
            return SimpleNamespace(name="fake", timeout_seconds=30)

    class Executor:
        async def acall(self, operation, *, context):
            return await operation()

    runner = ResearchWorkflowRunner(store=Store(), models=Models(), executor=Executor())
    text = await runner._synthesize(
        snapshot=snapshot(),
        token=Token(),
        worker_id="worker",
        project_id="project",
        sections=["成本待核验 [E1]"],
        evidence=[SimpleNamespace(citation_number=1, content="价格材料")],
        claims=[
            SimpleNamespace(
                claim="成本不超过预算", verdict="insufficient", reason="缺少部署报价"
            )
        ],
        profile=resolve_research_profile("quick"),
    )
    assert "证据不足，仍需核验：成本不超过预算" in text
    assert "缺少部署报价" in text


@pytest.mark.asyncio
async def test_concurrent_runs_keep_drafts_and_identities_separate(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    entered = 0
    saved = []
    finals = []

    class WorkflowStore(Store):
        def load_manifest(self, run_id):
            return {
                "project_id": f"project-{run_id}",
                "plan": {"steps": [{"step_key": "scope"}]},
                "profile": {},
            }

        def write_section_and_draft(self, **kwargs):
            saved.append(kwargs)

        def finalize_artifacts(self, **kwargs):
            finals.append(kwargs)

    runner = ResearchWorkflowRunner(store=WorkflowStore())

    async def section(**kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            started.set()
        await release.wait()
        run_id = kwargs["snapshot"].run.id
        return (
            1,
            "scope",
            run_id,
            f"only-{run_id}",
            [],
            True,
            0,
            SimpleNamespace(claim=run_id, verdict="insufficient", reason="缺口"),
        )

    monkeypatch.setattr(runner, "_research_section", section)
    snapshots = [snapshot(), snapshot()]
    for item, identity in zip(snapshots, ("A", "B"), strict=True):
        item.run.id = identity
        item.user_text = f"目标-{identity}"
    tasks = [
        asyncio.create_task(
            runner._run_workflow(snapshot=item, token=Token(), worker_id="worker")
        )
        for item in snapshots
    ]
    try:
        await asyncio.wait_for(started.wait(), 2)
    finally:
        release.set()
        await asyncio.gather(*tasks)
    for entry in saved:
        identity = entry["run_id"]
        other = "B" if identity == "A" else "A"
        assert entry["project_id"] == f"project-{identity}"
        assert f"only-{identity}" in entry["complete_draft"]
        assert f"only-{other}" not in entry["complete_draft"]
    assert {entry["run_id"] for entry in finals} == {"A", "B"}
