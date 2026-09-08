"""DataQa（智能问数）契约：请求/视图模型与 LLM 结构化输出。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DataQaStatus = Literal["pending", "running", "completed", "failed"]
DataQaChartType = Literal["bar", "line", "pie", "none"]


class DataQaQueryCreateRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class DataQaAnalysisRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


class DataQaFieldRationaleV1(BaseModel):
    name: str
    comment: str = ""


class DataQaTableRationaleV1(BaseModel):
    name: str
    comment: str = ""
    reason: str = ""
    score: float = 0.0
    fields: list[DataQaFieldRationaleV1] = Field(default_factory=list)


class DataQaChartV1(BaseModel):
    chart_type: DataQaChartType = "none"
    label_field: str = ""
    value_field: str = ""
    title: str = ""
    source: Literal["rules", "llm"] = "rules"
    recommendation_error: str | None = None


class DataQaChartSuggestion(BaseModel):
    """Untrusted display-only proposal, validated against the actual result."""

    model_config = {"extra": "forbid"}
    chart_type: Literal["bar", "line", "pie"]
    label_field: str = Field(min_length=1, max_length=128)
    value_field: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=120)


class DataQaResultV1(BaseModel):
    """智能问数结果页六区块中除问题栏外的全部结构化内容。"""

    sql: str = ""
    tables: list[DataQaTableRationaleV1] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    chart: DataQaChartV1 = Field(default_factory=DataQaChartV1)
    analysis: str | None = None


class DataQaQueryV1(BaseModel):
    id: str
    question: str
    status: DataQaStatus
    run_id: str | None = None
    error_code: str | None = None
    version: int
    created_at: str
    updated_at: str
    result: DataQaResultV1 | None = None


class DataQaQueryListResponse(BaseModel):
    queries: list[DataQaQueryV1]


class DataQaGroundedSqlDecision(BaseModel):
    """SQL plus an optional proposal; malformed display advice must not fail SQL."""

    sql: str
    chart: Any = Field(
        default=None,
        description="Optional chart proposal: chart_type, label_field, value_field, title. Never include data or code.",
    )


class DataQaSemanticMetadataRequest(BaseModel):
    schema_name: str = Field(min_length=1, max_length=63)
    table_name: str = Field(min_length=1, max_length=63)
    column_name: str = Field(default="", max_length=63)
    description: str = Field(default="", max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class DataQaSemanticColumnV1(BaseModel):
    column_name: str
    data_type: str
    sensitive: bool
    description: str
    aliases: list[str]


class DataQaSemanticTableV1(BaseModel):
    schema_name: str
    table_name: str
    description: str
    aliases: list[str]
    columns: list[DataQaSemanticColumnV1]


class DataQaSemanticSchemaResponse(BaseModel):
    fingerprint: str
    tables: list[DataQaSemanticTableV1]


__all__ = [
    "DataQaAnalysisRequest",
    "DataQaChartV1",
    "DataQaChartSuggestion",
    "DataQaChartType",
    "DataQaFieldRationaleV1",
    "DataQaGroundedSqlDecision",
    "DataQaQueryCreateRequest",
    "DataQaQueryListResponse",
    "DataQaQueryV1",
    "DataQaResultV1",
    "DataQaSemanticColumnV1",
    "DataQaSemanticMetadataRequest",
    "DataQaSemanticSchemaResponse",
    "DataQaSemanticTableV1",
    "DataQaStatus",
    "DataQaTableRationaleV1",
]
