"""add grounded DataQa semantic schema

Revision ID: 0022_dataqa_semantic_schema
Revises: 0021_dataqa_workbench
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op


revision = "0022_dataqa_semantic_schema"
down_revision = "0021_dataqa_workbench"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataqa_semantic_metadata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("schema_name", sa.String(length=63), nullable=False),
        sa.Column("table_name", sa.String(length=63), nullable=False),
        sa.Column(
            "column_name", sa.String(length=63), nullable=False, server_default=""
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(schema_name) > 0 AND length(table_name) > 0",
            name="ck_dataqa_semantic_metadata_relation",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["sql_assistant_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "schema_name",
            "table_name",
            "column_name",
            name="uq_dataqa_semantic_metadata_identity",
        ),
    )
    op.create_index(
        "ix_dataqa_semantic_metadata_profile_id",
        "dataqa_semantic_metadata",
        ["profile_id"],
    )
    op.create_index(
        "ix_dataqa_semantic_metadata_updated_by_user_id",
        "dataqa_semantic_metadata",
        ["updated_by_user_id"],
    )
    op.add_column(
        "dataqa_queries",
        sa.Column("semantic_schema_hash", sa.CHAR(length=64), nullable=True),
    )
    op.add_column(
        "dataqa_queries",
        sa.Column("candidate_schema_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT 1 FROM dataqa_semantic_metadata LIMIT 1")
    ).first():
        raise RuntimeError("dataqa semantic metadata contains data; downgrade refused")
    if connection.execute(
        sa.text(
            "SELECT 1 FROM dataqa_queries "
            "WHERE semantic_schema_hash IS NOT NULL OR candidate_schema_json IS NOT NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError("dataqa grounding snapshots contain data; downgrade refused")
    op.drop_column("dataqa_queries", "candidate_schema_json")
    op.drop_column("dataqa_queries", "semantic_schema_hash")
    op.drop_index(
        "ix_dataqa_semantic_metadata_updated_by_user_id",
        table_name="dataqa_semantic_metadata",
    )
    op.drop_index(
        "ix_dataqa_semantic_metadata_profile_id",
        table_name="dataqa_semantic_metadata",
    )
    op.drop_table("dataqa_semantic_metadata")
