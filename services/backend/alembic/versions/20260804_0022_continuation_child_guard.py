"""Enforce one continuation child per parent Job.

Revision ID: 20260804_0022
Revises: 20260804_0021
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260804_0022"
down_revision: str | None = "20260804_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.create_unique_constraint(
            "uq_jobs_continuation_parent_job_id",
            ["continuation_parent_job_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint(
            "uq_jobs_continuation_parent_job_id",
            type_="unique",
        )
