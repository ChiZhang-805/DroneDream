"""Minimal Phase 3 aggregation.

Once all of a job's trials are terminal, this module moves the job into
``AGGREGATING``, rolls up the baseline candidate's trial metrics into
``aggregated_metric_json``/``aggregated_score``, produces a READY JobReport
that uses the baseline as both baseline and optimized (the real optimizer
comes in Phase 5), and sets the job to ``COMPLETED`` (or ``FAILED`` if every
trial failed).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.orchestration.events import record_event

logger = logging.getLogger("drone_dream.orchestration.aggregation")

_TERMINAL_TRIAL = {"COMPLETED", "FAILED", "CANCELLED"}


def _now() -> datetime:
    return datetime.now(UTC)


def _aggregate_candidate(
    candidate: models.CandidateParameterSet,
    trials: list[models.Trial],
) -> dict[str, Any] | None:
    """Roll up COMPLETED trial metrics into the candidate.

    Returns the aggregated metric dict (also assigned onto the candidate), or
    ``None`` if no completed trials exist.
    """

    completed_trials = [
        t for t in trials if t.status == "COMPLETED" and t.metric is not None
    ]
    candidate.trial_count = len(trials)
    candidate.completed_trial_count = len(completed_trials)
    candidate.failed_trial_count = sum(1 for t in trials if t.status == "FAILED")

    if not completed_trials:
        candidate.aggregated_metric_json = None
        candidate.aggregated_score = None
        return None

    # Narrow the optional metric for mypy — filtered above.
    metrics = [t.metric for t in completed_trials if t.metric is not None]

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4)

    rmse = _avg([m.rmse or 0.0 for m in metrics])
    max_error = _avg([m.max_error or 0.0 for m in metrics])
    overshoot = int(round(sum((m.overshoot_count or 0) for m in metrics) / len(metrics)))
    completion_time = _avg([m.completion_time or 0.0 for m in metrics])
    score = _avg([m.score or 0.0 for m in metrics])

    agg: dict[str, Any] = {
        "rmse": rmse,
        "max_error": max_error,
        "overshoot_count": overshoot,
        "completion_time": completion_time,
        "score": score,
    }
    candidate.aggregated_metric_json = agg
    candidate.aggregated_score = score
    return agg


def _build_report(
    job: models.Job,
    baseline: models.CandidateParameterSet,
    agg: dict[str, Any],
) -> dict[str, Any]:
    """Construct the JobReport JSON. Phase 3 has no optimizer, so optimized
    metrics match baseline metrics and ``comparison`` shows a flat delta."""

    comparison = [
        {
            "metric": "rmse",
            "label": "RMSE",
            "baseline": agg["rmse"],
            "optimized": agg["rmse"],
            "lower_is_better": True,
            "unit": "m",
        },
        {
            "metric": "max_error",
            "label": "Max error",
            "baseline": agg["max_error"],
            "optimized": agg["max_error"],
            "lower_is_better": True,
            "unit": "m",
        },
        {
            "metric": "overshoot_count",
            "label": "Overshoot",
            "baseline": agg["overshoot_count"],
            "optimized": agg["overshoot_count"],
            "lower_is_better": True,
            "unit": None,
        },
        {
            "metric": "completion_time",
            "label": "Completion time",
            "baseline": agg["completion_time"],
            "optimized": agg["completion_time"],
            "lower_is_better": True,
            "unit": "s",
        },
        {
            "metric": "score",
            "label": "Score",
            "baseline": agg["score"],
            "optimized": agg["score"],
            "lower_is_better": False,
            "unit": None,
        },
    ]
    return {
        "baseline": agg,
        "optimized": agg,
        "comparison": comparison,
        "best_parameters": dict(baseline.parameter_json or {}),
        "summary_text": (
            "Baseline-only run (Phase 3). Optimizer candidates will be added in "
            "Phase 5, at which point the optimized metrics here will diverge "
            "from the baseline."
        ),
    }


def _write_report(
    db: Session,
    job: models.Job,
    baseline: models.CandidateParameterSet,
    report_body: dict[str, Any],
) -> None:
    existing = db.scalars(
        select(models.JobReport).where(models.JobReport.job_id == job.id)
    ).first()
    if existing is None:
        existing = models.JobReport(job_id=job.id)
        db.add(existing)
    existing.best_candidate_id = baseline.id
    existing.summary_text = report_body["summary_text"]
    existing.baseline_metric_json = report_body["baseline"]
    existing.optimized_metric_json = report_body["optimized"]
    existing.comparison_metric_json = report_body["comparison"]
    existing.best_parameter_json = report_body["best_parameters"]
    existing.report_status = "READY"


def finalize_job_if_ready(db: Session, job: models.Job) -> bool:
    """If every trial for ``job`` is terminal, drive the job to its terminal
    state. Returns True if anything changed.
    """

    if job.status not in {"RUNNING", "AGGREGATING"}:
        return False

    trials = list(job.trials)
    if not trials:
        return False
    if not all(t.status in _TERMINAL_TRIAL for t in trials):
        return False

    changed = False

    # Transition RUNNING -> AGGREGATING first so the frontend sees the phase.
    if job.status == "RUNNING":
        job.status = "AGGREGATING"
        job.current_phase = "aggregating"
        record_event(db, job.id, "aggregation_started", None)
        db.commit()
        db.refresh(job)
        changed = True

    baseline_id = job.baseline_candidate_id
    if baseline_id is None:
        _fail_job(db, job, code="BASELINE_MISSING", message="No baseline candidate was created.")
        return True

    baseline = db.get(models.CandidateParameterSet, baseline_id)
    if baseline is None:
        _fail_job(db, job, code="BASELINE_MISSING", message="Baseline candidate row missing.")
        return True

    baseline_trials = [t for t in trials if t.candidate_id == baseline.id]
    agg = _aggregate_candidate(baseline, baseline_trials)

    total_failed = sum(1 for t in trials if t.status == "FAILED")
    # If every baseline trial failed there is nothing to aggregate; mark FAILED.
    if agg is None or total_failed == len(baseline_trials):
        _fail_job(
            db,
            job,
            code="ALL_TRIALS_FAILED",
            message="All baseline trials failed; cannot produce a report.",
        )
        return True

    baseline.is_best = True
    baseline.rank_in_job = 1
    job.best_candidate_id = baseline.id

    report_body = _build_report(job, baseline, agg)
    _write_report(db, job, baseline, report_body)

    now = _now()
    job.status = "COMPLETED"
    job.completed_at = now
    job.current_phase = "completed"
    record_event(
        db,
        job.id,
        "job_completed",
        {
            "best_candidate_id": baseline.id,
            "aggregated_score": agg["score"],
        },
    )
    db.commit()
    logger.info("job %s COMPLETED (score=%s)", job.id, agg["score"])
    del changed  # Any path reaching here mutated the job.
    return True


def _fail_job(db: Session, job: models.Job, *, code: str, message: str) -> None:
    now = _now()
    job.status = "FAILED"
    job.failed_at = now
    job.current_phase = None
    job.latest_error_code = code
    job.latest_error_message = message
    record_event(db, job.id, "job_failed", {"code": code, "message": message})
    db.commit()
    logger.warning("job %s FAILED code=%s", job.id, code)


def finalize_ready_jobs(db: Session, *, limit: int = 20) -> list[str]:
    """Finalize up to ``limit`` jobs that are ready to complete."""

    stmt = (
        select(models.Job)
        .where(models.Job.status.in_(["RUNNING", "AGGREGATING"]))
        .limit(limit)
    )
    finalized: list[str] = []
    for job in list(db.scalars(stmt)):
        if finalize_job_if_ready(db, job):
            finalized.append(job.id)
    return finalized
