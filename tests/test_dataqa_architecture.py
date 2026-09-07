from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dataqa_uses_only_new_api_and_canonical_run_stream():
    route = (ROOT / "backend/api/routes/dataqa.py").read_text(encoding="utf-8")
    executor = (ROOT / "backend/runs/agent_executor.py").read_text(encoding="utf-8")
    api_router = (ROOT / "backend/api/router.py").read_text(encoding="utf-8")
    assert 'prefix="/v1/dataqa/queries"' in route
    assert 'snapshot.channel == "dataqa"' in executor
    assert "DataQaWorkflowRunner" in executor
    assert "dataqa_router" in api_router
    assert "dataqa_schema_router" in api_router
    # 事件流必须走 canonical Run 信道，dataqa 路由不允许自带 /stream 端点
    assert "/stream" not in route


def test_dataqa_events_never_emit_sensitive_payload_fields():
    workflow = (ROOT / "backend/dataqa/workflow.py").read_text(encoding="utf-8")
    repository = (ROOT / "backend/dataqa/repository.py").read_text(encoding="utf-8")
    forbidden = (
        'data={"content"',
        'data={"url"',
        'data={"query"',
        'data={"path"',
        'data={"exception"',
        "dsn",
        "password",
    )
    for source in (workflow, repository):
        assert all(value not in source for value in forbidden)


def test_dataqa_domain_is_not_imported_by_rag_or_chat():
    for directory in (ROOT / "backend/rag", ROOT / "backend/chat"):
        for path in directory.rglob("*.py"):
            assert "backend.dataqa" not in path.read_text(encoding="utf-8"), path


def test_dataqa_persistence_is_a_first_class_channel():
    models = (ROOT / "backend/db/models.py").read_text(encoding="utf-8")
    migration = (ROOT / "migrations/versions/0021_dataqa_workbench.py").read_text(
        encoding="utf-8"
    )
    assert "channel IN ('run', 'research', 'dataqa')" in models
    assert "kind IN ('chat', 'research', 'dataqa')" in models
    assert "dataqa_queries" in models
    assert "ck_dataqa_queries_status" in migration
    assert "downgrade refused" in migration


def test_dataqa_grounding_keeps_one_sql_execution_seam():
    workflow = (ROOT / "backend/dataqa/workflow.py").read_text(encoding="utf-8")
    runtime = (ROOT / "backend/sql_assistant/runtime.py").read_text(encoding="utf-8")
    assert "select_candidates" in workflow
    assert "freeze_grounding" in workflow
    assert "relation_scope=selection.relation_scope" in workflow
    assert "_scope_catalog" in runtime
    assert "SqlPolicyCompiler" in runtime
