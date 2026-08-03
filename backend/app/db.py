"""Database engine, session, and Base for the DroneDream backend.

SQLite is the default for local development. The code avoids SQLite-specific
features so Postgres can be swapped in later by changing ``DATABASE_URL``.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
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
        connect_args["timeout"] = get_settings().sqlite_busy_timeout_seconds
    built_engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=not database_url.startswith("sqlite"),
    )
    if database_url.startswith("sqlite"):
        # SQLite keeps foreign-key enforcement disabled per connection unless
        # explicitly enabled. ORM cascades cover normal application deletes,
        # but workers, migrations, and operator SQL must receive the same
        # referential-integrity guarantees as PostgreSQL.
        @event.listens_for(built_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return built_engine


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
                row[1] for row in conn.execute(text("PRAGMA table_info('users')")).fetchall()
            }
            if "identity_provider" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN identity_provider VARCHAR(255)"))
            if "external_subject" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN external_subject VARCHAR(255)"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_users_identity_provider_subject "
                    "ON users(identity_provider, external_subject) "
                    "WHERE external_subject IS NOT NULL"
                )
            )
        job_columns = {row[1] for row in conn.execute(text("PRAGMA table_info('jobs')")).fetchall()}
        if "advanced_scenario_config_json" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN advanced_scenario_config_json JSON"))
        if "baseline_parameter_json" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN baseline_parameter_json JSON"))
        if "display_name" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN display_name VARCHAR(255)"))
        if "batch_id" not in job_columns:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN batch_id VARCHAR(64)"))
        if "control_version" not in job_columns:
            conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN control_version "
                    "INTEGER NOT NULL DEFAULT 1"
                )
            )
        experiment_columns = {
            "vehicle_profile_json": "JSON",
            "parameter_space_json": "JSON",
            "objective_config_json": "JSON",
            "scenario_suite_json": "JSON",
            "llm_access_mode": "VARCHAR(16)",
            "llm_provider": "VARCHAR(64)",
            "llm_base_url": "VARCHAR(2048)",
        }
        for column_name, column_type in experiment_columns.items():
            if column_name not in job_columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}"))
        first_qualified_columns = {
            "completion_policy": (
                "VARCHAR(32) NOT NULL DEFAULT 'first_qualified_stop'"
            ),
            "job_kind": "VARCHAR(32) NOT NULL DEFAULT 'primary'",
            "cognitive_policy_version": (
                "VARCHAR(32) NOT NULL DEFAULT 'adaptive-2-4-v1'"
            ),
            "provider_turn_cap": "INTEGER NOT NULL DEFAULT 64",
            "provider_turns_attempted": "INTEGER NOT NULL DEFAULT 0",
            "provider_turns_succeeded": "INTEGER NOT NULL DEFAULT 0",
            "next_candidate_dispatch_ordinal": "BIGINT NOT NULL DEFAULT 1",
            "next_qualification_sequence": "BIGINT NOT NULL DEFAULT 1",
            "first_qualified_candidate_id": "VARCHAR(64)",
            "first_qualified_at": "DATETIME",
            "continue_exploration_requested": "BOOLEAN NOT NULL DEFAULT 0",
            "exploration_budget_json": "JSON",
            "continuation_parent_job_id": "VARCHAR(64)",
            "continuation_root_job_id": "VARCHAR(64)",
            "holdout_policy_version": (
                "VARCHAR(32) NOT NULL DEFAULT 'legacy-visible-v0'"
            ),
            "holdout_contract_json": "JSON",
        }
        for column_name, column_type in first_qualified_columns.items():
            if column_name not in job_columns:
                conn.execute(
                    text(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}")
                )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_jobs_first_qualified_candidate_id "
                "ON jobs(first_qualified_candidate_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_jobs_continuation_parent_job_id "
                "ON jobs(continuation_parent_job_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_jobs_continuation_root_job_id "
                "ON jobs(continuation_root_job_id)"
            )
        )
        conn.execute(
            text(
                "UPDATE jobs SET llm_access_mode = CASE "
                "WHEN llm_provider = 'dronedream' THEN 'platform' "
                "WHEN llm_provider IS NOT NULL THEN 'byok' "
                "ELSE NULL END "
                "WHERE llm_access_mode IS NULL"
            )
        )
        finalization_claim_columns = {
            "finalization_claim_token": "VARCHAR(64)",
            "finalization_claim_generation": "INTEGER",
            "finalization_lease_expires_at": "DATETIME",
        }
        for column_name, column_type in finalization_claim_columns.items():
            if column_name not in job_columns:
                conn.execute(
                    text(
                        f"ALTER TABLE jobs ADD COLUMN {column_name} "
                        f"{column_type}"
                    )
                )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_jobs_finalization_claim_token "
                "ON jobs(finalization_claim_token)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_jobs_finalization_lease_expires_at "
                "ON jobs(finalization_lease_expires_at)"
            )
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
                row[1] for row in conn.execute(text("PRAGMA table_info('batch_jobs')")).fetchall()
            }
            if "cancelled_at" not in batch_columns:
                conn.execute(text("ALTER TABLE batch_jobs ADD COLUMN cancelled_at DATETIME"))
            if "control_version" not in batch_columns:
                conn.execute(
                    text(
                        "ALTER TABLE batch_jobs ADD COLUMN control_version "
                        "INTEGER NOT NULL DEFAULT 1"
                    )
                )
        if "job_secrets" in table_names:
            secret_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info('job_secrets')")).fetchall()
            }
            if "expires_at" not in secret_columns:
                conn.execute(text("ALTER TABLE job_secrets ADD COLUMN expires_at DATETIME"))
        if "candidate_parameter_sets" in table_names:
            candidate_columns = {
                row[1]
                for row in conn.execute(
                    text("PRAGMA table_info('candidate_parameter_sets')")
                ).fetchall()
            }
            if "optimizer_metadata_json" not in candidate_columns:
                conn.execute(
                    text(
                        "ALTER TABLE candidate_parameter_sets "
                        "ADD COLUMN optimizer_metadata_json JSON"
                    )
                )
            first_qualified_candidate_columns = {
                "dispatch_ordinal": "BIGINT",
                "qualification_sequence": "BIGINT",
                "qualified_at": "DATETIME",
            }
            for column_name, column_type in first_qualified_candidate_columns.items():
                if column_name not in candidate_columns:
                    conn.execute(
                        text(
                            "ALTER TABLE candidate_parameter_sets "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_candidate_job_dispatch_ordinal "
                    "ON candidate_parameter_sets(job_id, dispatch_ordinal) "
                    "WHERE dispatch_ordinal IS NOT NULL"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_candidate_job_qualification_sequence "
                    "ON candidate_parameter_sets(job_id, qualification_sequence) "
                    "WHERE qualification_sequence IS NOT NULL"
                )
            )
            if "evidence_ledger_required" not in candidate_columns:
                conn.execute(
                    text(
                        "ALTER TABLE candidate_parameter_sets "
                        "ADD COLUMN evidence_ledger_required BOOLEAN "
                        "NOT NULL DEFAULT 0"
                    )
                )
            if "aggregated_metric_json" in candidate_columns:
                conn.execute(
                    text(
                        "UPDATE candidate_parameter_sets "
                        "SET evidence_ledger_required = 1 "
                        "WHERE evidence_ledger_required = 0 "
                        "AND aggregated_metric_json IS NOT NULL "
                        "AND ("
                        "json_extract(aggregated_metric_json, "
                        "'$.candidate_outcome_evidence.schema_id') = "
                        "'dronedream.candidate-outcome-evidence/v3' "
                        "OR json_extract(aggregated_metric_json, "
                        "'$.candidate_report_evidence.schema_id') = "
                        "'dronedream.candidate-report-evidence/v3'"
                        ")"
                    )
                )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_candidate_evidence_required_no_downgrade
                    BEFORE UPDATE OF evidence_ledger_required
                    ON candidate_parameter_sets
                    WHEN OLD.evidence_ledger_required = 1
                     AND NEW.evidence_ledger_required IS NOT 1
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'Candidate evidence requirement is irreversible'
                        );
                    END
                    """
                )
            )
        if "job_reports" in table_names:
            report_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info('job_reports')")).fetchall()
            }
            if "winner_evidence_json" not in report_columns:
                conn.execute(text("ALTER TABLE job_reports ADD COLUMN winner_evidence_json JSON"))
            if "winner_freeze_receipt_id" not in report_columns:
                conn.execute(
                    text("ALTER TABLE job_reports ADD COLUMN winner_freeze_receipt_id VARCHAR(64)")
                )
        if "winner_freeze_receipts" in table_names:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS
                    winner_freeze_delete_authorizations (
                        receipt_id VARCHAR(64) PRIMARY KEY,
                        reason VARCHAR(64) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(receipt_id)
                            REFERENCES winner_freeze_receipts(id)
                            ON DELETE CASCADE
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_winner_freeze_receipts_no_update
                    BEFORE UPDATE ON winner_freeze_receipts
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'winner freeze receipts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(text("DROP TRIGGER IF EXISTS trg_winner_freeze_receipts_no_delete"))
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_winner_freeze_receipts_no_delete
                    BEFORE DELETE ON winner_freeze_receipts
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM winner_freeze_delete_authorizations
                        WHERE receipt_id = OLD.id
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'winner freeze receipts are append-only'
                        );
                    END
                    """
                )
            )
        if "first_qualified_freeze_receipts" in table_names:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS
                    first_qualified_freeze_delete_authorizations (
                        receipt_id VARCHAR(64) PRIMARY KEY,
                        reason VARCHAR(64) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(receipt_id)
                            REFERENCES first_qualified_freeze_receipts(id)
                            ON DELETE CASCADE
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_first_qualified_freeze_receipts_no_update
                    BEFORE UPDATE ON first_qualified_freeze_receipts
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'first-qualified freeze receipts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    "DROP TRIGGER IF EXISTS "
                    "trg_first_qualified_freeze_receipts_no_delete"
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER
                    trg_first_qualified_freeze_receipts_no_delete
                    BEFORE DELETE ON first_qualified_freeze_receipts
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM first_qualified_freeze_delete_authorizations
                        WHERE receipt_id = OLD.id
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'first-qualified freeze receipts are append-only'
                        );
                    END
                    """
                )
            )
        if "artifacts" in table_names:
            artifact_columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info('artifacts')")).fetchall()
            }
            if "integrity_policy" not in artifact_columns:
                conn.execute(text("ALTER TABLE artifacts ADD COLUMN integrity_policy VARCHAR(32)"))
        if "artifact_digest_receipts" in table_names:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS
                    artifact_digest_delete_authorizations (
                        artifact_id VARCHAR(64) PRIMARY KEY,
                        reason VARCHAR(64) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(artifact_id)
                            REFERENCES artifacts(id)
                            ON DELETE CASCADE
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_artifact_digest_receipts_no_update
                    BEFORE UPDATE ON artifact_digest_receipts
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'artifact digest receipts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_artifact_digest_receipts_no_delete
                    BEFORE DELETE ON artifact_digest_receipts
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM artifact_digest_delete_authorizations
                        WHERE artifact_id = OLD.artifact_id
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'artifact digest receipts are append-only'
                        );
                    END
                    """
                )
            )
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info('trials')")).fetchall()}
        add_sql: list[str] = []
        if "lease_owner" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN lease_owner VARCHAR(64)")
        if "lease_expires_at" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN lease_expires_at DATETIME")
        if "claimed_at" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN claimed_at DATETIME")
        if "accepted_attempt_id" not in columns:
            add_sql.append("ALTER TABLE trials ADD COLUMN accepted_attempt_id VARCHAR(64)")
        for stmt in add_sql:
            conn.execute(text(stmt))
        if "trial_execution_attempts" in table_names:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_trials_accepted_attempt_id "
                    "ON trials(accepted_attempt_id) "
                    "WHERE accepted_attempt_id IS NOT NULL"
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS
                    trial_execution_attempt_delete_authorizations (
                        attempt_id VARCHAR(64) PRIMARY KEY,
                        reason VARCHAR(64) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(attempt_id)
                            REFERENCES trial_execution_attempts(id)
                            ON DELETE CASCADE
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_trial_execution_attempts_no_update
                    BEFORE UPDATE ON trial_execution_attempts
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'trial execution attempts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_trial_execution_attempts_no_delete
                    BEFORE DELETE ON trial_execution_attempts
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM trial_execution_attempt_delete_authorizations
                        WHERE attempt_id = OLD.id
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'trial execution attempts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_trial_execution_attempt_outcomes_no_update
                    BEFORE UPDATE ON trial_execution_attempt_outcomes
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'trial execution attempt outcomes are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_trial_execution_attempt_outcomes_no_delete
                    BEFORE DELETE ON trial_execution_attempt_outcomes
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM trial_execution_attempt_delete_authorizations
                        WHERE attempt_id = OLD.attempt_id
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'trial execution attempt outcomes are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_trials_accepted_attempt_immutable
                    BEFORE UPDATE OF accepted_attempt_id ON trials
                    WHEN (
                        OLD.accepted_attempt_id IS NOT NULL
                        AND NEW.accepted_attempt_id
                            IS NOT OLD.accepted_attempt_id
                        AND NOT EXISTS (
                            SELECT 1
                            FROM trial_execution_attempt_delete_authorizations
                            WHERE attempt_id = OLD.accepted_attempt_id
                        )
                    ) OR (
                        NEW.accepted_attempt_id IS NOT NULL
                        AND NOT EXISTS (
                            SELECT 1
                            FROM trial_execution_attempts
                            WHERE id = NEW.accepted_attempt_id
                              AND trial_id = OLD.id
                        )
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'accepted Trial execution attempt is immutable or mismatched'
                        );
                    END
                    """
                )
            )
        if "candidate_evidence_receipts" in table_names:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS
                    candidate_evidence_delete_authorizations (
                        receipt_id VARCHAR(64) PRIMARY KEY,
                        reason VARCHAR(64) NOT NULL,
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(receipt_id)
                            REFERENCES candidate_evidence_receipts(id)
                            ON DELETE CASCADE
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_candidate_evidence_receipts_no_update
                    BEFORE UPDATE ON candidate_evidence_receipts
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'Candidate evidence receipts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_candidate_evidence_receipts_no_delete
                    BEFORE DELETE ON candidate_evidence_receipts
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM candidate_evidence_delete_authorizations
                        WHERE receipt_id = OLD.id
                    )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'Candidate evidence receipts are append-only'
                        );
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS
                    trg_candidate_provenance_no_mutation
                    BEFORE UPDATE OF source_type, optimizer_metadata_json
                    ON candidate_parameter_sets
                    WHEN OLD.evidence_ledger_required = 1
                     AND (
                            NEW.source_type IS NOT OLD.source_type
                         OR NEW.optimizer_metadata_json
                            IS NOT OLD.optimizer_metadata_json
                     )
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'Candidate provenance is immutable after evidence sealing'
                        );
                    END
                    """
                )
            )


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["Base", "SessionLocal", "engine", "get_db", "init_db"]
