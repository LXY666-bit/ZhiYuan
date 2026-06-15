import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/langchain_app",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def init_db() -> None:
    # 延迟导入以避免循环依赖。
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # 自动迁移：为已有表添加新列
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS web_sources JSON"
            ))
        except Exception:
            pass
