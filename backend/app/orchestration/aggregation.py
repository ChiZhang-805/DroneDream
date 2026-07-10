"""Job aggregation + best-candidate selection (Phase 5).

Once every trial for a job is terminal, this module:

1. Moves the job to ``AGGREGATING``.
2. For each ``CandidateParameterSet`` (baseline and every optimizer
   candidate), rolls up the candidate's completed trials into
   ``aggregated_metric_json`` / ``aggregated_score``, and persists trial
   counts. See :func:`_aggregate_candidate`.
3. Selects the best candidate by lowest ``aggregated_score`` among
   "eligible" candidates (candidates with enough completed trials — see
   :data:`constants.MIN_COMPLETED_TRIAL_RATIO`). Baseline is always eligible
   if it has any completed trials so we can always produce a report.
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
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.optimization.robust import CandidateEvaluation
from app.optimization.robust import evaluate_candidate as evaluate_objectives
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Scoring ---------------------------------------------------------------


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

    mean_rmse = sum(m.rmse or 0.0 for m in metrics) / n
    mean_max_error = sum(m.max_error or 0.0 for m in metrics) / n
    mean_completion = sum(m.completion_time or 0.0 for m in metrics) / n
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

    completed_trials = [t for t in trials if t.status == "COMPLETED" and t.metric is not None]
    metrics = [t.metric for t in completed_trials if t.metric is not None]

    candidate.trial_count = len(trials)
    candidate.completed_trial_count = len(completed_trials)
    candidate.failed_trial_count = sum(1 for t in trials if t.status == "FAILED")
    passing_trial_count = sum(1 for m in metrics if m.pass_flag)

    if not metrics:
        candidate.aggregated_metric_json = None
        candidate.aggregated_score = None
        return None

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4)

    rmse = _avg([m.rmse or 0.0 for m in metrics])
    max_error = _avg([m.max_error or 0.0 for m in metrics])
    overshoot = int(round(sum(m.overshoot_count or 0 for m in metrics) / len(metrics)))
    completion_time = _avg([m.completion_time or 0.0 for m in metrics])
    trial_score_mean = _avg([m.score or 0.0 for m in metrics])

    aggregated_score = _score_candidate(
        metrics, trial_count=len(trials), failed=candidate.failed_trial_count
    )

    agg: dict[str, Any] = {
        "rmse": rmse,
        "max_error": max_error,
        "overshoot_count": overshoot,
        "completion_time": completion_time,
        "score": trial_score_mean,
        "aggregated_score": aggregated_score,
        "trial_count": len(trials),
        "completed_trial_count": len(completed_trials),
        "failed_trial_count": candidate.failed_trial_count,
        # Phase 8 polish: the "pass rate" that drives the acceptance check is
        # the fraction of dispatched trials whose per-trial pass_flag is true,
        # NOT the execution-completion ratio. Persisting it here keeps
        # acceptance.evaluate_candidate and the UI in sync.
        "passing_trial_count": passing_trial_count,
    }
    if objective_config is not None:
        cases_by_id = {
            case.id: case
            for case in (scenario_suite.cases if scenario_suite is not None else [])
            if case.enabled
        }
        cases_by_type: dict[str, schemas.ScenarioCaseConfig] = {}
        for case in cases_by_id.values():
            cases_by_type.setdefault(case.scenario_type, case)

        def _evaluate_rows(
            rows: list[models.Trial],
        ) -> tuple[CandidateEvaluation, float] | None:
            completed_rows = [
                trial
                for trial in rows
                if trial.status == "COMPLETED" and trial.metric is not None
            ]
            if not completed_rows:
                return None
            failed_rate = sum(1 for trial in rows if trial.status == "FAILED") / max(
                1, len(rows)
            )
            pass_rate = sum(
                1 for trial in completed_rows if trial.metric and trial.metric.pass_flag
            ) / max(1, len(rows))
            samples: list[dict[str, float]] = []
            sample_weights: list[float] = []
            for trial in completed_rows:
                metric = trial.metric
                assert metric is not None
                sample: dict[str, float] = {
                    "rmse": float(metric.rmse or 0.0),
                    "max_error": float(metric.max_error or 0.0),
                    "overshoot_count": float(metric.overshoot_count or 0),
                    "completion_time": float(metric.completion_time or 0.0),
                    "crash_flag": float(metric.crash_flag),
                    "timeout_flag": float(metric.timeout_flag),
                    "score": float(metric.score or 0.0),
                    "final_error": float(metric.final_error or 0.0),
                    "pass_flag": float(metric.pass_flag),
                    "instability_flag": float(metric.instability_flag),
                    "failed_trial_rate": failed_rate,
                    "pass_rate": pass_rate,
                }
                for key, raw_value in (metric.raw_metric_json or {}).items():
                    if isinstance(raw_value, (bool, int, float)):
                        sample[key] = float(raw_value)
                samples.append(sample)
                scenario_config = trial.scenario_config_json or {}
                case_id = scenario_config.get("scenario_case_id")
                case = cases_by_id.get(str(case_id)) if case_id is not None else None
                if case is None:
                    case = cases_by_type.get(trial.scenario_type)
                sample_weights.append(case.weight if case is not None else 1.0)
            return (
                evaluate_objectives(
                    samples,
                    objective_config,
                    sample_weights=sample_weights,
                ),
                failed_rate,
            )

        training_trials = [
            trial
            for trial in trials
            if not bool((trial.scenario_config_json or {}).get("holdout"))
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
        evaluation, failed_rate = training_result
        training_completed = [
            trial
            for trial in training_trials
            if trial.status == "COMPLETED" and trial.metric is not None
        ]
        training_metrics = [
            trial.metric for trial in training_completed if trial.metric is not None
        ]
        training_passing = sum(1 for metric in training_metrics if metric.pass_flag)
        training_failed = sum(1 for trial in training_trials if trial.status == "FAILED")
        agg.update(
            {
                "rmse": _avg([metric.rmse or 0.0 for metric in training_metrics]),
                "max_error": _avg(
                    [metric.max_error or 0.0 for metric in training_metrics]
                ),
                "overshoot_count": int(
                    round(
                        sum(metric.overshoot_count or 0 for metric in training_metrics)
                        / len(training_metrics)
                    )
                ),
                "completion_time": _avg(
                    [metric.completion_time or 0.0 for metric in training_metrics]
                ),
                "score": _avg([metric.score or 0.0 for metric in training_metrics]),
                "passing_trial_count": training_passing,
                "training_completed_trial_count": len(training_completed),
                "training_failed_trial_count": training_failed,
                "training_passing_trial_count": training_passing,
            }
        )
        selection_score = evaluation.scalar_loss
        selection_score += constants.SCORE_WEIGHTS["failed_trial"] * failed_rate
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
            trial
            for trial in trials
            if bool((trial.scenario_config_json or {}).get("holdout"))
        ]
        if holdout_trials:
            try:
                holdout_result = _evaluate_rows(holdout_trials)
            except ValueError as exc:
                agg["holdout"] = {
                    "trial_count": len(holdout_trials),
                    "evaluation_error": str(exc),
                }
            else:
                if holdout_result is None:
                    agg["holdout"] = {
                        "trial_count": len(holdout_trials),
                        "evaluation_error": "no completed holdout metrics",
                    }
                else:
                    holdout_evaluation, _holdout_failed_rate = holdout_result
                    agg["holdout"] = {
                        "trial_count": len(holdout_trials),
                        "objective_values": holdout_evaluation.objectives,
                        "constraint_values": holdout_evaluation.constraint_values,
                        "constraint_violations": holdout_evaluation.violations,
                        "feasible": holdout_evaluation.feasible,
                        "total_constraint_violation": holdout_evaluation.total_violation,
                    }
    candidate.aggregated_metric_json = agg
    candidate.aggregated_score = aggregated_score
    return agg


# --- Best selection --------------------------------------------------------


def _is_eligible(candidate: models.CandidateParameterSet) -> bool:
    """A candidate is eligible to win only if it has enough completed trials.

    Baseline is always eligible when it has at least one completed trial so
    we can produce *some* report; optimizer candidates need at least
    :data:`constants.MIN_COMPLETED_TRIAL_RATIO` of their dispatched trials
    completed.
    """

    if candidate.aggregated_score is None:
        return False
    aggregate = candidate.aggregated_metric_json or {}
    trial_count = int(aggregate.get("training_trial_count", candidate.trial_count) or 0)
    completed_trial_count = int(
        aggregate.get(
            "training_completed_trial_count", candidate.completed_trial_count
        )
        or 0
    )
    if candidate.is_baseline:
        return completed_trial_count > 0
    if trial_count <= 0:
        return False
    ratio = completed_trial_count / trial_count
    return ratio >= constants.MIN_COMPLETED_TRIAL_RATIO


def _rank_and_select_best(
    candidates: list[models.CandidateParameterSet],
) -> models.CandidateParameterSet | None:
    """Assign ``rank_in_job`` to every scorable candidate, mark best, return it.

    Sorting key: aggregated_score ascending, with baseline tie-broken last so
    a tied optimizer candidate wins (the report is more useful when the
    optimized column differs from the baseline column).
    """

    scorable = [c for c in candidates if c.aggregated_score is not None]
    if not scorable:
        return None

    scorable.sort(
        key=lambda c: (
            c.aggregated_score if c.aggregated_score is not None else float("inf"),
            0 if not c.is_baseline else 1,
            c.generation_index,
        )
    )

    best: models.CandidateParameterSet | None = None
    for rank, candidate in enumerate(scorable, start=1):
        candidate.rank_in_job = rank
        candidate.is_best = False
    # Pick the first eligible candidate in score order. If none are eligible,
    # we fall back to the baseline if it scored at all.
    for candidate in scorable:
        if _is_eligible(candidate):
            best = candidate
            break
    if best is None:
        for candidate in scorable:
            if candidate.is_baseline:
                best = candidate
                break
    if best is not None:
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
    if job.optimizer_strategy in {"gpt", "cma_es"}:
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

    outcome, terminal_status, terminal_error = _determine_terminal_state(
        job, best, criteria
    )
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
    if not any_criterion_set(criteria) and criteria.min_pass_rate <= (
        result.pass_rate + 1e-9
    ):
        return "success", "COMPLETED", None
    if job.optimizer_strategy in {"gpt", "cma_es"}:
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

    if not any_criterion_set(criteria):
        return False

    scored = [c for c in candidates if c.aggregated_score is not None]
    passed = any(evaluate_candidate(c, criteria).passed for c in scored)
    if passed:
        return False
    if job.current_generation >= job.max_iterations:
        return False
    next_generation_trials = max(1, job.trials_per_candidate)
    if job.progress_total_trials + next_generation_trials > job.max_total_trials:
        return False

    from app.orchestration.job_manager import (
        dispatch_next_cma_es_generation,
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
        if cma_dispatch.status in {"budget_exhausted", "max_iterations_reached"}:
            return False
    else:
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

    if baseline_agg is not None:
        # Treat baseline as best-so-far.
        job.best_candidate_id = baseline.id
        baseline.is_best = True
        report_generator.generate_and_persist_report(
            db,
            job=job,
            best=baseline,
            baseline_agg=baseline_agg,
            best_agg=baseline_agg,
        )
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
    """Atomically claim and finalize up to ``limit`` ready jobs.

    ``FINALIZING`` is a transaction-scoped claim: it is committed only with
    the terminal result (or with a newly dispatched iterative generation).
    A worker crash before that point rolls the status change back, so another
    worker can safely retry without a separate job-lease column.
    """

    stmt = (
        select(models.Job)
        .where(models.Job.status.in_(["RUNNING", "AGGREGATING"]))
        .limit(limit)
    )
    finalized: list[str] = []
    for job in list(db.scalars(stmt)):
        trials = list(job.trials)
        if not trials or not all(t.status in _TERMINAL_TRIAL for t in trials):
            continue
        claimed = db.execute(
            update(models.Job)
            .where(
                models.Job.id == job.id,
                models.Job.status.in_(["RUNNING", "AGGREGATING"]),
            )
            .values(status="FINALIZING", current_phase="aggregating")
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            continue
        db.expire(job)
        db.refresh(job)
        record_event(db, job.id, "aggregation_started", None)
        if finalize_job_if_ready(db, job, llm_client=_llm_client_override):
            finalized.append(job.id)
    return finalized
