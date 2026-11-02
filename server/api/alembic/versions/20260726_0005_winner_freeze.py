"""Persist insert-once winner-freeze receipts.

Revision ID: 20260726_0005
Revises: 20260726_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_0005"
down_revision = "20260726_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "winner_freeze_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("receipt_schema", sa.String(length=128), nullable=False),
        sa.Column("evidence_id", sa.String(length=71), nullable=False),
        sa.Column("outcome_contract_id", sa.String(length=71), nullable=False),
        sa.Column(
            "baseline_candidate_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "winner_candidate_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            name="uq_winner_freeze_receipts_job_id",
        ),
        sa.UniqueConstraint(
            "evidence_id",
            name="uq_winner_freeze_receipts_evidence_id",
        ),
    )
    with op.batch_alter_table("job_reports") as batch_op:
        batch_op.add_column(
            sa.Column(
                "winner_freeze_receipt_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_job_reports_winner_freeze_receipt_id",
            "winner_freeze_receipts",
            ["winner_freeze_receipt_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_job_reports_winner_freeze_receipt_id",
            ["winner_freeze_receipt_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("job_reports") as batch_op:
        batch_op.drop_constraint(
            "uq_job_reports_winner_freeze_receipt_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_job_reports_winner_freeze_receipt_id",
            type_="foreignkey",
        )
        batch_op.drop_column("winner_freeze_receipt_id")
    op.drop_table("winner_freeze_receipts")
