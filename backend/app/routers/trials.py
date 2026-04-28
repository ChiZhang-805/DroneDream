"""Trial-related routes under /api/v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.response import ok
from app.services import jobs as job_service

router = APIRouter(tags=["trials"])


@router.get("/trials/{trial_id}")
def get_trial(
    trial_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    trial = db.get(models.Trial, trial_id)
    if trial is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRIAL_NOT_FOUND", "message": f"Trial {trial_id} was not found."},
        )
    auth_disabled_owned_null = (
        get_settings().auth_mode == "disabled"
        and trial.job is not None
        and trial.job.user_id is None
    )
    if trial.job is None or (trial.job.user_id != user.id and not auth_disabled_owned_null):
        raise HTTPException(
            status_code=404,
            detail={"code": "TRIAL_NOT_FOUND", "message": f"Trial {trial_id} was not found."},
        )
    return ok(job_service.to_trial_schema(trial).model_dump(mode="json"))
