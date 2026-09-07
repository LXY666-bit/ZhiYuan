from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.research.generated.research_api_v1 import (
    MarkdownArtifactEditV1 as MarkdownArtifactEditRequest,
    ResearchMode,
    ResearchPlanJobStatus,
    ResearchPlanStepV1,
    ResearchPlanV1,
    ResearchProjectLifecycle,
    ResearchProjectV1,
    ResearchSource,
)


class PlannerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    steps: list[ResearchPlanStepV1]


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=3, max_length=10000)
    mode: ResearchMode = "quick"
    sources: list[ResearchSource] = Field(default_factory=lambda: ["knowledge_base"])
    output_formats: list[str] = Field(default_factory=lambda: ["markdown"])

    @model_validator(mode="after")
    def nonempty_sets(self) -> ProjectCreateRequest:
        if not self.sources:
            raise ValueError("sources cannot be empty")
        if not self.output_formats or any(
            value not in {"markdown", "pdf"} for value in self.output_formats
        ):
            raise ValueError("output_formats must contain markdown and/or pdf")
        self.sources = list(dict.fromkeys(self.sources))
        self.output_formats = list(dict.fromkeys(self.output_formats))
        return self


class PlanWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_project_version: int = Field(ge=1)
    steps: list[ResearchPlanStepV1]


class PlanJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_project_version: int = Field(ge=1)


class PlanJobView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    status: ResearchPlanJobStatus
    fencing_token: int
    attempts: int
    result_plan_id: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ApproveProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_project_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ProjectListResponse(BaseModel):
    projects: list[ResearchProjectV1]


class PlanResponse(BaseModel):
    plan: ResearchPlanV1


class ApprovalResponse(BaseModel):
    project: ResearchProjectV1
    run_id: str
    thread_version: int


class ResearchRunListResponse(BaseModel):
    runs: list[dict]


class ResearchResourceListResponse(BaseModel):
    items: list[dict]


class ResearchMetricsResponse(BaseModel):
    metrics: dict


__all__ = [
    "ApprovalResponse",
    "ApproveProjectRequest",
    "PlanJobCreateRequest",
    "PlanJobView",
    "PlanResponse",
    "PlanWriteRequest",
    "PlannerDecision",
    "ProjectCreateRequest",
    "ProjectListResponse",
    "ResearchMode",
    "ResearchMetricsResponse",
    "ResearchResourceListResponse",
    "ResearchRunListResponse",
    "MarkdownArtifactEditRequest",
    "ResearchPlanStepV1",
    "ResearchPlanV1",
    "ResearchProjectLifecycle",
    "ResearchProjectV1",
    "ResearchSource",
]
