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

import hashlib
import json
import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app import schemas
from app.optimization.design import MAX_HALTON_DIMENSIONS, halton_design
from app.optimization.domain import SearchSpace
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
    metadata: dict[str, Any] = field(default_factory=dict)


# Fixed multiplicative perturbations applied to the baseline. Each entry
# produces exactly one CandidateProposal. Keeping this list between length
# 2 and 5 satisfies the Phase 5 directive; tests assert on the count so
# editing this list will flag the constraint if violated.
_PERTURBATIONS: tuple[tuple[str, str, dict[str, float]], ...] = (
    (
        "aggressive_tracking",
        "Stiffer gains, tighter velocity envelope — favors low RMSE on nominal/noise scenarios.",
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


def _apply_perturbation(baseline: dict[str, float], factors: dict[str, float]) -> dict[str, float]:
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


def _validated_count(count: int, *, maximum: int, label: str) -> int:
    """Reject booleans and non-integral counts before sequence slicing."""

    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError(f"{label} must be an integer")
    if count < 1 or count > maximum:
        raise ValueError(f"{label} must be in [1, {maximum}], got {count}.")
    return count


def _finite_baseline(baseline: Mapping[str, Any]) -> dict[str, float]:
    """Return a fully numeric baseline, failing closed on unsafe values."""

    normalized: dict[str, float] = {}
    for raw_key, raw_value in baseline.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise ValueError("Baseline parameter names must be non-empty strings")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            raise ValueError(f"Baseline parameter {raw_key!r} must be numeric")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"Baseline parameter {raw_key!r} must be finite")
        normalized[raw_key] = value
    return normalized


def _random_fill_design(
    search_space: SearchSpace,
    *,
    count: int,
    seed: int,
    existing: list[dict[str, float]],
) -> list[dict[str, float]]:
    """Deterministically fill constrained or high-dimensional initial designs."""

    candidates = list(existing)
    seen = {tuple(search_space.to_unit_vector(search_space.baseline()))}
    seen.update(tuple(search_space.to_unit_vector(candidate)) for candidate in candidates)
    rng = random.Random(seed)  # noqa: S311 - deterministic optimizer RNG
    dimensions = len(search_space.tunable)
    max_attempts = max(4_096, count * 400)
    for _ in range(max_attempts):
        if len(candidates) >= count:
            break
        try:
            candidate = search_space.from_unit_vector([rng.random() for _ in range(dimensions)])
        except ValueError:
            continue
        fingerprint = tuple(search_space.to_unit_vector(candidate))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        candidates.append(candidate)
    return candidates


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
        If ``count`` is out of the [1, 5] range, or the baseline is missing
        any tunable key.
    """

    target = constants.OPTIMIZER_CANDIDATE_COUNT if count is None else count
    target = _validated_count(
        target,
        maximum=5,
        label="Optimizer candidate count",
    )
    if target > len(_PERTURBATIONS):
        raise ValueError(
            f"Optimizer has only {len(_PERTURBATIONS)} perturbations defined; "
            f"cannot produce {target} candidates."
        )

    baseline_floats = _finite_baseline(baseline)
    missing = [k for k in _TUNABLE_KEYS if k not in baseline_floats]
    if missing:
        raise ValueError(f"Baseline parameters are missing tunable keys: {missing!r}")

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


def generate_selected_parameter_candidates(
    parameter_space_json: list[dict[str, Any]],
    *,
    count: int = 3,
    candidate_validator: Callable[[Mapping[str, float]], None] | None = None,
) -> list[CandidateProposal]:
    """Generate a space-filling first generation for arbitrary PX4 parameters."""

    count = _validated_count(
        count,
        maximum=100,
        label="Selected-parameter candidate count",
    )
    if not isinstance(parameter_space_json, list) or any(
        not isinstance(item, dict) for item in parameter_space_json
    ):
        raise ValueError("parameter_space_json must be a list of parameter objects")
    selections = [
        schemas.ParameterSelection(**item)
        for item in parameter_space_json
        if item.get("enabled", True)
    ]
    search_space = SearchSpace.from_schema(
        selections,
        candidate_validator=candidate_validator,
    )
    if not search_space.tunable:
        raise ValueError("At least one enabled, unlocked parameter is required")

    baseline = search_space.baseline()
    if len(search_space.tunable) <= MAX_HALTON_DIMENSIONS:
        # Ask for extra points because discrete domains and coupled PX4
        # constraints can collapse or reject otherwise valid Halton samples.
        design = halton_design(
            search_space,
            max(count + 1, count * 4 + 1),
            include_baseline=True,
        )
        non_baseline = [candidate for candidate in design if candidate != baseline]
    else:
        non_baseline = []

    seed_payload = json.dumps(
        {"parameter_space": parameter_space_json, "count": count},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_payload).digest()[:8], "big")
    non_baseline = _random_fill_design(
        search_space,
        count=count,
        seed=seed,
        existing=non_baseline[:count],
    )
    if len(non_baseline) != count:
        raise ValueError(
            "The selected parameter domain cannot produce the requested number "
            f"of unique feasible candidates ({len(non_baseline)}/{count})"
        )
    return [
        CandidateProposal(
            generation_index=index,
            label=f"space_filling_{index}",
            strategy=(
                "Deterministic Halton space-filling proposal over the user-selected "
                f"PX4 domain ({len(search_space.tunable)} tunable dimensions)."
            ),
            parameters=parameters,
        )
        for index, parameters in enumerate(non_baseline, start=1)
    ]


__all__ = [
    "CandidateProposal",
    "generate_candidates",
    "generate_selected_parameter_candidates",
]
