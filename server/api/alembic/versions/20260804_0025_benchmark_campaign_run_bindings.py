"""add immutable campaign Batch and run provenance bindings

Revision ID: 20260804_0025
Revises: 20260804_0024
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0025"
down_revision: str | None = "20260804_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH_TABLE = "benchmark_campaign_batch_bindings"
_RUN_TABLE = "benchmark_campaign_run_bindings"
_POSTGRES_FUNCTION = "dronedream_reject_benchmark_binding_mutation"


def _create_immutable_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table, prefix in ((_BATCH_TABLE, "batch"), (_RUN_TABLE, "run")):
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"""
                    CREATE TRIGGER trg_benchmark_{prefix}_binding_no_{operation.lower()}
                    BEFORE {operation} ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, 'benchmark execution bindings are append-only');
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
                RAISE EXCEPTION 'benchmark execution bindings are append-only';
            END;
            $$
            """
        )
        for table, prefix in ((_BATCH_TABLE, "batch"), (_RUN_TABLE, "run")):
            op.execute(
                f"""
                CREATE TRIGGER trg_benchmark_{prefix}_binding_immutable
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
                """
            )
    else:
        raise RuntimeError("Benchmark binding migration supports SQLite/PostgreSQL only")


def upgrade() -> None:
    op.create_table(
        _BATCH_TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("binding_key", sa.String(length=96), nullable=False),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("batch_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("budget_reservation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "batch_ordinal >= 1 AND lease_generation >= 1 "
            "AND job_count >= 1 AND job_count <= 50",
            name="ck_benchmark_batch_binding_ordinals",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["benchmark_campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["batch_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["budget_reservation_id"],
            ["benchmark_budget_reservations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", name="uq_benchmark_batch_binding_batch"),
        sa.UniqueConstraint(
            "budget_reservation_id",
            name="uq_benchmark_batch_binding_reservation",
        ),
        sa.UniqueConstraint(
            "campaign_id", "binding_key", name="uq_benchmark_batch_binding_key"
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "batch_ordinal",
            name="uq_benchmark_batch_binding_ordinal",
        ),
    )
    op.create_index(
        "ix_benchmark_batch_bindings_campaign_id", _BATCH_TABLE, ["campaign_id"]
    )
    op.create_index("ix_benchmark_batch_bindings_batch_id", _BATCH_TABLE, ["batch_id"])
    op.create_index(
        "ix_benchmark_batch_bindings_sha256", _BATCH_TABLE, ["binding_sha256"]
    )

    op.create_table(
        _RUN_TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("batch_binding_id", sa.String(length=64), nullable=False),
        sa.Column("benchmark_arm_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("run_key", sa.String(length=96), nullable=False),
        sa.Column("run_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("batch_run_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("algorithm_seed", sa.BigInteger(), nullable=False),
        sa.Column("simulator_seed_block", sa.String(length=128), nullable=False),
        sa.Column("provider_randomness_policy", sa.String(length=32), nullable=False),
        sa.Column("provider_seed", sa.BigInteger(), nullable=True),
        sa.Column("binding_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "run_ordinal >= 1 AND batch_run_ordinal >= 1 "
            "AND algorithm_seed >= 0 AND (provider_seed IS NULL OR provider_seed >= 0)",
            name="ck_benchmark_run_binding_ordinals",
        ),
        sa.CheckConstraint(
            "provider_randomness_policy IN "
            "('not_applicable', 'fixed_seed', 'provider_managed')",
            name="ck_benchmark_run_provider_policy",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["benchmark_campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["batch_binding_id"], [_BATCH_TABLE + ".id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["benchmark_arm_id"], ["benchmark_arms.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_benchmark_run_binding_job"),
        sa.UniqueConstraint(
            "campaign_id", "run_key", name="uq_benchmark_run_binding_key"
        ),
        sa.UniqueConstraint(
            "campaign_id", "run_ordinal", name="uq_benchmark_run_binding_ordinal"
        ),
        sa.UniqueConstraint(
            "batch_binding_id",
            "batch_run_ordinal",
            name="uq_benchmark_batch_run_ordinal",
        ),
    )
    op.create_index("ix_benchmark_run_bindings_campaign_id", _RUN_TABLE, ["campaign_id"])
    op.create_index(
        "ix_benchmark_run_bindings_batch_binding_id", _RUN_TABLE, ["batch_binding_id"]
    )
    op.create_index(
        "ix_benchmark_run_bindings_arm_id", _RUN_TABLE, ["benchmark_arm_id"]
    )
    op.create_index("ix_benchmark_run_bindings_job_id", _RUN_TABLE, ["job_id"])
    op.create_index(
        "ix_benchmark_run_bindings_sha256", _RUN_TABLE, ["binding_sha256"]
    )
    _create_immutable_triggers()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for prefix in ("run", "batch"):
            for operation in ("delete", "update"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS trg_benchmark_{prefix}_binding_no_{operation}"
                )
    elif dialect == "postgresql":
        for table, prefix in ((_RUN_TABLE, "run"), (_BATCH_TABLE, "batch")):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_benchmark_{prefix}_binding_immutable ON {table}"
            )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError("Benchmark binding migration supports SQLite/PostgreSQL only")

    for name in (
        "ix_benchmark_run_bindings_sha256",
        "ix_benchmark_run_bindings_job_id",
        "ix_benchmark_run_bindings_arm_id",
        "ix_benchmark_run_bindings_batch_binding_id",
        "ix_benchmark_run_bindings_campaign_id",
    ):
        op.drop_index(name, table_name=_RUN_TABLE)
    op.drop_table(_RUN_TABLE)
    for name in (
        "ix_benchmark_batch_bindings_sha256",
        "ix_benchmark_batch_bindings_batch_id",
        "ix_benchmark_batch_bindings_campaign_id",
    ):
        op.drop_index(name, table_name=_BATCH_TABLE)
    op.drop_table(_BATCH_TABLE)
