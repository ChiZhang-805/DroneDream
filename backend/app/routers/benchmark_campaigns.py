"""Authenticated benchmark preregistration routes under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app import models
from app.api_idempotency import begin_mutation
from app.auth import get_current_user
from app.benchmarking import service
from app.benchmarking.contracts import BenchmarkCampaignCreateRequest
from app.db import get_db
from app.response import ok

router = APIRouter(tags=["benchmark-campaigns"])


def _raise(error: service.BenchmarkCampaignError) -> None:
    raise HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": error.message},
    )


@router.post("/benchmark-campaigns")
def create_benchmark_campaign(
    request: BenchmarkCampaignCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    gate = begin_mutation(
        db,
        user=user,
        operation="benchmark-campaigns.create",
        idempotency_key=idempotency_key,
        payload=request.model_dump(mode="json"),
    )
    if gate.replay is not None:
        return gate.replay
    try:
        campaign = service.create_campaign(db, request.manifest, user=user)
    except service.BenchmarkCampaignError as error:
        db.rollback()
        _raise(error)
    response = ok(service.to_record(campaign).model_dump(mode="json"))
    return gate.complete(
        response,
        resource_type="benchmark_campaign",
        resource_id=campaign.id,
    )


@router.get("/benchmark-campaigns")
def list_benchmark_campaigns(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, object]:
    campaigns, total = service.list_campaigns(
        db,
        user=user,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [service.to_record(item).model_dump(mode="json") for item in campaigns],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


@router.get("/benchmark-campaigns/{campaign_id}")
def get_benchmark_campaign(
    campaign_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        campaign = service.get_campaign(db, campaign_id, user=user)
    except service.BenchmarkCampaignError as error:
        _raise(error)
    return ok(service.to_record(campaign).model_dump(mode="json"))
