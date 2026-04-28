"""Dependency-free CMA-ES-style proposal generator.

This module intentionally implements only a lightweight adaptive search:
it updates a sampling center from scored history and shrinks per-parameter
sigma over generations. It does not depend on scipy/skopt or claim full
industrial CMA-ES parity.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from app import models
from app.orchestration.optimizer import CandidateProposal

_TUNABLE_KEYS: tuple[str, ...] = (
    "kp_xy",
    "kd_xy",
    "ki_xy",
    "vel_limit",
    "accel_limit",
    "disturbance_rejection",
)
_EPSILON = 1e-6
_MAX_RESAMPLE = 10


def _clamp(key: str, value: float, safe_ranges: dict[str, tuple[float, float]]) -> float:
    lo, hi = safe_ranges[key]
    return max(lo, min(hi, value))


def _parameters_from(candidate: models.CandidateParameterSet | None) -> dict[str, float]:
    if candidate is None:
        return {}
    params = candidate.parameter_json or {}
    return {
        k: float(v)
        for k, v in params.items()
        if k in _TUNABLE_KEYS and isinstance(v, int | float)
    }


def _best_scored_center(
    candidates: list[models.CandidateParameterSet],
) -> models.CandidateParameterSet | None:
    scored = [c for c in candidates if c.aggregated_score is not None]
    if not scored:
        return None
    scored.sort(
        key=lambda c: (
            c.aggregated_score if c.aggregated_score is not None else float("inf"),
            c.generation_index,
            c.id,
        )
    )
    return scored[0]


def _is_duplicate(
    params: dict[str, float],
    history: list[dict[str, float]],
) -> bool:
    for prev in history:
        if all(abs(params[k] - prev.get(k, params[k])) <= _EPSILON for k in _TUNABLE_KEYS):
            return True
    return False


def _seed_for(
    *,
    job_id: str,
    generation_index: int,
    center_candidate: models.CandidateParameterSet | None,
    candidate_history: list[models.CandidateParameterSet],
) -> int:
    payload = {
        "job_id": job_id,
        "generation_index": generation_index,
        "center_candidate_id": center_candidate.id if center_candidate is not None else "baseline",
        "history": [
            {
                "id": c.id,
                "g": c.generation_index,
                "score": c.aggregated_score,
                "params": {k: float(c.parameter_json.get(k, 0.0)) for k in _TUNABLE_KEYS},
            }
            for c in sorted(candidate_history, key=lambda c: (c.generation_index, c.id))
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def propose_next_generation(
    *,
    job: models.Job,
    candidates: list[models.CandidateParameterSet],
    safe_ranges: dict[str, tuple[float, float]],
    baseline_parameters: dict[str, Any],
    generation_index: int,
) -> CandidateProposal:
    """Generate one deterministic CMA-ES-style proposal for ``generation_index``."""

    center_candidate = _best_scored_center(candidates)
    center_source = (
        baseline_parameters if center_candidate is None else _parameters_from(center_candidate)
    )
    center = {k: float(v) for k, v in center_source.items() if k in _TUNABLE_KEYS}
    if not center:
        center = {k: float(baseline_parameters[k]) for k in _TUNABLE_KEYS}

    seed = _seed_for(
        job_id=job.id,
        generation_index=generation_index,
        center_candidate=center_candidate,
        candidate_history=candidates,
    )
    rng = random.Random(seed)

    sigma_scale = 0.85 ** generation_index
    sigma_by_key = {
        key: (safe_ranges[key][1] - safe_ranges[key][0]) * 0.15 * sigma_scale
        for key in _TUNABLE_KEYS
    }
    history_params = [
        {k: float(c.parameter_json.get(k, 0.0)) for k in _TUNABLE_KEYS}
        for c in candidates
        if c.parameter_json is not None
    ]

    candidate_params: dict[str, float] = {}
    for attempt in range(_MAX_RESAMPLE + 1):
        candidate_params = {}
        for key in _TUNABLE_KEYS:
            mu = center[key]
            sigma = sigma_by_key[key]
            sampled = rng.normalvariate(mu, sigma)
            candidate_params[key] = round(_clamp(key, sampled, safe_ranges), 6)
        if not _is_duplicate(candidate_params, history_params):
            break
        if attempt == _MAX_RESAMPLE:
            for idx, key in enumerate(_TUNABLE_KEYS, start=1):
                jitter = (((seed + idx * 97) % 21) - 10) * 1e-4
                candidate_params[key] = round(
                    _clamp(key, center[key] + jitter, safe_ranges),
                    6,
                )

    center_label = center_candidate.label if center_candidate is not None else "baseline"
    sigma_summary = ", ".join(f"{k}={sigma_by_key[k]:.4f}" for k in _TUNABLE_KEYS)
    reason = (
        f"CMA-ES-style adaptive step from center={center_label} "
        f"(generation={generation_index}, sigma: {sigma_summary})"
    )
    return CandidateProposal(
        generation_index=generation_index,
        label=f"cma_es_gen_{generation_index}",
        strategy=reason,
        parameters=candidate_params,
    )


__all__ = ["propose_next_generation"]
