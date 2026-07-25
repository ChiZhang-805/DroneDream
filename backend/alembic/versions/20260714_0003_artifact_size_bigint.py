"""Store artifact sizes as 64-bit integers.

Revision ID: 20260714_0003
Revises: 20260714_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260714_0003"
down_revision = "20260714_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column(
            "file_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column(
            "file_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
