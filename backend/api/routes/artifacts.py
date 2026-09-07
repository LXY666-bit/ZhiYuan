from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend.artifacts import artifact_service
from backend.core.settings import get_settings
from backend.db.models import User
from backend.infra.auth import get_current_user


router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
async def download_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
):
    record, path = await run_in_threadpool(
        artifact_service.get_owned,
        username=current_user.username,
        tenant_id=get_settings().app.default_tenant_id,
        artifact_id=artifact_id,
    )
    return FileResponse(path, media_type=record.media_type, filename=record.filename)
