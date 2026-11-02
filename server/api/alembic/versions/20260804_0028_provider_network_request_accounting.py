"""separate logical cognitive turns from actual provider network requests

Revision ID: 20260804_0028
Revises: 20260804_0027
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0028"
down_revision: str | None = "20260804_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECEIPT_TABLE = "provider_network_request_receipts"
_OUTCOME_TABLE = "provider_network_request_outcomes"
_RECEIPT_UPDATE_TRIGGER = "trg_provider_network_request_receipts_no_update"
_RECEIPT_DELETE_TRIGGER = "trg_provider_network_request_receipts_no_delete"
_OUTCOME_UPDATE_TRIGGER = "trg_provider_network_request_outcomes_no_update"
_OUTCOME_DELETE_TRIGGER = "trg_provider_network_request_outcomes_no_delete"
_POSTGRES_FUNCTION = "dronedream_reject_provider_network_request_mutation"
_POSTGRES_RECEIPT_TRIGGER = "trg_provider_network_request_receipts_immutable"
_POSTGRES_OUTCOME_TRIGGER = "trg_provider_network_request_outcomes_immutable"


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider_request_cap",
                sa.Integer(),
                nullable=False,
                server_default="128",
            )
        )
        batch_op.add_column(
            sa.Column(
                "provider_requests_attempted",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "provider_requests_succeeded",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_jobs_provider_request_cap",
            "provider_request_cap >= 0 AND provider_request_cap <= 256",
        )
        batch_op.create_check_constraint(
            "ck_jobs_provider_request_counts",
            "provider_requests_attempted >= 0 "
            "AND provider_requests_succeeded >= 0 "
            "AND provider_requests_succeeded <= provider_requests_attempted",
        )

    op.create_table(
        _RECEIPT_TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("cognitive_turn_receipt_id", sa.String(length=64), nullable=False),
        sa.Column("receipt_schema", sa.String(length=128), nullable=False),
        sa.Column("request_index", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_snapshot", sa.String(length=128), nullable=False),
        sa.Column("api_surface", sa.String(length=64), nullable=False),
        sa.Column("base_url_normalized", sa.String(length=2048), nullable=False),
        sa.Column("base_url_sha256", sa.String(length=64), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("provider_seed", sa.BigInteger(), nullable=True),
        sa.Column("response_schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("tool_outputs_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_body_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_utf8_bytes", sa.BigInteger(), nullable=False),
        sa.Column("price_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("price_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_index >= 1 AND request_index <= 8",
            name="ck_provider_request_index",
        ),
        sa.CheckConstraint(
            "input_utf8_bytes >= 0",
            name="ck_provider_request_input_bytes",
        ),
        sa.CheckConstraint(
            "temperature IS NULL OR (temperature >= 0 AND temperature <= 2)",
            name="ck_provider_request_temperature",
        ),
        sa.CheckConstraint(
            "top_p IS NULL OR (top_p > 0 AND top_p <= 1)",
            name="ck_provider_request_top_p",
        ),
        sa.ForeignKeyConstraint(
            ["cognitive_turn_receipt_id"],
            ["harness_cognitive_turn_receipts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cognitive_turn_receipt_id",
            "request_index",
            name="uq_provider_request_turn_index",
        ),
    )
    op.create_index(
        "ix_provider_network_request_receipts_cognitive_turn_receipt_id",
        _RECEIPT_TABLE,
        ["cognitive_turn_receipt_id"],
    )

    op.create_table(
        _OUTCOME_TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("request_receipt_id", sa.String(length=64), nullable=False),
        sa.Column("outcome_schema", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("output_utf8_bytes", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("provider_cost_microusd", sa.BigInteger(), nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'indeterminate')",
            name="ck_provider_request_outcome_status",
        ),
        sa.CheckConstraint(
            "output_utf8_bytes >= 0 AND latency_ms >= 0",
            name="ck_provider_request_outcome_bytes_latency",
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0) "
            "AND (total_tokens IS NULL OR total_tokens >= 0) "
            "AND (provider_cost_microusd IS NULL OR provider_cost_microusd >= 0)",
            name="ck_provider_request_outcome_usage",
        ),
        sa.ForeignKeyConstraint(
            ["request_receipt_id"],
            [f"{_RECEIPT_TABLE}.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_receipt_id",
            name="uq_provider_request_outcome_receipt",
        ),
    )
    op.create_index(
        "ix_provider_network_request_outcomes_request_receipt_id",
        _OUTCOME_TABLE,
        ["request_receipt_id"],
        unique=True,
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite_guards()
    elif dialect == "postgresql":
        _install_postgres_guards()
    else:
        raise RuntimeError(
            "Provider network request migration supports SQLite/PostgreSQL only"
        )


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER {_RECEIPT_UPDATE_TRIGGER}
        BEFORE UPDATE ON {_RECEIPT_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'provider network request receipts are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_RECEIPT_DELETE_TRIGGER}
        BEFORE DELETE ON {_RECEIPT_TABLE}
        WHEN NOT EXISTS (
            SELECT 1 FROM harness_cognitive_turn_delete_authorizations
            WHERE receipt_id = OLD.cognitive_turn_receipt_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'provider network request receipts are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_OUTCOME_UPDATE_TRIGGER}
        BEFORE UPDATE ON {_OUTCOME_TABLE}
        BEGIN
            SELECT RAISE(ABORT, 'provider network request outcomes are append-only');
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_OUTCOME_DELETE_TRIGGER}
        BEFORE DELETE ON {_OUTCOME_TABLE}
        WHEN NOT EXISTS (
            SELECT 1
            FROM harness_cognitive_turn_delete_authorizations AS authorization
            JOIN {_RECEIPT_TABLE} AS receipt
              ON receipt.cognitive_turn_receipt_id = authorization.receipt_id
            WHERE receipt.id = OLD.request_receipt_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'provider network request outcomes are append-only');
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
                IF TG_TABLE_NAME = '{_RECEIPT_TABLE}' THEN
                    protected_receipt_id := OLD.cognitive_turn_receipt_id;
                ELSE
                    SELECT cognitive_turn_receipt_id
                    INTO protected_receipt_id
                    FROM {_RECEIPT_TABLE}
                    WHERE id = OLD.request_receipt_id;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM harness_cognitive_turn_delete_authorizations
                    WHERE receipt_id = protected_receipt_id
                ) THEN
                    RETURN OLD;
                END IF;
            END IF;
            RAISE EXCEPTION 'provider network request records are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_POSTGRES_RECEIPT_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_RECEIPT_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_POSTGRES_OUTCOME_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_OUTCOME_TABLE}
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
            f"DROP TRIGGER IF EXISTS {_POSTGRES_OUTCOME_TRIGGER} ON {_OUTCOME_TABLE}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_RECEIPT_TRIGGER} ON {_RECEIPT_TABLE}"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError(
            "Provider network request migration supports SQLite/PostgreSQL only"
        )

    op.drop_index(
        "ix_provider_network_request_outcomes_request_receipt_id",
        table_name=_OUTCOME_TABLE,
    )
    op.drop_table(_OUTCOME_TABLE)
    op.drop_index(
        "ix_provider_network_request_receipts_cognitive_turn_receipt_id",
        table_name=_RECEIPT_TABLE,
    )
    op.drop_table(_RECEIPT_TABLE)
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("ck_jobs_provider_request_counts", type_="check")
        batch_op.drop_constraint("ck_jobs_provider_request_cap", type_="check")
        batch_op.drop_column("provider_requests_succeeded")
        batch_op.drop_column("provider_requests_attempted")
        batch_op.drop_column("provider_request_cap")
