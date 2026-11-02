"""Restrict saved defaults to generated track types.

Revision ID: 20260729_0017
Revises: 20260729_0016
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260729_0017"
down_revision: str | None = "20260729_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_user_experience_preferences_track"


def upgrade() -> None:
    with op.batch_alter_table("user_experience_preferences") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(
            _CONSTRAINT_NAME,
            "default_track_type IS NULL OR default_track_type IN "
            "('hover', 'circle', 'u_turn', 'lemniscate')",
        )


def downgrade() -> None:
    with op.batch_alter_table("user_experience_preferences") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(
            _CONSTRAINT_NAME,
            "default_track_type IS NULL OR default_track_type IN "
            "('hover', 'circle', 'u_turn', 'lemniscate', 'custom')",
        )
