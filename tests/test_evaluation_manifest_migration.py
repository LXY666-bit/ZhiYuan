import pytest
from alembic import command
from sqlalchemy import create_engine, text

from backend.infra.database import alembic_config


def test_upgrade_preserves_legacy_job_without_inventing_retrieval_identity(tmp_path):
    url = f"sqlite:///{tmp_path / 'evaluation.db'}"
    config = alembic_config(url)
    command.upgrade(config, "0023_model_timeout_720")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO rag_evaluation_datasets
                    (id, name, fingerprint, payload_json, case_count, created_at, updated_at)
                VALUES ('dataset', 'legacy', :fingerprint, '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
                {"fingerprint": "a" * 64},
            )
            connection.execute(
                text("""
                INSERT INTO rag_evaluation_jobs
                    (id, dataset_id, status, completed_cases, total_cases, gate_policy_json,
                     model_catalog_hash, model_snapshot_json, fencing_token, attempts, max_attempts,
                     created_at, updated_at)
                VALUES ('job', 'dataset', 'queued', 0, 1, '{}', :fingerprint, '{}', 0, 0, 3,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
                {"fingerprint": "b" * 64},
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT status, execution_manifest_json FROM rag_evaluation_jobs WHERE id='job'"
                )
            ).one()
            assert row == ("queued", None)
        with pytest.raises(RuntimeError, match="downgrade refused"):
            command.downgrade(config, "0023_model_timeout_720")
    finally:
        engine.dispose()
