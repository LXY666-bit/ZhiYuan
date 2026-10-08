from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.errors import AppError, ErrorCode
from backend.dataqa.contracts import DataQaGroundedSqlDecision
from backend.dataqa.repository import DataQaRepository
from backend.dataqa.semantic_schema import build_semantic_schema
from backend.dataqa.workflow import DataQaWorkflowRunner, build_content, infer_chart
from backend.db.models import Base, DataQaQuery, Message, Run, Thread, User
from backend.model_control import (
    ModelRole,
    ModelRuntimeSpec,
    build_model_catalog_snapshot,
)
from backend.runs.state import RunStatus
from backend.sql_assistant.postgres import SqlAssistantError, SqlAssistantErrorCode

SessionFactory = Any


@pytest.fixture()
def session_factory():
    # StaticPool + 单连接：asyncio.to_thread 跨线程共享同一个内存 SQLite 连接
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(User(username="alice", password_hash="unused", role="user"))
        db.add(User(username="bob", password_hash="unused", role="admin"))
    return factory


def _snapshot():
    assignments = {}
    for role in (ModelRole.ANSWER, ModelRole.FAST):
        assignments[role] = ModelRuntimeSpec(
            profile_id="model_" + hashlib.sha256(role.value.encode()).hexdigest()[:32],
            profile_version=1,
            display_name=role.value,
            model_name=f"test-{role.value}",
            timeout_seconds=30,
            supports_stream=True,
            supports_structured_output=True,
        )
    return build_model_catalog_snapshot(assignments)


class _FakeModel:
    def __init__(self, decision: Any = None, text: str = "分析文本") -> None:
        self.decision = decision
        self.text = text

    def with_structured_output(self, _schema: Any, *, method) -> _FakeModel:
        return self

    def invoke(self, _messages: Any) -> Any:
        if self.decision is not None:
            return self.decision
        return SimpleNamespace(content=self.text)


class _FakeExecutor:
    def call(self, fn: Any, *, context: Any = None) -> Any:
        return fn()


class _FakeModels:
    def __init__(self, model: _FakeModel) -> None:
        self.model = model

    def get(self, _role: Any, *, snapshot: Any = None) -> _FakeModel:
        return self.model

    def describe(self, _role: Any, *, snapshot: Any = None) -> Any:
        return SimpleNamespace(name="fake", timeout_seconds=30)


class _FakeRuntime:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def describe_schema(self, tables: tuple[str, ...]) -> dict[str, Any]:
        return {
            "tables": [
                {
                    "schema": "public",
                    "name": "biz_order_goods",
                    "kind": "table",
                    "columns": [
                        {"name": "good_name", "data_type": "text", "nullable": True},
                        {"name": "num", "data_type": "integer", "nullable": True},
                    ],
                }
            ]
        }

    def query(
        self,
        sql: str,
        *,
        deadline_at: float | None,
        cancellation_probe: Any = None,
        relation_scope: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        assert relation_scope == ("public.biz_order_goods",)
        self.executed.append(sql)
        return {
            "columns": ["good_name", "total_num"],
            "rows": [["无线键盘", 128], ["无线鼠标", 96]],
            "row_count": 2,
            "truncated": False,
        }


class _PolicyDeniedRuntime(_FakeRuntime):
    def query(
        self,
        sql: str,
        *,
        deadline_at: float | None,
        cancellation_probe: Any = None,
        relation_scope: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        raise SqlAssistantError(SqlAssistantErrorCode.POLICY_DENIED)


def _decision() -> DataQaGroundedSqlDecision:
    return DataQaGroundedSqlDecision(
        sql="SELECT good_name, SUM(num) AS total_num FROM biz_order_goods "
        "GROUP BY good_name ORDER BY total_num DESC LIMIT 5;",
    )


class _SemanticSchema:
    def load(self, tables: list[dict[str, Any]]):
        metadata = [
            SimpleNamespace(
                schema_name="public",
                table_name="biz_order_goods",
                column_name="",
                description="订单商品明细",
                aliases_json=["销量", "商品"],
            ),
            SimpleNamespace(
                schema_name="public",
                table_name="biz_order_goods",
                column_name="good_name",
                description="商品名称",
                aliases_json=["商品"],
            ),
            SimpleNamespace(
                schema_name="public",
                table_name="biz_order_goods",
                column_name="num",
                description="销售数量",
                aliases_json=["销量"],
            ),
        ]
        return build_semantic_schema(tables, metadata)


def _execution_snapshot(session_factory: SessionFactory, run_id: str) -> Any:
    with session_factory() as db:
        assert isinstance(db, Session)
        run = db.query(Run).filter(Run.id == run_id).one()
        return SimpleNamespace(
            run=SimpleNamespace(id=run.id, fencing_token=run.fencing_token),
            user_text="销量前五的商品是哪些？",
            model_snapshot=_snapshot(),
            username="alice",
            tenant_id="default",
        )


def _run_once(
    repository: DataQaRepository,
    session_factory: SessionFactory,
    record: Any,
    *,
    model: _FakeModel | None = None,
    runtime: Any = None,
) -> Any:
    runner = DataQaWorkflowRunner(
        store=repository,
        models=_FakeModels(model or _FakeModel(_decision())),  # type: ignore[arg-type]
        executor=_FakeExecutor(),  # type: ignore[arg-type]
        runtime_provider=lambda: runtime,
        semantic_schema=_SemanticSchema(),  # type: ignore[arg-type]
    )
    return asyncio.run(
        runner.run(
            snapshot=_execution_snapshot(session_factory, record.run_id),
            token=SimpleNamespace(cancelled=False),
            worker_id="test-worker",
        )
    )


# ----------------------------------------------------------------- 仓储层


def test_create_query_is_atomic_and_idempotent(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v1",
        model_snapshot=_snapshot(),
    )
    repeated = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v1",
        model_snapshot=_snapshot(),
    )
    assert record.query.status == "pending"
    assert record.run_id == repeated.run_id
    assert record.query.id == repeated.query.id
    with session_factory() as db:
        run = db.query(Run).filter(Run.id == record.run_id).one()
        thread = db.query(Thread).filter(Thread.id == run.thread_ref_id).one()
        query = db.query(DataQaQuery).filter(DataQaQuery.run_id == run.id).one()
        assert run.channel == "dataqa"
        assert thread.kind == "dataqa"
        assert run.last_event_sequence == 1
        assert query.status == "pending"
        messages = (
            db.query(Message)
            .filter(Message.thread_ref_id == thread.id)
            .order_by(Message.sequence)
            .all()
        )
        assert [m.message_type for m in messages] == ["human", "ai"]
        assert messages[0].content == "销量前五的商品是哪些？"


def test_create_query_rejects_unknown_user(session_factory):
    repository = DataQaRepository(session_factory)
    with pytest.raises(AppError):
        repository.create_query(
            username="nobody",
            tenant_id="default",
            question="问题",
            idempotency_key="query-v2",
            model_snapshot=_snapshot(),
        )


def test_list_and_get_queries_are_user_scoped(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="我的问题",
        idempotency_key="query-v3",
        model_snapshot=_snapshot(),
    )
    assert (
        repository.get_query(
            username="alice", tenant_id="default", query_id=record.query.id
        ).id
        == record.query.id
    )
    with pytest.raises(AppError):
        repository.get_query(
            username="bob", tenant_id="default", query_id=record.query.id
        )
    assert len(repository.list_queries(username="alice", tenant_id="default")) == 1
    assert repository.list_queries(username="bob", tenant_id="default") == []


def test_delete_query_removes_its_dedicated_thread_and_rejects_active_runs(
    session_factory,
):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="我的问题",
        idempotency_key="query-delete",
        model_snapshot=_snapshot(),
    )
    with pytest.raises(AppError) as active_error:
        repository.delete_query(
            username="alice", tenant_id="default", query_id=record.query.id
        )
    assert active_error.value.code == ErrorCode.RUN_ACTIVE
    with pytest.raises(AppError) as ownership_error:
        repository.delete_query(
            username="bob", tenant_id="default", query_id=record.query.id
        )
    assert ownership_error.value.code == ErrorCode.NOT_FOUND

    with session_factory.begin() as db:
        run = db.query(Run).filter(Run.id == record.run_id).one()
        run.status = RunStatus.SUCCEEDED.value

    assert repository.delete_query(
        username="alice", tenant_id="default", query_id=record.query.id
    )
    with session_factory() as db:
        assert (
            db.query(DataQaQuery)
            .filter(DataQaQuery.id == record.query.id)
            .one_or_none()
            is None
        )
        assert db.query(Run).filter(Run.id == record.run_id).one_or_none() is None
        assert db.query(Thread).filter(Thread.kind == "dataqa").one_or_none() is None
        assert db.query(Message).filter(Message.run_id == record.run_id).count() == 0


# ----------------------------------------------------------------- 工作流


def test_workflow_completes_query_with_structured_result(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v4",
        model_snapshot=_snapshot(),
    )
    content = _run_once(repository, session_factory, record, runtime=_FakeRuntime())
    assert "SELECT good_name" in content
    with session_factory() as db:
        query = db.query(DataQaQuery).filter(DataQaQuery.run_id == record.run_id).one()
        assert query.status == "completed"
        result = query.result_json
        assert result is not None
        assert "SELECT good_name" in result["sql"]
        assert result["columns"] == ["good_name", "total_num"]
        assert result["row_count"] == 2
        assert result["chart"]["chart_type"] == "bar"
        assert result["chart"]["label_field"] == "good_name"
        assert result["tables"][0]["comment"] == "订单商品明细"
        assert result["tables"][0]["fields"][0]["comment"] == "商品名称"
        assert query.candidate_schema_json is not None
        run = db.query(Run).filter(Run.id == record.run_id).one()
        message = db.query(Message).filter(Message.id == run.assistant_message_id).one()
        assert "SELECT good_name" in message.content
        assert "无线键盘" in message.content


def test_workflow_is_idempotent_on_replay(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v5",
        model_snapshot=_snapshot(),
    )
    runtime = _FakeRuntime()
    _run_once(repository, session_factory, record, runtime=runtime)
    # 重放：不再执行 SQL，直接从持久化结果恢复
    _run_once(repository, session_factory, record, runtime=runtime)
    assert runtime.executed == [
        "SELECT good_name, SUM(num) AS total_num FROM biz_order_goods GROUP BY good_name ORDER BY total_num DESC LIMIT 5;"
    ]
    with session_factory() as db:
        query = db.query(DataQaQuery).filter(DataQaQuery.run_id == record.run_id).one()
        assert query.status == "completed"
        # Grounding snapshot and final result each advance the optimistic version.
        assert query.version == 3


def test_workflow_failure_marks_query_failed(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v6",
        model_snapshot=_snapshot(),
    )
    with pytest.raises(AppError):
        _run_once(repository, session_factory, record, runtime=None)
    with session_factory() as db:
        query = db.query(DataQaQuery).filter(DataQaQuery.run_id == record.run_id).one()
        assert query.status == "failed"
        assert query.error_code == "DATAQA_SQL_UNAVAILABLE"


def test_workflow_preserves_sql_policy_error_for_the_canonical_run(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-policy-denied",
        model_snapshot=_snapshot(),
    )

    with pytest.raises(AppError) as captured:
        _run_once(repository, session_factory, record, runtime=_PolicyDeniedRuntime())

    assert captured.value.code == SqlAssistantErrorCode.POLICY_DENIED
    assert captured.value.public_error.category == "dataqa"
    assert captured.value.public_error.stage == "sql"
    with session_factory() as db:
        query = db.query(DataQaQuery).filter(DataQaQuery.run_id == record.run_id).one()
        assert query.status == "failed"
        assert query.error_code == SqlAssistantErrorCode.POLICY_DENIED


# ----------------------------------------------------------------- 分析


def test_attach_analysis_is_gated_and_idempotent(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v7",
        model_snapshot=_snapshot(),
    )
    with pytest.raises(AppError):
        repository.attach_analysis(
            username="alice",
            tenant_id="default",
            query_id=record.query.id,
            analysis="分析",
        )
    _run_once(repository, session_factory, record, runtime=_FakeRuntime())
    updated = repository.attach_analysis(
        username="alice",
        tenant_id="default",
        query_id=record.query.id,
        analysis="键盘销量最高。",
    )
    assert updated.result is not None
    assert updated.result.analysis == "键盘销量最高。"
    again = repository.attach_analysis(
        username="alice",
        tenant_id="default",
        query_id=record.query.id,
        analysis="不同的分析",
    )
    assert again.result is not None
    assert again.result.analysis == "键盘销量最高。"


# ----------------------------------------------------------------- 确定性


def test_infer_chart_rules():
    two_columns = infer_chart(["a", "b"], [["x", 1], ["y", 2]])
    assert two_columns["chart_type"] == "bar"
    decimal_strings = infer_chart(["a", "b"], [["x", "1.25"], ["y", "2.5"]])
    assert decimal_strings["chart_type"] == "bar"
    non_numeric = infer_chart(["a", "b"], [["x", "not-a-number"]])
    assert non_numeric["chart_type"] == "none"
    non_finite = infer_chart(["a", "b"], [["x", "NaN"]])
    assert non_finite["chart_type"] == "none"
    single_column = infer_chart(["a"], [["x"]])
    assert single_column["chart_type"] == "none"
    too_many_rows = infer_chart(["a", "b"], [[str(i), i] for i in range(61)])
    assert too_many_rows["chart_type"] == "none"


@pytest.mark.parametrize(
    "proposal",
    [
        {
            "chart_type": "bar",
            "label_field": "good_name",
            "value_field": "total_num",
            "title": "销量",
        },
        {"chart_type": "bar", "label_field": "invented", "value_field": "total_num"},
        "invalid suggestion",
    ],
)
def test_chart_suggestions_are_validated_and_persisted_without_failing_query(
    session_factory, proposal
):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="chart-suggestion",
        model_snapshot=_snapshot(),
    )
    decision = _decision().model_copy(update={"chart": proposal})
    _run_once(
        repository,
        session_factory,
        record,
        model=_FakeModel(decision),
        runtime=_FakeRuntime(),
    )
    saved = repository.get_query(
        username="alice", tenant_id="default", query_id=record.query.id
    )
    assert saved.status == "completed"
    assert saved.result is not None
    assert saved.result.rows == [["无线键盘", 128], ["无线鼠标", 96]]
    valid = isinstance(proposal, dict) and proposal.get("label_field") == "good_name"
    assert saved.result.chart.source == ("llm" if valid else "rules")
    assert bool(saved.result.chart.recommendation_error) is not valid


def test_build_content_mentions_blocks():
    content = build_content(
        "问题",
        {
            "sql": "SELECT 1",
            "columns": ["a"],
            "rows": [["x"]],
            "row_count": 1,
            "analysis": "已有分析",
        },
    )
    assert "**问题**" in content
    assert "**生成 SQL**" in content
    assert "**查询结果**" in content
    assert "已有分析" in content


def test_analysis_generation_uses_answer_model(session_factory):
    repository = DataQaRepository(session_factory)
    record = repository.create_query(
        username="alice",
        tenant_id="default",
        question="销量前五的商品是哪些？",
        idempotency_key="query-v8",
        model_snapshot=_snapshot(),
    )
    _run_once(repository, session_factory, record, runtime=_FakeRuntime())
    runner = DataQaWorkflowRunner(
        store=repository,
        models=_FakeModels(_FakeModel(text="趋势向上")),  # type: ignore[arg-type]
        executor=_FakeExecutor(),  # type: ignore[arg-type]
        runtime_provider=lambda: _FakeRuntime(),
    )
    analysis = runner.analyze(
        question="销量前五的商品是哪些？",
        result={
            "sql": "SELECT 1",
            "columns": ["a"],
            "rows": [["x"]],
            "row_count": 1,
        },
        model_snapshot=_snapshot(),
    )
    assert analysis == "趋势向上"
