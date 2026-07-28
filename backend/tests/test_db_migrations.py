from __future__ import annotations

import importlib
import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import BigInteger, text


def test_sqlite_lightweight_migration_adds_trial_lease_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "migrate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")

    from app import config as config_module

    config_module.get_settings.cache_clear()

    import app.db as db_module

    importlib.reload(db_module)

    with db_module.engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE jobs (
                    id VARCHAR(64) PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE candidate_parameter_sets (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64) NOT NULL,
                    aggregated_metric_json JSON,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO candidate_parameter_sets (
                    id,
                    job_id,
                    aggregated_metric_json,
                    created_at,
                    updated_at
                ) VALUES
                (
                    'candidate-v3',
                    'job-v3',
                    '{"candidate_outcome_evidence":{"schema_id":"dronedream.candidate-outcome-evidence/v3"}}',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                ),
                (
                    'candidate-v2',
                    'job-v2',
                    '{"candidate_outcome_evidence":{"schema_id":"dronedream.candidate-outcome-evidence/v2"}}',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE job_reports (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64) NOT NULL,
                    report_status VARCHAR(16) NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE winner_freeze_receipts (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64) NOT NULL,
                    evidence_id VARCHAR(71) NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE artifacts (
                    id VARCHAR(64) PRIMARY KEY,
                    owner_type VARCHAR(32) NOT NULL,
                    owner_id VARCHAR(64) NOT NULL,
                    artifact_type VARCHAR(32) NOT NULL,
                    storage_path VARCHAR(512) NOT NULL,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE artifact_digest_receipts (
                    id VARCHAR(64) PRIMARY KEY,
                    artifact_id VARCHAR(64) NOT NULL,
                    evidence_id VARCHAR(71) NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE trials (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64) NOT NULL,
                    candidate_id VARCHAR(64) NOT NULL,
                    seed INTEGER NOT NULL DEFAULT 0,
                    scenario_type VARCHAR(32) NOT NULL DEFAULT 'nominal',
                    scenario_config_json JSON,
                    worker_id VARCHAR(64),
                    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    failure_reason TEXT,
                    failure_code VARCHAR(64),
                    queued_at DATETIME,
                    started_at DATETIME,
                    finished_at DATETIME,
                    simulator_backend VARCHAR(64),
                    log_excerpt TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE batch_jobs (
                    id VARCHAR(64) PRIMARY KEY,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE job_secrets (
                    id VARCHAR(64) PRIMARY KEY,
                    job_id VARCHAR(64) NOT NULL,
                    provider VARCHAR(32) NOT NULL,
                    encrypted_api_key TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    deleted_at DATETIME
                )
                """
            )
        )

    db_module._apply_sqlite_lightweight_migrations()

    with db_module.engine.begin() as conn:
        job_columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info('jobs')")
            ).fetchall()
        }
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info('trials')")).fetchall()}
        batch_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info('batch_jobs')")).fetchall()
        }
        secret_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info('job_secrets')")).fetchall()
        }
        candidate_columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info('candidate_parameter_sets')")
            ).fetchall()
        }
        candidate_evidence_requirements = dict(
            conn.execute(
                text("SELECT id, evidence_ledger_required FROM candidate_parameter_sets")
            ).fetchall()
        )
        report_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info('job_reports')")).fetchall()
        }
        winner_freeze_triggers = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' "
                    "AND tbl_name='winner_freeze_receipts'"
                )
            ).fetchall()
        }
        winner_freeze_delete_authorization_columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info('winner_freeze_delete_authorizations')")
            ).fetchall()
        }
        artifact_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info('artifacts')")).fetchall()
        }
        artifact_digest_triggers = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='trigger' "
                    "AND tbl_name='artifact_digest_receipts'"
                )
            ).fetchall()
        }
        artifact_digest_delete_authorization_columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info('artifact_digest_delete_authorizations')")
            ).fetchall()
        }
    assert {
        "finalization_claim_token",
        "finalization_claim_generation",
        "finalization_lease_expires_at",
    }.issubset(job_columns)
    assert "control_version" in job_columns
    assert "lease_owner" in columns
    assert "lease_expires_at" in columns
    assert "claimed_at" in columns
    assert "accepted_attempt_id" in columns
    assert "cancelled_at" in batch_columns
    assert "control_version" in batch_columns
    assert "expires_at" in secret_columns
    assert "optimizer_metadata_json" in candidate_columns
    assert "evidence_ledger_required" in candidate_columns
    assert candidate_evidence_requirements == {
        "candidate-v2": 0,
        "candidate-v3": 1,
    }
    assert "winner_evidence_json" in report_columns
    assert "winner_freeze_receipt_id" in report_columns
    assert winner_freeze_triggers == {
        "trg_winner_freeze_receipts_no_update",
        "trg_winner_freeze_receipts_no_delete",
    }
    assert winner_freeze_delete_authorization_columns == {
        "receipt_id",
        "reason",
        "created_at",
    }
    assert "integrity_policy" in artifact_columns
    assert artifact_digest_triggers == {
        "trg_artifact_digest_receipts_no_update",
        "trg_artifact_digest_receipts_no_delete",
    }
    assert artifact_digest_delete_authorization_columns == {
        "artifact_id",
        "reason",
        "created_at",
    }


def test_sqlite_engine_enables_foreign_key_enforcement(tmp_path) -> None:
    from app.db import _build_engine

    local_engine = _build_engine(f"sqlite:///{tmp_path / 'foreign-keys.db'}")
    try:
        with local_engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        local_engine.dispose()


def test_artifact_size_uses_big_integer_in_production_schema() -> None:
    from app import models

    assert isinstance(models.Artifact.__table__.c.file_size_bytes.type, BigInteger)


def test_alembic_accepts_percent_encoded_database_urls(tmp_path: Path) -> None:
    database_path = (tmp_path / "encoded%25password.db").as_posix()
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "DATABASE_AUTO_CREATE": "false",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from alembic.config import main; main(argv=['upgrade', 'head'])",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    migrated_path = tmp_path / "encoded%25password.db"
    assert migrated_path.is_file()
    with sqlite3.connect(migrated_path) as connection:
        trigger_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='trigger' "
                "AND tbl_name IN ("
                "'winner_freeze_receipts', "
                "'artifact_digest_receipts', "
                "'trial_execution_attempts', "
                "'trial_execution_attempt_outcomes', "
                "'candidate_evidence_receipts', "
                "'candidate_parameter_sets', "
                "'trials'"
                ")"
            ).fetchall()
        }
        attempt_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "AND name LIKE 'trial_execution_attempt%'"
            ).fetchall()
        }
        candidate_evidence_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "AND name LIKE 'candidate_evidence%'"
            ).fetchall()
        }
        winner_freeze_authorization_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "AND name='winner_freeze_delete_authorizations'"
            ).fetchall()
        }
        api_idempotency_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' "
                "AND name='api_idempotency_records'"
            ).fetchall()
        }
        api_idempotency_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('api_idempotency_records')"
            ).fetchall()
        }
        candidate_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('candidate_parameter_sets')"
            ).fetchall()
        }
        job_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('jobs')"
            ).fetchall()
        }
        batch_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info('batch_jobs')"
            ).fetchall()
        }
    assert trigger_names == {
        "trg_winner_freeze_receipts_no_update",
        "trg_winner_freeze_receipts_no_delete",
        "trg_artifact_digest_receipts_no_update",
        "trg_artifact_digest_receipts_no_delete",
        "trg_trial_execution_attempts_no_update",
        "trg_trial_execution_attempts_no_delete",
        "trg_trial_execution_attempt_outcomes_no_update",
        "trg_trial_execution_attempt_outcomes_no_delete",
        "trg_trials_accepted_attempt_immutable",
        "trg_candidate_evidence_receipts_no_update",
        "trg_candidate_evidence_receipts_no_delete",
        "trg_candidate_evidence_required_no_downgrade",
        "trg_candidate_provenance_no_mutation",
    }
    assert attempt_tables == {
        "trial_execution_attempts",
        "trial_execution_attempt_outcomes",
        "trial_execution_attempt_delete_authorizations",
    }
    assert candidate_evidence_tables == {
        "candidate_evidence_receipts",
        "candidate_evidence_delete_authorizations",
    }
    assert winner_freeze_authorization_tables == {
        "winner_freeze_delete_authorizations",
    }
    assert api_idempotency_tables == {"api_idempotency_records"}
    assert {
        "user_id",
        "idempotency_key_hash",
        "operation",
        "request_hash",
        "status",
        "response_json",
        "resource_type",
        "resource_id",
    }.issubset(api_idempotency_columns)
    assert "evidence_ledger_required" in candidate_columns
    assert {
        "finalization_claim_token",
        "finalization_claim_generation",
        "finalization_lease_expires_at",
    }.issubset(job_columns)
    assert "control_version" in job_columns
    assert "control_version" in batch_columns


def test_postgresql_winner_freeze_migration_emits_immutable_trigger(
    monkeypatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260726_0006_winner_freeze_guards.py"
    )
    spec = importlib.util.spec_from_file_location(
        "winner_freeze_guards_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    emitted: list[str] = []

    class _PostgresOp:
        @staticmethod
        def get_bind():
            return type(
                "_Bind",
                (),
                {"dialect": type("_Dialect", (), {"name": "postgresql"})()},
            )()

        @staticmethod
        def execute(statement: str) -> None:
            emitted.append(statement)

    monkeypatch.setattr(migration, "op", _PostgresOp)
    migration.upgrade()

    sql = "\n".join(emitted)
    assert "CREATE FUNCTION dronedream_reject_winner_freeze_mutation()" in sql
    assert "CREATE TRIGGER trg_winner_freeze_receipts_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON winner_freeze_receipts" in sql
    assert "winner freeze receipts are append-only" in sql


def test_postgresql_artifact_digest_migration_emits_immutable_trigger(
    monkeypatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260726_0007_artifact_digests.py"
    )
    spec = importlib.util.spec_from_file_location(
        "artifact_digest_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    emitted: list[str] = []

    class _BatchOp:
        @staticmethod
        def add_column(column) -> None:
            assert column.name == "integrity_policy"

    class _BatchContext:
        def __enter__(self):
            return _BatchOp()

        def __exit__(self, exc_type, exc, traceback) -> None:
            _ = exc_type, exc, traceback

    class _PostgresOp:
        @staticmethod
        def get_bind():
            return type(
                "_Bind",
                (),
                {"dialect": type("_Dialect", (), {"name": "postgresql"})()},
            )()

        @staticmethod
        def batch_alter_table(table_name: str):
            assert table_name == "artifacts"
            return _BatchContext()

        @staticmethod
        def create_table(table_name: str, *columns) -> None:
            assert table_name in {
                "artifact_digest_receipts",
                "artifact_digest_delete_authorizations",
            }
            assert columns

        @staticmethod
        def execute(statement: str) -> None:
            emitted.append(statement)

    monkeypatch.setattr(migration, "op", _PostgresOp)
    migration.upgrade()

    sql = "\n".join(emitted)
    assert "CREATE FUNCTION dronedream_reject_artifact_digest_mutation()" in sql
    assert "CREATE TRIGGER trg_artifact_digest_receipts_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON artifact_digest_receipts" in sql
    assert "artifact_digest_delete_authorizations" in sql
    assert "artifact digest receipts are append-only" in sql


def test_postgresql_trial_attempt_migration_emits_immutable_guards(
    monkeypatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260726_0008_trial_execution_attempts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "trial_attempt_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    emitted: list[str] = []

    class _PostgresOp:
        @staticmethod
        def execute(statement: str) -> None:
            emitted.append(statement)

    monkeypatch.setattr(migration, "op", _PostgresOp)
    migration._install_postgres_guards()

    sql = "\n".join(emitted)
    assert ("CREATE FUNCTION dronedream_reject_trial_execution_attempt_mutation()") in sql
    assert "BEFORE UPDATE OR DELETE ON trial_execution_attempts" in sql
    assert "BEFORE UPDATE OR DELETE ON trial_execution_attempt_outcomes" in sql
    assert "trial_execution_attempt_delete_authorizations" in sql
    assert "CREATE FUNCTION dronedream_guard_trial_accepted_attempt()" in sql
    assert "BEFORE UPDATE OF accepted_attempt_id ON trials" in sql
    assert "belongs to another Trial" in sql


def test_alembic_has_one_schema_head() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    heads = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert heads == ["20260728_0015 (head)"]


def test_postgresql_candidate_evidence_migration_emits_immutable_guard(
    monkeypatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260726_0009_candidate_evidence_ledger.py"
    )
    spec = importlib.util.spec_from_file_location(
        "candidate_evidence_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    emitted: list[str] = []

    class _PostgresOp:
        @staticmethod
        def execute(statement: str) -> None:
            emitted.append(statement)

    monkeypatch.setattr(migration, "op", _PostgresOp)
    migration._install_postgres_guards()

    sql = "\n".join(emitted)
    assert "CREATE FUNCTION dronedream_reject_candidate_evidence_mutation()" in sql
    assert "BEFORE UPDATE OR DELETE ON candidate_evidence_receipts" in sql
    assert "candidate_evidence_delete_authorizations" in sql
    assert "Candidate evidence receipts are append-only" in sql
    assert "winner_freeze_delete_authorizations" in sql
    assert "winner freeze receipts are append-only" in sql
    assert "dronedream_reject_candidate_evidence_downgrade" in sql
    assert "BEFORE UPDATE OF evidence_ledger_required" in sql


def test_postgresql_candidate_provenance_migration_freezes_source_and_metadata(
    monkeypatch,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260727_0010_candidate_provenance_guards.py"
    )
    spec = importlib.util.spec_from_file_location(
        "candidate_provenance_migration",
        migration_path,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    emitted: list[str] = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _PostgresOp:
        @staticmethod
        def get_bind() -> _Bind:
            return _Bind()

        @staticmethod
        def execute(statement: str) -> None:
            emitted.append(statement)

    monkeypatch.setattr(migration, "op", _PostgresOp)
    migration.upgrade()

    sql = "\n".join(emitted)
    assert "dronedream_reject_candidate_provenance_mutation" in sql
    assert "BEFORE UPDATE OF source_type, optimizer_metadata_json" in sql
    assert "NEW.source_type IS DISTINCT FROM OLD.source_type" in sql
    assert "NEW.optimizer_metadata_json" in sql
    assert "Candidate provenance is immutable after evidence sealing" in sql
