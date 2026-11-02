"""Add persistent fencing tokens for renewable Job finalization claims.

Revision ID: 20260727_0011
Revises: 20260727_0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_0011"
down_revision = "20260727_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "finalization_claim_token",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "finalization_claim_generation",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "finalization_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_jobs_finalization_claim_token",
        "jobs",
        ["finalization_claim_token"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_finalization_lease_expires_at",
        "jobs",
        ["finalization_lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jobs_finalization_lease_expires_at",
        table_name="jobs",
    )
    op.drop_index(
        "ix_jobs_finalization_claim_token",
        table_name="jobs",
    )
    op.drop_column("jobs", "finalization_lease_expires_at")
    op.drop_column("jobs", "finalization_claim_generation")
    op.drop_column("jobs", "finalization_claim_token")
