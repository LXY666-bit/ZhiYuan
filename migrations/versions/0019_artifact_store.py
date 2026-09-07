"""add tenant-scoped platform artifact store

Revision ID: 0019_artifact_store
Revises: 0018_capability_control_plane
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op


revision = "0019_artifact_store"
down_revision = "0018_capability_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("owner_type", sa.String(length=48), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("logical_type", sa.String(length=48), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_artifact_id", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("state IN ('draft', 'final')", name="ck_artifacts_state"),
        sa.CheckConstraint("version >= 1", name="ck_artifacts_version_positive"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifacts_size_nonnegative"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_artifacts_sha256_length"),
        sa.ForeignKeyConstraint(
            ["parent_artifact_id"], ["artifacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_artifacts_storage_key"),
        sa.UniqueConstraint(
            "tenant_id",
            "owner_type",
            "owner_id",
            "logical_type",
            "version",
            name="uq_artifact_owner_logical_version",
        ),
    )
    op.create_index("ix_artifacts_tenant_id", "artifacts", ["tenant_id"])
    op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"])
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_owner_id", "artifacts", ["owner_id"])
    op.create_index(
        "uq_artifact_one_draft",
        "artifacts",
        ["run_id", "logical_type"],
        unique=True,
        postgresql_where=sa.text("state = 'draft'"),
        sqlite_where=sa.text("state = 'draft'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM artifacts LIMIT 1")).first():
        raise RuntimeError("artifact store contains data; downgrade refused")
    op.drop_index("uq_artifact_one_draft", table_name="artifacts")
    op.drop_index("ix_artifacts_owner_id", table_name="artifacts")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_user_id", table_name="artifacts")
    op.drop_index("ix_artifacts_tenant_id", table_name="artifacts")
    op.drop_table("artifacts")
