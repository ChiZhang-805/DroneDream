"""Acceptance-criteria evaluator (Phase 8).

Given a candidate's persisted aggregate and the job's acceptance criteria,
:func:`evaluate_candidate` returns a ``(passed, reason)`` pair. Used by the
iterative GPT tuning loop to decide whether to stop or keep proposing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app import models
from app.optimization.candidate_evidence_ledger import (
    candidate_evidence_chain_matches_current,
    candidate_evidence_receipt_required,
)
from app.optimization.outcome_evidence import (
    authoritative_candidate_trial_outcome_projection,
    candidate_outcome_evidence_required,
    candidate_training_trial_evidence_rows,
)


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
    """Scenario-case-weighted fraction of seeds whose ``pass_flag`` is true.

    Each case first uses all dispatched seeds as its denominator, including
    failed seeds, before case weights are applied. ``completion_rate`` uses
    the same hierarchy for execution success.
    """
    completion_rate: float
    rmse: float | None
    max_error: float | None
    """Worst observed trial max-error used by the acceptance threshold."""


def _safe_float(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_rate(value: object) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return min(1.0, max(0.0, parsed))


def _safe_nonnegative_int(value: object) -> int:
    parsed = _safe_float(value)
    if parsed is None or parsed < 0 or not parsed.is_integer():
        return 0
    return int(parsed)


def _criteria_are_valid(criteria: AcceptanceCriteria) -> bool:
    minimum_rate = _safe_float(criteria.min_pass_rate)
    if minimum_rate is None or not 0.0 <= minimum_rate <= 1.0:
        return False
    for threshold in (criteria.target_rmse, criteria.target_max_error):
        if threshold is None:
            continue
        parsed = _safe_float(threshold)
        if parsed is None or parsed < 0:
            return False
    return True


def evaluate_candidate(
    candidate: models.CandidateParameterSet,
    criteria: AcceptanceCriteria,
) -> AcceptanceResult:
    """Determine whether ``candidate`` satisfies the acceptance criteria.

    ``pass_rate`` and ``completion_rate`` prefer the persisted case-weighted
    rates. Legacy aggregates without those fields fall back to raw dispatched
    trial counts.
    """

    raw_aggregate = candidate.aggregated_metric_json
    ledger_required = candidate_evidence_receipt_required(candidate)
    evidence_required = (
        candidate_outcome_evidence_required(raw_aggregate)
        or ledger_required
    )
    if ledger_required and not candidate_evidence_chain_matches_current(
        candidate,
        raw_aggregate,
    ):
        raw_aggregate = {}
    agg = authoritative_candidate_trial_outcome_projection(
        candidate_id=candidate.id,
        generation_index=candidate.generation_index,
        parameter_snapshot=candidate.parameter_json,
        trial_evidence_rows=candidate_training_trial_evidence_rows(candidate),
        aggregate=raw_aggregate,
    )
    trial_count = _safe_nonnegative_int(
        agg.get("training_trial_count", candidate.trial_count or 0)
    )
    completed = min(
        trial_count,
        _safe_nonnegative_int(
            agg.get(
                "training_completed_trial_count",
                candidate.completed_trial_count or 0,
            )
        ),
    )
    stored_completion_rate = _safe_rate(
        agg.get(
            "acceptance_completion_rate",
            agg.get("training_completion_rate"),
        )
    )
    if (
        stored_completion_rate is None
        and agg.get("rate_aggregation") == "scenario_case_weighted_v1"
    ):
        stored_completion_rate = _safe_rate(agg.get("completion_rate"))
    completion_rate = (
        stored_completion_rate
        if stored_completion_rate is not None
        else completed / trial_count if trial_count > 0 else 0.0
    )

    rmse = _safe_float(agg.get("acceptance_rmse", agg.get("rmse")))
    # ``max_error`` historically contains the completed-trial mean. New
    # aggregates retain it for compatibility while acceptance uses the worst
    # observed trial excursion.
    max_error = _safe_float(
        agg.get(
            "acceptance_max_error",
            agg.get("max_error_worst", agg.get("max_error")),
        )
    )
    passing = min(
        trial_count,
        _safe_nonnegative_int(
            agg.get(
                "training_passing_trial_count",
                agg.get("passing_trial_count", 0),
            )
        ),
    )
    stored_pass_rate = _safe_rate(
        agg.get(
            "acceptance_pass_rate",
            agg.get("training_pass_rate"),
        )
    )
    if (
        stored_pass_rate is None
        and agg.get("rate_aggregation") == "scenario_case_weighted_v1"
    ):
        stored_pass_rate = _safe_rate(agg.get("pass_rate"))
    pass_rate = (
        stored_pass_rate
        if stored_pass_rate is not None
        else passing / trial_count if trial_count > 0 else 0.0
    )

    if not _criteria_are_valid(criteria):
        return AcceptanceResult(
            False, "invalid_criteria", pass_rate, completion_rate, rmse, max_error
        )
    if evidence_required and not agg:
        return AcceptanceResult(
            False,
            "invalid_outcome_evidence",
            pass_rate,
            completion_rate,
            rmse,
            max_error,
        )
    if candidate.aggregated_metric_json is None or trial_count == 0:
        return AcceptanceResult(
            False, "no_metrics", pass_rate, completion_rate, rmse, max_error
        )
    if completed == 0:
        return AcceptanceResult(
            False,
            "no_completed_trials",
            pass_rate,
            completion_rate,
            rmse,
            max_error,
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

    return (
        criteria.target_rmse is not None
        or criteria.target_max_error is not None
        or criteria.min_pass_rate > 0
    )


__all__ = [
    "AcceptanceCriteria",
    "AcceptanceResult",
    "any_criterion_set",
    "criteria_for_job",
    "evaluate_candidate",
]
