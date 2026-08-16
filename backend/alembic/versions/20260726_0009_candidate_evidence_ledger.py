"""Add the append-only Candidate outcome/report evidence ledger.

Revision ID: 20260726_0009
Revises: 20260726_0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_0009"
down_revision = "20260726_0008"
branch_labels = None
depends_on = None

_UPDATE_TRIGGER = "trg_candidate_evidence_receipts_no_update"
_DELETE_TRIGGER = "trg_candidate_evidence_receipts_no_delete"
_POSTGRES_FUNCTION = "dronedream_reject_candidate_evidence_mutation"
_WINNER_SQLITE_DELETE_TRIGGER = "trg_winner_freeze_receipts_no_delete"
_WINNER_POSTGRES_TRIGGER = "trg_winner_freeze_receipts_immutable"
_WINNER_POSTGRES_FUNCTION = "dronedream_reject_winner_freeze_mutation"
_REQUIRED_SQLITE_TRIGGER = "trg_candidate_evidence_required_no_downgrade"
_REQUIRED_POSTGRES_TRIGGER = "trg_candidate_evidence_required_no_downgrade"
_REQUIRED_POSTGRES_FUNCTION = "dronedream_reject_candidate_evidence_downgrade"


def upgrade() -> None:
    op.add_column(
        "candidate_parameter_sets",
        sa.Column(
            "evidence_ledger_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "candidate_evidence_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "previous_evidence_id",
            sa.String(length=71),
            nullable=True,
        ),
        sa.Column("receipt_schema", sa.String(length=128), nullable=False),
        sa.Column("evidence_id", sa.String(length=71), nullable=False),
        sa.Column("aggregate_sha256", sa.String(length=71), nullable=False),
        sa.Column("outcome_evidence_id", sa.String(length=71), nullable=False),
        sa.Column("report_evidence_id", sa.String(length=71), nullable=False),
        sa.Column("outcome_evidence_json", sa.JSON(), nullable=False),
        sa.Column("report_evidence_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_parameter_sets.id"],
            ondelete="CASCADE",
            name=(
                "fk_candidate_evidence_receipts_candidate_id_"
                "candidate_parameter_sets"
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "revision",
            name="uq_candidate_evidence_receipts_candidate_revision",
        ),
    )
    op.create_index(
        "ix_candidate_evidence_receipts_candidate_id",
        "candidate_evidence_receipts",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_evidence_receipts_job_id",
        "candidate_evidence_receipts",
        ["job_id"],
    )
    op.create_index(
        "ix_candidate_evidence_receipts_evidence_id",
        "candidate_evidence_receipts",
        ["evidence_id"],
        unique=True,
    )
    op.create_table(
        "candidate_evidence_delete_authorizations",
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["candidate_evidence_receipts.id"],
            ondelete="CASCADE",
            name=(
                "fk_candidate_evidence_delete_auth_receipt_id_"
                "candidate_evidence_receipts"
            ),
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
    )
    op.create_table(
        "winner_freeze_delete_authorizations",
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["winner_freeze_receipts.id"],
            ondelete="CASCADE",
            name=(
                "fk_winner_freeze_delete_auth_receipt_id_"
                "winner_freeze_receipts"
            ),
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            """
            UPDATE candidate_parameter_sets
            SET evidence_ledger_required = 1
            WHERE evidence_ledger_required = 0
              AND aggregated_metric_json IS NOT NULL
              AND (
                  json_extract(
                      aggregated_metric_json,
                      '$.candidate_outcome_evidence.schema_id'
                  ) = 'dronedream.candidate-outcome-evidence/v3'
                  OR json_extract(
                      aggregated_metric_json,
                      '$.candidate_report_evidence.schema_id'
                  ) = 'dronedream.candidate-report-evidence/v3'
              )
            """
        )
        _install_sqlite_guards()
    elif dialect == "postgresql":
        op.execute(
            """
            UPDATE candidate_parameter_sets
            SET evidence_ledger_required = TRUE
            WHERE evidence_ledger_required = FALSE
              AND aggregated_metric_json IS NOT NULL
              AND (
                  aggregated_metric_json
                      -> 'candidate_outcome_evidence'
                      ->> 'schema_id'
                      = 'dronedream.candidate-outcome-evidence/v3'
                  OR aggregated_metric_json
                      -> 'candidate_report_evidence'
                      ->> 'schema_id'
                      = 'dronedream.candidate-report-evidence/v3'
              )
            """
        )
        _install_postgres_guards()
    else:
        raise RuntimeError(
            "Candidate evidence migration supports SQLite/PostgreSQL only"
        )


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_REQUIRED_SQLITE_TRIGGER}
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
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_UPDATE_TRIGGER}
        BEFORE UPDATE ON candidate_evidence_receipts
        BEGIN
            SELECT RAISE(
                ABORT,
                'Candidate evidence receipts are append-only'
            );
        END
        """
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_WINNER_SQLITE_DELETE_TRIGGER}")
    op.execute(
        f"""
        CREATE TRIGGER {_WINNER_SQLITE_DELETE_TRIGGER}
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
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_DELETE_TRIGGER}
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


def _install_postgres_guards() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_REQUIRED_POSTGRES_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.evidence_ledger_required
               AND NOT NEW.evidence_ledger_required THEN
                RAISE EXCEPTION
                    'Candidate evidence requirement is irreversible';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_REQUIRED_POSTGRES_TRIGGER}
        BEFORE UPDATE OF evidence_ledger_required
        ON candidate_parameter_sets
        FOR EACH ROW
        EXECUTE FUNCTION {_REQUIRED_POSTGRES_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_POSTGRES_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1
                FROM candidate_evidence_delete_authorizations
                WHERE receipt_id = OLD.id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'Candidate evidence receipts are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS {_WINNER_POSTGRES_TRIGGER} "
        "ON winner_freeze_receipts"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {_WINNER_POSTGRES_FUNCTION}()")
    op.execute(
        f"""
        CREATE FUNCTION {_WINNER_POSTGRES_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1
                FROM winner_freeze_delete_authorizations
                WHERE receipt_id = OLD.id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'winner freeze receipts are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_WINNER_POSTGRES_TRIGGER}
        BEFORE UPDATE OR DELETE ON winner_freeze_receipts
        FOR EACH ROW
        EXECUTE FUNCTION {_WINNER_POSTGRES_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_UPDATE_TRIGGER}
        BEFORE UPDATE OR DELETE ON candidate_evidence_receipts
        FOR EACH ROW
        EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_REQUIRED_SQLITE_TRIGGER}")
        op.execute(f"DROP TRIGGER IF EXISTS {_DELETE_TRIGGER}")
        op.execute(f"DROP TRIGGER IF EXISTS {_UPDATE_TRIGGER}")
        op.execute(
            f"DROP TRIGGER IF EXISTS {_WINNER_SQLITE_DELETE_TRIGGER}"
        )
        op.execute(
            f"""
            CREATE TRIGGER {_WINNER_SQLITE_DELETE_TRIGGER}
            BEFORE DELETE ON winner_freeze_receipts
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'winner freeze receipts are append-only'
                );
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_REQUIRED_POSTGRES_TRIGGER} "
            "ON candidate_parameter_sets"
        )
        op.execute(
            f"DROP FUNCTION IF EXISTS {_REQUIRED_POSTGRES_FUNCTION}()"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_UPDATE_TRIGGER} "
            "ON candidate_evidence_receipts"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
        op.execute(
            f"DROP TRIGGER IF EXISTS {_WINNER_POSTGRES_TRIGGER} "
            "ON winner_freeze_receipts"
        )
        op.execute(
            f"DROP FUNCTION IF EXISTS {_WINNER_POSTGRES_FUNCTION}()"
        )
        op.execute(
            f"""
            CREATE FUNCTION {_WINNER_POSTGRES_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'winner freeze receipts are append-only';
            END;
            $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_WINNER_POSTGRES_TRIGGER}
            BEFORE UPDATE OR DELETE ON winner_freeze_receipts
            FOR EACH ROW
            EXECUTE FUNCTION {_WINNER_POSTGRES_FUNCTION}()
            """
        )
    else:
        raise RuntimeError(
            "Candidate evidence migration supports SQLite/PostgreSQL only"
        )
    op.drop_table("winner_freeze_delete_authorizations")
    op.drop_table("candidate_evidence_delete_authorizations")
    op.drop_table("candidate_evidence_receipts")
    op.drop_column("candidate_parameter_sets", "evidence_ledger_required")
