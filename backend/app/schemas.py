"""Pydantic schemas for /api/v1 request and response shapes.

These mirror the frontend ``src/types/api.ts`` contract exactly — any change
here must be kept in sync there. The schemas are the source of truth for input
validation; unknown fields are rejected (``extra="forbid"``) per the API spec.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Enums / literals -------------------------------------------------------

TrackType = Literal["circle", "u_turn", "lemniscate"]
SensorNoiseLevel = Literal["low", "medium", "high"]
ObjectiveProfile = Literal["stable", "fast", "smooth", "robust", "custom"]
JobStatus = Literal[
    "CREATED",
    "QUEUED",
    "RUNNING",
    "AGGREGATING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]
TrialStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
ScenarioType = Literal["nominal", "noise_perturbed", "wind_perturbed", "combined_perturbed"]
ReportStatus = Literal["PENDING", "READY", "FAILED"]


JOB_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
JOB_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {"CREATED", "QUEUED", "RUNNING", "AGGREGATING"}
)


# --- Shared shapes ----------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartPoint(_Strict):
    x: float = 0.0
    y: float = 0.0


class WindVector(_Strict):
    north: Annotated[float, Field(ge=-10, le=10)] = 0.0
    east: Annotated[float, Field(ge=-10, le=10)] = 0.0
    south: Annotated[float, Field(ge=-10, le=10)] = 0.0
    west: Annotated[float, Field(ge=-10, le=10)] = 0.0


class JobProgress(BaseModel):
    completed_trials: int = 0
    total_trials: int = 0
    current_phase: str | None = None


class JobErrorInfo(BaseModel):
    code: str
    message: str


class JobEventInfo(BaseModel):
    """Single JobEvent row exposed on job detail for diagnostics.

    The payload is whatever was recorded at event time (may be ``None``).
    The frontend treats it as opaque JSON.
    """

    id: str
    event_type: str
    payload: dict[str, Any] | None = None
    created_at: datetime


# --- Requests ---------------------------------------------------------------


class JobCreateRequest(_Strict):
    """POST /api/v1/jobs body."""

    track_type: TrackType = "circle"
    start_point: StartPoint = Field(default_factory=StartPoint)
    altitude_m: Annotated[float, Field(ge=1.0, le=20.0)] = 3.0
    wind: WindVector = Field(default_factory=WindVector)
    sensor_noise_level: SensorNoiseLevel = "medium"
    objective_profile: ObjectiveProfile = "robust"


# --- Responses --------------------------------------------------------------


class Job(BaseModel):
    id: str
    track_type: TrackType
    start_point: StartPoint
    altitude_m: float
    wind: WindVector
    sensor_noise_level: SensorNoiseLevel
    objective_profile: ObjectiveProfile
    status: JobStatus
    progress: JobProgress
    baseline_candidate_id: str | None = None
    best_candidate_id: str | None = None
    source_job_id: str | None = None
    latest_error: JobErrorInfo | None = None
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    failed_at: datetime | None = None
    # Phase 6: recent JobEvent rows (capped, newest first) so the diagnostics
    # panel can render without a separate request. Empty list for jobs that
    # have not emitted any events yet.
    recent_events: list[JobEventInfo] = Field(default_factory=list)


class PaginatedJobs(BaseModel):
    items: list[Job]
    page: int
    page_size: int
    total: int


class TrialMetrics(BaseModel):
    rmse: float
    max_error: float
    overshoot_count: int
    completion_time: float
    crash_flag: bool
    timeout_flag: bool
    score: float
    final_error: float
    pass_flag: bool
    instability_flag: bool


CandidateSourceType = Literal["baseline", "optimizer"]


class TrialSummary(BaseModel):
    id: str
    candidate_id: str
    seed: int
    scenario_type: ScenarioType
    status: TrialStatus
    score: float | None = None
    # Phase 5: candidate metadata surfaced so the frontend can distinguish
    # baseline vs optimizer rows and highlight the best candidate without
    # needing a second API call.
    candidate_label: str | None = None
    candidate_source_type: CandidateSourceType | None = None
    candidate_is_baseline: bool = False
    candidate_is_best: bool = False
    candidate_generation_index: int = 0


class Trial(TrialSummary):
    job_id: str
    attempt_count: int
    worker_id: str | None = None
    simulator_backend: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    log_excerpt: str | None = None
    metrics: TrialMetrics | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AggregatedMetrics(BaseModel):
    rmse: float
    max_error: float
    overshoot_count: int
    completion_time: float
    score: float


class ComparisonPoint(BaseModel):
    metric: str
    label: str
    baseline: float
    optimized: float
    lower_is_better: bool
    unit: str | None = None


class JobReport(BaseModel):
    job_id: str
    best_candidate_id: str
    summary_text: str
    baseline_metrics: AggregatedMetrics
    optimized_metrics: AggregatedMetrics
    comparison: list[ComparisonPoint]
    best_parameters: dict[str, Any]
    report_status: ReportStatus
    created_at: datetime
    updated_at: datetime


class Artifact(BaseModel):
    id: str
    owner_type: str
    owner_id: str
    artifact_type: str
    display_name: str | None = None
    storage_path: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    created_at: datetime


__all__ = [
    "AggregatedMetrics",
    "Artifact",
    "ComparisonPoint",
    "JOB_CANCELLABLE_STATUSES",
    "JOB_TERMINAL_STATUSES",
    "Job",
    "JobCreateRequest",
    "JobErrorInfo",
    "JobEventInfo",
    "JobProgress",
    "JobReport",
    "ObjectiveProfile",
    "PaginatedJobs",
    "SensorNoiseLevel",
    "StartPoint",
    "TrackType",
    "Trial",
    "TrialMetrics",
    "TrialStatus",
    "TrialSummary",
    "WindVector",
]
