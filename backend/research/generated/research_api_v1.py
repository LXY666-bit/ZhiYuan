# Generated from contracts/research_api_v1.json. Do not edit by hand.
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResearchMode = Literal['quick', 'standard', 'deep']
ResearchProjectLifecycle = Literal['draft', 'awaiting_approval', 'frozen']
ResearchPlanJobStatus = Literal['pending', 'running', 'cancelling', 'cancelled', 'completed', 'failed']
ResearchSource = Literal["knowledge_base", "web", "attachments"]


class ResearchPlanStepV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_key: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=300)
    question: str = Field(min_length=1, max_length=2000)
    sources: list[ResearchSource]


class ResearchPlanV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^rplan_[a-f0-9]{32}$")
    project_id: str = Field(pattern=r"^rproj_[a-f0-9]{32}$")
    version: int = Field(ge=1)
    objective: str
    steps: list[ResearchPlanStepV1]
    created_at: datetime


class MarkdownArtifactEditV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    markdown: str = Field(min_length=1, max_length=2_000_000)
    rebuild_pdf: bool = True


class ResearchProjectV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^rproj_[a-f0-9]{32}$")
    thread_id: str
    title: str
    objective: str
    mode: ResearchMode
    lifecycle_status: ResearchProjectLifecycle
    version: int = Field(ge=1)
    run_status: str | None = None
    latest_run_id: str | None = None
    created_at: datetime
    updated_at: datetime
