"""extend Model Profile timeout ceiling for deep research

Revision ID: 0023_model_timeout_720
Revises: 0022_dataqa_semantic_schema
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op


revision = "0023_model_timeout_720"
down_revision = "0022_dataqa_semantic_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_profile_timeout_range", type_="check")
        batch.create_check_constraint(
            "ck_model_profile_timeout_range",
            "timeout_seconds > 0 AND timeout_seconds <= 720",
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT 1 FROM model_profiles WHERE timeout_seconds > 600 LIMIT 1")
    ).first():
        raise RuntimeError(
            "Model Profile timeout exceeds 600 seconds; downgrade refused"
        )
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_constraint("ck_model_profile_timeout_range", type_="check")
        batch.create_check_constraint(
            "ck_model_profile_timeout_range",
            "timeout_seconds > 0 AND timeout_seconds <= 600",
        )
