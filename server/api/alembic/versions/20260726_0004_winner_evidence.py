"""Persist content-addressed winner-selection evidence.

Revision ID: 20260726_0004
Revises: 20260714_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_0004"
down_revision = "20260714_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_reports") as batch_op:
        batch_op.add_column(
            sa.Column("winner_evidence_json", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("job_reports") as batch_op:
        batch_op.drop_column("winner_evidence_json")
