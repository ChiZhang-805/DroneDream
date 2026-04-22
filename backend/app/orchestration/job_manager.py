"""Job-level orchestration: claim QUEUED jobs, create baseline, dispatch trials.

The job manager only mutates Job/CandidateParameterSet/Trial rows. It never
executes a trial directly — trial-level work is done by the trial executor
from a separate transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.orchestration import constants
from app.orchestration.events import record_event


def _now() -> datetime:
    return datetime.now(UTC)


def _create_baseline_candidate(db: Session, job: models.Job) -> models.CandidateParameterSet:
    """Persist the baseline CandidateParameterSet for a job.

    The controller parameters come from ``constants.BASELINE_PARAMETERS`` so the
    optimizer can vary the exact same keys in Phase 5 without schema churn.
    """

    candidate = models.CandidateParameterSet(
        job_id=job.id,
        generation_index=0,
        source_type="baseline",
        label="baseline",
        parameter_json=dict(constants.BASELINE_PARAMETERS),
        is_baseline=True,
        trial_count=len(constants.BASELINE_SCENARIOS),
    )
    db.add(candidate)
    db.flush()
    job.baseline_candidate_id = candidate.id
    record_event(
        db,
        job.id,
        "baseline_started",
        {"candidate_id": candidate.id, "scenario_count": len(constants.BASELINE_SCENARIOS)},
    )
    return candidate


def _dispatch_baseline_trials(
    db: Session,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> list[models.Trial]:
    """Create PENDING Trial rows for every baseline scenario."""

    trials: list[models.Trial] = []
    now = _now()
    for scenario in constants.BASELINE_SCENARIOS:
        seed = constants.SCENARIO_SEEDS[scenario]
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=seed,
            scenario_type=scenario,
            scenario_config_json=constants.baseline_scenario_config(scenario),
            status="PENDING",
            queued_at=now,
        )
        db.add(trial)
        db.flush()
        trials.append(trial)
        record_event(
            db,
            job.id,
            "trial_dispatched",
            {"trial_id": trial.id, "candidate_id": candidate.id, "scenario": scenario},
        )
    return trials


def start_job(db: Session, job: models.Job) -> models.Job:
    """Move a single QUEUED job to RUNNING and dispatch its baseline work.

    Expects the caller to hold a transaction; commits are managed by the
    session-using caller (usually ``start_queued_jobs``).
    """

    if job.status != "QUEUED":
        return job

    now = _now()
    job.status = "RUNNING"
    job.started_at = now
    job.current_phase = "baseline"
    job.progress_completed_trials = 0
    job.progress_total_trials = len(constants.BASELINE_SCENARIOS)
    record_event(db, job.id, "job_started", None)

    candidate = _create_baseline_candidate(db, job)
    _dispatch_baseline_trials(db, job, candidate)
    return job


def start_queued_jobs(db: Session, *, limit: int = 10) -> list[str]:
    """Process up to ``limit`` QUEUED jobs, moving each to RUNNING.

    Returns the list of job ids that were started. Each job is advanced in its
    own commit so a failure on one job does not roll back others.
    """

    stmt = (
        select(models.Job)
        .where(models.Job.status == "QUEUED")
        .order_by(models.Job.queued_at.asc().nullsfirst(), models.Job.created_at.asc())
        .limit(limit)
    )
    started: list[str] = []
    for job in list(db.scalars(stmt)):
        start_job(db, job)
        db.commit()
        started.append(job.id)
    return started
