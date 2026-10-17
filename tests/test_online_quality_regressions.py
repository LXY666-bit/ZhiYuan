from types import SimpleNamespace
from datetime import UTC, datetime
import hashlib
import time

import pytest

from backend.research.source_quality import enrich_web_evidence, rank_web_evidence
from test_rag_short_circuit import FakeStructuredModel, _doc, _meta, load_pipeline


def test_keyword_tool_queries_preserve_each_runs_original_request(monkeypatch):
    import sys
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from backend.rag.checkpoint_runner import CheckpointedRagRunner, RagRunOutcome
    from backend.runs.request_context import RunRequestContext
    from backend.tools.knowledge import make_checkpointed_search_knowledge_base

    barrier = threading.Barrier(2)

    def retrieve(*args, **kwargs):
        barrier.wait(timeout=10)
        return {"docs": [_doc("邻近资料")], "meta": _meta(1)}

    pipeline = load_pipeline(retrieve_documents=retrieve)
    grade = pipeline.EvidenceGrade(
        relevance="strong",
        answerability="partial",
        ambiguity="missing_slot",
        route="clarify",
        missing_slots=["型号"],
    )

    monkeypatch.setattr(
        pipeline,
        "_get_grader_model",
        lambda *_: FakeStructuredModel(lambda *_: grade.model_dump()),
    )
    monkeypatch.setitem(sys.modules, "backend.rag.pipeline", pipeline)
    runner = CheckpointedRagRunner(checkpoint_repository=SimpleNamespace())
    monkeypatch.setattr(
        runner,
        "_outcome",
        lambda **kw: RagRunOutcome(
            result=kw["result"], fencing_token=kw["fencing_token"], pause=None
        ),
    )

    def run_one(name, original):
        context = RunRequestContext.for_sync(
            user_id=name, thread_id=name, tenant_id="default"
        )
        try:
            tool = make_checkpointed_search_knowledge_base(
                context,
                run_id=name,
                worker_id="worker",
                fencing_token=1,
                runner=runner,
                original_question=original,
            )
            return tool.invoke({"query": "量子极速模式 电脑 支持"})
        finally:
            context.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            run_one, "run-a", "如果没有相关证据，请直接说明，不能猜测。"
        )
        second = pool.submit(run_one, "run-b", "这款电脑支持量子极速模式吗？")
        assert first.result().startswith("INSUFFICIENT_EVIDENCE:")
        assert second.result().startswith("NEEDS_CLARIFICATION:")


@pytest.mark.parametrize(
    "answers", [[], ["没有新资料，请不要继续追问。"], ["角色甲", "版本乙"]]
)
def test_missing_evidence_finishes_without_repeated_clarification(answers):
    pipeline = load_pipeline(
        retrieve_documents=lambda *args, **kwargs: {
            "docs": [_doc("只有邻近主题资料")],
            "meta": _meta(1),
        }
    )
    grade = pipeline.EvidenceGrade(
        relevance="strong",
        answerability="partial",
        ambiguity="none",
        route="clarify",
        reason="资料未说明这个功能",
    )
    state = {"docs": [_doc("邻近资料")], "rewrite_count": 1, "hitl_answers": answers}
    update = pipeline._grade_update(grade, pipeline._resolve_route(grade, state))
    assert update["route"] == "insufficient_evidence"
    assert update["retrieval_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert update["hitl_prompt"] == ""


def test_resume_declining_more_information_finishes_with_insufficient_evidence():
    pipeline = load_pipeline(
        retrieve_documents=lambda *args, **kwargs: {
            "docs": [_doc("邻近资料")],
            "meta": _meta(1),
        }
    )
    pipeline._get_grader_model = lambda *_: FakeStructuredModel(
        lambda *_: {
            "relevance": "strong",
            "answerability": "partial",
            "ambiguity": "missing_slot",
            "route": "clarify",
            "missing_slots": ["功能名"],
            "hitl_prompt": "请补充功能名",
        }
    )
    result = pipeline.resume_rag_state(
        {"question": "支持量子模式吗？", "route": "clarify", "tenant_id": "default"},
        "不需要补充新资料，请仅说明现有证据不足。",
    )
    assert result["route"] == "insufficient_evidence"
    assert result["retrieval_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert not result["docs"]


def test_official_request_does_not_fill_evidence_slots_with_mirrors():
    rows = rank_web_evidence(
        [
            {
                "source_uri": url,
                "title": "PostgreSQL B-tree",
                "content": "PostgreSQL B-tree supports equality",
            }
            for url in [
                "https://postgres.ac.cn/docs/current/btree.html",
                "https://docs.postgresql.tw/15/btree.html",
                "https://www.postgresql.org/docs/current/indexes-types.html",
            ]
        ],
        objective="根据 PostgreSQL 官方文档介绍 B-tree",
        limit=3,
    )
    assert [r["source_uri"] for r in rows] == [
        "https://www.postgresql.org/docs/current/indexes-types.html"
    ]


@pytest.mark.parametrize(
    ("url", "title", "version"),
    [
        ("https://docs.postgresql.tw/15/internals/btree", "PostgreSQL B-tree", "15"),
        (
            "https://www.postgresql.org/docs/current/btree.html",
            "PostgreSQL: Documentation: 18: B-tree",
            "18",
        ),
        (
            "https://www.postgresql.org/docs/current/btree.html",
            "PostgreSQL B-tree",
            "未标明（不能推定为最新版本）",
        ),
    ],
)
def test_postgresql_version_clues_are_preserved(url, title, version):
    row = enrich_web_evidence(
        {"source_uri": url, "title": title, "content": "B-tree"},
        objective="PostgreSQL B-tree",
    )
    assert row["metadata"]["version_hint"] == version


def test_report_body_budget_keeps_whole_blocks_and_discloses_omissions():
    from backend.research.workflow import ResearchWorkflowRunner

    result = ResearchWorkflowRunner._merge(
        "报告",
        ["## 结论\n\n可验证事实 [E1]。\n\n" + "很长的限定条件" * 150],
        [
            SimpleNamespace(
                citation_number=1,
                title="官方资料",
                source_uri="https://example.org",
                source_kind="web",
                metadata_json={},
            )
        ],
        body_limit=100,
    )
    body = result.split("\n\n", 1)[1].split("\n\n## 证据与来源", 1)[0]
    assert len(body) <= 100
    assert "可验证事实 [E1]。" in body
    assert "完整章节" in body
    assert "很长的限定条件" not in body


@pytest.mark.parametrize("fetch_fails", [False, True])
def test_web_completion_only_fetches_search_evidence_and_keeps_failures_visible(
    monkeypatch, fetch_fails
):
    from backend.research.workflow import ResearchWorkflowRunner
    from backend.core.errors import AppError

    url = "https://www.postgresql.org/docs/18/btree.html"
    calls = []
    deadline = time.monotonic() + 20

    def evidence(content):
        return SimpleNamespace(
            canonical_url=url,
            title="PostgreSQL: Documentation: 18: B-tree",
            content=content,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            retrieved_at=datetime.now(UTC),
        )

    class Runtime:
        def start(self):
            pass

        def close(self):
            calls.append("closed")

        def search(self, query, **kwargs):
            assert kwargs["allowed_domains"] == ("postgresql.org",)
            assert kwargs["deadline_at"] < deadline
            return SimpleNamespace(evidence=[evidence("PostgreSQL search excerpt")])

        def fetch(self, target, **kwargs):
            calls.append(target)
            assert target == url
            assert kwargs["deadline_at"] <= deadline
            assert kwargs["allowed_domains"] == ("postgresql.org",)
            if fetch_fails:
                raise AppError("WEB_FETCH_UNAVAILABLE", "网页不可用", status_code=503)
            return SimpleNamespace(
                evidence=[
                    evidence("PostgreSQL complete text with explicit index limits")
                ]
            )

    monkeypatch.setattr(
        "backend.research.workflow.get_settings",
        lambda: SimpleNamespace(web_research=SimpleNamespace(search_configured=True)),
    )
    monkeypatch.setattr(
        "backend.research.workflow.build_web_research_runtime", lambda _: Runtime()
    )
    rows = ResearchWorkflowRunner._retrieve_web(
        SimpleNamespace(cancelled=False),
        "PostgreSQL 官方文档",
        "B-tree 限制",
        3,
        deadline=deadline,
    )
    assert calls == [url, "closed"]
    if fetch_fails:
        assert rows[0]["metadata"]["fetch_error_code"] == "WEB_FETCH_UNAVAILABLE"
        assert rows[0]["content"] == "PostgreSQL search excerpt"
    else:
        assert "complete text" in rows[0]["content"]
        assert not rows[0]["metadata"].get("fetch_error_code")


def test_editorial_preamble_is_removed_but_reader_content_remains():
    from backend.research.workflow import ResearchWorkflowRunner

    assert (
        ResearchWorkflowRunner._without_duplicate_title(
            "限制", "以下是面向读者的正文内容：\n\n## 限制\n\n大小受限 [E1]。"
        )
        == "大小受限 [E1]。"
    )


def test_report_keeps_fenced_blocks_whole():
    from backend.research.workflow import ResearchWorkflowRunner

    assert ResearchWorkflowRunner._report_blocks(
        "文字\n\n```sql\nSELECT 1;\n\nSELECT 2;\n```\n\n末尾"
    ) == ["文字", "```sql\nSELECT 1;\n\nSELECT 2;\n```", "末尾"]


def test_report_excerpt_drops_orphan_heading_and_does_not_skip_qualifications():
    from backend.research.workflow import ResearchWorkflowRunner

    report = ResearchWorkflowRunner._merge(
        "标题",
        [
            "## 结论\n\n事实 [E1]。",
            "## 适用条件\n\n" + "必要限定条件。" * 80 + "\n\n可以使用。",
        ],
        [],
        body_limit=100,
    )
    body = report.split("## 证据与来源")[0]
    assert "事实 [E1]。" in body
    assert "## 适用条件" not in body
    assert "可以使用。" not in body


@pytest.mark.asyncio
async def test_failed_summary_verification_deduplicates_supported_claims(monkeypatch):
    from backend.research.workflow import ResearchWorkflowRunner
    from test_research_quality import Store, Token, snapshot

    runner = ResearchWorkflowRunner(store=Store())

    async def call(**kwargs):
        return SimpleNamespace(content="建议 [E1]。")

    async def review(**kwargs):
        return SimpleNamespace(
            verdict="insufficient", needs_revision=False, reason="缺少依据"
        )

    monkeypatch.setattr(runner, "_call_model", call)
    monkeypatch.setattr(runner, "_verify_claim", review)
    claim = SimpleNamespace(
        claim="等值比较受支持 [E1]", verdict="supported", reason="原文明确"
    )
    text = await runner._synthesize(
        snapshot=snapshot(),
        token=Token(),
        worker_id="worker",
        project_id="project",
        sections=["正文 [E1]"],
        evidence=[SimpleNamespace(citation_number=1, content="原文")],
        claims=[claim, claim],
        profile={"verify_synthesis": True},
    )
    assert text.count(claim.claim) == 1
    assert "未通过核验" in text


@pytest.mark.parametrize(
    "state",
    [
        {"question": "如果没有相关证据，请直接说明，不能猜测。"},
        {"hitl_answers": ["角色甲", "版本乙"]},
    ],
)
def test_explicit_no_evidence_instruction_and_clarification_limit_end_hitl(state):
    pipeline = load_pipeline(retrieve_documents=lambda *_: {})
    grade = pipeline.EvidenceGrade(
        relevance="strong",
        answerability="partial",
        ambiguity="missing_slot",
        route="clarify",
        missing_slots=["功能名"],
    )
    assert (
        pipeline._resolve_route(grade, {**state, "docs": [_doc("邻近资料")]})
        == "insufficient_evidence"
    )


def test_healthy_insufficient_tool_result_does_not_claim_provider_failure():
    from backend.tools.knowledge import _render_rag_result

    ctx = SimpleNamespace(store_rag_trace=lambda *_: None)
    text = _render_rag_result(
        ctx,
        {
            "docs": [],
            "rag_trace": {
                "route": "insufficient_evidence",
                "retrieval_outcome": "INSUFFICIENT_EVIDENCE",
            },
        },
    )
    assert "provider branches failed" not in text
    assert "INSUFFICIENT_EVIDENCE" in text


def test_synthesis_preserves_insufficient_evidence_and_original_user_intent():
    pipeline = load_pipeline(retrieve_documents=lambda *_: {})
    sends = pipeline._fanout_sub_questions(
        {"question": "不要追问", "sub_questions": ["甲", "乙"], "tenant_id": "default"}
    )
    assert all(send.arg["original_question"] == "不要追问" for send in sends)
    result = pipeline.synthesis(
        {
            "question": "甲和乙",
            "sub_results": [
                {
                    "question": "甲",
                    "docs": [],
                    "retrieval_status": "insufficient_evidence",
                },
                {"question": "乙", "docs": [], "retrieval_status": "no_knowledge"},
            ],
        }
    )
    assert result["retrieval_outcome"] == "INSUFFICIENT_EVIDENCE"
    assert result["route"] == "insufficient_evidence"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_expired_async_scope_owns_timeout_classification_before_clock_tick(
    monkeypatch, stream
):
    from backend.agent.runtime import AgentRuntime, AgentRuntimeInput
    from backend.providers import ProviderCode, ProviderError
    from test_agent_runtime import FakeCompiledAgent, _context

    class ExpiredScope:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            raise TimeoutError

        def expired(self):
            return True

    request_context, context = _context()
    context.deadline_at = time.monotonic() + 60
    runtime = AgentRuntime(agent=FakeCompiledAgent(), context=context)
    monkeypatch.setattr(
        "backend.agent.runtime.asyncio.timeout", lambda _: ExpiredScope()
    )
    try:
        with pytest.raises(ProviderError) as raised:
            request = AgentRuntimeInput(history=[], user_text="hello")
            if stream:
                async for _ in runtime.astream(request):
                    pass
            else:
                await runtime.ainvoke(request)
        assert raised.value.code == ProviderCode.PROVIDER_TIMEOUT
    finally:
        request_context.close()
