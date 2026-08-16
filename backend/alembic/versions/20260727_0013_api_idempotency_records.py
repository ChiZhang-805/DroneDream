"""Add atomic API idempotency receipts.

Revision ID: 20260727_0013
Revises: 20260727_0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_0013"
down_revision = "20260727_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_idempotency_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key_hash",
            name="uq_api_idempotency_user_key",
        ),
    )
    op.create_index(
        "ix_api_idempotency_records_user_id",
        "api_idempotency_records",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_api_idempotency_records_status",
        "api_idempotency_records",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_idempotency_records_status",
        table_name="api_idempotency_records",
    )
    op.drop_index(
        "ix_api_idempotency_records_user_id",
        table_name="api_idempotency_records",
    )
    op.drop_table("api_idempotency_records")
