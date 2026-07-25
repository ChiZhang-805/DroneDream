"""Initial production schema.

Revision ID: 20260710_0001
Revises: None
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260710_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("identity_provider", sa.String(255), nullable=True),
        sa.Column("external_subject", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "identity_provider",
            "external_subject",
            name="uq_users_identity_provider_subject",
        ),
    )
    op.create_index("ix_users_identity_provider", "users", ["identity_provider"])
    op.create_index("ix_users_external_subject", "users", ["external_subject"])
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_batch_jobs_user_id", "batch_jobs", ["user_id"])
    op.create_index("ix_batch_jobs_status", "batch_jobs", ["status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("track_type", sa.String(32), nullable=False),
        sa.Column("start_point_x", sa.Float(), nullable=False),
        sa.Column("start_point_y", sa.Float(), nullable=False),
        sa.Column("altitude_m", sa.Float(), nullable=False),
        sa.Column("wind_north", sa.Float(), nullable=False),
        sa.Column("wind_east", sa.Float(), nullable=False),
        sa.Column("wind_south", sa.Float(), nullable=False),
        sa.Column("wind_west", sa.Float(), nullable=False),
        sa.Column("sensor_noise_level", sa.String(16), nullable=False),
        sa.Column("objective_profile", sa.String(16), nullable=False),
        sa.Column("reference_track_json", sa.JSON(), nullable=True),
        sa.Column("baseline_parameter_json", sa.JSON(), nullable=True),
        sa.Column("advanced_scenario_config_json", sa.JSON(), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("vehicle_profile_json", sa.JSON(), nullable=True),
        sa.Column("parameter_catalog_version", sa.String(128), nullable=False),
        sa.Column("parameter_space_json", sa.JSON(), nullable=True),
        sa.Column("objective_config_json", sa.JSON(), nullable=True),
        sa.Column("scenario_suite_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_phase", sa.String(64), nullable=True),
        sa.Column("progress_completed_trials", sa.Integer(), nullable=False),
        sa.Column("progress_total_trials", sa.Integer(), nullable=False),
        sa.Column("latest_error_code", sa.String(64), nullable=True),
        sa.Column("latest_error_message", sa.Text(), nullable=True),
        sa.Column("simulator_backend_requested", sa.String(32), nullable=False),
        sa.Column("optimizer_strategy", sa.String(32), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("trials_per_candidate", sa.Integer(), nullable=False),
        sa.Column("target_rmse", sa.Float(), nullable=True),
        sa.Column("target_max_error", sa.Float(), nullable=True),
        sa.Column("min_pass_rate", sa.Float(), nullable=False),
        sa.Column("max_total_trials", sa.Integer(), nullable=False),
        sa.Column("current_generation", sa.Integer(), nullable=False),
        sa.Column("optimization_outcome", sa.String(64), nullable=True),
        sa.Column("openai_model", sa.String(128), nullable=True),
        sa.Column("llm_provider", sa.String(64), nullable=True),
        sa.Column("llm_base_url", sa.String(2048), nullable=True),
        sa.Column("best_candidate_id", sa.String(64), nullable=True),
        sa.Column("baseline_candidate_id", sa.String(64), nullable=True),
        sa.Column("source_job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("batch_id", sa.String(64), sa.ForeignKey("batch_jobs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name in ("user_id", "status", "source_job_id", "batch_id"):
        op.create_index(f"ix_jobs_{name}", "jobs", [name])

    op.create_table(
        "candidate_parameter_sets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("generation_index", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("parameter_json", sa.JSON(), nullable=False),
        sa.Column("aggregated_score", sa.Float(), nullable=True),
        sa.Column("aggregated_metric_json", sa.JSON(), nullable=True),
        sa.Column("proposal_reason", sa.Text(), nullable=True),
        sa.Column("parent_candidate_id", sa.String(64), nullable=True),
        sa.Column("llm_response_json", sa.JSON(), nullable=True),
        sa.Column("trial_count", sa.Integer(), nullable=False),
        sa.Column("completed_trial_count", sa.Integer(), nullable=False),
        sa.Column("failed_trial_count", sa.Integer(), nullable=False),
        sa.Column("rank_in_job", sa.Integer(), nullable=True),
        sa.Column("is_best", sa.Boolean(), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_parameter_sets_job_id", "candidate_parameter_sets", ["job_id"]
    )

    op.create_table(
        "trials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "candidate_id",
            sa.String(64),
            sa.ForeignKey("candidate_parameter_sets.id"),
            nullable=False,
        ),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("scenario_type", sa.String(32), nullable=False),
        sa.Column("scenario_config_json", sa.JSON(), nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("simulator_backend", sa.String(64), nullable=True),
        sa.Column("log_excerpt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("job_id", "candidate_id", "status", "lease_owner", "lease_expires_at"):
        op.create_index(f"ix_trials_{name}", "trials", [name])

    op.create_table(
        "trial_metrics",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("trial_id", sa.String(64), sa.ForeignKey("trials.id"), nullable=False),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column("max_error", sa.Float(), nullable=True),
        sa.Column("overshoot_count", sa.Integer(), nullable=True),
        sa.Column("completion_time", sa.Float(), nullable=True),
        sa.Column("crash_flag", sa.Boolean(), nullable=False),
        sa.Column("timeout_flag", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("final_error", sa.Float(), nullable=True),
        sa.Column("pass_flag", sa.Boolean(), nullable=False),
        sa.Column("instability_flag", sa.Boolean(), nullable=False),
        sa.Column("raw_metric_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trial_metrics_trial_id", "trial_metrics", ["trial_id"], unique=True)

    op.create_table(
        "job_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("best_candidate_id", sa.String(64), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("baseline_metric_json", sa.JSON(), nullable=True),
        sa.Column("optimized_metric_json", sa.JSON(), nullable=True),
        sa.Column("comparison_metric_json", sa.JSON(), nullable=True),
        sa.Column("best_parameter_json", sa.JSON(), nullable=True),
        sa.Column("report_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_reports_job_id", "job_reports", ["job_id"], unique=True)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_owner_id", "artifacts", ["owner_id"])

    op.create_table(
        "job_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])

    op.create_table(
        "job_secrets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_job_secrets_job_id", "job_secrets", ["job_id"])


def downgrade() -> None:
    for table in (
        "job_secrets",
        "job_events",
        "artifacts",
        "job_reports",
        "trial_metrics",
        "trials",
        "candidate_parameter_sets",
        "jobs",
        "batch_jobs",
        "users",
    ):
        op.drop_table(table)
