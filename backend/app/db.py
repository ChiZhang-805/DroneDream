"""Database engine, session, and Base for the DroneDream backend.

SQLite is the default for local development. The code avoids SQLite-specific
features so Postgres can be swapped in later by changing ``DATABASE_URL``.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _build_engine(database_url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        # SQLite in a multi-threaded test/dev server needs this.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, future=True)


_settings = get_settings()
engine: Engine = _build_engine(_settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def init_db() -> None:
    """Create development tables unless schema management is external.

    Production deployments set ``DATABASE_AUTO_CREATE=false`` and run
    Alembic before starting the API, avoiding implicit schema drift at import
    time. The default remains enabled for SQLite tests and local development.
    """

    # Import models so they are registered on Base.metadata before create_all.
    from app import models  # noqa: F401

    if _settings.database_auto_create:
        Base.metadata.create_all(bind=engine)
        _apply_sqlite_lightweight_migrations()


def _apply_sqlite_lightweight_migrations() -> None:
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "users" in table_names:
            user_columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info('users')")).fetchall()
            }
            if "identity_provider" not in user_columns:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN identity_provider VARCHAR(255)")
                )
            if "external_subject" not in user_columns:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN external_subject VARCHAR(255)")
                )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_users_identity_provider_subject "
                    "ON users(identity_provider, external_subject) "
                    "WHERE external_subject IS NOT NULL"
                )
            )
        job_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('jobs')")).fetchall()
        }
        if "advanced_scenario_config_json" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN advanced_scenario_config_json JSON"))
        if "baseline_parameter_json" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN baseline_parameter_json JSON"))
        if "display_name" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN display_name VARCHAR(255)"))
        if "batch_id" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN batch_id VARCHAR(64)"))
        experiment_columns = {
            "vehicle_profile_json": "JSON",
            "parameter_space_json": "JSON",
            "objective_config_json": "JSON",
            "scenario_suite_json": "JSON",
            "llm_provider": "VARCHAR(64)",
            "llm_base_url": "VARCHAR(2048)",
        }
        for column_name, column_type in experiment_columns.items():
            if column_name not in job_columns:
                conn.execute(
                    text(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}")
                )
        if "parameter_catalog_version" not in job_columns:
            conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN parameter_catalog_version "
                    "VARCHAR(128) NOT NULL DEFAULT 'builtin-v1'"
                )
            )
        if "batch_jobs" in table_names:
            batch_columns = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info('batch_jobs')")).fetchall()
            }
            if "cancelled_at" not in batch_columns:
                conn.execute(text("ALTER TABLE batch_jobs ADD COLUMN cancelled_at DATETIME"))
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info('trials')")).fetchall()
        }
        add_sql: list[str] = []
        if "lease_owner" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN lease_owner VARCHAR(64)")
        if "lease_expires_at" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN lease_expires_at DATETIME")
        if "claimed_at" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN claimed_at DATETIME")
        for stmt in add_sql:
            conn.execute(text(stmt))


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["Base", "SessionLocal", "engine", "get_db", "init_db"]
