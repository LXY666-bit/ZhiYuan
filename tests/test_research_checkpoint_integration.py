from __future__ import annotations

import asyncio
import os
import selectors
import sys
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, StateGraph

from backend.rag.checkpointing import postgres_async_saver_factory


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1",
    reason="set RUN_POSTGRES_TESTS=1 with the migrated PostgreSQL test database",
)


class State(TypedDict):
    run_id: str
    stage: str


async def _exercise_checkpoint() -> None:
    run_id = f"run_research_checkpoint_{uuid4().hex}"
    config = {"configurable": {"thread_id": run_id}}
    builder = StateGraph(State)
    builder.add_node(
        "research_stage",
        lambda state: {"run_id": state["run_id"], "stage": "evidence_persisted"},
    )
    builder.set_entry_point("research_stage")
    builder.add_edge("research_stage", END)

    async with postgres_async_saver_factory() as saver:
        graph = builder.compile(checkpointer=saver)
        first = await graph.ainvoke(
            {"run_id": run_id, "stage": "planned"}, config=config
        )
        recovered = await graph.aget_state(config)
        assert first == {"run_id": run_id, "stage": "evidence_persisted"}
        assert recovered.values == first
        assert recovered.config["configurable"]["thread_id"] == run_id
        await saver.conn.execute(
            "DELETE FROM checkpoint_writes WHERE thread_id = %s", (run_id,)
        )
        await saver.conn.execute(
            "DELETE FROM checkpoint_blobs WHERE thread_id = %s", (run_id,)
        )
        await saver.conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = %s", (run_id,)
        )


def test_research_langgraph_checkpoint_recovers_same_run_identity():
    if sys.platform == "win32":
        with asyncio.Runner(
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        ) as runner:
            runner.run(_exercise_checkpoint())
    else:
        asyncio.run(_exercise_checkpoint())
