from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_research_uses_only_new_api_and_canonical_run_stream():
    route = (ROOT / "backend/api/routes/research.py").read_text(encoding="utf-8")
    executor = (ROOT / "backend/runs/agent_executor.py").read_text(encoding="utf-8")
    api_router = (ROOT / "backend/api/router.py").read_text(encoding="utf-8")
    assert 'prefix="/v1/research/projects"' in route
    assert "/research/tasks" not in route
    assert 'snapshot.channel == "research"' in executor
    assert "ResearchWorkflowRunner" in executor
    assert "research_router" in api_router
    assert "/stream" not in route


def test_research_events_never_emit_sensitive_payload_fields():
    workflow = (ROOT / "backend/research/workflow.py").read_text(encoding="utf-8")
    forbidden = (
        'data={"content"',
        'data={"url"',
        'data={"query"',
        'data={"path"',
        'data={"exception"',
    )
    assert all(value not in workflow for value in forbidden)


def test_research_domain_is_not_imported_by_rag_or_chat():
    for directory in (ROOT / "backend/rag", ROOT / "backend/chat"):
        for path in directory.rglob("*.py"):
            assert "backend.research" not in path.read_text(encoding="utf-8"), path
