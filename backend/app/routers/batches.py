"""Batch job routes under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.api_idempotency import begin_mutation
from app.auth import get_current_user
from app.db import get_db
from app.response import ok
from app.services import jobs as job_service

router = APIRouter(tags=["batches"])

_PageQ = Query(1, ge=1)
_PageSizeQ = Query(100, ge=1, le=200)


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
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    gate = begin_mutation(
        db,
        user=user,
        operation="batches.create",
        idempotency_key=idempotency_key,
        payload=req.model_dump(mode="json"),
    )
    if gate.replay is not None:
        return gate.replay
    try:
        batch = job_service.create_batch(db, req, user=user, commit=False)
    except job_service.JobServiceError as err:
        db.rollback()
        _raise(err)
    response = ok(job_service.to_batch_schema(batch).model_dump(mode="json"))
    return gate.complete(response, resource_type="batch", resource_id=batch.id)


@router.get("/batches")
def list_batches(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    page: int = _PageQ,
    page_size: int = _PageSizeQ,
) -> dict[str, object]:
    try:
        items, total = job_service.list_batches(
            db,
            user=user,
            page=page,
            page_size=page_size,
        )
    except job_service.JobServiceError as err:
        _raise(err)
    payload = schemas.PaginatedBatchJobs(
        items=[job_service.to_batch_schema(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
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
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    control_version: Annotated[
        int | None,
        Query(alias="control_version", ge=1),
    ] = None,
) -> dict[str, object]:
    gate = begin_mutation(
        db,
        user=user,
        operation="batches.cancel",
        idempotency_key=idempotency_key,
        payload={"batch_id": batch_id, "control_version": control_version},
    )
    if gate.replay is not None:
        return gate.replay
    try:
        batch = job_service.cancel_batch(
            db,
            batch_id,
            user=user,
            commit=False,
            expected_control_version=control_version,
        )
    except job_service.JobServiceError as err:
        db.rollback()
        _raise(err)
    response = ok(job_service.to_batch_schema(batch).model_dump(mode="json"))
    return gate.complete(response, resource_type="batch", resource_id=batch.id)
