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
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "identity_provider",
            "external_subject",
            name="uq_users_identity_provider_subject",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("usr"))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identity_provider: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    external_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="user")
    batch_jobs: Mapped[list[BatchJob]] = relationship(back_populates="user")


class DesktopBridgeNonce(Base):
    """Durable one-use receipt for a verified desktop bridge request."""

    __tablename__ = "desktop_bridge_nonces"

    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    runtime_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class ApiIdempotencyRecord(Base):
    """Atomic receipt for one authenticated business mutation.

    The response is committed in the same transaction as the domain change.
    A retry can therefore replay the original result without executing the
    mutation again, including after the desktop application restarts.
    """

    __tablename__ = "api_idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key_hash",
            name="uq_api_idempotency_user_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: _new_id("idem"),
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="IN_PROGRESS",
        index=True,
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("bat"))
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED", index=True)
    # Monotonic fence for user-authored control commands. Worker progress does
    # not advance it; current status guards continue to serialize lifecycle
    # transitions without making normal polling invalidate a pending command.
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    baseline_parameter_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    advanced_scenario_config_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Versioned, extensible experiment definition.  The legacy flat columns
    # above remain populated for backwards-compatible filtering and clients.
    vehicle_profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    parameter_catalog_version: Mapped[str] = mapped_column(
        String(128), nullable=False, default="builtin-v1"
    )
    parameter_space_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    objective_config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    scenario_suite_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # State.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED", index=True)
    # Monotonic fence for user-authored control commands such as rename,
    # cancel, and delete. It is intentionally separate from worker progress.
    control_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    # Cross-process finalization fencing. The opaque token identifies one
    # exact claim; generation prevents a stale claim from crossing a dispatch
    # boundary, and the explicit expiry is renewable without overloading
    # ``updated_at`` with lease semantics.
    finalization_claim_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    finalization_claim_generation: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    finalization_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    openai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

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
    winner_freeze: Mapped[WinnerFreezeReceipt | None] = relationship(
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
    optimizer_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    evidence_ledger_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
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
    evidence_receipts: Mapped[list[CandidateEvidenceReceipt]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="CandidateEvidenceReceipt.revision",
    )


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
    accepted_attempt_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("trial_execution_attempts.id"),
        nullable=True,
        unique=True,
    )
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
    execution_attempts: Mapped[list[TrialExecutionAttempt]] = relationship(
        back_populates="trial",
        cascade="all, delete-orphan",
        foreign_keys="TrialExecutionAttempt.trial_id",
    )
    accepted_attempt: Mapped[TrialExecutionAttempt | None] = relationship(
        foreign_keys=[accepted_attempt_id],
        post_update=True,
        uselist=False,
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


class WinnerFreezeReceipt(Base):
    __tablename__ = "winner_freeze_receipts"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("wfr")
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, unique=True, index=True
    )
    receipt_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False, unique=True, index=True
    )
    outcome_contract_id: Mapped[str] = mapped_column(String(71), nullable=False)
    baseline_candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    winner_candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="winner_freeze")
    report: Mapped[JobReport | None] = relationship(
        back_populates="winner_freeze_receipt", uselist=False
    )


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
    winner_evidence_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    winner_freeze_receipt_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("winner_freeze_receipts.id"),
        nullable=True,
        unique=True,
    )
    report_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="report")
    winner_freeze_receipt: Mapped[WinnerFreezeReceipt | None] = relationship(
        back_populates="report"
    )


class WinnerFreezeDeleteAuthorization(Base):
    """Transaction-scoped authorization for winner-freeze lifecycle deletion."""

    __tablename__ = "winner_freeze_delete_authorizations"

    receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("winner_freeze_receipts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("art"))
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)  # job | trial
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Artifact logs and telemetry can legitimately exceed PostgreSQL's
    # 32-bit INTEGER ceiling. SQLite already stores 64-bit integers, while
    # BigInteger keeps the production schema portable and lossless.
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    integrity_policy: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    digest_receipt: Mapped[ArtifactDigestReceipt | None] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ArtifactDigestReceipt(Base):
    __tablename__ = "artifact_digest_receipts"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("adr")
    )
    artifact_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("artifacts.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False, unique=True, index=True
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    content_size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    storage_path_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    artifact: Mapped[Artifact] = relationship(
        back_populates="digest_receipt"
    )


class ArtifactDigestDeleteAuthorization(Base):
    """Transaction-scoped authorization for lifecycle deletion of a receipt."""

    __tablename__ = "artifact_digest_delete_authorizations"

    artifact_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class TrialExecutionAttempt(Base):
    """Immutable claim receipt for one physical execution of a logical Trial."""

    __tablename__ = "trial_execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "trial_id",
            "attempt_count",
            name="uq_trial_execution_attempts_trial_attempt",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trial_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("trials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    simulator_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False, unique=True, index=True
    )
    claim_evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    trial: Mapped[Trial] = relationship(
        back_populates="execution_attempts",
        foreign_keys=[trial_id],
    )
    outcome: Mapped[TrialExecutionAttemptOutcome | None] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TrialExecutionAttemptOutcome(Base):
    """Immutable terminal or superseded outcome for one execution attempt."""

    __tablename__ = "trial_execution_attempt_outcomes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("trial_execution_attempts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False, unique=True, index=True
    )
    terminal_status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_class: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    attempt: Mapped[TrialExecutionAttempt] = relationship(
        back_populates="outcome"
    )


class TrialExecutionAttemptDeleteAuthorization(Base):
    """Transaction-scoped authorization for lifecycle deletion of a ledger."""

    __tablename__ = "trial_execution_attempt_delete_authorizations"

    attempt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("trial_execution_attempts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


class CandidateEvidenceReceipt(Base):
    """Append-only Candidate outcome/report evidence-chain revision."""

    __tablename__ = "candidate_evidence_receipts"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "revision",
            name="uq_candidate_evidence_receipts_candidate_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("candidate_parameter_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_evidence_id: Mapped[str | None] = mapped_column(
        String(71), nullable=True
    )
    receipt_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False, unique=True, index=True
    )
    aggregate_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    outcome_evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False
    )
    report_evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False
    )
    outcome_evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    report_evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    candidate: Mapped[CandidateParameterSet] = relationship(
        back_populates="evidence_receipts"
    )


class CandidateEvidenceDeleteAuthorization(Base):
    """Transaction-scoped authorization for Candidate evidence deletion."""

    __tablename__ = "candidate_evidence_delete_authorizations"

    receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("candidate_evidence_receipts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
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
    "BatchJob",
    "CandidateEvidenceDeleteAuthorization",
    "CandidateEvidenceReceipt",
    "CandidateParameterSet",
    "Job",
    "JobEvent",
    "JobReport",
    "JobSecret",
    "Trial",
    "TrialExecutionAttempt",
    "TrialExecutionAttemptDeleteAuthorization",
    "TrialExecutionAttemptOutcome",
    "TrialMetric",
    "User",
    "WinnerFreezeDeleteAuthorization",
]
