"""Deterministic mock trial metrics.

Produces a ``TrialMetric``-shaped dict from ``(parameter_json, scenario, seed)``
so that the worker can run without PX4/Gazebo. The function is deterministic:
same inputs always produce the same outputs, which keeps Phase 3 tests stable
and gives the future optimizer a smooth fitness landscape to exercise.

Model (cheap but plausible):

* ``base_err`` shrinks as ``kp_xy`` approaches a sweet spot around 1.2 and
  ``kd_xy`` approaches 0.3.
* ``scenario_factor`` multiplies the base error depending on perturbation.
* A deterministic pseudo-random jitter is added based on ``seed`` so different
  scenarios of the same candidate are not identical.
"""

from __future__ import annotations

import random
from typing import Any

_SCENARIO_FACTOR: dict[str, float] = {
    "nominal": 1.00,
    "noise_perturbed": 1.30,
    "wind_perturbed": 1.45,
    "combined_perturbed": 1.80,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_mock_metrics(
    *,
    parameters: dict[str, Any],
    scenario: str,
    seed: int,
) -> dict[str, Any]:
    """Return a deterministic mock metric payload for one trial.

    The returned dict has exactly the keys stored on ``TrialMetric``:
    ``rmse``, ``max_error``, ``overshoot_count``, ``completion_time``,
    ``crash_flag``, ``timeout_flag``, ``score``, ``final_error``,
    ``pass_flag``, ``instability_flag``.
    """

    kp = float(parameters.get("kp_xy", 1.0))
    kd = float(parameters.get("kd_xy", 0.2))
    ki = float(parameters.get("ki_xy", 0.05))
    accel_limit = float(parameters.get("accel_limit", 4.0))
    disturbance = float(parameters.get("disturbance_rejection", 0.5))

    # Distance from a synthetic optimum. Abs so the landscape is a simple bowl.
    base_err = (
        abs(kp - 1.2) * 0.30
        + abs(kd - 0.30) * 0.20
        + abs(ki - 0.05) * 0.50
        + max(0.0, 3.5 - accel_limit) * 0.05
        + (1.0 - _clamp(disturbance, 0.0, 1.0)) * 0.10
        + 0.35
    )
    factor = _SCENARIO_FACTOR.get(scenario, 1.0)

    rng = random.Random(seed * 31 + sum(ord(c) for c in scenario))
    jitter = rng.uniform(-0.04, 0.04)

    rmse = max(0.05, base_err * factor + jitter)
    max_error = rmse * 2.1 + rng.uniform(0.0, 0.15)
    overshoot_count = max(0, int(rmse * 3.0))
    completion_time = 12.0 + rng.uniform(-0.4, 0.6)
    final_error = rmse * 0.55
    score = 1.0 / (1.0 + rmse)

    crash_flag = False
    timeout_flag = False
    instability_flag = rmse > 1.1
    pass_flag = (not instability_flag) and (not crash_flag) and (not timeout_flag)

    return {
        "rmse": round(rmse, 4),
        "max_error": round(max_error, 4),
        "overshoot_count": overshoot_count,
        "completion_time": round(completion_time, 3),
        "crash_flag": crash_flag,
        "timeout_flag": timeout_flag,
        "score": round(score, 4),
        "final_error": round(final_error, 4),
        "pass_flag": pass_flag,
        "instability_flag": instability_flag,
    }
