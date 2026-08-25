"""Persist canonical Model + Harness and verified-memory domains.

Revision ID: 20260824_0006
Revises: 20260816_0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0006"
down_revision: str | None = "20260816_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "model_harness_domain",
                sa.String(length=64),
                server_default="optimization.control_tuning",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_jobs_model_harness_domain",
            "model_harness_domain = 'optimization.control_tuning'",
        )

    with op.batch_alter_table("harness_experience_memories") as batch_op:
        batch_op.add_column(
            sa.Column(
                "memory_domain",
                sa.String(length=64),
                server_default="optimization.control_tuning",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "source_kind",
                sa.String(length=32),
                server_default="verified_job_outcome",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("evidence_count", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "lifecycle_status",
                sa.String(length=16),
                server_default="consolidated",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_harness_experience_source_kind",
            "source_kind = 'verified_job_outcome'",
        )
        batch_op.create_check_constraint(
            "ck_harness_experience_memory_domain",
            "memory_domain IN ("
            "'optimization.control_tuning', 'autonomy.mission', "
            "'asset.qualification', 'experiment.simulation', "
            "'workflow.cross_edition', 'validation.hardware', "
            "'calibration.system', 'transfer.sim_to_real', "
            "'transfer.real_to_sim', 'operations.field'"
            ")",
        )
        batch_op.create_check_constraint(
            "ck_harness_experience_evidence_count",
            "evidence_count >= 1",
        )
        batch_op.create_check_constraint(
            "ck_harness_experience_confidence",
            "confidence >= 0 AND confidence <= 1",
        )
        batch_op.create_check_constraint(
            "ck_harness_experience_lifecycle_status",
            "lifecycle_status = 'consolidated'",
        )

    op.create_index(
        "ix_harness_experience_memories_memory_domain",
        "harness_experience_memories",
        ["memory_domain"],
        unique=False,
    )
    op.create_index(
        "ix_harness_experience_owner_domain_family",
        "harness_experience_memories",
        ["user_id", "memory_domain", "task_family_sha256"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_harness_experience_owner_domain_family",
        table_name="harness_experience_memories",
    )
    op.drop_index(
        "ix_harness_experience_memories_memory_domain",
        table_name="harness_experience_memories",
    )
    with op.batch_alter_table("harness_experience_memories") as batch_op:
        batch_op.drop_constraint(
            "ck_harness_experience_lifecycle_status",
            type_="check",
        )
        batch_op.drop_constraint("ck_harness_experience_confidence", type_="check")
        batch_op.drop_constraint("ck_harness_experience_evidence_count", type_="check")
        batch_op.drop_constraint("ck_harness_experience_memory_domain", type_="check")
        batch_op.drop_constraint("ck_harness_experience_source_kind", type_="check")
        batch_op.drop_column("lifecycle_status")
        batch_op.drop_column("confidence")
        batch_op.drop_column("evidence_count")
        batch_op.drop_column("source_kind")
        batch_op.drop_column("memory_domain")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("ck_jobs_model_harness_domain", type_="check")
        batch_op.drop_column("model_harness_domain")
