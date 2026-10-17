import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.dataqa import router
from backend.db.models import User
from backend.infra.auth import get_current_user


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "", None),
        ("get", "/qa_owned", None),
        ("delete", "/qa_owned", None),
        ("post", "", {"question": "销量多少", "idempotency_key": "request-key"}),
        ("post", "/qa_owned/analysis", {"idempotency_key": "analysis-key"}),
    ],
)
def test_all_dataqa_endpoints_reject_non_admin_before_execution(method, path, body):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: User(
        username="user", role="user", password_hash="unused"
    )
    with TestClient(app) as client:
        response = client.request(method, "/v1/dataqa/queries" + path, json=body)
    assert response.status_code == 403
