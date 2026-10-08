"""Offline adapters exercise the production Research workflow and repositories."""

from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.artifacts.service import ArtifactService
from backend.db.models import Base, User
from backend.model_control import (
    ModelRole,
    ModelRuntimeSpec,
    build_model_catalog_snapshot,
)
from backend.research.generated.research_api_v1 import ResearchPlanStepV1
from backend.research.profiles import resolve_research_profile
from backend.research.query_policy import objective_match
from backend.research.repository import ResearchRepository
from backend.research.workflow import ResearchWorkflowRunner, ResearchWorkflowStore
from backend.runs.repository import RunRepository


class OfflineModel:
    """Fixed extractive responses, never a substitute for real-model quality."""

    def __init__(self, schema=None):
        self.schema = schema

    def with_structured_output(self, schema, *, method):
        return OfflineModel(schema)

    def invoke(self, messages):
        prompt = messages[0]["content"]
        material = prompt.rsplit("Evidence：", 1)[-1]
        passages = re.findall(
            r"\[(E\d+)\] ([^\n]+)\n(.*?)(?=\n\n\[E\d+\]|\Z)", material, re.S
        )
        if self.schema is not None:
            name = self.schema.__name__
            if name == "GapDecision":
                return {"needs_research": False, "question": ""}
            if name == "SectionReviewDecision":
                # Verifier prompts omit titles; judge the observed evidence, not Case flags.
                chapter = prompt.split("章节：", 1)[-1].split("\nEvidence：", 1)[0]
                verdict = (
                    "conflicting"
                    if "存在冲突" in chapter
                    else "insufficient"
                    if "没有证据" in chapter
                    else "supported"
                )
                return {
                    "needs_revision": False,
                    "issues": [],
                    "claim": next(
                        (
                            line.lstrip("- ").strip()[:2000]
                            for line in chapter.splitlines()
                            if line.strip()
                        ),
                        "本章结论",
                    ),
                    "verdict": verdict,
                    "reason": "固定资料存在冲突，不能直接采信。"
                    if verdict == "conflicting"
                    else "固定资料明确说明证据不足。"
                    if verdict == "insufficient"
                    else "结论来自提供的资料。",
                }
            raise ValueError(f"unsupported offline schema: {name}")
        if not passages:
            # Synthesis prompts contain evidence without titles.
            passages = [
                (number, "", content)
                for number, content in re.findall(
                    r"\[(E\d+)\] (.*?)(?=\n\n\[E\d+\]|\Z)", material, re.S
                )
            ]
        lines = []
        objective = re.search(r"(?:原始)?研究目标：([^\n]+)", prompt)
        for number, _title, content in passages:
            for paragraph in content.splitlines():
                if (
                    paragraph.strip()
                    and not paragraph.startswith("#")
                    and (
                        not objective
                        or objective_match(objective[1], content=paragraph)[
                            "objective_match"
                        ]
                    )
                ):
                    lines.append(f"- {paragraph.strip()} [{number}]")
        return SimpleNamespace(
            content="\n".join(dict.fromkeys(lines)),
            usage_metadata={"input_tokens": 0, "output_tokens": 0},
        )

    async def ainvoke(self, messages, **_kwargs):
        return self.invoke(messages)


class OfflineModels:
    def get(self, *_args, **_kwargs):
        return OfflineModel()

    def describe(self, *_args, **_kwargs):
        return SimpleNamespace(name="offline-extractive", timeout_seconds=30)


class OfflineExecutor:
    async def acall(self, operation, *, context):
        if context.cancellation():
            raise asyncio.CancelledError
        return await operation()


class OfflineToken:
    cancelled = False

    async def checkpoint(self):
        return None

    def append_partial(self, _content):
        return None


def observe_case(case: dict, mode: str, sources_root: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="zhiyuan-research-eval-") as directory:
        root = Path(directory)
        engine = create_engine(f"sqlite:///{(root / 'eval.db').as_posix()}")

        # SQLite has no FOR UPDATE. Serialize evaluation transactions explicitly;
        # production lock / fencing behavior still requires PostgreSQL integration.
        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _record):
            connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def begin_sqlite(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        try:
            Base.metadata.create_all(engine)
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            with factory.begin() as db:
                db.add(
                    User(username="offline-eval", password_hash="unused", role="user")
                )
            repository = ResearchRepository(factory)
            profile = resolve_research_profile(mode)
            project = repository.create_project(
                username="offline-eval",
                tenant_id="offline",
                title=case["id"],
                objective=case["objective"],
                mode=mode,
                sources=["knowledge_base"],
                output_formats=["markdown"],
            )
            steps = [
                ResearchPlanStepV1(
                    step_key=f"step-{index}",
                    title=topic,
                    question=f"{case['objective']}：核验{topic}",
                    sources=["knowledge_base"],
                )
                for index, topic in enumerate(
                    case["expected_topics"][: profile["max_steps"]], 1
                )
            ]
            while len(steps) < profile["min_steps"]:
                steps.append(
                    ResearchPlanStepV1(
                        step_key=f"step-{len(steps) + 1}",
                        title="证据缺口",
                        question=f"{case['objective']}：检查适用条件与证据缺口{len(steps)}",
                        sources=["knowledge_base"],
                    )
                )
            repository.write_plan(
                username="offline-eval",
                tenant_id="offline",
                project_id=project.id,
                expected_project_version=project.version,
                steps=steps,
                origin="user",
            )
            model_snapshot = build_model_catalog_snapshot(
                {
                    role: ModelRuntimeSpec(
                        profile_id="model_"
                        + hashlib.sha256(role.value.encode()).hexdigest()[:32],
                        profile_version=1,
                        display_name=role.value,
                        model_name="offline-extractive",
                        timeout_seconds=30,
                        supports_stream=True,
                        supports_structured_output=True,
                    )
                    for role in (ModelRole.ANSWER, ModelRole.FAST, ModelRole.GRADER)
                }
            )
            current = repository.get_project(
                username="offline-eval", tenant_id="offline", project_id=project.id
            )
            approved = repository.approve(
                username="offline-eval",
                tenant_id="offline",
                project_id=project.id,
                expected_project_version=current.version,
                idempotency_key="offline-eval",
                model_snapshot=model_snapshot,
            )
            runs = RunRepository(factory)
            claimed = runs.claim(
                run_id=approved.run_id, worker_id="offline-eval", lease_seconds=600
            )
            snapshot = runs.load_execution_snapshot(
                username="offline-eval",
                run_id=claimed.id,
                worker_id="offline-eval",
                fencing_token=claimed.fencing_token,
            )
            evidence = [
                {
                    "stable_key": source,
                    "source_kind": "knowledge_base",
                    "title": f"{source}.md",
                    "content": (sources_root / f"{source}.md").read_text(
                        encoding="utf-8"
                    ),
                    "metadata": {"fixture_source_id": source},
                }
                for source in case["sources"]
            ]
            runner = ResearchWorkflowRunner(
                store=ResearchWorkflowStore(
                    factory, artifacts=ArtifactService(factory, root=root / "artifacts")
                ),
                models=OfflineModels(),
                executor=OfflineExecutor(),
            )
            # Only retrieval and model adapters are replaced; all workflow, persistence,
            # ownership, Events, Claims, Sections and Artifacts use production code.
            runner._resolve_knowledge_scope = lambda **_kwargs: object()
            runner._retrieve_knowledge = lambda *_args, **_kwargs: evidence
            report = asyncio.run(
                runner.run(
                    snapshot=snapshot, token=OfflineToken(), worker_id="offline-eval"
                )
            )
            metrics = repository.metrics(
                username="offline-eval",
                tenant_id="offline",
                project_id=project.id,
                run_id=claimed.id,
            )
            finished = runs.finalize(
                run_id=claimed.id,
                target_status="succeeded",
                content=report,
                fencing_token=claimed.fencing_token,
                input_tokens=metrics["input_tokens"],
                output_tokens=metrics["output_tokens"],
            )
            scope = {
                "username": "offline-eval",
                "tenant_id": "offline",
                "project_id": project.id,
                "run_id": claimed.id,
            }
            return {
                "report": report,
                "completed": finished.status == "succeeded",
                "plan_steps": len(steps),
                "evidence": repository.list_evidence(**scope),
                "claims": repository.list_claims(**scope),
                "sections": repository.list_sections(**scope),
                "metrics": metrics,
            }
        finally:
            engine.dispose()
