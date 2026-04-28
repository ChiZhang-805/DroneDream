"""Pydantic schemas for /api/v1 request and response shapes.

These mirror the frontend ``src/types/api.ts`` contract exactly — any change
here must be kept in sync there. The schemas are the source of truth for input
validation; unknown fields are rejected (``extra="forbid"``) per the API spec.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Enums / literals -------------------------------------------------------

TrackType = Literal["circle", "u_turn", "lemniscate", "custom"]
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
SimulatorBackend = Literal["mock", "real_cli"]
OptimizerStrategy = Literal["heuristic", "gpt", "cma_es"]
OptimizationOutcome = Literal[
    "success",
    "max_iterations_reached",
    "no_usable_candidate",
    "simulator_unavailable",
    "llm_failed",
]
BatchStatus = Literal[
    "CREATED",
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]


JOB_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
JOB_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {"CREATED", "QUEUED", "RUNNING", "AGGREGATING"}
)
BATCH_TERMINAL_STATUSES: frozenset[str] = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


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


class AcceptanceCriteria(_Strict):
    target_rmse: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    target_max_error: Annotated[float, Field(ge=0.0, le=100.0)] | None = None
    min_pass_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 0.8


class OpenAIConfig(_Strict):
    api_key: str = Field(min_length=1, max_length=512)
    model: str | None = Field(default=None, max_length=128)


class TrackPoint(_Strict):
    x: float
    y: float
    z: float | None = None


class WindGustsConfig(_Strict):
    enabled: bool = False
    magnitude_mps: Annotated[float, Field(ge=0.0, le=30.0)] = 0.0
    direction_deg: Annotated[float, Field(ge=0.0, lt=360.0)] = 0.0
    period_s: Annotated[float, Field(gt=0.0, le=300.0)] = 10.0


class ObstacleConfig(_Strict):
    type: Literal["cylinder", "box"]
    x: float
    y: float
    z: float
    radius: Annotated[float, Field(gt=0.0)] | None = None
    size_x: Annotated[float, Field(gt=0.0)] | None = None
    size_y: Annotated[float, Field(gt=0.0)] | None = None
    size_z: Annotated[float, Field(gt=0.0)] | None = None
    height: Annotated[float, Field(gt=0.0)] | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> ObstacleConfig:
        if self.type == "cylinder":
            if self.radius is None:
                raise ValueError("cylinder obstacle requires radius")
            if self.height is None:
                raise ValueError("cylinder obstacle requires height")
        if self.type == "box" and (
            self.size_x is None or self.size_y is None or self.size_z is None
        ):
            raise ValueError("box obstacle requires size_x/size_y/size_z")
        return self


class SensorDegradationConfig(_Strict):
    gps_noise_m: Annotated[float, Field(ge=0.0, le=100.0)] = 0.0
    baro_noise_m: Annotated[float, Field(ge=0.0, le=100.0)] = 0.0
    imu_noise_scale: Annotated[float, Field(ge=0.0, le=10.0)] = 1.0
    dropout_rate: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0


class BatteryConfig(_Strict):
    initial_percent: Annotated[float, Field(ge=0.0, le=100.0)] = 100.0
    voltage_sag: bool = False
    mass_payload_kg: Annotated[float, Field(ge=0.0, le=20.0)] | None = None


class AdvancedScenarioConfig(_Strict):
    wind_gusts: WindGustsConfig = Field(default_factory=WindGustsConfig)
    obstacles: list[ObstacleConfig] = Field(default_factory=list)
    sensor_degradation: SensorDegradationConfig = Field(default_factory=SensorDegradationConfig)
    battery: BatteryConfig = Field(default_factory=BatteryConfig)


ScenarioAdvancedConfig = AdvancedScenarioConfig


class JobCreateRequest(_Strict):
    """POST /api/v1/jobs body."""

    track_type: TrackType = "circle"
    start_point: StartPoint = Field(default_factory=StartPoint)
    altitude_m: Annotated[float, Field(ge=1.0, le=20.0)] = 3.0
    wind: WindVector = Field(default_factory=WindVector)
    sensor_noise_level: SensorNoiseLevel = "medium"
    objective_profile: ObjectiveProfile = "robust"
    reference_track: list[TrackPoint] | None = None
    advanced_scenario_config: AdvancedScenarioConfig | None = None

    simulator_backend: SimulatorBackend = "mock"
    optimizer_strategy: OptimizerStrategy = "gpt"
    max_iterations: Annotated[int, Field(ge=1, le=20)] = 20
    trials_per_candidate: Annotated[int, Field(ge=1, le=10)] = 3
    max_total_trials: Annotated[int, Field(ge=1, le=1000)] = 100
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    openai: OpenAIConfig | None = None

    @model_validator(mode="after")
    def _validate_custom_reference_track(self) -> JobCreateRequest:
        points = self.reference_track or []
        if self.track_type == "custom" and len(points) < 2:
            raise ValueError(
                "reference_track with at least 2 points is required when track_type=custom"
            )
        for idx, point in enumerate(points):
            if not math.isfinite(point.x) or not math.isfinite(point.y):
                raise ValueError(f"reference_track[{idx}] x/y must be finite numbers")
            if point.z is not None and not math.isfinite(point.z):
                raise ValueError(f"reference_track[{idx}].z must be a finite number")
        return self


class BatchCreateRequest(_Strict):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = Field(default=None, max_length=2000)
    jobs: Annotated[list[JobCreateRequest], Field(min_length=1, max_length=50)]


# --- Responses --------------------------------------------------------------


class Job(BaseModel):
    id: str
    track_type: TrackType
    start_point: StartPoint
    altitude_m: float
    wind: WindVector
    sensor_noise_level: SensorNoiseLevel
    objective_profile: ObjectiveProfile
    reference_track: list[TrackPoint] | None = None
    advanced_scenario_config: AdvancedScenarioConfig | None = None
    status: JobStatus
    progress: JobProgress
    baseline_candidate_id: str | None = None
    best_candidate_id: str | None = None
    source_job_id: str | None = None
    batch_id: str | None = None
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
    # Phase 8: auto-tuning configuration + progress.
    simulator_backend_requested: SimulatorBackend = "mock"
    optimizer_strategy: OptimizerStrategy = "gpt"
    max_iterations: int = 20
    trials_per_candidate: int = 3
    max_total_trials: int = 100
    acceptance_criteria: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    current_generation: int = 0
    optimization_outcome: OptimizationOutcome | None = None
    openai_model: str | None = None


class PaginatedJobs(BaseModel):
    items: list[Job]
    page: int
    page_size: int
    total: int


class BatchProgress(BaseModel):
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    running_jobs: int
    queued_jobs: int
    created_jobs: int
    terminal_jobs: int


class BatchJob(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: BatchStatus
    progress: BatchProgress
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class PaginatedBatchJobs(BaseModel):
    items: list[BatchJob]
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


CandidateSourceType = Literal["baseline", "optimizer", "llm_optimizer"]


class TrialSummary(BaseModel):
    id: str
    candidate_id: str
    seed: int
    scenario_type: ScenarioType
    status: TrialStatus
    score: float | None = None
    # Phase 8 polish: per-trial pass/fail surfaced on the trial list so the
    # Job Detail table can render PASS / FAIL alongside the COMPLETED status.
    # ``None`` means "no metric yet" (queued/running/failed-without-metrics).
    pass_flag: bool | None = None
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


class JobRerunRequest(_Strict):
    """POST /api/v1/jobs/{job_id}/rerun body."""

    openai: OpenAIConfig | None = None


class JobsCompareRequest(_Strict):
    job_ids: list[str] = Field(min_length=2, max_length=10)


class JobCompareItem(BaseModel):
    job_id: str
    status: JobStatus
    track_type: TrackType
    simulator_backend: SimulatorBackend
    optimizer_strategy: OptimizerStrategy
    optimization_outcome: OptimizationOutcome | None = None
    baseline_metrics: dict[str, Any] | None = None
    optimized_metrics: dict[str, Any] | None = None
    best_candidate_id: str | None = None
    best_parameters: dict[str, Any] = Field(default_factory=dict)
    trial_count: int
    completed_trial_count: int
    failed_trial_count: int
    created_at: datetime
    completed_at: datetime | None = None


class JobsCompareResponse(BaseModel):
    items: list[JobCompareItem]


__all__ = [
    "AcceptanceCriteria",
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
    "OpenAIConfig",
    "OptimizationOutcome",
    "OptimizerStrategy",
    "PaginatedJobs",
    "SensorNoiseLevel",
    "AdvancedScenarioConfig",
    "ScenarioAdvancedConfig",
    "SimulatorBackend",
    "StartPoint",
    "TrackType",
    "JobsCompareRequest",
    "JobsCompareResponse",
    "Trial",
    "TrialMetrics",
    "TrialStatus",
    "TrialSummary",
    "WindVector",
]
