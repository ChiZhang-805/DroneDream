from __future__ import annotations

import importlib

from sqlalchemy import text


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
    assert "lease_owner" in columns
    assert "lease_expires_at" in columns
    assert "claimed_at" in columns
    assert "cancelled_at" in batch_columns
