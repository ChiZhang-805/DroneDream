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

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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


@dataclass
class TrialFailure:
    """Structured failure info returned when a trial does not complete."""

    code: str
    reason: str


@dataclass
class TrialResult:
    """Full adapter output for one trial."""

    success: bool
    backend: str
    metrics: TrialMetricsPayload | None = None
    artifacts: list[ArtifactMetadata] = field(default_factory=list)
    failure: TrialFailure | None = None
    log_excerpt: str | None = None


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


__all__ = [
    "FAILURE_ADAPTER_UNAVAILABLE",
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
