"""Persist non-secret model access mode for faithful job reruns.

Revision ID: 20260729_0018
Revises: 20260729_0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0018"
down_revision: str | None = "20260729_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("llm_access_mode", sa.String(length=16), nullable=True),
    )
    op.execute(
        "UPDATE jobs SET llm_access_mode = CASE "
        "WHEN llm_provider = 'dronedream' THEN 'platform' "
        "WHEN llm_provider IS NOT NULL THEN 'byok' "
        "ELSE NULL END "
        "WHERE llm_access_mode IS NULL"
    )


def downgrade() -> None:
    op.drop_column("jobs", "llm_access_mode")
