"""DataQa 薄门面：在写操作前冻结 Model Snapshot。"""

from __future__ import annotations

from typing import Any

from backend.dataqa.repository import (
    DataQaRepository,
    QueryCreateRecord,
    dataqa_repository,
)
from backend.model_control import ModelControlService, ModelRole, model_control_service


class DataQaService:
    def __init__(
        self,
        repository: DataQaRepository = dataqa_repository,
        *,
        model_control: ModelControlService = model_control_service,
    ) -> None:
        self.repository = repository
        self.model_control = model_control

    def create_query(self, **kwargs: Any) -> QueryCreateRecord:
        snapshot = self.model_control.runtime_snapshot(
            required_roles=frozenset({ModelRole.FAST, ModelRole.ANSWER})
        )
        return self.repository.create_query(model_snapshot=snapshot, **kwargs)

    def create_analysis(self, **kwargs: Any) -> QueryCreateRecord:
        snapshot = self.model_control.runtime_snapshot(
            required_roles=frozenset({ModelRole.ANSWER})
        )
        return self.repository.create_analysis(model_snapshot=snapshot, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.repository, name)


dataqa_service = DataQaService()
