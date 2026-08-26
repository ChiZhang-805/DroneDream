"""persist recoverable direct-arm proposals without provider replay

Revision ID: 20260805_0031
Revises: 20260804_0030
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0031"
down_revision: str | None = "20260804_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "benchmark_direct_proposal_handoffs"
_UPDATE_TRIGGER = "trg_benchmark_direct_handoff_no_update"
_DELETE_TRIGGER = "trg_benchmark_direct_handoff_no_delete"
_POSTGRES_FUNCTION = "dronedream_reject_benchmark_direct_handoff_mutation"
_POSTGRES_TRIGGER = "trg_benchmark_direct_handoff_immutable"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("run_binding_id", sa.String(length=64), nullable=False),
        sa.Column("cognitive_turn_receipt_id", sa.String(length=64), nullable=False),
        sa.Column("handoff_schema", sa.String(length=128), nullable=False),
        sa.Column("generation_index", sa.Integer(), nullable=False),
        sa.Column("dispatch_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("source_commit", sa.String(length=40), nullable=False),
        sa.Column("observation_sha256", sa.String(length=64), nullable=False),
        sa.Column("turn_binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_ref", sa.String(length=255), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("parameter_sha256", sa.String(length=64), nullable=False),
        sa.Column("proposal_receipt_json", sa.JSON(), nullable=False),
        sa.Column("proposal_receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generation_index >= 1 AND dispatch_ordinal >= 1",
            name="ck_benchmark_direct_handoff_ordinals",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["run_binding_id"],
            ["benchmark_campaign_run_bindings.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cognitive_turn_receipt_id"],
            ["harness_cognitive_turn_receipts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "generation_index",
            name="uq_benchmark_direct_handoff_job_generation",
        ),
        sa.UniqueConstraint(
            "cognitive_turn_receipt_id",
            name="uq_benchmark_direct_handoff_turn",
        ),
    )
    op.create_index("ix_benchmark_direct_proposal_handoffs_job_id", _TABLE, ["job_id"])
    op.create_index(
        "ix_benchmark_direct_proposal_handoffs_run_binding_id",
        _TABLE,
        ["run_binding_id"],
    )
    op.create_index(
        "ix_benchmark_direct_proposal_handoffs_cognitive_turn_receipt_id",
        _TABLE,
        ["cognitive_turn_receipt_id"],
        unique=True,
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite_guards()
    elif dialect == "postgresql":
        _install_postgres_guards()
    else:
        raise RuntimeError("Benchmark direct handoff migration supports SQLite/PostgreSQL only")


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER {_UPDATE_TRIGGER}
        BEFORE UPDATE ON {_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'benchmark direct proposal handoffs are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_DELETE_TRIGGER}
        BEFORE DELETE ON {_TABLE}
        WHEN NOT EXISTS (
            SELECT 1 FROM harness_cognitive_turn_delete_authorizations
            WHERE receipt_id = OLD.cognitive_turn_receipt_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'benchmark direct proposal handoffs are append-only');
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
                SELECT 1 FROM harness_cognitive_turn_delete_authorizations
                WHERE receipt_id = OLD.cognitive_turn_receipt_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'benchmark direct proposal handoffs are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_POSTGRES_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_DELETE_TRIGGER}")
        op.execute(f"DROP TRIGGER IF EXISTS {_UPDATE_TRIGGER}")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} ON {_TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError("Benchmark direct handoff migration supports SQLite/PostgreSQL only")
    op.drop_index(
        "ix_benchmark_direct_proposal_handoffs_cognitive_turn_receipt_id",
        table_name=_TABLE,
    )
    op.drop_index("ix_benchmark_direct_proposal_handoffs_run_binding_id", table_name=_TABLE)
    op.drop_index("ix_benchmark_direct_proposal_handoffs_job_id", table_name=_TABLE)
    op.drop_table(_TABLE)
