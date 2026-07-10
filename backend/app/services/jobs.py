"""Job service — creation, listing, rerun, cancel, serialization.

All state transitions that the HTTP layer can perform live here. Trial
execution, baseline + optimizer dispatch, aggregation, and report
generation live in :mod:`app.orchestration` and run inside the worker
process — never inside a request handler.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import models, schemas
from app import secrets as job_secrets
from app.config import get_settings
from app.optimization.pareto import ParetoPoint, nondominated_front, representative_points
from app.optimization.robust import CandidateEvaluation, evaluate_candidate
from app.orchestration.events import record_event
from app.parameters import (
    classify_airframe,
    get_parameter,
    normalize_px4_version,
    normalize_vehicle_type,
    resolve_catalog_version,
    validate_parameter_values,
    validate_search_selections,
)
from app.storage import get_artifact_storage


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
    provider_config = req.llm or req.openai
    if provider_config is None or not provider_config.api_key:
        raise JobServiceError(
            "INVALID_INPUT",
            "llm.api_key (or legacy openai.api_key) is required when optimizer_strategy=gpt.",
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
    if req.llm is not None and req.llm.base_url:
        settings = get_settings()
        allowed = {
            item.strip().rstrip("/")
            for item in settings.llm_allowed_base_urls.split(",")
            if item.strip()
        }
        is_production = settings.app_env.strip().lower() in {"prod", "production"}
        if (is_production or allowed) and req.llm.base_url not in allowed:
            raise JobServiceError(
                "LLM_BASE_URL_NOT_ALLOWED",
                (
                    "The requested llm.base_url is not in LLM_ALLOWED_BASE_URLS. "
                    "An explicit production allowlist is required to prevent SSRF."
                ),
                http_status=422,
            )


def _validate_parameter_space(req: schemas.JobCreateRequest) -> None:
    try:
        px4_version = normalize_px4_version(req.vehicle_profile.px4_version)
    except ValueError as exc:
        raise JobServiceError("UNSUPPORTED_PX4_VERSION", str(exc), http_status=422) from exc
    try:
        canonical_catalog_version = resolve_catalog_version(
            req.parameter_catalog_version,
            px4_version=px4_version,
        )
    except ValueError as exc:
        raise JobServiceError(
            "UNSUPPORTED_PARAMETER_CATALOG",
            str(exc),
            http_status=422,
        ) from exc
    # Aliases are accepted only at the input boundary. Persisting the resolved
    # immutable id keeps reports, reruns, LLM prompts, and repro manifests from
    # claiming an alias while validation used a different installed revision.
    req.parameter_catalog_version = canonical_catalog_version
    try:
        vehicle_type = normalize_vehicle_type(req.vehicle_profile.vehicle_type)
    except ValueError as exc:
        raise JobServiceError("UNSUPPORTED_VEHICLE_TYPE", str(exc), http_status=422) from exc
    try:
        classify_airframe(req.vehicle_profile.airframe)
    except ValueError as exc:
        raise JobServiceError("UNSUPPORTED_AIRFRAME", str(exc), http_status=422) from exc
    if not req.parameter_space:
        return

    active = [selection for selection in req.parameter_space if selection.enabled]
    tunable = [selection for selection in active if not selection.locked]
    active_names = {selection.name for selection in active}
    for selection in active:
        definition = get_parameter(
            selection.name,
            px4_version=px4_version,
            vehicle_type=vehicle_type,
            airframe=req.vehicle_profile.airframe,
        )
        if definition is None:
            continue
        missing_hard_dependencies = sorted(
            dependency.parameter
            for dependency in definition.dependencies
            if dependency.kind != "recommended_with"
            and dependency.parameter not in active_names
        )
        if missing_hard_dependencies:
            raise JobServiceError(
                "INVALID_PARAMETER_SPACE",
                (
                    f"{selection.name} requires coupled parameter(s) "
                    f"{', '.join(missing_hard_dependencies)} to be enabled or locked "
                    "in the same job"
                ),
                http_status=422,
            )
    if tunable:
        result = validate_search_selections(
            (
                {
                    "name": selection.name,
                    "search_min": selection.minimum,
                    "search_max": selection.maximum,
                    "initial_value": selection.baseline,
                    "step": selection.step,
                    "scale": selection.scale,
                    "choices": selection.choices,
                }
                for selection in tunable
            ),
            px4_version=px4_version,
            catalog_version=req.parameter_catalog_version,
            vehicle_type=vehicle_type,
            airframe=req.vehicle_profile.airframe,
            enforce_safe_bounds=True,
        )
        if not result.valid:
            messages = "; ".join(issue.message for issue in result.errors)
            raise JobServiceError("INVALID_PARAMETER_SPACE", messages, http_status=422)
    try:
        validate_parameter_values(
            {selection.name: selection.baseline for selection in active},
            px4_version=px4_version,
            catalog_version=req.parameter_catalog_version,
            vehicle_type=vehicle_type,
            airframe=req.vehicle_profile.airframe,
            enforce_safe_bounds=True,
        )
    except ValueError as exc:
        raise JobServiceError("INVALID_PARAMETER_SPACE", str(exc), http_status=422) from exc

    # Disabled/locked entries are still part of the persisted contract. Resolve
    # and normalize every name now so a later enable/unlock cannot revive an
    # arbitrary or version-incompatible parameter without revalidation.
    for selection in req.parameter_space:
        definition = get_parameter(
            selection.name,
            px4_version=px4_version,
            vehicle_type=vehicle_type,
            airframe=req.vehicle_profile.airframe,
        )
        if definition is None:
            raise JobServiceError(
                "INVALID_PARAMETER_SPACE",
                f"Unknown PX4 parameter: {selection.name}",
                http_status=422,
            )
        selection.value_type = (
            "integer" if definition.value_type == "int" else "float"
        )
        if definition.choices:
            allowed_choices = {float(choice.value) for choice in definition.choices}
            if selection.choices is not None and not set(selection.choices).issubset(
                allowed_choices
            ):
                raise JobServiceError(
                    "INVALID_PARAMETER_SPACE",
                    f"{selection.name} choices contain values not defined by the catalog",
                    http_status=422,
                )
            if selection.choices is None:
                applicable_choices = sorted(
                    value
                    for value in allowed_choices
                    if selection.minimum <= value <= selection.maximum
                )
                if not applicable_choices:
                    raise JobServiceError(
                        "INVALID_PARAMETER_SPACE",
                        f"{selection.name} bounds contain no catalog choice",
                        http_status=422,
                    )
                selection.choices = applicable_choices
            if selection.enabled and not selection.locked and len(selection.choices) < 2:
                raise JobServiceError(
                    "INVALID_PARAMETER_SPACE",
                    (
                        f"{selection.name} has fewer than two reachable catalog choices; "
                        "widen its bounds or set locked=true"
                    ),
                    http_status=422,
                )
        catalog_step = float(definition.step)
        if selection.step is None:
            selection.step = catalog_step
        else:
            ratio = selection.step / catalog_step
            if ratio < 1.0 - 1e-9 or not math.isclose(
                ratio, round(ratio), rel_tol=0.0, abs_tol=1e-8
            ):
                raise JobServiceError(
                    "INVALID_PARAMETER_SPACE",
                    (
                        f"{selection.name} step must be a positive integer multiple "
                        f"of catalog step {catalog_step:g}"
                    ),
                    http_status=422,
                )


def _create_job_from_config(
    db: Session,
    *,
    user: models.User,
    req: schemas.JobCreateRequest,
    source_job_id: str | None = None,
    batch_id: str | None = None,
    persist_objective_config: bool | None = None,
    persist_scenario_suite: bool | None = None,
) -> models.Job:
    now = _now()
    if persist_objective_config is None:
        persist_objective_config = "objective_config" in req.model_fields_set
    if persist_scenario_suite is None:
        persist_scenario_suite = "scenario_suite" in req.model_fields_set
    llm_provider = req.llm.provider if req.llm is not None else (
        "openai" if req.openai is not None else None
    )
    llm_model = req.llm.model if req.llm is not None else (
        req.openai.model if req.openai is not None else None
    )
    llm_base_url = req.llm.base_url if req.llm is not None else None
    llm_api_key = req.llm.api_key if req.llm is not None else (
        req.openai.api_key if req.openai is not None else None
    )
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
        advanced_scenario_config_json=(
            req.advanced_scenario_config.model_dump(mode="json")
            if req.advanced_scenario_config is not None
            else None
        ),
        baseline_parameter_json=req.baseline_parameters.model_dump(mode="json"),
        display_name=req.display_name.strip() if req.display_name else None,
        vehicle_profile_json=req.vehicle_profile.model_dump(mode="json"),
        parameter_catalog_version=req.parameter_catalog_version,
        parameter_space_json=[
            parameter.model_dump(mode="json") for parameter in req.parameter_space
        ],
        objective_config_json=(
            req.objective_config.model_dump(mode="json")
            if persist_objective_config
            else None
        ),
        scenario_suite_json=(
            req.scenario_suite.model_dump(mode="json")
            if persist_scenario_suite
            else None
        ),
        status="QUEUED",
        current_phase="queued",
        progress_completed_trials=0,
        progress_total_trials=0,
        source_job_id=source_job_id,
        batch_id=batch_id,
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
        openai_model=llm_model,
        llm_provider=llm_provider,
        llm_base_url=llm_base_url,
    )
    db.add(job)
    db.flush()
    if llm_api_key:
        secret_expires_at = now + timedelta(
            seconds=get_settings().job_secret_ttl_seconds
        )
        db.add(
            models.JobSecret(
                job_id=job.id,
                # The current proposer consumes an OpenAI-compatible client.
                # Actual provider identity is retained on Job metadata.
                provider="openai",
                encrypted_api_key=job_secrets.encrypt_secret(llm_api_key),
                expires_at=secret_expires_at,
            )
        )
    db.add(
        models.JobEvent(
            job_id=job.id,
            event_type="job_created",
            payload_json={
                "source_job_id": source_job_id,
                "batch_id": batch_id,
                "simulator_backend": req.simulator_backend,
                "optimizer_strategy": req.optimizer_strategy,
                "max_iterations": req.max_iterations,
                "trials_per_candidate": req.trials_per_candidate,
                "baseline_parameters": req.baseline_parameters.model_dump(mode="json"),
                "vehicle_profile": req.vehicle_profile.model_dump(mode="json"),
                "parameter_catalog_version": req.parameter_catalog_version,
                "parameter_names": [item.name for item in req.parameter_space if item.enabled],
                "scenario_case_count": len(req.scenario_suite.cases),
                "objective_metrics": [
                    item.metric for item in req.objective_config.objectives
                ],
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
    existing = (
        db.scalars(
            select(models.User)
            .where(models.User.email == "default@drone-dream.local")
            .limit(1)
        ).first()
    )
    if existing is not None:
        return existing
    created = models.User(email="default@drone-dream.local", display_name="Default User")
    db.add(created)
    db.flush()
    return created


def create_job(
    db: Session, req: schemas.JobCreateRequest, *, user: models.User | None = None
) -> models.Job:
    _validate_parameter_space(req)
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


def purge_expired_job_secrets(
    db: Session, *, now: datetime | None = None
) -> int:
    """Wipe expired credentials even when jobs remain queued without a worker.

    ``expires_at`` was introduced after the first secret-store revision.  Old
    rows without it are treated as expired once ``created_at + configured TTL``
    has elapsed, so upgrades cannot leave legacy ciphertext indefinitely.
    """

    current = now or _now()
    legacy_cutoff = current - timedelta(
        seconds=get_settings().job_secret_ttl_seconds
    )
    expired = list(
        db.scalars(
            select(models.JobSecret).where(
                models.JobSecret.deleted_at.is_(None),
                models.JobSecret.encrypted_api_key != "",
                or_(
                    models.JobSecret.expires_at <= current,
                    (
                        models.JobSecret.expires_at.is_(None)
                        & (models.JobSecret.created_at <= legacy_cutoff)
                    ),
                ),
            )
        )
    )
    for secret in expired:
        secret.deleted_at = current
        secret.encrypted_api_key = ""
    if expired:
        db.commit()
    return len(expired)


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

    stmt = select(models.Job)
    count_stmt = select(func.count(models.Job.id))
    if user is not None:
        if get_settings().auth_mode == "disabled":
            owner_filter = or_(models.Job.user_id == user.id, models.Job.user_id.is_(None))
            stmt = stmt.where(owner_filter)
            count_stmt = count_stmt.where(owner_filter)
        else:
            stmt = stmt.where(models.Job.user_id == user.id)
            count_stmt = count_stmt.where(models.Job.user_id == user.id)
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
    if job is None:
        raise JobServiceError("JOB_NOT_FOUND", f"Job {job_id} was not found.", http_status=404)
    auth_disabled_owned_null = get_settings().auth_mode == "disabled" and job.user_id is None
    if user is not None and job.user_id != user.id and not auth_disabled_owned_null:
        raise JobServiceError("JOB_NOT_FOUND", f"Job {job_id} was not found.", http_status=404)
    return job


def rerun_job(
    db: Session,
    job_id: str,
    *,
    user: models.User | None = None,
    openai: schemas.OpenAIConfig | None = None,
    llm: schemas.LLMProviderConfig | None = None,
) -> models.Job:
    resolved_user = _resolve_user(db, user)
    source = get_job(db, job_id, user=resolved_user)
    rerun_suffix = " (rerun)"
    rerun_display_name = (
        f"{source.display_name[: 255 - len(rerun_suffix)]}{rerun_suffix}"
        if source.display_name
        else None
    )
    strategy: schemas.OptimizerStrategy = source.optimizer_strategy  # type: ignore[assignment]
    rerun_openai: schemas.OpenAIConfig | None = None
    rerun_llm: schemas.LLMProviderConfig | None = None
    if strategy == "gpt":
        provider_config = llm or openai
        if provider_config is None or not provider_config.api_key:
            raise JobServiceError(
                "INVALID_INPUT",
                "llm.api_key (or legacy openai.api_key) is required when rerunning a gpt job.",
                http_status=422,
            )
        if llm is not None or source.llm_provider not in {None, "openai"}:
            rerun_llm = schemas.LLMProviderConfig(
                provider=(llm.provider if llm is not None else source.llm_provider or "openai"),
                api_key=provider_config.api_key,
                model=(
                    provider_config.model
                    if provider_config.model is not None
                    else source.openai_model
                ),
                base_url=(llm.base_url if llm is not None else source.llm_base_url),
            )
        else:
            rerun_openai = schemas.OpenAIConfig(
                api_key=provider_config.api_key,
                model=(
                    provider_config.model
                    if provider_config.model is not None
                    else source.openai_model
                ),
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
        advanced_scenario_config=(
            schemas.AdvancedScenarioConfig(**source.advanced_scenario_config_json)
            if source.advanced_scenario_config_json
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
        display_name=rerun_display_name,
        baseline_parameters=(
            schemas.BaselineParameters(**source.baseline_parameter_json)
            if source.baseline_parameter_json
            else schemas.BaselineParameters()
        ),
        vehicle_profile=schemas.VehicleProfileConfig(**(source.vehicle_profile_json or {})),
        parameter_catalog_version=source.parameter_catalog_version,
        parameter_space=[
            schemas.ParameterSelection(**item) for item in (source.parameter_space_json or [])
        ],
        objective_config=schemas.ObjectiveConfig(**(source.objective_config_json or {})),
        scenario_suite=schemas.ScenarioSuiteConfig(**(source.scenario_suite_json or {})),
        llm=rerun_llm,
    )
    _validate_parameter_space(req)
    _validate_gpt_request(req)
    new_job = _create_job_from_config(
        db,
        user=resolved_user,
        req=req,
        source_job_id=source.id,
        persist_objective_config=source.objective_config_json is not None,
        persist_scenario_suite=source.scenario_suite_json is not None,
    )
    db.commit()
    db.refresh(new_job)
    return new_job


def _aggregate_batch_progress(children: list[models.Job]) -> tuple[schemas.BatchProgress, str]:
    by_status = {
        "CREATED": 0,
        "QUEUED": 0,
        "RUNNING": 0,
        "AGGREGATING": 0,
        "FINALIZING": 0,
        "COMPLETED": 0,
        "FAILED": 0,
        "CANCELLED": 0,
    }
    for child in children:
        if child.status in by_status:
            by_status[child.status] += 1
    total_jobs = len(children)
    terminal_jobs = by_status["COMPLETED"] + by_status["FAILED"] + by_status["CANCELLED"]
    if total_jobs > 0 and terminal_jobs == total_jobs:
        if by_status["FAILED"] > 0:
            status = "FAILED"
        elif by_status["CANCELLED"] > 0:
            status = "CANCELLED"
        else:
            status = "COMPLETED"
    elif (
        by_status["RUNNING"] > 0
        or by_status["AGGREGATING"] > 0
        or by_status["FINALIZING"] > 0
    ):
        status = "RUNNING"
    elif by_status["QUEUED"] > 0:
        status = "QUEUED"
    else:
        status = "CREATED"
    return (
        schemas.BatchProgress(
            total_jobs=total_jobs,
            completed_jobs=by_status["COMPLETED"],
            failed_jobs=by_status["FAILED"],
            cancelled_jobs=by_status["CANCELLED"],
            running_jobs=(
                by_status["RUNNING"]
                + by_status["AGGREGATING"]
                + by_status["FINALIZING"]
            ),
            queued_jobs=by_status["QUEUED"],
            created_jobs=by_status["CREATED"],
            terminal_jobs=terminal_jobs,
        ),
        status,
    )


def to_batch_schema(batch: models.BatchJob) -> schemas.BatchJob:
    progress, computed_status = _aggregate_batch_progress(batch.jobs)
    completed_at = batch.completed_at
    cancelled_at = batch.cancelled_at
    if computed_status in schemas.BATCH_TERMINAL_STATUSES and completed_at is None:
        terminal_times = [
            ts
            for ts in (j.completed_at or j.failed_at or j.cancelled_at for j in batch.jobs)
            if ts is not None
        ]
        completed_at = max(terminal_times) if terminal_times else None
    return schemas.BatchJob(
        id=batch.id,
        name=batch.name,
        description=batch.description,
        status=computed_status,  # type: ignore[arg-type]
        progress=progress,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        completed_at=completed_at,
        cancelled_at=cancelled_at,
    )


def create_batch(
    db: Session,
    req: schemas.BatchCreateRequest,
    *,
    user: models.User | None = None,
) -> models.BatchJob:
    resolved_user = _resolve_user(db, user)
    for child_req in req.jobs:
        _validate_parameter_space(child_req)
        _validate_gpt_request(child_req)
    batch = models.BatchJob(
        user_id=resolved_user.id,
        name=req.name,
        description=req.description,
        status="QUEUED",
    )
    db.add(batch)
    db.flush()
    for child_req in req.jobs:
        _create_job_from_config(db, user=resolved_user, req=child_req, batch_id=batch.id)
    db.commit()
    db.refresh(batch)
    return batch


def list_batches(db: Session, *, user: models.User | None = None) -> list[models.BatchJob]:
    resolved_user = _resolve_user(db, user)
    owner_filter = models.BatchJob.user_id == resolved_user.id
    if get_settings().auth_mode == "disabled":
        owner_filter = or_(owner_filter, models.BatchJob.user_id.is_(None))
    return list(
        db.scalars(
            select(models.BatchJob)
            .where(owner_filter)
            .order_by(models.BatchJob.created_at.desc())
        )
    )


def get_batch(db: Session, batch_id: str, *, user: models.User | None = None) -> models.BatchJob:
    batch = db.get(models.BatchJob, batch_id)
    resolved_user = _resolve_user(db, user)
    auth_disabled_owned_null = (
        get_settings().auth_mode == "disabled"
        and batch is not None
        and batch.user_id is None
    )
    if batch is None or (
        batch.user_id != resolved_user.id and not auth_disabled_owned_null
    ):
        raise JobServiceError(
            "BATCH_NOT_FOUND",
            f"Batch {batch_id} was not found.",
            http_status=404,
        )
    return batch


def cancel_batch(db: Session, batch_id: str, *, user: models.User | None = None) -> models.BatchJob:
    batch = get_batch(db, batch_id, user=user)
    if batch.jobs and all(
        child.status in schemas.JOB_TERMINAL_STATUSES for child in batch.jobs
    ):
        _, terminal_status = _aggregate_batch_progress(batch.jobs)
        raise JobServiceError(
            "BATCH_ALREADY_TERMINAL",
            f"Batch {batch.id} is already in terminal state {terminal_status}.",
            http_status=409,
        )
    now = _now()
    terminal_trials = {"COMPLETED", "FAILED", "CANCELLED"}
    for child in batch.jobs:
        if child.status in schemas.JOB_TERMINAL_STATUSES:
            # Sweep stale credentials too: an older worker/version may have
            # terminalized this child without performing the invariant cleanup.
            purge_job_secrets(db, child, reason="batch_cancel_terminal_sweep")
            continue
        child.status = "CANCELLED"
        child.cancelled_at = now
        child.current_phase = None
        for trial in child.trials:
            if trial.status in terminal_trials:
                continue
            trial.status = "CANCELLED"
            trial.finished_at = now
            trial.lease_owner = None
            trial.lease_expires_at = None
        db.add(
            models.JobEvent(
                job_id=child.id,
                event_type="job_cancelled",
                payload_json={"by": "batch"},
            )
        )
        purge_job_secrets(db, child, reason="batch_cancelled")
    batch.status = "CANCELLED"
    batch.cancelled_at = now
    db.commit()
    db.refresh(batch)
    return batch


def update_job(
    db: Session, job_id: str, req: schemas.JobUpdateRequest, *, user: models.User | None = None
) -> models.Job:
    job = get_job(db, job_id, user=user)
    job.display_name = req.display_name
    db.add(
        models.JobEvent(
            job_id=job.id,
            event_type="job_updated",
            payload_json={"display_name": req.display_name},
        )
    )
    db.commit()
    db.refresh(job)
    return job


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
    terminal_trials = {"COMPLETED", "FAILED", "CANCELLED"}
    job.status = "CANCELLED"
    job.cancelled_at = now
    job.current_phase = None
    for trial in job.trials:
        if trial.status in terminal_trials:
            continue
        trial.status = "CANCELLED"
        trial.finished_at = now
        trial.lease_owner = None
        trial.lease_expires_at = None
    purge_job_secrets(db, job, reason="job_cancelled")
    db.add(models.JobEvent(job_id=job.id, event_type="job_cancelled", payload_json=None))
    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job_id: str, *, user: models.User | None = None) -> dict[str, object]:
    job = get_job(db, job_id, user=user)
    if job.status not in schemas.JOB_TERMINAL_STATUSES:
        raise JobServiceError(
            "JOB_NOT_DELETABLE",
            f"Active job {job.id} cannot be deleted.",
            http_status=409,
        )
    trial_ids = [t.id for t in job.trials]
    artifact_rows = list(
        db.scalars(
            select(models.Artifact).where(
                or_(
                    (models.Artifact.owner_type == "job") & (models.Artifact.owner_id == job.id),
                    (models.Artifact.owner_type == "trial")
                    & (models.Artifact.owner_id.in_(trial_ids)),
                )
            )
        )
    )
    real_artifacts = [a for a in artifact_rows if not a.storage_path.startswith("mock://")]
    storage = get_artifact_storage() if real_artifacts else None
    try:
        for artifact in real_artifacts:
            if storage is None:
                continue
            storage_path = artifact.storage_path
            try:
                if storage_path.startswith("s3://"):
                    if storage.exists(storage_path):
                        storage.delete(storage_path)
                    continue
                raw_path = Path(storage_path)
                if ".." in raw_path.parts:
                    raise JobServiceError(
                        "ARTIFACT_PATH_FORBIDDEN",
                        "Artifact path is outside allowed roots.",
                        http_status=403,
                    )
                if not storage.exists(storage_path):
                    continue
                storage.delete(storage_path)
            except JobServiceError:
                raise
            except ValueError as exc:
                raise JobServiceError(
                    "ARTIFACT_PATH_FORBIDDEN",
                    f"Artifact path is outside allowed roots. artifact_id={artifact.id}",
                    http_status=403,
                ) from exc
            except Exception as exc:
                raise JobServiceError(
                    "ARTIFACT_DELETE_FAILED",
                    f"Failed to delete artifact_id={artifact.id}",
                    http_status=500,
                ) from exc

        for child in db.scalars(select(models.Job).where(models.Job.source_job_id == job.id)):
            child.source_job_id = None
        for artifact in artifact_rows:
            db.delete(artifact)
        db.delete(job)
        db.commit()
        return {"id": job_id, "deleted": True}
    except Exception as exc:
        db.rollback()
        if isinstance(exc, JobServiceError):
            raise exc
        raise


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
    baseline_parameters = schemas.BaselineParameters(**(job.baseline_parameter_json or {}))
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
        advanced_scenario_config=(
            schemas.AdvancedScenarioConfig(**job.advanced_scenario_config_json)
            if job.advanced_scenario_config_json
            else None
        ),
        display_name=job.display_name,
        baseline_parameters=baseline_parameters,
        vehicle_profile=schemas.VehicleProfileConfig(**(job.vehicle_profile_json or {})),
        parameter_catalog_version=job.parameter_catalog_version,
        parameter_space=[
            schemas.ParameterSelection(**item) for item in (job.parameter_space_json or [])
        ],
        objective_config=schemas.ObjectiveConfig(**(job.objective_config_json or {})),
        scenario_suite=schemas.ScenarioSuiteConfig(**(job.scenario_suite_json or {})),
        status=job.status,  # type: ignore[arg-type]
        progress=schemas.JobProgress(
            completed_trials=job.progress_completed_trials,
            total_trials=job.progress_total_trials,
            current_phase=job.current_phase,
        ),
        baseline_candidate_id=job.baseline_candidate_id,
        best_candidate_id=job.best_candidate_id,
        source_job_id=job.source_job_id,
        batch_id=job.batch_id,
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
        llm_provider=job.llm_provider,
        llm_base_url=job.llm_base_url,
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


def compare_jobs(
    db: Session,
    req: schemas.JobsCompareRequest,
    *,
    user: models.User | None = None,
) -> schemas.JobsCompareResponse:
    resolved_user = _resolve_user(db, user)
    auth_disabled = get_settings().auth_mode == "disabled"
    ids = list(dict.fromkeys(req.job_ids))
    stmt = select(models.Job).where(models.Job.id.in_(ids))
    if auth_disabled:
        stmt = stmt.where(
            or_(models.Job.user_id == resolved_user.id, models.Job.user_id.is_(None))
        )
    else:
        stmt = stmt.where(models.Job.user_id == resolved_user.id)
    rows = list(db.scalars(stmt))
    by_id = {row.id: row for row in rows}
    missing = [job_id for job_id in ids if job_id not in by_id]
    if missing:
        raise JobServiceError(
            "JOB_NOT_FOUND",
            f"Job(s) not found: {', '.join(missing)}",
            http_status=404,
        )

    items: list[schemas.JobCompareItem] = []
    for job_id in ids:
        job = by_id[job_id]
        baseline_parameters = schemas.BaselineParameters(**(job.baseline_parameter_json or {}))
        baseline_metrics = (
            dict(job.report.baseline_metric_json or {}) if job.report is not None else None
        )
        optimized_metrics = (
            dict(job.report.optimized_metric_json or {}) if job.report is not None else None
        )
        if job.status != "COMPLETED":
            baseline_metrics = None
            optimized_metrics = None
        best_candidate = next((c for c in job.candidates if c.id == job.best_candidate_id), None)
        items.append(
            schemas.JobCompareItem(
                job_id=job.id,
                display_name=job.display_name,
                baseline_parameters=baseline_parameters,
        status=job.status,  # type: ignore[arg-type]
                track_type=job.track_type,  # type: ignore[arg-type]
                simulator_backend=job.simulator_backend_requested,  # type: ignore[arg-type]
                optimizer_strategy=job.optimizer_strategy,  # type: ignore[arg-type]
                optimization_outcome=job.optimization_outcome,  # type: ignore[arg-type]
                baseline_metrics=baseline_metrics,
                optimized_metrics=optimized_metrics,
                best_candidate_id=job.best_candidate_id,
                best_parameters=dict(best_candidate.parameter_json or {})
                if best_candidate is not None
                else {},
                trial_count=len(job.trials),
                completed_trial_count=sum(1 for t in job.trials if t.status == "COMPLETED"),
                failed_trial_count=sum(1 for t in job.trials if t.status == "FAILED"),
                created_at=job.created_at,
                completed_at=job.completed_at,
            )
        )
    return schemas.JobsCompareResponse(items=items)


def _metric_sample(metric: models.TrialMetric) -> dict[str, float]:
    """Expose built-in and adapter-provided numeric metrics to objective math."""

    values: dict[str, float] = {
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
    }
    for key, raw_value in (metric.raw_metric_json or {}).items():
        if isinstance(raw_value, (bool, int, float)):
            values[key] = float(raw_value)
    return values


def _candidate_evaluation(
    candidate: models.CandidateParameterSet,
    objective_config: schemas.ObjectiveConfig,
    scenario_suite: schemas.ScenarioSuiteConfig,
) -> CandidateEvaluation | None:
    samples: list[dict[str, float]] = []
    weights: list[float] = []
    training_trials = [
        trial
        for trial in candidate.trials
        if not bool((trial.scenario_config_json or {}).get("holdout"))
    ]
    cases_by_id = {case.id: case for case in scenario_suite.cases if case.enabled}
    cases_by_type: dict[str, schemas.ScenarioCaseConfig] = {}
    for case in scenario_suite.cases:
        if case.enabled:
            cases_by_type.setdefault(case.scenario_type, case)
    for trial in candidate.trials:
        if trial.status != "COMPLETED" or trial.metric is None:
            continue
        if bool((trial.scenario_config_json or {}).get("holdout")):
            continue
        samples.append(_metric_sample(trial.metric))
        scenario_config: dict[str, Any] = trial.scenario_config_json or {}
        case_id = scenario_config.get("scenario_case_id") or scenario_config.get("_case_id")
        scenario_case = cases_by_id.get(str(case_id)) if case_id is not None else None
        if scenario_case is None:
            scenario_case = cases_by_type.get(trial.scenario_type)
        weights.append(scenario_case.weight if scenario_case is not None else 1.0)
    if not samples:
        return None
    pass_rate = sum(sample.get("pass_flag", 0.0) for sample in samples) / max(
        1, len(training_trials)
    )
    failed_rate = sum(1 for trial in training_trials if trial.status == "FAILED") / max(
        1, len(training_trials)
    )
    for sample in samples:
        sample["pass_rate"] = pass_rate
        sample["failed_trial_rate"] = failed_rate
    try:
        return evaluate_candidate(samples, objective_config, sample_weights=weights)
    except ValueError:
        # A custom metric may not be emitted by older simulator adapters.  The
        # raw aggregate remains visible while Pareto status stays unknown.
        return None


def optimization_history(job: models.Job) -> schemas.OptimizationHistory:
    """Build candidate history, robust objective values, and the Pareto front."""

    objective_config = schemas.ObjectiveConfig(**(job.objective_config_json or {}))
    scenario_suite = schemas.ScenarioSuiteConfig(**(job.scenario_suite_json or {}))
    directions: dict[str, schemas.ObjectiveDirection] = {
        objective.metric: objective.direction for objective in objective_config.objectives
    }
    items: list[schemas.Candidate] = []
    pareto_points: list[ParetoPoint] = []
    ordered_candidates = sorted(
        job.candidates, key=lambda item: (item.generation_index, item.created_at, item.id)
    )
    for candidate in ordered_candidates:
        evaluation = _candidate_evaluation(candidate, objective_config, scenario_suite)
        if evaluation is not None:
            pareto_points.append(
                ParetoPoint(
                    id=candidate.id,
                    objectives=evaluation.objectives,
                    directions=directions,
                    feasible=evaluation.feasible,
                    total_violation=evaluation.total_violation,
                )
            )
        items.append(
            schemas.Candidate(
                id=candidate.id,
                generation_index=candidate.generation_index,
                source_type=candidate.source_type,
                label=candidate.label,
                parameters=dict(candidate.parameter_json or {}),
                proposal_reason=candidate.proposal_reason,
                parent_candidate_id=candidate.parent_candidate_id,
                aggregated_score=candidate.aggregated_score,
                aggregated_metrics=(
                    dict(candidate.aggregated_metric_json)
                    if candidate.aggregated_metric_json is not None
                    else None
                ),
                objective_values=(evaluation.objectives if evaluation is not None else None),
                feasible=(evaluation.feasible if evaluation is not None else None),
                total_constraint_violation=(
                    evaluation.total_violation if evaluation is not None else None
                ),
                trial_count=candidate.trial_count,
                completed_trial_count=candidate.completed_trial_count,
                failed_trial_count=candidate.failed_trial_count,
                rank_in_job=candidate.rank_in_job,
                is_best=candidate.is_best,
                is_baseline=candidate.is_baseline,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            )
        )
    front = nondominated_front(pareto_points)
    recommendations = representative_points(pareto_points)
    return schemas.OptimizationHistory(
        items=items,
        pareto_candidate_ids=[point.id for point in front],
        recommendations={label: point.id for label, point in recommendations.items()},
        objective_directions=directions,
    )
