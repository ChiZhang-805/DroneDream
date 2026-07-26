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
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
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
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('trials')")).fetchall()
        }
        batch_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('batch_jobs')")).fetchall()
        }
        secret_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('job_secrets')")).fetchall()
        }
        candidate_columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info('candidate_parameter_sets')")
            ).fetchall()
        }
        report_columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info('job_reports')")
            ).fetchall()
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
    assert "lease_owner" in columns
    assert "lease_expires_at" in columns
    assert "claimed_at" in columns
    assert "cancelled_at" in batch_columns
    assert "expires_at" in secret_columns
    assert "optimizer_metadata_json" in candidate_columns
    assert "winner_evidence_json" in report_columns
    assert "winner_freeze_receipt_id" in report_columns
    assert winner_freeze_triggers == {
        "trg_winner_freeze_receipts_no_update",
        "trg_winner_freeze_receipts_no_delete",
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
                "AND tbl_name='winner_freeze_receipts'"
            ).fetchall()
        }
    assert trigger_names == {
        "trg_winner_freeze_receipts_no_update",
        "trg_winner_freeze_receipts_no_delete",
    }


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
    assert (
        "CREATE TRIGGER trg_winner_freeze_receipts_immutable" in sql
    )
    assert "BEFORE UPDATE OR DELETE ON winner_freeze_receipts" in sql
    assert "winner freeze receipts are append-only" in sql
