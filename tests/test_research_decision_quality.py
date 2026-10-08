from types import SimpleNamespace
import asyncio

import pytest

from backend.research.profiles import resolve_research_profile
from backend.research.query_policy import build_web_queries, focus_question
from backend.research.source_quality import enrich_web_evidence, rank_web_evidence
from backend.research.workflow import ClaimDecision, ResearchWorkflowRunner


OBJECTIVE = "比较 Redis 7.2 Streams/XACK/WAIT 与 RabbitMQ 3.13，优先官方文档，核验确认、重试和死信。"


def test_versioned_comparison_searches_products_not_command_names():
    queries = build_web_queries(
        OBJECTIVE, focus_question(OBJECTIVE, "确认与死信", OBJECTIVE)
    )
    assert len(queries) == 2
    assert any("redis 7.2" in q and "site:redis.io/docs" in q for q in queries)
    assert any(
        "rabbitmq 3.13" in q and "site:rabbitmq.com/docs/3.13" in q for q in queries
    )
    assert all("acknowledgements" in q and "dead lettering" in q for q in queries)


@pytest.mark.parametrize(
    "url,content,note",
    [
        (
            "https://redis.io/docs/latest/operate/rs/databases/consistency",
            "Redis Enterprise consistency",
            "产品",
        ),
        ("https://www.rabbitmq.com/docs/4.3/confirms", "RabbitMQ confirms", "版本"),
        (
            "https://redis.io/docs/latest/commands/xreadgroup",
            "CLAIM was added in Redis 8.4",
            "新增",
        ),
    ],
)
def test_other_products_and_versions_are_explicitly_scoped(url, content, note):
    row = enrich_web_evidence(
        {"source_uri": url, "title": "Redis RabbitMQ", "content": content},
        objective=OBJECTIVE,
    )
    assert note in row["metadata"]["scope_note"]
    assert row["metadata"]["version_scope"] != "matched"


def test_correct_version_outranks_newer_official_docs_without_discarding_conflicts():
    rows = rank_web_evidence(
        [
            {
                "source_uri": "https://www.rabbitmq.com/docs/4.3/confirms",
                "content": "RabbitMQ confirms differ",
                "relevance_score": 1,
            },
            {
                "source_uri": "https://www.rabbitmq.com/docs/3.13/confirms",
                "content": "RabbitMQ confirmed messages",
                "relevance_score": 0.2,
            },
        ],
        objective=OBJECTIVE,
        limit=2,
    )
    assert len(rows) == 2
    assert rows[0]["version_hint"] == "3.13"


def test_evidence_context_includes_scope_and_command_version_history():
    evidence = SimpleNamespace(
        citation_number=1,
        source_uri="https://redis.io/docs/latest/commands/xreadgroup",
        title="XREADGROUP",
        content="PEL explanation " * 200
        + "\nHistory\nStarting with Redis version 8.4.0: Added CLAIM option.",
        metadata_json={"scope_note": "新版本语义不能外推", "version_scope": "unknown"},
    )
    text = ResearchWorkflowRunner._evidence_context([evidence], 100)
    assert "新版本语义不能外推" in text
    assert "8.4.0" in text


def test_official_entry_and_empty_fence_do_not_outrank_functional_docs():
    rows = rank_web_evidence(
        [
            {
                "source_uri": "https://www.rabbitmq.com/docs/3.13",
                "content": "RabbitMQ Documentation is Versioned Table of Contents",
            },
            {
                "source_uri": "https://redis.io/docs/latest/operate/rc/changelog/version-release-notes/7-2",
                "content": "``` [...] ```",
            },
            {
                "source_uri": "https://www.rabbitmq.com/docs/3.13/confirms",
                "content": "RabbitMQ manual acknowledgements requeue unacked deliveries",
            },
        ],
        objective=OBJECTIVE,
        limit=3,
    )
    assert rows[0]["source_uri"].endswith("/confirms")
    assert not rows[1]["substantive"]


def test_version_is_associated_with_source_product_not_every_compared_product():
    row = enrich_web_evidence(
        {
            "source_uri": "https://www.rabbitmq.com/docs/3.13/confirms",
            "title": "Redis RabbitMQ comparison",
            "content": "RabbitMQ 3.13 confirms",
        },
        objective=OBJECTIVE,
    )
    assert row["version_scope"] == "matched"


@pytest.mark.parametrize(
    "url",
    [
        "https://rabbitmq.com.evil.example/docs/3.13",
        "https://redis.io.evil.example/docs/latest/commands/xack",
    ],
)
def test_official_identity_does_not_trust_domain_prefixes(url):
    row = enrich_web_evidence(
        {"source_uri": url, "content": "Redis RabbitMQ acknowledgement"},
        objective=OBJECTIVE,
    )
    assert not row["primary_source"]


@pytest.mark.asyncio
async def test_decision_steps_wait_for_saved_facts_and_reuse_run_owned_evidence(
    monkeypatch,
):
    saved = []
    entered = asyncio.Event()
    release = asyncio.Event()
    facts_started = 0
    captures = {}
    steps = [
        {"step_key": str(i), "title": title}
        for i, title in enumerate(
            ["Redis 核心事实", "RabbitMQ 核心事实", "横向比较", "选型建议"], 1
        )
    ]
    store = SimpleNamespace(
        load_manifest=lambda _: {
            "project_id": "project",
            "plan": {"steps": steps},
            "profile": resolve_research_profile("deep"),
        },
        write_section_and_draft=lambda **kw: saved.append(kw["section_key"]),
        finalize_artifacts=lambda **kw: None,
    )
    runner = ResearchWorkflowRunner(store=store)
    request = SimpleNamespace(
        run=SimpleNamespace(id="run", fencing_token=1),
        user_text=OBJECTIVE,
        user_db_id=1,
        tenant_id="default",
    )

    async def section(**kw):
        nonlocal facts_started
        key = kw["step"]["step_key"]
        if key in {"1", "2"}:
            facts_started += 1
            if facts_started == 2:
                entered.set()
            await release.wait()
            material = [
                SimpleNamespace(
                    id=key,
                    citation_number=int(key),
                    title=key,
                    content=key,
                    source_uri=None,
                    source_kind="knowledge_base",
                    metadata_json={},
                )
            ]
        else:
            assert {"1", "2"}.issubset(saved)
            if key == "4":
                assert "3" in saved
            captures[key] = {item.id for item in kw["prior_evidence"]}
            assert len(kw["prior_claims"]) >= 2
            material = kw["prior_evidence"]
        return (
            kw["position"],
            key,
            key,
            "正文",
            material,
            False,
            0,
            ClaimDecision(claim=key, verdict="supported", reason="证据支持"),
        )

    async def synthesize(**_kw):
        return "综合结论 [E1]"

    monkeypatch.setattr(runner, "_research_section", section)
    monkeypatch.setattr(runner, "_synthesize", synthesize)
    task = asyncio.create_task(
        runner._run_workflow(
            snapshot=request,
            token=SimpleNamespace(append_partial=lambda _: None),
            worker_id="worker",
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert saved == []
        assert captures == {}
    finally:
        release.set()
        await task
    assert captures == {"3": {"1", "2"}, "4": {"1", "2"}}


@pytest.mark.asyncio
async def test_summary_with_rejected_facts_is_not_published_as_a_decision(monkeypatch):
    warnings = []
    deadlines = []
    store = SimpleNamespace(
        record_usage=lambda **kw: None,
        warning=lambda **kw: warnings.append(kw),
        load_manifest=lambda _: {"project_id": "project"},
    )
    runner = ResearchWorkflowRunner(store=store)
    request = SimpleNamespace(
        run=SimpleNamespace(id="run", fencing_token=1), user_text=OBJECTIVE
    )

    async def call(**kw):
        deadlines.append(kw["profile"]["writing_deadline"])
        if kw.get("schema"):
            return {
                "claim": "Redis 不会记录次数",
                "verdict": "unsupported",
                "reason": "XPENDING 有投递次数",
                "needs_revision": True,
                "issues": ["把投递计数说成不存在"],
            }
        return SimpleNamespace(
            content="## 综合结论\n\nRedis 不会记录次数，必须选择 RabbitMQ [E1]。"
        )

    monkeypatch.setattr(runner, "_call_model", call)
    text = await runner._synthesize(
        snapshot=request,
        token=SimpleNamespace(cancelled=False),
        worker_id="worker",
        project_id="project",
        sections=["投递计数 [E1]"],
        evidence=[
            SimpleNamespace(citation_number=1, content="XPENDING delivery count")
        ],
        claims=[
            ClaimDecision(
                claim="存在投递计数 [E1]", verdict="supported", reason="官方文档"
            )
        ],
        profile=resolve_research_profile("deep"),
    )
    assert "必须选择 RabbitMQ" not in text
    assert "存在投递计数" in text
    assert "RESEARCH_SYNTHESIS_UNVERIFIED" in {w["code"] for w in warnings}
    assert len(deadlines) == 2 and deadlines[0] == deadlines[1]
