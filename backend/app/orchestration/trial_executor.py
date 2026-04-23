"""Trial-level execution.

The worker polls for the oldest ``PENDING`` trial, claims it by moving it to
``RUNNING``, hands control to a :class:`~app.simulator.SimulatorAdapter`,
persists the returned metrics + artifact metadata, and sets the trial
terminal. Progress counters on the parent job are updated atomically with
trial completion.

The executor itself contains **no** simulator logic — swapping backends is
purely a matter of setting ``SIMULATOR_BACKEND`` (see
:mod:`app.simulator.factory`). Job-level decisions (cancel the whole job,
retry policy, etc.) remain the job manager's responsibility; the executor
only reports trial outcomes.

Concurrency note: Phase 3 targets a **single** local worker process, so the
claim-by-update-then-commit pattern is safe. If we ever run multiple workers
against the same SQLite DB we would need ``SELECT ... FOR UPDATE SKIP LOCKED``
semantics (Postgres) or app-level leasing, neither of which is worth the
complexity in the MVP. A TODO marker is left at the claim site.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.orchestration.events import record_event
from app.simulator import (
    ArtifactMetadata,
    JobConfig,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialResult,
    get_simulator_adapter,
)
from app.simulator.base import FAILURE_SIM_ERROR


def _env_simulator_backend() -> str | None:
    """Read ``SIMULATOR_BACKEND`` from the environment, treating blank as unset."""

    raw = os.environ.get("SIMULATOR_BACKEND", "").strip()
    return raw or None


def _resolve_backend_override(
    *,
    env_backend: str | None,
    job_backend_requested: str | None,
) -> str | None:
    """Resolve which simulator backend to use for a trial.

    Precedence (highest first):

    1. ``SIMULATOR_BACKEND`` env var — back-compat with Phase 7 deployments
       and a global override for debugging. Blank/empty is treated as unset
       (see :func:`_env_simulator_backend`) so leaving it unset in ``.env``
       lets per-job UI selection take effect.
    2. The job's ``simulator_backend_requested`` column — Phase 8 per-job
       UI selection.
    3. ``None`` — the :func:`~app.simulator.factory.get_simulator_adapter`
       default (``mock``).
    """

    if env_backend:
        return env_backend
    if job_backend_requested:
        return job_backend_requested
    return None


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


def _job_config_from(job: models.Job) -> JobConfig:
    return JobConfig(
        track_type=job.track_type,
        start_point_x=job.start_point_x,
        start_point_y=job.start_point_y,
        altitude_m=job.altitude_m,
        wind_north=job.wind_north,
        wind_east=job.wind_east,
        wind_south=job.wind_south,
        wind_west=job.wind_west,
        sensor_noise_level=job.sensor_noise_level,
        objective_profile=job.objective_profile,
    )


def _build_trial_context(
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> TrialContext:
    return TrialContext(
        trial_id=trial.id,
        job_id=trial.job_id,
        job_config=_job_config_from(job),
        candidate_id=trial.candidate_id,
        parameters=dict(candidate.parameter_json or {}),
        seed=trial.seed,
        scenario_type=trial.scenario_type,
        scenario_config=(
            dict(trial.scenario_config_json) if trial.scenario_config_json else None
        ),
    )


def _persist_artifacts(
    db: Session, trial: models.Trial, artifacts: list[ArtifactMetadata]
) -> None:
    for meta in artifacts:
        db.add(
            models.Artifact(
                owner_type="trial",
                owner_id=trial.id,
                artifact_type=meta.artifact_type,
                display_name=meta.display_name,
                storage_path=meta.storage_path,
                mime_type=meta.mime_type,
                file_size_bytes=meta.file_size_bytes,
            )
        )


def claim_and_run_one_pending_trial(
    db: Session,
    worker_id: str,
    *,
    adapter: SimulatorAdapter | None = None,
) -> str | None:
    """Pick one PENDING trial and run it to terminal state.

    Returns the trial id that was executed, or ``None`` if no PENDING trial
    was available. All DB mutations for this trial are flushed/committed by
    this function; the caller should NOT be holding an open transaction.

    ``adapter`` is optional and primarily exists for tests. In production
    the worker passes ``None`` and the factory selects the adapter from the
    ``SIMULATOR_BACKEND`` environment variable.
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

    backend_override: str | None = None
    if adapter is None:
        job_row = db.get(models.Job, trial.job_id)
        backend_override = _resolve_backend_override(
            env_backend=_env_simulator_backend(),
            job_backend_requested=(
                str(job_row.simulator_backend_requested)
                if job_row is not None and job_row.simulator_backend_requested
                else None
            ),
        )
    sim = adapter or get_simulator_adapter(backend_override)

    # --- Claim ----------------------------------------------------------
    now = _now()
    trial.status = "RUNNING"
    trial.worker_id = worker_id
    trial.attempt_count = (trial.attempt_count or 0) + 1
    trial.started_at = now
    trial.simulator_backend = sim.backend_name
    db.commit()
    db.refresh(trial)

    logger.info(
        "claimed trial %s (job=%s candidate=%s scenario=%s seed=%d backend=%s)",
        trial.id,
        trial.job_id,
        trial.candidate_id,
        trial.scenario_type,
        trial.seed,
        sim.backend_name,
    )

    candidate = db.get(models.CandidateParameterSet, trial.candidate_id)
    if candidate is None:
        _mark_trial_failed(
            db, trial, code="CANDIDATE_NOT_FOUND", reason="Candidate row disappeared."
        )
        return trial.id
    job = db.get(models.Job, trial.job_id)
    if job is None:  # pragma: no cover — defensive only
        _mark_trial_failed(db, trial, code="JOB_NOT_FOUND", reason="Job row disappeared.")
        return trial.id

    ctx = _build_trial_context(trial, job, candidate)

    # --- Execute --------------------------------------------------------
    result: TrialResult
    try:
        sim.prepare(ctx)
        result = sim.run_trial(ctx)
    except Exception as exc:  # Infrastructure-level crash inside the adapter.
        logger.exception("simulator adapter crashed for trial %s", trial.id)
        _mark_trial_failed(db, trial, code=FAILURE_SIM_ERROR, reason=str(exc)[:500])
        return trial.id
    finally:
        try:
            sim.cleanup(ctx)
        except Exception:  # pragma: no cover — cleanup is best-effort.
            logger.exception("simulator adapter cleanup failed for trial %s", trial.id)

    if not result.success or result.metrics is None:
        failure: TrialFailure = result.failure or TrialFailure(
            code=FAILURE_SIM_ERROR, reason="Adapter returned no metrics and no failure."
        )
        _mark_trial_failed(
            db,
            trial,
            code=failure.code,
            reason=failure.reason,
            log_excerpt=result.log_excerpt,
        )
        # Artifacts can still be useful for post-mortem even on failure.
        _persist_artifacts(db, trial, result.artifacts)
        db.commit()
        return trial.id

    # --- Persist metrics + mark COMPLETED ------------------------------
    payload = result.metrics
    metric = models.TrialMetric(
        trial_id=trial.id,
        rmse=payload.rmse,
        max_error=payload.max_error,
        overshoot_count=payload.overshoot_count,
        completion_time=payload.completion_time,
        crash_flag=payload.crash_flag,
        timeout_flag=payload.timeout_flag,
        score=payload.score,
        final_error=payload.final_error,
        pass_flag=payload.pass_flag,
        instability_flag=payload.instability_flag,
        raw_metric_json=payload.raw_metric_json,
    )
    db.add(metric)
    _persist_artifacts(db, trial, result.artifacts)

    trial.status = "COMPLETED"
    trial.finished_at = _now()
    trial.log_excerpt = result.log_excerpt or (
        f"[{sim.backend_name}] scenario={trial.scenario_type} seed={trial.seed} "
        f"rmse={payload.rmse} score={payload.score}"
    )

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
            "score": payload.score,
            "backend": sim.backend_name,
        },
    )

    db.commit()
    logger.info("completed trial %s score=%s", trial.id, payload.score)
    return trial.id


def _mark_trial_failed(
    db: Session,
    trial: models.Trial,
    *,
    code: str,
    reason: str,
    log_excerpt: str | None = None,
) -> None:
    trial.status = "FAILED"
    trial.finished_at = _now()
    trial.failure_code = code
    trial.failure_reason = reason
    if log_excerpt is not None:
        trial.log_excerpt = log_excerpt

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
