"""make first-qualified freeze receipts append-only

Revision ID: 20260804_0020
Revises: 20260803_0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0020"
down_revision: str | None = "20260803_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_UPDATE_TRIGGER = "trg_first_qualified_freeze_receipts_no_update"
_SQLITE_DELETE_TRIGGER = "trg_first_qualified_freeze_receipts_no_delete"
_POSTGRES_FUNCTION = "dronedream_reject_first_qualified_freeze_mutation"
_POSTGRES_TRIGGER = "trg_first_qualified_freeze_receipts_immutable"


def upgrade() -> None:
    op.create_table(
        "first_qualified_freeze_delete_authorizations",
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["first_qualified_freeze_receipts.id"],
            ondelete="CASCADE",
            name=(
                "fk_first_qualified_freeze_delete_auth_receipt_id_"
                "first_qualified_freeze_receipts"
            ),
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
            "First-qualified freeze migration supports SQLite/PostgreSQL only"
        )


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER {_SQLITE_UPDATE_TRIGGER}
        BEFORE UPDATE ON first_qualified_freeze_receipts
        BEGIN
            SELECT RAISE(
                ABORT,
                'first-qualified freeze receipts are append-only'
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_SQLITE_DELETE_TRIGGER}
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


def _install_postgres_guards() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_POSTGRES_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1
                FROM first_qualified_freeze_delete_authorizations
                WHERE receipt_id = OLD.id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'first-qualified freeze receipts are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_POSTGRES_TRIGGER}
        BEFORE UPDATE OR DELETE ON first_qualified_freeze_receipts
        FOR EACH ROW
        EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_DELETE_TRIGGER}")
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_UPDATE_TRIGGER}")
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} "
            "ON first_qualified_freeze_receipts"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError(
            "First-qualified freeze migration supports SQLite/PostgreSQL only"
        )
    op.drop_table("first_qualified_freeze_delete_authorizations")
