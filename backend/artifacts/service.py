from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.errors import AppError, ErrorCode
from backend.core.settings import get_settings
from backend.db.models import Artifact, User, utcnow
from backend.infra.database import SessionLocal


SessionFactory = Callable[[], Session]
_SAFE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    id: str
    tenant_id: str
    user_id: int
    run_id: str | None
    owner_type: str
    owner_id: str
    logical_type: str
    state: str
    version: int
    parent_artifact_id: str | None
    sha256: str
    size_bytes: int
    media_type: str
    filename: str
    created_at: str


class ArtifactService:
    """Tenant-scoped artifact metadata and atomic local object storage."""

    def __init__(
        self,
        session_factory: SessionFactory = SessionLocal,
        *,
        root: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.root = (root or get_settings().storage.artifact_dir).resolve()

    @staticmethod
    def _record(row: Artifact) -> ArtifactRecord:
        return ArtifactRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            run_id=row.run_id,
            owner_type=row.owner_type,
            owner_id=row.owner_id,
            logical_type=row.logical_type,
            state=row.state,
            version=row.version,
            parent_artifact_id=row.parent_artifact_id,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            media_type=row.media_type,
            filename=row.filename,
            created_at=row.created_at.isoformat(),
        )

    @staticmethod
    def _safe_part(value: str, field: str) -> str:
        normalized = (value or "").strip()
        if _SAFE_PART.fullmatch(normalized) is None:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"{field} 不是安全标识符",
                status_code=400,
            )
        return normalized

    def _resolve_key(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise AppError(
                ErrorCode.NOT_FOUND, "Artifact 不存在", status_code=404
            ) from exc
        return candidate

    def read_storage_key(self, storage_key: str) -> bytes:
        path = self._resolve_key(storage_key)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "Artifact 不存在", status_code=404)
        return path.read_bytes()

    def delete_storage_key(self, storage_key: str) -> None:
        """Best-effort removal for a storage key already authorized by a domain service."""
        try:
            self._resolve_key(storage_key).unlink(missing_ok=True)
        except OSError:
            # The metadata has already been removed. An inaccessible orphan is safer
            # than rolling back a completed deletion to a record without its content.
            pass

    def _write_atomic(self, storage_key: str, content: bytes) -> None:
        target = self._resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, target)
        finally:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass

    def write_in_session(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: int,
        owner_type: str,
        owner_id: str,
        logical_type: str,
        state: str,
        content: bytes,
        media_type: str,
        filename: str,
        run_id: str | None = None,
        parent_artifact_id: str | None = None,
        metadata: dict | None = None,
    ) -> Artifact:
        tenant_id = self._safe_part(tenant_id, "tenant_id")
        owner_type = self._safe_part(owner_type, "owner_type")
        owner_id = self._safe_part(owner_id, "owner_id")
        logical_type = self._safe_part(logical_type, "logical_type")
        if state not in {"draft", "final"}:
            raise AppError(
                ErrorCode.INVALID_REQUEST, "Artifact state 无效", status_code=400
            )
        digest = hashlib.sha256(content).hexdigest()
        now = utcnow()
        if state == "draft":
            row = (
                db.query(Artifact)
                .filter(
                    Artifact.run_id == run_id,
                    Artifact.logical_type == logical_type,
                    Artifact.state == "draft",
                )
                .with_for_update()
                .first()
            )
            if row is not None:
                self._write_atomic(row.storage_key, content)
                row.sha256 = digest
                row.size_bytes = len(content)
                row.media_type = media_type
                row.filename = filename
                row.metadata_json = metadata or {}
                row.updated_at = now
                return row
        version = (
            int(
                db.query(func.coalesce(func.max(Artifact.version), 0))
                .filter(
                    Artifact.tenant_id == tenant_id,
                    Artifact.owner_type == owner_type,
                    Artifact.owner_id == owner_id,
                    Artifact.logical_type == logical_type,
                )
                .scalar()
                or 0
            )
            + 1
        )
        if state == "final" and parent_artifact_id is None:
            previous = (
                db.query(Artifact.id)
                .filter(
                    Artifact.tenant_id == tenant_id,
                    Artifact.owner_type == owner_type,
                    Artifact.owner_id == owner_id,
                    Artifact.logical_type == logical_type,
                    Artifact.state == "final",
                )
                .order_by(Artifact.version.desc())
                .first()
            )
            parent_artifact_id = previous[0] if previous else None
        artifact_id = f"art_{uuid4().hex}"
        suffix = Path(filename).suffix.lower() or ".bin"
        storage_key = "/".join(
            (tenant_id, str(user_id), owner_type, owner_id, f"{artifact_id}{suffix}")
        )
        self._write_atomic(storage_key, content)
        row = Artifact(
            id=artifact_id,
            tenant_id=tenant_id,
            user_id=user_id,
            run_id=run_id,
            owner_type=owner_type,
            owner_id=owner_id,
            logical_type=logical_type,
            state=state,
            version=version,
            parent_artifact_id=parent_artifact_id,
            storage_key=storage_key,
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
            filename=Path(filename).name,
            metadata_json=metadata or {},
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        return row

    def write(self, **kwargs: Any) -> ArtifactRecord:
        db = self._session_factory()
        try:
            with db.begin():
                return self._record(self.write_in_session(db, **kwargs))
        finally:
            db.close()

    def get_owned(
        self, *, username: str, tenant_id: str, artifact_id: str
    ) -> tuple[ArtifactRecord, Path]:
        db = self._session_factory()
        try:
            row = (
                db.query(Artifact)
                .join(User, User.id == Artifact.user_id)
                .filter(
                    Artifact.id == artifact_id,
                    Artifact.tenant_id == tenant_id,
                    User.username == username,
                )
                .first()
            )
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND, "Artifact 不存在", status_code=404)
            path = self._resolve_key(row.storage_key)
            if not path.is_file():
                raise AppError(ErrorCode.NOT_FOUND, "Artifact 不存在", status_code=404)
            return self._record(row), path
        finally:
            db.close()


artifact_service = ArtifactService()
