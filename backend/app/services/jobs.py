"""Job service — creation, listing, rerun, cancel, serialization.

All state transitions that the HTTP layer can perform live here. Trial
execution, baseline + optimizer dispatch, aggregation, and report
generation live in :mod:`app.orchestration` and run inside the worker
process — never inside a request handler.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app import secrets as job_secrets
from app.orchestration.events import record_event


class JobServiceError(Exception):
    """Structured error surfaced by the HTTP layer as an error envelope."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_gpt_request(req: schemas.JobCreateRequest) -> None:
    if req.optimizer_strategy != "gpt":
        return
    if req.openai is None or not req.openai.api_key:
        raise JobServiceError(
            "INVALID_INPUT",
            "openai.api_key is required when optimizer_strategy=gpt.",
            http_status=422,
        )
    if not job_secrets.is_configured():
        raise JobServiceError(
            "CONFIGURATION_ERROR",
            (
                "Server-side secret key is not configured. Set APP_SECRET_KEY "
                "or DRONEDREAM_SECRET_KEY before submitting a GPT-tuned job."
            ),
            http_status=500,
        )


def _create_job_from_config(
    db: Session,
    *,
    user: models.User,
    req: schemas.JobCreateRequest,
    source_job_id: str | None = None,
) -> models.Job:
    now = _now()
    job = models.Job(
        user_id=user.id,
        track_type=req.track_type,
        start_point_x=req.start_point.x,
        start_point_y=req.start_point.y,
        altitude_m=req.altitude_m,
        wind_north=req.wind.north,
        wind_east=req.wind.east,
        wind_south=req.wind.south,
        wind_west=req.wind.west,
        sensor_noise_level=req.sensor_noise_level,
        objective_profile=req.objective_profile,
        reference_track_json=(
            [point.model_dump(mode="json") for point in req.reference_track]
            if req.reference_track is not None
            else None
        ),
        status="QUEUED",
        current_phase="queued",
        progress_completed_trials=0,
        progress_total_trials=0,
        source_job_id=source_job_id,
        queued_at=now,
        simulator_backend_requested=req.simulator_backend,
        optimizer_strategy=req.optimizer_strategy,
        max_iterations=req.max_iterations,
        trials_per_candidate=req.trials_per_candidate,
        max_total_trials=req.max_total_trials,
        target_rmse=req.acceptance_criteria.target_rmse,
        target_max_error=req.acceptance_criteria.target_max_error,
        min_pass_rate=req.acceptance_criteria.min_pass_rate,
        current_generation=0,
        optimization_outcome=None,
        openai_model=(req.openai.model if req.openai is not None else None),
    )
    db.add(job)
    db.flush()
    if req.openai is not None and req.openai.api_key:
        db.add(
            models.JobSecret(
                job_id=job.id,
                provider="openai",
                encrypted_api_key=job_secrets.encrypt_secret(req.openai.api_key),
            )
        )
    db.add(
        models.JobEvent(
            job_id=job.id,
            event_type="job_created",
            payload_json={
                "source_job_id": source_job_id,
                "simulator_backend": req.simulator_backend,
                "optimizer_strategy": req.optimizer_strategy,
                "max_iterations": req.max_iterations,
                "trials_per_candidate": req.trials_per_candidate,
            },
        )
    )
    db.add(
        models.JobEvent(
            job_id=job.id,
            event_type="job_queued",
            payload_json=None,
        )
    )
    return job


def _resolve_user(db: Session, user: models.User | None) -> models.User:
    if user is not None and user.id:
        return user
    if user is not None and user.email:
        existing_email = (
            db.scalars(select(models.User).where(models.User.email == user.email).limit(1)).first()
        )
        if existing_email is not None:
            return existing_email
        created_email_user = models.User(email=user.email, display_name=user.display_name)
        db.add(created_email_user)
        db.flush()
        return created_email_user
    existing = db.scalars(select(models.User).limit(1)).first()
    if existing is not None:
        return existing
    created = models.User(display_name="Default User")
    db.add(created)
    db.flush()
    return created


def create_job(
    db: Session, req: schemas.JobCreateRequest, *, user: models.User | None = None
) -> models.Job:
    _validate_gpt_request(req)
    job = _create_job_from_config(
        db, user=_resolve_user(db, user), req=req, source_job_id=None
    )
    db.commit()
    db.refresh(job)
    return job


def purge_job_secrets(db: Session, job: models.Job, *, reason: str = "job_terminal") -> int:
    """Soft-delete any JobSecret rows attached to a terminal job.

    Returns the number of secrets purged. Safe to call multiple times.
    """

    now = _now()
    deleted = 0
    for secret in list(job.secrets):
        if secret.deleted_at is not None:
            continue
        secret.deleted_at = now
        secret.encrypted_api_key = ""
        deleted += 1
    if deleted:
        record_event(db, job.id, "job_secrets_purged", {"reason": reason, "count": deleted})
    return deleted


def list_jobs(
    db: Session,
    *,
    user: models.User | None = None,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> tuple[list[models.Job], int]:
    if page < 1:
        raise JobServiceError("INVALID_INPUT", "page must be >= 1", http_status=422)
    if page_size < 1 or page_size > 200:
        raise JobServiceError("INVALID_INPUT", "page_size must be in [1, 200]", http_status=422)

    resolved_user = _resolve_user(db, user)
    owner_filter = or_(models.Job.user_id == resolved_user.id, models.Job.user_id.is_(None))
    stmt = select(models.Job).where(owner_filter)
    count_stmt = select(func.count(models.Job.id)).where(owner_filter)
    if status is not None:
        stmt = stmt.where(models.Job.status == status)
        count_stmt = count_stmt.where(models.Job.status == status)

    total = int(db.scalar(count_stmt) or 0)
    stmt = (
        stmt.order_by(models.Job.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(db.scalars(stmt))
    return items, total


def get_job(db: Session, job_id: str, *, user: models.User | None = None) -> models.Job:
    job = db.get(models.Job, job_id)
    resolved_user = _resolve_user(db, user)
    if job is None or (job.user_id is not None and job.user_id != resolved_user.id):
        raise JobServiceError("JOB_NOT_FOUND", f"Job {job_id} was not found.", http_status=404)
    return job


def rerun_job(
    db: Session,
    job_id: str,
    *,
    user: models.User | None = None,
    openai: schemas.OpenAIConfig | None = None,
) -> models.Job:
    resolved_user = _resolve_user(db, user)
    source = get_job(db, job_id, user=resolved_user)
    strategy: schemas.OptimizerStrategy = source.optimizer_strategy  # type: ignore[assignment]
    rerun_openai: schemas.OpenAIConfig | None = None
    if strategy == "gpt":
        if openai is None or not openai.api_key:
            raise JobServiceError(
                "INVALID_INPUT",
                "openai.api_key is required when rerunning a gpt job.",
                http_status=422,
            )
        rerun_openai = schemas.OpenAIConfig(
            api_key=openai.api_key,
            model=openai.model if openai.model is not None else source.openai_model,
        )
    req = schemas.JobCreateRequest(
        track_type=source.track_type,  # type: ignore[arg-type]
        start_point=schemas.StartPoint(x=source.start_point_x, y=source.start_point_y),
        altitude_m=source.altitude_m,
        wind=schemas.WindVector(
            north=source.wind_north,
            east=source.wind_east,
            south=source.wind_south,
            west=source.wind_west,
        ),
        sensor_noise_level=source.sensor_noise_level,  # type: ignore[arg-type]
        objective_profile=source.objective_profile,  # type: ignore[arg-type]
        reference_track=(
            [schemas.TrackPoint(**point) for point in source.reference_track_json]
            if source.reference_track_json
            else None
        ),
        simulator_backend=source.simulator_backend_requested,  # type: ignore[arg-type]
        optimizer_strategy=strategy,
        max_iterations=source.max_iterations,
        trials_per_candidate=source.trials_per_candidate,
        max_total_trials=source.max_total_trials,
        acceptance_criteria=schemas.AcceptanceCriteria(
            target_rmse=source.target_rmse,
            target_max_error=source.target_max_error,
            min_pass_rate=source.min_pass_rate,
        ),
        openai=rerun_openai,
    )
    new_job = _create_job_from_config(db, user=resolved_user, req=req, source_job_id=source.id)
    db.commit()
    db.refresh(new_job)
    return new_job


def cancel_job(db: Session, job_id: str, *, user: models.User | None = None) -> models.Job:
    job = get_job(db, job_id, user=user)
    if job.status in schemas.JOB_TERMINAL_STATUSES:
        code = (
            "JOB_ALREADY_CANCELLED" if job.status == "CANCELLED" else "JOB_ALREADY_COMPLETED"
        )
        raise JobServiceError(
            code,
            f"Job {job.id} is already in terminal state {job.status}.",
            http_status=409,
        )
    if job.status not in schemas.JOB_CANCELLABLE_STATUSES:
        raise JobServiceError(
            "JOB_NOT_RUNNABLE",
            f"Job {job.id} in status {job.status} cannot be cancelled.",
            http_status=409,
        )
    now = _now()
    job.status = "CANCELLED"
    job.cancelled_at = now
    job.current_phase = None
    db.add(models.JobEvent(job_id=job.id, event_type="job_cancelled", payload_json=None))
    db.commit()
    db.refresh(job)
    return job


# --- Serialization ----------------------------------------------------------


# Cap on how many JobEvent rows we embed on the Job detail response. Keeps
# the payload bounded even after many optimizer+trial events accumulate.
_RECENT_EVENTS_LIMIT = 25


def _recent_events(job: models.Job) -> list[schemas.JobEventInfo]:
    """Return the newest ``_RECENT_EVENTS_LIMIT`` events for a job.

    SQLAlchemy loads ``job.events`` in insertion order; we sort defensively
    and truncate to the limit so callers get a stable, bounded list.
    """

    events = sorted(
        list(job.events), key=lambda e: (e.created_at, e.id), reverse=True
    )[:_RECENT_EVENTS_LIMIT]
    return [
        schemas.JobEventInfo(
            id=e.id,
            event_type=e.event_type,
            payload=e.payload_json,
            created_at=e.created_at,
        )
        for e in events
    ]


def to_job_schema(job: models.Job) -> schemas.Job:
    latest_error = None
    if job.latest_error_code is not None:
        latest_error = schemas.JobErrorInfo(
            code=job.latest_error_code,
            message=job.latest_error_message or "",
        )
    return schemas.Job(
        id=job.id,
        track_type=job.track_type,  # type: ignore[arg-type]
        start_point=schemas.StartPoint(x=job.start_point_x, y=job.start_point_y),
        altitude_m=job.altitude_m,
        wind=schemas.WindVector(
            north=job.wind_north,
            east=job.wind_east,
            south=job.wind_south,
            west=job.wind_west,
        ),
        sensor_noise_level=job.sensor_noise_level,  # type: ignore[arg-type]
        objective_profile=job.objective_profile,  # type: ignore[arg-type]
        reference_track=(
            [schemas.TrackPoint(**point) for point in job.reference_track_json]
            if job.reference_track_json
            else None
        ),
        status=job.status,  # type: ignore[arg-type]
        progress=schemas.JobProgress(
            completed_trials=job.progress_completed_trials,
            total_trials=job.progress_total_trials,
            current_phase=job.current_phase,
        ),
        baseline_candidate_id=job.baseline_candidate_id,
        best_candidate_id=job.best_candidate_id,
        source_job_id=job.source_job_id,
        latest_error=latest_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        cancelled_at=job.cancelled_at,
        failed_at=job.failed_at,
        recent_events=_recent_events(job),
        simulator_backend_requested=job.simulator_backend_requested,  # type: ignore[arg-type]
        optimizer_strategy=job.optimizer_strategy,  # type: ignore[arg-type]
        max_iterations=job.max_iterations,
        trials_per_candidate=job.trials_per_candidate,
        max_total_trials=job.max_total_trials,
        acceptance_criteria=schemas.AcceptanceCriteria(
            target_rmse=job.target_rmse,
            target_max_error=job.target_max_error,
            min_pass_rate=job.min_pass_rate,
        ),
        current_generation=job.current_generation,
        optimization_outcome=job.optimization_outcome,  # type: ignore[arg-type]
        openai_model=job.openai_model,
    )


def to_trial_summary(trial: models.Trial) -> schemas.TrialSummary:
    candidate = trial.candidate
    source_type: schemas.CandidateSourceType | None = None
    if candidate is not None and candidate.source_type in {
        "baseline",
        "optimizer",
        "llm_optimizer",
    }:
        source_type = candidate.source_type  # type: ignore[assignment]
    return schemas.TrialSummary(
        id=trial.id,
        candidate_id=trial.candidate_id,
        seed=trial.seed,
        scenario_type=trial.scenario_type,  # type: ignore[arg-type]
        status=trial.status,  # type: ignore[arg-type]
        score=trial.metric.score if trial.metric is not None else None,
        pass_flag=(trial.metric.pass_flag if trial.metric is not None else None),
        candidate_label=candidate.label if candidate is not None else None,
        candidate_source_type=source_type,
        candidate_is_baseline=bool(candidate.is_baseline) if candidate is not None else False,
        candidate_is_best=bool(candidate.is_best) if candidate is not None else False,
        candidate_generation_index=(
            candidate.generation_index if candidate is not None else 0
        ),
    )


def to_trial_schema(trial: models.Trial) -> schemas.Trial:
    metrics: schemas.TrialMetrics | None = None
    m = trial.metric
    if m is not None and m.rmse is not None and m.score is not None:
        metrics = schemas.TrialMetrics(
            rmse=m.rmse,
            max_error=m.max_error or 0.0,
            overshoot_count=m.overshoot_count or 0,
            completion_time=m.completion_time or 0.0,
            crash_flag=m.crash_flag,
            timeout_flag=m.timeout_flag,
            score=m.score,
            final_error=m.final_error or 0.0,
            pass_flag=m.pass_flag,
            instability_flag=m.instability_flag,
        )
    return schemas.Trial(
        id=trial.id,
        job_id=trial.job_id,
        candidate_id=trial.candidate_id,
        seed=trial.seed,
        scenario_type=trial.scenario_type,  # type: ignore[arg-type]
        status=trial.status,  # type: ignore[arg-type]
        score=m.score if m is not None else None,
        attempt_count=trial.attempt_count,
        worker_id=trial.worker_id,
        simulator_backend=trial.simulator_backend,
        failure_code=trial.failure_code,
        failure_reason=trial.failure_reason,
        log_excerpt=trial.log_excerpt,
        metrics=metrics,
        queued_at=trial.queued_at,
        started_at=trial.started_at,
        finished_at=trial.finished_at,
    )


def to_artifact_schema(artifact: models.Artifact) -> schemas.Artifact:
    return schemas.Artifact(
        id=artifact.id,
        owner_type=artifact.owner_type,
        owner_id=artifact.owner_id,
        artifact_type=artifact.artifact_type,
        display_name=artifact.display_name,
        storage_path=artifact.storage_path,
        mime_type=artifact.mime_type,
        file_size_bytes=artifact.file_size_bytes,
        created_at=artifact.created_at,
    )
