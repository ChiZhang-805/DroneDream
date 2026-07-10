"""Cross-process worker presence heartbeats backed by Redis/Valkey."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("drone_dream.orchestration.worker_presence")


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


def publish_worker_heartbeat(worker_id: str) -> bool:
    """Publish one expiring worker-presence signal without crashing work."""

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
        raw = client.get(settings.worker_presence_key)
        if not raw:
            return {"ok": False, "status": "missing", "detail": "no live worker signal"}
        payload = json.loads(raw)
        observed_epoch = float(payload["observed_at_epoch"])
        age = max(0.0, _now().timestamp() - observed_epoch)
        if age > settings.worker_presence_ttl_seconds:
            return {
                "ok": False,
                "status": "stale",
                "age_seconds": round(age, 3),
            }
        return {
            "ok": True,
            "status": "available",
            "worker_id": str(payload.get("worker_id", "unknown")),
            "age_seconds": round(age, 3),
        }
    except Exception as exc:
        return {"ok": False, "status": "unavailable", "detail": str(exc)[:200]}


class WorkerPresenceHeartbeat:
    """Background signal that remains live while a long trial is executing."""

    def __init__(self, worker_id: str) -> None:
        self._worker_id = worker_id
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
