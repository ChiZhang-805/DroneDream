"""Add durable replay receipts for authenticated desktop bridge requests.

Revision ID: 20260727_0012
Revises: 20260727_0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260727_0012"
down_revision = "20260727_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_bridge_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_id", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("nonce"),
    )
    op.create_index(
        "ix_desktop_bridge_nonces_session_id",
        "desktop_bridge_nonces",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_desktop_bridge_nonces_expires_at",
        "desktop_bridge_nonces",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_desktop_bridge_nonces_expires_at",
        table_name="desktop_bridge_nonces",
    )
    op.drop_index(
        "ix_desktop_bridge_nonces_session_id",
        table_name="desktop_bridge_nonces",
    )
    op.drop_table("desktop_bridge_nonces")
