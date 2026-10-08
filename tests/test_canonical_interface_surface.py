from inspect import signature

from fastapi import FastAPI

from backend.api.router import router
from backend.documents.catalog import DocumentCatalog


def test_application_exposes_only_canonical_interfaces() -> None:
    app = FastAPI()
    app.include_router(router)
    assert set(app.openapi()["paths"]) == {
        "/api/artifacts/{artifact_id}",
        "/auth/login",
        "/auth/logout",
        "/auth/logout-all",
        "/auth/me",
        "/auth/refresh",
        "/auth/register",
        "/documents",
        "/documents/delete/async/{filename}",
        "/documents/delete/jobs",
        "/documents/delete/jobs/{job_id}",
        "/documents/upload/async",
        "/documents/upload/jobs",
        "/documents/upload/jobs/{job_id}",
        "/health/live",
        "/health/ready",
        "/v1/capabilities",
        "/v1/capabilities/control-plane",
        "/v1/capabilities/skills",
        "/v1/capabilities/skills/{name}",
        "/v1/capabilities/tools",
        "/v1/capabilities/tools/{name}",
        "/v1/capabilities/sql-assistant",
        "/v1/capabilities/web-research",
        "/v1/dataqa/queries",
        "/v1/dataqa/queries/{query_id}",
        "/v1/dataqa/queries/{query_id}/analysis",
        "/v1/dataqa/semantic-schema",
        "/v1/dataqa/semantic-schema/metadata",
        "/v1/models",
        "/v1/models/assignments/{role}",
        "/v1/models/{profile_id}",
        "/v1/rag-evaluations/datasets",
        "/v1/rag-evaluations/datasets/{dataset_id}",
        "/v1/rag-evaluations/jobs",
        "/v1/rag-evaluations/jobs/{job_id}",
        "/v1/rag-evaluations/jobs/{job_id}/cancel",
        "/v1/rag-evaluations/jobs/{job_id}/cases",
        "/v1/research/projects",
        "/v1/research/projects/{project_id}",
        "/v1/research/projects/{project_id}/approve",
        "/v1/research/projects/{project_id}/artifacts",
        "/v1/research/projects/{project_id}/artifacts/{artifact_id}",
        "/v1/research/projects/{project_id}/artifacts/markdown",
        "/v1/research/projects/{project_id}/attachments",
        "/v1/research/projects/{project_id}/attachments/{attachment_id}",
        "/v1/research/projects/{project_id}/attachments/{attachment_id}/retry",
        "/v1/research/projects/{project_id}/claims",
        "/v1/research/projects/{project_id}/clone",
        "/v1/research/projects/{project_id}/evidence",
        "/v1/research/projects/{project_id}/metrics",
        "/v1/research/projects/{project_id}/plan",
        "/v1/research/projects/{project_id}/plan-jobs",
        "/v1/research/projects/{project_id}/plan-jobs/{job_id}",
        "/v1/research/projects/{project_id}/plan-jobs/{job_id}/cancel",
        "/v1/research/projects/{project_id}/rerun",
        "/v1/research/projects/{project_id}/retry",
        "/v1/research/projects/{project_id}/runs",
        "/v1/research/projects/{project_id}/sections",
        "/v1/research/projects/{project_id}/steps",
        "/v1/runs/{run_id}",
        "/v1/runs/{run_id}/cancel",
        "/v1/runs/{run_id}/events",
        "/v1/runs/{run_id}/resume",
        "/v1/runs/{run_id}/stream",
        "/v1/threads",
        "/v1/threads/{thread_id}",
        "/v1/threads/{thread_id}/messages",
        "/v1/threads/{thread_id}/runs",
        "/v1/threads/{thread_id}/runs/stream",
    }


def test_cleanup_grace_is_not_exposed_to_callers() -> None:
    assert "cleanup_grace" not in signature(DocumentCatalog.publish).parameters
    assert "cleanup_grace" not in signature(DocumentCatalog.reserve_upload).parameters
    assert "cleanup_grace" not in signature(DocumentCatalog.retire).parameters
