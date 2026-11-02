"""add versioned two-stage candidate qualification contract

Revision ID: 20260804_0026
Revises: 20260804_0025
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0026"
down_revision: str | None = "20260804_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUALIFICATION_TABLE = "candidate_qualifications"
_RECEIPT_TABLE = "qualification_trial_receipts"
_POSTGRES_FUNCTION = "dronedream_reject_qualification_trial_receipt_mutation"


def _restore_sqlite_accepted_attempt_guard() -> None:
    """Reinstall the guard dropped by SQLite's batch table rebuild."""

    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_trials_accepted_attempt_immutable
        BEFORE UPDATE OF accepted_attempt_id ON trials
        WHEN (
            OLD.accepted_attempt_id IS NOT NULL
            AND NEW.accepted_attempt_id IS NOT OLD.accepted_attempt_id
            AND NOT EXISTS (
                SELECT 1
                FROM trial_execution_attempt_delete_authorizations
                WHERE attempt_id = OLD.accepted_attempt_id
            )
        ) OR (
            NEW.accepted_attempt_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM trial_execution_attempts
                WHERE id = NEW.accepted_attempt_id
                  AND trial_id = OLD.id
            )
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'accepted Trial execution attempt is immutable or mismatched'
            );
        END
        """
    )


def _create_receipt_immutability_triggers() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE TRIGGER trg_qualification_trial_receipts_no_{operation.lower()}
                BEFORE {operation} ON {_RECEIPT_TABLE}
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'qualification Trial receipts are append-only'
                    );
                END
                """
            )
    elif dialect == "postgresql":
        op.execute(
            f"""
            CREATE FUNCTION {_POSTGRES_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'qualification Trial receipts are append-only';
            END;
            $$
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_qualification_trial_receipts_immutable
            BEFORE UPDATE OR DELETE ON {_RECEIPT_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {_POSTGRES_FUNCTION}()
            """
        )
    else:
        raise RuntimeError("Qualification migration supports SQLite/PostgreSQL only")


def upgrade() -> None:
    op.create_table(
        _QUALIFICATION_TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("contract_schema", sa.String(length=128), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("rule_sha256", sa.String(length=64), nullable=False),
        sa.Column("holdout_contract_sha256", sa.String(length=64), nullable=False),
        sa.Column("selection_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default="pending_screening",
        ),
        sa.Column("state_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("qualification_sequence", sa.BigInteger(), nullable=True),
        sa.Column("screening_required", sa.Integer(), nullable=False, server_default="4"),
        sa.Column(
            "qualification_initial_required",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
        sa.Column(
            "qualification_extended_required",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column("direct_pass_min", sa.Integer(), nullable=False, server_default="9"),
        sa.Column(
            "extension_trigger_passes",
            sa.Integer(),
            nullable=False,
            server_default="8",
        ),
        sa.Column("extended_pass_min", sa.Integer(), nullable=False, server_default="18"),
        sa.Column(
            "max_candidates_per_run",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ("
            "'pending_screening', 'screening', 'screening_failed', "
            "'sealed_qualification', 'qualification_10', "
            "'qualification_extended_20', 'qualified', "
            "'qualification_failed', 'indeterminate', 'cancelled'"
            ")",
            name="ck_candidate_qualification_state",
        ),
        sa.CheckConstraint(
            "state_revision >= 1 AND screening_required = 4 "
            "AND qualification_initial_required = 10 "
            "AND qualification_extended_required = 20 "
            "AND direct_pass_min = 9 AND extension_trigger_passes = 8 "
            "AND extended_pass_min = 18 AND max_candidates_per_run = 2",
            name="ck_candidate_qualification_rule_v1",
        ),
        sa.CheckConstraint(
            "qualification_sequence IS NULL OR qualification_sequence >= 1",
            name="ck_candidate_qualification_sequence",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_parameter_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", name="uq_candidate_qualification_candidate"),
        sa.UniqueConstraint(
            "job_id",
            "qualification_sequence",
            name="uq_candidate_qualification_job_sequence",
        ),
    )
    op.create_index("ix_candidate_qualifications_job_id", _QUALIFICATION_TABLE, ["job_id"])
    op.create_index(
        "ix_candidate_qualifications_candidate_id",
        _QUALIFICATION_TABLE,
        ["candidate_id"],
    )
    op.create_index("ix_candidate_qualifications_state", _QUALIFICATION_TABLE, ["state"])

    with op.batch_alter_table("trials") as batch_op:
        batch_op.add_column(sa.Column("qualification_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "evaluation_phase",
                sa.String(length=32),
                nullable=False,
                server_default="optimization",
            )
        )
        batch_op.add_column(sa.Column("qualification_ordinal", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_trials_qualification_id",
            _QUALIFICATION_TABLE,
            ["qualification_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_trial_qualification_phase_ordinal",
            ["qualification_id", "evaluation_phase", "qualification_ordinal"],
        )
        batch_op.create_check_constraint(
            "ck_trial_evaluation_phase_binding",
            "(evaluation_phase = 'optimization' "
            "AND qualification_id IS NULL AND qualification_ordinal IS NULL) OR "
            "(evaluation_phase = 'screening' "
            "AND qualification_id IS NOT NULL "
            "AND qualification_ordinal >= 1 AND qualification_ordinal <= 4) OR "
            "(evaluation_phase = 'qualification' "
            "AND qualification_id IS NOT NULL "
            "AND qualification_ordinal >= 1 AND qualification_ordinal <= 20)",
        )
    _restore_sqlite_accepted_attempt_guard()
    op.create_index("ix_trials_qualification_id", "trials", ["qualification_id"])

    op.create_table(
        _RECEIPT_TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("qualification_id", sa.String(length=64), nullable=False),
        sa.Column("trial_id", sa.String(length=64), nullable=False),
        sa.Column("receipt_schema", sa.String(length=128), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("terminal_status", sa.String(length=32), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("safety_critical_failure", sa.Boolean(), nullable=False),
        sa.Column("effect_readback_complete", sa.Boolean(), nullable=False),
        sa.Column("evidence_complete", sa.Boolean(), nullable=False),
        sa.Column("evidence_id", sa.String(length=71), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('screening', 'qualification')",
            name="ck_qualification_trial_receipt_phase",
        ),
        sa.CheckConstraint(
            "(phase = 'screening' AND ordinal >= 1 AND ordinal <= 4) OR "
            "(phase = 'qualification' AND ordinal >= 1 AND ordinal <= 20)",
            name="ck_qualification_trial_receipt_ordinal",
        ),
        sa.CheckConstraint(
            "terminal_status IN ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'INDETERMINATE')",
            name="ck_qualification_trial_receipt_terminal_status",
        ),
        sa.ForeignKeyConstraint(
            ["qualification_id"], [_QUALIFICATION_TABLE + ".id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["trials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_id", name="uq_qualification_trial_receipt_trial"),
        sa.UniqueConstraint(
            "qualification_id",
            "phase",
            "ordinal",
            name="uq_qualification_trial_receipt_phase_ordinal",
        ),
        sa.UniqueConstraint("evidence_id", name="uq_qualification_trial_receipt_evidence"),
    )
    op.create_index(
        "ix_qualification_trial_receipts_qualification_id",
        _RECEIPT_TABLE,
        ["qualification_id"],
    )
    op.create_index("ix_qualification_trial_receipts_trial_id", _RECEIPT_TABLE, ["trial_id"])
    op.create_index("ix_qualification_trial_receipts_evidence_id", _RECEIPT_TABLE, ["evidence_id"])
    _create_receipt_immutability_triggers()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for operation in ("delete", "update"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_qualification_trial_receipts_no_{operation}")
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_qualification_trial_receipts_immutable ON {_RECEIPT_TABLE}"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
    else:
        raise RuntimeError("Qualification migration supports SQLite/PostgreSQL only")

    for name in (
        "ix_qualification_trial_receipts_evidence_id",
        "ix_qualification_trial_receipts_trial_id",
        "ix_qualification_trial_receipts_qualification_id",
    ):
        op.drop_index(name, table_name=_RECEIPT_TABLE)
    op.drop_table(_RECEIPT_TABLE)
    op.drop_index("ix_trials_qualification_id", table_name="trials")
    with op.batch_alter_table("trials") as batch_op:
        batch_op.drop_constraint("ck_trial_evaluation_phase_binding", type_="check")
        batch_op.drop_constraint("uq_trial_qualification_phase_ordinal", type_="unique")
        batch_op.drop_constraint("fk_trials_qualification_id", type_="foreignkey")
        batch_op.drop_column("qualification_ordinal")
        batch_op.drop_column("evaluation_phase")
        batch_op.drop_column("qualification_id")
    _restore_sqlite_accepted_attempt_guard()
    for name in (
        "ix_candidate_qualifications_state",
        "ix_candidate_qualifications_candidate_id",
        "ix_candidate_qualifications_job_id",
    ):
        op.drop_index(name, table_name=_QUALIFICATION_TABLE)
    op.drop_table(_QUALIFICATION_TABLE)
