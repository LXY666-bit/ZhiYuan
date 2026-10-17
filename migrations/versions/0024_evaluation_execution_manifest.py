"""Freeze the retrieval/source identity for each Evaluation Job.

Legacy jobs retain NULL: their historical retrieval scope cannot be reconstructed.
Workers reject such active jobs instead of silently resolving today's catalog.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_eval_execution_manifest"
down_revision = "0023_model_timeout_720"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_evaluation_jobs",
        sa.Column("execution_manifest_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError("Evaluation execution identity would be lost; downgrade refused")
