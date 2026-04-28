"""Batch job routes under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.auth import get_current_user
from app.db import get_db
from app.response import ok
from app.services import jobs as job_service

router = APIRouter(tags=["batches"])


def _raise(err: job_service.JobServiceError) -> None:
    raise HTTPException(
        status_code=err.http_status,
        detail={"code": err.code, "message": err.message},
    )


@router.post("/batches")
def create_batch(
    req: schemas.BatchCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        batch = job_service.create_batch(db, req, user=user)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok(job_service.to_batch_schema(batch).model_dump(mode="json"))


@router.get("/batches")
def list_batches(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        items = job_service.list_batches(db, user=user)
    except job_service.JobServiceError as err:
        _raise(err)
    payload = schemas.PaginatedBatchJobs(
        items=[job_service.to_batch_schema(item) for item in items],
        total=len(items),
    )
    return ok(payload.model_dump(mode="json"))


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        batch = job_service.get_batch(db, batch_id, user=user)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok(job_service.to_batch_schema(batch).model_dump(mode="json"))


@router.get("/batches/{batch_id}/jobs")
def get_batch_jobs(
    batch_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        batch = job_service.get_batch(db, batch_id, user=user)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok([job_service.to_job_schema(item).model_dump(mode="json") for item in batch.jobs])


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(
    batch_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        batch = job_service.cancel_batch(db, batch_id, user=user)
    except job_service.JobServiceError as err:
        _raise(err)
    return ok(job_service.to_batch_schema(batch).model_dump(mode="json"))
