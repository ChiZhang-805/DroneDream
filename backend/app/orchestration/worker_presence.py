"""Cross-process worker presence heartbeats backed by Redis/Valkey."""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("drone_dream.orchestration.worker_presence")
_MAX_HEARTBEAT_BYTES = 4096


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings() -> Any:
    # Several test/development workflows reload app.config after changing the
    # environment. Resolve it lazily so this long-lived module never holds a
    # stale cached get_settings function.
    from app.config import get_settings

    return get_settings()


def _client() -> Any:
    settings = _settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is not configured")
    try:
        import redis
    except ModuleNotFoundError as exc:  # pragma: no cover - packaging guard.
        raise RuntimeError("redis package is required when REDIS_URL is configured") from exc
    return redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )


def _validated_worker_id(worker_id: object) -> str:
    if not isinstance(worker_id, str):
        raise ValueError("worker_id must be a string")
    normalized = worker_id.strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError("worker_id must be 1-128 visible characters")
    return normalized


def publish_worker_heartbeat(worker_id: str) -> bool:
    """Publish one expiring worker-presence signal without crashing work."""

    worker_id = _validated_worker_id(worker_id)
    settings = _settings()
    if not settings.redis_url:
        return False
    now = _now()
    payload = json.dumps(
        {
            "worker_id": worker_id,
            "observed_at": now.isoformat(),
            "observed_at_epoch": now.timestamp(),
        },
        separators=(",", ":"),
    )
    try:
        _client().set(
            settings.worker_presence_key,
            payload,
            ex=settings.worker_presence_ttl_seconds,
        )
        return True
    except Exception:
        logger.warning("failed to publish worker heartbeat", exc_info=True)
        return False


def worker_presence_health() -> dict[str, object]:
    """Return a readiness component for Redis and the latest worker signal."""

    settings = _settings()
    if not settings.redis_url:
        if settings.require_worker_heartbeat:
            return {
                "ok": False,
                "status": "not_configured",
                "detail": "REDIS_URL is required for worker heartbeat checks",
            }
        return {"ok": True, "status": "not_required"}
    try:
        client = _client()
        client.ping()
        raw = client.getrange(
            settings.worker_presence_key,
            0,
            _MAX_HEARTBEAT_BYTES,
        )
        if not raw:
            return {"ok": False, "status": "missing", "detail": "no live worker signal"}
        if (
            not isinstance(raw, str)
            or len(raw.encode("utf-8")) > _MAX_HEARTBEAT_BYTES
        ):
            return {
                "ok": False,
                "status": "invalid",
                "detail": "worker signal exceeds the supported size",
            }
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "status": "invalid",
                "detail": "worker signal must be a JSON object",
            }
        raw_epoch = payload.get("observed_at_epoch")
        raw_worker_id = payload.get("worker_id")
        if isinstance(raw_epoch, bool) or not isinstance(raw_epoch, int | float):
            return {
                "ok": False,
                "status": "invalid",
                "detail": "worker signal observation time must be numeric",
            }
        observed_epoch = float(raw_epoch)
        try:
            worker_id = _validated_worker_id(raw_worker_id)
        except ValueError:
            return {
                "ok": False,
                "status": "invalid",
                "detail": "worker signal has an invalid worker id",
            }
        now_epoch = _now().timestamp()
        if not math.isfinite(observed_epoch) or observed_epoch > now_epoch + 5.0:
            return {
                "ok": False,
                "status": "invalid",
                "detail": "worker signal has an invalid observation time",
            }
        age = max(0.0, now_epoch - observed_epoch)
        if age > settings.worker_presence_ttl_seconds:
            return {
                "ok": False,
                "status": "stale",
                "age_seconds": round(age, 3),
            }
        return {
            "ok": True,
            "status": "available",
            "worker_id": worker_id,
            "age_seconds": round(age, 3),
        }
    except Exception as exc:
        logger.warning(
            "worker presence health check failed exception_type=%s",
            type(exc).__name__,
        )
        return {
            "ok": False,
            "status": "unavailable",
            "detail": type(exc).__name__,
        }


class WorkerPresenceHeartbeat:
    """Background signal that remains live while a long trial is executing."""

    def __init__(self, worker_id: str) -> None:
        self._worker_id = _validated_worker_id(worker_id)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"worker-presence-{worker_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        settings = _settings()
        publish_worker_heartbeat(self._worker_id)
        while not self._stop.wait(settings.worker_presence_interval_seconds):
            publish_worker_heartbeat(self._worker_id)


__all__ = [
    "WorkerPresenceHeartbeat",
    "publish_worker_heartbeat",
    "worker_presence_health",
]
