"""Liveness and dependency-aware readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.response import ok
from app.storage import get_artifact_storage

router = APIRouter(tags=["health"])


def _runtime_id() -> str | None:
    # Some test and worker bootstrap paths reload app.config after changing the
    # environment. Import lazily so readiness never retains a stale cached
    # get_settings function from the previous module state.
    from app.config import get_settings

    return get_settings().dronedream_runtime_id


@router.get("/health")
def health() -> dict[str, object]:
    """Return a simple liveness payload in the standard envelope."""

    return ok(
        {
            "status": "ok",
            "service": "drone-dream-backend",
            "version": __version__,
            "runtime_id": _runtime_id(),
        }
    )


@router.get("/health/live")
def live() -> dict[str, object]:
    """Process liveness; intentionally avoids external dependencies."""

    return health()


def _database_health() -> dict[str, object]:
    try:
        # Import dynamically so isolated tests that reload app.db use the
        # current engine instead of a module-import-time reference.
        from app.db import engine

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"ok": True, "status": "available"}
    except Exception as exc:
        return {"ok": False, "status": "unavailable", "detail": type(exc).__name__}


def _storage_health() -> dict[str, object]:
    try:
        storage = get_artifact_storage()
        storage.check_health()
        return {"ok": True, "status": "available"}
    except Exception as exc:
        return {"ok": False, "status": "unavailable", "detail": type(exc).__name__}


@router.get("/health/ready", response_model=None)
def ready() -> dict[str, object] | JSONResponse:
    """Check database, artifact storage, and worker-presence dependencies."""

    from app.orchestration.worker_presence import worker_presence_health

    components = {
        "database": _database_health(),
        "storage": _storage_health(),
        "worker": worker_presence_health(),
    }
    is_ready = all(bool(component.get("ok")) for component in components.values())
    payload = ok(
        {
            "status": "ready" if is_ready else "not_ready",
            "service": "drone-dream-backend",
            "version": __version__,
            "runtime_id": _runtime_id(),
            "components": components,
        }
    )
    if is_ready:
        return payload
    return JSONResponse(status_code=503, content=payload)
