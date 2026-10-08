from types import SimpleNamespace
from datetime import UTC, datetime
import time

import pytest

from backend.model_control import ModelRole
from backend.research.profiles import resolve_research_profile
from backend.research.query_policy import build_web_queries, focus_question
from backend.research.query_policy import objective_match
from backend.research.source_quality import rank_web_evidence
from backend.research.workflow import ResearchWorkflowRunner
from backend.core.errors import AppError


def test_official_comparison_searches_each_target_with_short_focus():
    objective = "比较 PostgreSQL + pgvector、Milvus、Qdrant。300 万分块，优先引用官方文档，标明版本。"
    queries = build_web_queries(
        objective, focus_question(objective, "多租户隔离", objective)
    )
    assert len(queries) == 4
    assert all(len(query) <= 320 and "300" not in query for query in queries)
    assert all("documentation" in query for query in queries)
    assert all(
        "multitenancy" in query or "row level security" in query for query in queries
    )
    assert any("site:postgresql.org/docs/current" in query for query in queries)
    assert {query.split()[0] for query in queries} == {
        "milvus",
        "pgvector",
        "postgresql",
        "qdrant",
    }


def test_identical_sources_do_not_consume_domain_quota_but_conflicts_survive():
    def item(content, url):
        return {"source_uri": url, "title": "Alpha", "content": content}

    rows = rank_web_evidence(
        [
            item("Alpha supported", "https://alpha.example/docs/v1.10/tenant"),
            item("Alpha supported", "https://alpha.example/docs/v1.10/tenant"),
            item("Alpha unsupported", "https://alpha.example/docs/v1.10/tenant"),
            item("Alpha comparison", "https://blog.example/compare"),
        ],
        objective="Alpha",
        limit=3,
    )
    assert len(rows) == 3
    assert rows[0]["documentation_candidate"]
    assert not rows[0][
        "primary_source"
    ]  # A docs path is not proof of official ownership.
    assert rows[0]["version_hint"] == "1.10"
    assert len({row["stable_key"] for row in rows}) == 3


@pytest.mark.parametrize(
    "url,primary",
    [
        ("https://www.postgresql.org/docs/18/ddl-rowsecurity.html", True),
        ("https://postgresql.org.evil.example/docs/18/foo", False),
        ("https://github.com/pgvector/pgvector", True),
        ("https://github.com/pgvector/pgvector/issues/123", False),
        ("https://github.com/pgvector/pgvector-other", False),
    ],
)
def test_primary_documentation_requires_exact_owner_and_path(url, primary):
    assert (
        objective_match("PostgreSQL pgvector", locator=url)["primary_source"] is primary
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,thinking", [("dashscope.aliyuncs.com", False), ("other.example", None)]
)
async def test_research_request_bounds_tokens_without_injecting_unknown_provider_parameters(
    host, thinking
):
    options = {}

    class Model:
        async def ainvoke(self, messages, **kwargs):
            options.update(kwargs)
            return SimpleNamespace(content="bounded")

    class Models:
        def get(self, *args, **kwargs):
            return Model()

        def describe(self, *args, **kwargs):
            return SimpleNamespace(
                name="deepseek-v4-pro-0813",
                base_url=f"https://{host}/compatible-mode/v1",
                timeout_seconds=720,
            )

    runner = ResearchWorkflowRunner(models=Models())
    await runner._call_model(
        snapshot=SimpleNamespace(model_snapshot=None),
        token=SimpleNamespace(cancelled=False),
        role=ModelRole.ANSWER,
        profile=resolve_research_profile("deep"),
        prompt="summary",
        timeout_key="synthesis_timeout_seconds",
    )
    assert options["max_tokens"] == 1600
    assert options.get("extra_body", {}).get("enable_thinking") is thinking


def test_web_partial_failure_preserves_other_targets_and_public_error(monkeypatch):
    calls = []
    closed = []
    deadline = time.monotonic() + 10

    class Runtime:
        def start(self):
            pass

        def close(self):
            closed.append(True)

        def search(self, query, **kwargs):
            calls.append(kwargs)
            assert kwargs["deadline_at"] <= deadline
            if len(calls) == 1:
                raise AppError("WEB_DEADLINE_EXCEEDED", "受控超时", status_code=504)
            return SimpleNamespace(
                evidence=[
                    SimpleNamespace(
                        canonical_url=f"https://example.com/docs/{len(calls)}",
                        content_sha256=str(len(calls)),
                        title="Alpha",
                        content="支持隔离",
                        retrieved_at=datetime.now(UTC),
                    )
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
        "比较 PostgreSQL、Milvus、Qdrant，优先官方文档",
        "隔离",
        8,
        deadline=deadline,
    )
    assert len(calls) == 3
    assert len(rows) == 2
    assert rows[0]["metadata"]["search_error_code"] == "WEB_DEADLINE_EXCEEDED"
    assert closed == [True]


@pytest.mark.asyncio
async def test_truncated_generation_is_not_accepted_as_a_complete_result():
    class Models:
        def get(self, *args, **kwargs):
            async def invoke(*args, **kwargs):
                return SimpleNamespace(
                    content="unfinished", response_metadata={"finish_reason": "length"}
                )

            return SimpleNamespace(ainvoke=invoke)

        def describe(self, *args, **kwargs):
            return SimpleNamespace(name="test", timeout_seconds=30)

    with pytest.raises(AppError) as error:
        await ResearchWorkflowRunner(models=Models())._call_model(
            snapshot=SimpleNamespace(model_snapshot=None),
            token=SimpleNamespace(cancelled=False),
            role=ModelRole.ANSWER,
            profile=resolve_research_profile("quick"),
            prompt="write",
        )
    assert error.value.code == "RESEARCH_OUTPUT_LIMIT"
