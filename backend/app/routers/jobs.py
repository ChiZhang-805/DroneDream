"""Job-related routes under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.response import ok
from app.services import jobs as job_service

router = APIRouter(tags=["jobs"])

_PageQ = Query(1, ge=1)
_PageSizeQ = Query(20, ge=1, le=200)
_StatusQ: schemas.JobStatus | None = Query(None)


def _raise(err: job_service.JobServiceError) -> None:
    raise HTTPException(
        status_code=err.http_status,
        detail={"code": err.code, "message": err.message},
    )


@router.post("/jobs")
def create_job(
    req: schemas.JobCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    job = job_service.create_job(db, req)
    return ok(job_service.to_job_schema(job).model_dump(mode="json"))


@router.get("/jobs")
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    page: int = _PageQ,
    page_size: int = _PageSizeQ,
    status: schemas.JobStatus | None = _StatusQ,
) -> dict[str, object]:
    try:
        items, total = job_service.list_jobs(
            db, page=page, page_size=page_size, status=status
        )
    except job_service.JobServiceError as err:
        _raise(err)

    page_data = schemas.PaginatedJobs(
        items=[job_service.to_job_schema(j) for j in items],
        page=page,
        page_size=page_size,
        total=total,
    )
    return ok(page_data.model_dump(mode="json"))


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        job = job_service.get_job(db, job_id)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok(job_service.to_job_schema(job).model_dump(mode="json"))


@router.post("/jobs/{job_id}/rerun")
def rerun_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        job = job_service.rerun_job(db, job_id)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok(job_service.to_job_schema(job).model_dump(mode="json"))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        job = job_service.cancel_job(db, job_id)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok(job_service.to_job_schema(job).model_dump(mode="json"))


@router.get("/jobs/{job_id}/trials")
def list_job_trials(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        job = job_service.get_job(db, job_id)
    except job_service.JobServiceError as err:
        _raise(err)
    summaries = [job_service.to_trial_summary(t) for t in job.trials]
    return ok([s.model_dump(mode="json") for s in summaries])


@router.get("/jobs/{job_id}/report")
def get_job_report(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        job = job_service.get_job(db, job_id)
    except job_service.JobServiceError as err:
        _raise(err)

    report = job.report
    if report is None or report.report_status != "READY":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REPORT_NOT_READY",
                "message": f"Report for job {job.id} is not ready yet.",
            },
        )

    data = schemas.JobReport(
        job_id=job.id,
        best_candidate_id=report.best_candidate_id or "",
        summary_text=report.summary_text or "",
        baseline_metrics=schemas.AggregatedMetrics(**(report.baseline_metric_json or {})),
        optimized_metrics=schemas.AggregatedMetrics(**(report.optimized_metric_json or {})),
        comparison=[
            schemas.ComparisonPoint(**c) for c in (report.comparison_metric_json or [])
        ],
        best_parameters=report.best_parameter_json or {},
        report_status=report.report_status,  # type: ignore[arg-type]
        created_at=report.created_at,
        updated_at=report.updated_at,
    )
    return ok(data.model_dump(mode="json"))


@router.get("/jobs/{job_id}/artifacts")
def list_job_artifacts(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        job = job_service.get_job(db, job_id)
    except job_service.JobServiceError as err:
        _raise(err)

    from app import models

    artifacts = (
        db.query(models.Artifact)
        .filter(models.Artifact.owner_type == "job", models.Artifact.owner_id == job.id)
        .order_by(models.Artifact.created_at.desc())
        .all()
    )
    return ok(
        [job_service.to_artifact_schema(a).model_dump(mode="json") for a in artifacts]
    )
