from __future__ import annotations

from typing import Any

from backend.model_control import ModelControlService, ModelRole, model_control_service
from backend.research.repository import (
    ApprovalRecord,
    PlanJobRecord,
    ResearchRepository,
    research_repository,
)


class ResearchService:
    def __init__(
        self,
        repository: ResearchRepository = research_repository,
        *,
        model_control: ModelControlService = model_control_service,
    ) -> None:
        self.repository = repository
        self.model_control = model_control

    def create_plan_job(self, **kwargs: Any) -> PlanJobRecord:
        snapshot = self.model_control.runtime_snapshot(
            required_roles=frozenset({ModelRole.FAST, ModelRole.GRADER})
        )
        return self.repository.create_plan_job(model_snapshot=snapshot, **kwargs)

    def approve(self, **kwargs: Any) -> ApprovalRecord:
        snapshot = self.model_control.runtime_snapshot(
            required_roles=frozenset(
                {ModelRole.ANSWER, ModelRole.FAST, ModelRole.GRADER}
            )
        )
        return self.repository.approve(model_snapshot=snapshot, **kwargs)

    def rerun(self, **kwargs: Any) -> ApprovalRecord:
        snapshot = self.model_control.runtime_snapshot(
            required_roles=frozenset(
                {ModelRole.ANSWER, ModelRole.FAST, ModelRole.GRADER}
            )
        )
        return self.repository.approve(
            model_snapshot=snapshot,
            allow_frozen=True,
            **kwargs,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)


research_service = ResearchService()
