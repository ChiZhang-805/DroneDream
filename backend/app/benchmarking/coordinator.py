"""Fenced, idempotent accounting for benchmark campaigns spanning many Batches."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.benchmarking import service
from app.benchmarking.contracts import (
    BenchmarkBudgetCapsV1,
    BenchmarkBudgetReservationRecordV1,
    BenchmarkBudgetReservationRequestV1,
    BenchmarkCampaignUsageV1,
    BenchmarkCoordinatorLeaseV1,
    BenchmarkResourceVectorV1,
    BenchmarkUsageDeltaV1,
    canonical_sha256,
)


class BenchmarkCoordinatorError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


_RESOURCE_FIELDS = {
    "jobs": ("jobs_used", "job_cap"),
    "trials": ("trials_used", "trial_cap"),
    "logical_turns": ("logical_turns_used", "logical_turn_cap"),
    "network_requests": ("network_requests_used", "network_request_cap"),
    "input_utf8_bytes": ("input_utf8_bytes_used", "input_utf8_byte_cap"),
    "output_utf8_bytes": ("output_utf8_bytes_used", "output_utf8_byte_cap"),
    "provider_tokens": ("provider_tokens_used", "provider_token_cap"),
    "provider_cost_microusd": (
        "provider_cost_microusd_used",
        "provider_cost_microusd_cap",
    ),
    "wall_time_seconds": ("wall_time_seconds_used", "wall_time_second_cap"),
    "disk_bytes": ("disk_bytes_used", "disk_byte_cap"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    if not 32 <= len(token) <= 256:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_TOKEN_INVALID",
            "Benchmark coordinator lease token is malformed.",
            http_status=409,
        )
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _campaign(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
) -> models.BenchmarkCampaign:
    try:
        return service.get_campaign(db, campaign_id, user=user)
    except service.BenchmarkCampaignError as error:
        raise BenchmarkCoordinatorError(
            error.code,
            error.message,
            http_status=error.http_status,
        ) from error


def _coordinator_state(
    db: Session,
    campaign: models.BenchmarkCampaign,
) -> models.BenchmarkCampaignCoordinatorState:
    state = db.get(models.BenchmarkCampaignCoordinatorState, campaign.id)
    if state is None:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_STATE_MISSING",
            "Campaign coordinator state is missing; run the current database migration.",
            http_status=500,
        )
    return state


def claim_lease(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
    owner_id: str,
    lease_seconds: int,
) -> BenchmarkCoordinatorLeaseV1:
    campaign = _campaign(db, campaign_id, user=user)
    if campaign.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise BenchmarkCoordinatorError(
            "BENCHMARK_CAMPAIGN_TERMINAL",
            "A terminal benchmark campaign cannot acquire a coordinator lease.",
            http_status=409,
        )
    state = _coordinator_state(db, campaign)
    now = _now()
    expires_at = now + timedelta(seconds=lease_seconds)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _token_hash(raw_token)
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            or_(
                models.BenchmarkCampaignCoordinatorState.lease_token_hash.is_(None),
                models.BenchmarkCampaignCoordinatorState.lease_expires_at.is_(None),
                models.BenchmarkCampaignCoordinatorState.lease_expires_at <= now,
            ),
        )
        .values(
            lease_owner=owner_id,
            lease_token_hash=token_hash,
            lease_generation=(
                models.BenchmarkCampaignCoordinatorState.lease_generation + 1
            ),
            lease_expires_at=expires_at,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_LEASE_HELD",
            "Another coordinator holds the unexpired campaign lease.",
            http_status=409,
        )
    db.flush()
    db.refresh(state)
    return BenchmarkCoordinatorLeaseV1(
        campaign_id=campaign.id,
        owner_id=owner_id,
        lease_token=raw_token,
        lease_generation=state.lease_generation,
        lease_expires_at=expires_at,
    )


def renew_lease(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
    lease_token: str,
    lease_generation: int,
    lease_seconds: int,
) -> BenchmarkCoordinatorLeaseV1:
    campaign = _campaign(db, campaign_id, user=user)
    state = _coordinator_state(db, campaign)
    now = _now()
    expires_at = now + timedelta(seconds=lease_seconds)
    token_hash = _token_hash(lease_token)
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            models.BenchmarkCampaignCoordinatorState.lease_token_hash == token_hash,
            models.BenchmarkCampaignCoordinatorState.lease_generation == lease_generation,
            models.BenchmarkCampaignCoordinatorState.lease_expires_at > now,
        )
        .values(lease_expires_at=expires_at, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_FENCE_REJECTED",
            "Coordinator lease is expired, stale, or does not match this campaign.",
            http_status=409,
        )
    db.flush()
    db.refresh(state)
    return BenchmarkCoordinatorLeaseV1(
        campaign_id=campaign.id,
        owner_id=state.lease_owner or "unknown",
        lease_token=lease_token,
        lease_generation=lease_generation,
        lease_expires_at=expires_at,
    )


def release_lease(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
    lease_token: str,
    lease_generation: int,
) -> BenchmarkCampaignUsageV1:
    campaign = _campaign(db, campaign_id, user=user)
    state = _coordinator_state(db, campaign)
    now = _now()
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(
            models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
            models.BenchmarkCampaignCoordinatorState.lease_token_hash
            == _token_hash(lease_token),
            models.BenchmarkCampaignCoordinatorState.lease_generation == lease_generation,
        )
        .values(
            lease_owner=None,
            lease_token_hash=None,
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise BenchmarkCoordinatorError(
            "BENCHMARK_COORDINATOR_FENCE_REJECTED",
            "Coordinator lease is stale or does not match this campaign.",
            http_status=409,
        )
    db.flush()
    db.refresh(state)
    return to_usage(campaign, state)


def reserve_budget(
    db: Session,
    campaign_id: str,
    request: BenchmarkBudgetReservationRequestV1,
    *,
    user: models.User,
    lease_token: str,
) -> BenchmarkBudgetReservationRecordV1:
    campaign = _campaign(db, campaign_id, user=user)
    campaign_id_value = campaign.id
    request_payload = request.model_dump(mode="json", exclude_none=False)
    request_sha256 = canonical_sha256(request_payload)
    existing = db.scalar(
        select(models.BenchmarkBudgetReservation).where(
            models.BenchmarkBudgetReservation.campaign_id == campaign_id_value,
            models.BenchmarkBudgetReservation.reservation_key == request.reservation_key,
        )
    )
    if existing is not None:
        if existing.reservation_sha256 == request_sha256:
            return to_reservation_record(existing)
        raise BenchmarkCoordinatorError(
            "BENCHMARK_RESERVATION_KEY_CONFLICT",
            "reservation_key is already bound to a different immutable usage delta.",
            http_status=409,
        )
    if campaign.status != "ACTIVE":
        raise BenchmarkCoordinatorError(
            "BENCHMARK_CAMPAIGN_NOT_ACTIVE",
            "Budget can only be consumed by an ACTIVE benchmark campaign.",
            http_status=409,
        )

    state = _coordinator_state(db, campaign)
    now = _now()
    token_hash = _token_hash(lease_token)
    usage = request.usage.model_dump()
    conditions: list[Any] = [
        models.BenchmarkCampaignCoordinatorState.campaign_id == campaign.id,
        models.BenchmarkCampaignCoordinatorState.lease_token_hash == token_hash,
        models.BenchmarkCampaignCoordinatorState.lease_generation
        == request.lease_generation,
        models.BenchmarkCampaignCoordinatorState.lease_expires_at > now,
    ]
    values: dict[str, Any] = {"updated_at": now}
    for resource, (used_field, cap_field) in _RESOURCE_FIELDS.items():
        delta = int(usage[resource])
        used_column = getattr(models.BenchmarkCampaignCoordinatorState, used_field)
        cap = int(getattr(campaign, cap_field))
        conditions.append(used_column + delta <= cap)
        values[used_field] = used_column + delta
    statement = (
        update(models.BenchmarkCampaignCoordinatorState)
        .where(and_(*conditions))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = db.execute(statement)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        db.refresh(state)
        lease_is_current = (
            state.lease_token_hash == token_hash
            and state.lease_generation == request.lease_generation
            and state.lease_expires_at is not None
            and _as_utc(state.lease_expires_at) > now
        )
        if not lease_is_current:
            raise BenchmarkCoordinatorError(
                "BENCHMARK_COORDINATOR_FENCE_REJECTED",
                "Coordinator lease is expired, stale, or does not match this campaign.",
                http_status=409,
            )
        raise BenchmarkCoordinatorError(
            "BENCHMARK_CAMPAIGN_CAP_EXCEEDED",
            "The requested work would exceed one or more frozen campaign caps.",
            http_status=409,
        )

    reservation = models.BenchmarkBudgetReservation(
        campaign_id=campaign_id_value,
        reservation_key=request.reservation_key,
        lease_generation=request.lease_generation,
        reason=request.reason,
        reservation_sha256=request_sha256,
        **usage,
    )
    db.add(reservation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        replay = db.scalar(
            select(models.BenchmarkBudgetReservation).where(
                models.BenchmarkBudgetReservation.campaign_id == campaign_id_value,
                models.BenchmarkBudgetReservation.reservation_key
                == request.reservation_key,
            )
        )
        if replay is not None and replay.reservation_sha256 == request_sha256:
            return to_reservation_record(replay)
        raise BenchmarkCoordinatorError(
            "BENCHMARK_RESERVATION_KEY_CONFLICT",
            "Concurrent reservation used the same key with a different payload.",
            http_status=409,
        ) from None
    return to_reservation_record(reservation)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_usage(
    db: Session,
    campaign_id: str,
    *,
    user: models.User,
) -> BenchmarkCampaignUsageV1:
    campaign = _campaign(db, campaign_id, user=user)
    return to_usage(campaign, _coordinator_state(db, campaign))


def _resource_vector(
    campaign: models.BenchmarkCampaign,
    state: models.BenchmarkCampaignCoordinatorState,
) -> tuple[BenchmarkResourceVectorV1, BenchmarkResourceVectorV1]:
    used_payload: dict[str, int] = {}
    remaining_payload: dict[str, int] = {}
    for resource, (used_field, cap_field) in _RESOURCE_FIELDS.items():
        used_value = int(getattr(state, used_field))
        cap_value = int(getattr(campaign, cap_field))
        used_payload[resource] = used_value
        remaining_payload[resource] = max(0, cap_value - used_value)
    return (
        BenchmarkResourceVectorV1(**used_payload),
        BenchmarkResourceVectorV1(**remaining_payload),
    )


def to_usage(
    campaign: models.BenchmarkCampaign,
    state: models.BenchmarkCampaignCoordinatorState,
) -> BenchmarkCampaignUsageV1:
    used, remaining = _resource_vector(campaign, state)
    caps = BenchmarkBudgetCapsV1(
        jobs=campaign.job_cap,
        trials=campaign.trial_cap,
        logical_turns=campaign.logical_turn_cap,
        network_requests=campaign.network_request_cap,
        input_utf8_bytes=campaign.input_utf8_byte_cap,
        output_utf8_bytes=campaign.output_utf8_byte_cap,
        provider_tokens=campaign.provider_token_cap,
        provider_cost_microusd=campaign.provider_cost_microusd_cap,
        wall_time_seconds=campaign.wall_time_second_cap,
        disk_bytes=campaign.disk_byte_cap,
    )
    return BenchmarkCampaignUsageV1(
        campaign_id=campaign.id,
        status=campaign.status,  # type: ignore[arg-type]
        caps=caps,
        used=used,
        remaining=remaining,
        lease_owner=state.lease_owner,
        lease_generation=state.lease_generation,
        lease_expires_at=state.lease_expires_at,
    )


def to_reservation_record(
    reservation: models.BenchmarkBudgetReservation,
) -> BenchmarkBudgetReservationRecordV1:
    return BenchmarkBudgetReservationRecordV1(
        id=reservation.id,
        campaign_id=reservation.campaign_id,
        reservation_key=reservation.reservation_key,
        lease_generation=reservation.lease_generation,
        reason=reservation.reason,
        reservation_sha256=reservation.reservation_sha256,
        usage=BenchmarkUsageDeltaV1(
            jobs=reservation.jobs,
            trials=reservation.trials,
            logical_turns=reservation.logical_turns,
            network_requests=reservation.network_requests,
            input_utf8_bytes=reservation.input_utf8_bytes,
            output_utf8_bytes=reservation.output_utf8_bytes,
            provider_tokens=reservation.provider_tokens,
            provider_cost_microusd=reservation.provider_cost_microusd,
            wall_time_seconds=reservation.wall_time_seconds,
            disk_bytes=reservation.disk_bytes,
        ),
        created_at=reservation.created_at,
    )


__all__ = [
    "BenchmarkCoordinatorError",
    "claim_lease",
    "get_usage",
    "release_lease",
    "renew_lease",
    "reserve_budget",
    "to_reservation_record",
    "to_usage",
]
