from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.models import get_model_control_service, router
from backend.core.errors import install_exception_handlers
from backend.infra.auth import get_current_user


class _FakeModelControl:
    def __init__(self) -> None:
        self.created = []
        self.assigned = []

    @staticmethod
    def control_plane():
        return {
            "schema_version": 1,
            "catalog_hash": "0" * 64,
            "api_key_configured": True,
            "profiles": (),
            "assignments": {
                "answer": None,
                "fast": None,
                "grader": None,
                "evaluator": None,
            },
            "requirements": {
                "answer": {
                    "supports_stream": True,
                    "supports_structured_output": False,
                    "temperature": 0.3,
                },
                "fast": {
                    "supports_stream": False,
                    "supports_structured_output": True,
                    "temperature": 0.2,
                },
                "grader": {
                    "supports_stream": False,
                    "supports_structured_output": True,
                    "temperature": 0.0,
                },
                "evaluator": {
                    "supports_stream": False,
                    "supports_structured_output": True,
                    "temperature": 0.0,
                },
            },
        }

    def create_profile(self, **kwargs):
        self.created.append(kwargs)

    def update_profile(self, **kwargs):
        self.created.append(kwargs)

    def delete_profile(self, **kwargs):
        self.created.append(kwargs)

    def assign_role(self, **kwargs):
        self.assigned.append(kwargs)


def _app(*, role: str = "admin"):
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router)
    fake = _FakeModelControl()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        username="alice",
        role=role,
    )
    app.dependency_overrides[get_model_control_service] = lambda: fake
    return app, fake


def test_admin_can_create_and_assign_profiles():
    app, fake = _app()
    with TestClient(app) as client:
        created = client.post(
            "/v1/models",
            json={
                "display_name": "Answer",
                "model_name": "answer-v2",
                "base_url": "https://models.example.test/v1",
                "timeout_seconds": 30,
                "supports_stream": True,
                "supports_structured_output": True,
                "enabled": True,
            },
        )
        assigned = client.put(
            "/v1/models/assignments/evaluator",
            json={"profile_id": "model_" + "a" * 32},
        )

    assert created.status_code == 201
    assert assigned.status_code == 200
    assert fake.created[0]["username"] == "alice"
    assert fake.created[0]["model_name"] == "answer-v2"
    assert fake.assigned == [
        {
            "username": "alice",
            "role": "evaluator",
            "profile_id": "model_" + "a" * 32,
        }
    ]


def test_non_admin_cannot_read_or_mutate_model_control():
    app, fake = _app(role="user")
    with TestClient(app) as client:
        listed = client.get("/v1/models")
        created = client.post(
            "/v1/models",
            json={
                "display_name": "Answer",
                "model_name": "answer-v2",
            },
        )

    assert listed.status_code == 403
    assert created.status_code == 403
    assert fake.created == []


@pytest.mark.parametrize(
    "method,path,expected_status",
    [
        ("post", "/v1/models", 201),
        ("put", "/v1/models/model_" + "a" * 32, 200),
    ],
)
@pytest.mark.parametrize("timeout_seconds", [600, 601, 720])
def test_model_form_can_save_extended_timeout(
    method, path, expected_status, timeout_seconds
):
    app, fake = _app()
    with TestClient(app) as client:
        response = client.request(
            method,
            path,
            json={
                "display_name": "研究模型",
                "provider": "openai",
                "model_name": "research-model",
                "base_url": "",
                "timeout_seconds": timeout_seconds,
                "supports_stream": True,
                "supports_structured_output": True,
                "enabled": True,
            },
        )
    assert response.status_code == expected_status
    assert fake.created[0]["timeout_seconds"] == timeout_seconds


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/v1/models"),
        ("put", "/v1/models/model_" + "a" * 32),
    ],
)
@pytest.mark.parametrize("timeout_seconds", [0, -1, 721])
def test_model_form_rejects_timeout_outside_supported_range(
    method, path, timeout_seconds
):
    app, fake = _app()
    with TestClient(app) as client:
        response = client.request(
            method,
            path,
            json={
                "display_name": "研究模型",
                "model_name": "research-model",
                "timeout_seconds": timeout_seconds,
            },
        )
    assert response.status_code == 422
    assert fake.created == []
