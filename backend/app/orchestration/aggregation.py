"""Job aggregation + best-candidate selection (Phase 5).

Once every trial for a job is terminal, this module:

1. Moves the job to ``AGGREGATING``.
2. For each ``CandidateParameterSet`` (baseline and every optimizer
   candidate), rolls up the candidate's completed trials into
   ``aggregated_metric_json`` / ``aggregated_score``, and persists trial
   counts. See :func:`_aggregate_candidate`.
3. Selects the best candidate with the shared lexicographic Selection Key 1.0
   among candidates that completed the entire configured full-fidelity
   scenario matrix, passed every required holdout, and satisfied all persisted
   hard constraints.
4. Ranks every candidate (``rank_in_job``, 1-indexed) and marks ``is_best``
   on the winner.
5. Writes the ``JobReport`` using the baseline's aggregate as the baseline
   and the winner's aggregate as the optimized comparison.
6. Sets the job ``COMPLETED`` (or ``FAILED`` only when no candidate produced
   a usable aggregate).

The compatibility score remains deterministic and lower-is-better, while hard
feasibility and failure precedence are represented explicitly rather than by a
magic numeric penalty.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.db import SessionLocal
from app.optimization.experimental_types import EXPERIMENTAL_OPTIMIZER_STRATEGIES
from app.optimization.outcome_contract import (
    OptimizationOutcomeContractV1,
    build_selection_key,
    selection_order_key,
)
from app.optimization.outcome_evidence import (
    authoritative_candidate_trial_outcome_projection,
    candidate_outcome_evidence_required,
    candidate_report_evidence_required,
    candidate_report_trial_evidence_rows,
    candidate_training_trial_evidence_rows,
    compile_candidate_outcome_evidence,
    compile_candidate_report_evidence,
    require_authoritative_candidate_report_projection,
    trial_is_holdout,
)
from app.optimization.outcome_taxonomy import (
    TRIAL_OUTCOME_CLASSES,
    TRIAL_OUTCOME_TAXONOMY_SCHEMA,
    TrialOutcomeClass,
    classify_trial_outcome,
    is_optimizer_learning_failure,
    is_optimizer_learning_outcome,
)
from app.optimization.robust import (
    CandidateEvaluation,
    aggregate_metric,
)
from app.optimization.robust import (
    evaluate_candidate as evaluate_objectives,
)
from app.optimization.scenarios import scenario_matrix
from app.optimization.winner_evidence import (
    WinnerSelectionEvidenceError,
    WinnerSelectionEvidenceV1,
    compile_winner_selection_evidence,
    winner_evidence_matches_current_candidates,
)
from app.orchestration import constants, report_generator
from app.orchestration.acceptance import (
    AcceptanceCriteria,
    any_criterion_set,
    criteria_for_job,
    evaluate_candidate,
)
from app.orchestration.events import record_event
from app.orchestration.outcome_contract_guard import check_job_outcome_contract

logger = logging.getLogger("drone_dream.orchestration.aggregation")

_TERMINAL_TRIAL = {"COMPLETED", "FAILED", "CANCELLED"}
_ITERATIVE_OPTIMIZERS = {
    "gpt",
    "llm_harness",
    "cma_es",
    *EXPERIMENTAL_OPTIMIZER_STRATEGIES,
}


def _candidate_fidelity(candidate: object) -> float:
    """Read optimizer fidelity defensively for legacy rows and test doubles."""

    metadata = getattr(candidate, "optimizer_metadata_json", None)
    if not isinstance(metadata, dict):
        return 1.0
    raw = metadata.get("requested_fidelity", metadata.get("fidelity", 1.0))
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        return 1.0
    try:
        fidelity = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return fidelity if math.isfinite(fidelity) and 0.0 < fidelity <= 1.0 else 0.0


def _configured_scenario_contract(
    candidate: object,
) -> tuple[Counter[tuple[str, bool]], bool] | None:
    """Return the expected case/holdout multiplicities when the job is available.

    The public recommendation gate is also used with lightweight test doubles and
    legacy detached rows.  In those cases there is no trustworthy job-side suite
    to compare, so the older aggregate/trial checks remain the compatibility
    boundary.  A present but invalid persisted suite is never considered safe.
    """

    try:
        job = getattr(candidate, "job", None)
        raw_suite = getattr(job, "scenario_suite_json", None)
    except Exception:  # pragma: no cover - detached ORM state is not publishable
        return Counter(), False
    if raw_suite is None:
        return None
    if not isinstance(raw_suite, dict):
        return Counter(), False
    try:
        runs = scenario_matrix(schemas.ScenarioSuiteConfig(**raw_suite))
    except (TypeError, ValueError):
        return Counter(), False
    expected = Counter((run.case_id, run.holdout) for run in runs)
    return expected, any(run.holdout for run in runs)


def _uses_experimental_optimizer(candidate: object) -> bool:
    try:
        job_strategy = str(getattr(getattr(candidate, "job", None), "optimizer_strategy", ""))
    except Exception:  # pragma: no cover - fail closed for detached ORM state
        return True
    metadata = getattr(candidate, "optimizer_metadata_json", None)
    child_strategy = ""
    if isinstance(metadata, dict):
        child_strategy = str(metadata.get("child_strategy") or metadata.get("strategy") or "")
    return (
        job_strategy in EXPERIMENTAL_OPTIMIZER_STRATEGIES
        or child_strategy in EXPERIMENTAL_OPTIMIZER_STRATEGIES
    )


def _safe_candidate_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def candidate_is_publishable(candidate: models.CandidateParameterSet) -> bool:
    """Return whether a candidate is safe to expose as a parameter recommendation.

    Optimizer observations may remain useful after a partial or reduced-cost
    evaluation, but a public recommendation has a stricter contract: nominal
    full fidelity, a completely successful dispatched matrix, a finite score,
    no known hard-constraint failure, exact coverage of the configured scenario
    matrix, and a passed holdout whenever the suite requires one. Legacy
    aggregates did not persist ``feasible``; absence remains compatible for
    legacy optimizers, while experimental optimizers require an explicit result.
    """

    if not candidate.is_baseline and _candidate_fidelity(candidate) < 1.0 - 1e-9:
        return False
    trial_count = _safe_candidate_count(candidate.trial_count)
    completed_trial_count = _safe_candidate_count(candidate.completed_trial_count)
    failed_trial_count = _safe_candidate_count(candidate.failed_trial_count)
    if (
        trial_count is None
        or completed_trial_count is None
        or failed_trial_count is None
        or trial_count <= 0
        or completed_trial_count != trial_count
        or failed_trial_count != 0
    ):
        return False
    score = candidate.aggregated_score
    if (
        isinstance(score, bool)
        or not isinstance(score, int | float)
        or not math.isfinite(float(score))
    ):
        return False
    aggregate = candidate.aggregated_metric_json
    if not isinstance(aggregate, dict):
        return False
    authoritative_aggregate = authoritative_candidate_trial_outcome_projection(
        candidate_id=getattr(candidate, "id", None),
        generation_index=getattr(candidate, "generation_index", None),
        parameter_snapshot=getattr(candidate, "parameter_json", None),
        trial_evidence_rows=candidate_training_trial_evidence_rows(candidate),
        aggregate=aggregate,
    )
    if candidate_outcome_evidence_required(aggregate) and not authoritative_aggregate:
        return False
    aggregate = authoritative_aggregate
    aggregate_feasible = aggregate.get("feasible")
    if _uses_experimental_optimizer(candidate) and aggregate_feasible is not True:
        return False
    if aggregate_feasible is not None and aggregate_feasible is not True:
        return False

    try:
        has_trial_relationship = hasattr(candidate, "trials")
        trials = list(getattr(candidate, "trials", ()) or ())
    except Exception:  # pragma: no cover - detached ORM state is not publishable
        return False
    if has_trial_relationship and (
        len(trials) != trial_count or any(not _trial_has_usable_metric(trial) for trial in trials)
    ):
        return False

    configured_contract = _configured_scenario_contract(candidate)
    configured_holdout = False
    if configured_contract is not None:
        expected_cases, configured_holdout = configured_contract
        actual_cases: Counter[tuple[str, bool]] = Counter()
        unique_runs: set[tuple[str, int]] = set()
        for trial in trials:
            config = getattr(trial, "scenario_config_json", None)
            if not isinstance(config, dict):
                return False
            case_id = config.get("scenario_case_id")
            seed = getattr(trial, "seed", None)
            holdout_value = config.get("holdout", False)
            if (
                not isinstance(case_id, str)
                or isinstance(seed, bool)
                or not isinstance(seed, int)
                or not isinstance(holdout_value, bool)
            ):
                return False
            trial_holdout = holdout_value
            actual_cases[(case_id, trial_holdout)] += 1
            unique_runs.add((case_id, seed))
        if not expected_cases or actual_cases != expected_cases or len(unique_runs) != trial_count:
            return False

    def _trial_is_holdout(trial: object) -> bool:
        config = getattr(trial, "scenario_config_json", None)
        return isinstance(config, dict) and config.get("holdout") is True

    expects_holdout = (
        configured_holdout
        or isinstance(aggregate.get("holdout"), dict)
        or any(_trial_is_holdout(trial) for trial in trials)
    )
    if expects_holdout:
        holdout_result = aggregate.get("holdout")
        if not (
            isinstance(holdout_result, dict)
            and holdout_result.get("validation_status") == "passed"
            and holdout_result.get("feasible") is True
        ):
            return False
    return True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_is_cancelled(job_id: str) -> bool:
    """Read a cancellation fence without discarding this session's changes."""

    with SessionLocal() as fence_db:
        return (
            fence_db.scalar(select(models.Job.status).where(models.Job.id == job_id)) == "CANCELLED"
        )


# --- Scoring ---------------------------------------------------------------


def _finite_metric_number(value: object, *, nonnegative: bool = True) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or (nonnegative and numeric < 0.0):
        return None
    return numeric


def _metric_is_usable(metric: models.TrialMetric | None) -> bool:
    if metric is None:
        return False
    overshoot = metric.overshoot_count
    return (
        _finite_metric_number(metric.rmse) is not None
        and _finite_metric_number(metric.max_error) is not None
        and _finite_metric_number(metric.completion_time) is not None
        and _finite_metric_number(metric.score, nonnegative=False) is not None
        and _finite_metric_number(metric.final_error) is not None
        and isinstance(overshoot, int)
        and not isinstance(overshoot, bool)
        and overshoot >= 0
        and all(
            isinstance(flag, bool)
            for flag in (
                metric.crash_flag,
                metric.timeout_flag,
                metric.pass_flag,
                metric.instability_flag,
            )
        )
    )


def _required_metric_number(value: object, *, field_name: str) -> float:
    numeric = _finite_metric_number(
        value,
        nonnegative=field_name != "score",
    )
    if numeric is None:
        raise ValueError(f"trial metric {field_name} is missing or invalid")
    return numeric


def _required_overshoot_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("trial metric overshoot_count is missing or invalid")
    return value


def _trial_has_usable_metric(trial: models.Trial) -> bool:
    return getattr(trial, "status", None) == "COMPLETED" and _metric_is_usable(
        getattr(trial, "metric", None)
    )


def _trial_outcome_class(trial: models.Trial) -> TrialOutcomeClass:
    return classify_trial_outcome(
        status=getattr(trial, "status", None),
        failure_code=getattr(trial, "failure_code", None),
        usable_metric=_trial_has_usable_metric(trial),
    )


def _trial_passed_with_usable_metric(trial: models.Trial) -> bool:
    metric = getattr(trial, "metric", None)
    return (
        getattr(trial, "status", None) == "COMPLETED"
        and _metric_is_usable(metric)
        and metric is not None
        and metric.pass_flag
    )


def _score_candidate(metrics: list[models.TrialMetric], trial_count: int, failed: int) -> float:
    """Compute the deterministic aggregated_score for a candidate.

    Formula (lower is better)::

        score = w_rmse           * mean(rmse)
              + w_max_error      * mean(max_error)
              + w_completion     * mean(completion_time)
              + w_crash          * crash_rate
              + w_timeout        * timeout_rate
              + w_instability    * instability_rate
              + w_failed_trial   * failed_rate

    * ``*_rate`` denominators use ``trial_count`` (dispatched trials), so a
      candidate with many failed trials is penalised correctly even though
      only completed-trial metrics contribute to the mean error terms.
    * All weights live in :data:`constants.SCORE_WEIGHTS` so tests can pin
      the exact values without importing private state.
    """

    w = constants.SCORE_WEIGHTS
    n = max(1, len(metrics))
    denom = max(1, trial_count)

    if not metrics or any(not _metric_is_usable(metric) for metric in metrics):
        raise ValueError("candidate score requires at least one complete valid metric")
    mean_rmse = (
        sum(_required_metric_number(metric.rmse, field_name="rmse") for metric in metrics) / n
    )
    mean_max_error = (
        sum(_required_metric_number(metric.max_error, field_name="max_error") for metric in metrics)
        / n
    )
    mean_completion = (
        sum(
            _required_metric_number(metric.completion_time, field_name="completion_time")
            for metric in metrics
        )
        / n
    )
    crash_rate = sum(1 for m in metrics if m.crash_flag) / denom
    timeout_rate = sum(1 for m in metrics if m.timeout_flag) / denom
    instability_rate = sum(1 for m in metrics if m.instability_flag) / denom
    failed_rate = failed / denom

    score = (
        w["rmse"] * mean_rmse
        + w["max_error"] * mean_max_error
        + w["completion_time"] * mean_completion
        + w["crash"] * crash_rate
        + w["timeout"] * timeout_rate
        + w["instability"] * instability_rate
        + w["failed_trial"] * failed_rate
    )
    return round(score, 4)


def _aggregate_candidate(
    candidate: models.CandidateParameterSet,
    trials: list[models.Trial],
    *,
    objective_config: schemas.ObjectiveConfig | None = None,
    scenario_suite: schemas.ScenarioSuiteConfig | None = None,
    outcome_contract: OptimizationOutcomeContractV1 | None = None,
) -> dict[str, Any] | None:
    """Roll up this candidate's trial metrics, update counts + aggregated_score.

    Returns the aggregated metric dict (also written onto the candidate), or
    ``None`` if no completed trials exist — in which case the candidate is
    ineligible to win.
    """

    completed_trials = [trial for trial in trials if _trial_has_usable_metric(trial)]
    metrics = [t.metric for t in completed_trials if t.metric is not None]

    candidate.trial_count = len(trials)
    candidate.completed_trial_count = len(completed_trials)
    candidate.failed_trial_count = len(trials) - len(completed_trials)
    passing_trial_count = sum(1 for m in metrics if m.pass_flag)

    if not metrics:
        candidate.aggregated_metric_json = None
        candidate.aggregated_score = None
        return None

    cases_by_id = {
        case.id: case
        for case in (scenario_suite.cases if scenario_suite is not None else [])
        if case.enabled
    }
    cases_by_type: dict[str, schemas.ScenarioCaseConfig] = {}
    for case in cases_by_id.values():
        cases_by_type.setdefault(case.scenario_type, case)

    def _resolved_case(
        trial: models.Trial,
    ) -> tuple[str, schemas.ScenarioCaseConfig | None]:
        scenario_config = trial.scenario_config_json or {}
        raw_case_id = scenario_config.get("scenario_case_id")
        if raw_case_id is not None:
            case_id = str(raw_case_id)
            case = cases_by_id.get(case_id)
            if case is not None:
                return f"id:{case_id}", case
            fallback_case = cases_by_type.get(trial.scenario_type)
            if fallback_case is not None:
                return f"id:{fallback_case.id}", fallback_case
            return f"id:{case_id}", None
        case = cases_by_type.get(trial.scenario_type)
        if case is not None:
            return f"id:{case.id}", case
        return f"type:{trial.scenario_type}", None

    def _rate_summary(rows: list[models.Trial]) -> dict[str, Any]:
        """Calculate case-weighted execution and pass rates.

        Seeds are first reduced within their scenario case. Each case then
        contributes exactly its configured ``weight``, independent of how
        many seeds it contains. Failed seeds remain in the per-case
        denominator, so a partially executed case cannot look healthier just
        because only successful rows produced metrics.
        """

        grouped: dict[str, tuple[schemas.ScenarioCaseConfig | None, list[models.Trial]]] = {}
        for trial in rows:
            group_key, case = _resolved_case(trial)
            if group_key not in grouped:
                grouped[group_key] = (case, [])
            grouped[group_key][1].append(trial)

        completed_count = sum(1 for trial in rows if _trial_has_usable_metric(trial))
        failed_count = len(rows) - completed_count
        passing_count = sum(1 for trial in rows if _trial_passed_with_usable_metric(trial))
        outcome_counts = Counter(_trial_outcome_class(trial) for trial in rows)
        if not grouped:
            return {
                "trial_count": 0,
                "completed_trial_count": 0,
                "failed_trial_count": 0,
                "passing_trial_count": 0,
                "completion_rate": 0.0,
                "failure_rate": 0.0,
                "pass_rate": 0.0,
                "scenario_case_count": 0,
                "scenario_weight_total": 0.0,
                "scenario_cases": [],
                "trial_outcome_taxonomy_schema": (
                    TRIAL_OUTCOME_TAXONOMY_SCHEMA
                ),
                "trial_outcome_counts": {
                    outcome_class: 0
                    for outcome_class in TRIAL_OUTCOME_CLASSES
                },
                "trial_outcome_rates": {
                    outcome_class: 0.0
                    for outcome_class in TRIAL_OUTCOME_CLASSES
                },
                "optimizer_learning_failure_rate": 0.0,
                "optimizer_learning_case_weight_total": 0.0,
            }

        weight_total = sum(
            float(case.weight) if case is not None else 1.0 for case, _case_rows in grouped.values()
        )
        weighted_completion = 0.0
        weighted_failure = 0.0
        weighted_pass = 0.0
        weighted_outcome_rates = {
            outcome_class: 0.0
            for outcome_class in TRIAL_OUTCOME_CLASSES
        }
        weighted_optimizer_learning_failure = 0.0
        optimizer_learning_weight_total = 0.0
        case_summaries: list[dict[str, Any]] = []
        for group_key, (case, case_rows) in grouped.items():
            weight = float(case.weight) if case is not None else 1.0
            denominator = len(case_rows)
            case_completed = sum(1 for trial in case_rows if _trial_has_usable_metric(trial))
            case_failed = denominator - case_completed
            case_passing = sum(1 for trial in case_rows if _trial_passed_with_usable_metric(trial))
            case_outcome_counts = Counter(
                _trial_outcome_class(trial) for trial in case_rows
            )
            learning_count = sum(
                count
                for outcome_class, count in case_outcome_counts.items()
                if is_optimizer_learning_outcome(outcome_class)
            )
            learning_failure_count = sum(
                count
                for outcome_class, count in case_outcome_counts.items()
                if is_optimizer_learning_failure(outcome_class)
            )
            weighted_completion += weight * case_completed / denominator
            weighted_failure += weight * case_failed / denominator
            weighted_pass += weight * case_passing / denominator
            for outcome_class in TRIAL_OUTCOME_CLASSES:
                weighted_outcome_rates[outcome_class] += (
                    weight
                    * case_outcome_counts[outcome_class]
                    / denominator
                )
            if learning_count > 0:
                weighted_optimizer_learning_failure += (
                    weight * learning_failure_count / learning_count
                )
                optimizer_learning_weight_total += weight
            case_summaries.append(
                {
                    "scenario_case_id": (
                        case.id if case is not None else group_key.split(":", 1)[-1]
                    ),
                    "scenario_type": (
                        case.scenario_type if case is not None else case_rows[0].scenario_type
                    ),
                    "weight": weight,
                    "trial_count": denominator,
                    "completed_trial_count": case_completed,
                    "failed_trial_count": case_failed,
                    "passing_trial_count": case_passing,
                    "completion_rate": round(case_completed / denominator, 8),
                    "failure_rate": round(case_failed / denominator, 8),
                    "pass_rate": round(case_passing / denominator, 8),
                    "trial_outcome_counts": {
                        outcome_class: case_outcome_counts[outcome_class]
                        for outcome_class in TRIAL_OUTCOME_CLASSES
                    },
                    "optimizer_learning_failure_rate": (
                        round(
                            learning_failure_count / learning_count,
                            8,
                        )
                        if learning_count > 0
                        else None
                    ),
                }
            )

        return {
            "trial_count": len(rows),
            "completed_trial_count": completed_count,
            "failed_trial_count": failed_count,
            "passing_trial_count": passing_count,
            "completion_rate": weighted_completion / weight_total,
            "failure_rate": weighted_failure / weight_total,
            "pass_rate": weighted_pass / weight_total,
            "scenario_case_count": len(grouped),
            "scenario_weight_total": round(weight_total, 8),
            "scenario_cases": case_summaries,
            "trial_outcome_taxonomy_schema": (
                TRIAL_OUTCOME_TAXONOMY_SCHEMA
            ),
            "trial_outcome_counts": {
                outcome_class: outcome_counts[outcome_class]
                for outcome_class in TRIAL_OUTCOME_CLASSES
            },
            "trial_outcome_rates": {
                outcome_class: weighted_outcome_rates[outcome_class]
                / weight_total
                for outcome_class in TRIAL_OUTCOME_CLASSES
            },
            "optimizer_learning_failure_rate": (
                weighted_optimizer_learning_failure
                / optimizer_learning_weight_total
                if optimizer_learning_weight_total > 0.0
                else 0.0
            ),
            "optimizer_learning_case_weight_total": (
                optimizer_learning_weight_total
            ),
        }

    def _case_weighted_metric_mean(
        rows: list[models.Trial],
        *,
        field_name: str,
    ) -> float | None:
        grouped: dict[
            str,
            tuple[schemas.ScenarioCaseConfig | None, list[models.Trial]],
        ] = {}
        for trial in rows:
            group_key, case = _resolved_case(trial)
            if group_key not in grouped:
                grouped[group_key] = (case, [])
            grouped[group_key][1].append(trial)
        weighted_sum = 0.0
        weight_total = 0.0
        for case, case_rows in grouped.values():
            usable_metrics = [
                trial.metric
                for trial in case_rows
                if _trial_has_usable_metric(trial) and trial.metric is not None
            ]
            if not usable_metrics:
                return None
            if field_name == "overshoot_count":
                values = [
                    float(_required_overshoot_count(metric.overshoot_count))
                    for metric in usable_metrics
                ]
            else:
                values = [
                    _required_metric_number(
                        getattr(metric, field_name),
                        field_name=field_name,
                    )
                    for metric in usable_metrics
                ]
            weight = float(case.weight) if case is not None else 1.0
            weighted_sum += weight * sum(values) / len(values)
            weight_total += weight
        if weight_total <= 0.0:
            return None
        return weighted_sum / weight_total

    rmse_decision = _case_weighted_metric_mean(
        trials,
        field_name="rmse",
    )
    rmse = round(rmse_decision, 4) if rmse_decision is not None else None
    max_error_values = [
        _required_metric_number(metric.max_error, field_name="max_error") for metric in metrics
    ]
    max_error_decision = _case_weighted_metric_mean(
        trials,
        field_name="max_error",
    )
    max_error = (
        round(max_error_decision, 4)
        if max_error_decision is not None
        else None
    )
    max_error_worst_decision = max(max_error_values)
    max_error_worst = round(max_error_worst_decision, 4)
    overshoot_decision = _case_weighted_metric_mean(
        trials,
        field_name="overshoot_count",
    )
    overshoot = (
        int(round(overshoot_decision))
        if overshoot_decision is not None
        else None
    )
    completion_time_decision = _case_weighted_metric_mean(
        trials,
        field_name="completion_time",
    )
    completion_time = (
        round(completion_time_decision, 4)
        if completion_time_decision is not None
        else None
    )
    trial_score_decision = _case_weighted_metric_mean(
        trials,
        field_name="score",
    )
    trial_score_mean = (
        round(trial_score_decision, 4)
        if trial_score_decision is not None
        else None
    )

    aggregated_score = _score_candidate(
        metrics, trial_count=len(trials), failed=candidate.failed_trial_count
    )
    overall_rates = _rate_summary(trials)

    agg: dict[str, Any] = {
        "rmse": rmse,
        # ``max_error`` remains the historical mean for report/API
        # compatibility. Acceptance and safety checks use the explicit worst
        # field so a single large excursion is never averaged away.
        "max_error": max_error,
        "max_error_mean": max_error,
        "max_error_worst": max_error_worst,
        "overshoot_count": overshoot,
        "completion_time": completion_time,
        "score": trial_score_mean,
        "aggregated_score": aggregated_score,
        "trial_count": len(trials),
        "completed_trial_count": len(completed_trials),
        "failed_trial_count": candidate.failed_trial_count,
        "invalid_metric_count": sum(
            1
            for trial in trials
            if trial.status == "COMPLETED" and not _metric_is_usable(trial.metric)
        ),
        "cancelled_trial_count": sum(1 for trial in trials if trial.status == "CANCELLED"),
        # Counts remain available for compatibility; the rates below first
        # reduce seeds within each case and then apply scenario weights.
        "passing_trial_count": passing_trial_count,
        "completion_rate": overall_rates["completion_rate"],
        "failure_rate": overall_rates["failure_rate"],
        "failed_trial_rate": overall_rates["failure_rate"],
        "pass_rate": overall_rates["pass_rate"],
        "rate_aggregation": "scenario_case_weighted_v1",
        "scenario_case_rates": overall_rates["scenario_cases"],
        "trial_outcome_taxonomy_schema": overall_rates[
            "trial_outcome_taxonomy_schema"
        ],
        "trial_outcome_counts": overall_rates["trial_outcome_counts"],
        "trial_outcome_rates": overall_rates["trial_outcome_rates"],
        "optimizer_learning_failure_rate": overall_rates[
            "optimizer_learning_failure_rate"
        ],
        "optimizer_learning_case_weight_total": overall_rates[
            "optimizer_learning_case_weight_total"
        ],
    }
    if objective_config is not None:
        within_case_mode = objective_config.robust_aggregation
        across_case_mode = "worst" if within_case_mode == "worst" else "mean"
        objective_estimator = (
            f"within_case_{within_case_mode}_then_fixed_suite_"
            f"{across_case_mode}_v1"
        )

        def _evaluate_rows(
            rows: list[models.Trial],
        ) -> tuple[CandidateEvaluation, dict[str, Any]] | None:
            completed_rows = [trial for trial in rows if _trial_has_usable_metric(trial)]
            if not completed_rows:
                return None
            rate_summary = _rate_summary(rows)
            grouped: dict[
                str,
                tuple[schemas.ScenarioCaseConfig | None, list[models.Trial]],
            ] = {}
            for trial in rows:
                group_key, case = _resolved_case(trial)
                if group_key not in grouped:
                    grouped[group_key] = (case, [])
                grouped[group_key][1].append(trial)

            def _metric_sample(trial: models.Trial) -> dict[str, float]:
                metric = trial.metric
                if metric is None:
                    raise RuntimeError(
                        "aggregation invariant violated: usable trial lost its metric"
                    )
                sample: dict[str, float] = {
                    "rmse": _required_metric_number(metric.rmse, field_name="rmse"),
                    "max_error": _required_metric_number(
                        metric.max_error,
                        field_name="max_error",
                    ),
                    "overshoot_count": float(
                        _required_overshoot_count(metric.overshoot_count)
                    ),
                    "completion_time": _required_metric_number(
                        metric.completion_time,
                        field_name="completion_time",
                    ),
                    "crash_flag": float(metric.crash_flag),
                    "timeout_flag": float(metric.timeout_flag),
                    "score": _required_metric_number(
                        metric.score,
                        field_name="score",
                    ),
                    "final_error": _required_metric_number(
                        metric.final_error,
                        field_name="final_error",
                    ),
                    "pass_flag": float(metric.pass_flag),
                    "instability_flag": float(metric.instability_flag),
                    "completion_rate": float(rate_summary["completion_rate"]),
                    "failed_trial_rate": float(rate_summary["failure_rate"]),
                    "failure_rate": float(rate_summary["failure_rate"]),
                    "pass_rate": float(rate_summary["pass_rate"]),
                }
                raw_metrics = metric.raw_metric_json
                if not isinstance(raw_metrics, dict):
                    raw_metrics = {}
                for key, raw_value in raw_metrics.items():
                    if (
                        key not in sample
                        and isinstance(raw_value, bool | int | float)
                        and math.isfinite(float(raw_value))
                    ):
                        sample[key] = float(raw_value)
                return sample

            case_samples: list[dict[str, float]] = []
            case_weights: list[float] = []
            constraint_samples: list[dict[str, float]] = []
            for group_key, (case, case_rows) in grouped.items():
                usable_rows = [
                    trial for trial in case_rows if _trial_has_usable_metric(trial)
                ]
                if not usable_rows:
                    raise ValueError(
                        "scenario case "
                        f"{group_key.split(':', 1)[-1]} has no usable metric samples"
                    )
                seed_samples = [_metric_sample(trial) for trial in usable_rows]
                common_metrics = set(seed_samples[0]).intersection(
                    *(set(sample) for sample in seed_samples[1:])
                )
                case_sample = {
                    metric_name: sum(
                        sample[metric_name] for sample in seed_samples
                    )
                    / len(seed_samples)
                    for metric_name in sorted(common_metrics)
                }
                for objective in objective_config.objectives:
                    if objective.metric not in common_metrics:
                        raise ValueError(
                            f"missing objective metric: {objective.metric}"
                        )
                    case_sample[objective.metric] = aggregate_metric(
                        [
                            sample[objective.metric]
                            for sample in seed_samples
                        ],
                        direction=objective.direction,
                        mode=within_case_mode,
                        cvar_alpha=objective_config.cvar_alpha,
                        percentile=objective_config.percentile,
                    )
                case_samples.append(case_sample)
                case_weights.append(
                    float(case.weight) if case is not None else 1.0
                )
                constraint_samples.extend(seed_samples)
            return (
                evaluate_objectives(
                    case_samples,
                    objective_config,
                    sample_weights=case_weights,
                    constraint_samples=constraint_samples,
                    objective_aggregation_mode=across_case_mode,
                ),
                rate_summary,
            )

        training_trials = [
            trial for trial in trials if not trial_is_holdout(trial)
        ]
        try:
            training_result = _evaluate_rows(training_trials)
        except ValueError as exc:
            agg["objective_evaluation_error"] = str(exc)
            candidate.aggregated_metric_json = agg
            candidate.aggregated_score = None
            return agg
        if training_result is None:
            agg["objective_evaluation_error"] = "no completed training scenario metrics"
            candidate.aggregated_metric_json = agg
            candidate.aggregated_score = None
            return agg
        evaluation, training_rates = training_result
        training_completed = [trial for trial in training_trials if _trial_has_usable_metric(trial)]
        training_metrics = [
            trial.metric for trial in training_completed if trial.metric is not None
        ]
        training_passing = sum(1 for metric in training_metrics if metric.pass_flag)
        training_failed = len(training_trials) - len(training_completed)
        training_max_errors = [
            _required_metric_number(metric.max_error, field_name="max_error")
            for metric in training_metrics
        ]
        training_rmse_decision = _case_weighted_metric_mean(
            training_trials,
            field_name="rmse",
        )
        training_max_error_decision = _case_weighted_metric_mean(
            training_trials,
            field_name="max_error",
        )
        training_overshoot_decision = _case_weighted_metric_mean(
            training_trials,
            field_name="overshoot_count",
        )
        training_completion_time_decision = _case_weighted_metric_mean(
            training_trials,
            field_name="completion_time",
        )
        training_score_decision = _case_weighted_metric_mean(
            training_trials,
            field_name="score",
        )
        if any(
            value is None
            for value in (
                training_rmse_decision,
                training_max_error_decision,
                training_overshoot_decision,
                training_completion_time_decision,
                training_score_decision,
            )
        ):
            raise RuntimeError(
                "aggregation invariant violated: evaluated case lost compatibility metrics"
            )
        assert training_rmse_decision is not None
        assert training_max_error_decision is not None
        assert training_overshoot_decision is not None
        assert training_completion_time_decision is not None
        assert training_score_decision is not None
        training_max_error_worst_decision = max(training_max_errors)
        agg.update(
            {
                "rmse": round(float(training_rmse_decision), 4),
                "max_error": round(
                    float(training_max_error_decision),
                    4,
                ),
                "max_error_mean": round(
                    float(training_max_error_decision),
                    4,
                ),
                "max_error_worst": round(
                    training_max_error_worst_decision,
                    4,
                ),
                "overshoot_count": int(
                    round(float(training_overshoot_decision))
                ),
                "completion_time": round(
                    float(training_completion_time_decision),
                    4,
                ),
                "score": round(float(training_score_decision), 4),
                "acceptance_projection_schema": "dronedream.acceptance-projection/v1",
                "acceptance_rmse": float(training_rmse_decision),
                "acceptance_max_error": training_max_error_worst_decision,
                "acceptance_pass_rate": float(training_rates["pass_rate"]),
                "acceptance_completion_rate": float(
                    training_rates["completion_rate"]
                ),
                "training_completed_trial_count": len(training_completed),
                "training_failed_trial_count": training_failed,
                "training_passing_trial_count": training_passing,
                "completion_rate": training_rates["completion_rate"],
                "failure_rate": training_rates["failure_rate"],
                "failed_trial_rate": training_rates["failure_rate"],
                "pass_rate": training_rates["pass_rate"],
                "training_completion_rate": training_rates["completion_rate"],
                "training_failure_rate": training_rates["failure_rate"],
                "training_pass_rate": training_rates["pass_rate"],
                "training_scenario_case_rates": training_rates["scenario_cases"],
                "training_trial_outcome_taxonomy_schema": training_rates[
                    "trial_outcome_taxonomy_schema"
                ],
                "training_trial_outcome_counts": training_rates[
                    "trial_outcome_counts"
                ],
                "training_trial_outcome_rates": training_rates[
                    "trial_outcome_rates"
                ],
                "optimizer_learning_failure_rate": training_rates[
                    "optimizer_learning_failure_rate"
                ],
                "optimizer_learning_case_weight_total": training_rates[
                    "optimizer_learning_case_weight_total"
                ],
            }
        )
        training_failure_rate = float(training_rates["failure_rate"])
        selection_score = (
            evaluation.scalar_loss + constants.SCORE_WEIGHTS["failed_trial"] * training_failure_rate
        )
        aggregated_score = round(selection_score, 8)
        selection_key = build_selection_key(
            evidence_complete=(
                len(training_completed) == len(training_trials) and training_failed == 0
            ),
            hard_feasible=evaluation.feasible,
            hard_constraint_violation=evaluation.hard_constraint_violation,
            training_failure_rate=training_failure_rate,
            decision_loss=evaluation.scalar_loss,
        )
        agg.update(
            {
                "aggregated_score": aggregated_score,
                "objective_values": evaluation.objectives,
                "constraint_values": evaluation.constraint_values,
                "constraint_violations": evaluation.violations,
                "feasible": evaluation.feasible,
                "total_constraint_violation": evaluation.total_violation,
                "hard_constraint_violation": (evaluation.hard_constraint_violation),
                "robust_aggregation": objective_config.robust_aggregation,
                "objective_estimator": objective_estimator,
                "constraint_estimator": "worst_usable_seed_v1",
                "preference_loss": evaluation.preference_loss,
                "soft_constraint_penalty": evaluation.soft_constraint_penalty,
                "scalar_loss": evaluation.scalar_loss,
                "selection_key": selection_key,
                "training_trial_count": len(training_trials),
            }
        )
        if outcome_contract is not None:
            agg["outcome_contract_schema"] = outcome_contract.schema_id
            agg["outcome_contract_id"] = outcome_contract.contract_id
        holdout_trials = [
            trial for trial in trials if trial_is_holdout(trial)
        ]
        if holdout_trials:
            holdout_rates = _rate_summary(holdout_trials)
            holdout_payload: dict[str, Any] = {
                "trial_count": int(holdout_rates["trial_count"]),
                "completed_trial_count": int(holdout_rates["completed_trial_count"]),
                "failed_trial_count": int(holdout_rates["failed_trial_count"]),
                "passing_trial_count": int(holdout_rates["passing_trial_count"]),
                "completion_rate": float(holdout_rates["completion_rate"]),
                "failure_rate": float(holdout_rates["failure_rate"]),
                "failed_trial_rate": float(holdout_rates["failure_rate"]),
                "pass_rate": float(holdout_rates["pass_rate"]),
                "scenario_case_count": int(holdout_rates["scenario_case_count"]),
                "scenario_weight_total": float(holdout_rates["scenario_weight_total"]),
                "scenario_case_rates": holdout_rates["scenario_cases"],
                "trial_outcome_taxonomy_schema": holdout_rates[
                    "trial_outcome_taxonomy_schema"
                ],
                "trial_outcome_counts": holdout_rates[
                    "trial_outcome_counts"
                ],
                "trial_outcome_rates": holdout_rates[
                    "trial_outcome_rates"
                ],
            }
            try:
                holdout_result = _evaluate_rows(holdout_trials)
            except ValueError as exc:
                holdout_payload.update(
                    {
                        "evaluation_error": str(exc),
                        "validation_status": "error",
                        "feasible": False,
                    }
                )
            else:
                if holdout_result is None:
                    holdout_payload.update(
                        {
                            "evaluation_error": "no completed holdout metrics",
                            "validation_status": "failed",
                            "feasible": False,
                        }
                    )
                else:
                    holdout_evaluation, _holdout_summary = holdout_result
                    trial_count = int(holdout_rates["trial_count"])
                    completed_count = int(holdout_rates["completed_trial_count"])
                    passing_count = int(holdout_rates["passing_trial_count"])
                    execution_complete = completed_count == trial_count
                    all_trials_passed = passing_count == trial_count
                    validation_feasible = (
                        holdout_evaluation.feasible and execution_complete and all_trials_passed
                    )
                    if not execution_complete:
                        validation_status = "incomplete"
                    elif not all_trials_passed or not holdout_evaluation.feasible:
                        validation_status = "failed"
                    else:
                        validation_status = "passed"
                    holdout_payload.update(
                        {
                            "objective_values": holdout_evaluation.objectives,
                            "constraint_values": holdout_evaluation.constraint_values,
                            "constraint_violations": holdout_evaluation.violations,
                            "objective_feasible": holdout_evaluation.feasible,
                            "feasible": validation_feasible,
                            "validation_status": validation_status,
                            "total_constraint_violation": (holdout_evaluation.total_violation),
                            "hard_constraint_violation": (
                                holdout_evaluation.hard_constraint_violation
                            ),
                            "objective_estimator": objective_estimator,
                            "constraint_estimator": "worst_usable_seed_v1",
                            "preference_loss": holdout_evaluation.preference_loss,
                            "soft_constraint_penalty": (holdout_evaluation.soft_constraint_penalty),
                            "scalar_loss": holdout_evaluation.scalar_loss,
                        }
                    )
            agg["holdout"] = holdout_payload
        if outcome_contract is not None:
            ordered_training_trials = sorted(
                training_trials,
                key=lambda trial: (
                    trial.scenario_type,
                    trial.seed,
                    trial.id,
                ),
            )
            report_trial_rows = candidate_report_trial_evidence_rows(
                candidate,
                bind_artifacts=True,
                bind_attempts=True,
                verify_artifact_bytes=True,
            )
            if report_trial_rows is None:
                raise ValueError(
                    "candidate report evidence requires readable, "
                    "byte-verified Trial artifact rows"
                )
            report_rows_by_trial_id = {
                str(row["trial_id"]): row for row in report_trial_rows
            }
            training_trial_rows = [
                report_rows_by_trial_id[trial.id]
                for trial in ordered_training_trials
            ]
            evidence = compile_candidate_outcome_evidence(
                outcome_contract_id=outcome_contract.contract_id,
                candidate_id=candidate.id,
                generation_index=candidate.generation_index,
                parameter_snapshot=candidate.parameter_json,
                trial_evidence_rows=training_trial_rows,
                aggregate=agg,
                bind_trial_artifacts=True,
                bind_trial_attempts=True,
            )
            agg["candidate_outcome_evidence_required"] = True
            agg["candidate_outcome_evidence"] = evidence.model_dump(mode="json")
            report_evidence = compile_candidate_report_evidence(
                candidate_outcome_evidence=evidence.model_dump(mode="json"),
                report_trial_evidence_rows=report_trial_rows,
                aggregate=agg,
            )
            agg["candidate_report_evidence_required"] = True
            agg["candidate_report_evidence"] = report_evidence.model_dump(
                mode="json"
            )
    candidate.aggregated_metric_json = agg
    candidate.aggregated_score = aggregated_score
    return agg


# --- Best selection --------------------------------------------------------


def _is_eligible(candidate: models.CandidateParameterSet) -> bool:
    """Compatibility wrapper for the public recommendation contract."""

    return candidate_is_publishable(candidate)


def _rank_and_select_best(
    candidates: list[models.CandidateParameterSet],
) -> models.CandidateParameterSet | None:
    """Assign ``rank_in_job`` to every scorable candidate, mark best, return it.

    Sorting key: aggregated_score ascending, with baseline tie-broken last so
    a tied optimizer candidate wins (the report is more useful when the
    optimized column differs from the baseline column).
    """

    for candidate in candidates:
        candidate.rank_in_job = None
        candidate.is_best = False
    scorable = [candidate for candidate in candidates if candidate_is_publishable(candidate)]
    if not scorable:
        return None

    scorable.sort(
        key=lambda c: (
            *selection_order_key(
                c.aggregated_metric_json,
                c.aggregated_score,
            ),
            0 if not c.is_baseline else 1,
            c.generation_index,
            c.id,
        )
    )

    for rank, candidate in enumerate(scorable, start=1):
        candidate.rank_in_job = rank
    best = scorable[0]
    best.is_best = True
    return best


def _compile_current_winner_evidence(
    *,
    candidates: list[models.CandidateParameterSet],
    baseline: models.CandidateParameterSet,
    best: models.CandidateParameterSet,
    outcome_contract: OptimizationOutcomeContractV1,
) -> WinnerSelectionEvidenceV1:
    inputs: list[dict[str, object]] = []
    outcome_projections: dict[str, dict[str, Any]] = {}
    report_projections: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        outcome = authoritative_candidate_trial_outcome_projection(
            candidate_id=candidate.id,
            generation_index=candidate.generation_index,
            parameter_snapshot=candidate.parameter_json,
            trial_evidence_rows=candidate_training_trial_evidence_rows(
                candidate
            ),
            aggregate=candidate.aggregated_metric_json,
        )
        try:
            report = require_authoritative_candidate_report_projection(
                candidate
            )
        except ValueError as exc:
            raise WinnerSelectionEvidenceError(str(exc)) from exc
        order = selection_order_key(
            candidate.aggregated_metric_json,
            candidate.aggregated_score,
        )
        if not outcome or not report:
            raise WinnerSelectionEvidenceError(
                "winner evidence requires authoritative Candidate inputs "
                f"for {candidate.id}"
            )
        finite_order = (
            order
            if all(math.isfinite(float(value)) for value in order)
            else None
        )
        eligible = candidate_is_publishable(candidate)
        if eligible and finite_order is None:
            raise WinnerSelectionEvidenceError(
                "publishable Candidate has a non-finite Selection Key: "
                f"{candidate.id} -> {order}"
            )
        inputs.append(
            {
                "candidate_id": candidate.id,
                "generation_index": candidate.generation_index,
                "is_baseline": candidate.is_baseline,
                "eligible": eligible,
                "candidate_outcome_evidence_id": report.get(
                    "candidate_outcome_evidence_id"
                ),
                "candidate_report_evidence_id": report.get(
                    "candidate_report_evidence_id"
                ),
                "selection_order_key": finite_order,
            }
        )
        outcome_projections[candidate.id] = outcome
        report_projections[candidate.id] = report
    evidence = compile_winner_selection_evidence(
        outcome_contract_id=outcome_contract.contract_id,
        baseline_candidate_id=baseline.id,
        winner_candidate_id=best.id,
        candidates=inputs,
    )
    if not winner_evidence_matches_current_candidates(
        evidence.model_dump(mode="json"),
        candidates=candidates,
        outcome_projections=outcome_projections,
        report_projections=report_projections,
    ):
        raise WinnerSelectionEvidenceError(
            "winner evidence does not match persisted Candidate ranks"
        )
    return evidence


# --- Finalization ----------------------------------------------------------


def finalize_job_if_ready(
    db: Session,
    job: models.Job,
    *,
    llm_client: object | None = None,
) -> bool:
    """If every trial is terminal, aggregate candidates and finalize the job.

    For GPT jobs this method implements the iterative loop: after aggregating
    the current generation it evaluates acceptance and, if neither accepted
    nor budget-exhausted, dispatches the next LLM-proposed generation instead
    of finalizing. The job is only marked terminal when either a candidate
    passes acceptance, the acceptance criteria are not configured, or the
    iteration/trial budget is exhausted.
    """

    if job.status not in {"RUNNING", "AGGREGATING", "FINALIZING"}:
        return False

    trials = list(job.trials)
    if not trials:
        return False
    if not all(t.status in _TERMINAL_TRIAL for t in trials):
        return False

    # RUNNING -> AGGREGATING transition so the frontend can display the phase.
    if job.status == "RUNNING":
        job.status = "AGGREGATING"
        job.current_phase = "aggregating"
        record_event(db, job.id, "aggregation_started", None)
        db.commit()
        db.refresh(job)
        trials = list(job.trials)

    baseline_id = job.baseline_candidate_id
    if baseline_id is None:
        _fail_job(db, job, code="BASELINE_MISSING", message="No baseline candidate was created.")
        return True
    baseline = db.get(models.CandidateParameterSet, baseline_id)
    if baseline is None:
        _fail_job(db, job, code="BASELINE_MISSING", message="Baseline candidate row missing.")
        return True

    # Aggregate every candidate (baseline first so the baseline_agg variable
    # is available for the report builder).
    candidates = list(job.candidates)
    trials_by_candidate: dict[str, list[models.Trial]] = {}
    for t in trials:
        trials_by_candidate.setdefault(t.candidate_id, []).append(t)

    objective_config = (
        schemas.ObjectiveConfig(**job.objective_config_json)
        if job.objective_config_json is not None
        else None
    )
    scenario_suite = (
        schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
        if job.scenario_suite_json is not None
        else None
    )
    outcome_contract_check = check_job_outcome_contract(db, job)
    outcome_contract = outcome_contract_check.contract
    if not outcome_contract_check.valid:
        _fail_job(
            db,
            job,
            code="OUTCOME_CONTRACT_DRIFT",
            message=(
                "The persisted optimization outcome contract no longer "
                "matches the Job configuration; refusing to rank candidates."
            ),
        )
        return True
    baseline_agg = _aggregate_candidate(
        baseline,
        trials_by_candidate.get(baseline.id, []),
        objective_config=objective_config,
        scenario_suite=scenario_suite,
        outcome_contract=outcome_contract,
    )
    for candidate in candidates:
        if candidate.id == baseline.id:
            continue
        _aggregate_candidate(
            candidate,
            trials_by_candidate.get(candidate.id, []),
            objective_config=objective_config,
            scenario_suite=scenario_suite,
            outcome_contract=outcome_contract,
        )

    # Persist aggregation results before any report storage or LLM network I/O.
    # This releases SQLite's write lock while a provider or filesystem is slow.
    db.commit()
    if _job_is_cancelled(job.id):
        db.rollback()
        return True

    if baseline_agg is None:
        _fail_job(
            db,
            job,
            code="ALL_TRIALS_FAILED",
            message=(
                "All baseline trials failed; cannot produce a report. "
                "Inspect trial failures on the job detail page."
            ),
        )
        return True

    criteria = criteria_for_job(job)

    # Iterative optimizer loop (GPT / CMA-ES-style): possibly dispatch another
    # generation instead of finalizing.
    if job.optimizer_strategy in _ITERATIVE_OPTIMIZERS:
        if _try_continue_iterative_optimizer(
            db, job, baseline, candidates, criteria, llm_client=llm_client
        ):
            return False
        if job.status in {"FAILED", "COMPLETED", "CANCELLED"}:
            return True

    best = _rank_and_select_best(candidates)
    if best is None or best.aggregated_metric_json is None:
        _finalize_without_usable_candidate(db, job, baseline_agg=baseline_agg, baseline=baseline)
        return True

    job.best_candidate_id = best.id

    try:
        winner_evidence = (
            _compile_current_winner_evidence(
                candidates=candidates,
                baseline=baseline,
                best=best,
                outcome_contract=outcome_contract,
            )
            if outcome_contract is not None
            and any(
                candidate_report_evidence_required(
                    candidate.aggregated_metric_json
                )
                for candidate in candidates
            )
            else None
        )
        report = report_generator.generate_and_persist_report(
            db,
            job=job,
            best=best,
            baseline_agg=baseline_agg,
            best_agg=best.aggregated_metric_json,
            winner_evidence=winner_evidence,
        )
    except (
        report_generator.ReportEvidenceError,
        WinnerSelectionEvidenceError,
    ) as exc:
        logger.warning(
            "job %s report evidence rejected (%s): %s",
            job.id,
            type(exc).__name__,
            exc,
        )
        _fail_job(
            db,
            job,
            code="REPORT_EVIDENCE_INVALID",
            message=(
                "Candidate report or winner-selection evidence no longer "
                "matches current Candidate/Trial state; refusing to publish."
            ),
        )
        return True

    winner_evidence_id = (
        report.winner_evidence_json.get("evidence_id")
        if isinstance(report.winner_evidence_json, dict)
        else None
    )
    winner_freeze_receipt_id = report.winner_freeze_receipt_id
    if _job_is_cancelled(job.id):
        db.rollback()
        return True

    outcome, terminal_status, terminal_error = _determine_terminal_state(job, best, criteria)
    now = _now()
    job.status = terminal_status
    job.current_phase = "completed" if terminal_status == "COMPLETED" else None
    job.optimization_outcome = outcome
    if terminal_status == "COMPLETED":
        job.completed_at = now
    else:
        job.failed_at = now
        if terminal_error is not None:
            job.latest_error_code, job.latest_error_message = terminal_error

    record_event(
        db,
        job.id,
        "best_candidate_selected",
        {
            "best_candidate_id": best.id,
            "baseline_candidate_id": baseline.id,
            "best_source_type": best.source_type,
            "best_score": best.aggregated_score,
            "baseline_score": baseline.aggregated_score,
            "optimization_outcome": outcome,
            "winner_evidence_id": winner_evidence_id,
            "winner_freeze_receipt_id": winner_freeze_receipt_id,
        },
    )
    if terminal_status == "COMPLETED":
        record_event(
            db,
            job.id,
            "job_completed",
            {
                "best_candidate_id": best.id,
                "aggregated_score": best.aggregated_score,
                "optimization_outcome": outcome,
                "winner_evidence_id": winner_evidence_id,
                "winner_freeze_receipt_id": winner_freeze_receipt_id,
            },
        )
    else:
        record_event(
            db,
            job.id,
            "job_failed",
            {
                "code": (terminal_error[0] if terminal_error else "UNKNOWN"),
                "message": (terminal_error[1] if terminal_error else ""),
                "best_candidate_id": best.id,
                "optimization_outcome": outcome,
            },
        )
    _purge_secrets_on_terminal(db, job)
    db.commit()
    logger.info(
        "job %s %s (best=%s score=%s baseline_score=%s outcome=%s)",
        job.id,
        terminal_status,
        best.id,
        best.aggregated_score,
        baseline.aggregated_score,
        outcome,
    )
    return True


def _determine_terminal_state(
    job: models.Job,
    best: models.CandidateParameterSet,
    criteria: AcceptanceCriteria,
) -> tuple[str, str, tuple[str, str] | None]:
    """Return ``(optimization_outcome, job_status, optional_error)``.

    Heuristic jobs are kept on the Phase 7 happy path (COMPLETED) but are now
    annotated with an ``optimization_outcome`` so the UI can surface whether
    the best candidate actually met the user's acceptance criteria.
    """

    result = evaluate_candidate(best, criteria)
    if result.passed:
        return "success", "COMPLETED", None
    # No criteria set → treat completion as success by convention.
    if not any_criterion_set(criteria) and criteria.min_pass_rate <= (result.pass_rate + 1e-9):
        return "success", "COMPLETED", None
    if job.optimizer_strategy in _ITERATIVE_OPTIMIZERS:
        # Iterative optimizer exhausted iteration/trial budget without finding
        # a passing candidate — report best-so-far as a completed run.
        if job.current_generation >= job.max_iterations:
            return ("max_iterations_reached", "COMPLETED", None)
        return ("no_usable_candidate", "COMPLETED", None)
    # Heuristic: stay COMPLETED (Phase 7 contract) but flag the outcome.
    return "no_usable_candidate", "COMPLETED", None


def _try_continue_iterative_optimizer(
    db: Session,
    job: models.Job,
    baseline: models.CandidateParameterSet,
    candidates: list[models.CandidateParameterSet],
    criteria: AcceptanceCriteria,
    *,
    llm_client: object | None,
) -> bool:
    """If an iterative optimizer should run another generation, dispatch it.

    Guarantees of the loop:

    * If any scored candidate (including baseline) passes acceptance, we stop
      and let the caller finalize as COMPLETED.
    * If acceptance criteria are not configured, we don't proceed past the
      baseline generation — the baseline is implicitly accepted.
    * Respects ``max_iterations`` and ``max_total_trials``.
    """

    scored = [candidate for candidate in candidates if candidate_is_publishable(candidate)]
    passed = any_criterion_set(criteria) and any(
        evaluate_candidate(c, criteria).passed for c in scored
    )
    needs_verified_optimizer = job.optimizer_strategy in {
        "llm_harness",
        *EXPERIMENTAL_OPTIMIZER_STRATEGIES,
    } and not any(
        candidate.source_type == "optimizer" and candidate_is_publishable(candidate)
        for candidate in candidates
    )
    if passed and not needs_verified_optimizer:
        return False
    if job.current_generation >= job.max_iterations:
        return False
    from app.orchestration.job_manager import (
        dispatch_next_cma_es_generation,
        dispatch_next_experimental_generation,
        dispatch_next_harness_generation,
        dispatch_next_llm_generation,
    )
    from app.orchestration.llm_parameter_proposer import OpenAIClientLike

    client_cast: OpenAIClientLike | None = None
    if llm_client is not None:
        client_cast = llm_client  # type: ignore[assignment]

    if job.optimizer_strategy == "gpt":
        llm_dispatch = dispatch_next_llm_generation(db, job, client=client_cast)
        if llm_dispatch.status == "llm_error":
            _fail_job(
                db,
                job,
                code="LLM_FAILED",
                message=llm_dispatch.error or "LLM proposer failed.",
                outcome="llm_failed",
            )
            return False
        if llm_dispatch.status in {
            "budget_exhausted",
            "max_iterations_reached",
            "no_usable_proposal",
        }:
            return False
    elif job.optimizer_strategy == "llm_harness":
        harness_dispatch = dispatch_next_harness_generation(
            db,
            job,
            client=client_cast,
        )
        if harness_dispatch.status in {
            "budget_exhausted",
            "max_iterations_reached",
            "search_space_exhausted",
        }:
            return False
    elif job.optimizer_strategy == "cma_es":
        cma_dispatch = dispatch_next_cma_es_generation(db, job)
        if cma_dispatch.status in {
            "budget_exhausted",
            "max_iterations_reached",
            "search_space_exhausted",
        }:
            return False
    elif job.optimizer_strategy in EXPERIMENTAL_OPTIMIZER_STRATEGIES:
        experimental_dispatch = dispatch_next_experimental_generation(db, job)
        if experimental_dispatch.status in {
            "budget_exhausted",
            "max_iterations_reached",
            "search_space_exhausted",
        }:
            return False
    else:
        return False

    # Re-check the persisted state after an external LLM call. Cancellation is
    # allowed while FINALIZING and must never be overwritten by the worker.
    if _job_is_cancelled(job.id):
        db.rollback()
        return False
    # Return to RUNNING so the worker keeps draining trials.
    job.status = "RUNNING"
    db.commit()
    db.refresh(job)
    return True


def _finalize_without_usable_candidate(
    db: Session,
    job: models.Job,
    *,
    baseline_agg: dict[str, Any] | None,
    baseline: models.CandidateParameterSet,
) -> None:
    """Terminal state when no candidate produced a usable aggregate."""

    db.refresh(job)
    if job.status == "CANCELLED":
        db.rollback()
        return

    if baseline_agg is not None:
        # Preserve a diagnostic baseline comparison without publishing a
        # partial/failed baseline as a validated parameter recommendation.
        job.best_candidate_id = None
        baseline.is_best = False
        report_generator.generate_and_persist_report(
            db,
            job=job,
            best=baseline,
            baseline_agg=baseline_agg,
            best_agg=baseline_agg,
        )
        if _job_is_cancelled(job.id):
            db.rollback()
            return
    now = _now()
    job.status = "COMPLETED"
    job.completed_at = now
    job.current_phase = "completed"
    job.optimization_outcome = "no_usable_candidate"
    record_event(
        db,
        job.id,
        "job_completed",
        {
            "best_candidate_id": job.best_candidate_id,
            "optimization_outcome": "no_usable_candidate",
        },
    )
    _purge_secrets_on_terminal(db, job)
    db.commit()


def _purge_secrets_on_terminal(db: Session, job: models.Job) -> None:
    """Best-effort wipe of stored secrets once the job is about to become terminal."""

    from app.services.jobs import purge_job_secrets

    purge_job_secrets(db, job, reason="job_terminal")


def _fail_job(
    db: Session,
    job: models.Job,
    *,
    code: str,
    message: str,
    outcome: str | None = None,
) -> None:
    if _job_is_cancelled(job.id):
        db.rollback()
        return
    now = _now()
    job.status = "FAILED"
    job.failed_at = now
    job.current_phase = None
    job.latest_error_code = code
    job.latest_error_message = message
    if outcome is not None:
        job.optimization_outcome = outcome
    record_event(db, job.id, "job_failed", {"code": code, "message": message})
    _purge_secrets_on_terminal(db, job)
    db.commit()
    logger.warning("job %s FAILED code=%s", job.id, code)


# Module-level LLM-client override so tests (and potential future operator
# tooling) can substitute a deterministic :class:`OpenAIClientLike` for the
# real OpenAI SDK call without monkey-patching every entry point.
_llm_client_override: object | None = None


def set_llm_client_override(client: object | None) -> None:
    """Install or clear a process-wide fake OpenAI client for GPT tuning."""

    global _llm_client_override
    _llm_client_override = client


def finalize_ready_jobs(db: Session, *, limit: int = 20) -> list[str]:
    """Claim and finalize ready jobs without holding a DB lock over external I/O.

    ``FINALIZING`` plus ``updated_at`` acts as a bounded lease. The claim is
    committed before report/LLM work; a crashed worker's stale claim becomes
    reclaimable after ``FINALIZATION_LEASE_SECONDS``.
    """

    finalized: list[str] = []
    examined: set[str] = set()
    for _ in range(max(0, limit)):
        # Recompute immediately before each atomic claim. A preceding job may
        # spend minutes in an LLM call, so reusing the function-entry timestamp
        # could make a later claim stale the instant it is committed.
        claim_time = _now()
        stale_before = claim_time - timedelta(seconds=get_settings().finalization_lease_seconds)
        claimable = or_(
            models.Job.status.in_(["RUNNING", "AGGREGATING"]),
            and_(
                models.Job.status == "FINALIZING",
                models.Job.updated_at <= stale_before,
            ),
        )
        stmt = select(models.Job).where(claimable)
        if examined:
            stmt = stmt.where(models.Job.id.not_in(examined))
        job = db.scalars(stmt.order_by(models.Job.updated_at.asc()).limit(1)).first()
        if job is None:
            break
        examined.add(job.id)
        trials = list(job.trials)
        if not trials or not all(t.status in _TERMINAL_TRIAL for t in trials):
            continue
        claimed = db.execute(
            update(models.Job)
            .where(
                models.Job.id == job.id,
                claimable,
            )
            .values(
                status="FINALIZING",
                current_phase="aggregating",
                updated_at=claim_time,
            )
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            continue
        db.expire(job)
        db.refresh(job)
        record_event(db, job.id, "aggregation_started", None)
        db.commit()
        db.refresh(job)
        try:
            if finalize_job_if_ready(db, job, llm_client=_llm_client_override):
                finalized.append(job.id)
        except Exception as exc:
            logger.exception("job %s finalization crashed", job.id)
            db.rollback()
            failed_job = db.get(models.Job, job.id)
            if failed_job is None or failed_job.status == "CANCELLED":
                continue
            try:
                _fail_job(
                    db,
                    failed_job,
                    code="FINALIZATION_FAILED",
                    message=(
                        "Finalization failed while producing optimizer output or "
                        f"artifacts: {str(exc)[:500]}"
                    ),
                    outcome="no_usable_candidate",
                )
                finalized.append(job.id)
            except Exception:
                db.rollback()
                logger.exception("job %s could not be marked failed", job.id)
    return finalized
