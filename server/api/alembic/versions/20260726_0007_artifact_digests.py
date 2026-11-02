"""Add immutable content-digest receipts for artifacts.

Revision ID: 20260726_0007
Revises: 20260726_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_0007"
down_revision = "20260726_0006"
branch_labels = None
depends_on = None

_POSTGRES_FUNCTION = "dronedream_reject_artifact_digest_mutation"
_POSTGRES_TRIGGER = "trg_artifact_digest_receipts_immutable"
_SQLITE_UPDATE_TRIGGER = "trg_artifact_digest_receipts_no_update"
_SQLITE_DELETE_TRIGGER = "trg_artifact_digest_receipts_no_delete"


def upgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "integrity_policy",
                sa.String(length=32),
                nullable=True,
            )
        )
    op.create_table(
        "artifact_digest_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=71), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "storage_path_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            name="uq_artifact_digest_receipts_artifact_id",
        ),
        sa.UniqueConstraint(
            "evidence_id",
            name="uq_artifact_digest_receipts_evidence_id",
        ),
    )
    op.create_table(
        "artifact_digest_delete_authorizations",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {_SQLITE_UPDATE_TRIGGER}
            BEFORE UPDATE ON artifact_digest_receipts
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'artifact digest receipts are append-only'
                );
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {_SQLITE_DELETE_TRIGGER}
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
        return
    if dialect == "postgresql":
        op.execute(
            f"""
            CREATE FUNCTION {_POSTGRES_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' AND EXISTS (
                    SELECT 1
                    FROM artifact_digest_delete_authorizations
                    WHERE artifact_id = OLD.artifact_id
                ) THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION
                    'artifact digest receipts are append-only';
            END;
            $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_POSTGRES_TRIGGER}
            BEFORE UPDATE OR DELETE ON artifact_digest_receipts
            FOR EACH ROW
            EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
            """
        )
        return
    raise RuntimeError(
        "artifact-digest migration supports SQLite/PostgreSQL only"
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
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} "
            "ON artifact_digest_receipts"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError(
            "artifact-digest migration supports SQLite/PostgreSQL only"
        )
    op.drop_table("artifact_digest_delete_authorizations")
    op.drop_table("artifact_digest_receipts")
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.drop_column("integrity_policy")
