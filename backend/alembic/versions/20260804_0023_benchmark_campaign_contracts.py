"""add immutable benchmark campaign and arm preregistration contracts

Revision ID: 20260804_0023
Revises: 20260804_0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0023"
down_revision: str | None = "20260804_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAMPAIGN_TRIGGER_SQLITE = "trg_benchmark_campaign_manifest_immutable"
_ARM_TRIGGER_SQLITE = "trg_benchmark_arm_manifest_immutable"
_POSTGRES_FUNCTION = "dronedream_reject_benchmark_manifest_update"
_CAMPAIGN_TRIGGER_POSTGRES = "trg_benchmark_campaign_manifest_immutable"
_ARM_TRIGGER_POSTGRES = "trg_benchmark_arm_manifest_immutable"


def upgrade() -> None:
    op.create_table(
        "benchmark_campaigns",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("campaign_key", sa.String(length=128), nullable=False),
        sa.Column("campaign_version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("panel", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="PREREGISTERED",
            nullable=False,
        ),
        sa.Column("control_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("protocol_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("composite_inventory_sha256", sa.String(length=64), nullable=False),
        sa.Column("composite_inventory_json", sa.JSON(), nullable=False),
        sa.Column("job_cap", sa.Integer(), nullable=False),
        sa.Column("trial_cap", sa.BigInteger(), nullable=False),
        sa.Column("logical_turn_cap", sa.BigInteger(), nullable=False),
        sa.Column("network_request_cap", sa.BigInteger(), nullable=False),
        sa.Column("input_utf8_byte_cap", sa.BigInteger(), nullable=False),
        sa.Column("output_utf8_byte_cap", sa.BigInteger(), nullable=False),
        sa.Column("provider_token_cap", sa.BigInteger(), nullable=False),
        sa.Column("provider_cost_microusd_cap", sa.BigInteger(), nullable=False),
        sa.Column("wall_time_second_cap", sa.BigInteger(), nullable=False),
        sa.Column("disk_byte_cap", sa.BigInteger(), nullable=False),
        sa.Column("preregistered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PREREGISTERED', 'ACTIVE', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_benchmark_campaign_status",
        ),
        sa.CheckConstraint(
            "job_cap >= 1 AND trial_cap >= 1 AND logical_turn_cap >= 0 "
            "AND network_request_cap >= 0 AND input_utf8_byte_cap >= 0 "
            "AND output_utf8_byte_cap >= 0 AND provider_token_cap >= 0 "
            "AND provider_cost_microusd_cap >= 0 AND wall_time_second_cap >= 1 "
            "AND disk_byte_cap >= 1",
            name="ck_benchmark_campaign_caps",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "campaign_key",
            "campaign_version",
            name="uq_benchmark_campaign_owner_key_version",
        ),
    )
    op.create_index(
        "ix_benchmark_campaigns_user_id",
        "benchmark_campaigns",
        ["user_id"],
    )
    op.create_index(
        "ix_benchmark_campaigns_status",
        "benchmark_campaigns",
        ["status"],
    )
    op.create_index(
        "ix_benchmark_campaigns_manifest_sha256",
        "benchmark_campaigns",
        ["manifest_sha256"],
    )
    op.create_index(
        "ix_benchmark_campaigns_composite_inventory_sha256",
        "benchmark_campaigns",
        ["composite_inventory_sha256"],
    )

    op.create_table(
        "benchmark_arms",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("benchmark_arm_id", sa.String(length=128), nullable=False),
        sa.Column("arm_version", sa.String(length=64), nullable=False),
        sa.Column("arm_family", sa.String(length=32), nullable=False),
        sa.Column("proposal_adapter_id", sa.String(length=128), nullable=False),
        sa.Column("evaluator_contract_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("execution_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "arm_family IN ('traditional', 'llm_harness')",
            name="ck_benchmark_arm_family",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["benchmark_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "benchmark_arm_id",
            name="uq_benchmark_arm_campaign_id",
        ),
    )
    op.create_index(
        "ix_benchmark_arms_campaign_id",
        "benchmark_arms",
        ["campaign_id"],
    )
    op.create_index(
        "ix_benchmark_arms_manifest_sha256",
        "benchmark_arms",
        ["manifest_sha256"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite_guards()
    elif dialect == "postgresql":
        _install_postgres_guards()
    else:
        raise RuntimeError("Benchmark campaign migration supports SQLite/PostgreSQL only")


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER {_CAMPAIGN_TRIGGER_SQLITE}
        BEFORE UPDATE ON benchmark_campaigns
        WHEN NEW.user_id IS NOT OLD.user_id
          OR NEW.campaign_key IS NOT OLD.campaign_key
          OR NEW.campaign_version IS NOT OLD.campaign_version
          OR NEW.name IS NOT OLD.name
          OR NEW.panel IS NOT OLD.panel
          OR NEW.protocol_sha256 IS NOT OLD.protocol_sha256
          OR NEW.manifest_sha256 IS NOT OLD.manifest_sha256
          OR NEW.manifest_json IS NOT OLD.manifest_json
          OR NEW.composite_inventory_sha256 IS NOT OLD.composite_inventory_sha256
          OR NEW.composite_inventory_json IS NOT OLD.composite_inventory_json
          OR NEW.job_cap IS NOT OLD.job_cap
          OR NEW.trial_cap IS NOT OLD.trial_cap
          OR NEW.logical_turn_cap IS NOT OLD.logical_turn_cap
          OR NEW.network_request_cap IS NOT OLD.network_request_cap
          OR NEW.input_utf8_byte_cap IS NOT OLD.input_utf8_byte_cap
          OR NEW.output_utf8_byte_cap IS NOT OLD.output_utf8_byte_cap
          OR NEW.provider_token_cap IS NOT OLD.provider_token_cap
          OR NEW.provider_cost_microusd_cap IS NOT OLD.provider_cost_microusd_cap
          OR NEW.wall_time_second_cap IS NOT OLD.wall_time_second_cap
          OR NEW.disk_byte_cap IS NOT OLD.disk_byte_cap
          OR NEW.preregistered_at IS NOT OLD.preregistered_at
          OR NEW.created_at IS NOT OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'benchmark campaign preregistration is immutable');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_ARM_TRIGGER_SQLITE}
        BEFORE UPDATE ON benchmark_arms
        BEGIN
            SELECT RAISE(ABORT, 'benchmark arm preregistration is immutable');
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
            IF TG_TABLE_NAME = 'benchmark_arms' THEN
                RAISE EXCEPTION 'benchmark arm preregistration is immutable';
            END IF;
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
              OR NEW.campaign_key IS DISTINCT FROM OLD.campaign_key
              OR NEW.campaign_version IS DISTINCT FROM OLD.campaign_version
              OR NEW.name IS DISTINCT FROM OLD.name
              OR NEW.panel IS DISTINCT FROM OLD.panel
              OR NEW.protocol_sha256 IS DISTINCT FROM OLD.protocol_sha256
              OR NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256
              OR NEW.manifest_json IS DISTINCT FROM OLD.manifest_json
              OR NEW.composite_inventory_sha256 IS DISTINCT FROM OLD.composite_inventory_sha256
              OR NEW.composite_inventory_json IS DISTINCT FROM OLD.composite_inventory_json
              OR NEW.job_cap IS DISTINCT FROM OLD.job_cap
              OR NEW.trial_cap IS DISTINCT FROM OLD.trial_cap
              OR NEW.logical_turn_cap IS DISTINCT FROM OLD.logical_turn_cap
              OR NEW.network_request_cap IS DISTINCT FROM OLD.network_request_cap
              OR NEW.input_utf8_byte_cap IS DISTINCT FROM OLD.input_utf8_byte_cap
              OR NEW.output_utf8_byte_cap IS DISTINCT FROM OLD.output_utf8_byte_cap
              OR NEW.provider_token_cap IS DISTINCT FROM OLD.provider_token_cap
              OR NEW.provider_cost_microusd_cap IS DISTINCT FROM OLD.provider_cost_microusd_cap
              OR NEW.wall_time_second_cap IS DISTINCT FROM OLD.wall_time_second_cap
              OR NEW.disk_byte_cap IS DISTINCT FROM OLD.disk_byte_cap
              OR NEW.preregistered_at IS DISTINCT FROM OLD.preregistered_at
              OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'benchmark campaign preregistration is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_CAMPAIGN_TRIGGER_POSTGRES}
        BEFORE UPDATE ON benchmark_campaigns
        FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_ARM_TRIGGER_POSTGRES}
        BEFORE UPDATE ON benchmark_arms
        FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_ARM_TRIGGER_SQLITE}")
        op.execute(f"DROP TRIGGER IF EXISTS {_CAMPAIGN_TRIGGER_SQLITE}")
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_ARM_TRIGGER_POSTGRES} ON benchmark_arms"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_CAMPAIGN_TRIGGER_POSTGRES} ON benchmark_campaigns"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError("Benchmark campaign migration supports SQLite/PostgreSQL only")
    op.drop_index("ix_benchmark_arms_manifest_sha256", table_name="benchmark_arms")
    op.drop_index("ix_benchmark_arms_campaign_id", table_name="benchmark_arms")
    op.drop_table("benchmark_arms")
    op.drop_index(
        "ix_benchmark_campaigns_composite_inventory_sha256",
        table_name="benchmark_campaigns",
    )
    op.drop_index("ix_benchmark_campaigns_manifest_sha256", table_name="benchmark_campaigns")
    op.drop_index("ix_benchmark_campaigns_status", table_name="benchmark_campaigns")
    op.drop_index("ix_benchmark_campaigns_user_id", table_name="benchmark_campaigns")
    op.drop_table("benchmark_campaigns")
