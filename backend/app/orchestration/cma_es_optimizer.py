"""Dependency-free CMA-ES-style proposal generator.

This module intentionally implements only a lightweight adaptive search:
it updates a sampling center from scored history and shrinks per-parameter
sigma over generations. It does not depend on scipy/skopt or claim full
industrial CMA-ES parity.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any

from app import models, schemas
from app.optimization.candidate_evidence_ledger import (
    candidate_evidence_chain_matches_current,
    candidate_evidence_receipt_required,
)
from app.optimization.domain import SearchSpace
from app.optimization.outcome_contract import selection_order_key
from app.orchestration.optimizer import CandidateProposal
from app.orchestration.parameter_constraints import validator_for_job

_TUNABLE_KEYS: tuple[str, ...] = (
    "kp_xy",
    "kd_xy",
    "ki_xy",
    "vel_limit",
    "accel_limit",
    "disturbance_rejection",
)
_EPSILON = 1e-6
_MAX_RESAMPLE = 50


def _clamp(key: str, value: float, safe_ranges: dict[str, tuple[float, float]]) -> float:
    lo, hi = safe_ranges[key]
    return max(lo, min(hi, value))


def _parameters_from(
    candidate: models.CandidateParameterSet | None,
    safe_ranges: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float] | None:
    if candidate is None:
        return None
    params = candidate.parameter_json or {}
    normalized: dict[str, float] = {}
    for key in _TUNABLE_KEYS:
        raw_value = params.get(key)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            return None
        value = float(raw_value)
        if not math.isfinite(value):
            return None
        if safe_ranges is not None:
            lo, hi = safe_ranges[key]
            if value < lo or value > hi:
                return None
        normalized[key] = value
    return normalized


def _best_scored_center(
    candidates: list[models.CandidateParameterSet],
    *,
    safe_ranges: dict[str, tuple[float, float]] | None = None,
) -> models.CandidateParameterSet | None:
    scored = [
        candidate
        for candidate in candidates
        if candidate.aggregated_score is not None
        and not isinstance(candidate.aggregated_score, bool)
        and math.isfinite(float(candidate.aggregated_score))
        and (
            not candidate_evidence_receipt_required(candidate)
            or candidate_evidence_chain_matches_current(candidate)
        )
        and (safe_ranges is None or _parameters_from(candidate, safe_ranges) is not None)
    ]
    if not scored:
        return None
    scored.sort(
        key=lambda c: (
            *selection_order_key(
                c.aggregated_metric_json,
                c.aggregated_score,
            ),
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
                "score": (
                    float(c.aggregated_score)
                    if c.aggregated_score is not None
                    and not isinstance(c.aggregated_score, bool)
                    and math.isfinite(float(c.aggregated_score))
                    else None
                ),
                "params": _parameters_from(c) or {},
            }
            for c in sorted(candidate_history, key=lambda c: (c.generation_index, c.id))
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _validate_legacy_inputs(
    *,
    safe_ranges: dict[str, tuple[float, float]],
    baseline_parameters: dict[str, Any],
    generation_index: int,
) -> dict[str, float]:
    if (
        isinstance(generation_index, bool)
        or not isinstance(generation_index, int)
        or generation_index < 0
    ):
        raise ValueError("generation_index must be a non-negative integer")
    normalized_baseline: dict[str, float] = {}
    for key in _TUNABLE_KEYS:
        bounds = safe_ranges.get(key)
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            raise ValueError(f"Missing valid safe range for {key}")
        lo, hi = bounds
        if (
            isinstance(lo, bool)
            or isinstance(hi, bool)
            or not isinstance(lo, int | float)
            or not isinstance(hi, int | float)
            or not math.isfinite(float(lo))
            or not math.isfinite(float(hi))
            or float(lo) > float(hi)
        ):
            raise ValueError(f"Invalid safe range for {key}")
        raw_value = baseline_parameters.get(key)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            raise ValueError(f"Baseline parameter {key} must be numeric")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"Baseline parameter {key} must be finite")
        normalized_baseline[key] = _clamp(key, value, safe_ranges)
    return normalized_baseline


def propose_next_generation(
    *,
    job: models.Job,
    candidates: list[models.CandidateParameterSet],
    safe_ranges: dict[str, tuple[float, float]],
    baseline_parameters: dict[str, Any],
    generation_index: int,
) -> CandidateProposal:
    """Generate one deterministic CMA-ES-style proposal for ``generation_index``."""

    if job.parameter_space_json:
        if (
            isinstance(generation_index, bool)
            or not isinstance(generation_index, int)
            or generation_index < 0
        ):
            raise ValueError("generation_index must be a non-negative integer")
        return _propose_selected_parameter_generation(
            job=job,
            candidates=candidates,
            generation_index=generation_index,
        )

    baseline = _validate_legacy_inputs(
        safe_ranges=safe_ranges,
        baseline_parameters=baseline_parameters,
        generation_index=generation_index,
    )
    center_candidate = _best_scored_center(candidates, safe_ranges=safe_ranges)
    center_source = (
        baseline if center_candidate is None else _parameters_from(center_candidate, safe_ranges)
    )
    center = dict(center_source or baseline)

    seed = _seed_for(
        job_id=job.id,
        generation_index=generation_index,
        center_candidate=center_candidate,
        candidate_history=candidates,
    )
    rng = random.Random(seed)  # noqa: S311 - deterministic optimizer RNG

    sigma_scale = 0.85**generation_index
    sigma_by_key = {
        key: (safe_ranges[key][1] - safe_ranges[key][0]) * 0.15 * sigma_scale
        for key in _TUNABLE_KEYS
    }
    history_params = [
        parameters
        for candidate in candidates
        if (parameters := _parameters_from(candidate, safe_ranges)) is not None
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


def _propose_selected_parameter_generation(
    *,
    job: models.Job,
    candidates: list[models.CandidateParameterSet],
    generation_index: int,
) -> CandidateProposal:
    """Adaptive proposal in normalized space for arbitrary selected PX4 parameters."""

    selections = [
        schemas.ParameterSelection(**item)
        for item in (job.parameter_space_json or [])
        if item.get("enabled", True)
    ]
    search_space = SearchSpace.from_schema(
        selections,
        candidate_validator=validator_for_job(job),
    )
    tunable_keys = tuple(domain.name for domain in search_space.tunable)
    known_keys = {domain.name for domain in search_space.domains}
    baseline = search_space.baseline()

    def project_candidate(
        candidate: models.CandidateParameterSet,
    ) -> dict[str, float] | None:
        raw_parameters = candidate.parameter_json or {}
        selected: dict[str, float] = {}
        for key, value in raw_parameters.items():
            if key not in known_keys:
                continue
            if isinstance(value, bool) or not isinstance(value, int | float):
                return None
            numeric = float(value)
            if not math.isfinite(numeric):
                return None
            selected[key] = numeric
        try:
            return search_space.project(selected)
        except ValueError:
            return None

    valid_history: list[tuple[models.CandidateParameterSet, dict[str, float]]] = []
    for candidate in candidates:
        projected = project_candidate(candidate)
        if projected is None:
            continue
        valid_history.append((candidate, projected))
    scored_history = [
        (candidate, parameters)
        for candidate, parameters in valid_history
        if candidate.aggregated_score is not None
        and not isinstance(candidate.aggregated_score, bool)
        and math.isfinite(float(candidate.aggregated_score))
        and (
            not candidate_evidence_receipt_required(candidate)
            or candidate_evidence_chain_matches_current(candidate)
        )
    ]
    scored_history.sort(
        key=lambda item: (
            *selection_order_key(
                item[0].aggregated_metric_json,
                item[0].aggregated_score,
            ),
            item[0].generation_index,
            item[0].id,
        )
    )
    center_candidate, center = scored_history[0] if scored_history else (None, baseline)
    history = [parameters for _candidate, parameters in valid_history]
    seed_payload = {
        "job_id": job.id,
        "generation_index": generation_index,
        "center_candidate_id": center_candidate.id if center_candidate is not None else None,
        "parameter_space": job.parameter_space_json,
        "history": [
            {
                "id": candidate.id,
                "score": (
                    float(candidate.aggregated_score)
                    if candidate.aggregated_score is not None
                    and not isinstance(candidate.aggregated_score, bool)
                    and math.isfinite(float(candidate.aggregated_score))
                    else None
                ),
                "parameters": parameters,
            }
            for candidate, parameters in valid_history
        ],
    }
    digest = hashlib.sha256(json.dumps(seed_payload, sort_keys=True).encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))  # noqa: S311 - deterministic optimizer RNG
    normalized_sigma = 0.15 * (0.85**generation_index)

    candidate_params = baseline
    found_unique = False
    for _attempt in range(_MAX_RESAMPLE + 1):
        unit_values = []
        for domain in search_space.tunable:
            center_unit = domain.to_unit(center[domain.name])
            sampled_unit = rng.normalvariate(center_unit, normalized_sigma)
            unit_values.append(max(0.0, min(1.0, sampled_unit)))
        try:
            sampled_params = search_space.from_unit_vector(unit_values)
        except ValueError:
            continue
        if not _is_dynamic_duplicate(sampled_params, history, tunable_keys):
            candidate_params = sampled_params
            found_unique = True
            break

    center_label = center_candidate.label if center_candidate is not None else "baseline"
    reason = (
        f"Adaptive normalized-space step from center={center_label} "
        f"(generation={generation_index}, sigma={normalized_sigma:.4f}, "
        f"dimensions={len(tunable_keys)}, "
        f"fallback_to_center={str(not found_unique).lower()})"
    )
    return CandidateProposal(
        generation_index=generation_index,
        label=f"cma_es_gen_{generation_index}",
        strategy=reason,
        parameters=candidate_params,
    )


def _is_dynamic_duplicate(
    params: dict[str, float],
    history: list[dict[str, float]],
    keys: tuple[str, ...],
) -> bool:
    return any(
        all(abs(params[key] - previous.get(key, params[key])) <= _EPSILON for key in keys)
        for previous in history
    )


__all__ = ["propose_next_generation"]
