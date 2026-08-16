"""Trial-level execution.

The worker polls for a fairly scheduled ``PENDING`` trial, claims it by
moving it to ``RUNNING``, hands control to a
:class:`~app.simulator.SimulatorAdapter`, persists the returned metrics +
artifact metadata, and sets the trial terminal. Progress counters on the
parent job are updated atomically with trial completion.

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

import copy
import logging
import math
import os
import shutil
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased

from app import models, schemas
from app.config import get_settings
from app.optimization.outcome_taxonomy import classify_trial_outcome
from app.optimization.scenarios import validate_scenario_execution_contract
from app.orchestration.attempt_evidence import (
    TrialAttemptEvidenceError,
    accepted_trial_attempt_evidence,
    record_accepted_trial_attempt_outcome,
    record_superseded_trial_attempt_outcome,
    record_trial_attempt_claim,
    snapshot_trial_attempt_inputs,
    trial_attempt_claim_matches_current_inputs,
)
from app.orchestration.events import record_event
from app.orchestration.outcome_contract_guard import check_job_outcome_contract
from app.orchestration.qualification_receipts import (
    record_qualification_trial_receipt,
)
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
    FAILURE_INPUT_EVIDENCE_DRIFT,
    FAILURE_INVALID_PARAMETERS,
    FAILURE_INVALID_RESULT,
    FAILURE_OUTCOME_CONTRACT_DRIFT,
    FAILURE_RESULT_PERSISTENCE,
    FAILURE_SCENARIO_CONTRACT_DRIFT,
    FAILURE_SIM_ERROR,
)
from app.storage import get_artifact_storage
from app.storage.evidence import candidate_trial_artifact_evidence
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

_MAX_CLAIM_COLLISION_RETRIES = 32


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


def _attempt_for_token(
    db: Session,
    token: _TrialLeaseToken,
) -> models.TrialExecutionAttempt | None:
    return db.scalar(
        select(models.TrialExecutionAttempt).where(
            models.TrialExecutionAttempt.trial_id == token.trial_id,
            models.TrialExecutionAttempt.attempt_count == token.attempt_count,
        )
    )


def _trial_artifact_evidence(
    trial: models.Trial,
    *,
    verify_bytes: bool,
) -> dict[str, Any]:
    mapping = candidate_trial_artifact_evidence(
        trial.candidate,
        [trial],
        verify_bytes=verify_bytes,
    )
    if mapping is None or trial.id not in mapping:
        raise TrialAttemptEvidenceError(
            "physical attempt cannot resolve its Trial artifact evidence"
        )
    return mapping[trial.id]


def _seal_accepted_attempt(
    db: Session,
    *,
    trial: models.Trial,
    attempt_id: str | None,
) -> None:
    if attempt_id is None:
        return
    db.flush()
    attempt = db.get(models.TrialExecutionAttempt, attempt_id)
    if attempt is None:
        raise TrialAttemptEvidenceError("terminal Trial is missing its physical attempt claim")
    outcome_class = classify_trial_outcome(
        status=trial.status,
        failure_code=trial.failure_code,
        usable_metric=trial.metric is not None,
    )
    record_accepted_trial_attempt_outcome(
        db,
        trial=trial,
        attempt=attempt,
        outcome_class=outcome_class,
        artifact_evidence=_trial_artifact_evidence(
            trial,
            verify_bytes=True,
        ),
    )


def _seal_qualification_trial_receipt(
    db: Session,
    *,
    trial: models.Trial,
) -> None:
    """Persist the terminal qualification receipt in the Trial transaction."""

    if trial.qualification_id is None:
        return
    db.flush()
    artifact_evidence = _trial_artifact_evidence(
        trial,
        verify_bytes=True,
    )
    db.expire(trial, ["accepted_attempt", "qualification_receipt"])
    accepted_attempt = accepted_trial_attempt_evidence(
        trial,
        artifact_evidence=artifact_evidence,
    )
    record_qualification_trial_receipt(
        db,
        trial=trial,
        accepted_attempt=accepted_attempt,
        artifact_evidence=artifact_evidence,
    )


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

        renewal_deadline = time.monotonic() + float(self._lease_seconds)
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
                    renewal_deadline = time.monotonic() + float(self._lease_seconds)
            except Exception:
                logger.warning(
                    "failed to renew lease for trial %s",
                    self._token.trial_id,
                    exc_info=True,
                )
                # A short database outage does not invalidate the current
                # ownership proof. Once the last confirmed lease window has
                # elapsed, however, another worker may legally reclaim the
                # Trial. Stop this adapter through its cancellation event so
                # two physical simulations do not keep running in parallel;
                # the completion fence remains the final persistence guard.
                if time.monotonic() >= renewal_deadline:
                    self.lost.set()
                    if self._cancellation_event is not None:
                        self._cancellation_event.set()
                    logger.error(
                        "trial %s lease could not be confirmed before expiry; "
                        "requesting simulator cancellation",
                        self._token.trial_id,
                    )
                    return


def _acquire_completion_fence(
    db: Session,
    token: _TrialLeaseToken,
    *,
    lease_seconds: int,
) -> bool:
    """Fence result persistence using the global Job-before-Trial lock order."""

    job_id = db.scalar(select(models.Trial.job_id).where(models.Trial.id == token.trial_id))
    if not isinstance(job_id, str) or not job_id:
        db.rollback()
        return False
    # Cancellation acquires the Job row before it updates child Trials. Taking
    # the same first lock here prevents a PostgreSQL Job<->Trial deadlock when
    # cancellation races simulator completion.
    locked_job = db.scalar(select(models.Job).where(models.Job.id == job_id).with_for_update())
    if locked_job is None:
        db.rollback()
        return False
    if not _renew_owned_lease(db, token, lease_seconds=lease_seconds):
        db.rollback()
        current = db.get(models.Trial, token.trial_id)
        attempt = _attempt_for_token(db, token)
        if (
            current is not None
            and attempt is not None
            and attempt.outcome is None
            and current.attempt_count > token.attempt_count
        ):
            record_superseded_trial_attempt_outcome(
                db,
                attempt=attempt,
                superseded_by_attempt_count=current.attempt_count,
                finished_at=_now(),
            )
            db.commit()
        logger.warning(
            "discarding stale result for trial %s attempt=%d worker=%s",
            token.trial_id,
            token.attempt_count,
            token.worker_id,
        )
        return False
    db.expire_all()
    return True


def _claim_inputs_still_match(
    db: Session,
    trial: models.Trial,
    *,
    attempt_id: str | None,
    lock_sources: bool,
) -> bool:
    """Verify the claim receipt, optionally row-locking every mutable source."""

    if attempt_id is None:
        return False
    # Never let a caller's identity-map state stand in for current database
    # evidence. This helper is used across transaction boundaries around a
    # potentially long simulator run, so refresh its sources itself.
    db.expire_all()
    if lock_sources:
        locked_job = db.scalar(
            select(models.Job).where(models.Job.id == trial.job_id).with_for_update()
        )
        locked_candidate = db.scalar(
            select(models.CandidateParameterSet)
            .where(models.CandidateParameterSet.id == trial.candidate_id)
            .with_for_update()
        )
        if locked_job is None or locked_candidate is None:
            return False
        current_attempt = db.scalar(
            select(models.TrialExecutionAttempt)
            .where(models.TrialExecutionAttempt.id == attempt_id)
            .with_for_update()
        )
    else:
        current_attempt = db.get(models.TrialExecutionAttempt, attempt_id)
    return current_attempt is not None and trial_attempt_claim_matches_current_inputs(
        trial,
        attempt=current_attempt,
    )


def _trial_execution_contract_failure(
    db: Session,
    *,
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> tuple[str, str] | None:
    """Return a closed failure when frozen Trial authority has diverged."""

    if not check_job_outcome_contract(db, job).valid:
        return (
            FAILURE_OUTCOME_CONTRACT_DRIFT,
            "frozen_job_outcome_contract_mismatch",
        )
    if not job.scenario_suite_json:
        return None
    if candidate.job_id != job.id:
        return (FAILURE_SCENARIO_CONTRACT_DRIFT, "candidate_job_mismatch")
    if candidate.source_type == "baseline":
        if not candidate.is_baseline or job.baseline_candidate_id != candidate.id:
            return (
                FAILURE_SCENARIO_CONTRACT_DRIFT,
                "baseline_candidate_identity_mismatch",
            )
    elif candidate.is_baseline or job.baseline_candidate_id == candidate.id:
        return (
            FAILURE_SCENARIO_CONTRACT_DRIFT,
            "candidate_baseline_role_mismatch",
        )
    try:
        suite = schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
    except (TypeError, ValueError):
        return (
            FAILURE_SCENARIO_CONTRACT_DRIFT,
            "invalid_persisted_scenario_suite",
        )
    contract = validate_scenario_execution_contract(
        suite,
        scenario_type=trial.scenario_type,
        scenario_config=trial.scenario_config_json,
        seed=trial.seed,
        candidate_source=candidate.source_type,
        candidate_generation=candidate.generation_index,
        candidate_is_baseline=candidate.is_baseline,
        optimizer_metadata=candidate.optimizer_metadata_json,
        advanced_scenario_config=job.advanced_scenario_config_json,
    )
    if contract.valid:
        return None
    return (
        FAILURE_SCENARIO_CONTRACT_DRIFT,
        contract.error or "scenario_contract_mismatch",
    )


def _refresh_progress_counters(db: Session, job: models.Job) -> None:
    """Recompute ``progress_completed_trials`` from terminal trial rows.

    Uses the actual trial rows as the source of truth (per the Phase 3 spec
    that job progress must be driven by real trial state, not a fake counter).
    """

    terminal = {"COMPLETED", "FAILED", "CANCELLED"}
    completed = sum(1 for t in job.trials if t.status in terminal)
    job.progress_completed_trials = completed


def _job_config_from_snapshot(snapshot: Mapping[str, Any]) -> JobConfig:
    reference_track: list[dict[str, float]] | None = None
    raw_reference_track = snapshot.get("reference_track")
    if raw_reference_track:
        if not isinstance(raw_reference_track, list):
            raise ValueError("reference_track_json must be an array")
        normalized: list[dict[str, float]] = []
        for index, point in enumerate(raw_reference_track):
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
                        snapshot.get("altitude_m") if z_raw is None else z_raw,
                        field_name=f"track[{index}].z",
                    ),
                }
            )
        reference_track = normalized

    parameter_space = snapshot.get("parameter_space") or []
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

    vehicle_profile = snapshot.get("vehicle_profile") or {}
    if not isinstance(vehicle_profile, dict):
        raise ValueError("vehicle_profile_json must be an object")
    track_type = snapshot.get("track_type")
    sensor_noise_level = snapshot.get("sensor_noise_level")
    objective_profile = snapshot.get("objective_profile")
    if not isinstance(track_type, str):
        raise ValueError("track_type must be a string")
    if not isinstance(sensor_noise_level, str):
        raise ValueError("sensor_noise_level must be a string")
    if not isinstance(objective_profile, str):
        raise ValueError("objective_profile must be a string")
    parameter_catalog_version = snapshot.get("parameter_catalog_version")
    if parameter_catalog_version is not None and not isinstance(
        parameter_catalog_version,
        str,
    ):
        raise ValueError("parameter_catalog_version must be a string")
    return JobConfig(
        track_type=track_type,
        start_point_x=_finite_job_number(
            snapshot.get("start_point_x"),
            field_name="start_point_x",
        ),
        start_point_y=_finite_job_number(
            snapshot.get("start_point_y"),
            field_name="start_point_y",
        ),
        altitude_m=_finite_job_number(
            snapshot.get("altitude_m"),
            field_name="altitude_m",
        ),
        wind_north=_finite_job_number(
            snapshot.get("wind_north"),
            field_name="wind_north",
        ),
        wind_east=_finite_job_number(
            snapshot.get("wind_east"),
            field_name="wind_east",
        ),
        wind_south=_finite_job_number(
            snapshot.get("wind_south"),
            field_name="wind_south",
        ),
        wind_west=_finite_job_number(
            snapshot.get("wind_west"),
            field_name="wind_west",
        ),
        sensor_noise_level=sensor_noise_level,
        objective_profile=objective_profile,
        reference_track=reference_track,
        vehicle_profile=copy.deepcopy(vehicle_profile),
        parameter_catalog_version=parameter_catalog_version,
        selected_parameter_names=tuple(selected_parameter_names),
    )


def _job_config_from(job: models.Job) -> JobConfig:
    return _job_config_from_snapshot(
        {
            "track_type": job.track_type,
            "start_point_x": job.start_point_x,
            "start_point_y": job.start_point_y,
            "altitude_m": job.altitude_m,
            "wind_north": job.wind_north,
            "wind_east": job.wind_east,
            "wind_south": job.wind_south,
            "wind_west": job.wind_west,
            "sensor_noise_level": job.sensor_noise_level,
            "objective_profile": job.objective_profile,
            "reference_track": job.reference_track_json,
            "vehicle_profile": job.vehicle_profile_json,
            "parameter_catalog_version": job.parameter_catalog_version,
            "parameter_space": job.parameter_space_json,
        }
    )


def _build_trial_context(
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    *,
    cancellation_event: threading.Event | None = None,
    input_snapshot: Mapping[str, Any] | None = None,
) -> TrialContext:
    parameters: object
    if input_snapshot is None:
        parameters = candidate.parameter_json or {}
        scenario_config = trial.scenario_config_json
        raw_trial: Mapping[str, Any] = {
            "trial_id": trial.id,
            "job_id": trial.job_id,
            "candidate_id": trial.candidate_id,
            "attempt_count": trial.attempt_count,
            "seed": trial.seed,
            "scenario_type": trial.scenario_type,
            "scenario_config": scenario_config,
        }
        job_config = _job_config_from(job)
    else:
        raw_trial_value = input_snapshot.get("trial")
        parameters = input_snapshot.get("candidate_parameters")
        raw_job_config = input_snapshot.get("job_config")
        if not isinstance(raw_trial_value, Mapping) or not isinstance(raw_job_config, Mapping):
            raise ValueError("trial execution input snapshot has an invalid shape")
        raw_trial = raw_trial_value
        scenario_config = raw_trial.get("scenario_config")
        job_config = _job_config_from_snapshot(raw_job_config)
    if not isinstance(parameters, dict):
        raise ValueError("candidate parameter_json must be an object")
    if scenario_config is not None and not isinstance(scenario_config, dict):
        raise ValueError("trial scenario_config_json must be an object")
    seed = raw_trial.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("trial seed must be an integer")
    trial_id = raw_trial.get("trial_id")
    job_id = raw_trial.get("job_id")
    candidate_id = raw_trial.get("candidate_id")
    scenario_type = raw_trial.get("scenario_type")
    attempt_count = raw_trial.get("attempt_count")
    if (
        not isinstance(trial_id, str)
        or not trial_id
        or not isinstance(job_id, str)
        or not job_id
        or not isinstance(candidate_id, str)
        or not candidate_id
        or not isinstance(scenario_type, str)
        or not scenario_type
    ):
        raise ValueError("trial execution input identity is invalid")
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 1:
        raise ValueError("trial attempt_count must be a positive integer")
    return TrialContext(
        trial_id=trial_id,
        job_id=job_id,
        job_config=job_config,
        candidate_id=candidate_id,
        parameters=copy.deepcopy(parameters),
        seed=seed,
        scenario_type=scenario_type,
        scenario_config=(copy.deepcopy(scenario_config) if scenario_config is not None else None),
        attempt_count=attempt_count,
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


def _validate_trial_px4_parameters(
    ctx: TrialContext,
    *,
    require_explicit_px4_parameters: bool = False,
) -> TrialContext:
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
        if require_explicit_px4_parameters:
            raise ValueError("real_cli optimization requires at least one explicit PX4 parameter")
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
                raise ArtifactIntegrityError("trial returned duplicate artifact content metadata")
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
                        target_sha256, target_size = artifact_content_digest(target)
                        if target_sha256 != source_sha256 or target_size != source_size:
                            raise ArtifactIntegrityError(
                                "content-addressed artifact target was modified"
                            )
                    else:
                        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
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
                stored_sha256, stored_size = storage.content_digest(storage_path)
                if stored_sha256 != source_sha256 or stored_size != source_size:
                    raise ArtifactIntegrityError(
                        "artifact storage did not preserve simulator bytes"
                    )
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
        current_attempt = _attempt_for_token(db, token)
        _mark_trial_failed(
            db,
            trial,
            code=failure_code,
            reason=failure_reason,
            log_excerpt=log_excerpt,
            attempt_id=(current_attempt.id if current_attempt is not None else None),
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
    lease_seconds = get_settings().worker_lease_seconds
    reclaim_enabled = get_settings().worker_stale_running_reclaim_enabled
    claim_collisions = 0
    while True:
        eligibility_now = _now()
        claimable = (models.Trial.status == "PENDING") & (
            models.Trial.lease_expires_at.is_(None)
            | (models.Trial.lease_expires_at <= eligibility_now)
        )
        stale_running = (
            (models.Trial.status == "RUNNING")
            & (models.Trial.lease_expires_at.is_not(None))
            & (models.Trial.lease_expires_at <= eligibility_now)
        )
        claim_pool = or_(claimable, stale_running) if reclaim_enabled else claimable
        # Schedule the least-served eligible Job first, then its oldest Trial.
        # The Job row is the short-lived scheduling mutex on PostgreSQL:
        # concurrent workers skip a locked Job and spread across other runnable
        # Jobs instead of letting one large experiment monopolize the queue.
        # ``attempt_count`` measures actual execution claims (including retry
        # work), so newly arrived Jobs receive prompt service without erasing
        # the FIFO order inside any one Job.
        eligible_trial = aliased(models.Trial)
        eligible_claimable = (eligible_trial.status == "PENDING") & (
            eligible_trial.lease_expires_at.is_(None)
            | (eligible_trial.lease_expires_at <= eligibility_now)
        )
        eligible_stale_running = (
            (eligible_trial.status == "RUNNING")
            & (eligible_trial.lease_expires_at.is_not(None))
            & (eligible_trial.lease_expires_at <= eligibility_now)
        )
        eligible_pool = (
            or_(eligible_claimable, eligible_stale_running)
            if reclaim_enabled
            else eligible_claimable
        )
        service_history = aliased(models.Trial)
        served_attempts = (
            select(func.coalesce(func.sum(service_history.attempt_count), 0))
            .where(service_history.job_id == models.Job.id)
            .correlate(models.Job)
            .scalar_subquery()
        )
        selected_job_id = db.scalar(
            select(models.Job.id)
            .where(
                models.Job.status == "RUNNING",
                models.Job.first_qualified_candidate_id.is_(None),
                exists(
                    select(eligible_trial.id).where(
                        eligible_trial.job_id == models.Job.id,
                        eligible_pool,
                    )
                ),
            )
            .order_by(
                served_attempts.asc(),
                models.Job.created_at.asc(),
                models.Job.id.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if selected_job_id is None:
            return None
        selected_trial = db.execute(
            select(models.Trial.id, models.Trial.job_id, models.Trial.status)
            .where(models.Trial.job_id == selected_job_id, claim_pool)
            .order_by(
                models.Trial.queued_at.asc().nullsfirst(),
                models.Trial.created_at.asc(),
                models.Trial.id.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        ).one_or_none()
        if selected_trial is None:
            db.rollback()
            claim_collisions += 1
            if claim_collisions >= _MAX_CLAIM_COLLISION_RETRIES:
                logger.warning(
                    "worker %s exhausted %d fair-scheduling retries",
                    worker_id,
                    _MAX_CLAIM_COLLISION_RETRIES,
                )
                return None
            continue
        trial_id = str(selected_trial.id)
        job_id = str(selected_trial.job_id)
        was_pending = selected_trial.status == "PENDING"
        claim_time = _now()
        lease_until = claim_time + timedelta(seconds=lease_seconds)

        # --- Claim ------------------------------------------------------
        update_stmt = (
            update(models.Trial)
            .where(models.Trial.id == trial_id)
            .where(claim_pool)
            .values(
                status="RUNNING",
                worker_id=worker_id,
                lease_owner=worker_id,
                lease_expires_at=lease_until,
                claimed_at=claim_time,
                finished_at=None,
                failure_code=None,
                failure_reason=None,
                log_excerpt=None,
            )
            .values(attempt_count=(models.Trial.attempt_count + 1))
            .values(
                started_at=case(
                    (models.Trial.started_at.is_(None), claim_time),
                    else_=models.Trial.started_at,
                )
            )
        )
        claim_result = db.execute(update_stmt)
        if claim_result.rowcount == 1:  # type: ignore[attr-defined]
            break
        db.rollback()
        claim_collisions += 1
        if claim_collisions >= _MAX_CLAIM_COLLISION_RETRIES:
            logger.warning(
                "worker %s exhausted %d conditional-claim retries",
                worker_id,
                _MAX_CLAIM_COLLISION_RETRIES,
            )
            return None

    backend_override: str | None = None
    env_backend = _env_simulator_backend() if adapter is None else None

    trial = db.get(models.Trial, trial_id)
    if trial is None:
        db.rollback()
        return None
    candidate = db.get(models.CandidateParameterSet, trial.candidate_id)
    job = db.get(models.Job, trial.job_id)
    if adapter is None:
        backend_override = _resolve_backend_override(
            env_backend=env_backend,
            job_backend_requested=(
                str(job.simulator_backend_requested)
                if job is not None and job.simulator_backend_requested
                else None
            ),
        )
    sim = adapter or get_simulator_adapter(backend_override)
    trial.simulator_backend = sim.backend_name
    require_explicit_px4_parameters = bool(
        sim.backend_name == "real_cli" and job is not None and job.optimizer_strategy != "none"
    )
    attempt_id: str | None = None
    cancellation_event = threading.Event()
    ctx: TrialContext | None = None
    context_error: TypeError | ValueError | None = None
    execution_contract_failure: tuple[str, str] | None = None
    if candidate is not None and job is not None:
        execution_contract_failure = _trial_execution_contract_failure(
            db,
            trial=trial,
            job=job,
            candidate=candidate,
        )
        input_snapshot = snapshot_trial_attempt_inputs(
            trial=trial,
            job=job,
            candidate=candidate,
        )
        try:
            ctx = _build_trial_context(
                trial,
                job,
                candidate,
                cancellation_event=cancellation_event,
                input_snapshot=input_snapshot,
            )
        except (TypeError, ValueError) as exc:
            context_error = exc
        if not was_pending:
            previous_open_attempts = list(
                db.scalars(
                    select(models.TrialExecutionAttempt)
                    .outerjoin(models.TrialExecutionAttemptOutcome)
                    .where(
                        models.TrialExecutionAttempt.trial_id == trial.id,
                        models.TrialExecutionAttempt.attempt_count < trial.attempt_count,
                        models.TrialExecutionAttemptOutcome.id.is_(None),
                    )
                    .order_by(models.TrialExecutionAttempt.attempt_count.asc())
                )
            )
            for previous in previous_open_attempts:
                record_superseded_trial_attempt_outcome(
                    db,
                    attempt=previous,
                    superseded_by_attempt_count=trial.attempt_count,
                    finished_at=claim_time,
                )
        attempt = record_trial_attempt_claim(
            db,
            trial=trial,
            job=job,
            candidate=candidate,
            worker_id=worker_id,
            simulator_backend=sim.backend_name,
            claim_kind=("initial" if was_pending else "stale-reclaim"),
            claimed_at=claim_time,
            input_snapshot=input_snapshot,
        )
        attempt_id = attempt.id
    db.commit()
    db.refresh(trial)
    record_event(
        db,
        trial.job_id,
        "trial_reclaimed_from_stale_worker" if not was_pending else "trial_claimed",
        {
            "trial_id": trial.id,
            "worker_id": worker_id,
            "attempt_id": attempt_id,
            "attempt_count": trial.attempt_count,
        },
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
            db,
            trial,
            code="CANDIDATE_NOT_FOUND",
            reason="Candidate row disappeared.",
            attempt_id=attempt_id,
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
        _mark_trial_failed(
            db,
            trial,
            code="JOB_NOT_FOUND",
            reason="Job row disappeared.",
            attempt_id=attempt_id,
        )
        return trial_id

    if not _claim_inputs_still_match(
        db,
        trial,
        attempt_id=attempt_id,
        lock_sources=False,
    ):
        logger.warning(
            "trial inputs diverged from claim-time evidence trial=%s attempt=%s",
            trial_id,
            attempt_id,
        )
        if not _acquire_completion_fence(
            db,
            lease_token,
            lease_seconds=lease_seconds,
        ):
            return trial_id
        trial = db.get(models.Trial, trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return trial_id
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_INPUT_EVIDENCE_DRIFT,
            reason=(
                "Trial, Candidate, or Job execution inputs changed after the "
                "attempt was claimed; the simulator was not started."
            ),
            attempt_id=attempt_id,
        )
        return trial_id

    if execution_contract_failure is not None:
        contract_failure_code, contract_failure_reason = execution_contract_failure
        logger.warning(
            "rejected non-authoritative execution contract trial=%s: %s",
            trial_id,
            contract_failure_reason,
        )
        if not _acquire_completion_fence(
            db,
            lease_token,
            lease_seconds=lease_seconds,
        ):
            return trial_id
        trial = db.get(models.Trial, trial_id)
        if trial is None:  # pragma: no cover - defensive only.
            db.rollback()
            return trial_id
        _mark_trial_failed(
            db,
            trial,
            code=contract_failure_code,
            reason=(
                "The Trial execution inputs do not match the frozen Job and "
                f"Scenario Suite contract ({contract_failure_reason}); the "
                "simulator was not started."
            )[:1000],
            attempt_id=attempt_id,
        )
        return trial_id

    if context_error is not None:
        logger.warning(
            "rejected invalid trial configuration trial=%s: %s",
            trial_id,
            context_error,
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
            reason=str(context_error)[:1000],
            attempt_id=attempt_id,
        )
        return trial_id
    if ctx is None:  # pragma: no cover - candidate/job guards above are exhaustive.
        raise RuntimeError("trial context was not frozen at claim time")
    # Do not hold the main session's read transaction open while PX4/Gazebo
    # runs. Lease heartbeats use independent short-lived sessions.
    db.commit()

    try:
        ctx = _validate_trial_px4_parameters(
            ctx,
            require_explicit_px4_parameters=require_explicit_px4_parameters,
        )
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
            attempt_id=attempt_id,
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
        _mark_trial_failed(
            db,
            trial,
            code="JOB_NOT_FOUND",
            reason="Job row disappeared.",
            attempt_id=attempt_id,
        )
        _finalize_adapter_run(sim, ctx, result)
        return trial_id

    # The simulator ran outside the transaction. Re-lock and re-verify the Job
    # and Candidate sources before any metric, artifact, or terminal outcome is
    # admitted. PostgreSQL updates now serialize behind these row locks; the
    # SQLite completion CAS already holds the database write fence.
    if not _claim_inputs_still_match(
        db,
        trial,
        attempt_id=attempt_id,
        lock_sources=True,
    ):
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_INPUT_EVIDENCE_DRIFT,
            reason=(
                "Trial, Candidate, or Job execution inputs changed while the "
                "simulator was running; its result and artifacts were rejected."
            ),
            attempt_id=attempt_id,
        )
        _finalize_adapter_run(sim, ctx, result)
        return trial_id

    if execution_error is not None:
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_SIM_ERROR,
            reason=str(execution_error)[:500],
            attempt_id=attempt_id,
        )
        _finalize_adapter_run(sim, ctx, result)
        return trial_id
    if result is None:  # pragma: no cover - adapter contract guard.
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_SIM_ERROR,
            reason="Adapter returned without a TrialResult.",
            attempt_id=attempt_id,
        )
        _finalize_adapter_run(sim, ctx, result)
        return trial_id

    if result.backend != sim.backend_name:
        _mark_trial_failed(
            db,
            trial,
            code=FAILURE_INVALID_RESULT,
            reason=(
                "Simulator result backend does not match the claimed adapter "
                f"({result.backend!r} != {sim.backend_name!r}); metrics and "
                "artifacts were rejected."
            )[:1000],
            attempt_id=attempt_id,
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
                attempt_id=attempt_id,
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
    _seal_accepted_attempt(
        db,
        trial=trial,
        attempt_id=attempt_id,
    )
    _seal_qualification_trial_receipt(db, trial=trial)

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
            "attempt_id": attempt_id,
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
    attempt_id: str | None = None,
) -> None:
    trial.status = "FAILED"
    trial.finished_at = _now()
    trial.lease_owner = None
    trial.lease_expires_at = None
    trial.failure_code = code
    trial.failure_reason = reason
    if log_excerpt is not None:
        trial.log_excerpt = log_excerpt
    _seal_accepted_attempt(
        db,
        trial=trial,
        attempt_id=attempt_id,
    )
    _seal_qualification_trial_receipt(db, trial=trial)

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
                "attempt_id": attempt_id,
            },
        )

    db.commit()
    logger.warning("trial %s failed code=%s reason=%s", trial.id, code, reason)
