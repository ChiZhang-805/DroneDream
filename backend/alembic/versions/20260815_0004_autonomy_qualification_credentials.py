"""Persist owner-scoped autonomy qualification credentials.

Revision ID: 20260815_0004
Revises: 20260714_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0004"
down_revision = "20260714_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomy_qualification_credentials",
        sa.Column("receipt_id", sa.String(length=96), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("asset_kind", sa.String(length=16), nullable=False),
        sa.Column("asset_id", sa.String(length=128), nullable=False),
        sa.Column("asset_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("receipt_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("receipt_id"),
        sa.UniqueConstraint(
            "user_id",
            "asset_kind",
            "asset_id",
            "asset_version",
            name="uq_autonomy_qualification_credentials_owner_asset_version",
        ),
    )
    op.create_index(
        "ix_autonomy_qualification_credentials_user_id",
        "autonomy_qualification_credentials",
        ["user_id"],
    )
    op.create_index(
        "ix_autonomy_qualification_credentials_asset_kind",
        "autonomy_qualification_credentials",
        ["asset_kind"],
    )
    op.create_index(
        "ix_autonomy_qualification_credentials_asset_id",
        "autonomy_qualification_credentials",
        ["asset_id"],
    )
    op.create_index(
        "ix_autonomy_qualification_credentials_content_sha256",
        "autonomy_qualification_credentials",
        ["content_sha256"],
    )
    op.create_index(
        "ix_autonomy_qualification_credentials_revoked_at",
        "autonomy_qualification_credentials",
        ["revoked_at"],
    )
    op.create_index(
        "uq_autonomy_qualification_credentials_active_asset",
        "autonomy_qualification_credentials",
        ["user_id", "asset_kind", "asset_id"],
        unique=True,
        sqlite_where=sa.text("revoked_at IS NULL"),
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_autonomy_qualification_credentials_active_asset",
        table_name="autonomy_qualification_credentials",
    )
    op.drop_index(
        "ix_autonomy_qualification_credentials_revoked_at",
        table_name="autonomy_qualification_credentials",
    )
    op.drop_index(
        "ix_autonomy_qualification_credentials_content_sha256",
        table_name="autonomy_qualification_credentials",
    )
    op.drop_index(
        "ix_autonomy_qualification_credentials_asset_id",
        table_name="autonomy_qualification_credentials",
    )
    op.drop_index(
        "ix_autonomy_qualification_credentials_asset_kind",
        table_name="autonomy_qualification_credentials",
    )
    op.drop_index(
        "ix_autonomy_qualification_credentials_user_id",
        table_name="autonomy_qualification_credentials",
    )
    op.drop_table("autonomy_qualification_credentials")
