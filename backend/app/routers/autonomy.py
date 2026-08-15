"""Read-only compilation and qualification API for shared mission autonomy."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app import models
from app.auth import get_current_user
from app.autonomy.catalog import list_scenes
from app.autonomy.models import (
    AutonomyCompileRequest,
    RuntimeObservation,
    RuntimeOperatorCommand,
    RuntimeSessionCreateRequest,
)
from app.autonomy.runtime import AutonomyRuntimeError, runtime_sessions
from app.autonomy.service import AutonomyCompileError, compile_autonomy_mission
from app.response import ok

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


def _runtime_error(exc: AutonomyRuntimeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/scenes")
def read_autonomy_scenes(
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    return ok(
        {
            "schema_version": "dronedream.autonomy.scene-catalog.v1",
            "items": [scene.model_dump(mode="json") for scene in list_scenes()],
        }
    )


@router.post("/compile")
async def compile_mission(
    request: AutonomyCompileRequest,
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Compile and qualify a mission without starting a simulator or vehicle."""

    try:
        result = await asyncio.to_thread(compile_autonomy_mission, request)
    except AutonomyCompileError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ok(result.model_dump(mode="json"))


@router.get("/runtime/capabilities")
def read_runtime_capabilities(
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Expose runtime boundaries without probing or connecting to a vehicle."""

    return ok(runtime_sessions.capabilities())


@router.post("/runtime/sessions", status_code=201)
async def create_runtime_session(
    request: RuntimeSessionCreateRequest,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Create an idempotent, process-local simulation supervision session."""

    try:
        result = await asyncio.to_thread(runtime_sessions.create, current_user.id, request)
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.get("/runtime/sessions/{session_id}")
def read_runtime_session(
    session_id: str,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    try:
        result = runtime_sessions.get(current_user.id, session_id)
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/runtime/sessions/{session_id}/observations")
async def ingest_runtime_observation(
    session_id: str,
    observation: RuntimeObservation,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Evaluate one ordered observation; this endpoint never emits actuator commands."""

    try:
        result = await asyncio.to_thread(
            runtime_sessions.observe,
            current_user.id,
            session_id,
            observation,
        )
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


@router.post("/runtime/sessions/{session_id}/operator-commands")
async def apply_runtime_operator_command(
    session_id: str,
    command: RuntimeOperatorCommand,
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Accept only safety-reducing hold or abort commands."""

    try:
        result = await asyncio.to_thread(
            runtime_sessions.command,
            current_user.id,
            session_id,
            command,
        )
    except AutonomyRuntimeError as exc:
        raise _runtime_error(exc) from exc
    return ok(result.model_dump(mode="json"))


__all__ = ["router"]
