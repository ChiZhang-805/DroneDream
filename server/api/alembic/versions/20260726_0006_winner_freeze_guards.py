"""Reject winner-freeze receipt mutation at the database boundary.

Revision ID: 20260726_0006
Revises: 20260726_0005
"""

from __future__ import annotations

from alembic import op

revision = "20260726_0006"
down_revision = "20260726_0005"
branch_labels = None
depends_on = None

_POSTGRES_FUNCTION = "dronedream_reject_winner_freeze_mutation"
_POSTGRES_TRIGGER = "trg_winner_freeze_receipts_immutable"
_SQLITE_UPDATE_TRIGGER = "trg_winner_freeze_receipts_no_update"
_SQLITE_DELETE_TRIGGER = "trg_winner_freeze_receipts_no_delete"


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {_SQLITE_UPDATE_TRIGGER}
            BEFORE UPDATE ON winner_freeze_receipts
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
            CREATE TRIGGER IF NOT EXISTS {_SQLITE_DELETE_TRIGGER}
            BEFORE DELETE ON winner_freeze_receipts
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'winner freeze receipts are append-only'
                );
            END
            """
        )
        return
    if dialect == "postgresql":
        op.execute(
            f"""
            CREATE FUNCTION {_POSTGRES_FUNCTION}()
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
            CREATE TRIGGER {_POSTGRES_TRIGGER}
            BEFORE UPDATE OR DELETE ON winner_freeze_receipts
            FOR EACH ROW
            EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
            """
        )
        return
    raise RuntimeError(
        "winner-freeze immutability migration supports SQLite/PostgreSQL only"
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_SQLITE_UPDATE_TRIGGER}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_SQLITE_DELETE_TRIGGER}"
        )
        return
    if dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} "
            "ON winner_freeze_receipts"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
        return
    raise RuntimeError(
        "winner-freeze immutability migration supports SQLite/PostgreSQL only"
    )
