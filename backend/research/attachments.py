from __future__ import annotations

from contextlib import closing

from dataclasses import dataclass
from datetime import timedelta
from threading import Event, Thread
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.core.errors import AppError, ErrorCode
from backend.core.settings import get_settings
from backend.db.models import (
    ResearchAttachment,
    ResearchAttachmentJob,
    ResearchProject,
    User,
    utcnow,
)
from backend.indexing.document_loader import DocumentArtifactMetadata, DocumentLoader
from backend.indexing.milvus_client import MilvusSettings
from backend.indexing.milvus_writer import MilvusWriter
from backend.infra.database import SessionLocal
from backend.security.uploads import StoredUpload


SessionFactory = Callable[[], Session]
RESEARCH_COLLECTION_SUFFIX = "_research_v1"


@dataclass(frozen=True, slots=True)
class AttachmentBuild:
    job_id: str
    fencing_token: int
    attachment_id: str
    project_id: str
    tenant_id: str
    version_key: str
    filename: str
    storage_key: str
    vector_collection: str


class ResearchAttachmentRepository:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _owned(
        db: Session,
        username: str,
        tenant_id: str,
        project_id: str,
        *,
        lock: bool = False,
    ) -> tuple[ResearchProject, User]:
        query = (
            db.query(ResearchProject, User)
            .join(User, User.id == ResearchProject.user_id)
            .filter(
                ResearchProject.id == project_id,
                ResearchProject.tenant_id == tenant_id,
                ResearchProject.deleted_at.is_(None),
                User.username == username,
            )
        )
        if lock:
            query = query.with_for_update()
        row = query.first()
        if row is None:
            raise AppError(
                ErrorCode.NOT_FOUND, "Research Project 不存在", status_code=404
            )
        return row

    def reserve_upload(
        self, *, username: str, tenant_id: str, project_id: str, upload: StoredUpload
    ) -> dict:
        with closing(self._session_factory()) as db:
            with db.begin():
                project, user = self._owned(
                    db, username, tenant_id, project_id, lock=True
                )
                if project.lifecycle_status not in {"draft", "awaiting_approval"}:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "已审批项目不能修改附件",
                        status_code=409,
                    )
                attachment_id = f"ratt_{uuid4().hex}"
                version_key = f"rattv_{uuid4().hex}"
                collection = f"{MilvusSettings.from_env().collection_name}{RESEARCH_COLLECTION_SUFFIX}"
                now = utcnow()
                attachment = ResearchAttachment(
                    id=attachment_id,
                    project_id=project.id,
                    tenant_id=tenant_id,
                    user_id=user.id,
                    version_key=version_key,
                    filename=upload.original_name,
                    media_type=upload.media_type,
                    storage_key=upload.object_key,
                    sha256=upload.content_sha256,
                    size_bytes=upload.size_bytes,
                    status="pending",
                    vector_collection=collection,
                    created_at=now,
                    updated_at=now,
                )
                job = ResearchAttachmentJob(
                    id=f"rattjob_{uuid4().hex}",
                    attachment_id=attachment.id,
                    status="pending",
                    attempts=0,
                    fencing_token=0,
                    created_at=now,
                    updated_at=now,
                )
                db.add_all((attachment, job))
                project.version += 1
                project.updated_at = now
                db.flush()
                return self._view(attachment, job.id)

    def list(self, *, username: str, tenant_id: str, project_id: str) -> list[dict]:
        with closing(self._session_factory()) as db:
            project, _user = self._owned(db, username, tenant_id, project_id)
            rows = (
                db.query(ResearchAttachment)
                .filter(ResearchAttachment.project_id == project.id)
                .order_by(ResearchAttachment.created_at.asc())
                .all()
            )
            return [self._view(row) for row in rows]

    @staticmethod
    def _view(row: ResearchAttachment, job_id: str | None = None) -> dict:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "version_key": row.version_key,
            "filename": row.filename,
            "media_type": row.media_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "status": row.status,
            "job_id": job_id,
            "created_at": row.created_at.isoformat(),
        }

    def retry(
        self, *, username: str, tenant_id: str, project_id: str, attachment_id: str
    ) -> dict:
        with closing(self._session_factory()) as db:
            with db.begin():
                project, _user = self._owned(
                    db, username, tenant_id, project_id, lock=True
                )
                if project.lifecycle_status not in {"draft", "awaiting_approval"}:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "已审批项目不能重试附件",
                        status_code=409,
                    )
                attachment = (
                    db.query(ResearchAttachment)
                    .filter(
                        ResearchAttachment.id == attachment_id,
                        ResearchAttachment.project_id == project.id,
                    )
                    .with_for_update()
                    .first()
                )
                if attachment is None:
                    raise AppError(
                        ErrorCode.NOT_FOUND,
                        "Research Attachment 不存在",
                        status_code=404,
                    )
                active = (
                    db.query(ResearchAttachmentJob.id)
                    .filter(
                        ResearchAttachmentJob.attachment_id == attachment.id,
                        ResearchAttachmentJob.status.in_(("pending", "running")),
                    )
                    .first()
                )
                if active:
                    raise AppError(
                        ErrorCode.RUN_ACTIVE, "附件已有活跃 Index Job", status_code=409
                    )
                job = ResearchAttachmentJob(
                    id=f"rattjob_{uuid4().hex}",
                    attachment_id=attachment.id,
                    status="pending",
                    attempts=0,
                    fencing_token=0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                attachment.status = "pending"
                attachment.updated_at = utcnow()
                db.add(job)
                db.flush()
                return self._view(attachment, job.id)

    def prepare_delete(
        self, *, username: str, tenant_id: str, project_id: str, attachment_id: str
    ) -> AttachmentBuild:
        with closing(self._session_factory()) as db:
            with db.begin():
                project, _user = self._owned(
                    db, username, tenant_id, project_id, lock=True
                )
                if project.lifecycle_status not in {"draft", "awaiting_approval"}:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "已审批项目不能删除附件",
                        status_code=409,
                    )
                attachment = (
                    db.query(ResearchAttachment)
                    .filter(
                        ResearchAttachment.id == attachment_id,
                        ResearchAttachment.project_id == project.id,
                    )
                    .with_for_update()
                    .first()
                )
                if attachment is None:
                    raise AppError(
                        ErrorCode.NOT_FOUND,
                        "Research Attachment 不存在",
                        status_code=404,
                    )
                active = (
                    db.query(ResearchAttachmentJob.id)
                    .filter(
                        ResearchAttachmentJob.attachment_id == attachment.id,
                        ResearchAttachmentJob.status.in_(("pending", "running")),
                    )
                    .first()
                )
                if active:
                    raise AppError(
                        ErrorCode.RUN_ACTIVE, "附件仍有活跃 Index Job", status_code=409
                    )
                attachment.status = "deleting"
                attachment.updated_at = utcnow()
                return AttachmentBuild(
                    "",
                    0,
                    attachment.id,
                    attachment.project_id,
                    attachment.tenant_id,
                    attachment.version_key,
                    attachment.filename,
                    attachment.storage_key,
                    attachment.vector_collection,
                )

    def finish_delete(self, build: AttachmentBuild) -> None:
        with closing(self._session_factory()) as db:
            with db.begin():
                row = (
                    db.query(ResearchAttachment)
                    .filter(
                        ResearchAttachment.id == build.attachment_id,
                        ResearchAttachment.project_id == build.project_id,
                        ResearchAttachment.version_key == build.version_key,
                        ResearchAttachment.status == "deleting",
                    )
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise AppError(
                        ErrorCode.RUN_STATE_CONFLICT,
                        "附件删除状态已变化",
                        status_code=409,
                    )
                db.delete(row)

    def claim(self, *, worker_id: str, lease_seconds: int) -> AttachmentBuild | None:
        with closing(self._session_factory()) as db:
            with db.begin():
                now = utcnow()
                query = (
                    db.query(ResearchAttachmentJob, ResearchAttachment)
                    .join(
                        ResearchAttachment,
                        ResearchAttachment.id == ResearchAttachmentJob.attachment_id,
                    )
                    .filter(
                        (ResearchAttachmentJob.status == "pending")
                        | (
                            (ResearchAttachmentJob.status == "running")
                            & (ResearchAttachmentJob.lease_expires_at < now)
                        )
                    )
                    .order_by(ResearchAttachmentJob.created_at.asc())
                )
                if db.get_bind().dialect.name == "postgresql":
                    query = query.with_for_update(
                        skip_locked=True, of=ResearchAttachmentJob
                    )
                row = query.first()
                if row is None:
                    return None
                job, attachment = row
                job.status = "running"
                job.owner_worker_id = worker_id
                job.fencing_token += 1
                job.attempts += 1
                job.heartbeat_at = now
                job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                job.updated_at = now
                attachment.status = "indexing"
                attachment.updated_at = now
                return AttachmentBuild(
                    job.id,
                    job.fencing_token,
                    attachment.id,
                    attachment.project_id,
                    attachment.tenant_id,
                    attachment.version_key,
                    attachment.filename,
                    attachment.storage_key,
                    attachment.vector_collection,
                )

    def finish(
        self,
        build: AttachmentBuild,
        *,
        worker_id: str,
        success: bool,
        error_code: str | None = None,
    ) -> None:
        with closing(self._session_factory()) as db:
            with db.begin():
                row = (
                    db.query(ResearchAttachmentJob, ResearchAttachment)
                    .join(
                        ResearchAttachment,
                        ResearchAttachment.id == ResearchAttachmentJob.attachment_id,
                    )
                    .filter(
                        ResearchAttachmentJob.id == build.job_id,
                        ResearchAttachmentJob.owner_worker_id == worker_id,
                        ResearchAttachmentJob.fencing_token == build.fencing_token,
                    )
                    .with_for_update()
                    .first()
                )
                if row is None:
                    return
                job, attachment = row
                job.status = "completed" if success else "failed"
                job.error_code = error_code
                job.error_detail_redacted = (
                    None if success else "附件索引失败，请重试。"
                )
                job.owner_worker_id = None
                job.lease_expires_at = None
                job.updated_at = utcnow()
                attachment.status = "indexed" if success else "failed"
                attachment.updated_at = utcnow()

    def heartbeat(
        self,
        build: AttachmentBuild,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        with closing(self._session_factory()) as db:
            with db.begin():
                now = utcnow()
                updated = (
                    db.query(ResearchAttachmentJob)
                    .filter(
                        ResearchAttachmentJob.id == build.job_id,
                        ResearchAttachmentJob.owner_worker_id == worker_id,
                        ResearchAttachmentJob.fencing_token == build.fencing_token,
                        ResearchAttachmentJob.status == "running",
                    )
                    .update(
                        {
                            ResearchAttachmentJob.heartbeat_at: now,
                            ResearchAttachmentJob.lease_expires_at: now
                            + timedelta(seconds=lease_seconds),
                            ResearchAttachmentJob.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                )
                return updated == 1


class ResearchAttachmentIndexer:
    def __init__(
        self,
        *,
        repository: ResearchAttachmentRepository | None = None,
        loader: DocumentLoader | None = None,
        writer: MilvusWriter | None = None,
    ) -> None:
        self.repository = repository or ResearchAttachmentRepository()
        self.loader = loader or DocumentLoader()
        self.writer = writer or MilvusWriter()

    def run_once(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        heartbeat_seconds: int | None = None,
    ) -> bool:
        build = self.repository.claim(worker_id=worker_id, lease_seconds=lease_seconds)
        if build is None:
            return False
        stop = Event()
        ownership_lost = Event()

        def heartbeat_loop() -> None:
            interval = max(1, heartbeat_seconds or max(1, lease_seconds // 3))
            while not stop.wait(interval):
                if not self.repository.heartbeat(
                    build, worker_id=worker_id, lease_seconds=lease_seconds
                ):
                    ownership_lost.set()
                    return

        heartbeat = Thread(
            target=heartbeat_loop,
            name=f"research-attachment-heartbeat:{build.job_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            root = get_settings().storage.research_attachment_dir.resolve()
            path = (root / build.storage_key).resolve()
            if path.parent != root or not path.is_file():
                raise FileNotFoundError("research attachment object missing")
            metadata = DocumentArtifactMetadata(
                tenant_id=build.tenant_id,
                knowledge_base_id=f"research:{build.project_id}",
                document_id=build.attachment_id,
                document_version_id=build.version_key,
                index_version="research-v1",
            )
            scope = self.writer.build_version_scope(
                tenant_id=build.tenant_id,
                knowledge_base_id=f"research:{build.project_id}",
                document_id=build.attachment_id,
                document_version_id=build.version_key,
                index_version="research-v1",
                collection_name=build.vector_collection,
            )
            # Every attempt owns one exact attachment version. Clearing that scope first
            # makes a retry idempotent after a partial Milvus write.
            self.writer.ensure_versioned_collection(build.vector_collection)
            self.writer.delete_by_version(scope)
            documents = self.loader.load_document(
                str(path), build.filename, metadata=metadata
            )
            leaf = [item for item in documents if int(item.get("chunk_level", 0)) == 3]
            receipt = self.writer.write_versioned_documents(
                leaf, collection_name=build.vector_collection
            )
            verification = self.writer.verify_receipt(receipt)
            if not verification.exact:
                raise RuntimeError("research attachment exact verification failed")
            if not ownership_lost.is_set():
                self.repository.finish(build, worker_id=worker_id, success=True)
        except BaseException as exc:
            if not ownership_lost.is_set():
                self.repository.finish(
                    build,
                    worker_id=worker_id,
                    success=False,
                    error_code=str(
                        getattr(exc, "code", "RESEARCH_ATTACHMENT_INDEX_FAILED")
                    )[:64],
                )
        finally:
            stop.set()
            heartbeat.join(timeout=5)
        return True

    def delete(self, build: AttachmentBuild) -> None:
        scope = self.writer.build_version_scope(
            tenant_id=build.tenant_id,
            knowledge_base_id=f"research:{build.project_id}",
            document_id=build.attachment_id,
            document_version_id=build.version_key,
            index_version="research-v1",
            collection_name=build.vector_collection,
        )
        self.writer.delete_by_version(scope)
        root = get_settings().storage.research_attachment_dir.resolve()
        path = (root / build.storage_key).resolve()
        if path.parent != root:
            raise AppError(
                ErrorCode.INVALID_REQUEST, "附件存储路径无效", status_code=400
            )
        path.unlink(missing_ok=True)
        self.repository.finish_delete(build)


research_attachment_repository = ResearchAttachmentRepository()
research_attachment_indexer = ResearchAttachmentIndexer(
    repository=research_attachment_repository
)
