"""Job aggregation + best-candidate selection (Phase 5).

Once every trial for a job is terminal, this module:

1. Moves the job to ``AGGREGATING``.
2. For each ``CandidateParameterSet`` (baseline and every optimizer
   candidate), rolls up the candidate's completed trials into
   ``aggregated_metric_json`` / ``aggregated_score``, and persists trial
   counts. See :func:`_aggregate_candidate`.
3. Selects the best candidate by lowest ``aggregated_score`` among candidates
   that completed the entire configured full-fidelity scenario matrix, passed
   every required holdout, and satisfied all persisted hard constraints.
4. Ranks every candidate (``rank_in_job``, 1-indexed) and marks ``is_best``
   on the winner.
5. Writes the ``JobReport`` using the baseline's aggregate as the baseline
   and the winner's aggregate as the optimized comparison.
6. Sets the job ``COMPLETED`` (or ``FAILED`` only when no candidate produced
   a usable aggregate).

The scoring formula is deterministic and documented in
:func:`_score_candidate`. Lower is better.
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
from app.optimization.robust import CandidateEvaluation
from app.optimization.robust import evaluate_candidate as evaluate_objectives
from app.optimization.scenarios import scenario_matrix
from app.orchestration import constants, report_generator
from app.orchestration.acceptance import (
    AcceptanceCriteria,
    any_criterion_set,
    criteria_for_job,
    evaluate_candidate,
)
from app.orchestration.events import record_event

logger = logging.getLogger("drone_dream.orchestration.aggregation")

_TERMINAL_TRIAL = {"COMPLETED", "FAILED", "CANCELLED"}
_ITERATIVE_OPTIMIZERS = {
    "gpt",
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

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4)

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
            }

        weight_total = sum(
            float(case.weight) if case is not None else 1.0 for case, _case_rows in grouped.values()
        )
        weighted_completion = 0.0
        weighted_failure = 0.0
        weighted_pass = 0.0
        case_summaries: list[dict[str, Any]] = []
        for group_key, (case, case_rows) in grouped.items():
            weight = float(case.weight) if case is not None else 1.0
            denominator = len(case_rows)
            case_completed = sum(1 for trial in case_rows if _trial_has_usable_metric(trial))
            case_failed = denominator - case_completed
            case_passing = sum(1 for trial in case_rows if _trial_passed_with_usable_metric(trial))
            weighted_completion += weight * case_completed / denominator
            weighted_failure += weight * case_failed / denominator
            weighted_pass += weight * case_passing / denominator
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
                }
            )

        return {
            "trial_count": len(rows),
            "completed_trial_count": completed_count,
            "failed_trial_count": failed_count,
            "passing_trial_count": passing_count,
            "completion_rate": round(weighted_completion / weight_total, 8),
            "failure_rate": round(weighted_failure / weight_total, 8),
            "pass_rate": round(weighted_pass / weight_total, 8),
            "scenario_case_count": len(grouped),
            "scenario_weight_total": round(weight_total, 8),
            "scenario_cases": case_summaries,
        }

    rmse = _avg([_required_metric_number(metric.rmse, field_name="rmse") for metric in metrics])
    max_error_values = [
        _required_metric_number(metric.max_error, field_name="max_error") for metric in metrics
    ]
    max_error = _avg(max_error_values)
    max_error_worst = round(max(max_error_values), 4)
    overshoot = int(
        round(
            sum(_required_overshoot_count(metric.overshoot_count) for metric in metrics)
            / len(metrics)
        )
    )
    completion_time = _avg(
        [
            _required_metric_number(
                metric.completion_time,
                field_name="completion_time",
            )
            for metric in metrics
        ]
    )
    trial_score_mean = _avg(
        [_required_metric_number(metric.score, field_name="score") for metric in metrics]
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
    }
    if objective_config is not None:

        def _evaluate_rows(
            rows: list[models.Trial],
        ) -> tuple[CandidateEvaluation, dict[str, Any]] | None:
            completed_rows = [trial for trial in rows if _trial_has_usable_metric(trial)]
            if not completed_rows:
                return None
            rate_summary = _rate_summary(rows)
            samples: list[dict[str, float]] = []
            sample_weights: list[float] = []
            resolved_cases = [_resolved_case(trial) for trial in completed_rows]
            dispatched_per_case = Counter(_resolved_case(trial)[0] for trial in rows)
            for trial, (group_key, case) in zip(completed_rows, resolved_cases, strict=True):
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
                    "overshoot_count": float(_required_overshoot_count(metric.overshoot_count)),
                    "completion_time": _required_metric_number(
                        metric.completion_time,
                        field_name="completion_time",
                    ),
                    "crash_flag": float(metric.crash_flag),
                    "timeout_flag": float(metric.timeout_flag),
                    "score": _required_metric_number(metric.score, field_name="score"),
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
                        and isinstance(raw_value, (bool, int, float))
                        and math.isfinite(float(raw_value))
                    ):
                        sample[key] = float(raw_value)
                samples.append(sample)
                # A case weight is shared by every dispatched seed, including
                # seeds that failed before producing metrics. This prevents a
                # lone surviving seed from inheriting an incomplete case's
                # entire configured weight.
                sample_weights.append(
                    (float(case.weight) if case is not None else 1.0)
                    / dispatched_per_case[group_key]
                )
            return (
                evaluate_objectives(
                    samples,
                    objective_config,
                    sample_weights=sample_weights,
                ),
                rate_summary,
            )

        training_trials = [
            trial for trial in trials if not bool((trial.scenario_config_json or {}).get("holdout"))
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
        training_max_error_mean = _avg(training_max_errors)
        training_max_error_worst = round(max(training_max_errors), 4)
        agg.update(
            {
                "rmse": _avg(
                    [
                        _required_metric_number(metric.rmse, field_name="rmse")
                        for metric in training_metrics
                    ]
                ),
                "max_error": training_max_error_mean,
                "max_error_mean": training_max_error_mean,
                "max_error_worst": training_max_error_worst,
                "overshoot_count": int(
                    round(
                        sum(
                            _required_overshoot_count(metric.overshoot_count)
                            for metric in training_metrics
                        )
                        / len(training_metrics)
                    )
                ),
                "completion_time": _avg(
                    [
                        _required_metric_number(
                            metric.completion_time,
                            field_name="completion_time",
                        )
                        for metric in training_metrics
                    ]
                ),
                "score": _avg(
                    [
                        _required_metric_number(metric.score, field_name="score")
                        for metric in training_metrics
                    ]
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
            }
        )
        selection_score = evaluation.scalar_loss
        selection_score += constants.SCORE_WEIGHTS["failed_trial"] * float(
            training_rates["failure_rate"]
        )
        if not evaluation.feasible:
            selection_score += 1_000_000.0 + 1_000.0 * evaluation.total_violation
        aggregated_score = round(selection_score, 8)
        agg.update(
            {
                "aggregated_score": aggregated_score,
                "objective_values": evaluation.objectives,
                "constraint_values": evaluation.constraint_values,
                "constraint_violations": evaluation.violations,
                "feasible": evaluation.feasible,
                "total_constraint_violation": evaluation.total_violation,
                "robust_aggregation": objective_config.robust_aggregation,
                "scalar_loss": evaluation.scalar_loss,
                "training_trial_count": len(training_trials),
            }
        )
        holdout_trials = [
            trial for trial in trials if bool((trial.scenario_config_json or {}).get("holdout"))
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
                        }
                    )
            agg["holdout"] = holdout_payload
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
            c.aggregated_score if c.aggregated_score is not None else float("inf"),
            0 if not c.is_baseline else 1,
            c.generation_index,
        )
    )

    for rank, candidate in enumerate(scorable, start=1):
        candidate.rank_in_job = rank
    best = scorable[0]
    best.is_best = True
    return best


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
    baseline_agg = _aggregate_candidate(
        baseline,
        trials_by_candidate.get(baseline.id, []),
        objective_config=objective_config,
        scenario_suite=scenario_suite,
    )
    for candidate in candidates:
        if candidate.id == baseline.id:
            continue
        _aggregate_candidate(
            candidate,
            trials_by_candidate.get(candidate.id, []),
            objective_config=objective_config,
            scenario_suite=scenario_suite,
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

    report_generator.generate_and_persist_report(
        db,
        job=job,
        best=best,
        baseline_agg=baseline_agg,
        best_agg=best.aggregated_metric_json,
    )

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
    needs_verified_optimizer = (
        job.optimizer_strategy in EXPERIMENTAL_OPTIMIZER_STRATEGIES
        and not any(
            candidate.source_type == "optimizer" and candidate_is_publishable(candidate)
            for candidate in candidates
        )
    )
    if passed and not needs_verified_optimizer:
        return False
    if job.current_generation >= job.max_iterations:
        return False
    from app.orchestration.job_manager import (
        dispatch_next_cma_es_generation,
        dispatch_next_experimental_generation,
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
