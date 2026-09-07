from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from backend.artifacts import ArtifactService, artifact_service
from backend.core.errors import AppError, ErrorCode
from backend.db.models import Artifact, ResearchProject, Run, User
from backend.infra.database import SessionLocal
from backend.research.pdf import render_markdown_pdf
from backend.runs.state import ACTIVE_RUN_STATUSES


class ResearchArtifactRevisionService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        artifacts: ArtifactService = artifact_service,
    ) -> None:
        self._session_factory = session_factory
        self.artifacts = artifacts

    def revise_markdown(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        markdown: str,
        rebuild_pdf: bool,
    ) -> list[dict]:
        db: Session = self._session_factory()
        try:
            with db.begin():
                row = (
                    db.query(ResearchProject, User)
                    .join(User, User.id == ResearchProject.user_id)
                    .filter(
                        ResearchProject.id == project_id,
                        ResearchProject.tenant_id == tenant_id,
                        ResearchProject.deleted_at.is_(None),
                        User.username == username,
                    )
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise AppError(
                        ErrorCode.NOT_FOUND, "Research Project 不存在", status_code=404
                    )
                project, user = row
                if project.lifecycle_status != "frozen":
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "只有已审批研究报告可以创建编辑版本",
                        status_code=409,
                    )
                created = [
                    self.artifacts.write_in_session(
                        db,
                        tenant_id=tenant_id,
                        user_id=user.id,
                        owner_type="research_project",
                        owner_id=project.id,
                        logical_type="report_markdown",
                        state="final",
                        content=markdown.encode("utf-8"),
                        media_type="text/markdown",
                        filename="research-report.md",
                        metadata={"origin": "user_edit"},
                    )
                ]
                if rebuild_pdf:
                    created.append(
                        self.artifacts.write_in_session(
                            db,
                            tenant_id=tenant_id,
                            user_id=user.id,
                            owner_type="research_project",
                            owner_id=project.id,
                            logical_type="report_pdf",
                            state="final",
                            content=render_markdown_pdf(project.title, markdown),
                            media_type="application/pdf",
                            filename="research-report.pdf",
                            metadata={"origin": "user_edit"},
                        )
                    )
                return [
                    {
                        "id": artifact.id,
                        "logical_type": artifact.logical_type,
                        "state": artifact.state,
                        "version": artifact.version,
                        "parent_artifact_id": artifact.parent_artifact_id,
                        "filename": artifact.filename,
                        "media_type": artifact.media_type,
                        "sha256": artifact.sha256,
                        "size_bytes": artifact.size_bytes,
                        "download_url": f"/api/artifacts/{artifact.id}",
                    }
                    for artifact in created
                ]
        finally:
            db.close()

    def delete_artifact(
        self,
        *,
        username: str,
        tenant_id: str,
        project_id: str,
        artifact_id: str,
    ) -> None:
        db: Session = self._session_factory()
        storage_key: str | None = None
        try:
            with db.begin():
                owned = (
                    db.query(ResearchProject, User)
                    .join(User, User.id == ResearchProject.user_id)
                    .filter(
                        ResearchProject.id == project_id,
                        ResearchProject.tenant_id == tenant_id,
                        ResearchProject.deleted_at.is_(None),
                        User.username == username,
                    )
                    .with_for_update()
                    .first()
                )
                if owned is None:
                    raise AppError(
                        ErrorCode.NOT_FOUND, "Research Project 不存在", status_code=404
                    )
                project, user = owned
                artifact = (
                    db.query(Artifact)
                    .filter(
                        Artifact.id == artifact_id,
                        Artifact.tenant_id == tenant_id,
                        Artifact.user_id == user.id,
                        Artifact.owner_type == "research_project",
                        Artifact.owner_id == project.id,
                    )
                    .with_for_update()
                    .first()
                )
                if artifact is None:
                    raise AppError(ErrorCode.NOT_FOUND, "交付物不存在", status_code=404)
                if artifact.run_id and (
                    db.query(Run.id)
                    .filter(
                        Run.id == artifact.run_id,
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .first()
                ):
                    raise AppError(
                        ErrorCode.RUN_ACTIVE,
                        "运行中的交付物不能删除",
                        status_code=409,
                    )
                storage_key = artifact.storage_key
                (
                    db.query(Artifact)
                    .filter(Artifact.parent_artifact_id == artifact.id)
                    .update(
                        {Artifact.parent_artifact_id: artifact.parent_artifact_id},
                        synchronize_session=False,
                    )
                )
                db.delete(artifact)
            self.artifacts.delete_storage_key(storage_key)
        finally:
            db.close()


research_artifact_revision_service = ResearchArtifactRevisionService()
