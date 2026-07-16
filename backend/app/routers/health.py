"""Liveness and dependency-aware readiness probes."""

from __future__ import annotations

import os
from pathlib import Path

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


def _runtime_executable_health(
    configured_path: str | None,
    *,
    component: str,
    environment_name: str,
) -> dict[str, object]:
    """Verify one packaged-runtime executable without launching it."""

    if not configured_path or not configured_path.strip():
        return {
            "ok": False,
            "status": "not_configured",
            "detail": f"{environment_name} is required for the packaged desktop runtime",
        }
    executable = Path(configured_path.strip()).expanduser()
    if not executable.is_absolute():
        return {
            "ok": False,
            "status": "invalid",
            "detail": f"{component} executable path must be absolute",
        }
    if not executable.is_file():
        return {
            "ok": False,
            "status": "missing",
            "detail": f"{component} executable was not found",
        }
    if not os.access(executable, os.X_OK):
        return {
            "ok": False,
            "status": "not_executable",
            "detail": f"{component} path is not executable",
        }
    return {
        "ok": True,
        "status": "available",
    }


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
    """Check persistence plus packaged-runtime worker and simulator dependencies."""

    from app.config import get_settings
    from app.orchestration.worker_presence import worker_presence_health

    settings = get_settings()
    runtime_id = settings.dronedream_runtime_id
    worker = worker_presence_health()
    if runtime_id is not None and worker.get("status") == "not_required":
        worker = {
            "ok": False,
            "status": "not_configured",
            "detail": (
                "The packaged desktop runtime requires REDIS_URL and a live "
                "worker heartbeat"
            ),
        }
    components = {
        "database": _database_health(),
        "storage": _storage_health(),
        "worker": worker,
    }
    if runtime_id is not None:
        components["px4"] = _runtime_executable_health(
            settings.dronedream_px4_executable,
            component="PX4",
            environment_name="DRONEDREAM_PX4_EXECUTABLE",
        )
        components["gazebo"] = _runtime_executable_health(
            settings.dronedream_gazebo_executable,
            component="Gazebo",
            environment_name="DRONEDREAM_GAZEBO_EXECUTABLE",
        )
    is_ready = all(bool(component.get("ok")) for component in components.values())
    payload = ok(
        {
            "status": "ready" if is_ready else "not_ready",
            "service": "drone-dream-backend",
            "version": __version__,
            "runtime_id": runtime_id,
            "components": components,
        }
    )
    if is_ready:
        return payload
    return JSONResponse(status_code=503, content=payload)
