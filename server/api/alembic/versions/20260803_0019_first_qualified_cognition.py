"""Add first-qualified and bounded cognitive-turn persistence contracts.

Revision ID: 20260803_0019
Revises: 20260729_0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0019"
down_revision: str | None = "20260729_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "completion_policy",
                sa.String(length=32),
                nullable=False,
                server_default="first_qualified_stop",
            )
        )
        batch_op.add_column(
            sa.Column(
                "job_kind",
                sa.String(length=32),
                nullable=False,
                server_default="primary",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cognitive_policy_version",
                sa.String(length=32),
                nullable=False,
                server_default="adaptive-2-4-v1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "provider_turn_cap",
                sa.Integer(),
                nullable=False,
                server_default="64",
            )
        )
        batch_op.add_column(
            sa.Column(
                "provider_turns_attempted",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "provider_turns_succeeded",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "next_candidate_dispatch_ordinal",
                sa.BigInteger(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "next_qualification_sequence",
                sa.BigInteger(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column("first_qualified_candidate_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("first_qualified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "continue_exploration_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("exploration_budget_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("continuation_parent_job_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("continuation_root_job_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "holdout_policy_version",
                sa.String(length=32),
                nullable=False,
                server_default="legacy-visible-v0",
            )
        )
        batch_op.add_column(sa.Column("holdout_contract_json", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_jobs_continuation_parent_job_id_jobs",
            "jobs",
            ["continuation_parent_job_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_jobs_continuation_root_job_id_jobs",
            "jobs",
            ["continuation_root_job_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_jobs_provider_turn_cap",
            "provider_turn_cap >= 0 AND provider_turn_cap <= 128",
        )
        batch_op.create_check_constraint(
            "ck_jobs_provider_turn_counts",
            "provider_turns_attempted >= 0 "
            "AND provider_turns_succeeded >= 0 "
            "AND provider_turns_succeeded <= provider_turns_attempted",
        )
        batch_op.create_check_constraint(
            "ck_jobs_next_candidate_dispatch_ordinal",
            "next_candidate_dispatch_ordinal >= 1",
        )
        batch_op.create_check_constraint(
            "ck_jobs_next_qualification_sequence",
            "next_qualification_sequence >= 1",
        )

    op.create_index(
        "ix_jobs_first_qualified_candidate_id",
        "jobs",
        ["first_qualified_candidate_id"],
    )
    op.create_index(
        "ix_jobs_continuation_parent_job_id",
        "jobs",
        ["continuation_parent_job_id"],
    )
    op.create_index(
        "ix_jobs_continuation_root_job_id",
        "jobs",
        ["continuation_root_job_id"],
    )

    with op.batch_alter_table("candidate_parameter_sets") as batch_op:
        batch_op.add_column(sa.Column("dispatch_ordinal", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("qualification_sequence", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(
            "uq_candidate_job_dispatch_ordinal",
            ["job_id", "dispatch_ordinal"],
        )
        batch_op.create_unique_constraint(
            "uq_candidate_job_qualification_sequence",
            ["job_id", "qualification_sequence"],
        )
        batch_op.create_check_constraint(
            "ck_candidate_dispatch_ordinal",
            "dispatch_ordinal IS NULL OR dispatch_ordinal >= 1",
        )
        batch_op.create_check_constraint(
            "ck_candidate_qualification_sequence",
            "qualification_sequence IS NULL OR qualification_sequence >= 1",
        )
    if op.get_bind().dialect.name == "sqlite":
        _restore_sqlite_candidate_guards()

    op.create_table(
        "first_qualified_freeze_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("receipt_schema", sa.String(length=128), nullable=False),
        sa.Column("definition_version", sa.String(length=32), nullable=False),
        sa.Column("evidence_id", sa.String(length=71), nullable=False),
        sa.Column("holdout_contract_sha256", sa.String(length=64), nullable=False),
        sa.Column("qualification_sequence", sa.BigInteger(), nullable=False),
        sa.Column("generation_index", sa.Integer(), nullable=False),
        sa.Column("dispatch_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("time_to_first_qualified_ms", sa.BigInteger(), nullable=False),
        sa.Column("simulations_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_completed_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_passed_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_failed_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_cancelled_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_timed_out_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("trials_indeterminate_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("generations_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("provider_turns_attempted_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("provider_turns_succeeded_to_first_qualified", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "qualification_sequence >= 1 AND generation_index >= 0 "
            "AND dispatch_ordinal >= 1 AND time_to_first_qualified_ms >= 0",
            name="ck_first_qualified_order_and_time",
        ),
        sa.CheckConstraint(
            "simulations_to_first_qualified >= 0 "
            "AND trials_to_first_qualified >= 0 "
            "AND trials_completed_to_first_qualified >= 0 "
            "AND trials_passed_to_first_qualified >= 0 "
            "AND trials_failed_to_first_qualified >= 0 "
            "AND trials_cancelled_to_first_qualified >= 0 "
            "AND trials_timed_out_to_first_qualified >= 0 "
            "AND trials_indeterminate_to_first_qualified >= 0 "
            "AND generations_to_first_qualified >= 0 "
            "AND provider_turns_attempted_to_first_qualified >= 0 "
            "AND provider_turns_succeeded_to_first_qualified >= 0 "
            "AND provider_turns_succeeded_to_first_qualified "
            "<= provider_turns_attempted_to_first_qualified",
            name="ck_first_qualified_nonnegative_accounting",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_first_qualified_freeze_job_id"),
        sa.UniqueConstraint("evidence_id", name="uq_first_qualified_freeze_evidence_id"),
    )
    op.create_index(
        "ix_first_qualified_freeze_receipts_job_id",
        "first_qualified_freeze_receipts",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        "ix_first_qualified_freeze_receipts_candidate_id",
        "first_qualified_freeze_receipts",
        ["candidate_id"],
    )

    op.create_table(
        "harness_cognitive_turn_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("receipt_schema", sa.String(length=128), nullable=False),
        sa.Column("generation_index", sa.Integer(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("turn_role", sa.String(length=32), nullable=False),
        sa.Column("trigger_policy_version", sa.String(length=32), nullable=False),
        sa.Column("trigger_reasons_json", sa.JSON(), nullable=False),
        sa.Column("source_commit", sa.String(length=40), nullable=False),
        sa.Column("model_snapshot", sa.String(length=128), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("tool_outputs_sha256", sa.String(length=64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("generation_index >= 0", name="ck_harness_turn_generation"),
        sa.CheckConstraint("turn_index >= 1 AND turn_index <= 4", name="ck_harness_turn_index"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "generation_index",
            "turn_index",
            name="uq_harness_turn_job_generation_index",
        ),
    )
    op.create_index(
        "ix_harness_cognitive_turn_receipts_job_id",
        "harness_cognitive_turn_receipts",
        ["job_id"],
    )

    op.create_table(
        "harness_cognitive_turn_outcomes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("turn_receipt_id", sa.String(length=64), nullable=False),
        sa.Column("outcome_schema", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["turn_receipt_id"],
            ["harness_cognitive_turn_receipts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_receipt_id", name="uq_harness_cognitive_turn_outcome_receipt"),
    )
    op.create_index(
        "ix_harness_cognitive_turn_outcomes_turn_receipt_id",
        "harness_cognitive_turn_outcomes",
        ["turn_receipt_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_harness_cognitive_turn_outcomes_turn_receipt_id",
        table_name="harness_cognitive_turn_outcomes",
    )
    op.drop_table("harness_cognitive_turn_outcomes")
    op.drop_index(
        "ix_harness_cognitive_turn_receipts_job_id",
        table_name="harness_cognitive_turn_receipts",
    )
    op.drop_table("harness_cognitive_turn_receipts")
    op.drop_index(
        "ix_first_qualified_freeze_receipts_candidate_id",
        table_name="first_qualified_freeze_receipts",
    )
    op.drop_index(
        "ix_first_qualified_freeze_receipts_job_id",
        table_name="first_qualified_freeze_receipts",
    )
    op.drop_table("first_qualified_freeze_receipts")

    with op.batch_alter_table("candidate_parameter_sets") as batch_op:
        batch_op.drop_constraint("ck_candidate_qualification_sequence", type_="check")
        batch_op.drop_constraint("ck_candidate_dispatch_ordinal", type_="check")
        batch_op.drop_constraint("uq_candidate_job_qualification_sequence", type_="unique")
        batch_op.drop_constraint("uq_candidate_job_dispatch_ordinal", type_="unique")
        batch_op.drop_column("qualified_at")
        batch_op.drop_column("qualification_sequence")
        batch_op.drop_column("dispatch_ordinal")
    if op.get_bind().dialect.name == "sqlite":
        _restore_sqlite_candidate_guards()

    op.drop_index("ix_jobs_continuation_root_job_id", table_name="jobs")
    op.drop_index("ix_jobs_continuation_parent_job_id", table_name="jobs")
    op.drop_index("ix_jobs_first_qualified_candidate_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("ck_jobs_next_qualification_sequence", type_="check")
        batch_op.drop_constraint("ck_jobs_next_candidate_dispatch_ordinal", type_="check")
        batch_op.drop_constraint("ck_jobs_provider_turn_counts", type_="check")
        batch_op.drop_constraint("ck_jobs_provider_turn_cap", type_="check")
        batch_op.drop_constraint("fk_jobs_continuation_root_job_id_jobs", type_="foreignkey")
        batch_op.drop_constraint("fk_jobs_continuation_parent_job_id_jobs", type_="foreignkey")
        batch_op.drop_column("holdout_contract_json")
        batch_op.drop_column("holdout_policy_version")
        batch_op.drop_column("continuation_root_job_id")
        batch_op.drop_column("continuation_parent_job_id")
        batch_op.drop_column("exploration_budget_json")
        batch_op.drop_column("continue_exploration_requested")
        batch_op.drop_column("first_qualified_at")
        batch_op.drop_column("first_qualified_candidate_id")
        batch_op.drop_column("next_qualification_sequence")
        batch_op.drop_column("next_candidate_dispatch_ordinal")
        batch_op.drop_column("provider_turns_succeeded")
        batch_op.drop_column("provider_turns_attempted")
        batch_op.drop_column("provider_turn_cap")
        batch_op.drop_column("cognitive_policy_version")
        batch_op.drop_column("job_kind")
        batch_op.drop_column("completion_policy")


def _restore_sqlite_candidate_guards() -> None:
    """Restore guards dropped when SQLite batch mode recreates the table."""

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS
        trg_candidate_evidence_required_no_downgrade
        BEFORE UPDATE OF evidence_ledger_required
        ON candidate_parameter_sets
        WHEN OLD.evidence_ledger_required = 1
         AND NEW.evidence_ledger_required IS NOT 1
        BEGIN
            SELECT RAISE(
                ABORT,
                'Candidate evidence requirement is irreversible'
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS
        trg_candidate_provenance_no_mutation
        BEFORE UPDATE OF source_type, optimizer_metadata_json
        ON candidate_parameter_sets
        WHEN OLD.evidence_ledger_required = 1
         AND (
                NEW.source_type IS NOT OLD.source_type
             OR NEW.optimizer_metadata_json IS NOT OLD.optimizer_metadata_json
         )
        BEGIN
            SELECT RAISE(
                ABORT,
                'Candidate provenance is immutable after evidence sealing'
            );
        END
        """
    )
