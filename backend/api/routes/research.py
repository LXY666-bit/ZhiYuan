from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from backend.core.settings import get_settings
from backend.db.models import User
from backend.infra.auth import get_current_user
from backend.research.contracts import (
    ApprovalResponse,
    ApproveProjectRequest,
    PlanJobCreateRequest,
    PlanJobView,
    PlanResponse,
    PlanWriteRequest,
    MarkdownArtifactEditRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ResearchMetricsResponse,
    ResearchProjectV1,
    ResearchResourceListResponse,
    ResearchRunListResponse,
)
from backend.research.service import research_service
from backend.research.artifact_revision import research_artifact_revision_service
from backend.runs.agent_executor import run_agent_executor
from backend.research.attachments import (
    research_attachment_indexer,
    research_attachment_repository,
)
from backend.security.uploads import UploadPolicy, store_upload


router = APIRouter(prefix="/v1/research/projects", tags=["research"])


def _tenant() -> str:
    return get_settings().app.default_tenant_id


def _job_view(record) -> PlanJobView:
    return PlanJobView(
        id=record.id,
        project_id=record.project_id,
        status=record.status,
        fencing_token=record.fencing_token,
        attempts=record.attempts,
        result_plan_id=record.result_plan_id,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("", response_model=ResearchProjectV1, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
):
    return await run_in_threadpool(
        research_service.create_project,
        username=current_user.username,
        tenant_id=_tenant(),
        title=request.title,
        objective=request.objective,
        mode=request.mode,
        sources=request.sources,
        output_formats=request.output_formats,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(current_user: User = Depends(get_current_user)):
    projects = await run_in_threadpool(
        research_service.list_projects,
        username=current_user.username,
        tenant_id=_tenant(),
    )
    return ProjectListResponse(projects=projects)


@router.get("/{project_id}", response_model=ResearchProjectV1)
async def get_project(project_id: str, current_user: User = Depends(get_current_user)):
    return await run_in_threadpool(
        research_service.get_project,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str, current_user: User = Depends(get_current_user)
):
    await run_in_threadpool(
        research_service.soft_delete,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/clone",
    response_model=ResearchProjectV1,
    status_code=status.HTTP_201_CREATED,
)
async def clone_project(
    project_id: str, current_user: User = Depends(get_current_user)
):
    return await run_in_threadpool(
        research_service.clone_project,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )


@router.post(
    "/{project_id}/plan-jobs",
    response_model=PlanJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_plan_job(
    project_id: str,
    request: PlanJobCreateRequest,
    current_user: User = Depends(get_current_user),
):
    record = await run_in_threadpool(
        research_service.create_plan_job,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        idempotency_key=request.idempotency_key,
        expected_project_version=request.expected_project_version,
    )
    return _job_view(record)


@router.get("/{project_id}/plan-jobs/{job_id}", response_model=PlanJobView)
async def get_plan_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    record = await run_in_threadpool(
        research_service.get_plan_job,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        job_id=job_id,
    )
    return _job_view(record)


@router.post("/{project_id}/plan-jobs/{job_id}/cancel", response_model=PlanJobView)
async def cancel_plan_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    record = await run_in_threadpool(
        research_service.cancel_plan_job,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        job_id=job_id,
    )
    return _job_view(record)


@router.get("/{project_id}/plan", response_model=PlanResponse)
async def get_plan(project_id: str, current_user: User = Depends(get_current_user)):
    plan = await run_in_threadpool(
        research_service.get_plan,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )
    return PlanResponse(plan=plan)


@router.put("/{project_id}/plan", response_model=PlanResponse)
async def update_plan(
    project_id: str,
    request: PlanWriteRequest,
    current_user: User = Depends(get_current_user),
):
    plan = await run_in_threadpool(
        research_service.write_plan,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        expected_project_version=request.expected_project_version,
        steps=request.steps,
        origin="user",
    )
    return PlanResponse(plan=plan)


@router.post(
    "/{project_id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_project(
    project_id: str,
    request: ApproveProjectRequest,
    current_user: User = Depends(get_current_user),
):
    approved = await run_in_threadpool(
        research_service.approve,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        expected_project_version=request.expected_project_version,
        idempotency_key=request.idempotency_key,
    )
    await run_agent_executor.spawn_once(
        username=current_user.username, run_id=approved.run_id
    )
    return ApprovalResponse(
        project=approved.project,
        run_id=approved.run_id,
        thread_version=approved.thread_version,
    )


@router.post(
    "/{project_id}/retry",
    response_model=ApprovalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@router.post(
    "/{project_id}/rerun",
    response_model=ApprovalResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rerun_project(
    project_id: str,
    request: ApproveProjectRequest,
    current_user: User = Depends(get_current_user),
):
    approved = await run_in_threadpool(
        research_service.rerun,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        expected_project_version=request.expected_project_version,
        idempotency_key=request.idempotency_key,
    )
    await run_agent_executor.spawn_once(
        username=current_user.username, run_id=approved.run_id
    )
    return ApprovalResponse(
        project=approved.project,
        run_id=approved.run_id,
        thread_version=approved.thread_version,
    )


@router.get("/{project_id}/runs", response_model=ResearchRunListResponse)
async def list_research_runs(
    project_id: str, current_user: User = Depends(get_current_user)
):
    rows = await run_in_threadpool(
        research_service.list_runs,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )
    return ResearchRunListResponse(runs=rows)


@router.get("/{project_id}/evidence", response_model=ResearchResourceListResponse)
async def list_research_evidence(
    project_id: str,
    run_id: str | None = None,
    current_user: User = Depends(get_current_user),
):
    rows = await run_in_threadpool(
        research_service.list_evidence,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        run_id=run_id,
    )
    return ResearchResourceListResponse(items=rows)


@router.get("/{project_id}/steps", response_model=ResearchResourceListResponse)
async def list_research_steps(
    project_id: str,
    run_id: str | None = None,
    current_user: User = Depends(get_current_user),
):
    rows = await run_in_threadpool(
        research_service.list_steps,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        run_id=run_id,
    )
    return ResearchResourceListResponse(items=rows)


@router.get("/{project_id}/sections", response_model=ResearchResourceListResponse)
async def list_research_sections(
    project_id: str,
    run_id: str | None = None,
    current_user: User = Depends(get_current_user),
):
    rows = await run_in_threadpool(
        research_service.list_sections,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        run_id=run_id,
    )
    return ResearchResourceListResponse(items=rows)


@router.get("/{project_id}/claims", response_model=ResearchResourceListResponse)
async def list_research_claims(
    project_id: str,
    run_id: str | None = None,
    current_user: User = Depends(get_current_user),
):
    rows = await run_in_threadpool(
        research_service.list_claims,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        run_id=run_id,
    )
    return ResearchResourceListResponse(items=rows)


@router.get("/{project_id}/artifacts", response_model=ResearchResourceListResponse)
async def list_research_artifacts(
    project_id: str, current_user: User = Depends(get_current_user)
):
    rows = await run_in_threadpool(
        research_service.list_artifacts,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )
    return ResearchResourceListResponse(items=rows)


@router.delete(
    "/{project_id}/artifacts/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_research_artifact(
    project_id: str,
    artifact_id: str,
    current_user: User = Depends(get_current_user),
):
    await run_in_threadpool(
        research_artifact_revision_service.delete_artifact,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        artifact_id=artifact_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{project_id}/artifacts/markdown", response_model=ResearchResourceListResponse
)
async def edit_research_markdown(
    project_id: str,
    request: MarkdownArtifactEditRequest,
    current_user: User = Depends(get_current_user),
):
    rows = await run_in_threadpool(
        research_artifact_revision_service.revise_markdown,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        markdown=request.markdown,
        rebuild_pdf=request.rebuild_pdf,
    )
    return ResearchResourceListResponse(items=rows)


@router.get("/{project_id}/metrics", response_model=ResearchMetricsResponse)
async def get_research_metrics(
    project_id: str,
    run_id: str | None = None,
    current_user: User = Depends(get_current_user),
):
    metrics = await run_in_threadpool(
        research_service.metrics,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        run_id=run_id,
    )
    return ResearchMetricsResponse(metrics=metrics)


@router.post(
    "/{project_id}/attachments",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_research_attachment(
    project_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    storage = get_settings().storage
    policy = UploadPolicy(
        directory=storage.research_attachment_dir,
        max_bytes=storage.max_upload_bytes,
        max_pages=storage.max_document_pages,
        max_archive_entries=storage.max_archive_entries,
        max_uncompressed_bytes=storage.max_uncompressed_bytes,
        max_compression_ratio=storage.max_compression_ratio,
    )
    stored = await store_upload(file, policy)
    try:
        return await run_in_threadpool(
            research_attachment_repository.reserve_upload,
            username=current_user.username,
            tenant_id=_tenant(),
            project_id=project_id,
            upload=stored,
        )
    except BaseException:
        stored.path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/{project_id}/attachments", response_model=ResearchResourceListResponse)
async def list_research_attachments(
    project_id: str, current_user: User = Depends(get_current_user)
):
    rows = await run_in_threadpool(
        research_attachment_repository.list,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
    )
    return ResearchResourceListResponse(items=rows)


@router.post(
    "/{project_id}/attachments/{attachment_id}/retry",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_research_attachment(
    project_id: str,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
):
    return await run_in_threadpool(
        research_attachment_repository.retry,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        attachment_id=attachment_id,
    )


@router.delete(
    "/{project_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_research_attachment(
    project_id: str,
    attachment_id: str,
    current_user: User = Depends(get_current_user),
):
    build = await run_in_threadpool(
        research_attachment_repository.prepare_delete,
        username=current_user.username,
        tenant_id=_tenant(),
        project_id=project_id,
        attachment_id=attachment_id,
    )
    await run_in_threadpool(research_attachment_indexer.delete, build)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
