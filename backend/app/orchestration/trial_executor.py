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
import math
import os
import shutil
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import case, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.orchestration.events import record_event
from app.parameters import get_parameter, validate_parameter_values
from app.simulator import (
    ArtifactMetadata,
    JobConfig,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialResult,
    get_simulator_adapter,
)
from app.simulator.base import (
    FAILURE_ARTIFACT_PERSISTENCE,
    FAILURE_INVALID_PARAMETERS,
    FAILURE_RESULT_PERSISTENCE,
    FAILURE_SIM_ERROR,
)
from app.storage import get_artifact_storage
from app.storage.integrity import (
    ArtifactIntegrityError,
    artifact_content_digest,
    bind_artifact_integrity,
)
from app.storage.registration import guard_artifact_registration


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


def _validated_worker_id(worker_id: object) -> str:
    if not isinstance(worker_id, str):
        raise ValueError("worker_id must be a string")
    normalized = worker_id.strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError("worker_id must be 1-128 visible characters")
    return normalized


def _finite_job_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


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
        cancellation_event: threading.Event | None = None,
    ) -> None:
        self._token = token
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self.lost = threading.Event()
        self._cancellation_event = cancellation_event
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
                        if self._cancellation_event is not None:
                            self._cancellation_event.set()
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
        if not isinstance(job.reference_track_json, list):
            raise ValueError("reference_track_json must be an array")
        normalized: list[dict[str, float]] = []
        for index, point in enumerate(job.reference_track_json):
            if not isinstance(point, dict):
                raise ValueError(f"reference track point {index} must be an object")
            x = point.get("x")
            y = point.get("y")
            z_raw = point.get("z")
            if x is None or y is None:
                raise ValueError(f"reference track point {index} requires x and y")
            normalized.append(
                {
                    "x": _finite_job_number(x, field_name=f"track[{index}].x"),
                    "y": _finite_job_number(y, field_name=f"track[{index}].y"),
                    "z": _finite_job_number(
                        job.altitude_m if z_raw is None else z_raw,
                        field_name=f"track[{index}].z",
                    ),
                }
            )
        reference_track = normalized

    parameter_space = job.parameter_space_json or []
    if not isinstance(parameter_space, list) or any(
        not isinstance(item, dict) for item in parameter_space
    ):
        raise ValueError("parameter_space_json must be an array of objects")
    selected_parameter_names: list[str] = []
    for item in parameter_space:
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("parameter enabled flags must be boolean")
        if not enabled:
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("enabled parameters require a non-empty name")
        normalized_name = name.strip().upper()
        if normalized_name in selected_parameter_names:
            raise ValueError(f"duplicate selected parameter {normalized_name}")
        selected_parameter_names.append(normalized_name)

    vehicle_profile = job.vehicle_profile_json or {}
    if not isinstance(vehicle_profile, dict):
        raise ValueError("vehicle_profile_json must be an object")
    return JobConfig(
        track_type=job.track_type,
        start_point_x=_finite_job_number(job.start_point_x, field_name="start_point_x"),
        start_point_y=_finite_job_number(job.start_point_y, field_name="start_point_y"),
        altitude_m=_finite_job_number(job.altitude_m, field_name="altitude_m"),
        wind_north=_finite_job_number(job.wind_north, field_name="wind_north"),
        wind_east=_finite_job_number(job.wind_east, field_name="wind_east"),
        wind_south=_finite_job_number(job.wind_south, field_name="wind_south"),
        wind_west=_finite_job_number(job.wind_west, field_name="wind_west"),
        sensor_noise_level=job.sensor_noise_level,
        objective_profile=job.objective_profile,
        reference_track=reference_track,
        vehicle_profile=dict(vehicle_profile),
        parameter_catalog_version=job.parameter_catalog_version,
        selected_parameter_names=tuple(selected_parameter_names),
    )


def _build_trial_context(
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    *,
    cancellation_event: threading.Event | None = None,
) -> TrialContext:
    parameters = candidate.parameter_json or {}
    if not isinstance(parameters, dict):
        raise ValueError("candidate parameter_json must be an object")
    scenario_config = trial.scenario_config_json
    if scenario_config is not None and not isinstance(scenario_config, dict):
        raise ValueError("trial scenario_config_json must be an object")
    if isinstance(trial.seed, bool) or not isinstance(trial.seed, int):
        raise ValueError("trial seed must be an integer")
    return TrialContext(
        trial_id=trial.id,
        job_id=trial.job_id,
        job_config=_job_config_from(job),
        candidate_id=trial.candidate_id,
        parameters=dict(parameters),
        seed=trial.seed,
        scenario_type=trial.scenario_type,
        scenario_config=(dict(scenario_config) if scenario_config is not None else None),
        attempt_count=trial.attempt_count,
        cancellation_event=cancellation_event,
    )


_LEGACY_CONTROLLER_PARAMETERS = {
    "KP_XY",
    "KD_XY",
    "KI_XY",
    "VEL_LIMIT",
    "ACCEL_LIMIT",
    "DISTURBANCE_REJECTION",
}


def _validate_trial_px4_parameters(ctx: TrialContext) -> TrialContext:
    """Final safety fence before any simulator process is started."""

    profile = dict(ctx.job_config.vehicle_profile or {})
    px4_version = str(profile.get("px4_version") or "main")
    vehicle_type = str(profile.get("vehicle_type") or "multicopter")
    airframe = str(profile.get("airframe") or profile.get("simulator_model") or "x500")

    candidate_by_name: dict[str, tuple[str, Any]] = {}
    for raw_name, value in ctx.parameters.items():
        normalized_name = str(raw_name).strip().upper()
        if not normalized_name:
            raise ValueError("candidate contains an empty parameter name")
        if normalized_name in candidate_by_name:
            raise ValueError(
                f"candidate contains duplicate parameter name after normalization: "
                f"{normalized_name}"
            )
        candidate_by_name[normalized_name] = (str(raw_name), value)

    selected_names = {
        name.strip().upper()
        for name in ctx.job_config.selected_parameter_names
        if name.strip() and name.strip().upper() not in _LEGACY_CONTROLLER_PARAMETERS
    }
    px4_values: dict[str, Any] = {}
    if selected_names:
        missing = sorted(selected_names - set(candidate_by_name))
        if missing:
            raise ValueError(f"candidate is missing selected PX4 parameters: {missing}")
        px4_values = {name: candidate_by_name[name][1] for name in selected_names}
    else:
        for name, (_raw_name, value) in candidate_by_name.items():
            current_definition = get_parameter(
                name,
                px4_version=px4_version,
                vehicle_type=vehicle_type,
                airframe=airframe,
            )
            known_catalog_name = current_definition is not None or (
                get_parameter(
                    name,
                    px4_version="main",
                    vehicle_type=vehicle_type,
                    airframe=airframe,
                )
                is not None
            )
            if known_catalog_name:
                px4_values[name] = value

    if not px4_values:
        return ctx
    normalized = validate_parameter_values(
        px4_values,
        px4_version=px4_version,
        catalog_version=ctx.job_config.parameter_catalog_version,
        vehicle_type=vehicle_type,
        airframe=airframe,
        enforce_safe_bounds=True,
    )
    merged = {
        raw_name: value
        for normalized_name, (raw_name, value) in candidate_by_name.items()
        if normalized_name not in normalized
    }
    merged.update(normalized)
    return replace(ctx, parameters=merged)


def _persist_artifacts(db: Session, trial: models.Trial, artifacts: list[ArtifactMetadata]) -> None:
    guard_artifact_registration(db, owner_type="trial", owner_id=trial.id)
    storage = get_artifact_storage()
    settings = get_settings()
    seen_storage_keys: set[str] = set()
    for meta in artifacts:
        storage_path = meta.storage_path
        local_path = Path(storage_path)
        digest_source: bytes | Path | None = None
        persisted_size = meta.file_size_bytes
        if local_path.exists() and local_path.is_file():
            safe_name = Path(meta.display_name or local_path.name).name
            if safe_name in {"", ".", ".."}:
                safe_name = local_path.name
            safe_name = "".join(
                char if char.isalnum() or char in {"-", "_", "."} else "_" for char in safe_name
            ).strip(".")
            safe_name = safe_name[:200] or "artifact"
            safe_type = "".join(
                char if char.isalnum() or char in {"-", "_", "."} else "_"
                for char in meta.artifact_type
            ).strip(".")
            safe_type = safe_type[:128] or "artifact"
            source_sha256, source_size = artifact_content_digest(local_path)
            key = (
                f"jobs/{trial.job_id}/trials/{trial.id}/"
                f"attempts/{trial.attempt_count}/{safe_type}/"
                f"{source_sha256}-{safe_name}"
            )
            if key in seen_storage_keys:
                raise ArtifactIntegrityError(
                    "trial returned duplicate artifact content metadata"
                )
            seen_storage_keys.add(key)
            if settings.artifact_storage_backend == "local":
                # LocalArtifactStorage intentionally returns the source path.
                # Materialize real-simulator artifacts under the durable local
                # artifact root before an adapter removes its transient run dir.
                target = (settings.default_artifact_root_path / key).resolve()
                root = settings.default_artifact_root_path.resolve()
                if not target.is_relative_to(root):  # pragma: no cover - key is controlled.
                    raise ValueError("Trial artifact target escaped the local artifact root")
                target.parent.mkdir(parents=True, exist_ok=True)
                if local_path.resolve() != target:
                    if target.is_file():
                        target_sha256, target_size = artifact_content_digest(
                            target
                        )
                        if (
                            target_sha256 != source_sha256
                            or target_size != source_size
                        ):
                            raise ArtifactIntegrityError(
                                "content-addressed artifact target was modified"
                            )
                    else:
                        temporary = target.with_name(
                            f".{target.name}.{os.getpid()}.tmp"
                        )
                        try:
                            shutil.copy2(local_path, temporary)
                            temporary.replace(target)
                        finally:
                            try:
                                temporary.unlink(missing_ok=True)
                            except OSError:
                                logger.warning(
                                    "failed to remove temporary artifact copy %s",
                                    temporary,
                                    exc_info=True,
                                )
                local_path = target
            storage_path = storage.put_file(
                local_path,
                key,
                content_type=meta.mime_type,
            )
            persisted_size = local_path.stat().st_size
            digest_source = local_path
            if settings.artifact_storage_backend != "local":
                stored_content = storage.read_bytes(storage_path)
                stored_sha256, stored_size = artifact_content_digest(
                    stored_content
                )
                if (
                    stored_sha256 != source_sha256
                    or stored_size != source_size
                ):
                    raise ArtifactIntegrityError(
                        "artifact storage did not preserve simulator bytes"
                    )
                digest_source = stored_content
        artifact = models.Artifact(
            owner_type="trial",
            owner_id=trial.id,
            artifact_type=meta.artifact_type,
            display_name=meta.display_name,
            storage_path=storage_path,
            mime_type=meta.mime_type,
            file_size_bytes=persisted_size,
        )
        db.add(artifact)
        if digest_source is not None:
            bind_artifact_integrity(
                db,
                artifact=artifact,
                content=digest_source,
            )


def _finalize_adapter_run(
    simulator: SimulatorAdapter,
    ctx: TrialContext,
    result: TrialResult | None,
) -> None:
    """Best-effort post-persistence hook for transient simulator run data."""

    try:
        simulator.finalize_trial(ctx, result)
    except Exception:  # pragma: no cover - cleanup must not rewrite trial state.
        logger.exception("simulator adapter finalization failed for trial %s", ctx.trial_id)


def _handle_artifact_persistence_failure(
    db: Session,
    *,
    simulator: SimulatorAdapter,
    ctx: TrialContext,
    token: _TrialLeaseToken,
    lease_seconds: int,
    log_excerpt: str | None,
    failure_code: str = FAILURE_ARTIFACT_PERSISTENCE,
    failure_reason: str = (
        "Simulator finished, but one or more artifacts could not be persisted. "
        "The transient run was retained; inspect worker logs."
    ),
) -> None:
    """Fence and terminally classify a post-simulation storage failure.

    The transient simulator run is deliberately finalized with ``result=None``
    so adapters retain diagnostic files even when successful-run cleanup is
    configured. Deterministic object keys make any partial S3 upload harmless
    to a later explicit rerun.
    """

    db.rollback()
    try:
        if not _acquire_completion_fence(db, token, lease_seconds=lease_seconds):
            return
        trial = db.get(models.Trial, token.trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return
        _mark_trial_failed(
            db,
            trial,
            code=failure_code,
            reason=failure_reason,
            log_excerpt=log_excerpt,
        )
    finally:
        _finalize_adapter_run(simulator, ctx, None)


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

    worker_id = _validated_worker_id(worker_id)
    now = _now()
    lease_seconds = get_settings().worker_lease_seconds
    lease_until = now + timedelta(seconds=lease_seconds)
    reclaim_enabled = get_settings().worker_stale_running_reclaim_enabled
    claimable = (models.Trial.status == "PENDING") & (
        models.Trial.lease_expires_at.is_(None) | (models.Trial.lease_expires_at <= now)
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

    cancellation_event = threading.Event()
    try:
        ctx = _build_trial_context(
            trial,
            job,
            candidate,
            cancellation_event=cancellation_event,
        )
    except (TypeError, ValueError) as exc:
        logger.warning(
            "rejected invalid trial configuration trial=%s: %s",
            trial_id,
            exc,
        )
        if not _acquire_completion_fence(db, lease_token, lease_seconds=lease_seconds):
            return trial_id
        trial = db.get(models.Trial, trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return trial_id
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_INVALID_PARAMETERS,
            reason=str(exc)[:1000],
        )
        return trial_id
    # Do not hold the main session's read transaction open while PX4/Gazebo
    # runs. Lease heartbeats use independent short-lived sessions.
    db.commit()

    try:
        ctx = _validate_trial_px4_parameters(ctx)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "rejected invalid PX4 candidate before simulation trial=%s: %s",
            trial_id,
            exc,
        )
        if not _acquire_completion_fence(db, lease_token, lease_seconds=lease_seconds):
            return trial_id
        trial = db.get(models.Trial, trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return trial_id
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_INVALID_PARAMETERS,
            reason=str(exc)[:1000],
        )
        return trial_id

    # --- Execute --------------------------------------------------------
    settings = get_settings()
    heartbeat_interval = min(
        settings.worker_lease_heartbeat_seconds,
        max(0.1, lease_seconds / 3),
        # Cancellation clears the owned lease. Poll often enough that a long
        # PX4/Gazebo subprocess is stopped promptly after the API request.
        2.0,
    )
    heartbeat = _TrialLeaseHeartbeat(
        lease_token,
        lease_seconds=lease_seconds,
        interval_seconds=heartbeat_interval,
        cancellation_event=cancellation_event,
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
            try:
                sim.cleanup(ctx)
            except Exception:  # pragma: no cover - cleanup is best-effort.
                logger.exception("simulator adapter cleanup failed for trial %s", trial.id)
        finally:
            # Never strand the lease heartbeat when adapter cleanup is
            # interrupted by process-control exceptions such as SystemExit or
            # KeyboardInterrupt. Those BaseException subclasses must still
            # propagate to the worker boundary; only resource release is
            # unconditional here.
            heartbeat.stop()

    # The exact owner + attempt count form a fencing token. If another worker
    # reclaimed this lease, the old simulator result is intentionally dropped.
    if not _acquire_completion_fence(db, lease_token, lease_seconds=lease_seconds):
        _finalize_adapter_run(sim, ctx, result)
        return trial_id
    trial = db.get(models.Trial, trial_id)
    if trial is None:  # pragma: no cover - defensive only.
        db.rollback()
        _finalize_adapter_run(sim, ctx, result)
        return trial_id
    job = db.get(models.Job, job_id)
    if job is None:  # pragma: no cover - defensive only.
        _mark_trial_failed(db, trial, code="JOB_NOT_FOUND", reason="Job row disappeared.")
        _finalize_adapter_run(sim, ctx, result)
        return trial_id

    if execution_error is not None:
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_SIM_ERROR,
            reason=str(execution_error)[:500],
        )
        _finalize_adapter_run(sim, ctx, result)
        return trial_id
    if result is None:  # pragma: no cover - adapter contract guard.
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_SIM_ERROR,
            reason="Adapter returned without a TrialResult.",
        )
        _finalize_adapter_run(sim, ctx, result)
        return trial_id

    if not result.success or result.metrics is None:
        failure: TrialFailure = result.failure or TrialFailure(
            code=FAILURE_SIM_ERROR, reason="Adapter returned no metrics and no failure."
        )
        # Commit post-mortem artifacts and terminal state together. S3 keys
        # are deterministic, so a retry after an upload/DB boundary is safe.
        try:
            _persist_artifacts(db, trial, result.artifacts)
            _mark_trial_failed(
                db,
                trial,
                code=failure.code,
                reason=failure.reason,
                log_excerpt=result.log_excerpt,
            )
        except Exception:
            logger.exception("artifact persistence failed for trial %s", trial.id)
            _handle_artifact_persistence_failure(
                db,
                simulator=sim,
                ctx=ctx,
                token=lease_token,
                lease_seconds=lease_seconds,
                log_excerpt=result.log_excerpt,
            )
            return trial_id
        _finalize_adapter_run(sim, ctx, result)
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
    try:
        _persist_artifacts(db, trial, result.artifacts)
    except Exception:
        logger.exception("artifact persistence failed for trial %s", trial.id)
        _handle_artifact_persistence_failure(
            db,
            simulator=sim,
            ctx=ctx,
            token=lease_token,
            lease_seconds=lease_seconds,
            log_excerpt=result.log_excerpt,
        )
        return trial_id

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

    try:
        db.commit()
    except Exception:
        logger.exception("terminal persistence failed for trial %s", trial.id)
        _handle_artifact_persistence_failure(
            db,
            simulator=sim,
            ctx=ctx,
            token=lease_token,
            lease_seconds=lease_seconds,
            log_excerpt=result.log_excerpt,
            failure_code=FAILURE_RESULT_PERSISTENCE,
            failure_reason=(
                "Simulator and artifact persistence finished, but the terminal Trial "
                "state could not be committed. The transient run was retained; "
                "inspect worker logs."
            ),
        )
        return trial_id
    _finalize_adapter_run(sim, ctx, result)
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
