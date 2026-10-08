from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from backend.agent.models import ModelRegistry, structured_output
from backend.core.settings import ModelSettings
from backend.model_control import ModelRole
from backend.research.contracts import PlannerDecision
from backend.research.planner import ResearchPlanner
from backend.research.profiles import resolve_research_profile
from backend.research.workflow import ResearchWorkflowRunner


@pytest.fixture
async def compatible_provider():
    requests = []
    arguments = {
        "title": "数据库比较",
        "steps": [
            {
                "step_key": f"step-{index}",
                "title": dimension,
                "question": f"PostgreSQL 和 Milvus 的{dimension}如何比较？",
                "sources": ["knowledge_base"],
            }
            for index, dimension in enumerate(["功能", "运维", "成本"], 1)
        ],
    }

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "response_format" in payload:
            return httpx.Response(
                400,
                json={"error": {"code": "invalid_parameter_error"}},
            )
        name = payload["tools"][0]["function"]["name"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "test-model",
                "object": "chat.completion",
                "created": 0,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-test",
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        async_client = httpx.AsyncClient(transport=transport)
        registry = ModelRegistry(
            settings=SimpleNamespace(
                models=ModelSettings(
                    _env_file=None,
                    ARK_API_KEY="offline-test-key",
                    BASE_URL="https://models.example.test/v1",
                    FAST_MODEL="test-model",
                )
            ),
            initializer=lambda **kwargs: ChatOpenAI(
                **{
                    key: value
                    for key, value in kwargs.items()
                    if key != "model_provider"
                },
                http_client=client,
                http_async_client=async_client,
            ),
        )
        try:
            yield registry, requests, arguments
        finally:
            await async_client.aclose()


def test_research_plan_accepts_provider_without_json_schema(compatible_provider):
    registry, requests, _ = compatible_provider
    result = ResearchPlanner(models=registry).generate(
        objective="比较 PostgreSQL 和 Milvus 的功能、运维和成本",
        title="数据库比较",
        mode="quick",
        sources=["knowledge_base"],
        model_snapshot=registry.environment_snapshot(),
        cancellation=lambda: False,
    )

    assert result.usage_status == "completed"
    assert result.error_code is None
    assert len(result.steps) == 3
    assert len(requests) == 1
    assert "response_format" not in requests[0]
    assert requests[0]["model"] == "test-model"
    assert requests[0]["tool_choice"]["function"]["name"] == "PlannerDecision"


async def test_async_structured_output_parses_and_validates_tool_arguments(
    compatible_provider,
):
    registry, requests, _ = compatible_provider
    model = registry.get(ModelRole.FAST, snapshot=registry.environment_snapshot())

    result = await structured_output(model, PlannerDecision).ainvoke("生成研究计划")

    assert isinstance(result, PlannerDecision)
    assert result.steps[0].title == "功能"
    assert len(requests) == 1
    assert "response_format" not in requests[0]


async def test_research_structured_request_transmits_output_budget(compatible_provider):
    registry, requests, _ = compatible_provider
    result = await ResearchWorkflowRunner(models=registry)._call_model(
        snapshot=SimpleNamespace(model_snapshot=registry.environment_snapshot()),
        token=SimpleNamespace(cancelled=False),
        role=ModelRole.FAST,
        profile=resolve_research_profile("deep"),
        prompt="生成研究计划",
        schema=PlannerDecision,
        timeout_key="review_timeout_seconds",
    )
    assert isinstance(result, PlannerDecision)
    assert (
        requests[0].get("max_tokens", requests[0].get("max_completion_tokens")) == 1000
    )


@pytest.mark.parametrize("field,value", [("title", ""), ("steps", "invalid")])
def test_structured_output_rejects_invalid_tool_arguments(
    compatible_provider, field, value
):
    registry, requests, arguments = compatible_provider
    arguments[field] = value
    model = registry.get(ModelRole.FAST, snapshot=registry.environment_snapshot())

    with pytest.raises(ValidationError):
        structured_output(model, PlannerDecision).invoke("生成研究计划")

    assert len(requests) == 1
