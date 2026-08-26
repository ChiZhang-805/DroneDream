"""Merge autonomy qualification storage into the canonical schema lineage.

Revision ID: 20260816_0005
Revises: 20260805_0034, 20260815_0004
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "20260816_0005"
down_revision: tuple[str, str] = ("20260805_0034", "20260815_0004")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two already-applied schema lineages."""


def downgrade() -> None:
    """Return to the two parent heads without changing schema objects."""
