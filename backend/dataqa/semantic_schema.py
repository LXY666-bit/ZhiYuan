"""Business semantics layered on top of the SQL Assistant catalog.

Metadata is intentionally advisory.  It is joined with the already-authorized
runtime catalog and can therefore never make a relation or column queryable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.core.errors import AppError, ErrorCode
from backend.db.models import DataQaSemanticMetadata, utcnow
from backend.infra.database import SessionLocal

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_DESCRIPTION = 1_000
_MAX_ALIASES = 20
_MAX_ALIAS = 100


def _text(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise AppError(
            ErrorCode.INVALID_REQUEST, f"{field} 必须是文本", status_code=422
        )
    value = value.strip()
    if len(value) > maximum or _CONTROL.search(value):
        raise AppError(ErrorCode.INVALID_REQUEST, f"{field} 格式无效", status_code=422)
    return value


def normalize_aliases(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > _MAX_ALIASES:
        raise AppError(ErrorCode.INVALID_REQUEST, "字段别名数量无效", status_code=422)
    normalized = [_text(value, field="别名", maximum=_MAX_ALIAS) for value in values]
    return list(dict.fromkeys(value for value in normalized if value))


@dataclass(frozen=True, slots=True)
class SemanticColumn:
    name: str
    data_type: str
    sensitive: bool
    description: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticRelation:
    schema: str
    name: str
    description: str
    aliases: tuple[str, ...]
    columns: tuple[SemanticColumn, ...]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True, slots=True)
class SemanticSchema:
    relations: tuple[SemanticRelation, ...]
    fingerprint: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "tables": [
                {
                    "schema_name": relation.schema,
                    "table_name": relation.name,
                    "description": relation.description,
                    "aliases": list(relation.aliases),
                    "columns": [
                        {
                            "column_name": column.name,
                            "data_type": column.data_type,
                            "sensitive": column.sensitive,
                            "description": column.description,
                            "aliases": list(column.aliases),
                        }
                        for column in relation.columns
                    ],
                }
                for relation in self.relations
            ],
        }


def build_semantic_schema(
    tables: list[dict[str, Any]],
    metadata: list[DataQaSemanticMetadata],
) -> SemanticSchema:
    """Build semantics exclusively from the runtime's authorized catalog."""
    annotations = {
        (row.schema_name, row.table_name, row.column_name): row for row in metadata
    }
    relations: list[SemanticRelation] = []
    for table in sorted(
        tables, key=lambda item: (str(item["schema"]), str(item["name"]))
    ):
        schema, name = str(table["schema"]), str(table["name"])
        table_row = annotations.get((schema, name, ""))
        columns: list[SemanticColumn] = []
        for raw_column in table.get("columns") or []:
            column_name = str(raw_column["name"])
            column_row = annotations.get((schema, name, column_name))
            columns.append(
                SemanticColumn(
                    name=column_name,
                    data_type=str(raw_column.get("data_type") or "UNKNOWN"),
                    sensitive=bool(raw_column.get("sensitive")),
                    description=column_row.description if column_row else "",
                    aliases=tuple(column_row.aliases_json or ()) if column_row else (),
                )
            )
        relations.append(
            SemanticRelation(
                schema=schema,
                name=name,
                description=table_row.description if table_row else "",
                aliases=tuple(table_row.aliases_json or ()) if table_row else (),
                columns=tuple(columns),
            )
        )
    canonical = [
        {
            "relation": relation.qualified_name,
            "description": relation.description,
            "aliases": relation.aliases,
            "columns": [
                (
                    column.name,
                    column.data_type,
                    column.sensitive,
                    column.description,
                    column.aliases,
                )
                for column in relation.columns
            ],
        }
        for relation in relations
    ]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, default=list)
    return SemanticSchema(
        relations=tuple(relations),
        fingerprint=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


SessionFactory = Callable[[], Session]


class SemanticSchemaService:
    def __init__(self, session_factory: SessionFactory = SessionLocal) -> None:
        self._session_factory = session_factory

    def load(
        self, tables: list[dict[str, Any]], *, profile_id: str = "default"
    ) -> SemanticSchema:
        with self._session_factory() as db:
            metadata = (
                db.query(DataQaSemanticMetadata)
                .filter(DataQaSemanticMetadata.profile_id == profile_id)
                .all()
            )
            return build_semantic_schema(tables, metadata)

    def upsert(
        self,
        *,
        tables: list[dict[str, Any]],
        schema_name: str,
        table_name: str,
        column_name: str,
        description: str,
        aliases: list[str],
        updated_by_user_id: int,
        profile_id: str = "default",
    ) -> None:
        target = next(
            (
                table
                for table in tables
                if table.get("schema") == schema_name
                and table.get("name") == table_name
            ),
            None,
        )
        if target is None or (
            column_name
            and column_name
            not in {str(column["name"]) for column in target.get("columns") or []}
        ):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "元数据目标不在当前授权目录中",
                status_code=422,
            )
        description = _text(description, field="说明", maximum=_MAX_DESCRIPTION)
        aliases = normalize_aliases(aliases)
        with self._session_factory() as db:
            row = (
                db.query(DataQaSemanticMetadata)
                .filter_by(
                    profile_id=profile_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                )
                .with_for_update()
                .first()
            )
            if row is None:
                row = DataQaSemanticMetadata(
                    profile_id=profile_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                    description=description,
                    aliases_json=aliases,
                    updated_by_user_id=updated_by_user_id,
                )
                db.add(row)
            else:
                row.description = description
                row.aliases_json = aliases
                row.updated_by_user_id = updated_by_user_id
                row.version += 1
                row.updated_at = utcnow()
            db.commit()

    def delete(
        self,
        *,
        schema_name: str,
        table_name: str,
        column_name: str,
        profile_id: str = "default",
    ) -> None:
        with self._session_factory() as db:
            row = (
                db.query(DataQaSemanticMetadata)
                .filter_by(
                    profile_id=profile_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=column_name,
                )
                .first()
            )
            if row is not None:
                db.delete(row)
                db.commit()


semantic_schema_service = SemanticSchemaService()
