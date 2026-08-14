"""Read-only compilation and qualification API for shared mission autonomy."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app import models
from app.auth import get_current_user
from app.autonomy.catalog import list_scenes
from app.autonomy.models import AutonomyCompileRequest
from app.autonomy.service import AutonomyCompileError, compile_autonomy_mission
from app.response import ok

router = APIRouter(prefix="/autonomy", tags=["autonomy"])


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


__all__ = ["router"]
