"""Launch-bound authentication for the packaged desktop API bridge.

OIDC authenticates the cloud account. This layer separately proves that the
request was forwarded by the current DroneDream desktop process to the signed
Runtime, and consumes every nonce durably before route code runs.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from starlette.responses import JSONResponse, Response

from app import models
from app.config import Settings
from app.db import SessionLocal
from app.response import err
from app.secrets import SecretStoreError, validate_secret_material

_VERSION = "DD-BRIDGE-V2"
_DERIVATION_LABEL = b"dronedream-desktop-bridge-v2"
_MAX_BODY_BYTES = 25 * 1024 * 1024


def _rejection(code: str, message: str, status: int = 401) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=err(code=code, message=message),
    )


def _canonical_uuid(raw: str | None) -> str | None:
    if raw is None or len(raw) != 36:
        return None
    try:
        canonical = str(UUID(raw))
    except ValueError:
        return None
    return canonical if canonical == raw.lower() else None


def _bridge_key() -> bytes:
    app_secret = os.environ.get("APP_SECRET_KEY") or os.environ.get(
        "DRONEDREAM_SECRET_KEY"
    )
    if app_secret is None or len(app_secret.encode("utf-8")) < 32:
        raise RuntimeError("desktop bridge secret material is unavailable")
    try:
        validate_secret_material(app_secret)
    except SecretStoreError as exc:
        raise RuntimeError("desktop bridge secret material is invalid") from exc
    return hmac.new(
        app_secret.encode("utf-8"),
        _DERIVATION_LABEL,
        hashlib.sha256,
    ).digest()


def _canonical_request(
    *,
    runtime_id: str,
    session_id: str,
    timestamp: str,
    nonce: str,
    method: str,
    path_query: str,
    body_sha256: str,
    authorization_sha256: str,
    idempotency_key: str,
) -> bytes:
    return (
        "\n".join(
            (
                _VERSION,
                runtime_id,
                session_id,
                timestamp,
                nonce,
                method,
                path_query,
                body_sha256,
                authorization_sha256,
                idempotency_key,
                "",
            )
        )
    ).encode("utf-8")


def _consume_nonce(
    *,
    nonce: str,
    session_id: str,
    runtime_id: str,
    request_hash: str,
    now: datetime,
    retention_seconds: int,
) -> bool:
    expires_at = now + timedelta(seconds=retention_seconds)
    with SessionLocal() as db:
        # Bounded opportunistic cleanup keeps the local table finite without
        # weakening the active timestamp window.
        db.execute(delete(models.DesktopBridgeNonce).where(
            models.DesktopBridgeNonce.expires_at < now
        ))
        db.add(
            models.DesktopBridgeNonce(
                nonce=nonce,
                session_id=session_id,
                runtime_id=runtime_id,
                request_hash=request_hash,
                expires_at=expires_at,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
    return True


async def enforce_desktop_bridge(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    settings: Settings,
) -> Response:
    """Verify and consume a packaged-desktop request proof."""

    if not settings.desktop_bridge_required or not request.url.path.startswith(
        "/api/v1/"
    ):
        return await call_next(request)

    if request.headers.get("X-DroneDream-Bridge-Version") != _VERSION:
        return _rejection(
            "DESKTOP_BRIDGE_REQUIRED",
            "This Runtime accepts API requests only through DroneDream Desktop.",
        )

    runtime_id = _canonical_uuid(request.headers.get("X-DroneDream-Runtime-Id"))
    session_id = _canonical_uuid(request.headers.get("X-DroneDream-Session-Id"))
    nonce = _canonical_uuid(request.headers.get("X-DroneDream-Nonce"))
    if runtime_id is None or runtime_id != settings.dronedream_runtime_id:
        return _rejection(
            "DESKTOP_BRIDGE_RUNTIME_MISMATCH",
            "The desktop request belongs to a different Runtime.",
        )
    if session_id is None or nonce is None:
        return _rejection(
            "DESKTOP_BRIDGE_INVALID_PROOF",
            "The desktop request proof is malformed.",
        )

    timestamp = request.headers.get("X-DroneDream-Timestamp", "")
    try:
        issued_at = int(timestamp)
    except ValueError:
        return _rejection(
            "DESKTOP_BRIDGE_INVALID_PROOF",
            "The desktop request timestamp is malformed.",
        )
    if abs(int(time.time()) - issued_at) > settings.desktop_bridge_clock_skew_seconds:
        return _rejection(
            "DESKTOP_BRIDGE_EXPIRED",
            "The desktop request proof has expired.",
        )

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return _rejection(
            "DESKTOP_BRIDGE_BODY_TOO_LARGE",
            "The desktop request body exceeds the bridge limit.",
            status=413,
        )
    body_sha256 = hashlib.sha256(body).hexdigest()
    supplied_body_sha256 = request.headers.get("X-DroneDream-Body-Sha256", "")
    if not hmac.compare_digest(body_sha256, supplied_body_sha256):
        return _rejection(
            "DESKTOP_BRIDGE_BODY_MISMATCH",
            "The desktop request body does not match its proof.",
        )

    authorization = request.headers.get("Authorization", "")
    authorization_sha256 = hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    raw_idempotency_key = request.headers.get("Idempotency-Key", "")
    if raw_idempotency_key:
        parsed_idempotency_key = _canonical_uuid(raw_idempotency_key)
        if parsed_idempotency_key is None:
            return _rejection(
                "DESKTOP_BRIDGE_INVALID_PROOF",
                "The desktop idempotency key is malformed.",
            )
        idempotency_key = parsed_idempotency_key
    else:
        idempotency_key = ""
    raw_path = request.scope.get("raw_path")
    path_query = (
        bytes(raw_path).decode("ascii")
        if isinstance(raw_path, bytes)
        else request.url.path
    )
    raw_query = request.scope.get("query_string")
    if isinstance(raw_query, bytes) and raw_query:
        path_query += f"?{raw_query.decode('ascii')}"
    canonical = _canonical_request(
        runtime_id=runtime_id,
        session_id=session_id,
        timestamp=timestamp,
        nonce=nonce,
        method=request.method.upper(),
        path_query=path_query,
        body_sha256=body_sha256,
        authorization_sha256=authorization_sha256,
        idempotency_key=idempotency_key,
    )
    try:
        expected = hmac.new(_bridge_key(), canonical, hashlib.sha256).hexdigest()
    except RuntimeError:
        return _rejection(
            "DESKTOP_BRIDGE_CONFIGURATION_ERROR",
            "The Runtime desktop bridge is not configured.",
            status=500,
        )
    supplied = request.headers.get("X-DroneDream-Signature", "")
    if len(supplied) != 64 or not hmac.compare_digest(expected, supplied):
        return _rejection(
            "DESKTOP_BRIDGE_INVALID_PROOF",
            "The desktop request proof is invalid.",
        )

    request_hash = hashlib.sha256(canonical).hexdigest()
    if not _consume_nonce(
        nonce=nonce,
        session_id=session_id,
        runtime_id=runtime_id,
        request_hash=request_hash,
        now=datetime.now(timezone.utc),
        retention_seconds=settings.desktop_bridge_nonce_retention_seconds,
    ):
        return _rejection(
            "DESKTOP_BRIDGE_REPLAY",
            "This desktop request proof has already been used.",
            status=409,
        )

    return await call_next(request)
