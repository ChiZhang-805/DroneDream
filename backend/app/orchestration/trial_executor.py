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

Concurrency note: claims use conditional updates, renewable leases, and an
``attempt_count`` fencing token. A stale worker may finish its external
simulation after another worker reclaims the row, but it cannot persist that
obsolete attempt's metrics or artifacts.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import case, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
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
from app.storage import get_artifact_storage


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
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class _TrialLeaseToken:
    """Fencing token for exactly one execution attempt."""

    trial_id: str
    worker_id: str
    attempt_count: int


def _renew_owned_lease(
    db: Session,
    token: _TrialLeaseToken,
    *,
    lease_seconds: int,
) -> bool:
    """Renew a lease only while this exact attempt still owns the trial."""

    result = cast(
        CursorResult[Any],
        db.execute(
            update(models.Trial)
            .where(
                models.Trial.id == token.trial_id,
                models.Trial.status == "RUNNING",
                models.Trial.lease_owner == token.worker_id,
                models.Trial.attempt_count == token.attempt_count,
            )
            .values(lease_expires_at=_now() + timedelta(seconds=lease_seconds))
            .execution_options(synchronize_session=False)
        ),
    )
    return result.rowcount == 1


class _TrialLeaseHeartbeat:
    """Renew a trial lease from an independent DB session during simulation."""

    def __init__(
        self,
        token: _TrialLeaseToken,
        *,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._token = token
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self.lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"trial-lease-{token.trial_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))

    def _run(self) -> None:
        from app.db import SessionLocal

        while not self._stop.wait(self._interval_seconds):
            try:
                with SessionLocal() as heartbeat_db:
                    if not _renew_owned_lease(
                        heartbeat_db,
                        self._token,
                        lease_seconds=self._lease_seconds,
                    ):
                        heartbeat_db.rollback()
                        self.lost.set()
                        return
                    heartbeat_db.commit()
            except Exception:
                # A transient database outage should not kill a simulator
                # process. The completion fence below remains authoritative.
                logger.warning(
                    "failed to renew lease for trial %s",
                    self._token.trial_id,
                    exc_info=True,
                )


def _acquire_completion_fence(
    db: Session,
    token: _TrialLeaseToken,
    *,
    lease_seconds: int,
) -> bool:
    """Fence result persistence against a newer reclaimed attempt."""

    if not _renew_owned_lease(db, token, lease_seconds=lease_seconds):
        db.rollback()
        logger.warning(
            "discarding stale result for trial %s attempt=%d worker=%s",
            token.trial_id,
            token.attempt_count,
            token.worker_id,
        )
        return False
    db.expire_all()
    return True


def _refresh_progress_counters(db: Session, job: models.Job) -> None:
    """Recompute ``progress_completed_trials`` from terminal trial rows.

    Uses the actual trial rows as the source of truth (per the Phase 3 spec
    that job progress must be driven by real trial state, not a fake counter).
    """

    terminal = {"COMPLETED", "FAILED", "CANCELLED"}
    completed = sum(1 for t in job.trials if t.status in terminal)
    job.progress_completed_trials = completed


def _job_config_from(job: models.Job) -> JobConfig:
    reference_track: list[dict[str, float]] | None = None
    if job.reference_track_json:
        normalized: list[dict[str, float]] = []
        for point in job.reference_track_json:
            if not isinstance(point, dict):
                continue
            x = point.get("x")
            y = point.get("y")
            z_raw = point.get("z")
            if x is None or y is None:
                continue
            try:
                normalized.append(
                    {
                        "x": float(x),
                        "y": float(y),
                        "z": float(job.altitude_m if z_raw is None else z_raw),
                    }
                )
            except (TypeError, ValueError):
                continue
        reference_track = normalized or None
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
        reference_track=reference_track,
        vehicle_profile=dict(job.vehicle_profile_json or {}),
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
    storage = get_artifact_storage()
    for meta in artifacts:
        storage_path = meta.storage_path
        local_path = Path(storage_path)
        if local_path.exists() and local_path.is_file():
            safe_name = Path(meta.display_name or local_path.name).name
            key = f"jobs/{trial.job_id}/trials/{trial.id}/{meta.artifact_type}/{safe_name}"
            storage_path = storage.put_file(
                local_path,
                key,
                content_type=meta.mime_type,
            )
        db.add(
            models.Artifact(
                owner_type="trial",
                owner_id=trial.id,
                artifact_type=meta.artifact_type,
                display_name=meta.display_name,
                storage_path=storage_path,
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

    now = _now()
    lease_seconds = get_settings().worker_lease_seconds
    lease_until = now + timedelta(seconds=lease_seconds)
    reclaim_enabled = get_settings().worker_stale_running_reclaim_enabled
    claimable = (
        (models.Trial.status == "PENDING")
        & (
            models.Trial.lease_expires_at.is_(None)
            | (models.Trial.lease_expires_at <= now)
        )
    )
    stale_running = (
        (models.Trial.status == "RUNNING")
        & (models.Trial.lease_expires_at.is_not(None))
        & (models.Trial.lease_expires_at <= now)
    )
    claim_pool = or_(claimable, stale_running) if reclaim_enabled else claimable
    selected_trial = db.execute(
        select(models.Trial.id, models.Trial.job_id, models.Trial.status)
        .where(claim_pool)
        .order_by(models.Trial.queued_at.asc().nullsfirst(), models.Trial.created_at.asc())
        .limit(1)
    ).one_or_none()
    if selected_trial is None:
        return None
    trial_id = str(selected_trial.id)
    job_id = str(selected_trial.job_id)
    was_pending = selected_trial.status == "PENDING"

    backend_override: str | None = None
    env_backend = _env_simulator_backend() if adapter is None else None

    # --- Claim ----------------------------------------------------------
    update_stmt = (
        update(models.Trial)
        .where(models.Trial.id == trial_id)
        .where(claim_pool)
        .values(
            status="RUNNING",
            worker_id=worker_id,
            lease_owner=worker_id,
            lease_expires_at=lease_until,
            claimed_at=now,
            finished_at=None,
            failure_code=None,
            failure_reason=None,
            log_excerpt=None,
        )
        .values(attempt_count=(models.Trial.attempt_count + 1))
        .values(
            started_at=case(
                (models.Trial.started_at.is_(None), now),
                else_=models.Trial.started_at,
            )
        )
    )
    claim_result = db.execute(update_stmt)
    if claim_result.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        return None

    trial = db.get(models.Trial, trial_id)
    if trial is None:
        db.rollback()
        return None
    if adapter is None:
        job_row = db.get(models.Job, job_id)
        backend_override = _resolve_backend_override(
            env_backend=env_backend,
            job_backend_requested=(
                str(job_row.simulator_backend_requested)
                if job_row is not None and job_row.simulator_backend_requested
                else None
            ),
        )
    sim = adapter or get_simulator_adapter(backend_override)
    trial.simulator_backend = sim.backend_name
    db.commit()
    db.refresh(trial)
    record_event(
        db,
        trial.job_id,
        "trial_reclaimed_from_stale_worker" if not was_pending else "trial_claimed",
        {"trial_id": trial.id, "worker_id": worker_id},
    )
    db.commit()
    db.refresh(trial)
    lease_token = _TrialLeaseToken(
        trial_id=trial.id,
        worker_id=worker_id,
        attempt_count=trial.attempt_count,
    )

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
        if not _acquire_completion_fence(db, lease_token, lease_seconds=lease_seconds):
            return trial_id
        trial = db.get(models.Trial, trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return trial_id
        _mark_trial_failed(
            db, trial, code="CANDIDATE_NOT_FOUND", reason="Candidate row disappeared."
        )
        return trial_id
    job = db.get(models.Job, trial.job_id)
    if job is None:
        if not _acquire_completion_fence(db, lease_token, lease_seconds=lease_seconds):
            return trial_id
        trial = db.get(models.Trial, trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return trial_id
        _mark_trial_failed(db, trial, code="JOB_NOT_FOUND", reason="Job row disappeared.")
        return trial_id

    ctx = _build_trial_context(trial, job, candidate)
    # Do not hold the main session's read transaction open while PX4/Gazebo
    # runs. Lease heartbeats use independent short-lived sessions.
    db.commit()

    # --- Execute --------------------------------------------------------
    settings = get_settings()
    heartbeat_interval = min(
        settings.worker_lease_heartbeat_seconds,
        max(0.1, lease_seconds / 3),
    )
    heartbeat = _TrialLeaseHeartbeat(
        lease_token,
        lease_seconds=lease_seconds,
        interval_seconds=heartbeat_interval,
    )
    heartbeat.start()
    result: TrialResult | None = None
    execution_error: Exception | None = None
    try:
        sim.prepare(ctx)
        result = sim.run_trial(ctx)
    except Exception as exc:  # Infrastructure-level crash inside the adapter.
        logger.exception("simulator adapter crashed for trial %s", trial.id)
        execution_error = exc
    finally:
        try:
            sim.cleanup(ctx)
        except Exception:  # pragma: no cover — cleanup is best-effort.
            logger.exception("simulator adapter cleanup failed for trial %s", trial.id)
        heartbeat.stop()

    # The exact owner + attempt count form a fencing token. If another worker
    # reclaimed this lease, the old simulator result is intentionally dropped.
    if not _acquire_completion_fence(db, lease_token, lease_seconds=lease_seconds):
        return trial_id
    trial = db.get(models.Trial, trial_id)
    if trial is None:  # pragma: no cover - defensive only.
        db.rollback()
        return trial_id
    job = db.get(models.Job, job_id)
    if job is None:  # pragma: no cover - defensive only.
        _mark_trial_failed(db, trial, code="JOB_NOT_FOUND", reason="Job row disappeared.")
        return trial_id

    if execution_error is not None:
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_SIM_ERROR,
            reason=str(execution_error)[:500],
        )
        return trial_id
    if result is None:  # pragma: no cover - adapter contract guard.
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_SIM_ERROR,
            reason="Adapter returned without a TrialResult.",
        )
        return trial_id

    if not result.success or result.metrics is None:
        failure: TrialFailure = result.failure or TrialFailure(
            code=FAILURE_SIM_ERROR, reason="Adapter returned no metrics and no failure."
        )
        # Commit post-mortem artifacts and terminal state together. S3 keys
        # are deterministic, so a retry after an upload/DB boundary is safe.
        _persist_artifacts(db, trial, result.artifacts)
        _mark_trial_failed(
            db,
            trial,
            code=failure.code,
            reason=failure.reason,
            log_excerpt=result.log_excerpt,
        )
        return trial_id

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
    trial.lease_owner = None
    trial.lease_expires_at = None
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
    trial.lease_owner = None
    trial.lease_expires_at = None
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
