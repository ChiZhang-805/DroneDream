"""Add revocable, user-isolated Harness experience memory.

Revision ID: 20260728_0015
Revises: 20260727_0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260728_0015"
down_revision = "20260727_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "harness_experience_memories",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("source_job_id", sa.String(length=64), nullable=False),
        sa.Column("source_generation", sa.Integer(), nullable=False),
        sa.Column("memory_schema_version", sa.String(length=32), nullable=False),
        sa.Column(
            "source_evidence_schema_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "source_prompt_template_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "source_tool_registry_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "source_eligibility_policy_version",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("task_family_sha256", sa.String(length=64), nullable=False),
        sa.Column("scenario_profile_json", sa.JSON(), nullable=False),
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("decision_source", sa.String(length=32), nullable=False),
        sa.Column("plan_phase", sa.String(length=32), nullable=False),
        sa.Column("batch_policy", sa.String(length=32), nullable=False),
        sa.Column("dispatched_candidates", sa.Integer(), nullable=False),
        sa.Column("planned_candidates", sa.Integer(), nullable=False),
        sa.Column("observed_outcome_json", sa.JSON(), nullable=False),
        sa.Column("source_receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_job_id",
            "source_generation",
            name="uq_harness_experience_source_generation",
        ),
        sa.UniqueConstraint("source_receipt_sha256"),
    )
    op.create_index(
        op.f("ix_harness_experience_memories_user_id"),
        "harness_experience_memories",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_harness_experience_memories_source_job_id"),
        "harness_experience_memories",
        ["source_job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_harness_experience_memories_task_family_sha256"),
        "harness_experience_memories",
        ["task_family_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_harness_experience_memories_source_receipt_sha256"),
        "harness_experience_memories",
        ["source_receipt_sha256"],
        unique=True,
    )
    op.create_index(
        op.f("ix_harness_experience_memories_expires_at"),
        "harness_experience_memories",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_harness_experience_memories_revoked_at"),
        "harness_experience_memories",
        ["revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_harness_experience_memories_revoked_at"),
        table_name="harness_experience_memories",
    )
    op.drop_index(
        op.f("ix_harness_experience_memories_expires_at"),
        table_name="harness_experience_memories",
    )
    op.drop_index(
        op.f("ix_harness_experience_memories_source_receipt_sha256"),
        table_name="harness_experience_memories",
    )
    op.drop_index(
        op.f("ix_harness_experience_memories_task_family_sha256"),
        table_name="harness_experience_memories",
    )
    op.drop_index(
        op.f("ix_harness_experience_memories_source_job_id"),
        table_name="harness_experience_memories",
    )
    op.drop_index(
        op.f("ix_harness_experience_memories_user_id"),
        table_name="harness_experience_memories",
    )
    op.drop_table("harness_experience_memories")
