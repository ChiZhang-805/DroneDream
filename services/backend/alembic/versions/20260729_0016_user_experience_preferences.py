"""Add minimal per-user experience preferences and memory consent.

Revision ID: 20260729_0016
Revises: 20260728_0015
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0016"
down_revision: str | None = "20260728_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_experience_preferences",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column(
            "memory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("locale", sa.String(length=8), nullable=True),
        sa.Column("default_template_key", sa.String(length=64), nullable=True),
        sa.Column("default_track_type", sa.String(length=32), nullable=True),
        sa.Column("default_altitude_m", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint(
            "locale IS NULL OR locale IN ('en', 'zh-CN')",
            name="ck_user_experience_preferences_locale",
        ),
        sa.CheckConstraint(
            "default_template_key IS NULL OR default_template_key IN "
            "('hover-basics@1', 'first-circle@1', 'light-wind-circle@1')",
            name="ck_user_experience_preferences_template",
        ),
        sa.CheckConstraint(
            "default_track_type IS NULL OR default_track_type IN "
            "('hover', 'circle', 'u_turn', 'lemniscate', 'custom')",
            name="ck_user_experience_preferences_track",
        ),
        sa.CheckConstraint(
            "default_altitude_m IS NULL OR "
            "(default_altitude_m >= 1 AND default_altitude_m <= 20)",
            name="ck_user_experience_preferences_altitude",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_experience_preferences")
