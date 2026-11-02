"""Add immutable physical Trial execution-attempt receipts.

Revision ID: 20260726_0008
Revises: 20260726_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260726_0008"
down_revision = "20260726_0007"
branch_labels = None
depends_on = None

_ATTEMPT_UPDATE_TRIGGER = "trg_trial_execution_attempts_no_update"
_ATTEMPT_DELETE_TRIGGER = "trg_trial_execution_attempts_no_delete"
_OUTCOME_UPDATE_TRIGGER = "trg_trial_execution_attempt_outcomes_no_update"
_OUTCOME_DELETE_TRIGGER = "trg_trial_execution_attempt_outcomes_no_delete"
_ACCEPTED_ATTEMPT_TRIGGER = "trg_trials_accepted_attempt_immutable"
_POSTGRES_ATTEMPT_FUNCTION = (
    "dronedream_reject_trial_execution_attempt_mutation"
)
_POSTGRES_OUTCOME_FUNCTION = (
    "dronedream_reject_trial_execution_outcome_mutation"
)
_POSTGRES_ACCEPTED_FUNCTION = (
    "dronedream_guard_trial_accepted_attempt"
)


def upgrade() -> None:
    op.create_table(
        "trial_execution_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("trial_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id_sha256", sa.String(length=64), nullable=False),
        sa.Column("simulator_backend", sa.String(length=64), nullable=False),
        sa.Column("claim_evidence_id", sa.String(length=71), nullable=False),
        sa.Column("claim_evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["trial_id"],
            ["trials.id"],
            ondelete="CASCADE",
            name="fk_trial_execution_attempts_trial_id_trials",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trial_id",
            "attempt_count",
            name="uq_trial_execution_attempts_trial_attempt",
        ),
    )
    for column in ("trial_id", "job_id", "candidate_id"):
        op.create_index(
            f"ix_trial_execution_attempts_{column}",
            "trial_execution_attempts",
            [column],
        )
    op.create_index(
        "ix_trial_execution_attempts_claim_evidence_id",
        "trial_execution_attempts",
        ["claim_evidence_id"],
        unique=True,
    )

    op.create_table(
        "trial_execution_attempt_outcomes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=71), nullable=False),
        sa.Column("terminal_status", sa.String(length=32), nullable=False),
        sa.Column("outcome_class", sa.String(length=64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["trial_execution_attempts.id"],
            ondelete="CASCADE",
            name=(
                "fk_trial_execution_attempt_outcomes_attempt_id_"
                "trial_execution_attempts"
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trial_execution_attempt_outcomes_attempt_id",
        "trial_execution_attempt_outcomes",
        ["attempt_id"],
        unique=True,
    )
    op.create_index(
        "ix_trial_execution_attempt_outcomes_evidence_id",
        "trial_execution_attempt_outcomes",
        ["evidence_id"],
        unique=True,
    )
    op.create_table(
        "trial_execution_attempt_delete_authorizations",
        sa.Column("attempt_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["trial_execution_attempts.id"],
            ondelete="CASCADE",
            name=(
                "fk_trial_execution_attempt_delete_auth_attempt_id_"
                "trial_execution_attempts"
            ),
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
    )

    with op.batch_alter_table("trials") as batch_op:
        batch_op.add_column(
            sa.Column(
                "accepted_attempt_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_trials_accepted_attempt_id_trial_execution_attempts",
            "trial_execution_attempts",
            ["accepted_attempt_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_trials_accepted_attempt_id",
            ["accepted_attempt_id"],
        )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite_guards()
        return
    if dialect == "postgresql":
        _install_postgres_guards()
        return
    raise RuntimeError(
        "trial-attempt migration supports SQLite/PostgreSQL only"
    )


def _install_sqlite_guards() -> None:
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_ATTEMPT_UPDATE_TRIGGER}
        BEFORE UPDATE ON trial_execution_attempts
        BEGIN
            SELECT RAISE(
                ABORT,
                'trial execution attempts are append-only'
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_ATTEMPT_DELETE_TRIGGER}
        BEFORE DELETE ON trial_execution_attempts
        WHEN NOT EXISTS (
            SELECT 1
            FROM trial_execution_attempt_delete_authorizations
            WHERE attempt_id = OLD.id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'trial execution attempts are append-only'
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_OUTCOME_UPDATE_TRIGGER}
        BEFORE UPDATE ON trial_execution_attempt_outcomes
        BEGIN
            SELECT RAISE(
                ABORT,
                'trial execution attempt outcomes are append-only'
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_OUTCOME_DELETE_TRIGGER}
        BEFORE DELETE ON trial_execution_attempt_outcomes
        WHEN NOT EXISTS (
            SELECT 1
            FROM trial_execution_attempt_delete_authorizations
            WHERE attempt_id = OLD.attempt_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'trial execution attempt outcomes are append-only'
            );
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_ACCEPTED_ATTEMPT_TRIGGER}
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


def _install_postgres_guards() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {_POSTGRES_ATTEMPT_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1
                FROM trial_execution_attempt_delete_authorizations
                WHERE attempt_id = OLD.id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'trial execution attempts are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_ATTEMPT_UPDATE_TRIGGER}
        BEFORE UPDATE OR DELETE ON trial_execution_attempts
        FOR EACH ROW
        EXECUTE FUNCTION {_POSTGRES_ATTEMPT_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_POSTGRES_OUTCOME_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND EXISTS (
                SELECT 1
                FROM trial_execution_attempt_delete_authorizations
                WHERE attempt_id = OLD.attempt_id
            ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'trial execution attempt outcomes are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_OUTCOME_UPDATE_TRIGGER}
        BEFORE UPDATE OR DELETE ON trial_execution_attempt_outcomes
        FOR EACH ROW
        EXECUTE FUNCTION {_POSTGRES_OUTCOME_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_POSTGRES_ACCEPTED_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.accepted_attempt_id IS NOT NULL
               AND NEW.accepted_attempt_id IS DISTINCT FROM
                   OLD.accepted_attempt_id
               AND NOT EXISTS (
                    SELECT 1
                    FROM trial_execution_attempt_delete_authorizations
                    WHERE attempt_id = OLD.accepted_attempt_id
               ) THEN
                RAISE EXCEPTION
                    'accepted Trial execution attempt is immutable';
            END IF;
            IF NEW.accepted_attempt_id IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                    FROM trial_execution_attempts
                    WHERE id = NEW.accepted_attempt_id
                      AND trial_id = OLD.id
               ) THEN
                RAISE EXCEPTION
                    'accepted Trial execution attempt belongs to another Trial';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_ACCEPTED_ATTEMPT_TRIGGER}
        BEFORE UPDATE OF accepted_attempt_id ON trials
        FOR EACH ROW
        EXECUTE FUNCTION {_POSTGRES_ACCEPTED_FUNCTION}()
        """
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for trigger in (
            _ACCEPTED_ATTEMPT_TRIGGER,
            _OUTCOME_DELETE_TRIGGER,
            _OUTCOME_UPDATE_TRIGGER,
            _ATTEMPT_DELETE_TRIGGER,
            _ATTEMPT_UPDATE_TRIGGER,
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    elif dialect == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_ACCEPTED_ATTEMPT_TRIGGER} ON trials"
        )
        op.execute(
            f"DROP FUNCTION IF EXISTS {_POSTGRES_ACCEPTED_FUNCTION}()"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_OUTCOME_UPDATE_TRIGGER} "
            "ON trial_execution_attempt_outcomes"
        )
        op.execute(
            f"DROP FUNCTION IF EXISTS {_POSTGRES_OUTCOME_FUNCTION}()"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS {_ATTEMPT_UPDATE_TRIGGER} "
            "ON trial_execution_attempts"
        )
        op.execute(
            f"DROP FUNCTION IF EXISTS {_POSTGRES_ATTEMPT_FUNCTION}()"
        )
    else:
        raise RuntimeError(
            "trial-attempt migration supports SQLite/PostgreSQL only"
        )

    with op.batch_alter_table("trials") as batch_op:
        batch_op.drop_constraint(
            "uq_trials_accepted_attempt_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_trials_accepted_attempt_id_trial_execution_attempts",
            type_="foreignkey",
        )
        batch_op.drop_column("accepted_attempt_id")
    op.drop_table("trial_execution_attempt_delete_authorizations")
    op.drop_table("trial_execution_attempt_outcomes")
    op.drop_table("trial_execution_attempts")
