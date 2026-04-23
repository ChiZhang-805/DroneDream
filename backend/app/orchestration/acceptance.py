"""Acceptance-criteria evaluator (Phase 8).

Given a candidate's persisted aggregate and the job's acceptance criteria,
:func:`evaluate_candidate` returns a ``(passed, reason)`` pair. Used by the
iterative GPT tuning loop to decide whether to stop or keep proposing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import models


@dataclass(frozen=True)
class AcceptanceCriteria:
    """Static snapshot of the job's acceptance criteria."""

    target_rmse: float | None
    target_max_error: float | None
    min_pass_rate: float


def criteria_for_job(job: models.Job) -> AcceptanceCriteria:
    return AcceptanceCriteria(
        target_rmse=job.target_rmse,
        target_max_error=job.target_max_error,
        min_pass_rate=job.min_pass_rate,
    )


@dataclass(frozen=True)
class AcceptanceResult:
    passed: bool
    reason: str
    pass_rate: float
    """Fraction of dispatched trials whose per-trial ``pass_flag`` is true.

    This is the semantic definition used by the acceptance check: a candidate
    is accepted only when enough trials *actually passed*, not merely when
    they executed to completion. ``completion_rate`` captures the execution
    ratio separately.
    """
    completion_rate: float
    rmse: float | None
    max_error: float | None


def _safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def evaluate_candidate(
    candidate: models.CandidateParameterSet,
    criteria: AcceptanceCriteria,
) -> AcceptanceResult:
    """Determine whether ``candidate`` satisfies the acceptance criteria.

    Phase 8 polish: ``pass_rate`` is the fraction of *dispatched* trials whose
    per-trial ``pass_flag`` is true, matching the product intent that
    "success" means the candidate truly met the user's thresholds. The old
    execution-completion ratio is exposed as ``completion_rate`` for UI /
    diagnostics only.
    """

    trial_count = max(1, candidate.trial_count or 0)
    completed = candidate.completed_trial_count or 0
    completion_rate = completed / trial_count if trial_count > 0 else 0.0

    agg = candidate.aggregated_metric_json or {}
    rmse = _safe_float(agg.get("rmse"))
    max_error = _safe_float(agg.get("max_error"))
    passing = int(agg.get("passing_trial_count") or 0)
    pass_rate = passing / trial_count if trial_count > 0 else 0.0

    if candidate.aggregated_metric_json is None:
        return AcceptanceResult(
            False, "no_metrics", pass_rate, completion_rate, rmse, max_error
        )
    if pass_rate < criteria.min_pass_rate:
        return AcceptanceResult(
            False, "pass_rate_too_low", pass_rate, completion_rate, rmse, max_error
        )
    if criteria.target_rmse is not None and (rmse is None or rmse > criteria.target_rmse):
        return AcceptanceResult(
            False, "rmse_above_target", pass_rate, completion_rate, rmse, max_error
        )
    if criteria.target_max_error is not None and (
        max_error is None or max_error > criteria.target_max_error
    ):
        return AcceptanceResult(
            False,
            "max_error_above_target",
            pass_rate,
            completion_rate,
            rmse,
            max_error,
        )
    return AcceptanceResult(True, "passed", pass_rate, completion_rate, rmse, max_error)


def any_criterion_set(criteria: AcceptanceCriteria) -> bool:
    """Return ``True`` if at least one numeric threshold is configured."""

    return criteria.target_rmse is not None or criteria.target_max_error is not None


__all__ = [
    "AcceptanceCriteria",
    "AcceptanceResult",
    "any_criterion_set",
    "criteria_for_job",
    "evaluate_candidate",
]
