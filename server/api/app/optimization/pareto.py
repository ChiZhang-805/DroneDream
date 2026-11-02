"""Constraint-aware Pareto ranking and recommendation helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParetoPoint:
    id: str
    objectives: Mapping[str, float]
    directions: Mapping[str, str]
    feasible: bool = True
    total_violation: float = 0.0
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Pareto point id must be a non-empty string")
        if not self.objectives or any(
            not isinstance(metric, str) or not metric
            for metric in self.objectives
        ):
            raise ValueError("Pareto objectives require non-empty metric names")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
            for value in self.objectives.values()
        ):
            raise ValueError("Pareto objective values must be finite numbers")
        if set(self.directions) != set(self.objectives):
            raise ValueError("Pareto directions must exactly match objectives")
        for metric, direction in self.directions.items():
            if direction not in {"minimize", "maximize"}:
                raise ValueError(f"unsupported direction for {metric}: {direction}")
        if not isinstance(self.feasible, bool):
            raise ValueError("Pareto feasibility must be a boolean")
        if (
            isinstance(self.total_violation, bool)
            or not isinstance(self.total_violation, int | float)
            or not math.isfinite(float(self.total_violation))
            or float(self.total_violation) < 0.0
        ):
            raise ValueError("Pareto total_violation must be finite and non-negative")


def _dominates(first: ParetoPoint, second: ParetoPoint) -> bool:
    if first.feasible and not second.feasible:
        return True
    if second.feasible and not first.feasible:
        return False
    if not first.feasible and not second.feasible:
        return first.total_violation < second.total_violation
    if set(first.objectives) != set(second.objectives):
        raise ValueError("all Pareto points must expose the same objectives")
    no_worse = True
    strictly_better = False
    for metric, first_value in first.objectives.items():
        second_value = second.objectives[metric]
        direction = first.directions.get(metric)
        if direction != second.directions.get(metric):
            raise ValueError(f"direction mismatch for objective {metric}")
        if direction == "minimize":
            no_worse = no_worse and first_value <= second_value
            strictly_better = strictly_better or first_value < second_value
        elif direction == "maximize":
            no_worse = no_worse and first_value >= second_value
            strictly_better = strictly_better or first_value > second_value
        else:
            raise ValueError(f"unsupported direction for {metric}: {direction}")
    return no_worse and strictly_better


def nondominated_front(points: Sequence[ParetoPoint]) -> list[ParetoPoint]:
    """Return the stable first Pareto front using feasibility-first dominance."""

    return [
        point
        for index, point in enumerate(points)
        if not any(
            index != other_index and _dominates(other, point)
            for other_index, other in enumerate(points)
        )
    ]


def _oriented_value(point: ParetoPoint, metric: str) -> float:
    value = point.objectives[metric]
    return value if point.directions[metric] == "minimize" else -value


def representative_points(points: Sequence[ParetoPoint]) -> dict[str, ParetoPoint]:
    """Pick safe representative recommendations from the feasible Pareto front.

    The diagnostic Pareto front may contain least-violating points when every
    experiment is infeasible.  Those points are useful for deciding where to
    search next, but must never be exposed as parameter recommendations that
    appear to satisfy the user's constraints.
    """

    front = nondominated_front([point for point in points if point.feasible])
    if not front:
        return {}
    metrics = list(front[0].objectives)
    ranges: dict[str, tuple[float, float]] = {}
    for metric in metrics:
        values = [_oriented_value(point, metric) for point in front]
        ranges[metric] = (min(values), max(values))

    def balanced_loss(point: ParetoPoint) -> tuple[float, float, str]:
        normalized: list[float] = []
        for metric in metrics:
            low, high = ranges[metric]
            value = _oriented_value(point, metric)
            normalized.append(0.0 if high == low else (value - low) / (high - low))
        # Minimax first protects against a terrible trade-off; mean breaks ties.
        return max(normalized, default=0.0), sum(normalized) / len(normalized), point.id

    result: dict[str, ParetoPoint] = {"balanced": min(front, key=balanced_loss)}
    for metric in metrics:
        result[f"best_{metric}"] = min(
            front, key=lambda point: (_oriented_value(point, metric), point.id)
        )
    return result


__all__ = ["ParetoPoint", "nondominated_front", "representative_points"]
