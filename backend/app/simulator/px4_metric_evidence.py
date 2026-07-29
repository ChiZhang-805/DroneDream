"""Independent core-metric compiler for retained PX4 telemetry evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulator.scenario_effects import (
    ScenarioEffectContractError,
    validate_scenario_effect_evidence,
    validate_scenario_effect_request,
)
from app.simulator.telemetry_evidence import (
    TelemetrySamplingEvidenceV1,
    compile_sampling_evidence,
    verify_telemetry_semantic_contract,
)

PX4_CORE_METRIC_EVIDENCE_V1 = "dronedream.px4-core-metric-evidence/v1"
PX4_CORE_METRIC_VERIFIER_REVISION = "px4-core-metric-verifier-1.0"
PX4_TRACK_PROJECTION_REVISION = "ordered-local-3d-segment-projection-1.0"
PX4_STATIONARY_PROJECTION_REVISION = "stationary-point-3d-projection-1.0"
PX4_RMSE_INTEGRATION_REVISION = "time_weighted_trapezoidal"
PX4_EVALUATION_POLICY_V1 = "dronedream.px4-evaluation-policy/v1"
PX4_EVALUATION_WINDOW_EVIDENCE_V1 = "dronedream.px4-evaluation-window-evidence/v1"
PX4_EVALUATION_WINDOW_VERIFIER_REVISION = "px4-evaluation-window-verifier-1.0"
PX4_OUTCOME_POLICY_V1 = "dronedream.px4-outcome-policy/v1"
PX4_OUTCOME_EVIDENCE_V1 = "dronedream.px4-outcome-evidence/v1"
PX4_OUTCOME_VERIFIER_REVISION = "px4-outcome-verifier-1.0"
PX4_PROGRESS_REVISION = "directed-continuous-arc-coverage-1.0"
PX4_SCORE_REVISION = "rmse-plus-half-max-plus-duration-and-fixed-penalties-1.0"

_PROJECTION_BACKTRACK_SEGMENTS = 16
_PROJECTION_FORWARD_SEGMENTS = 64
_PROJECTION_GLOBAL_RESCAN_INTERVAL = 256
_PROJECTION_GLOBAL_RESCAN_DISTANCE_M = 2.0
_PROJECTION_LOCAL_ERROR_FALLBACK_M = 5.0
_MAX_PROJECTION_SEGMENT_COMPARISONS = 10_000_000
_MAX_COVERAGE_PROGRESS_STEP_FRACTION = 0.2
_MIN_CONTINUOUS_PROGRESS_STEP_M = 0.25
_CONTINUOUS_PROGRESS_POSITION_MULTIPLIER = 4.0
_CONTINUOUS_PROGRESS_OFFSET_M = 0.1
_MAX_STABLE_POSITION_SPEED_MPS = 25.0
_MAX_STABLE_TRACK_ERROR_M = 30.0
_MIN_AIRBORNE_REFERENCE_ALTITUDE_M = 0.5
_MIN_COLLAPSE_ALTITUDE_M = 0.2
_BACKWARD_TOLERANCE_M = 0.1
_BACKWARD_TOLERANCE_TRACK_FRACTION = 0.02
_ENDPOINT_TOLERANCE_M = 0.25
_ENDPOINT_TOLERANCE_TRACK_FRACTION = 0.01
_CRASH_PENALTY = 100.0
_TIMEOUT_PENALTY = 120.0
_INSTABILITY_PENALTY = 80.0
_PROGRESS_PENALTY = 20.0
_MAX_ERROR_SCORE_WEIGHT = 0.5
_DURATION_SCORE_WEIGHT = 0.05
_HOVER_MIN_EVALUATION_DURATION_SECONDS = 10.0

Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
NonnegativeInt = Annotated[int, Field(ge=0)]
NonnegativeFloat = Annotated[float, Field(ge=0.0)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]


class Px4CoreMetricEvidenceError(ValueError):
    """Raised when PX4 core metrics cannot be independently verified."""


class Px4EvaluationPolicyV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal["dronedream.px4-evaluation-policy/v1"] = (
        "dronedream.px4-evaluation-policy/v1"
    )
    policy_id: Sha256Id
    pass_rmse_m: NonnegativeFloat
    pass_max_error_m: NonnegativeFloat
    minimum_track_coverage: UnitInterval
    altitude_entry_fraction: Annotated[
        float,
        Field(gt=0.0, le=1.0),
    ]
    near_track_threshold_m: Annotated[float, Field(gt=0.0)]
    consecutive_samples: Annotated[int, Field(ge=1, le=10_000)]
    collapse_altitude_fraction: Annotated[
        float,
        Field(gt=0.0, le=1.0),
    ]

    @model_validator(mode="after")
    def _validate_policy_id(self) -> Px4EvaluationPolicyV1:
        payload = self.model_dump(mode="json")
        policy_id = payload.pop("policy_id")
        if policy_id != _sha256_id(payload):
            raise ValueError("evaluation policy ID does not match its content")
        return self


class Px4EvaluationWindowEvidenceV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal["dronedream.px4-evaluation-window-evidence/v1"] = (
        "dronedream.px4-evaluation-window-evidence/v1"
    )
    evidence_id: Sha256Id
    verifier_revision: Literal["px4-evaluation-window-verifier-1.0"] = (
        "px4-evaluation-window-verifier-1.0"
    )
    telemetry_contract_id: Sha256Id
    reference_track_sha256: Sha256Id
    policy_id: Sha256Id
    offboard_timing_sha256: Sha256Id | None = None
    synthetic: bool
    start_index: NonnegativeInt
    end_index: NonnegativeInt
    source: str = Field(min_length=1, max_length=64)
    raw_source: str = Field(min_length=1, max_length=64)
    raw_start_time_s: float | None = None
    raw_end_time_s: float | None = None
    start_reason: str = Field(min_length=1, max_length=64)
    trimmed_takeoff_samples: NonnegativeInt
    trimmed_landing_samples: NonnegativeInt

    @model_validator(mode="after")
    def _validate_window(self) -> Px4EvaluationWindowEvidenceV1:
        is_single_sample_synthetic = (
            self.synthetic
            and self.start_index == 0
            and self.end_index == 0
            and self.source == "synthetic_all_samples"
            and self.raw_source == "synthetic_all_samples"
        )
        if self.end_index <= self.start_index and not is_single_sample_synthetic:
            raise ValueError("evaluation window end index must follow its start index")
        if (self.raw_start_time_s is None) != (self.raw_end_time_s is None):
            raise ValueError("raw evaluation-window times must be supplied as a pair")
        if self.raw_source == "offboard_timing":
            if self.offboard_timing_sha256 is None:
                raise ValueError("offboard timing windows must bind timing evidence")
            if self.raw_start_time_s is None:
                raise ValueError("offboard timing windows must retain raw times")
        payload = self.model_dump(mode="json")
        evidence_id = payload.pop("evidence_id")
        if evidence_id != _sha256_id(payload):
            raise ValueError("evaluation-window evidence ID does not match its content")
        return self


class Px4OutcomePolicyV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal["dronedream.px4-outcome-policy/v1"] = "dronedream.px4-outcome-policy/v1"
    policy_id: Sha256Id
    evaluation_policy_id: Sha256Id
    progress_revision: Literal["directed-continuous-arc-coverage-1.0"] = (
        "directed-continuous-arc-coverage-1.0"
    )
    score_revision: Literal["rmse-plus-half-max-plus-duration-and-fixed-penalties-1.0"] = (
        "rmse-plus-half-max-plus-duration-and-fixed-penalties-1.0"
    )
    maximum_progress_step_fraction: Annotated[float, Field(gt=0.0, le=1.0)]
    minimum_progress_step_m: Annotated[float, Field(gt=0.0)]
    progress_position_multiplier: Annotated[float, Field(gt=0.0)]
    progress_offset_m: NonnegativeFloat
    maximum_position_speed_mps: Annotated[float, Field(gt=0.0)]
    maximum_stable_track_error_m: Annotated[float, Field(gt=0.0)]
    minimum_airborne_reference_altitude_m: NonnegativeFloat
    minimum_collapse_altitude_m: NonnegativeFloat
    backward_tolerance_m: NonnegativeFloat
    backward_tolerance_track_fraction: UnitInterval
    endpoint_tolerance_m: NonnegativeFloat
    endpoint_tolerance_track_fraction: UnitInterval
    crash_penalty: NonnegativeFloat
    timeout_penalty: NonnegativeFloat
    instability_penalty: NonnegativeFloat
    progress_penalty: NonnegativeFloat
    max_error_score_weight: NonnegativeFloat
    duration_score_weight: NonnegativeFloat

    @model_validator(mode="after")
    def _validate_policy_id(self) -> Px4OutcomePolicyV1:
        payload = self.model_dump(mode="json")
        policy_id = payload.pop("policy_id")
        if policy_id != _sha256_id(payload):
            raise ValueError("PX4 outcome policy ID does not match its content")
        return self


class Px4OutcomeEvidenceV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal["dronedream.px4-outcome-evidence/v1"] = "dronedream.px4-outcome-evidence/v1"
    evidence_id: Sha256Id
    verifier_revision: Literal["px4-outcome-verifier-1.0"] = "px4-outcome-verifier-1.0"
    outcome_policy_id: Sha256Id
    evaluation_policy_id: Sha256Id
    evaluation_window_evidence_id: Sha256Id
    core_metric_evidence_id: Sha256Id
    telemetry_contract_id: Sha256Id
    reference_track_sha256: Sha256Id
    scenario_effect_request_sha256: Sha256Id
    scenario_effect_evidence_sha256: Sha256Id | None = None
    synthetic: bool
    requested_effects: tuple[str, ...]
    applied_effects: tuple[str, ...]
    scenario_effect_status: Literal[
        "not_requested",
        "verified_applied",
        "unsupported",
        "failed",
        "missing_evidence",
        "invalid_evidence",
    ]
    scenario_effects_ready: bool
    crash_flag: bool
    crash_reason: Literal[
        "none",
        "telemetry_crashed_flag",
        "altitude_collapse_in_evaluation_window",
    ]
    crash_sample_index: NonnegativeInt | None = None
    timeout_flag: bool
    instability_flag: bool
    instability_reasons: tuple[
        Literal[
            "position_speed_exceeded",
            "track_error_exceeded",
        ],
        ...,
    ]
    instability_first_sample_index: NonnegativeInt | None = None
    maximum_observed_position_speed_mps: NonnegativeFloat
    full_track_coverage: UnitInterval
    evaluation_track_coverage: UnitInterval
    evaluation_directed_progress_fraction: UnitInterval
    evaluation_backward_distance_m: NonnegativeFloat
    evaluation_progress_discontinuity_count: NonnegativeInt
    evaluation_direction_valid: bool
    evaluation_start_reached: bool
    evaluation_endpoint_reached: bool
    evaluation_progress_contract_ok: bool
    track_length_3d_m: NonnegativeFloat
    track_is_closed: bool
    evaluation_min_z_m: float
    evaluation_max_z_m: float
    pass_flag: bool
    score_rmse_component: NonnegativeFloat
    score_max_error_component: NonnegativeFloat
    score_duration_component: NonnegativeFloat
    score_penalty: NonnegativeFloat
    score: float

    @model_validator(mode="after")
    def _validate_outcome(self) -> Px4OutcomeEvidenceV1:
        if self.crash_flag != (self.crash_reason != "none"):
            raise ValueError("PX4 crash flag and reason are inconsistent")
        if self.crash_flag != (self.crash_sample_index is not None):
            raise ValueError("PX4 crash flag and sample index are inconsistent")
        if self.instability_flag != bool(self.instability_reasons):
            raise ValueError("PX4 instability flag and reasons are inconsistent")
        if self.scenario_effects_ready != (
            self.requested_effects == self.applied_effects
            and self.scenario_effect_status in {"not_requested", "verified_applied"}
        ):
            raise ValueError("PX4 scenario-effect readiness is inconsistent")
        if self.pass_flag and (
            self.crash_flag
            or self.timeout_flag
            or self.instability_flag
            or not self.scenario_effects_ready
            or not self.evaluation_progress_contract_ok
        ):
            raise ValueError("PX4 passing outcome violates a mandatory gate")
        expected_score = round(
            self.score_rmse_component
            + self.score_max_error_component
            + self.score_duration_component
            + self.score_penalty,
            6,
        )
        if self.score != expected_score:
            raise ValueError("PX4 outcome score does not match its components")
        payload = self.model_dump(mode="json")
        evidence_id = payload.pop("evidence_id")
        if evidence_id != _sha256_id(payload):
            raise ValueError("PX4 outcome evidence ID does not match its content")
        return self


class Px4MaxErrorSampleV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    t: float
    x: float
    y: float
    z: float
    reference_x: float
    reference_y: float
    reference_z: float
    track_progress_m: NonnegativeFloat
    error: NonnegativeFloat


class Px4CoreMetricEvidenceV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal["dronedream.px4-core-metric-evidence/v1"] = (
        "dronedream.px4-core-metric-evidence/v1"
    )
    evidence_id: Sha256Id
    verifier_revision: Literal["px4-core-metric-verifier-1.0"] = "px4-core-metric-verifier-1.0"
    telemetry_contract_id: Sha256Id
    reference_track_sha256: Sha256Id
    projection_revision: Literal[
        "ordered-local-3d-segment-projection-1.0",
        "stationary-point-3d-projection-1.0",
    ] = "ordered-local-3d-segment-projection-1.0"
    rmse_integration: Literal["time_weighted_trapezoidal"] = "time_weighted_trapezoidal"
    synthetic: bool
    evaluation_start_index: NonnegativeInt
    evaluation_end_index: NonnegativeInt
    evaluation_sample_count: Annotated[int, Field(ge=1)]
    total_sample_count: Annotated[int, Field(ge=1)]
    evaluation_start_time_s: float
    evaluation_end_time_s: float
    evaluation_duration_s: NonnegativeFloat
    rmse_m: NonnegativeFloat
    max_error_m: NonnegativeFloat
    full_log_rmse_m: NonnegativeFloat
    full_log_max_error_m: NonnegativeFloat
    final_error_m: NonnegativeFloat
    overshoot_count: NonnegativeInt
    evaluation_sampling: TelemetrySamplingEvidenceV1
    evaluation_max_error_sample: Px4MaxErrorSampleV1

    @model_validator(mode="after")
    def _validate_window(self) -> Px4CoreMetricEvidenceV1:
        if (
            self.synthetic
            and self.total_sample_count == 1
            and self.evaluation_start_index == 0
            and self.evaluation_end_index == 0
            and self.evaluation_sample_count == 1
            and self.evaluation_start_time_s == self.evaluation_end_time_s
            and self.evaluation_duration_s == 0.0
        ):
            return self
        if self.evaluation_end_index <= self.evaluation_start_index:
            raise ValueError("evaluation end index must follow its start index")
        if (
            self.evaluation_end_index >= self.total_sample_count
            or self.evaluation_sample_count
            != self.evaluation_end_index - self.evaluation_start_index + 1
        ):
            raise ValueError("evaluation indices do not match sample counts")
        if self.evaluation_end_time_s <= self.evaluation_start_time_s:
            raise ValueError("evaluation end time must follow its start time")
        return self


@dataclass(frozen=True)
class _TrackSegment:
    start: tuple[float, float, float]
    delta: tuple[float, float, float]
    length: float
    start_progress: float


@dataclass(frozen=True)
class _TrackGeometry:
    segments: tuple[_TrackSegment, ...]
    total_length: float
    closed: bool
    stationary: bool = False


@dataclass(frozen=True)
class _TrackProjection:
    error: float
    segment_index: int
    progress: float
    reference_x: float
    reference_y: float
    reference_z: float


@dataclass(frozen=True)
class _EvaluationWindow:
    start_index: int
    end_index: int
    source: str
    raw_source: str
    raw_start_time_s: float | None
    raw_end_time_s: float | None
    start_reason: str
    trimmed_takeoff_samples: int
    trimmed_landing_samples: int


@dataclass(frozen=True)
class _TrackProgress:
    coverage: float
    directed_progress_fraction: float
    backward_distance: float
    discontinuity_count: int
    start_progress: float | None
    end_progress: float | None


@dataclass(frozen=True)
class _ScenarioEffectState:
    request_sha256: str
    evidence_sha256: str | None
    requested_effects: tuple[str, ...]
    applied_effects: tuple[str, ...]
    status: str
    ready: bool


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def compile_px4_outcome_policy(
    evaluation_policy: Px4EvaluationPolicyV1,
) -> Px4OutcomePolicyV1:
    payload = {
        "schema_id": PX4_OUTCOME_POLICY_V1,
        "evaluation_policy_id": evaluation_policy.policy_id,
        "progress_revision": PX4_PROGRESS_REVISION,
        "score_revision": PX4_SCORE_REVISION,
        "maximum_progress_step_fraction": (_MAX_COVERAGE_PROGRESS_STEP_FRACTION),
        "minimum_progress_step_m": _MIN_CONTINUOUS_PROGRESS_STEP_M,
        "progress_position_multiplier": (_CONTINUOUS_PROGRESS_POSITION_MULTIPLIER),
        "progress_offset_m": _CONTINUOUS_PROGRESS_OFFSET_M,
        "maximum_position_speed_mps": _MAX_STABLE_POSITION_SPEED_MPS,
        "maximum_stable_track_error_m": _MAX_STABLE_TRACK_ERROR_M,
        "minimum_airborne_reference_altitude_m": (_MIN_AIRBORNE_REFERENCE_ALTITUDE_M),
        "minimum_collapse_altitude_m": _MIN_COLLAPSE_ALTITUDE_M,
        "backward_tolerance_m": _BACKWARD_TOLERANCE_M,
        "backward_tolerance_track_fraction": (_BACKWARD_TOLERANCE_TRACK_FRACTION),
        "endpoint_tolerance_m": _ENDPOINT_TOLERANCE_M,
        "endpoint_tolerance_track_fraction": (_ENDPOINT_TOLERANCE_TRACK_FRACTION),
        "crash_penalty": _CRASH_PENALTY,
        "timeout_penalty": _TIMEOUT_PENALTY,
        "instability_penalty": _INSTABILITY_PENALTY,
        "progress_penalty": _PROGRESS_PENALTY,
        "max_error_score_weight": _MAX_ERROR_SCORE_WEIGHT,
        "duration_score_weight": _DURATION_SCORE_WEIGHT,
    }
    return Px4OutcomePolicyV1.model_validate({"policy_id": _sha256_id(payload), **payload})


def compile_px4_evaluation_policy(
    *,
    pass_rmse_m: float,
    pass_max_error_m: float,
    minimum_track_coverage: float,
    altitude_entry_fraction: float,
    near_track_threshold_m: float,
    consecutive_samples: int,
    collapse_altitude_fraction: float,
) -> Px4EvaluationPolicyV1:
    payload = {
        "schema_id": PX4_EVALUATION_POLICY_V1,
        "pass_rmse_m": pass_rmse_m,
        "pass_max_error_m": pass_max_error_m,
        "minimum_track_coverage": minimum_track_coverage,
        "altitude_entry_fraction": altitude_entry_fraction,
        "near_track_threshold_m": near_track_threshold_m,
        "consecutive_samples": consecutive_samples,
        "collapse_altitude_fraction": collapse_altitude_fraction,
    }
    return Px4EvaluationPolicyV1.model_validate({"policy_id": _sha256_id(payload), **payload})


def _environment_float(
    source: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise Px4CoreMetricEvidenceError(f"{name} must be numeric") from exc
    if not math.isfinite(value):
        raise Px4CoreMetricEvidenceError(f"{name} must be finite")
    return value


def _environment_int(
    source: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = source.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError as exc:
        raise Px4CoreMetricEvidenceError(f"{name} must be an integer") from exc


def px4_evaluation_policy_from_environment(
    source: Mapping[str, str],
) -> Px4EvaluationPolicyV1:
    return compile_px4_evaluation_policy(
        pass_rmse_m=_environment_float(
            source,
            "PX4_GAZEBO_PASS_RMSE",
            0.75,
        ),
        pass_max_error_m=_environment_float(
            source,
            "PX4_GAZEBO_PASS_MAX_ERROR",
            2.0,
        ),
        minimum_track_coverage=_environment_float(
            source,
            "PX4_GAZEBO_MIN_TRACK_COVERAGE",
            0.9,
        ),
        altitude_entry_fraction=_environment_float(
            source,
            "PX4_GAZEBO_EVAL_ALTITUDE_FRACTION",
            0.9,
        ),
        near_track_threshold_m=_environment_float(
            source,
            "PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M",
            1.5,
        ),
        consecutive_samples=_environment_int(
            source,
            "PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES",
            5,
        ),
        collapse_altitude_fraction=_environment_float(
            source,
            "PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION",
            0.5,
        ),
    )


def _finite_coordinate(
    value: object,
    *,
    label: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
    ):
        raise Px4CoreMetricEvidenceError(f"{label} must be finite")
    return float(value)


def _reference_points(payload: object) -> list[dict[str, float]]:
    if not isinstance(payload, Mapping):
        raise Px4CoreMetricEvidenceError("reference-track evidence must be an object")
    if payload.get("schema_version") != "dronedream.reference_track.v1":
        raise Px4CoreMetricEvidenceError("reference-track evidence has an unsupported schema")
    raw_points = payload.get("reference_track")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise Px4CoreMetricEvidenceError("reference track must contain at least two points")
    points: list[dict[str, float]] = []
    for index, raw_point in enumerate(raw_points):
        if not isinstance(raw_point, Mapping):
            raise Px4CoreMetricEvidenceError(f"reference point {index} must be an object")
        points.append(
            {
                axis: _finite_coordinate(
                    raw_point.get(axis),
                    label=f"reference point {index}.{axis}",
                )
                for axis in ("x", "y", "z")
            }
        )
    return points


def _reference_track_type(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("track_type")
    return raw if isinstance(raw, str) else None


def _telemetry_samples(
    payload: object,
) -> tuple[list[dict[str, Any]], str, bool]:
    contract = verify_telemetry_semantic_contract(payload)
    if contract is None or not isinstance(payload, Mapping):
        raise Px4CoreMetricEvidenceError("telemetry semantic contract is invalid")
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list):
        raise Px4CoreMetricEvidenceError("telemetry samples are missing")
    samples: list[dict[str, Any]] = []
    for index, raw_sample in enumerate(raw_samples):
        if not isinstance(raw_sample, Mapping):
            raise Px4CoreMetricEvidenceError(f"telemetry sample {index} must be an object")
        sample = dict(raw_sample)
        for field in ("t", "x", "y", "z"):
            sample[field] = _finite_coordinate(
                raw_sample.get(field),
                label=f"telemetry sample {index}.{field}",
            )
        if "crashed" in raw_sample and not isinstance(
            raw_sample["crashed"],
            bool,
        ):
            raise Px4CoreMetricEvidenceError(f"telemetry sample {index}.crashed must be boolean")
        samples.append(sample)
    return samples, contract.contract_id, contract.synthetic


def _build_track_geometry(
    ref_points: list[dict[str, float]],
    *,
    allow_stationary: bool = False,
) -> _TrackGeometry:
    segments: list[_TrackSegment] = []
    progress = 0.0
    for start, end in zip(ref_points, ref_points[1:], strict=False):
        start_xyz = (start["x"], start["y"], start["z"])
        delta = (
            end["x"] - start_xyz[0],
            end["y"] - start_xyz[1],
            end["z"] - start_xyz[2],
        )
        length = math.sqrt(sum(component * component for component in delta))
        if length <= 1e-12:
            continue
        segments.append(
            _TrackSegment(
                start=start_xyz,
                delta=delta,
                length=length,
                start_progress=progress,
            )
        )
        progress += length
    if not segments or progress <= 1e-12:
        if allow_stationary and ref_points:
            anchor = ref_points[0]
            anchor_start = (anchor["x"], anchor["y"], anchor["z"])
            return _TrackGeometry(
                segments=(
                    _TrackSegment(
                        start=anchor_start,
                        delta=(0.0, 0.0, 0.0),
                        length=0.0,
                        start_progress=0.0,
                    ),
                ),
                total_length=0.0,
                closed=True,
                stationary=True,
            )
        raise Px4CoreMetricEvidenceError(
            "reference track must have non-zero three-dimensional length"
        )
    first = ref_points[0]
    last = ref_points[-1]
    endpoint_distance = math.dist(
        (first["x"], first["y"], first["z"]),
        (last["x"], last["y"], last["z"]),
    )
    return _TrackGeometry(
        segments=tuple(segments),
        total_length=progress,
        closed=endpoint_distance <= max(1e-6, progress * 1e-6),
        stationary=False,
    )


def _project_sample_to_segment(
    sample: Mapping[str, Any],
    segment: _TrackSegment,
    segment_index: int,
) -> _TrackProjection:
    offset = (
        float(sample["x"]) - segment.start[0],
        float(sample["y"]) - segment.start[1],
        float(sample["z"]) - segment.start[2],
    )
    length_squared = segment.length * segment.length
    fraction = (
        0.0
        if length_squared <= 1e-24
        else min(
            1.0,
            max(
                0.0,
                sum(offset[index] * segment.delta[index] for index in range(3))
                / length_squared,
            ),
        )
    )
    reference = tuple(segment.start[index] + fraction * segment.delta[index] for index in range(3))
    error = math.dist(
        (
            float(sample["x"]),
            float(sample["y"]),
            float(sample["z"]),
        ),
        reference,
    )
    return _TrackProjection(
        error=error,
        segment_index=segment_index,
        progress=segment.start_progress + fraction * segment.length,
        reference_x=reference[0],
        reference_y=reference[1],
        reference_z=reference[2],
    )


def _best_track_projection(
    sample: Mapping[str, Any],
    geometry: _TrackGeometry,
    candidate_indices: Sequence[int],
    comparison_budget: list[int],
) -> _TrackProjection:
    candidate_count = len(candidate_indices)
    if candidate_count > comparison_budget[0]:
        raise Px4CoreMetricEvidenceError("track projection exceeds the bounded comparison budget")
    comparison_budget[0] -= candidate_count
    best: _TrackProjection | None = None
    for segment_index in candidate_indices:
        projection = _project_sample_to_segment(
            sample,
            geometry.segments[segment_index],
            segment_index,
        )
        if best is None or projection.error < best.error:
            best = projection
    if best is None:
        raise Px4CoreMetricEvidenceError("track projection requires a candidate segment")
    return best


def _local_segment_indices(
    previous_index: int,
    segment_count: int,
    *,
    closed: bool,
) -> list[int]:
    if segment_count <= _PROJECTION_BACKTRACK_SEGMENTS + _PROJECTION_FORWARD_SEGMENTS + 1:
        return list(range(segment_count))
    lower = previous_index - _PROJECTION_BACKTRACK_SEGMENTS
    upper = previous_index + _PROJECTION_FORWARD_SEGMENTS
    if closed and (lower < 0 or upper >= segment_count):
        wrapped = [index % segment_count for index in range(lower, upper + 1)]
        return list(dict.fromkeys(wrapped))
    return list(
        range(
            max(0, lower),
            min(segment_count - 1, upper) + 1,
        )
    )


def _project_samples_to_track(
    samples: list[dict[str, Any]],
    geometry: _TrackGeometry,
) -> list[_TrackProjection]:
    segment_count = len(geometry.segments)
    all_indices = list(range(segment_count))
    comparison_budget = [_MAX_PROJECTION_SEGMENT_COMPARISONS]
    projections: list[_TrackProjection] = []
    previous_index = 0
    last_global_position: tuple[float, float, float] | None = None
    for sample_index, sample in enumerate(samples):
        position = (
            float(sample["x"]),
            float(sample["y"]),
            float(sample["z"]),
        )
        if sample_index == 0:
            best = _best_track_projection(
                sample,
                geometry,
                all_indices,
                comparison_budget,
            )
            last_global_position = position
        else:
            local_indices = _local_segment_indices(
                previous_index,
                segment_count,
                closed=geometry.closed,
            )
            best = _best_track_projection(
                sample,
                geometry,
                local_indices,
                comparison_budget,
            )
            moved_since_global = (
                float("inf")
                if last_global_position is None
                else math.dist(position, last_global_position)
            )
            local_boundary_hit = len(local_indices) < segment_count and (
                (geometry.closed and best.segment_index in {local_indices[0], local_indices[-1]})
                or (
                    not geometry.closed
                    and (
                        (local_indices[0] > 0 and best.segment_index == local_indices[0])
                        or (
                            local_indices[-1] < segment_count - 1
                            and best.segment_index == local_indices[-1]
                        )
                    )
                )
            )
            needs_global = (
                sample_index % _PROJECTION_GLOBAL_RESCAN_INTERVAL == 0
                or local_boundary_hit
                or (
                    best.error > _PROJECTION_LOCAL_ERROR_FALLBACK_M
                    and moved_since_global >= _PROJECTION_GLOBAL_RESCAN_DISTANCE_M
                )
            )
            if needs_global:
                global_best = _best_track_projection(
                    sample,
                    geometry,
                    all_indices,
                    comparison_budget,
                )
                if global_best.error + 1e-9 < best.error:
                    best = global_best
                last_global_position = position
        projections.append(best)
        previous_index = best.segment_index
    return projections


def _sample_meets_track_entry_condition(
    sample: Mapping[str, Any],
    projection: _TrackProjection,
    policy: Px4EvaluationPolicyV1,
) -> bool:
    target_altitude = max(0.0, projection.reference_z)
    if (
        target_altitude > 0.0
        and float(sample["z"]) < policy.altitude_entry_fraction * target_altitude
    ):
        return False
    return projection.error <= policy.near_track_threshold_m


def _first_consecutive_index(
    samples: list[dict[str, Any]],
    start_index: int,
    end_index: int,
    predicate: Callable[[int, dict[str, Any]], bool],
    consecutive_count: int,
) -> int | None:
    count = 0
    run_start: int | None = None
    for index in range(start_index, end_index + 1):
        if predicate(index, samples[index]):
            if count == 0:
                run_start = index
            count += 1
            if count >= consecutive_count:
                return run_start
        else:
            count = 0
            run_start = None
    return None


def _last_before_landing_index(
    samples: list[dict[str, Any]],
    projections: list[_TrackProjection],
    start_index: int,
    end_index: int,
    policy: Px4EvaluationPolicyV1,
) -> int:
    count = 0
    run_start: int | None = None
    for index in range(start_index + 1, end_index + 1):
        target_altitude = max(
            0.0,
            projections[index].reference_z,
        )
        threshold = policy.altitude_entry_fraction * target_altitude
        if float(samples[index]["z"]) < threshold:
            if count == 0:
                run_start = index
            count += 1
            if count >= policy.consecutive_samples and run_start is not None:
                return max(start_index, run_start - 1)
        else:
            count = 0
            run_start = None
    return end_index


def _refine_candidate_window(
    samples: list[dict[str, Any]],
    projections: list[_TrackProjection],
    raw_start_index: int,
    raw_end_index: int,
    *,
    raw_source: str,
    policy: Px4EvaluationPolicyV1,
) -> _EvaluationWindow | None:
    raw_start_index = max(0, raw_start_index)
    raw_end_index = min(len(samples) - 1, raw_end_index)
    if raw_end_index <= raw_start_index:
        return None
    refined_start = _first_consecutive_index(
        samples,
        raw_start_index,
        raw_end_index,
        lambda index, sample: _sample_meets_track_entry_condition(
            sample,
            projections[index],
            policy,
        ),
        policy.consecutive_samples,
    )
    if refined_start is None:
        return None
    refined_end = _last_before_landing_index(
        samples,
        projections,
        refined_start,
        raw_end_index,
        policy,
    )
    if refined_end <= refined_start:
        return None
    return _EvaluationWindow(
        start_index=refined_start,
        end_index=refined_end,
        source=f"{raw_source}_refined",
        raw_source=raw_source,
        raw_start_time_s=float(samples[raw_start_index]["t"]),
        raw_end_time_s=float(samples[raw_end_index]["t"]),
        start_reason="altitude_and_near_track",
        trimmed_takeoff_samples=(refined_start - raw_start_index),
        trimmed_landing_samples=raw_end_index - refined_end,
    )


def _window_from_timing(
    samples: list[dict[str, Any]],
    projections: list[_TrackProjection],
    timing: Mapping[str, object],
    policy: Px4EvaluationPolicyV1,
) -> _EvaluationWindow | None:
    start_time_raw = timing.get("track_start_t")
    end_time_raw = timing.get("track_end_t")
    if (
        isinstance(start_time_raw, bool)
        or not isinstance(start_time_raw, int | float)
        or isinstance(end_time_raw, bool)
        or not isinstance(end_time_raw, int | float)
    ):
        return None
    start_time = float(start_time_raw)
    end_time = float(end_time_raw)
    if not math.isfinite(start_time) or not math.isfinite(end_time) or end_time <= start_time:
        return None
    start_index = next(
        (index for index, sample in enumerate(samples) if float(sample["t"]) >= start_time),
        None,
    )
    end_index = next(
        (index for index, sample in enumerate(samples) if float(sample["t"]) >= end_time),
        None,
    )
    if start_index is None or end_index is None or end_index <= start_index:
        return None
    return _refine_candidate_window(
        samples,
        projections,
        start_index,
        end_index,
        raw_source="offboard_timing",
        policy=policy,
    )


def _window_from_telemetry(
    samples: list[dict[str, Any]],
    projections: list[_TrackProjection],
    policy: Px4EvaluationPolicyV1,
) -> _EvaluationWindow | None:
    start_index = _first_consecutive_index(
        samples,
        0,
        len(samples) - 1,
        lambda index, sample: _sample_meets_track_entry_condition(
            sample,
            projections[index],
            policy,
        ),
        policy.consecutive_samples,
    )
    if start_index is None:
        return None
    end_index = _last_before_landing_index(
        samples,
        projections,
        start_index,
        len(samples) - 1,
        policy,
    )
    if end_index <= start_index:
        return None
    return _EvaluationWindow(
        start_index=start_index,
        end_index=end_index,
        source="telemetry_derived_refined",
        raw_source="telemetry_derived",
        raw_start_time_s=None,
        raw_end_time_s=None,
        start_reason="altitude_and_near_track",
        trimmed_takeoff_samples=start_index,
        trimmed_landing_samples=len(samples) - 1 - end_index,
    )


def _altitude_only_window(
    samples: list[dict[str, Any]],
    projections: list[_TrackProjection],
    policy: Px4EvaluationPolicyV1,
) -> _EvaluationWindow | None:
    start_index = _first_consecutive_index(
        samples,
        0,
        len(samples) - 1,
        lambda index, sample: (
            float(sample["z"])
            >= policy.altitude_entry_fraction * max(0.0, projections[index].reference_z)
        ),
        policy.consecutive_samples,
    )
    if start_index is None:
        return None
    end_index = _last_before_landing_index(
        samples,
        projections,
        start_index,
        len(samples) - 1,
        policy,
    )
    if end_index <= start_index:
        return None
    return _EvaluationWindow(
        start_index=start_index,
        end_index=end_index,
        source="altitude_only_refined",
        raw_source="altitude_only",
        raw_start_time_s=None,
        raw_end_time_s=None,
        start_reason="altitude_only",
        trimmed_takeoff_samples=start_index,
        trimmed_landing_samples=len(samples) - 1 - end_index,
    )


def compile_px4_evaluation_window_evidence(
    *,
    telemetry_payload: object,
    reference_track_payload: object,
    offboard_timing_payload: object | None,
    policy: Px4EvaluationPolicyV1,
) -> Px4EvaluationWindowEvidenceV1:
    samples, telemetry_contract_id, synthetic = _telemetry_samples(telemetry_payload)
    reference_points = _reference_points(reference_track_payload)
    geometry = _build_track_geometry(
        reference_points,
        allow_stationary=_reference_track_type(reference_track_payload) == "hover",
    )
    projections = _project_samples_to_track(samples, geometry)
    timing = offboard_timing_payload if isinstance(offboard_timing_payload, Mapping) else None
    window = (
        _window_from_timing(
            samples,
            projections,
            timing,
            policy,
        )
        if timing is not None
        else None
    )
    if window is None:
        window = _window_from_telemetry(
            samples,
            projections,
            policy,
        )
    if window is None:
        window = _altitude_only_window(
            samples,
            projections,
            policy,
        )
    if window is None:
        if not synthetic:
            raise Px4CoreMetricEvidenceError(
                "trusted evaluation window could not be independently derived"
            )
        window = _EvaluationWindow(
            start_index=0,
            end_index=len(samples) - 1,
            source="synthetic_all_samples",
            raw_source="synthetic_all_samples",
            raw_start_time_s=None,
            raw_end_time_s=None,
            start_reason="synthetic_all_samples",
            trimmed_takeoff_samples=0,
            trimmed_landing_samples=0,
        )
    payload: dict[str, Any] = {
        "schema_id": PX4_EVALUATION_WINDOW_EVIDENCE_V1,
        "verifier_revision": (PX4_EVALUATION_WINDOW_VERIFIER_REVISION),
        "telemetry_contract_id": telemetry_contract_id,
        "reference_track_sha256": _sha256_id(reference_points),
        "policy_id": policy.policy_id,
        "offboard_timing_sha256": (_sha256_id(dict(timing)) if timing is not None else None),
        "synthetic": synthetic,
        "start_index": window.start_index,
        "end_index": window.end_index,
        "source": window.source,
        "raw_source": window.raw_source,
        "raw_start_time_s": (
            round(window.raw_start_time_s, 6) if window.raw_start_time_s is not None else None
        ),
        "raw_end_time_s": (
            round(window.raw_end_time_s, 6) if window.raw_end_time_s is not None else None
        ),
        "start_reason": window.start_reason,
        "trimmed_takeoff_samples": (window.trimmed_takeoff_samples),
        "trimmed_landing_samples": (window.trimmed_landing_samples),
    }
    return Px4EvaluationWindowEvidenceV1.model_validate(
        {"evidence_id": _sha256_id(payload), **payload}
    )


def require_px4_evaluation_window_binding(
    raw_metrics: Mapping[str, object],
    *,
    policy: Px4EvaluationPolicyV1,
    evidence: Px4EvaluationWindowEvidenceV1,
) -> None:
    expected = {
        "evaluation_start_index": evidence.start_index,
        "evaluation_end_index": evidence.end_index,
        "evaluation_window_source": evidence.source,
        "evaluation_window_raw_source": evidence.raw_source,
        "raw_track_start_t": evidence.raw_start_time_s,
        "raw_track_end_t": evidence.raw_end_time_s,
        "evaluation_start_reason": evidence.start_reason,
        "evaluation_trimmed_takeoff_samples": (evidence.trimmed_takeoff_samples),
        "evaluation_trimmed_landing_samples": (evidence.trimmed_landing_samples),
        "pass_thresholds": {
            "rmse": policy.pass_rmse_m,
            "max_error": policy.pass_max_error_m,
            "min_track_coverage": (policy.minimum_track_coverage),
        },
        "evaluation_policy": policy.model_dump(mode="json"),
        "evaluation_window_evidence": evidence.model_dump(mode="json"),
    }
    if any(raw_metrics.get(field) != value for field, value in expected.items()):
        raise Px4CoreMetricEvidenceError(
            "PX4 evaluation window or policy does not match independent evidence"
        )


def _time_weighted_rms(
    values: list[float],
    samples: list[dict[str, Any]],
) -> float:
    if not values or len(values) != len(samples):
        raise Px4CoreMetricEvidenceError("time-weighted RMS requires one value per sample")
    if len(values) == 1:
        return abs(values[0])
    duration = float(samples[-1]["t"]) - float(samples[0]["t"])
    if duration <= 0:
        raise Px4CoreMetricEvidenceError("time-weighted RMS requires positive duration")
    integral = 0.0
    for index in range(1, len(values)):
        delta_t = float(samples[index]["t"]) - float(samples[index - 1]["t"])
        if delta_t <= 0:
            raise Px4CoreMetricEvidenceError("time-weighted RMS requires increasing timestamps")
        integral += (
            0.5 * (values[index - 1] * values[index - 1] + values[index] * values[index]) * delta_t
        )
    return math.sqrt(integral / duration)


def _evaluation_indices(
    start: object,
    end: object,
    *,
    sample_count: int,
    synthetic: bool,
) -> tuple[int, int]:
    if synthetic and sample_count == 1 and start == 0 and end == 0:
        return 0, 0
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start < 0
        or end <= start
        or end >= sample_count
    ):
        raise Px4CoreMetricEvidenceError("evaluation sample indices are invalid")
    return start, end


def compile_px4_core_metric_evidence(
    *,
    telemetry_payload: object,
    reference_track_payload: object,
    evaluation_start_index: object,
    evaluation_end_index: object,
) -> Px4CoreMetricEvidenceV1:
    samples, telemetry_contract_id, synthetic = _telemetry_samples(telemetry_payload)
    reference_points = _reference_points(reference_track_payload)
    start_index, end_index = _evaluation_indices(
        evaluation_start_index,
        evaluation_end_index,
        sample_count=len(samples),
        synthetic=synthetic,
    )
    geometry = _build_track_geometry(
        reference_points,
        allow_stationary=_reference_track_type(reference_track_payload) == "hover",
    )
    projections = _project_samples_to_track(samples, geometry)
    evaluation_samples = samples[start_index : end_index + 1]
    evaluation_projections = projections[start_index : end_index + 1]
    evaluation_sampling = compile_sampling_evidence(evaluation_samples)
    errors = [projection.error for projection in projections]
    evaluation_errors = [projection.error for projection in evaluation_projections]
    max_error = max(evaluation_errors)
    max_error_index = evaluation_errors.index(max_error)
    max_error_sample = evaluation_samples[max_error_index]
    max_error_projection = evaluation_projections[max_error_index]
    final_reference = reference_points[-1]
    final_sample = evaluation_samples[-1]
    final_error = math.dist(
        (
            float(final_sample["x"]),
            float(final_sample["y"]),
            float(final_sample["z"]),
        ),
        (
            final_reference["x"],
            final_reference["y"],
            final_reference["z"],
        ),
    )
    overshoot_count = 0
    for index in range(2, len(evaluation_errors)):
        previous = evaluation_errors[index - 2]
        current = evaluation_errors[index - 1]
        following = evaluation_errors[index]
        if current > previous and current > following and current - max(previous, following) > 0.25:
            overshoot_count += 1
    payload: dict[str, Any] = {
        "schema_id": PX4_CORE_METRIC_EVIDENCE_V1,
        "verifier_revision": PX4_CORE_METRIC_VERIFIER_REVISION,
        "telemetry_contract_id": telemetry_contract_id,
        "reference_track_sha256": _sha256_id(reference_points),
        "projection_revision": (
            PX4_STATIONARY_PROJECTION_REVISION
            if geometry.stationary
            else PX4_TRACK_PROJECTION_REVISION
        ),
        "rmse_integration": PX4_RMSE_INTEGRATION_REVISION,
        "synthetic": synthetic,
        "evaluation_start_index": start_index,
        "evaluation_end_index": end_index,
        "evaluation_sample_count": len(evaluation_samples),
        "total_sample_count": len(samples),
        "evaluation_start_time_s": round(
            float(evaluation_samples[0]["t"]),
            6,
        ),
        "evaluation_end_time_s": round(
            float(evaluation_samples[-1]["t"]),
            6,
        ),
        "evaluation_duration_s": round(
            evaluation_sampling.duration_s,
            6,
        ),
        "rmse_m": round(
            _time_weighted_rms(
                evaluation_errors,
                evaluation_samples,
            ),
            6,
        ),
        "max_error_m": round(max_error, 6),
        "full_log_rmse_m": round(
            _time_weighted_rms(errors, samples),
            6,
        ),
        "full_log_max_error_m": round(max(errors), 6),
        "final_error_m": round(final_error, 6),
        "overshoot_count": overshoot_count,
        "evaluation_sampling": evaluation_sampling.model_dump(mode="json"),
        "evaluation_max_error_sample": {
            "t": round(float(max_error_sample["t"]), 6),
            "x": round(float(max_error_sample["x"]), 6),
            "y": round(float(max_error_sample["y"]), 6),
            "z": round(float(max_error_sample["z"]), 6),
            "reference_x": round(max_error_projection.reference_x, 6),
            "reference_y": round(max_error_projection.reference_y, 6),
            "reference_z": round(max_error_projection.reference_z, 6),
            "track_progress_m": round(
                max_error_projection.progress,
                6,
            ),
            "error": round(max_error, 6),
        },
    }
    return Px4CoreMetricEvidenceV1.model_validate({"evidence_id": _sha256_id(payload), **payload})


def require_px4_core_metric_binding(
    metrics: Mapping[str, object],
    evidence: Px4CoreMetricEvidenceV1,
) -> None:
    raw_metrics = metrics.get("raw_metric_json")
    if not isinstance(raw_metrics, Mapping):
        raise Px4CoreMetricEvidenceError("PX4 raw metrics must be an object")
    expected_top_level = {
        "rmse": evidence.rmse_m,
        "max_error": evidence.max_error_m,
        "completion_time": evidence.evaluation_duration_s,
        "final_error": evidence.final_error_m,
        "overshoot_count": evidence.overshoot_count,
    }
    if any(metrics.get(field) != value for field, value in expected_top_level.items()):
        raise Px4CoreMetricEvidenceError(
            "PX4 top-level metrics do not match independently compiled core evidence"
        )
    expected_raw = {
        "rmse_integration": evidence.rmse_integration,
        "telemetry_semantic_contract_id": (evidence.telemetry_contract_id),
        "evaluation_start_index": evidence.evaluation_start_index,
        "evaluation_end_index": evidence.evaluation_end_index,
        "evaluation_start_t": evidence.evaluation_start_time_s,
        "evaluation_end_t": evidence.evaluation_end_time_s,
        "evaluation_sample_count": evidence.evaluation_sample_count,
        "total_sample_count": evidence.total_sample_count,
        "evaluation_sampling": evidence.evaluation_sampling.model_dump(mode="json"),
        "full_log_rmse": evidence.full_log_rmse_m,
        "full_log_max_error": evidence.full_log_max_error_m,
        "evaluation_max_error_sample": (
            evidence.evaluation_max_error_sample.model_dump(mode="json")
        ),
        "px4_core_metric_evidence": evidence.model_dump(mode="json"),
    }
    if any(raw_metrics.get(field) != value for field, value in expected_raw.items()):
        raise Px4CoreMetricEvidenceError(
            "PX4 raw metrics do not match independently compiled core evidence"
        )


def _merged_interval_length(
    intervals: list[tuple[float, float]],
) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + (end - start)


def _evaluate_track_progress(
    samples: list[dict[str, Any]],
    projections: list[_TrackProjection],
    geometry: _TrackGeometry,
    *,
    max_track_error: float,
    policy: Px4OutcomePolicyV1,
) -> _TrackProgress:
    if geometry.stationary:
        valid_projections = [
            projection for projection in projections if projection.error <= max_track_error
        ]
        duration_seconds = (
            max(0.0, float(samples[-1]["t"]) - float(samples[0]["t"]))
            if len(samples) >= 2
            else 0.0
        )
        duration_fraction = min(
            1.0,
            duration_seconds / _HOVER_MIN_EVALUATION_DURATION_SECONDS,
        )
        in_tolerance_fraction = (
            len(valid_projections) / len(projections) if projections else 0.0
        )
        coverage = in_tolerance_fraction * duration_fraction
        reached = 0.0 if valid_projections else None
        return _TrackProgress(
            coverage=coverage,
            directed_progress_fraction=coverage,
            backward_distance=0.0,
            discontinuity_count=0,
            start_progress=reached,
            end_progress=reached,
        )

    intervals: list[tuple[float, float]] = []
    previous: tuple[dict[str, Any], _TrackProjection] | None = None
    first_progress: float | None = None
    last_progress: float | None = None
    forward_distance = 0.0
    backward_distance = 0.0
    discontinuity_count = 0
    for sample, projection in zip(
        samples,
        projections,
        strict=True,
    ):
        if projection.error > max_track_error:
            previous = None
            continue
        if first_progress is None:
            first_progress = projection.progress
        last_progress = projection.progress
        if previous is not None:
            previous_sample, previous_projection = previous
            delta = projection.progress - previous_projection.progress
            if geometry.closed:
                half_length = geometry.total_length / 2.0
                if delta > half_length:
                    delta -= geometry.total_length
                elif delta < -half_length:
                    delta += geometry.total_length
            sample_distance = math.dist(
                (
                    float(sample["x"]),
                    float(sample["y"]),
                    float(sample["z"]),
                ),
                (
                    float(previous_sample["x"]),
                    float(previous_sample["y"]),
                    float(previous_sample["z"]),
                ),
            )
            maximum_continuous_step = min(
                geometry.total_length * policy.maximum_progress_step_fraction,
                max(
                    policy.minimum_progress_step_m,
                    sample_distance * policy.progress_position_multiplier
                    + policy.progress_offset_m,
                ),
            )
            if abs(delta) > maximum_continuous_step + 1e-9:
                discontinuity_count += 1
                previous = (sample, projection)
                continue
            if delta < -1e-12:
                backward_distance += -delta
                previous = (sample, projection)
                continue
            if delta > 1e-12:
                forward_distance += delta
                if geometry.closed:
                    start = previous_projection.progress
                    normalized_start = start % geometry.total_length
                    normalized_end = normalized_start + delta
                    if normalized_end <= geometry.total_length:
                        intervals.append((normalized_start, normalized_end))
                    else:
                        intervals.append(
                            (
                                normalized_start,
                                geometry.total_length,
                            )
                        )
                        intervals.append(
                            (
                                0.0,
                                normalized_end - geometry.total_length,
                            )
                        )
                else:
                    intervals.append(
                        (
                            previous_projection.progress,
                            projection.progress,
                        )
                    )
        previous = (sample, projection)
    return _TrackProgress(
        coverage=min(
            1.0,
            _merged_interval_length(intervals) / geometry.total_length,
        ),
        directed_progress_fraction=min(
            1.0,
            max(
                0.0,
                (forward_distance - backward_distance) / geometry.total_length,
            ),
        ),
        backward_distance=backward_distance,
        discontinuity_count=discontinuity_count,
        start_progress=first_progress,
        end_progress=last_progress,
    )


def _scenario_effect_state(
    request_payload: object,
    evidence_payload: object | None,
) -> _ScenarioEffectState:
    if not isinstance(request_payload, Mapping):
        raise Px4CoreMetricEvidenceError("scenario-effect request evidence must be an object")
    request = dict(request_payload)
    try:
        validate_scenario_effect_request(request)
    except ScenarioEffectContractError as exc:
        raise Px4CoreMetricEvidenceError(f"scenario-effect request is invalid: {exc}") from exc
    raw_effects = request.get("effects")
    if not isinstance(raw_effects, list):
        raise Px4CoreMetricEvidenceError("scenario-effect request effects must be an array")
    requested_effects = tuple(
        sorted(str(effect["effect_id"]) for effect in raw_effects if isinstance(effect, Mapping))
    )
    request_sha256 = _sha256_id(request)
    evidence_sha256 = (
        _sha256_id(dict(evidence_payload)) if isinstance(evidence_payload, Mapping) else None
    )
    if evidence_payload is None:
        status = "not_requested" if not requested_effects else "missing_evidence"
        return _ScenarioEffectState(
            request_sha256=request_sha256,
            evidence_sha256=None,
            requested_effects=requested_effects,
            applied_effects=(),
            status=status,
            ready=not requested_effects,
        )
    try:
        validated = validate_scenario_effect_evidence(
            request,
            evidence_payload,
        )
    except ScenarioEffectContractError:
        return _ScenarioEffectState(
            request_sha256=request_sha256,
            evidence_sha256=evidence_sha256,
            requested_effects=requested_effects,
            applied_effects=(),
            status="invalid_evidence",
            ready=False,
        )
    applied_effects = tuple(str(value) for value in validated.get("applied_effects", []))
    failed_effects = tuple(str(value) for value in validated.get("failed_effects", []))
    unsupported_effects = tuple(str(value) for value in validated.get("unsupported_effects", []))
    if failed_effects:
        status = "failed"
    elif unsupported_effects:
        status = "unsupported"
    elif requested_effects == applied_effects:
        status = "not_requested" if not requested_effects else "verified_applied"
    else:
        status = "invalid_evidence"
    ready = requested_effects == applied_effects and status in {"not_requested", "verified_applied"}
    return _ScenarioEffectState(
        request_sha256=request_sha256,
        evidence_sha256=evidence_sha256,
        requested_effects=requested_effects,
        applied_effects=applied_effects,
        status=status,
        ready=ready,
    )


def compile_px4_outcome_evidence(
    *,
    telemetry_payload: object,
    reference_track_payload: object,
    evaluation_policy: Px4EvaluationPolicyV1,
    evaluation_window_evidence: Px4EvaluationWindowEvidenceV1,
    core_metric_evidence: Px4CoreMetricEvidenceV1,
    scenario_effect_request_payload: object,
    scenario_effect_evidence_payload: object | None,
) -> tuple[Px4OutcomePolicyV1, Px4OutcomeEvidenceV1]:
    samples, telemetry_contract_id, synthetic = _telemetry_samples(telemetry_payload)
    reference_points = _reference_points(reference_track_payload)
    reference_track_sha256 = _sha256_id(reference_points)
    if (
        evaluation_window_evidence.telemetry_contract_id != telemetry_contract_id
        or evaluation_window_evidence.reference_track_sha256 != reference_track_sha256
        or evaluation_window_evidence.policy_id != evaluation_policy.policy_id
    ):
        raise Px4CoreMetricEvidenceError(
            "evaluation-window evidence is not bound to outcome inputs"
        )
    if (
        core_metric_evidence.telemetry_contract_id != telemetry_contract_id
        or core_metric_evidence.reference_track_sha256 != reference_track_sha256
        or core_metric_evidence.evaluation_start_index != evaluation_window_evidence.start_index
        or core_metric_evidence.evaluation_end_index != evaluation_window_evidence.end_index
    ):
        raise Px4CoreMetricEvidenceError("core-metric evidence is not bound to outcome inputs")
    outcome_policy = compile_px4_outcome_policy(evaluation_policy)
    geometry = _build_track_geometry(
        reference_points,
        allow_stationary=_reference_track_type(reference_track_payload) == "hover",
    )
    projections = _project_samples_to_track(samples, geometry)
    start_index = evaluation_window_evidence.start_index
    end_index = evaluation_window_evidence.end_index
    evaluation_samples = samples[start_index : end_index + 1]
    evaluation_projections = projections[start_index : end_index + 1]
    if not evaluation_samples:
        raise Px4CoreMetricEvidenceError("outcome compilation requires evaluation samples")
    evaluation_errors = [projection.error for projection in evaluation_projections]
    raw_rmse = _time_weighted_rms(
        evaluation_errors,
        evaluation_samples,
    )
    raw_max_error = max(evaluation_errors)
    evaluation_duration = float(evaluation_samples[-1]["t"]) - float(evaluation_samples[0]["t"])

    crash_flag = False
    crash_reason = "none"
    crash_sample_index: int | None = None
    for relative_index, sample in enumerate(evaluation_samples):
        if sample.get("crashed", False) is True:
            crash_flag = True
            crash_reason = "telemetry_crashed_flag"
            crash_sample_index = start_index + relative_index
            break
    stable_altitude_seen = any(
        projection.reference_z > outcome_policy.minimum_airborne_reference_altitude_m
        and float(sample["z"]) >= evaluation_policy.altitude_entry_fraction * projection.reference_z
        for sample, projection in zip(
            evaluation_samples,
            evaluation_projections,
            strict=True,
        )
    )
    if (
        not crash_flag
        and stable_altitude_seen
        and len(evaluation_samples) > evaluation_policy.consecutive_samples
    ):
        collapse_run = 0
        for relative_index in range(
            evaluation_policy.consecutive_samples,
            len(evaluation_samples),
        ):
            reference_z = evaluation_projections[relative_index].reference_z
            collapse_threshold = max(
                outcome_policy.minimum_collapse_altitude_m,
                evaluation_policy.collapse_altitude_fraction * reference_z,
            )
            if (
                reference_z > outcome_policy.minimum_airborne_reference_altitude_m
                and float(evaluation_samples[relative_index]["z"]) < collapse_threshold
            ):
                collapse_run += 1
                if collapse_run >= evaluation_policy.consecutive_samples:
                    crash_flag = True
                    crash_reason = "altitude_collapse_in_evaluation_window"
                    crash_sample_index = start_index + relative_index
                    break
            else:
                collapse_run = 0

    maximum_position_speed = 0.0
    speed_instability_index: int | None = None
    for relative_index in range(1, len(evaluation_samples)):
        previous = evaluation_samples[relative_index - 1]
        current = evaluation_samples[relative_index]
        delta_t = float(current["t"]) - float(previous["t"])
        position_speed = (
            math.dist(
                (
                    float(current["x"]),
                    float(current["y"]),
                    float(current["z"]),
                ),
                (
                    float(previous["x"]),
                    float(previous["y"]),
                    float(previous["z"]),
                ),
            )
            / delta_t
        )
        maximum_position_speed = max(
            maximum_position_speed,
            position_speed,
        )
        if (
            speed_instability_index is None
            and position_speed > outcome_policy.maximum_position_speed_mps
        ):
            speed_instability_index = start_index + relative_index
    instability_reasons: list[str] = []
    instability_indices: list[int] = []
    if speed_instability_index is not None:
        instability_reasons.append("position_speed_exceeded")
        instability_indices.append(speed_instability_index)
    if raw_max_error > outcome_policy.maximum_stable_track_error_m:
        instability_reasons.append("track_error_exceeded")
        instability_indices.append(start_index + evaluation_errors.index(raw_max_error))
    instability_flag = bool(instability_reasons)
    instability_first_sample_index = min(instability_indices) if instability_indices else None

    full_progress = _evaluate_track_progress(
        samples,
        projections,
        geometry,
        max_track_error=evaluation_policy.near_track_threshold_m,
        policy=outcome_policy,
    )
    evaluation_progress = _evaluate_track_progress(
        evaluation_samples,
        evaluation_projections,
        geometry,
        max_track_error=evaluation_policy.near_track_threshold_m,
        policy=outcome_policy,
    )
    backward_tolerance = max(
        outcome_policy.backward_tolerance_m,
        geometry.total_length * outcome_policy.backward_tolerance_track_fraction,
    )
    endpoint_tolerance = max(
        outcome_policy.endpoint_tolerance_m,
        geometry.total_length * outcome_policy.endpoint_tolerance_track_fraction,
    )
    start_progress = evaluation_progress.start_progress
    end_progress = evaluation_progress.end_progress
    final_reference = reference_points[-1]
    final_sample = evaluation_samples[-1]
    final_error = math.dist(
        (
            float(final_sample["x"]),
            float(final_sample["y"]),
            float(final_sample["z"]),
        ),
        (
            final_reference["x"],
            final_reference["y"],
            final_reference["z"],
        ),
    )
    if geometry.closed:
        start_reached = (
            start_progress is not None
            and min(
                start_progress,
                abs(geometry.total_length - start_progress),
            )
            <= endpoint_tolerance
        )
        endpoint_reached = final_error <= evaluation_policy.pass_max_error_m
    else:
        start_reached = start_progress is not None and start_progress <= endpoint_tolerance
        endpoint_reached = (
            end_progress is not None
            and end_progress >= geometry.total_length - endpoint_tolerance
            and final_error <= evaluation_policy.pass_max_error_m
        )
    direction_valid = evaluation_progress.backward_distance <= backward_tolerance
    progress_contract_ok = (
        direction_valid
        and evaluation_progress.discontinuity_count == 0
        and evaluation_progress.directed_progress_fraction
        >= evaluation_policy.minimum_track_coverage
        and start_reached
        and endpoint_reached
    )
    scenario_state = _scenario_effect_state(
        scenario_effect_request_payload,
        scenario_effect_evidence_payload,
    )
    timeout_flag = False
    pass_flag = (
        not crash_flag
        and not timeout_flag
        and not instability_flag
        and raw_rmse <= evaluation_policy.pass_rmse_m
        and raw_max_error <= evaluation_policy.pass_max_error_m
        and evaluation_progress.coverage >= evaluation_policy.minimum_track_coverage
        and progress_contract_ok
        and scenario_state.ready
    )
    penalty = 0.0
    if crash_flag:
        penalty += outcome_policy.crash_penalty
    if timeout_flag:
        penalty += outcome_policy.timeout_penalty
    if instability_flag:
        penalty += outcome_policy.instability_penalty
    if (
        evaluation_progress.coverage < evaluation_policy.minimum_track_coverage
        or not progress_contract_ok
    ):
        penalty += outcome_policy.progress_penalty
    rmse_component = round(raw_rmse, 12)
    max_error_component = round(
        outcome_policy.max_error_score_weight * raw_max_error,
        12,
    )
    duration_component = round(
        outcome_policy.duration_score_weight * evaluation_duration,
        12,
    )
    payload: dict[str, Any] = {
        "schema_id": PX4_OUTCOME_EVIDENCE_V1,
        "verifier_revision": PX4_OUTCOME_VERIFIER_REVISION,
        "outcome_policy_id": outcome_policy.policy_id,
        "evaluation_policy_id": evaluation_policy.policy_id,
        "evaluation_window_evidence_id": (evaluation_window_evidence.evidence_id),
        "core_metric_evidence_id": (core_metric_evidence.evidence_id),
        "telemetry_contract_id": telemetry_contract_id,
        "reference_track_sha256": reference_track_sha256,
        "scenario_effect_request_sha256": (scenario_state.request_sha256),
        "scenario_effect_evidence_sha256": (scenario_state.evidence_sha256),
        "synthetic": synthetic,
        "requested_effects": scenario_state.requested_effects,
        "applied_effects": scenario_state.applied_effects,
        "scenario_effect_status": scenario_state.status,
        "scenario_effects_ready": scenario_state.ready,
        "crash_flag": crash_flag,
        "crash_reason": crash_reason,
        "crash_sample_index": crash_sample_index,
        "timeout_flag": timeout_flag,
        "instability_flag": instability_flag,
        "instability_reasons": tuple(instability_reasons),
        "instability_first_sample_index": (instability_first_sample_index),
        "maximum_observed_position_speed_mps": round(
            maximum_position_speed,
            6,
        ),
        "full_track_coverage": round(full_progress.coverage, 6),
        "evaluation_track_coverage": round(
            evaluation_progress.coverage,
            6,
        ),
        "evaluation_directed_progress_fraction": round(
            evaluation_progress.directed_progress_fraction,
            6,
        ),
        "evaluation_backward_distance_m": round(
            evaluation_progress.backward_distance,
            6,
        ),
        "evaluation_progress_discontinuity_count": (evaluation_progress.discontinuity_count),
        "evaluation_direction_valid": direction_valid,
        "evaluation_start_reached": start_reached,
        "evaluation_endpoint_reached": endpoint_reached,
        "evaluation_progress_contract_ok": progress_contract_ok,
        "track_length_3d_m": round(geometry.total_length, 6),
        "track_is_closed": geometry.closed,
        "evaluation_min_z_m": round(
            min(float(sample["z"]) for sample in evaluation_samples),
            6,
        ),
        "evaluation_max_z_m": round(
            max(float(sample["z"]) for sample in evaluation_samples),
            6,
        ),
        "pass_flag": pass_flag,
        "score_rmse_component": rmse_component,
        "score_max_error_component": max_error_component,
        "score_duration_component": duration_component,
        "score_penalty": penalty,
        "score": round(
            rmse_component + max_error_component + duration_component + penalty,
            6,
        ),
    }
    evidence = Px4OutcomeEvidenceV1.model_validate({"evidence_id": _sha256_id(payload), **payload})
    return outcome_policy, evidence


def require_px4_outcome_binding(
    metrics: Mapping[str, object],
    *,
    policy: Px4OutcomePolicyV1,
    evidence: Px4OutcomeEvidenceV1,
) -> None:
    raw_metrics = metrics.get("raw_metric_json")
    if not isinstance(raw_metrics, Mapping):
        raise Px4CoreMetricEvidenceError("PX4 raw metrics must be an object")
    expected_top_level = {
        "crash_flag": evidence.crash_flag,
        "timeout_flag": evidence.timeout_flag,
        "instability_flag": evidence.instability_flag,
        "pass_flag": evidence.pass_flag,
        "score": evidence.score,
    }
    if any(metrics.get(field) != value for field, value in expected_top_level.items()):
        raise Px4CoreMetricEvidenceError(
            "PX4 top-level verdict does not match independent evidence"
        )
    stationary_hover = evidence.track_length_3d_m == 0.0
    expected_raw = {
        "track_coverage": evidence.full_track_coverage,
        "evaluation_track_coverage": (evidence.evaluation_track_coverage),
        "evaluation_directed_progress_fraction": (evidence.evaluation_directed_progress_fraction),
        "evaluation_backward_distance_m": (evidence.evaluation_backward_distance_m),
        "evaluation_progress_discontinuity_count": (
            evidence.evaluation_progress_discontinuity_count
        ),
        "evaluation_direction_valid": (evidence.evaluation_direction_valid),
        "evaluation_start_reached": (evidence.evaluation_start_reached),
        "evaluation_endpoint_reached": (evidence.evaluation_endpoint_reached),
        "evaluation_progress_contract_ok": (evidence.evaluation_progress_contract_ok),
        "track_length_3d_m": evidence.track_length_3d_m,
        "track_is_closed": evidence.track_is_closed,
        "track_projection": (
            "stationary_point_3d_projection"
            if stationary_hover
            else "ordered_local_3d_segment_projection"
        ),
        "track_projection_comparison_limit": (_MAX_PROJECTION_SEGMENT_COMPARISONS),
        "coverage_basis": (
            "stationary_hover_time_in_tolerance"
            if stationary_hover
            else "union_of_traversed_polyline_arc_length"
        ),
        "evaluation_min_z": evidence.evaluation_min_z_m,
        "evaluation_max_z": evidence.evaluation_max_z_m,
        "crash_reason": evidence.crash_reason,
        "scenario_effects_ready": evidence.scenario_effects_ready,
        "scenario_effect_status": evidence.scenario_effect_status,
        "scenario_effect_request_sha256": (evidence.scenario_effect_request_sha256),
        "scenario_effect_evidence_sha256": (evidence.scenario_effect_evidence_sha256),
        "px4_outcome_policy": policy.model_dump(mode="json"),
        "px4_outcome_evidence": evidence.model_dump(mode="json"),
    }
    if stationary_hover:
        expected_raw.update(
            {
                "track_mode": "stationary_hover",
                "hover_minimum_evaluation_duration_s": (
                    _HOVER_MIN_EVALUATION_DURATION_SECONDS
                ),
            }
        )
    if any(raw_metrics.get(field) != value for field, value in expected_raw.items()):
        raise Px4CoreMetricEvidenceError(
            "PX4 raw verdict does not match independent outcome evidence"
        )


__all__ = [
    "PX4_CORE_METRIC_EVIDENCE_V1",
    "PX4_CORE_METRIC_VERIFIER_REVISION",
    "PX4_EVALUATION_POLICY_V1",
    "PX4_EVALUATION_WINDOW_EVIDENCE_V1",
    "PX4_EVALUATION_WINDOW_VERIFIER_REVISION",
    "PX4_OUTCOME_EVIDENCE_V1",
    "PX4_OUTCOME_POLICY_V1",
    "PX4_OUTCOME_VERIFIER_REVISION",
    "PX4_PROGRESS_REVISION",
    "PX4_RMSE_INTEGRATION_REVISION",
    "PX4_SCORE_REVISION",
    "PX4_TRACK_PROJECTION_REVISION",
    "Px4CoreMetricEvidenceError",
    "Px4CoreMetricEvidenceV1",
    "Px4EvaluationPolicyV1",
    "Px4EvaluationWindowEvidenceV1",
    "Px4MaxErrorSampleV1",
    "Px4OutcomeEvidenceV1",
    "Px4OutcomePolicyV1",
    "compile_px4_core_metric_evidence",
    "compile_px4_evaluation_policy",
    "compile_px4_evaluation_window_evidence",
    "compile_px4_outcome_evidence",
    "compile_px4_outcome_policy",
    "px4_evaluation_policy_from_environment",
    "require_px4_core_metric_binding",
    "require_px4_evaluation_window_binding",
    "require_px4_outcome_binding",
]
