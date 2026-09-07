from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.core.settings import get_settings


def postgres_checkpoint_dsn() -> str:
    value = get_settings().storage.database_url.get_secret_value()
    for driver in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+asyncpg://",
    ):
        if value.startswith(driver):
            return "postgresql://" + value[len(driver) :]
    if value.startswith("postgresql://"):
        return value
    raise RuntimeError(
        "LangGraph PostgreSQL checkpointer requires a PostgreSQL DATABASE_URL"
    )


@contextmanager
def postgres_saver_factory() -> Iterator[BaseCheckpointSaver]:
    # Alembic owns the official checkpoint_* tables; do not call saver.setup() here.
    with PostgresSaver.from_conn_string(postgres_checkpoint_dsn()) as saver:
        yield saver


@asynccontextmanager
async def postgres_async_saver_factory() -> AsyncIterator[AsyncPostgresSaver]:
    # Alembic owns the official checkpoint_* tables; do not call saver.setup() here.
    async with AsyncPostgresSaver.from_conn_string(postgres_checkpoint_dsn()) as saver:
        yield saver
