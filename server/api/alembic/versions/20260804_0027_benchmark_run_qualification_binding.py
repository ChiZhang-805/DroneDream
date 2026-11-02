"""bind benchmark runs to sealed qualification execution contracts

Revision ID: 20260804_0027
Revises: 20260804_0026
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0027"
down_revision: str | None = "20260804_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_TABLE = "benchmark_campaign_run_bindings"


def upgrade() -> None:
    # Nullable preserves historical P0 preregistration rows honestly. Every
    # run bound by the current coordinator writes all three fields and fails
    # closed if the Job cannot compile the frozen 4+20 contract.
    op.add_column(
        _RUN_TABLE,
        sa.Column("qualification_policy_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        _RUN_TABLE,
        sa.Column("scenario_suite_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        _RUN_TABLE,
        sa.Column("qualification_contract_sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(_RUN_TABLE, "qualification_contract_sha256")
    op.drop_column(_RUN_TABLE, "scenario_suite_sha256")
    op.drop_column(_RUN_TABLE, "qualification_policy_version")
