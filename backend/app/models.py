"""SQLAlchemy ORM models for DroneDream.

Phase 2 models cover the full domain surface from docs/05_DATA_MODEL.md so the
worker and optimizer phases can plug in without schema churn. Only the fields
the Phase 2 API reads or writes are used today; the rest are persisted-ready.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("usr"))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="user")
    batch_jobs: Mapped[list[BatchJob]] = relationship(back_populates="user")


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("bat"))
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="batch_jobs")
    jobs: Mapped[list[Job]] = relationship(back_populates="batch")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("job"))
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )

    # Configuration (flat columns — high-query fields should not be buried in JSON).
    track_type: Mapped[str] = mapped_column(String(32), nullable=False)
    start_point_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    start_point_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    altitude_m: Mapped[float] = mapped_column(Float, nullable=False)
    wind_north: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wind_east: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wind_south: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    wind_west: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sensor_noise_level: Mapped[str] = mapped_column(String(16), nullable=False)
    objective_profile: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_track_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    advanced_scenario_config_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )

    # State.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED", index=True)
    current_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_completed_trials: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total_trials: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phase 8: backend/auto-tuning configuration.
    simulator_backend_requested: Mapped[str] = mapped_column(
        String(32), nullable=False, default="mock"
    )
    optimizer_strategy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="heuristic"
    )
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    trials_per_candidate: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    target_rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_max_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_pass_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    max_total_trials: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    current_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    optimization_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    openai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relational pointers.
    best_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    baseline_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=True, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("batch_jobs.id"), nullable=True, index=True
    )

    # Timestamps.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="jobs")
    candidates: Mapped[list[CandidateParameterSet]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    trials: Mapped[list[Trial]] = relationship(back_populates="job", cascade="all, delete-orphan")
    report: Mapped[JobReport | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    events: Mapped[list[JobEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    secrets: Mapped[list[JobSecret]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    batch: Mapped[BatchJob | None] = relationship(back_populates="jobs")


class CandidateParameterSet(Base):
    __tablename__ = "candidate_parameter_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("cand"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    generation_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="baseline")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parameter_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    aggregated_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggregated_metric_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    proposal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trial_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_trial_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_trial_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rank_in_job: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_best: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="candidates")
    trials: Mapped[list[Trial]] = relationship(back_populates="candidate")


class Trial(Base):
    __tablename__ = "trials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("tri"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("candidate_parameter_sets.id"), nullable=False, index=True
    )
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenario_type: Mapped[str] = mapped_column(String(32), nullable=False, default="nominal")
    scenario_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    simulator_backend: Mapped[str | None] = mapped_column(String(64), nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="trials")
    candidate: Mapped[CandidateParameterSet] = relationship(back_populates="trials")
    metric: Mapped[TrialMetric | None] = relationship(
        back_populates="trial", cascade="all, delete-orphan", uselist=False
    )


class TrialMetric(Base):
    __tablename__ = "trial_metrics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("tm"))
    trial_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("trials.id"), nullable=False, unique=True, index=True
    )
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    overshoot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    crash_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instability_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_metric_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    trial: Mapped[Trial] = relationship(back_populates="metric")


class JobReport(Base):
    __tablename__ = "job_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("rep"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, unique=True, index=True
    )
    best_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_metric_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    optimized_metric_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    comparison_metric_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    best_parameter_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    report_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="report")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("art"))
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)  # job | trial
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("evt"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="events")


class JobSecret(Base):
    """Per-job encrypted secret (currently only OpenAI API keys)."""

    __tablename__ = "job_secrets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("sec"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="openai")
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="secrets")


__all__ = [
    "Artifact",
    "CandidateParameterSet",
    "Job",
    "JobEvent",
    "JobReport",
    "JobSecret",
    "Trial",
    "TrialMetric",
    "User",
]
