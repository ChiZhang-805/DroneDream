"""freeze actual provider-request counts at first qualification

Revision ID: 20260804_0030
Revises: 20260804_0029
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0030"
down_revision: str | None = "20260804_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_COUNT_TRIGGER = "trg_first_qualified_provider_request_counts_insert"
_POSTGRES_COUNT_CONSTRAINT = "ck_first_qualified_provider_request_counts"


def upgrade() -> None:
    op.add_column(
        "first_qualified_freeze_receipts",
        sa.Column(
            "provider_requests_attempted_to_first_qualified",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "first_qualified_freeze_receipts",
        sa.Column(
            "provider_requests_succeeded_to_first_qualified",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER {_SQLITE_COUNT_TRIGGER}
            BEFORE INSERT ON first_qualified_freeze_receipts
            WHEN NEW.provider_requests_attempted_to_first_qualified < 0
              OR NEW.provider_requests_succeeded_to_first_qualified < 0
              OR NEW.provider_requests_succeeded_to_first_qualified
                 > NEW.provider_requests_attempted_to_first_qualified
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'first-qualified provider request counts are invalid'
                );
            END
            """
        )
    elif dialect == "postgresql":
        op.create_check_constraint(
            _POSTGRES_COUNT_CONSTRAINT,
            "first_qualified_freeze_receipts",
            "provider_requests_attempted_to_first_qualified >= 0 "
            "AND provider_requests_succeeded_to_first_qualified >= 0 "
            "AND provider_requests_succeeded_to_first_qualified "
            "<= provider_requests_attempted_to_first_qualified",
        )
    else:
        raise RuntimeError(
            "First-qualified request-count migration supports SQLite/PostgreSQL only"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_COUNT_TRIGGER}")
    elif dialect == "postgresql":
        op.drop_constraint(
            _POSTGRES_COUNT_CONSTRAINT,
            "first_qualified_freeze_receipts",
            type_="check",
        )
    else:
        raise RuntimeError(
            "First-qualified request-count migration supports SQLite/PostgreSQL only"
        )
    op.drop_column(
        "first_qualified_freeze_receipts",
        "provider_requests_succeeded_to_first_qualified",
    )
    op.drop_column(
        "first_qualified_freeze_receipts",
        "provider_requests_attempted_to_first_qualified",
    )
