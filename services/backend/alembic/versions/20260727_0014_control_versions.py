"""Add optimistic control-command versions.

Revision ID: 20260727_0014
Revises: 20260727_0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_0014"
down_revision = "20260727_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_jobs",
        sa.Column(
            "control_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "control_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "control_version")
    op.drop_column("batch_jobs", "control_version")
