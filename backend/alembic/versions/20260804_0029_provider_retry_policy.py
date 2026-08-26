"""freeze provider retry policy and actual request purpose

Revision ID: 20260804_0029
Revises: 20260804_0028
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0029"
down_revision: str | None = "20260804_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECEIPT_TABLE = "provider_network_request_receipts"
_SQLITE_POLICY_TRIGGER = "trg_provider_network_request_receipts_policy_check"


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider_max_retries",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_check_constraint(
            "ck_jobs_provider_max_retries",
            "provider_max_retries >= 0 AND provider_max_retries <= 5",
        )

    op.add_column(
        _RECEIPT_TABLE,
        sa.Column(
            "request_kind",
            sa.String(length=32),
            nullable=False,
            server_default="primary",
        ),
    )
    op.add_column(
        _RECEIPT_TABLE,
        sa.Column(
            "retry_policy_version",
            sa.String(length=64),
            nullable=False,
            server_default="explicit-network-attempts-v1",
        ),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER {_SQLITE_POLICY_TRIGGER}
            BEFORE INSERT ON {_RECEIPT_TABLE}
            WHEN NEW.request_kind NOT IN (
                'primary', 'retry', 'compatibility_fallback'
            )
            BEGIN
                SELECT RAISE(ABORT, 'provider request kind is invalid');
            END
            """
        )
    elif dialect == "postgresql":
        op.create_check_constraint(
            "ck_provider_request_kind",
            _RECEIPT_TABLE,
            "request_kind IN ('primary', 'retry', 'compatibility_fallback')",
        )
    else:
        raise RuntimeError("Provider retry policy supports SQLite/PostgreSQL only")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_POLICY_TRIGGER}")
    elif dialect == "postgresql":
        op.drop_constraint(
            "ck_provider_request_kind",
            _RECEIPT_TABLE,
            type_="check",
        )
    else:
        raise RuntimeError("Provider retry policy supports SQLite/PostgreSQL only")
    op.drop_column(_RECEIPT_TABLE, "retry_policy_version")
    op.drop_column(_RECEIPT_TABLE, "request_kind")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("ck_jobs_provider_max_retries", type_="check")
        batch_op.drop_column("provider_max_retries")
