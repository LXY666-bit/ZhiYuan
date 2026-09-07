"""DataQa（智能问数）REST 入口：创建即执行，事件流走 canonical Run 信道。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from starlette.concurrency import run_in_threadpool

from backend.core.settings import get_settings
from backend.dataqa.contracts import (
    DataQaAnalysisRequest,
    DataQaQueryCreateRequest,
    DataQaQueryListResponse,
    DataQaQueryV1,
)
from backend.dataqa.service import dataqa_service
from backend.dataqa.workflow import dataqa_workflow_runner
from backend.db.models import User
from backend.infra.auth import get_current_user
from backend.model_control import ModelRole, model_control_service
from backend.runs.agent_executor import run_agent_executor

router = APIRouter(prefix="/v1/dataqa/queries", tags=["dataqa"])


def _tenant() -> str:
    return get_settings().app.default_tenant_id


@router.post("", response_model=DataQaQueryV1, status_code=status.HTTP_201_CREATED)
async def create_query(
    request: DataQaQueryCreateRequest,
    current_user: User = Depends(get_current_user),
):
    record = await run_in_threadpool(
        dataqa_service.create_query,
        username=current_user.username,
        tenant_id=_tenant(),
        question=request.question.strip(),
        idempotency_key=request.idempotency_key,
    )
    if record.query.status == "pending":
        await run_agent_executor.spawn_once(
            username=current_user.username, run_id=record.run_id
        )
    return record.query


@router.get("", response_model=DataQaQueryListResponse)
async def list_queries(current_user: User = Depends(get_current_user)):
    queries = await run_in_threadpool(
        dataqa_service.list_queries,
        username=current_user.username,
        tenant_id=_tenant(),
    )
    return DataQaQueryListResponse(queries=queries)


@router.delete("/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_query(
    query_id: str, current_user: User = Depends(get_current_user)
) -> None:
    await run_in_threadpool(
        dataqa_service.delete_query,
        username=current_user.username,
        tenant_id=_tenant(),
        query_id=query_id,
    )


@router.get("/{query_id}", response_model=DataQaQueryV1)
async def get_query(query_id: str, current_user: User = Depends(get_current_user)):
    return await run_in_threadpool(
        dataqa_service.get_query,
        username=current_user.username,
        tenant_id=_tenant(),
        query_id=query_id,
    )


@router.post("/{query_id}/analysis", response_model=DataQaQueryV1)
async def create_analysis(
    query_id: str,
    request: DataQaAnalysisRequest,
    current_user: User = Depends(get_current_user),
):
    query = await run_in_threadpool(
        dataqa_service.get_query,
        username=current_user.username,
        tenant_id=_tenant(),
        query_id=query_id,
    )
    if query.result is not None and query.result.analysis is None:
        snapshot = model_control_service.runtime_snapshot(
            required_roles=frozenset({ModelRole.ANSWER})
        )
        analysis = await run_in_threadpool(
            dataqa_workflow_runner.analyze,
            question=query.question,
            result=query.result.model_dump(),
            model_snapshot=snapshot,
        )
        return await run_in_threadpool(
            dataqa_service.attach_analysis,
            username=current_user.username,
            tenant_id=_tenant(),
            query_id=query_id,
            analysis=analysis,
        )
    return await run_in_threadpool(
        dataqa_service.get_query,
        username=current_user.username,
        tenant_id=_tenant(),
        query_id=query_id,
    )
