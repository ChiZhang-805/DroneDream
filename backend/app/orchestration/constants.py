"""Phase 3 orchestration constants — baseline parameters and trial scenarios.

These live as plain dicts/lists so they are easy to JSON-serialise into
CandidateParameterSet.parameter_json and Trial.scenario_config_json. The real
optimizer in Phase 5 will generate additional CandidateParameterSet rows with
the same ``kp_xy``/``kd_xy``/... shape.
"""

from __future__ import annotations

from typing import Any

# Whitelisted baseline controller parameters. Keep this a flat numeric dict —
# the mock metrics function treats it as a ``dict[str, float]`` and the future
# optimizer will vary these keys.
BASELINE_PARAMETERS: dict[str, float] = {
    "kp_xy": 1.0,
    "kd_xy": 0.2,
    "ki_xy": 0.05,
    "vel_limit": 5.0,
    "accel_limit": 4.0,
    "disturbance_rejection": 0.5,
}

# Scenarios dispatched for the baseline candidate. One trial per scenario gives
# a small-but-meaningful sample of stable/perturbed conditions; Phase 5 will
# increase this and add scenarios for optimizer candidates.
BASELINE_SCENARIOS: list[str] = [
    "nominal",
    "noise_perturbed",
    "wind_perturbed",
    "combined_perturbed",
]

# Deterministic per-scenario seeds. Using fixed seeds keeps Phase 3 output
# reproducible so tests can assert specific metric values.
SCENARIO_SEEDS: dict[str, int] = {
    "nominal": 101,
    "noise_perturbed": 202,
    "wind_perturbed": 303,
    "combined_perturbed": 404,
}


def baseline_scenario_config(scenario: str) -> dict[str, Any]:
    """Return the scenario_config_json stored on a baseline trial."""

    return {"scenario": scenario, "source": "phase3_mock"}
