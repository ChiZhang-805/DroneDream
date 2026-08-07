"""add repeatable experiment defaults to user preferences

Revision ID: 20260807_0032
Revises: 20260805_0031
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0032"
down_revision: str | None = "20260805_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_experience_preferences") as batch_op:
        batch_op.add_column(sa.Column("default_objective_profile", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("default_optimizer_strategy", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("default_max_total_trials", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_user_experience_preferences_objective_profile",
            "default_objective_profile IS NULL OR default_objective_profile IN "
            "('stable', 'fast', 'smooth', 'robust', 'custom')",
        )
        batch_op.create_check_constraint(
            "ck_user_experience_preferences_optimizer_strategy",
            "default_optimizer_strategy IS NULL OR default_optimizer_strategy IN "
            "('none', 'heuristic', 'gpt', 'llm_harness', 'cma_es', "
            "'constrained_mobo', 'multi_fidelity_mobo', 'turbo', 'saasbo', "
            "'surrogate_cma_es', 'bipop_cma_es', 'optimizer_portfolio')",
        )
        batch_op.create_check_constraint(
            "ck_user_experience_preferences_trial_budget",
            "default_max_total_trials IS NULL OR "
            "(default_max_total_trials >= 1 AND default_max_total_trials <= 10000)",
        )


def downgrade() -> None:
    with op.batch_alter_table("user_experience_preferences") as batch_op:
        batch_op.drop_constraint(
            "ck_user_experience_preferences_trial_budget", type_="check"
        )
        batch_op.drop_constraint(
            "ck_user_experience_preferences_optimizer_strategy", type_="check"
        )
        batch_op.drop_constraint(
            "ck_user_experience_preferences_objective_profile", type_="check"
        )
        batch_op.drop_column("default_max_total_trials")
        batch_op.drop_column("default_optimizer_strategy")
        batch_op.drop_column("default_objective_profile")
