"""Trial-level execution.

The worker polls for the oldest ``PENDING`` trial, claims it by moving it to
``RUNNING``, runs a deterministic mock simulation, writes a ``TrialMetric``
row, and sets the trial terminal. Progress counters on the parent job are
updated atomically with trial completion.

Concurrency note: Phase 3 targets a **single** local worker process, so the
claim-by-update-then-commit pattern is safe. If we ever run multiple workers
against the same SQLite DB we would need ``SELECT ... FOR UPDATE SKIP LOCKED``
semantics (Postgres) or app-level leasing, neither of which is worth the
complexity in the MVP. A TODO marker is left at the claim site.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.orchestration.events import record_event
from app.orchestration.metrics import compute_mock_metrics

logger = logging.getLogger("drone_dream.orchestration.trial")


def _now() -> datetime:
    return datetime.now(UTC)


def _refresh_progress_counters(db: Session, job: models.Job) -> None:
    """Recompute ``progress_completed_trials`` from terminal trial rows.

    Uses the actual trial rows as the source of truth (per the Phase 3 spec
    that job progress must be driven by real trial state, not a fake counter).
    """

    terminal = {"COMPLETED", "FAILED", "CANCELLED"}
    completed = sum(1 for t in job.trials if t.status in terminal)
    job.progress_completed_trials = completed


def claim_and_run_one_pending_trial(db: Session, worker_id: str) -> str | None:
    """Pick one PENDING trial and run it to terminal state.

    Returns the trial id that was executed, or ``None`` if no PENDING trial
    was available. All DB mutations for this trial are flushed/committed by
    this function; the caller should NOT be holding an open transaction.
    """

    stmt = (
        select(models.Trial)
        .where(models.Trial.status == "PENDING")
        .order_by(models.Trial.queued_at.asc().nullsfirst(), models.Trial.created_at.asc())
        .limit(1)
    )
    # TODO(phase5+): for multi-worker safety, claim with an UPDATE ... WHERE
    # status='PENDING' ... RETURNING (Postgres) or a leased_until column.
    trial = db.scalars(stmt).first()
    if trial is None:
        return None

    # --- Claim ----------------------------------------------------------
    now = _now()
    trial.status = "RUNNING"
    trial.worker_id = worker_id
    trial.attempt_count = (trial.attempt_count or 0) + 1
    trial.started_at = now
    trial.simulator_backend = "mock"
    db.commit()
    db.refresh(trial)

    logger.info(
        "claimed trial %s (job=%s candidate=%s scenario=%s seed=%d)",
        trial.id,
        trial.job_id,
        trial.candidate_id,
        trial.scenario_type,
        trial.seed,
    )

    # --- Execute --------------------------------------------------------
    candidate = db.get(models.CandidateParameterSet, trial.candidate_id)
    if candidate is None:
        _mark_trial_failed(
            db, trial, code="CANDIDATE_NOT_FOUND", reason="Candidate row disappeared."
        )
        return trial.id

    try:
        payload = compute_mock_metrics(
            parameters=candidate.parameter_json or {},
            scenario=trial.scenario_type,
            seed=trial.seed,
        )
    except Exception as exc:  # pragma: no cover — defensive only
        logger.exception("mock simulator crashed for trial %s", trial.id)
        _mark_trial_failed(db, trial, code="SIM_ERROR", reason=str(exc)[:500])
        return trial.id

    # --- Persist metrics + mark COMPLETED ------------------------------
    metric = models.TrialMetric(
        trial_id=trial.id,
        rmse=payload["rmse"],
        max_error=payload["max_error"],
        overshoot_count=payload["overshoot_count"],
        completion_time=payload["completion_time"],
        crash_flag=payload["crash_flag"],
        timeout_flag=payload["timeout_flag"],
        score=payload["score"],
        final_error=payload["final_error"],
        pass_flag=payload["pass_flag"],
        instability_flag=payload["instability_flag"],
        raw_metric_json=payload,
    )
    db.add(metric)

    trial.status = "COMPLETED"
    trial.finished_at = _now()
    trial.log_excerpt = (
        f"[mock] scenario={trial.scenario_type} seed={trial.seed} "
        f"rmse={payload['rmse']} score={payload['score']}"
    )

    job = db.get(models.Job, trial.job_id)
    if job is not None:
        _refresh_progress_counters(db, job)
        record_event(
            db,
            job.id,
            "trial_completed",
            {
                "trial_id": trial.id,
                "candidate_id": trial.candidate_id,
                "scenario": trial.scenario_type,
                "status": "COMPLETED",
                "score": payload["score"],
            },
        )

    db.commit()
    logger.info("completed trial %s score=%s", trial.id, payload["score"])
    return trial.id


def _mark_trial_failed(
    db: Session,
    trial: models.Trial,
    *,
    code: str,
    reason: str,
) -> None:
    trial.status = "FAILED"
    trial.finished_at = _now()
    trial.failure_code = code
    trial.failure_reason = reason

    job = db.get(models.Job, trial.job_id)
    if job is not None:
        _refresh_progress_counters(db, job)
        record_event(
            db,
            job.id,
            "trial_completed",
            {
                "trial_id": trial.id,
                "candidate_id": trial.candidate_id,
                "scenario": trial.scenario_type,
                "status": "FAILED",
                "failure_code": code,
            },
        )

    db.commit()
    logger.warning("trial %s failed code=%s reason=%s", trial.id, code, reason)
