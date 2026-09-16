"""Authenticated benchmark preregistration routes under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app import models
from app.api_idempotency import begin_mutation
from app.auth import get_current_user
from app.benchmarking import coordinator, service
from app.benchmarking.contracts import (
    BenchmarkBatchBindingRequestV1,
    BenchmarkBudgetReservationRequestV1,
    BenchmarkCampaignCreateRequest,
    BenchmarkCoordinatorClaimRequestV1,
    BenchmarkCoordinatorReleaseRequestV1,
    BenchmarkCoordinatorRenewRequestV1,
)
from app.db import get_db
from app.response import ok

router = APIRouter(tags=["benchmark-campaigns"])


def _raise(error: service.BenchmarkCampaignError) -> None:
    """Translate campaign ownership or preregistration failures into the API error contract."""
    raise HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": error.message},
    )


def _raise_coordinator(error: coordinator.BenchmarkCoordinatorError) -> None:
    """Preserve lease/budget rejection codes; callers must not treat a denial as a retry receipt."""
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
    """Bind a preregistered manifest and replay receipt without running trials."""
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
    """Read an owner-scoped page of campaigns without claiming coordinator authority."""
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
    """Authorize the requested campaign before exposing its manifest and bindings."""
    try:
        campaign = service.get_campaign(db, campaign_id, user=user)
    except service.BenchmarkCampaignError as error:
        _raise(error)
    return ok(service.to_record(campaign).model_dump(mode="json"))


@router.post("/benchmark-campaigns/{campaign_id}/coordinator/claim")
def claim_benchmark_coordinator(
    campaign_id: str,
    request: BenchmarkCoordinatorClaimRequestV1,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Commit a time-limited coordinator lease; the service fences conflicting owners."""
    try:
        lease = coordinator.claim_lease(
            db,
            campaign_id,
            user=user,
            owner_id=request.owner_id,
            lease_seconds=request.lease_seconds,
        )
        db.commit()
    except coordinator.BenchmarkCoordinatorError as error:
        db.rollback()
        _raise_coordinator(error)
    return ok(lease.model_dump(mode="json"))


@router.post("/benchmark-campaigns/{campaign_id}/coordinator/renew")
def renew_benchmark_coordinator(
    campaign_id: str,
    request: BenchmarkCoordinatorRenewRequestV1,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    lease_token: Annotated[
        str,
        Header(
            alias="X-Benchmark-Lease-Token",
            min_length=32,
            max_length=256,
        ),
    ],
) -> dict[str, object]:
    """Extend only the matching token/generation lease, never revive another owner's lease."""
    try:
        lease = coordinator.renew_lease(
            db,
            campaign_id,
            user=user,
            lease_token=lease_token,
            lease_generation=request.lease_generation,
            lease_seconds=request.lease_seconds,
        )
        db.commit()
    except coordinator.BenchmarkCoordinatorError as error:
        db.rollback()
        _raise_coordinator(error)
    return ok(lease.model_dump(mode="json"))


@router.post("/benchmark-campaigns/{campaign_id}/coordinator/release")
def release_benchmark_coordinator(
    campaign_id: str,
    request: BenchmarkCoordinatorReleaseRequestV1,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    lease_token: Annotated[
        str,
        Header(
            alias="X-Benchmark-Lease-Token",
            min_length=32,
            max_length=256,
        ),
    ],
) -> dict[str, object]:
    """Release the presented lease generation and return usage, not permission to run new work."""
    try:
        usage = coordinator.release_lease(
            db,
            campaign_id,
            user=user,
            lease_token=lease_token,
            lease_generation=request.lease_generation,
        )
        db.commit()
    except coordinator.BenchmarkCoordinatorError as error:
        db.rollback()
        _raise_coordinator(error)
    return ok(usage.model_dump(mode="json"))


@router.post("/benchmark-campaigns/{campaign_id}/budget-reservations")
def reserve_benchmark_budget(
    campaign_id: str,
    request: BenchmarkBudgetReservationRequestV1,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    lease_token: Annotated[
        str,
        Header(
            alias="X-Benchmark-Lease-Token",
            min_length=32,
            max_length=256,
        ),
    ],
) -> dict[str, object]:
    """Reserve under a valid lease and commit before dispatch; reservation is not actual spend."""
    try:
        reservation = coordinator.reserve_budget(
            db,
            campaign_id,
            request,
            user=user,
            lease_token=lease_token,
        )
        db.commit()
    except coordinator.BenchmarkCoordinatorError as error:
        db.rollback()
        _raise_coordinator(error)
    return ok(reservation.model_dump(mode="json"))


@router.get("/benchmark-campaigns/{campaign_id}/usage")
def get_benchmark_campaign_usage(
    campaign_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Read server-accounted budget state without trusting client-reported trial totals."""
    try:
        usage = coordinator.get_usage(db, campaign_id, user=user)
    except coordinator.BenchmarkCoordinatorError as error:
        _raise_coordinator(error)
    return ok(usage.model_dump(mode="json"))


@router.post("/benchmark-campaigns/{campaign_id}/batch-bindings")
def bind_benchmark_batch(
    campaign_id: str,
    request: BenchmarkBatchBindingRequestV1,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    lease_token: Annotated[
        str,
        Header(
            alias="X-Benchmark-Lease-Token",
            min_length=32,
            max_length=256,
        ),
    ],
) -> dict[str, object]:
    """Attach an owned batch to its reserved benchmark slot under the active coordinator lease."""
    try:
        binding = coordinator.bind_batch(
            db,
            campaign_id,
            request,
            user=user,
            lease_token=lease_token,
        )
        db.commit()
    except coordinator.BenchmarkCoordinatorError as error:
        db.rollback()
        _raise_coordinator(error)
    return ok(binding.model_dump(mode="json"))


@router.get("/benchmark-campaigns/{campaign_id}/batch-bindings")
def list_benchmark_batch_bindings(
    campaign_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Return persisted bindings for this owner; missing bindings are not completed trials."""
    try:
        bindings = coordinator.list_batch_bindings(db, campaign_id, user=user)
    except coordinator.BenchmarkCoordinatorError as error:
        _raise_coordinator(error)
    return ok([binding.model_dump(mode="json") for binding in bindings])
