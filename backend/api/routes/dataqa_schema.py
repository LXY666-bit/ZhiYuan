"""Administrator data dictionary for grounded DataQa."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from starlette.concurrency import run_in_threadpool

from backend.capabilities.control_service import capability_control_service
from backend.core.errors import AppError, ErrorCode
from backend.dataqa.contracts import (
    DataQaSemanticMetadataRequest,
    DataQaSemanticSchemaResponse,
)
from backend.dataqa.semantic_schema import semantic_schema_service
from backend.db.models import User
from backend.infra.auth import require_admin

router = APIRouter(prefix="/v1/dataqa/semantic-schema", tags=["dataqa"])


def _catalog_tables() -> list[dict]:
    runtime = capability_control_service.sql_runtime
    if runtime is None:
        raise AppError(
            ErrorCode.TOOL_UNAVAILABLE, "SQL Assistant 未启用", status_code=503
        )
    return list(runtime.describe_schema(()).get("tables") or [])


@router.get("", response_model=DataQaSemanticSchemaResponse)
async def get_semantic_schema(_: User = Depends(require_admin)):
    tables = await run_in_threadpool(_catalog_tables)
    schema = await run_in_threadpool(semantic_schema_service.load, tables)
    return DataQaSemanticSchemaResponse.model_validate(schema.public_dict())


@router.put("/metadata", response_model=DataQaSemanticSchemaResponse)
async def put_semantic_metadata(
    request: DataQaSemanticMetadataRequest,
    current_user: User = Depends(require_admin),
):
    tables = await run_in_threadpool(_catalog_tables)
    await run_in_threadpool(
        semantic_schema_service.upsert,
        tables=tables,
        schema_name=request.schema_name,
        table_name=request.table_name,
        column_name=request.column_name,
        description=request.description,
        aliases=request.aliases,
        updated_by_user_id=current_user.id,
    )
    schema = await run_in_threadpool(semantic_schema_service.load, tables)
    return DataQaSemanticSchemaResponse.model_validate(schema.public_dict())


@router.delete("/metadata", status_code=status.HTTP_204_NO_CONTENT)
async def delete_semantic_metadata(
    request: DataQaSemanticMetadataRequest,
    _: User = Depends(require_admin),
):
    await run_in_threadpool(
        semantic_schema_service.delete,
        schema_name=request.schema_name,
        table_name=request.table_name,
        column_name=request.column_name,
    )
