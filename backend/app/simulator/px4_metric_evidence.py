"""Independent core-metric compiler for retained PX4 telemetry evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulator.telemetry_evidence import (
    TelemetrySamplingEvidenceV1,
    compile_sampling_evidence,
    verify_telemetry_semantic_contract,
)

PX4_CORE_METRIC_EVIDENCE_V1 = "dronedream.px4-core-metric-evidence/v1"
PX4_CORE_METRIC_VERIFIER_REVISION = "px4-core-metric-verifier-1.0"
PX4_TRACK_PROJECTION_REVISION = "ordered-local-3d-segment-projection-1.0"
PX4_RMSE_INTEGRATION_REVISION = "time_weighted_trapezoidal"

_PROJECTION_BACKTRACK_SEGMENTS = 16
_PROJECTION_FORWARD_SEGMENTS = 64
_PROJECTION_GLOBAL_RESCAN_INTERVAL = 256
_PROJECTION_GLOBAL_RESCAN_DISTANCE_M = 2.0
_PROJECTION_LOCAL_ERROR_FALLBACK_M = 5.0
_MAX_PROJECTION_SEGMENT_COMPARISONS = 10_000_000

Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
NonnegativeInt = Annotated[int, Field(ge=0)]
NonnegativeFloat = Annotated[float, Field(ge=0.0)]


class Px4CoreMetricEvidenceError(ValueError):
    """Raised when PX4 core metrics cannot be independently verified."""


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
    projection_revision: Literal["ordered-local-3d-segment-projection-1.0"] = (
        "ordered-local-3d-segment-projection-1.0"
    )
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


@dataclass(frozen=True)
class _TrackProjection:
    error: float
    segment_index: int
    progress: float
    reference_x: float
    reference_y: float
    reference_z: float


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
        samples.append(sample)
    return samples, contract.contract_id, contract.synthetic


def _build_track_geometry(
    ref_points: list[dict[str, float]],
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
    fraction = min(
        1.0,
        max(
            0.0,
            sum(offset[index] * segment.delta[index] for index in range(3)) / length_squared,
        ),
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
    geometry = _build_track_geometry(reference_points)
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
        "projection_revision": PX4_TRACK_PROJECTION_REVISION,
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


__all__ = [
    "PX4_CORE_METRIC_EVIDENCE_V1",
    "PX4_CORE_METRIC_VERIFIER_REVISION",
    "PX4_RMSE_INTEGRATION_REVISION",
    "PX4_TRACK_PROJECTION_REVISION",
    "Px4CoreMetricEvidenceError",
    "Px4CoreMetricEvidenceV1",
    "Px4MaxErrorSampleV1",
    "compile_px4_core_metric_evidence",
    "require_px4_core_metric_binding",
]
