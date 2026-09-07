"""Deterministic candidate selection for grounded Text2SQL."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from backend.dataqa.semantic_schema import (
    SemanticColumn,
    SemanticRelation,
    SemanticSchema,
)

MAX_CANDIDATE_TABLES = 5
MAX_CANDIDATE_COLUMNS = 20


def _normal(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _match(question: str, value: str) -> bool:
    candidate = _normal(value)
    # Very short identifiers (for example "id") are too noisy to be terms.
    return len(candidate) >= 2 and candidate in question


def _clip(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else f"{value[: maximum - 1]}…"


def _column_score(question: str, column: SemanticColumn) -> tuple[int, list[str]]:
    score, reasons = 0, []
    if any(_match(question, alias) for alias in column.aliases):
        score += 12
        reasons.append("字段别名")
    if column.description and _match(question, column.description):
        score += 10
        reasons.append("字段说明")
    if _match(question, column.name):
        score += 5
        reasons.append("字段名")
    return score, reasons


def _relation_score(question: str, relation: SemanticRelation) -> tuple[int, list[str]]:
    score, reasons = 0, []
    if any(_match(question, alias) for alias in relation.aliases):
        score += 12
        reasons.append("表别名")
    if relation.description and _match(question, relation.description):
        score += 8
        reasons.append("表说明")
    if _match(question, relation.name):
        score += 4
        reasons.append("表名")
    return score, reasons


@dataclass(frozen=True, slots=True)
class CandidateColumn:
    name: str
    data_type: str
    description: str
    aliases: tuple[str, ...]
    score: int
    matched_by: tuple[str, ...]

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "description": self.description,
            "aliases": list(self.aliases),
            "score": self.score,
            "matched_by": list(self.matched_by),
        }


@dataclass(frozen=True, slots=True)
class CandidateRelation:
    schema: str
    name: str
    description: str
    aliases: tuple[str, ...]
    score: int
    matched_by: tuple[str, ...]
    columns: tuple[CandidateColumn, ...]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"

    def snapshot(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "name": self.name,
            "description": self.description,
            "aliases": list(self.aliases),
            "score": self.score,
            "matched_by": list(self.matched_by),
            "columns": [column.snapshot() for column in self.columns],
        }


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    semantic_schema_hash: str
    relations: tuple[CandidateRelation, ...]

    @property
    def relation_scope(self) -> tuple[str, ...]:
        return tuple(relation.qualified_name for relation in self.relations)

    def snapshot(self) -> dict[str, object]:
        return {
            "semantic_schema_hash": self.semantic_schema_hash,
            "relations": [relation.snapshot() for relation in self.relations],
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, object]) -> "CandidateSelection":
        relations = []
        for raw_relation in payload.get("relations", []):  # type: ignore[union-attr]
            relation = dict(raw_relation)  # type: ignore[arg-type]
            columns = tuple(
                CandidateColumn(
                    name=str(raw_column["name"]),
                    data_type=str(raw_column["data_type"]),
                    description=str(raw_column.get("description") or ""),
                    aliases=tuple(raw_column.get("aliases") or []),
                    score=int(raw_column.get("score") or 0),
                    matched_by=tuple(raw_column.get("matched_by") or []),
                )
                for raw_column in relation.get("columns", [])
            )
            relations.append(
                CandidateRelation(
                    schema=str(relation["schema"]),
                    name=str(relation["name"]),
                    description=str(relation.get("description") or ""),
                    aliases=tuple(relation.get("aliases") or []),
                    score=int(relation.get("score") or 0),
                    matched_by=tuple(relation.get("matched_by") or []),
                    columns=columns,
                )
            )
        return cls(
            semantic_schema_hash=str(payload["semantic_schema_hash"]),
            relations=tuple(relations),
        )

    def prompt_schema(self, *, budget: int) -> str:
        if budget < 128:
            raise ValueError("candidate schema budget is too small")
        lines: list[str] = []
        for relation in self.relations:
            table = f"表 {relation.qualified_name}"
            if relation.description:
                table += f"：{_clip(relation.description, 240)}"
            if relation.aliases:
                table += f"（别名：{_clip('、'.join(relation.aliases), 240)}）"
            if len("\n".join([*lines, table])) > budget:
                break
            lines.append(table)
            for column in relation.columns:
                line = f"  - {column.name}: {column.data_type}"
                if column.description:
                    line += f"；{_clip(column.description, 240)}"
                if column.aliases:
                    line += f"（别名：{_clip('、'.join(column.aliases), 240)}）"
                if len("\n".join([*lines, line])) > budget:
                    break
                lines.append(line)
        return "\n".join(lines)

    def result_tables(self) -> list[dict[str, object]]:
        return [
            {
                "name": relation.qualified_name,
                "comment": relation.description,
                "reason": "、".join(relation.matched_by) or "候选表",
                "score": float(relation.score),
                "fields": [
                    {"name": column.name, "comment": column.description}
                    for column in relation.columns
                ],
            }
            for relation in self.relations
        ]


def select_candidates(
    question: str, semantic_schema: SemanticSchema
) -> CandidateSelection:
    normalized_question = _normal(question)
    scored: list[CandidateRelation] = []
    for relation in semantic_schema.relations:
        relation_score, relation_reasons = _relation_score(
            normalized_question, relation
        )
        columns = []
        for column in relation.columns:
            if column.sensitive:
                continue
            score, reasons = _column_score(normalized_question, column)
            columns.append((score, reasons, column))
        matched_columns = [item for item in columns if item[0] > 0]
        score = relation_score + sum(
            item[0]
            for item in sorted(matched_columns, reverse=True, key=lambda item: item[0])[
                :3
            ]
        )
        if score <= 0:
            continue
        # Retain a bounded set of zero-score support columns as well: a date,
        # status, or join key may be needed to express a question whose primary
        # business term matched another field.  This is grounding context, not
        # a column permission boundary (the SQL policy remains authoritative).
        chosen = sorted(columns, key=lambda item: (-item[0], item[2].name))[
            :MAX_CANDIDATE_COLUMNS
        ]
        scored.append(
            CandidateRelation(
                schema=relation.schema,
                name=relation.name,
                description=relation.description,
                aliases=relation.aliases,
                score=score,
                matched_by=tuple(
                    relation_reasons
                    + [f"字段：{column.name}" for _, _, column in matched_columns[:3]]
                ),
                columns=tuple(
                    CandidateColumn(
                        name=column.name,
                        data_type=column.data_type,
                        description=column.description,
                        aliases=column.aliases,
                        score=column_score,
                        matched_by=tuple(reasons),
                    )
                    for column_score, reasons, column in chosen
                ),
            )
        )
    selected = sorted(scored, key=lambda item: (-item.score, item.qualified_name))[
        :MAX_CANDIDATE_TABLES
    ]
    return CandidateSelection(semantic_schema.fingerprint, tuple(selected))
