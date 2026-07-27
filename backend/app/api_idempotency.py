"""Persistent, transaction-bound idempotency for business mutations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings


def _canonical_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    candidate = raw.strip().lower()
    if len(candidate) != 36:
        return None
    try:
        parsed = str(UUID(candidate))
    except ValueError:
        return None
    return parsed if parsed == candidate else None


def _request_hash(operation: str, payload: object) -> str:
    canonical = json.dumps(
        {"operation": operation, "payload": payload},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@dataclass
class MutationGate:
    """One mutation transaction, or a completed response to replay."""

    db: Session
    record: models.ApiIdempotencyRecord | None
    replay: dict[str, Any] | None = None

    def complete(
        self,
        response: dict[str, Any],
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        response_status: int = 200,
    ) -> dict[str, Any]:
        if self.replay is not None:
            return self.replay
        if self.record is not None:
            self.record.status = "COMPLETED"
            self.record.response_status = response_status
            self.record.response_json = response
            self.record.resource_type = resource_type
            self.record.resource_id = resource_id
            self.record.completed_at = datetime.now(timezone.utc)
        # The domain mutation and its replay receipt become visible together.
        self.db.commit()
        return response


def begin_mutation(
    db: Session,
    *,
    user: models.User,
    operation: str,
    idempotency_key: str | None,
    payload: object,
) -> MutationGate:
    """Claim one user action before executing its domain mutation.

    In packaged desktop production a canonical UUID key is mandatory. Tests
    and non-desktop development remain backward compatible when the header is
    absent, but still receive one atomic transaction boundary.
    """

    key = _canonical_key(idempotency_key)
    if idempotency_key is None:
        settings = get_settings()
        if settings.app_env.strip().lower() in {"desktop", "prod", "production"}:
            raise _http_error(
                428,
                "IDEMPOTENCY_KEY_REQUIRED",
                "A stable Idempotency-Key is required for this protected action.",
            )
        return MutationGate(db=db, record=None)
    if key is None:
        raise _http_error(
            422,
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be a canonical UUID.",
        )
    if not user.id:
        raise _http_error(
            500,
            "IDEMPOTENCY_IDENTITY_UNAVAILABLE",
            "The authenticated user identity is unavailable.",
        )

    digest = _request_hash(operation, payload)
    key_hash = hashlib.sha256(key.encode("ascii")).hexdigest()
    record = models.ApiIdempotencyRecord(
        user_id=user.id,
        idempotency_key_hash=key_hash,
        operation=operation,
        request_hash=digest,
    )
    db.add(record)
    try:
        db.flush()
        return MutationGate(db=db, record=record)
    except IntegrityError:
        # The competing transaction has either completed (and can be replayed)
        # or owns the same key with different semantics. PostgreSQL's unique
        # check waits for that transaction before raising this conflict.
        db.rollback()

    existing = db.scalar(
        select(models.ApiIdempotencyRecord).where(
            models.ApiIdempotencyRecord.user_id == user.id,
            models.ApiIdempotencyRecord.idempotency_key_hash == key_hash,
        )
    )
    if existing is None:
        raise _http_error(
            409,
            "IDEMPOTENCY_REQUEST_IN_PROGRESS",
            "The original action is still being resolved; retry with the same key.",
        )
    if existing.operation != operation or existing.request_hash != digest:
        raise _http_error(
            409,
            "IDEMPOTENCY_CONFLICT",
            "This Idempotency-Key was already used for a different request.",
        )
    if existing.status != "COMPLETED" or existing.response_json is None:
        raise _http_error(
            409,
            "IDEMPOTENCY_REQUEST_IN_PROGRESS",
            "The original action has not reached a replayable terminal response.",
        )
    return MutationGate(
        db=db,
        record=None,
        replay=dict(existing.response_json),
    )


__all__ = ["MutationGate", "begin_mutation"]
