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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
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
    return datetime.now(UTC)


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
    if candidate.is_baseline:
        return candidate.completed_trial_count > 0
    if candidate.trial_count <= 0:
        return False
    ratio = candidate.completed_trial_count / candidate.trial_count
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

    if job.status not in {"RUNNING", "AGGREGATING"}:
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

    baseline_agg = _aggregate_candidate(baseline, trials_by_candidate.get(baseline.id, []))
    for candidate in candidates:
        if candidate.id == baseline.id:
            continue
        _aggregate_candidate(candidate, trials_by_candidate.get(candidate.id, []))

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

    # GPT iterative loop: possibly dispatch another generation instead of
    # finalizing.
    if job.optimizer_strategy == "gpt" and _try_continue_gpt_loop(
        db, job, baseline, candidates, criteria, llm_client=llm_client
    ):
        return False

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
    if job.optimizer_strategy == "gpt":
        # GPT exhausted its iteration/trial budget without finding a passing
        # candidate — report best-so-far as a completed run.
        if job.current_generation >= job.max_iterations:
            return ("max_iterations_reached", "COMPLETED", None)
        return ("no_usable_candidate", "COMPLETED", None)
    # Heuristic: stay COMPLETED (Phase 7 contract) but flag the outcome.
    return "no_usable_candidate", "COMPLETED", None


def _try_continue_gpt_loop(
    db: Session,
    job: models.Job,
    baseline: models.CandidateParameterSet,
    candidates: list[models.CandidateParameterSet],
    criteria: AcceptanceCriteria,
    *,
    llm_client: object | None,
) -> bool:
    """If the GPT loop should run another generation, dispatch it and return True.

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

    from app.orchestration.job_manager import dispatch_next_llm_generation
    from app.orchestration.llm_parameter_proposer import OpenAIClientLike

    client_cast: OpenAIClientLike | None = None
    if llm_client is not None:
        client_cast = llm_client  # type: ignore[assignment]

    added = dispatch_next_llm_generation(db, job, client=client_cast)
    if added == 0:
        # Proposer failed — mark outcome accordingly but still let caller fall
        # through to standard finalization with whatever best-so-far exists.
        job.optimization_outcome = "llm_failed"
        db.commit()
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
    """Finalize up to ``limit`` jobs that are ready to complete."""

    stmt = (
        select(models.Job)
        .where(models.Job.status.in_(["RUNNING", "AGGREGATING"]))
        .limit(limit)
    )
    finalized: list[str] = []
    for job in list(db.scalars(stmt)):
        if finalize_job_if_ready(db, job, llm_client=_llm_client_override):
            finalized.append(job.id)
    return finalized
