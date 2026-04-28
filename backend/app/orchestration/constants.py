"""Orchestration constants — baseline parameters, safe ranges, and scenarios.

These live as plain dicts/lists so they are easy to JSON-serialise into
``CandidateParameterSet.parameter_json`` and ``Trial.scenario_config_json``.
Phase 5 adds optimizer-specific scenarios, per-parameter safe ranges, and the
aggregation scoring weights — all in one module so tests and the optimizer can
reference a single source of truth.
"""

from __future__ import annotations

from typing import Any

# Whitelisted baseline controller parameters. The mock adapter treats this as
# a ``dict[str, float]`` and the optimizer varies only these keys — we do not
# expose arbitrary PX4 parameter editing.
BASELINE_PARAMETERS: dict[str, float] = {
    "kp_xy": 1.0,
    "kd_xy": 0.2,
    "ki_xy": 0.05,
    "vel_limit": 5.0,
    "accel_limit": 4.0,
    "disturbance_rejection": 0.5,
}

# Safe ranges the optimizer must not escape. Anything it proposes is clamped
# into ``[lo, hi]`` before being persisted.
PARAMETER_SAFE_RANGES: dict[str, tuple[float, float]] = {
    "kp_xy": (0.3, 2.5),
    "kd_xy": (0.05, 0.8),
    "ki_xy": (0.0, 0.25),
    "vel_limit": (2.0, 10.0),
    "accel_limit": (2.0, 8.0),
    "disturbance_rejection": (0.0, 1.0),
}

# Scenarios dispatched for the baseline candidate. One trial per scenario.
BASELINE_SCENARIOS: list[str] = [
    "nominal",
    "noise_perturbed",
    "wind_perturbed",
    "combined_perturbed",
]

# Deterministic per-scenario seeds for baseline trials. Fixed seeds keep
# baseline metrics reproducible so tests can assert on them.
SCENARIO_SEEDS: dict[str, int] = {
    "nominal": 101,
    "noise_perturbed": 202,
    "wind_perturbed": 303,
    "combined_perturbed": 404,
}

# Scenarios dispatched for each optimizer candidate. Three trials per
# candidate satisfies the "3–5 trials per candidate" requirement while
# keeping the local demo fast. The scenario list is intentionally smaller
# than BASELINE_SCENARIOS so the optimizer loop is cheaper than the
# baseline sweep.
OPTIMIZER_SCENARIOS: list[str] = [
    "nominal",
    "noise_perturbed",
    "combined_perturbed",
]

# Target number of optimizer candidates generated per job (must be in
# [2, 5] per the Phase 5 directive).
OPTIMIZER_CANDIDATE_COUNT: int = 3

# Deterministic seed offset so optimizer trial seeds never collide with
# baseline trial seeds (baseline seeds live in the 100s–400s).
_OPTIMIZER_SEED_BASE = 10_000


def baseline_scenario_config(scenario: str) -> dict[str, Any]:
    """Return the ``scenario_config_json`` stored on a baseline trial."""

    return {"scenario": scenario, "source": "baseline"}


def optimizer_scenario_config(
    scenario: str, *, candidate_index: int, seed: int
) -> dict[str, Any]:
    """Return the ``scenario_config_json`` stored on an optimizer trial.

    Includes the candidate index so it's easy to trace which optimizer
    candidate a trial belongs to when reading the persisted JSON blob.
    """

    return {
        "scenario": scenario,
        "source": "optimizer",
        "candidate_index": candidate_index,
        "seed": seed,
    }


def with_advanced_scenario(
    scenario_config: dict[str, Any],
    advanced_scenario_config: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(scenario_config)
    payload["advanced_scenario_config"] = dict(advanced_scenario_config or {})
    return payload


def optimizer_seed_for(candidate_index: int, scenario: str) -> int:
    """Deterministic seed for one optimizer trial.

    Uses ``candidate_index`` so different optimizer candidates get different
    seeds, and mixes in the scenario name so trials within the same candidate
    also vary.
    """

    scenario_offset = sum(ord(c) for c in scenario)
    return _OPTIMIZER_SEED_BASE + candidate_index * 97 + scenario_offset


# --- Aggregation scoring ---------------------------------------------------
#
# Lower score is better. The formula is intentionally simple and deterministic
# so humans can reason about why one candidate won over another. See
# ``app.orchestration.aggregation._score_candidate`` for the canonical
# implementation.

SCORE_WEIGHTS: dict[str, float] = {
    "rmse": 1.0,
    "max_error": 0.5,
    "completion_time": 0.05,
    "crash": 2.0,
    "timeout": 1.5,
    "instability": 1.0,
    "failed_trial": 1.5,
}

# If a candidate has *fewer* completed trials than this fraction of its
# dispatched trials, it's considered too unreliable to win — the aggregator
# will mark it eligible=False and skip it during best-candidate selection.
MIN_COMPLETED_TRIAL_RATIO: float = 0.5
