"""Abstract simulator adapter + data classes.

The trial executor passes a :class:`TrialContext` into the adapter. The
adapter prepares its backend (``prepare``), runs the trial (``run_trial``),
and cleans up (``cleanup``). On success it returns a :class:`TrialResult`
with metrics and artifact metadata. On failure it returns a
:class:`TrialResult` with ``success=False`` and a :class:`TrialFailure`
payload describing the structured error — it never raises for domain
failures (timeout, unstable candidate, simulation failed).

Only *infrastructure* errors (e.g. the real adapter being unavailable) are
surfaced via exceptions; the trial executor wraps those into trial-level
``SIM_ERROR`` failures.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Event
from typing import Any

# --- Failure codes ---------------------------------------------------------
#
# Kept as string constants so they are easy to assert on in tests and stable
# in persisted ``Trial.failure_code`` values. The API contract (trial detail)
# treats these as opaque strings.

FAILURE_TIMEOUT = "TIMEOUT"
FAILURE_SIMULATION = "SIMULATION_FAILED"
FAILURE_UNSTABLE = "UNSTABLE_CANDIDATE"
FAILURE_SIM_ERROR = "SIM_ERROR"
FAILURE_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
FAILURE_CANCELLED = "CANCELLED"
FAILURE_ARTIFACT_PERSISTENCE = "ARTIFACT_PERSISTENCE_FAILED"
FAILURE_RESULT_PERSISTENCE = "RESULT_PERSISTENCE_FAILED"
FAILURE_INVALID_PARAMETERS = "INVALID_CANDIDATE_PARAMETERS"
FAILURE_INVALID_RESULT = "INVALID_SIMULATOR_RESULT"
FAILURE_INPUT_EVIDENCE_DRIFT = "INPUT_EVIDENCE_DRIFT"
FAILURE_UNVERIFIED_REPORT = "UNVERIFIED_SIMULATOR_FAILURE"
FAILURE_EXECUTION_TIMEOUT = "SIMULATOR_EXECUTION_TIMEOUT"

_MAX_RAW_METRIC_DEPTH = 20
_MAX_RAW_METRIC_NODES = 10_000
_MAX_RAW_METRIC_TEXT_CHARS = 10 * 1024 * 1024


def _validate_raw_metric_json(payload: dict[str, Any]) -> None:
    """Reject non-JSON, non-finite, or pathologically large metric payloads."""

    stack: list[tuple[object, int]] = [(payload, 0)]
    nodes = 0
    text_chars = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_RAW_METRIC_NODES:
            raise ValueError("raw_metric_json exceeds the node limit")
        if depth > _MAX_RAW_METRIC_DEPTH:
            raise ValueError("raw_metric_json exceeds the nesting limit")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("raw_metric_json object keys must be strings")
            text_chars += sum(len(key) for key in value)
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, str):
            text_chars += len(value)
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("raw_metric_json numbers must be finite")
        elif value is not None and not isinstance(value, (bool, int)):
            raise ValueError("raw_metric_json must contain only JSON-compatible values")
        if text_chars > _MAX_RAW_METRIC_TEXT_CHARS:
            raise ValueError("raw_metric_json exceeds the text-size limit")


# --- Value objects ---------------------------------------------------------


@dataclass(frozen=True)
class JobConfig:
    """Immutable snapshot of the Job fields the simulator cares about."""

    track_type: str
    start_point_x: float
    start_point_y: float
    altitude_m: float
    wind_north: float
    wind_east: float
    wind_south: float
    wind_west: float
    sensor_noise_level: str
    objective_profile: str
    reference_track: list[dict[str, float]] | None = None
    vehicle_profile: dict[str, Any] = field(default_factory=dict)
    parameter_catalog_version: str | None = None
    selected_parameter_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrialContext:
    """All inputs required to run one trial through the adapter."""

    trial_id: str
    job_id: str
    job_config: JobConfig
    candidate_id: str
    parameters: dict[str, Any]
    seed: int
    scenario_type: str
    scenario_config: dict[str, Any] | None = None
    attempt_count: int = 1
    cancellation_event: Event | None = field(default=None, compare=False, repr=False)

    def cancellation_requested(self) -> bool:
        """Return whether the worker no longer owns this execution attempt."""

        return self.cancellation_event is not None and self.cancellation_event.is_set()


@dataclass
class TrialMetricsPayload:
    """TrialMetric-compatible values returned by the adapter."""

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
    raw_metric_json: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("rmse", "max_error", "completion_time", "score", "final_error"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        for name in ("rmse", "max_error", "completion_time", "final_error"):
            if float(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if (
            isinstance(self.overshoot_count, bool)
            or not isinstance(self.overshoot_count, int)
            or self.overshoot_count < 0
        ):
            raise ValueError("overshoot_count must be a non-negative integer")
        for name in (
            "crash_flag",
            "timeout_flag",
            "pass_flag",
            "instability_flag",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be boolean")
        if not isinstance(self.raw_metric_json, dict):
            raise TypeError("raw_metric_json must be an object")
        _validate_raw_metric_json(self.raw_metric_json)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rmse": self.rmse,
            "max_error": self.max_error,
            "overshoot_count": self.overshoot_count,
            "completion_time": self.completion_time,
            "crash_flag": self.crash_flag,
            "timeout_flag": self.timeout_flag,
            "score": self.score,
            "final_error": self.final_error,
            "pass_flag": self.pass_flag,
            "instability_flag": self.instability_flag,
            "raw_metric_json": dict(self.raw_metric_json),
        }


@dataclass
class ArtifactMetadata:
    """Metadata for a single artifact produced during a trial.

    Matches the ``Artifact`` ORM model's writable fields. Actual bytes may or
    may not exist on disk in the MVP — ``storage_path`` is still required so
    future phases can render real files without schema churn.
    """

    artifact_type: str
    display_name: str
    storage_path: str
    mime_type: str | None = None
    file_size_bytes: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.artifact_type, str)
            or not self.artifact_type.strip()
            or len(self.artifact_type.strip()) > 32
            or any(
                not (char.isalnum() or char in {"-", "_", "."})
                for char in self.artifact_type.strip()
            )
        ):
            raise ValueError("artifact_type is invalid")
        self.artifact_type = self.artifact_type.strip()
        if (
            not isinstance(self.display_name, str)
            or not self.display_name.strip()
            or len(self.display_name.strip()) > 255
            or any(ord(char) < 32 for char in self.display_name)
        ):
            raise ValueError("display_name is invalid")
        self.display_name = self.display_name.strip()
        if (
            not isinstance(self.storage_path, str)
            or not self.storage_path.strip()
            or len(self.storage_path.strip()) > 512
            or any(ord(char) < 32 for char in self.storage_path)
        ):
            raise ValueError("storage_path is invalid")
        self.storage_path = self.storage_path.strip()
        if self.mime_type is not None and (
            not isinstance(self.mime_type, str)
            or not self.mime_type.strip()
            or len(self.mime_type.strip()) > 128
            or any(ord(char) < 32 for char in self.mime_type)
        ):
            raise ValueError("mime_type is invalid")
        if isinstance(self.mime_type, str):
            self.mime_type = self.mime_type.strip()
        if self.file_size_bytes is not None and (
            isinstance(self.file_size_bytes, bool)
            or not isinstance(self.file_size_bytes, int)
            or not 0 <= self.file_size_bytes <= 9_223_372_036_854_775_807
        ):
            raise ValueError("file_size_bytes must be a non-negative signed 64-bit integer")


@dataclass
class TrialFailure:
    """Structured failure info returned when a trial does not complete."""

    code: str
    reason: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or not self.code.strip()
            or len(self.code.strip()) > 64
            or any(ord(char) < 32 for char in self.code)
        ):
            raise ValueError("failure code is invalid")
        if (
            not isinstance(self.reason, str)
            or not self.reason.strip()
            or len(self.reason) > 8192
            or any(char in {"\x00", "\r"} for char in self.reason)
        ):
            raise ValueError("failure reason is invalid")
        self.code = self.code.strip()
        self.reason = self.reason.strip()


@dataclass
class TrialResult:
    """Full adapter output for one trial."""

    success: bool
    backend: str
    metrics: TrialMetricsPayload | None = None
    artifacts: list[ArtifactMetadata] = field(default_factory=list)
    failure: TrialFailure | None = None
    log_excerpt: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise TypeError("success must be boolean")
        if (
            not isinstance(self.backend, str)
            or not self.backend.strip()
            or len(self.backend.strip()) > 64
            or any(ord(char) < 32 for char in self.backend)
        ):
            raise ValueError("backend is invalid")
        self.backend = self.backend.strip()
        if self.success:
            if self.metrics is None or self.failure is not None:
                raise ValueError("successful trial results require metrics and forbid failure")
        elif self.failure is None or self.metrics is not None:
            raise ValueError("failed trial results require failure and forbid metrics")
        if not isinstance(self.artifacts, list) or any(
            not isinstance(artifact, ArtifactMetadata) for artifact in self.artifacts
        ):
            raise TypeError("artifacts must be a list of ArtifactMetadata")
        if len(self.artifacts) > 256:
            raise ValueError("artifacts cannot contain more than 256 items")
        if self.log_excerpt is not None and (
            not isinstance(self.log_excerpt, str) or len(self.log_excerpt) > 65_536
        ):
            raise ValueError("log_excerpt is invalid")


# --- Abstract adapter ------------------------------------------------------


class SimulatorAdapter(ABC):
    """Interface every simulator backend must implement.

    The lifecycle per trial is ``prepare -> run_trial -> cleanup``. Adapters
    may no-op any step; the trial executor always calls all three so future
    backends (PX4/Gazebo) can allocate/release resources safely.
    """

    #: Short identifier persisted in ``Trial.simulator_backend``.
    backend_name: str = "abstract"

    def prepare(self, ctx: TrialContext) -> None:  # noqa: B027 — optional hook
        """Hook for per-trial setup (world init, sensors, etc.). No-op default."""

    @abstractmethod
    def run_trial(self, ctx: TrialContext) -> TrialResult:
        """Execute the trial and return a :class:`TrialResult`."""

    def cleanup(self, ctx: TrialContext) -> None:  # noqa: B027 — optional hook
        """Hook for per-trial teardown. No-op default."""

    def finalize_trial(self, ctx: TrialContext, result: TrialResult | None) -> None:  # noqa: B027 — optional hook
        """Release persisted run data after the executor stores artifacts.

        This hook deliberately runs *after* artifact persistence. ``cleanup``
        remains the place to stop simulator processes and release transient
        resources immediately after execution.
        """

        _ = ctx, result


__all__ = [
    "FAILURE_ADAPTER_UNAVAILABLE",
    "FAILURE_ARTIFACT_PERSISTENCE",
    "FAILURE_RESULT_PERSISTENCE",
    "FAILURE_INVALID_PARAMETERS",
    "FAILURE_INVALID_RESULT",
    "FAILURE_UNVERIFIED_REPORT",
    "FAILURE_EXECUTION_TIMEOUT",
    "FAILURE_CANCELLED",
    "FAILURE_SIMULATION",
    "FAILURE_SIM_ERROR",
    "FAILURE_TIMEOUT",
    "FAILURE_UNSTABLE",
    "ArtifactMetadata",
    "JobConfig",
    "SimulatorAdapter",
    "TrialContext",
    "TrialFailure",
    "TrialMetricsPayload",
    "TrialResult",
]
