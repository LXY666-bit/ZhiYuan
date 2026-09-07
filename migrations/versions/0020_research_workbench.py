"""add research workbench persistence

Revision ID: 0020_research_workbench
Revises: 0019_artifact_store
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op


revision = "0020_research_workbench"
down_revision = "0019_artifact_store"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def upgrade() -> None:
    with op.batch_alter_table("threads") as batch:
        batch.add_column(
            sa.Column(
                "kind", sa.String(length=24), server_default="chat", nullable=False
            )
        )
        batch.create_check_constraint("ck_threads_kind", "kind IN ('chat', 'research')")
    op.create_index("ix_threads_kind", "threads", ["kind"])
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_runs_channel", "runs", "channel IN ('run', 'research')"
        )
    op.create_index("ix_runs_channel", "runs", ["channel"])

    op.create_table(
        "research_projects",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("thread_ref_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("source_config_json", sa.JSON(), nullable=False),
        sa.Column("output_format_json", sa.JSON(), nullable=False),
        sa.Column("current_plan_version", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "lifecycle_status IN ('draft', 'awaiting_approval', 'frozen')",
            name="ck_research_projects_lifecycle",
        ),
        sa.CheckConstraint(
            "mode IN ('quick', 'standard', 'deep')",
            name="ck_research_projects_mode",
        ),
        sa.ForeignKeyConstraint(["thread_ref_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_ref_id", name="uq_research_project_thread"),
    )
    op.create_index(
        "ix_research_projects_tenant_id", "research_projects", ["tenant_id"]
    )
    op.create_index("ix_research_projects_user_id", "research_projects", ["user_id"])

    op.create_table(
        "research_plans",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(length=24), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_research_plans_version_positive"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["research_projects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="uq_research_plan_version"),
    )
    op.create_index("ix_research_plans_project_id", "research_plans", ["project_id"])

    op.create_table(
        "research_plan_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("project_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("model_catalog_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("model_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("owner_worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail_redacted", sa.Text(), nullable=True),
        sa.Column("result_plan_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'cancelling', 'cancelled', 'completed', 'failed')",
            name="ck_research_plan_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["research_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["result_plan_id"], ["research_plans.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "idempotency_key", name="uq_research_plan_job_key"
        ),
    )
    op.create_index(
        "ix_research_plan_jobs_project_id", "research_plan_jobs", ["project_id"]
    )
    op.create_index(
        "uq_research_plan_job_active",
        "research_plan_jobs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running', 'cancelling')"),
        sqlite_where=sa.text("status IN ('pending', 'running', 'cancelling')"),
    )

    op.create_table(
        "research_run_manifests",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["research_plans.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["research_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_research_run_manifests_project_id", "research_run_manifests", ["project_id"]
    )

    op.create_table(
        "research_steps",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_key", sa.String(length=96), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'degraded', 'failed')",
            name="ck_research_steps_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_key", name="uq_research_step_run_key"),
    )
    op.create_index("ix_research_steps_run_id", "research_steps", ["run_id"])

    op.create_table(
        "research_evidence",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("stable_key", sa.String(length=160), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("published_date", sa.DateTime(), nullable=True),
        sa.Column("relevance_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("quality_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("quality_reason", sa.String(length=500), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "stable_key", name="uq_research_evidence_key"),
        sa.UniqueConstraint(
            "run_id", "citation_number", name="uq_research_evidence_citation"
        ),
    )
    op.create_index("ix_research_evidence_run_id", "research_evidence", ["run_id"])
    op.create_index(
        "ix_research_evidence_content_hash", "research_evidence", ["content_hash"]
    )

    op.create_table(
        "research_claims",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("claim_key", sa.String(length=160), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "verdict IN ('supported', 'unsupported', 'conflicting', 'insufficient')",
            name="ck_research_claims_verdict",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "claim_key", name="uq_research_claim_key"),
    )
    op.create_index("ix_research_claims_run_id", "research_claims", ["run_id"])

    op.create_table(
        "research_claim_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.String(length=96), nullable=False),
        sa.Column("evidence_id", sa.String(length=96), nullable=False),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"], ["research_claims.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["research_evidence.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id", "evidence_id", name="uq_research_claim_evidence"
        ),
    )

    op.create_table(
        "research_sections",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("section_key", sa.String(length=96), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'writing', 'completed', 'degraded', 'failed')",
            name="ck_research_sections_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "section_key", name="uq_research_section_key"),
        sa.UniqueConstraint("run_id", "position", name="uq_research_section_position"),
    )
    op.create_index("ix_research_sections_run_id", "research_sections", ["run_id"])

    op.create_table(
        "research_attachments",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("version_key", sa.String(length=96), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("vector_collection", sa.String(length=160), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'indexing', 'indexed', 'failed', 'deleting')",
            name="ck_research_attachments_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["research_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_research_attachment_storage_key"),
        sa.UniqueConstraint(
            "project_id", "version_key", name="uq_research_attachment_version"
        ),
    )
    op.create_index(
        "ix_research_attachments_project_id", "research_attachments", ["project_id"]
    )
    op.create_index(
        "ix_research_attachments_tenant_id", "research_attachments", ["tenant_id"]
    )
    op.create_index(
        "ix_research_attachments_user_id", "research_attachments", ["user_id"]
    )

    op.create_table(
        "research_attachment_jobs",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("attachment_id", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("owner_worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail_redacted", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_research_attachment_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["research_attachments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_attachment_jobs_attachment_id",
        "research_attachment_jobs",
        ["attachment_id"],
    )
    op.create_index(
        "ix_research_attachment_jobs_claim",
        "research_attachment_jobs",
        ["status", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "uq_research_attachment_job_active",
        "research_attachment_jobs",
        ["attachment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )

    op.create_table(
        "research_usage",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("plan_job_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_job_id"], ["research_plan_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["research_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_usage_project_id", "research_usage", ["project_id"])
    op.create_index("ix_research_usage_run_id", "research_usage", ["run_id"])


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM research_projects LIMIT 1")).first():
        raise RuntimeError("research workbench contains data; downgrade refused")
    for table in (
        "research_usage",
        "research_attachment_jobs",
        "research_attachments",
        "research_sections",
        "research_claim_evidence",
        "research_claims",
        "research_evidence",
        "research_steps",
        "research_run_manifests",
        "research_plan_jobs",
        "research_plans",
        "research_projects",
    ):
        op.drop_table(table)
    op.drop_index("ix_threads_kind", table_name="threads")
    with op.batch_alter_table("threads") as batch:
        batch.drop_constraint("ck_threads_kind", type_="check")
        batch.drop_column("kind")
    op.drop_index("ix_runs_channel", table_name="runs")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_runs_channel", "runs", type_="check")
