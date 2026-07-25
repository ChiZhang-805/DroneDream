"""Conversation-to-draft compiler endpoints."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app import experiment_assistant, models, schemas
from app.auth import get_current_user
from app.response import ok

router = APIRouter(prefix="/experiment-assistant", tags=["experiment-assistant"])


@router.post("/turn")
async def compile_turn(
    request: schemas.ExperimentAssistantTurnRequest,
    _current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Compile one ordinary-language turn into validated draft patches.

    This route is deliberately draft-only. It cannot create a Job, start a
    simulator, or mutate persisted experiment state.
    """

    try:
        result = await asyncio.to_thread(
            experiment_assistant.compile_experiment_turn,
            request,
        )
    except experiment_assistant.ExperimentAssistantError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return ok(result.model_dump(mode="json"))


__all__ = ["router"]
