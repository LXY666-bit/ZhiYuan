"""add dataqa workbench persistence

Revision ID: 0021_dataqa_workbench
Revises: 0020_research_workbench
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op


revision = "0021_dataqa_workbench"
down_revision = "0020_research_workbench"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("threads") as batch:
        batch.drop_constraint("ck_threads_kind", type_="check")
        batch.create_check_constraint(
            "ck_threads_kind", "kind IN ('chat', 'research', 'dataqa')"
        )
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_runs_channel", "runs", type_="check")
        op.create_check_constraint(
            "ck_runs_channel", "runs", "channel IN ('run', 'research', 'dataqa')"
        )

    op.create_table(
        "dataqa_queries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("thread_ref_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_dataqa_queries_status",
        ),
        sa.ForeignKeyConstraint(["thread_ref_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_dataqa_query_run"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_dataqa_query_key"),
    )
    op.create_index("ix_dataqa_queries_tenant_id", "dataqa_queries", ["tenant_id"])
    op.create_index("ix_dataqa_queries_user_id", "dataqa_queries", ["user_id"])
    op.create_index(
        "ix_dataqa_queries_thread_ref_id", "dataqa_queries", ["thread_ref_id"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM dataqa_queries LIMIT 1")).first():
        raise RuntimeError("dataqa workbench contains data; downgrade refused")
    op.drop_index("ix_dataqa_queries_thread_ref_id", table_name="dataqa_queries")
    op.drop_index("ix_dataqa_queries_user_id", table_name="dataqa_queries")
    op.drop_index("ix_dataqa_queries_tenant_id", table_name="dataqa_queries")
    op.drop_table("dataqa_queries")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_runs_channel", "runs", type_="check")
        op.create_check_constraint(
            "ck_runs_channel", "runs", "channel IN ('run', 'research')"
        )
    with op.batch_alter_table("threads") as batch:
        batch.drop_constraint("ck_threads_kind", type_="check")
        batch.create_check_constraint("ck_threads_kind", "kind IN ('chat', 'research')")
