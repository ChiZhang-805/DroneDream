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
    CheckConstraint,
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
    benchmark_campaigns: Mapped[list[BenchmarkCampaign]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    harness_experiences: Mapped[list[HarnessExperienceMemory]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    experience_preferences: Mapped[UserExperiencePreferences | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )


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
    benchmark_binding: Mapped[BenchmarkCampaignBatchBinding | None] = relationship(
        back_populates="batch",
        uselist=False,
    )


class BenchmarkCampaign(Base):
    """Immutable preregistration manifest for a cross-Batch benchmark campaign."""

    __tablename__ = "benchmark_campaigns"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "campaign_key",
            "campaign_version",
            name="uq_benchmark_campaign_owner_key_version",
        ),
        CheckConstraint(
            "status IN ('PREREGISTERED', 'ACTIVE', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_benchmark_campaign_status",
        ),
        CheckConstraint(
            "job_cap >= 1 AND trial_cap >= 1 AND logical_turn_cap >= 0 "
            "AND network_request_cap >= 0 AND input_utf8_byte_cap >= 0 "
            "AND output_utf8_byte_cap >= 0 AND provider_token_cap >= 0 "
            "AND provider_cost_microusd_cap >= 0 AND wall_time_second_cap >= 1 "
            "AND disk_byte_cap >= 1",
            name="ck_benchmark_campaign_caps",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: _new_id("bmk"),
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_key: Mapped[str] = mapped_column(String(128), nullable=False)
    campaign_version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    panel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="PREREGISTERED",
        server_default="PREREGISTERED",
        index=True,
    )
    control_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    protocol_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    composite_inventory_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    composite_inventory_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    job_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    trial_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    logical_turn_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    network_request_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_utf8_byte_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_utf8_byte_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_token_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_cost_microusd_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wall_time_second_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    disk_byte_cap: Mapped[int] = mapped_column(BigInteger, nullable=False)
    preregistered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="benchmark_campaigns")
    arms: Mapped[list[BenchmarkArm]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="BenchmarkArm.benchmark_arm_id",
    )
    coordinator_state: Mapped[BenchmarkCampaignCoordinatorState | None] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        uselist=False,
    )
    budget_reservations: Mapped[list[BenchmarkBudgetReservation]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    batch_bindings: Mapped[list[BenchmarkCampaignBatchBinding]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="BenchmarkCampaignBatchBinding.batch_ordinal",
    )
    run_bindings: Mapped[list[BenchmarkCampaignRunBinding]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="BenchmarkCampaignRunBinding.run_ordinal",
    )


class BenchmarkArm(Base):
    """One server-registered proposal arm frozen into a campaign manifest."""

    __tablename__ = "benchmark_arms"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "benchmark_arm_id",
            name="uq_benchmark_arm_campaign_id",
        ),
        CheckConstraint(
            "arm_family IN ('traditional', 'llm_harness')",
            name="ck_benchmark_arm_family",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: _new_id("bar"),
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    benchmark_arm_id: Mapped[str] = mapped_column(String(128), nullable=False)
    arm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    arm_family: Mapped[str] = mapped_column(String(32), nullable=False)
    proposal_adapter_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluator_contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    execution_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    campaign: Mapped[BenchmarkCampaign] = relationship(back_populates="arms")
    run_bindings: Mapped[list[BenchmarkCampaignRunBinding]] = relationship(
        back_populates="arm"
    )


class BenchmarkCampaignCoordinatorState(Base):
    """Mutable, fenced coordinator state kept separate from frozen manifests."""

    __tablename__ = "benchmark_campaign_coordinator_states"
    __table_args__ = (
        CheckConstraint(
            "lease_generation >= 0 AND next_batch_ordinal >= 1 "
            "AND next_run_ordinal >= 1",
            name="ck_benchmark_coordinator_sequence",
        ),
        CheckConstraint(
            "jobs_used >= 0 AND trials_used >= 0 AND logical_turns_used >= 0 "
            "AND network_requests_used >= 0 AND input_utf8_bytes_used >= 0 "
            "AND output_utf8_bytes_used >= 0 AND provider_tokens_used >= 0 "
            "AND provider_cost_microusd_used >= 0 AND wall_time_seconds_used >= 0 "
            "AND disk_bytes_used >= 0",
            name="ck_benchmark_coordinator_usage_nonnegative",
        ),
    )

    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    lease_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    next_batch_ordinal: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    next_run_ordinal: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    jobs_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    trials_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    logical_turns_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    network_requests_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    input_utf8_bytes_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    output_utf8_bytes_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    provider_tokens_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    provider_cost_microusd_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    wall_time_seconds_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    disk_bytes_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    campaign: Mapped[BenchmarkCampaign] = relationship(back_populates="coordinator_state")


class BenchmarkBudgetReservation(Base):
    """Append-only idempotency and accounting receipt for consumed campaign work."""

    __tablename__ = "benchmark_budget_reservations"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "reservation_key",
            name="uq_benchmark_budget_reservation_key",
        ),
        CheckConstraint(
            "lease_generation >= 1 AND jobs >= 0 AND trials >= 0 "
            "AND logical_turns >= 0 AND network_requests >= 0 "
            "AND input_utf8_bytes >= 0 AND output_utf8_bytes >= 0 "
            "AND provider_tokens >= 0 AND provider_cost_microusd >= 0 "
            "AND wall_time_seconds >= 0 AND disk_bytes >= 0",
            name="ck_benchmark_budget_reservation_nonnegative",
        ),
        CheckConstraint(
            "jobs + trials + logical_turns + network_requests + input_utf8_bytes + "
            "output_utf8_bytes + provider_tokens + provider_cost_microusd + "
            "wall_time_seconds + disk_bytes > 0",
            name="ck_benchmark_budget_reservation_nonzero",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("bres")
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reservation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    reservation_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    jobs: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trials: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    logical_turns: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    network_requests: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    input_utf8_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_utf8_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    provider_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    provider_cost_microusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    wall_time_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    disk_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    campaign: Mapped[BenchmarkCampaign] = relationship(back_populates="budget_reservations")


class BenchmarkCampaignBatchBinding(Base):
    """Immutable link between one owned Batch and a campaign-global ordinal."""

    __tablename__ = "benchmark_campaign_batch_bindings"
    __table_args__ = (
        UniqueConstraint("campaign_id", "binding_key", name="uq_benchmark_batch_binding_key"),
        UniqueConstraint(
            "campaign_id",
            "batch_ordinal",
            name="uq_benchmark_batch_binding_ordinal",
        ),
        CheckConstraint(
            "batch_ordinal >= 1 AND lease_generation >= 1 "
            "AND job_count >= 1 AND job_count <= 50",
            name="ck_benchmark_batch_binding_ordinals",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("bbnd")
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("batch_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    binding_key: Mapped[str] = mapped_column(String(96), nullable=False)
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    batch_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_reservation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_budget_reservations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    campaign: Mapped[BenchmarkCampaign] = relationship(back_populates="batch_bindings")
    batch: Mapped[BatchJob] = relationship(back_populates="benchmark_binding")
    runs: Mapped[list[BenchmarkCampaignRunBinding]] = relationship(
        back_populates="batch_binding",
        cascade="all, delete-orphan",
        order_by="BenchmarkCampaignRunBinding.batch_run_ordinal",
    )


class BenchmarkCampaignRunBinding(Base):
    """Immutable Job/arm/seed provenance for one campaign run."""

    __tablename__ = "benchmark_campaign_run_bindings"
    __table_args__ = (
        UniqueConstraint("campaign_id", "run_key", name="uq_benchmark_run_binding_key"),
        UniqueConstraint(
            "campaign_id",
            "run_ordinal",
            name="uq_benchmark_run_binding_ordinal",
        ),
        UniqueConstraint(
            "batch_binding_id",
            "batch_run_ordinal",
            name="uq_benchmark_batch_run_ordinal",
        ),
        CheckConstraint(
            "run_ordinal >= 1 AND batch_run_ordinal >= 1 "
            "AND algorithm_seed >= 0 AND (provider_seed IS NULL OR provider_seed >= 0)",
            name="ck_benchmark_run_binding_ordinals",
        ),
        CheckConstraint(
            "provider_randomness_policy IN "
            "('not_applicable', 'fixed_seed', 'provider_managed')",
            name="ck_benchmark_run_provider_policy",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("brun")
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_binding_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaign_batch_bindings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    benchmark_arm_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_arms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    run_key: Mapped[str] = mapped_column(String(96), nullable=False)
    run_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    batch_run_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    algorithm_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    simulator_seed_block: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_randomness_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qualification_policy_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    scenario_suite_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    qualification_contract_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    campaign: Mapped[BenchmarkCampaign] = relationship(back_populates="run_bindings")
    batch_binding: Mapped[BenchmarkCampaignBatchBinding] = relationship(back_populates="runs")
    arm: Mapped[BenchmarkArm] = relationship(back_populates="run_bindings")
    job: Mapped[Job] = relationship(back_populates="benchmark_run_binding")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "continuation_parent_job_id",
            name="uq_jobs_continuation_parent_job_id",
        ),
        CheckConstraint(
            "provider_turn_cap >= 0 AND provider_turn_cap <= 128",
            name="ck_jobs_provider_turn_cap",
        ),
        CheckConstraint(
            "provider_turns_attempted >= 0 "
            "AND provider_turns_succeeded >= 0 "
            "AND provider_turns_succeeded <= provider_turns_attempted",
            name="ck_jobs_provider_turn_counts",
        ),
        CheckConstraint(
            "provider_request_cap >= 0 AND provider_request_cap <= 256",
            name="ck_jobs_provider_request_cap",
        ),
        CheckConstraint(
            "provider_max_retries >= 0 AND provider_max_retries <= 5",
            name="ck_jobs_provider_max_retries",
        ),
        CheckConstraint(
            "provider_requests_attempted >= 0 "
            "AND provider_requests_succeeded >= 0 "
            "AND provider_requests_succeeded <= provider_requests_attempted",
            name="ck_jobs_provider_request_counts",
        ),
        CheckConstraint(
            "next_candidate_dispatch_ordinal >= 1",
            name="ck_jobs_next_candidate_dispatch_ordinal",
        ),
        CheckConstraint(
            "next_qualification_sequence >= 1",
            name="ck_jobs_next_qualification_sequence",
        ),
    )

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
    # Versioned completion/cognition policy. Legacy rows are migrated to the
    # safe default: stop after the first fully-qualified candidate.
    completion_policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="first_qualified_stop",
        server_default="first_qualified_stop",
    )
    job_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="primary",
        server_default="primary",
    )
    cognitive_policy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="adaptive-2-4-v1",
        server_default="adaptive-2-4-v1",
    )
    provider_turn_cap: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=64,
        server_default="64",
    )
    provider_turns_attempted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    provider_turns_succeeded: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    provider_request_cap: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=128,
        server_default="128",
    )
    provider_max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    provider_requests_attempted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    provider_requests_succeeded: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    next_candidate_dispatch_ordinal: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    next_qualification_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    first_qualified_candidate_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    first_qualified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    continue_exploration_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    exploration_budget_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    continuation_parent_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=True, index=True
    )
    continuation_root_job_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=True, index=True
    )
    holdout_policy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="legacy-visible-v0",
        server_default="legacy-visible-v0",
    )
    holdout_contract_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
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
    llm_access_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    first_qualified_freeze: Mapped[FirstQualifiedFreezeReceipt | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )
    cognitive_turn_receipts: Mapped[list[HarnessCognitiveTurnReceipt]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    benchmark_direct_proposal_handoffs: Mapped[
        list[BenchmarkDirectProposalHandoff]
    ] = relationship(back_populates="job", cascade="all, delete-orphan")
    events: Mapped[list[JobEvent]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    secrets: Mapped[list[JobSecret]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    harness_experiences: Mapped[list[HarnessExperienceMemory]] = relationship(
        back_populates="source_job",
        cascade="all, delete-orphan",
    )
    batch: Mapped[BatchJob | None] = relationship(back_populates="jobs")
    benchmark_run_binding: Mapped[BenchmarkCampaignRunBinding | None] = relationship(
        back_populates="job",
        uselist=False,
    )
    candidate_qualifications: Mapped[list[CandidateQualification]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class CandidateParameterSet(Base):
    __tablename__ = "candidate_parameter_sets"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "dispatch_ordinal",
            name="uq_candidate_job_dispatch_ordinal",
        ),
        UniqueConstraint(
            "job_id",
            "qualification_sequence",
            name="uq_candidate_job_qualification_sequence",
        ),
        CheckConstraint(
            "dispatch_ordinal IS NULL OR dispatch_ordinal >= 1",
            name="ck_candidate_dispatch_ordinal",
        ),
        CheckConstraint(
            "qualification_sequence IS NULL OR qualification_sequence >= 1",
            name="ck_candidate_qualification_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("cand"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    generation_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Assigned by the server under the Job fence. These values, never UUID or
    # client arrival order, define deterministic dispatch/qualification order.
    dispatch_ordinal: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qualification_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    qualified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    qualification: Mapped[CandidateQualification | None] = relationship(
        back_populates="candidate",
        uselist=False,
    )


class CandidateQualification(Base):
    """Versioned two-stage screening and sealed qualification state.

    Training/validation acceptance is deliberately not stored here.  This row
    starts only after a candidate has been selected for the preregistered
    screening gate, and it binds all later Trial receipts to one sealed holdout
    contract without exposing holdout outcomes to proposal generation.
    """

    __tablename__ = "candidate_qualifications"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_candidate_qualification_candidate"),
        UniqueConstraint(
            "job_id",
            "qualification_sequence",
            name="uq_candidate_qualification_job_sequence",
        ),
        CheckConstraint(
            "state IN ("
            "'pending_screening', 'screening', 'screening_failed', "
            "'sealed_qualification', 'qualification_10', "
            "'qualification_extended_20', 'qualified', "
            "'qualification_failed', 'indeterminate', 'cancelled'"
            ")",
            name="ck_candidate_qualification_state",
        ),
        CheckConstraint(
            "state_revision >= 1 AND screening_required = 4 "
            "AND qualification_initial_required = 10 "
            "AND qualification_extended_required = 20 "
            "AND direct_pass_min = 9 AND extension_trigger_passes = 8 "
            "AND extended_pass_min = 18 AND max_candidates_per_run = 2",
            name="ck_candidate_qualification_rule_v1",
        ),
        CheckConstraint(
            "qualification_sequence IS NULL OR qualification_sequence >= 1",
            name="ck_candidate_qualification_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("qlf")
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("candidate_parameter_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    holdout_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selection_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_screening", index=True
    )
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    qualification_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    screening_required: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    qualification_initial_required: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10
    )
    qualification_extended_required: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20
    )
    direct_pass_min: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    extension_trigger_passes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8
    )
    extended_pass_min: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    max_candidates_per_run: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    sealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="candidate_qualifications")
    candidate: Mapped[CandidateParameterSet] = relationship(back_populates="qualification")
    trials: Mapped[list[Trial]] = relationship(back_populates="qualification")
    trial_receipts: Mapped[list[QualificationTrialReceipt]] = relationship(
        back_populates="qualification",
        cascade="all, delete-orphan",
        order_by="QualificationTrialReceipt.ordinal",
    )


class Trial(Base):
    __tablename__ = "trials"
    __table_args__ = (
        UniqueConstraint(
            "qualification_id",
            "evaluation_phase",
            "qualification_ordinal",
            name="uq_trial_qualification_phase_ordinal",
        ),
        CheckConstraint(
            "(evaluation_phase = 'optimization' "
            "AND qualification_id IS NULL AND qualification_ordinal IS NULL) OR "
            "(evaluation_phase = 'screening' "
            "AND qualification_id IS NOT NULL "
            "AND qualification_ordinal >= 1 AND qualification_ordinal <= 4) OR "
            "(evaluation_phase = 'qualification' "
            "AND qualification_id IS NOT NULL "
            "AND qualification_ordinal >= 1 AND qualification_ordinal <= 20)",
            name="ck_trial_evaluation_phase_binding",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("tri"))
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("candidate_parameter_sets.id"), nullable=False, index=True
    )
    qualification_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("candidate_qualifications.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    evaluation_phase: Mapped[str] = mapped_column(
        String(32), nullable=False, default="optimization", server_default="optimization"
    )
    qualification_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    qualification: Mapped[CandidateQualification | None] = relationship(
        back_populates="trials"
    )
    qualification_receipt: Mapped[QualificationTrialReceipt | None] = relationship(
        back_populates="trial",
        uselist=False,
    )
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


class QualificationTrialReceipt(Base):
    """Append-only terminal evidence for one screening/qualification Trial."""

    __tablename__ = "qualification_trial_receipts"
    __table_args__ = (
        UniqueConstraint("trial_id", name="uq_qualification_trial_receipt_trial"),
        UniqueConstraint(
            "qualification_id",
            "phase",
            "ordinal",
            name="uq_qualification_trial_receipt_phase_ordinal",
        ),
        CheckConstraint(
            "phase IN ('screening', 'qualification')",
            name="ck_qualification_trial_receipt_phase",
        ),
        CheckConstraint(
            "(phase = 'screening' AND ordinal >= 1 AND ordinal <= 4) OR "
            "(phase = 'qualification' AND ordinal >= 1 AND ordinal <= 20)",
            name="ck_qualification_trial_receipt_ordinal",
        ),
        CheckConstraint(
            "terminal_status IN ("
            "'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'INDETERMINATE'"
            ")",
            name="ck_qualification_trial_receipt_terminal_status",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("qtr")
    )
    qualification_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("candidate_qualifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trial_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("trials.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receipt_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    terminal_status: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    safety_critical_failure: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effect_readback_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        String(71), nullable=False, unique=True, index=True
    )
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    qualification: Mapped[CandidateQualification] = relationship(
        back_populates="trial_receipts"
    )
    trial: Mapped[Trial] = relationship(back_populates="qualification_receipt")


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


class FirstQualifiedFreezeReceipt(Base):
    """Insert-once receipt for the first fully-qualified candidate.

    Database guards reject mutation, while orchestration freezes the row under
    the Job finalization fence without overloading the final winner receipt.
    """

    __tablename__ = "first_qualified_freeze_receipts"
    __table_args__ = (
        CheckConstraint(
            "qualification_sequence >= 1 AND generation_index >= 0 "
            "AND dispatch_ordinal >= 1 AND time_to_first_qualified_ms >= 0",
            name="ck_first_qualified_order_and_time",
        ),
        CheckConstraint(
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
            "<= provider_turns_attempted_to_first_qualified "
            "AND provider_requests_attempted_to_first_qualified >= 0 "
            "AND provider_requests_succeeded_to_first_qualified >= 0 "
            "AND provider_requests_succeeded_to_first_qualified "
            "<= provider_requests_attempted_to_first_qualified",
            name="ck_first_qualified_nonnegative_accounting",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("fqf")
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, unique=True, index=True
    )
    # The server verifies this identifier against the same Job transaction.
    # It deliberately mirrors WinnerFreezeReceipt rather than adding a
    # candidate FK that would make whole-Job deletion cyclic.
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    receipt_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    holdout_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    qualification_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dispatch_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time_to_first_qualified_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    simulations_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_completed_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_passed_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_failed_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_cancelled_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_timed_out_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    trials_indeterminate_to_first_qualified: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    generations_to_first_qualified: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_turns_attempted_to_first_qualified: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    provider_turns_succeeded_to_first_qualified: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    provider_requests_attempted_to_first_qualified: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    provider_requests_succeeded_to_first_qualified: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="first_qualified_freeze")


class HarnessCognitiveTurnReceipt(Base):
    """Append-only pre-provider-call receipt.

    The row is committed before network I/O. Absence of a matching outcome is
    therefore an indeterminate attempted turn that still consumes the cap.
    """

    __tablename__ = "harness_cognitive_turn_receipts"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "generation_index",
            "turn_index",
            name="uq_harness_turn_job_generation_index",
        ),
        CheckConstraint(
            "generation_index >= 0",
            name="ck_harness_turn_generation",
        ),
        CheckConstraint(
            "turn_index >= 1 AND turn_index <= 4",
            name="ck_harness_turn_index",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("htr")
    )
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("jobs.id"), nullable=False, index=True
    )
    receipt_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    generation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_role: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    model_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_outputs_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="cognitive_turn_receipts")
    outcome: Mapped[HarnessCognitiveTurnOutcome | None] = relationship(
        back_populates="turn_receipt", cascade="all, delete-orphan", uselist=False
    )
    network_requests: Mapped[list[ProviderNetworkRequestReceipt]] = relationship(
        back_populates="turn_receipt",
        cascade="all, delete-orphan",
    )


class HarnessCognitiveTurnOutcome(Base):
    """Append-only terminal outcome for one attempted cognitive turn."""

    __tablename__ = "harness_cognitive_turn_outcomes"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("hto")
    )
    turn_receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("harness_cognitive_turn_receipts.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    outcome_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    turn_receipt: Mapped[HarnessCognitiveTurnReceipt] = relationship(
        back_populates="outcome"
    )


class BenchmarkDirectProposalHandoff(Base):
    """Durable, secret-free handoff from one paid direct turn to dispatch.

    The row is committed atomically with the successful cognitive outcome. It
    contains only schema-validated numeric parameters and provenance hashes;
    raw prompts, raw provider responses, credentials, and provider request IDs
    are deliberately excluded. A worker may therefore recover the exact
    proposal after a crash without replaying paid provider I/O.
    """

    __tablename__ = "benchmark_direct_proposal_handoffs"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "generation_index",
            name="uq_benchmark_direct_handoff_job_generation",
        ),
        UniqueConstraint(
            "cognitive_turn_receipt_id",
            name="uq_benchmark_direct_handoff_turn",
        ),
        CheckConstraint(
            "generation_index >= 1 AND dispatch_ordinal >= 1",
            name="ck_benchmark_direct_handoff_ordinals",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("bdph")
    )
    job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_binding_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("benchmark_campaign_run_bindings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    cognitive_turn_receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("harness_cognitive_turn_receipts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    handoff_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    generation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dispatch_ordinal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    turn_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    parameter_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposal_receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    job: Mapped[Job] = relationship(
        back_populates="benchmark_direct_proposal_handoffs"
    )


class ProviderNetworkRequestReceipt(Base):
    """Append-only receipt committed immediately before one HTTP request.

    The row deliberately excludes credentials, provider request identifiers,
    and raw prompt/chat content. One cognitive turn may have more than one row
    only when a separately bounded retry or compatibility fallback is actually
    sent over the network.
    """

    __tablename__ = "provider_network_request_receipts"
    __table_args__ = (
        UniqueConstraint(
            "cognitive_turn_receipt_id",
            "request_index",
            name="uq_provider_request_turn_index",
        ),
        CheckConstraint(
            "request_index >= 1 AND request_index <= 8",
            name="ck_provider_request_index",
        ),
        CheckConstraint(
            "request_kind IN ('primary', 'retry', 'compatibility_fallback')",
            name="ck_provider_request_kind",
        ),
        CheckConstraint(
            "input_utf8_bytes >= 0",
            name="ck_provider_request_input_bytes",
        ),
        CheckConstraint(
            "temperature IS NULL OR (temperature >= 0 AND temperature <= 2)",
            name="ck_provider_request_temperature",
        ),
        CheckConstraint(
            "top_p IS NULL OR (top_p > 0 AND top_p <= 1)",
            name="ck_provider_request_top_p",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("pnr")
    )
    cognitive_turn_receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("harness_cognitive_turn_receipts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receipt_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    request_index: Mapped[int] = mapped_column(Integer, nullable=False)
    request_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    retry_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    api_surface: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False)
    base_url_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    response_schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_outputs_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_utf8_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    price_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    turn_receipt: Mapped[HarnessCognitiveTurnReceipt] = relationship(
        back_populates="network_requests"
    )
    outcome: Mapped[ProviderNetworkRequestOutcome | None] = relationship(
        back_populates="request_receipt",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ProviderNetworkRequestOutcome(Base):
    """Append-only terminal outcome for one actual provider HTTP request."""

    __tablename__ = "provider_network_request_outcomes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'indeterminate')",
            name="ck_provider_request_outcome_status",
        ),
        CheckConstraint(
            "output_utf8_bytes >= 0 AND latency_ms >= 0",
            name="ck_provider_request_outcome_bytes_latency",
        ),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0) "
            "AND (total_tokens IS NULL OR total_tokens >= 0) "
            "AND (provider_cost_microusd IS NULL OR provider_cost_microusd >= 0)",
            name="ck_provider_request_outcome_usage",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: _new_id("pno")
    )
    request_receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("provider_network_request_receipts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    outcome_schema: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_utf8_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_cost_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    request_receipt: Mapped[ProviderNetworkRequestReceipt] = relationship(
        back_populates="outcome"
    )


class HarnessCognitiveTurnDeleteAuthorization(Base):
    """Transaction-scoped authorization for cognitive receipt Job deletion."""

    __tablename__ = "harness_cognitive_turn_delete_authorizations"

    receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("harness_cognitive_turn_receipts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
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


class FirstQualifiedFreezeDeleteAuthorization(Base):
    """Transaction-scoped authorization for first-qualified lifecycle deletion."""

    __tablename__ = "first_qualified_freeze_delete_authorizations"

    receipt_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("first_qualified_freeze_receipts.id", ondelete="CASCADE"),
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


class HarnessExperienceMemory(Base):
    """Revocable, bounded cross-Job Harness experience.

    Rows contain only closed structured observations compiled from verified
    Harness decision/cohort receipts. Provider-visible projections never expose
    the ownership/source identifiers or the internal receipt binding.
    """

    __tablename__ = "harness_experience_memories"
    __table_args__ = (
        UniqueConstraint(
            "source_job_id",
            "source_generation",
            name="uq_harness_experience_source_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: _new_id("hexp"),
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_evidence_schema_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    source_prompt_template_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    source_tool_registry_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    source_eligibility_policy_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    task_family_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    scenario_profile_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    dispatched_candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_outcome_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    source_receipt_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="harness_experiences")
    source_job: Mapped[Job] = relationship(back_populates="harness_experiences")


class UserExperiencePreferences(Base):
    """Minimal, explicit per-user defaults and cross-Job memory consent."""

    __tablename__ = "user_experience_preferences"

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    default_template_key: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    default_track_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    default_altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="experience_preferences")


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
    "BenchmarkArm",
    "BenchmarkDirectProposalHandoff",
    "BenchmarkBudgetReservation",
    "BenchmarkCampaign",
    "BenchmarkCampaignCoordinatorState",
    "BatchJob",
    "CandidateEvidenceDeleteAuthorization",
    "CandidateEvidenceReceipt",
    "CandidateParameterSet",
    "FirstQualifiedFreezeDeleteAuthorization",
    "FirstQualifiedFreezeReceipt",
    "HarnessCognitiveTurnDeleteAuthorization",
    "HarnessCognitiveTurnOutcome",
    "HarnessCognitiveTurnReceipt",
    "HarnessExperienceMemory",
    "Job",
    "JobEvent",
    "JobReport",
    "JobSecret",
    "ProviderNetworkRequestOutcome",
    "ProviderNetworkRequestReceipt",
    "Trial",
    "TrialExecutionAttempt",
    "TrialExecutionAttemptDeleteAuthorization",
    "TrialExecutionAttemptOutcome",
    "TrialMetric",
    "User",
    "WinnerFreezeDeleteAuthorization",
]
