"""Thin compatibility shim over the Phase 4 simulator adapter.

Historically this module owned the mock metrics function. Phase 4 moved the
actual computation into :class:`app.simulator.mock.MockSimulatorAdapter` so
that the trial executor can swap backends via ``SIMULATOR_BACKEND``. The
function below is preserved only so downstream code that still imports
``compute_mock_metrics`` keeps working — it now delegates to the adapter.
"""

from __future__ import annotations

from typing import Any

from app.simulator.base import JobConfig, TrialContext
from app.simulator.mock import MockSimulatorAdapter

_DEFAULT_JOB_CONFIG = JobConfig(
    track_type="circle",
    start_point_x=0.0,
    start_point_y=0.0,
    altitude_m=3.0,
    wind_north=0.0,
    wind_east=0.0,
    wind_south=0.0,
    wind_west=0.0,
    sensor_noise_level="medium",
    objective_profile="robust",
)


def compute_mock_metrics(
    *,
    parameters: dict[str, Any],
    scenario: str,
    seed: int,
    job_config: JobConfig | None = None,
) -> dict[str, Any]:
    """Return a deterministic mock metric payload for one trial.

    Preserved for backwards compatibility; new callers should use
    :class:`app.simulator.SimulatorAdapter` directly.
    """

    adapter = MockSimulatorAdapter()
    ctx = TrialContext(
        trial_id="shim",
        job_id="shim",
        job_config=job_config or _DEFAULT_JOB_CONFIG,
        candidate_id="shim",
        parameters=dict(parameters or {}),
        seed=seed,
        scenario_type=scenario,
        scenario_config=None,
    )
    result = adapter.run_trial(ctx)
    if not result.success or result.metrics is None:  # pragma: no cover — defensive
        raise RuntimeError("compute_mock_metrics shim received a failed trial result")
    payload = result.metrics.as_dict()
    payload.pop("raw_metric_json", None)
    return payload


__all__ = ["compute_mock_metrics"]
