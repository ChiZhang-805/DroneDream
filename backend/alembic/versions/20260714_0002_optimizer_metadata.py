"""Persist reproducible experimental-optimizer candidate metadata.

Revision ID: 20260714_0002
Revises: 20260710_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260714_0002"
down_revision = "20260710_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("candidate_parameter_sets") as batch_op:
        batch_op.add_column(sa.Column("optimizer_metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("candidate_parameter_sets") as batch_op:
        batch_op.drop_column("optimizer_metadata_json")
