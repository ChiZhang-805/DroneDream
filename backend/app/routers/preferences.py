"""Authenticated, minimal user preference controls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app import models, schemas
from app.api_idempotency import begin_mutation
from app.auth import get_current_user
from app.db import get_db
from app.response import ok
from app.services.user_preferences import (
    delete_user_experience_preferences,
    get_user_experience_preferences,
    serialize_user_experience_preferences,
    update_user_experience_preferences,
)

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("/experience")
def read_experience_preferences(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    preferences = get_user_experience_preferences(db, user_id=user.id)
    return ok(serialize_user_experience_preferences(preferences).model_dump(mode="json"))


@router.put("/experience")
def write_experience_preferences(
    request: schemas.UserExperiencePreferencesUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    gate = begin_mutation(
        db,
        user=user,
        operation="preferences.experience.update",
        idempotency_key=idempotency_key,
        payload=request.model_dump(mode="json", exclude_unset=True),
    )
    if gate.replay is not None:
        return gate.replay
    preferences, deleted_memory_count = update_user_experience_preferences(
        db,
        user_id=user.id,
        request=request,
    )
    payload = serialize_user_experience_preferences(preferences).model_dump(mode="json")
    payload["deleted_memory_count"] = deleted_memory_count
    return gate.complete(
        ok(payload),
        resource_type="user_experience_preferences",
        resource_id=user.id,
    )


@router.delete("/experience")
def erase_experience_preferences(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    gate = begin_mutation(
        db,
        user=user,
        operation="preferences.experience.delete",
        idempotency_key=idempotency_key,
        payload={},
    )
    if gate.replay is not None:
        return gate.replay
    deleted_preferences, deleted_memory_count = delete_user_experience_preferences(
        db,
        user_id=user.id,
    )
    return gate.complete(
        ok(
            {
                "deleted_preferences": deleted_preferences,
                "deleted_memory_count": deleted_memory_count,
                "memory_enabled": False,
            }
        ),
        resource_type="user_experience_preferences",
        resource_id=user.id,
    )


__all__ = ["router"]
