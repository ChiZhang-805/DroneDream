"""add fenced cross-Batch benchmark campaign coordinator accounting

Revision ID: 20260804_0024
Revises: 20260804_0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0024"
down_revision: str | None = "20260804_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_RESERVATION_UPDATE = "trg_benchmark_budget_reservation_no_update"
_SQLITE_RESERVATION_DELETE = "trg_benchmark_budget_reservation_no_delete"
_POSTGRES_FUNCTION = "dronedream_reject_benchmark_reservation_mutation"
_POSTGRES_TRIGGER = "trg_benchmark_budget_reservation_immutable"


def upgrade() -> None:
    op.create_table(
        "benchmark_campaign_coordinator_states",
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_batch_ordinal", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("next_run_ordinal", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("jobs_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("trials_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("logical_turns_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("network_requests_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("input_utf8_bytes_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_utf8_bytes_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("provider_tokens_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "provider_cost_microusd_used", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("wall_time_seconds_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("disk_bytes_used", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lease_generation >= 0 AND next_batch_ordinal >= 1 AND next_run_ordinal >= 1",
            name="ck_benchmark_coordinator_sequence",
        ),
        sa.CheckConstraint(
            "jobs_used >= 0 AND trials_used >= 0 AND logical_turns_used >= 0 "
            "AND network_requests_used >= 0 AND input_utf8_bytes_used >= 0 "
            "AND output_utf8_bytes_used >= 0 AND provider_tokens_used >= 0 "
            "AND provider_cost_microusd_used >= 0 AND wall_time_seconds_used >= 0 "
            "AND disk_bytes_used >= 0",
            name="ck_benchmark_coordinator_usage_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["benchmark_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("campaign_id"),
        sa.UniqueConstraint(
            "lease_token_hash",
            name="uq_benchmark_coordinator_lease_token_hash",
        ),
    )
    op.create_index(
        "ix_benchmark_coordinator_lease_expires_at",
        "benchmark_campaign_coordinator_states",
        ["lease_expires_at"],
    )
    op.execute(
        """
        INSERT INTO benchmark_campaign_coordinator_states (
            campaign_id,
            lease_generation,
            next_batch_ordinal,
            next_run_ordinal,
            jobs_used,
            trials_used,
            logical_turns_used,
            network_requests_used,
            input_utf8_bytes_used,
            output_utf8_bytes_used,
            provider_tokens_used,
            provider_cost_microusd_used,
            wall_time_seconds_used,
            disk_bytes_used,
            created_at,
            updated_at
        )
        SELECT
            id, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM benchmark_campaigns
        """
    )

    op.create_table(
        "benchmark_budget_reservations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("reservation_key", sa.String(length=128), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=False),
        sa.Column("reservation_sha256", sa.String(length=64), nullable=False),
        sa.Column("jobs", sa.BigInteger(), nullable=False),
        sa.Column("trials", sa.BigInteger(), nullable=False),
        sa.Column("logical_turns", sa.BigInteger(), nullable=False),
        sa.Column("network_requests", sa.BigInteger(), nullable=False),
        sa.Column("input_utf8_bytes", sa.BigInteger(), nullable=False),
        sa.Column("output_utf8_bytes", sa.BigInteger(), nullable=False),
        sa.Column("provider_tokens", sa.BigInteger(), nullable=False),
        sa.Column("provider_cost_microusd", sa.BigInteger(), nullable=False),
        sa.Column("wall_time_seconds", sa.BigInteger(), nullable=False),
        sa.Column("disk_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lease_generation >= 1 AND jobs >= 0 AND trials >= 0 "
            "AND logical_turns >= 0 AND network_requests >= 0 "
            "AND input_utf8_bytes >= 0 AND output_utf8_bytes >= 0 "
            "AND provider_tokens >= 0 AND provider_cost_microusd >= 0 "
            "AND wall_time_seconds >= 0 AND disk_bytes >= 0",
            name="ck_benchmark_budget_reservation_nonnegative",
        ),
        sa.CheckConstraint(
            "jobs + trials + logical_turns + network_requests + input_utf8_bytes + "
            "output_utf8_bytes + provider_tokens + provider_cost_microusd + "
            "wall_time_seconds + disk_bytes > 0",
            name="ck_benchmark_budget_reservation_nonzero",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["benchmark_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "reservation_key",
            name="uq_benchmark_budget_reservation_key",
        ),
    )
    op.create_index(
        "ix_benchmark_budget_reservations_campaign_id",
        "benchmark_budget_reservations",
        ["campaign_id"],
    )
    op.create_index(
        "ix_benchmark_budget_reservations_reservation_sha256",
        "benchmark_budget_reservations",
        ["reservation_sha256"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER {_SQLITE_RESERVATION_UPDATE}
            BEFORE UPDATE ON benchmark_budget_reservations
            BEGIN
                SELECT RAISE(ABORT, 'benchmark budget reservations are append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_SQLITE_RESERVATION_DELETE}
            BEFORE DELETE ON benchmark_budget_reservations
            BEGIN
                SELECT RAISE(ABORT, 'benchmark budget reservations are append-only');
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
                RAISE EXCEPTION 'benchmark budget reservations are append-only';
            END;
            $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_POSTGRES_TRIGGER}
            BEFORE UPDATE OR DELETE ON benchmark_budget_reservations
            FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
            """
        )
    else:
        raise RuntimeError("Benchmark coordinator migration supports SQLite/PostgreSQL only")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_RESERVATION_DELETE}")
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_RESERVATION_UPDATE}")
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} ON benchmark_budget_reservations"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError("Benchmark coordinator migration supports SQLite/PostgreSQL only")
    op.drop_index(
        "ix_benchmark_budget_reservations_reservation_sha256",
        table_name="benchmark_budget_reservations",
    )
    op.drop_index(
        "ix_benchmark_budget_reservations_campaign_id",
        table_name="benchmark_budget_reservations",
    )
    op.drop_table("benchmark_budget_reservations")
    op.drop_index(
        "ix_benchmark_coordinator_lease_expires_at",
        table_name="benchmark_campaign_coordinator_states",
    )
    op.drop_table("benchmark_campaign_coordinator_states")
