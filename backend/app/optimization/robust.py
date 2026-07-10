"""Robust multi-objective scoring with hard and soft constraints."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.schemas import ConstraintSpec, ObjectiveConfig, ObjectiveSpec


@dataclass(frozen=True)
class CandidateEvaluation:
    objectives: dict[str, float]
    constraint_values: dict[str, float]
    violations: dict[str, float]
    feasible: bool
    total_violation: float
    scalar_loss: float
    sample_count: int


def _validated_values(values: Sequence[float]) -> list[float]:
    if not values:
        raise ValueError("at least one sample is required")
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise ValueError("metric samples must be finite")
    return result


def _validated_weights(count: int, weights: Sequence[float] | None) -> list[float]:
    if weights is None:
        return [1.0] * count
    if len(weights) != count:
        raise ValueError("sample weights must match sample count")
    result = [float(weight) for weight in weights]
    if not all(math.isfinite(weight) and weight > 0 for weight in result):
        raise ValueError("sample weights must be finite and > 0")
    return result


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(
        weights
    )


def _weighted_quantile(
    values: Sequence[float], weights: Sequence[float], quantile: float
) -> float:
    ordered = sorted(zip(values, weights, strict=True), key=lambda item: item[0])
    threshold = max(0.0, min(1.0, quantile)) * sum(weights)
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _weighted_tail_mean(
    values: Sequence[float],
    weights: Sequence[float],
    *,
    fraction: float,
    highest: bool,
) -> float:
    ordered = sorted(
        zip(values, weights, strict=True), key=lambda item: item[0], reverse=highest
    )
    target_weight = fraction * sum(weights)
    remaining = target_weight
    weighted_sum = 0.0
    consumed = 0.0
    for value, weight in ordered:
        take = min(weight, remaining)
        weighted_sum += value * take
        consumed += take
        remaining -= take
        if remaining <= 1e-15:
            break
    return weighted_sum / consumed


def aggregate_metric(
    values: Sequence[float],
    *,
    direction: str,
    mode: str,
    weights: Sequence[float] | None = None,
    cvar_alpha: float = 0.2,
    percentile: float = 95.0,
) -> float:
    """Aggregate repeated trials, preserving the objective's worst direction."""

    samples = _validated_values(values)
    sample_weights = _validated_weights(len(samples), weights)
    highest_is_worst = direction == "minimize"
    if direction not in {"minimize", "maximize"}:
        raise ValueError("direction must be minimize or maximize")
    if mode == "mean":
        return _weighted_mean(samples, sample_weights)
    if mode == "worst":
        return max(samples) if highest_is_worst else min(samples)
    if mode == "cvar":
        if not 0 < cvar_alpha < 1:
            raise ValueError("cvar_alpha must be in (0, 1)")
        return _weighted_tail_mean(
            samples,
            sample_weights,
            fraction=cvar_alpha,
            highest=highest_is_worst,
        )
    if mode == "percentile":
        quantile = percentile / 100.0
        if not highest_is_worst:
            quantile = 1.0 - quantile
        return _weighted_quantile(samples, sample_weights, quantile)
    raise ValueError(f"unsupported robust aggregation mode: {mode}")


def _constraint_observed(
    values: Sequence[float], constraint: ConstraintSpec
) -> float:
    samples = _validated_values(values)
    if constraint.operator in {"lt", "lte"}:
        return max(samples)
    if constraint.operator in {"gt", "gte"}:
        return min(samples)
    return max(samples, key=lambda value: abs(value - constraint.threshold))


def _constraint_violation(value: float, constraint: ConstraintSpec) -> float:
    threshold = constraint.threshold
    if constraint.operator == "lt":
        raw = max(0.0, value - threshold + 1e-12)
    elif constraint.operator == "lte":
        raw = max(0.0, value - threshold)
    elif constraint.operator == "gt":
        raw = max(0.0, threshold - value + 1e-12)
    elif constraint.operator == "gte":
        raw = max(0.0, threshold - value)
    else:
        raw = abs(value - threshold)
    return raw / max(1.0, abs(threshold))


def _objective_value(
    samples: Sequence[Mapping[str, float]],
    objective: ObjectiveSpec,
    config: ObjectiveConfig,
    weights: Sequence[float] | None,
) -> float:
    try:
        values = [sample[objective.metric] for sample in samples]
    except KeyError as exc:
        raise ValueError(f"missing objective metric: {objective.metric}") from exc
    return aggregate_metric(
        values,
        direction=objective.direction,
        mode=config.robust_aggregation,
        weights=weights,
        cvar_alpha=config.cvar_alpha,
        percentile=config.percentile,
    )


def evaluate_candidate(
    samples: Sequence[Mapping[str, float]],
    config: ObjectiveConfig,
    *,
    sample_weights: Sequence[float] | None = None,
) -> CandidateEvaluation:
    """Evaluate a candidate consistently across objectives and scenarios."""

    if not samples:
        raise ValueError("candidate evaluation requires at least one metric sample")
    _validated_weights(len(samples), sample_weights)
    objectives: dict[str, float] = {}
    scalar_loss = 0.0
    total_objective_weight = sum(objective.weight for objective in config.objectives)
    for objective in config.objectives:
        value = _objective_value(samples, objective, config, sample_weights)
        objectives[objective.metric] = value
        oriented = value if objective.direction == "minimize" else -value
        scalar_loss += (
            objective.weight / total_objective_weight
        ) * oriented / objective.normalization

    constraint_values: dict[str, float] = {}
    violations: dict[str, float] = {}
    hard_violation = False
    total_violation = 0.0
    for constraint in config.constraints:
        try:
            values = [sample[constraint.metric] for sample in samples]
        except KeyError as exc:
            raise ValueError(f"missing constraint metric: {constraint.metric}") from exc
        observed = _constraint_observed(values, constraint)
        violation = _constraint_violation(observed, constraint)
        constraint_values[constraint.metric] = observed
        if violation > 0:
            key = f"{constraint.metric}:{constraint.operator}:{constraint.threshold:g}"
            violations[key] = violation
            total_violation += violation
            hard_violation = hard_violation or constraint.hard
            scalar_loss += constraint.penalty * violation

    return CandidateEvaluation(
        objectives=objectives,
        constraint_values=constraint_values,
        violations=violations,
        feasible=not hard_violation,
        total_violation=total_violation,
        scalar_loss=scalar_loss,
        sample_count=len(samples),
    )


__all__ = ["CandidateEvaluation", "aggregate_metric", "evaluate_candidate"]
