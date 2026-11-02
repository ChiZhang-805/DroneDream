"""make cognitive turn attempts and outcomes append-only

Revision ID: 20260804_0021
Revises: 20260804_0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0021"
down_revision: str | None = "20260804_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTH_TABLE = "harness_cognitive_turn_delete_authorizations"
_RECEIPT_UPDATE_TRIGGER = "trg_harness_cognitive_turn_receipts_no_update"
_RECEIPT_DELETE_TRIGGER = "trg_harness_cognitive_turn_receipts_no_delete"
_OUTCOME_UPDATE_TRIGGER = "trg_harness_cognitive_turn_outcomes_no_update"
_OUTCOME_DELETE_TRIGGER = "trg_harness_cognitive_turn_outcomes_no_delete"
_POSTGRES_FUNCTION = "dronedream_reject_cognitive_turn_mutation"
_POSTGRES_RECEIPT_TRIGGER = "trg_harness_cognitive_turn_receipts_immutable"
_POSTGRES_OUTCOME_TRIGGER = "trg_harness_cognitive_turn_outcomes_immutable"


def upgrade() -> None:
    op.create_table(
        _AUTH_TABLE,
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["harness_cognitive_turn_receipts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite_guards()
    elif dialect == "postgresql":
        _install_postgres_guards()
    else:
        raise RuntimeError(
            "Cognitive turn guard migration supports SQLite/PostgreSQL only"
        )


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER {_RECEIPT_UPDATE_TRIGGER}
        BEFORE UPDATE ON harness_cognitive_turn_receipts
        BEGIN
            SELECT RAISE(ABORT, 'cognitive turn receipts are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_RECEIPT_DELETE_TRIGGER}
        BEFORE DELETE ON harness_cognitive_turn_receipts
        WHEN NOT EXISTS (
            SELECT 1 FROM {_AUTH_TABLE} WHERE receipt_id = OLD.id
        )
        BEGIN
            SELECT RAISE(ABORT, 'cognitive turn receipts are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_OUTCOME_UPDATE_TRIGGER}
        BEFORE UPDATE ON harness_cognitive_turn_outcomes
        BEGIN
            SELECT RAISE(ABORT, 'cognitive turn outcomes are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_OUTCOME_DELETE_TRIGGER}
        BEFORE DELETE ON harness_cognitive_turn_outcomes
        WHEN NOT EXISTS (
            SELECT 1 FROM {_AUTH_TABLE} WHERE receipt_id = OLD.turn_receipt_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'cognitive turn outcomes are append-only');
        END
        """
    )


def _install_postgres_guards() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_POSTGRES_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            protected_receipt_id VARCHAR(64);
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF TG_TABLE_NAME = 'harness_cognitive_turn_receipts' THEN
                    protected_receipt_id := OLD.id;
                ELSE
                    protected_receipt_id := OLD.turn_receipt_id;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM {_AUTH_TABLE}
                    WHERE receipt_id = protected_receipt_id
                ) THEN
                    RETURN OLD;
                END IF;
            END IF;
            RAISE EXCEPTION 'cognitive turn records are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_POSTGRES_RECEIPT_TRIGGER}
        BEFORE UPDATE OR DELETE ON harness_cognitive_turn_receipts
        FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_POSTGRES_OUTCOME_TRIGGER}
        BEFORE UPDATE OR DELETE ON harness_cognitive_turn_outcomes
        FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for trigger in (
            _OUTCOME_DELETE_TRIGGER,
            _OUTCOME_UPDATE_TRIGGER,
            _RECEIPT_DELETE_TRIGGER,
            _RECEIPT_UPDATE_TRIGGER,
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_OUTCOME_TRIGGER} "
            "ON harness_cognitive_turn_outcomes"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_RECEIPT_TRIGGER} "
            "ON harness_cognitive_turn_receipts"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError(
            "Cognitive turn guard migration supports SQLite/PostgreSQL only"
        )
    op.drop_table(_AUTH_TABLE)
