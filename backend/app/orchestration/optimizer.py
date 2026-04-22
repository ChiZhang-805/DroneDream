"""Optimizer service — generate CandidateParameterSet proposals around a baseline.

The optimizer is intentionally boring: it applies a fixed set of deterministic
multiplicative perturbations to the baseline parameter dict and returns the
resulting candidate proposals. It does NOT:

* execute trials directly,
* call the simulator,
* render UI,
* or touch the database. Persisting rows is the caller's job (see
  :mod:`app.orchestration.job_manager`).

The heuristic set and ordering are fixed so the full optimization loop is
reproducible — same baseline -> same candidates every time. That also makes
the MVP easy to reason about in tests. A real optimizer (Bayesian search,
CMA-ES, etc.) can replace ``_PERTURBATIONS`` later without touching any other
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.orchestration import constants

# Whitelisted parameter keys the optimizer is allowed to vary. The caller can
# pass any baseline dict; anything outside this set is ignored by the
# perturbation step but still copied verbatim into the candidate proposal so
# future per-job overrides keep propagating.
_TUNABLE_KEYS: tuple[str, ...] = (
    "kp_xy",
    "kd_xy",
    "ki_xy",
    "vel_limit",
    "accel_limit",
    "disturbance_rejection",
)


@dataclass(frozen=True)
class CandidateProposal:
    """One optimizer output: a label + parameter set + human-readable strategy."""

    generation_index: int
    label: str
    strategy: str
    parameters: dict[str, float]


# Fixed multiplicative perturbations applied to the baseline. Each entry
# produces exactly one CandidateProposal. Keeping this list between length
# 2 and 5 satisfies the Phase 5 directive; tests assert on the count so
# editing this list will flag the constraint if violated.
_PERTURBATIONS: tuple[tuple[str, str, dict[str, float]], ...] = (
    (
        "aggressive_tracking",
        "Stiffer gains, tighter velocity envelope — favors low RMSE on "
        "nominal/noise scenarios.",
        {
            "kp_xy": 1.25,
            "kd_xy": 1.20,
            "ki_xy": 1.00,
            "vel_limit": 0.90,
            "accel_limit": 1.00,
            "disturbance_rejection": 1.10,
        },
    ),
    (
        "smooth_damping",
        "Lower proportional gain, higher damping and disturbance rejection — "
        "favors smoothness in wind/noise scenarios.",
        {
            "kp_xy": 0.90,
            "kd_xy": 1.40,
            "ki_xy": 0.80,
            "vel_limit": 1.00,
            "accel_limit": 0.90,
            "disturbance_rejection": 1.30,
        },
    ),
    (
        "wind_robust",
        "Stronger integrator + disturbance rejection, relaxed velocity/accel "
        "limits — favors wind-perturbed scenarios.",
        {
            "kp_xy": 1.05,
            "kd_xy": 1.10,
            "ki_xy": 1.50,
            "vel_limit": 1.10,
            "accel_limit": 1.10,
            "disturbance_rejection": 1.40,
        },
    ),
)


def _clamp_to_safe_range(key: str, value: float) -> float:
    bounds = constants.PARAMETER_SAFE_RANGES.get(key)
    if bounds is None:
        return value
    lo, hi = bounds
    return max(lo, min(hi, value))


def _apply_perturbation(
    baseline: dict[str, float], factors: dict[str, float]
) -> dict[str, float]:
    """Apply ``factors`` multiplicatively to ``baseline`` and clamp to safe ranges.

    Non-tunable baseline keys are passed through untouched so the mock
    simulator still receives the full parameter dict it expects.
    """

    out: dict[str, float] = {}
    for key, base_value in baseline.items():
        if key in _TUNABLE_KEYS:
            factor = factors.get(key, 1.0)
            proposed = float(base_value) * float(factor)
            out[key] = round(_clamp_to_safe_range(key, proposed), 6)
        else:
            out[key] = float(base_value)
    return out


def generate_candidates(
    baseline: dict[str, Any],
    *,
    count: int | None = None,
) -> list[CandidateProposal]:
    """Produce 2–5 optimizer proposals around ``baseline``.

    Parameters
    ----------
    baseline:
        The baseline parameter dict. Must contain at least the tunable keys
        (see ``_TUNABLE_KEYS``); any extra keys are preserved unchanged.
    count:
        Optional override for how many proposals to return. Defaults to
        :data:`app.orchestration.constants.OPTIMIZER_CANDIDATE_COUNT`.

    Returns
    -------
    list[CandidateProposal]
        Deterministic proposals with ``generation_index`` starting at 1
        (0 is reserved for the baseline candidate).

    Raises
    ------
    ValueError
        If ``count`` is out of the [2, 5] range, or the baseline is missing
        any tunable key.
    """

    target = constants.OPTIMIZER_CANDIDATE_COUNT if count is None else count
    if target < 2 or target > 5:
        raise ValueError(
            f"Optimizer candidate count must be in [2, 5], got {target}."
        )
    if target > len(_PERTURBATIONS):
        raise ValueError(
            f"Optimizer has only {len(_PERTURBATIONS)} perturbations defined; "
            f"cannot produce {target} candidates."
        )

    missing = [k for k in _TUNABLE_KEYS if k not in baseline]
    if missing:
        raise ValueError(
            f"Baseline parameters are missing tunable keys: {missing!r}"
        )

    # Normalise baseline into float dict for the perturbation step.
    baseline_floats: dict[str, float] = {
        k: float(v) for k, v in baseline.items() if isinstance(v, int | float)
    }

    proposals: list[CandidateProposal] = []
    for idx, (label, strategy, factors) in enumerate(_PERTURBATIONS[:target], start=1):
        params = _apply_perturbation(baseline_floats, factors)
        proposals.append(
            CandidateProposal(
                generation_index=idx,
                label=f"optimizer_{label}",
                strategy=strategy,
                parameters=params,
            )
        )
    return proposals


__all__ = ["CandidateProposal", "generate_candidates"]
