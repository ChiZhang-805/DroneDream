"""Content-addressed semantic contract for metric-bearing telemetry."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TELEMETRY_SCHEMA_V2 = "dronedream.telemetry.v2"
TELEMETRY_SEMANTIC_CONTRACT_V1 = (
    "dronedream.telemetry-semantic-contract/v1"
)
TELEMETRY_VERIFIER_REVISION = "telemetry-semantic-verifier-1.0"

MIN_SAMPLING_COVERAGE = 0.8
MIN_MAX_GAP_SECONDS = 0.5
MAX_MEDIAN_GAP_MULTIPLIER = 10.0

Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
NonnegativeInt = Annotated[int, Field(ge=0)]
NonnegativeFloat = Annotated[float, Field(ge=0.0)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]


class TelemetrySemanticContractError(ValueError):
    """Raised when telemetry cannot satisfy the trusted semantic contract."""


class TelemetrySamplingEvidenceV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    sample_count: NonnegativeInt
    start_time_s: float
    end_time_s: float
    duration_s: NonnegativeFloat
    median_interval_s: NonnegativeFloat
    max_gap_s: NonnegativeFloat
    max_gap_limit_s: NonnegativeFloat
    sampling_coverage: UnitInterval
    minimum_sampling_coverage: UnitInterval = MIN_SAMPLING_COVERAGE

    @model_validator(mode="after")
    def _validate_sampling(self) -> TelemetrySamplingEvidenceV1:
        if self.end_time_s < self.start_time_s:
            raise ValueError("telemetry end time precedes start time")
        if self.sample_count <= 1:
            if any(
                value != 0.0
                for value in (
                    self.duration_s,
                    self.median_interval_s,
                    self.max_gap_s,
                )
            ):
                raise ValueError(
                    "single-sample telemetry cannot claim an interval"
                )
        elif self.duration_s <= 0 or self.median_interval_s <= 0:
            raise ValueError(
                "multi-sample telemetry requires positive duration and interval"
            )
        return self


class TelemetrySemanticContractV1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )

    schema_id: Literal[
        "dronedream.telemetry-semantic-contract/v1"
    ] = "dronedream.telemetry-semantic-contract/v1"
    contract_id: Sha256Id
    verifier_revision: Literal[
        "telemetry-semantic-verifier-1.0"
    ] = "telemetry-semantic-verifier-1.0"
    position_unit: Literal["m"] = "m"
    velocity_unit: Literal["m/s"] = "m/s"
    attitude_unit: Literal["rad"] = "rad"
    time_unit: Literal["s"] = "s"
    coordinate_frame: Literal[
        "dronedream_local_cartesian_z_up"
    ] = "dronedream_local_cartesian_z_up"
    time_origin: Literal[
        "relative_to_source_start"
    ] = "relative_to_source_start"
    source_kind: Literal[
        "launcher_json",
        "launcher_csv",
        "px4_ulog",
        "runner_dry_run",
    ]
    source_sha256: Sha256Id
    source_byte_count: NonnegativeInt
    extraction_revision: str = Field(min_length=1, max_length=128)
    samples_sha256: Sha256Id
    synthetic: bool
    sampling: TelemetrySamplingEvidenceV1
    origin_source_sha256: Sha256Id | None = None
    origin_source_byte_count: NonnegativeInt | None = None
    origin_extraction_revision: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    origin_coordinate_frame: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    coordinate_transform: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )

    @model_validator(mode="after")
    def _validate_origin_provenance(self) -> TelemetrySemanticContractV1:
        origin_values = (
            self.origin_source_sha256,
            self.origin_source_byte_count,
            self.origin_extraction_revision,
            self.origin_coordinate_frame,
            self.coordinate_transform,
        )
        if any(value is not None for value in origin_values) and not all(
            value is not None for value in origin_values
        ):
            raise ValueError(
                "origin telemetry provenance must be complete or absent"
            )
        if self.source_kind == "px4_ulog" and not all(
            value is not None for value in origin_values
        ):
            raise ValueError(
                "PX4 ULog telemetry requires complete origin provenance"
            )
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _finite_time(sample: object, *, index: int) -> float:
    if not isinstance(sample, Mapping):
        raise TelemetrySemanticContractError(
            f"telemetry sample {index} must be an object"
        )
    raw = sample.get("t")
    if (
        isinstance(raw, bool)
        or not isinstance(raw, int | float)
        or not math.isfinite(float(raw))
    ):
        raise TelemetrySemanticContractError(
            f"telemetry sample {index} requires finite time"
        )
    return float(raw)


def compile_sampling_evidence(
    samples: Sequence[object],
) -> TelemetrySamplingEvidenceV1:
    if not samples:
        raise TelemetrySemanticContractError(
            "telemetry samples cannot be empty"
        )
    times = [
        _finite_time(sample, index=index)
        for index, sample in enumerate(samples)
    ]
    gaps: list[float] = []
    for index, (previous, current) in enumerate(
        zip(times, times[1:], strict=False),
        start=1,
    ):
        gap = current - previous
        if gap <= 0:
            raise TelemetrySemanticContractError(
                f"telemetry sample {index} time is not strictly increasing"
            )
        gaps.append(gap)
    if not gaps:
        return TelemetrySamplingEvidenceV1(
            sample_count=1,
            start_time_s=times[0],
            end_time_s=times[0],
            duration_s=0.0,
            median_interval_s=0.0,
            max_gap_s=0.0,
            max_gap_limit_s=MIN_MAX_GAP_SECONDS,
            sampling_coverage=1.0,
        )
    duration = times[-1] - times[0]
    median_interval = float(statistics.median(gaps))
    max_gap = max(gaps)
    max_gap_limit = max(
        MIN_MAX_GAP_SECONDS,
        MAX_MEDIAN_GAP_MULTIPLIER * median_interval,
    )
    coverage = min(
        1.0,
        ((len(times) - 1) * median_interval) / duration,
    )
    return TelemetrySamplingEvidenceV1(
        sample_count=len(times),
        start_time_s=round(times[0], 12),
        end_time_s=round(times[-1], 12),
        duration_s=round(duration, 12),
        median_interval_s=round(median_interval, 12),
        max_gap_s=round(max_gap, 12),
        max_gap_limit_s=round(max_gap_limit, 12),
        sampling_coverage=round(coverage, 12),
    )


def require_sampling_quality(
    sampling: TelemetrySamplingEvidenceV1,
    *,
    synthetic: bool,
) -> None:
    if synthetic and sampling.sample_count == 1:
        return
    if sampling.sample_count < 2 or sampling.duration_s <= 0:
        raise TelemetrySemanticContractError(
            "metric-bearing telemetry requires at least two timed samples"
        )
    if sampling.max_gap_s > sampling.max_gap_limit_s + 1e-12:
        raise TelemetrySemanticContractError(
            "telemetry maximum gap exceeds its semantic contract"
        )
    if (
        sampling.sampling_coverage
        + 1e-12
        < sampling.minimum_sampling_coverage
    ):
        raise TelemetrySemanticContractError(
            "telemetry sampling coverage is below its semantic contract"
        )


def compile_telemetry_semantic_contract(
    *,
    samples: Sequence[object],
    source_bytes: bytes,
    source_kind: str,
    extraction_revision: str,
    synthetic: bool,
    origin_provenance: Mapping[str, object] | None = None,
) -> TelemetrySemanticContractV1:
    sampling = compile_sampling_evidence(samples)
    require_sampling_quality(sampling, synthetic=synthetic)
    origin = dict(origin_provenance or {})
    payload: dict[str, Any] = {
        "schema_id": TELEMETRY_SEMANTIC_CONTRACT_V1,
        "verifier_revision": TELEMETRY_VERIFIER_REVISION,
        "position_unit": "m",
        "velocity_unit": "m/s",
        "attitude_unit": "rad",
        "time_unit": "s",
        "coordinate_frame": "dronedream_local_cartesian_z_up",
        "time_origin": "relative_to_source_start",
        "source_kind": source_kind,
        "source_sha256": sha256_bytes(source_bytes),
        "source_byte_count": len(source_bytes),
        "extraction_revision": extraction_revision,
        "samples_sha256": _sha256_id(list(samples)),
        "synthetic": synthetic,
        "sampling": sampling.model_dump(mode="json"),
        "origin_source_sha256": origin.get("origin_source_sha256"),
        "origin_source_byte_count": origin.get(
            "origin_source_byte_count"
        ),
        "origin_extraction_revision": origin.get(
            "origin_extraction_revision"
        ),
        "origin_coordinate_frame": origin.get(
            "origin_coordinate_frame"
        ),
        "coordinate_transform": origin.get("coordinate_transform"),
    }
    return TelemetrySemanticContractV1.model_validate(
        {"contract_id": _sha256_id(payload), **payload}
    )


def verify_telemetry_semantic_contract(
    payload: object,
) -> TelemetrySemanticContractV1 | None:
    if not isinstance(payload, Mapping):
        return None
    samples = payload.get("samples")
    raw_contract = payload.get("semantic_contract")
    if (
        payload.get("schema_version") != TELEMETRY_SCHEMA_V2
        or not isinstance(samples, list)
    ):
        return None
    try:
        contract = TelemetrySemanticContractV1.model_validate(raw_contract)
        sampling = compile_sampling_evidence(samples)
        require_sampling_quality(
            sampling,
            synthetic=contract.synthetic,
        )
    except (
        TypeError,
        ValidationError,
        TelemetrySemanticContractError,
        ValueError,
    ):
        return None
    contract_payload = contract.model_dump(mode="json")
    contract_id = contract_payload.pop("contract_id")
    if (
        contract_id != _sha256_id(contract_payload)
        or contract.samples_sha256 != _sha256_id(samples)
        or contract.sampling != sampling
    ):
        return None
    return contract


__all__ = [
    "MAX_MEDIAN_GAP_MULTIPLIER",
    "MIN_MAX_GAP_SECONDS",
    "MIN_SAMPLING_COVERAGE",
    "TELEMETRY_SCHEMA_V2",
    "TELEMETRY_SEMANTIC_CONTRACT_V1",
    "TELEMETRY_VERIFIER_REVISION",
    "TelemetrySamplingEvidenceV1",
    "TelemetrySemanticContractError",
    "TelemetrySemanticContractV1",
    "compile_sampling_evidence",
    "compile_telemetry_semantic_contract",
    "require_sampling_quality",
    "sha256_bytes",
    "verify_telemetry_semantic_contract",
]
