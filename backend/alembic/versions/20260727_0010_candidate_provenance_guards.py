"""Freeze Candidate source identity after the evidence ledger starts.

Revision ID: 20260727_0010
Revises: 20260726_0009
"""

from __future__ import annotations

from alembic import op

revision = "20260727_0010"
down_revision = "20260726_0009"
branch_labels = None
depends_on = None

_SQLITE_TRIGGER = "trg_candidate_provenance_no_mutation"
_POSTGRES_TRIGGER = "trg_candidate_provenance_no_mutation"
_POSTGRES_FUNCTION = "dronedream_reject_candidate_provenance_mutation"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {_SQLITE_TRIGGER}
            BEFORE UPDATE OF source_type, optimizer_metadata_json
            ON candidate_parameter_sets
            WHEN OLD.evidence_ledger_required = 1
             AND (
                    NEW.source_type IS NOT OLD.source_type
                 OR NEW.optimizer_metadata_json IS NOT OLD.optimizer_metadata_json
             )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Candidate provenance is immutable after evidence sealing'
                );
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            f"""
            CREATE FUNCTION {_POSTGRES_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF OLD.evidence_ledger_required
                   AND (
                        NEW.source_type IS DISTINCT FROM OLD.source_type
                        OR NEW.optimizer_metadata_json
                           IS DISTINCT FROM OLD.optimizer_metadata_json
                   ) THEN
                    RAISE EXCEPTION
                        'Candidate provenance is immutable after evidence sealing';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_POSTGRES_TRIGGER}
            BEFORE UPDATE OF source_type, optimizer_metadata_json
            ON candidate_parameter_sets
            FOR EACH ROW
            EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
            """
        )
    else:
        raise RuntimeError("Candidate provenance guards support SQLite/PostgreSQL only")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_TRIGGER}")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} ON candidate_parameter_sets")
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError("Candidate provenance guards support SQLite/PostgreSQL only")
