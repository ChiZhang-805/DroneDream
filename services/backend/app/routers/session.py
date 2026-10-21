"""Authenticated desktop-session verification."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app import models
from app.auth import get_current_user
from app.response import ok

router = APIRouter(prefix="/session", tags=["session"])


@router.get("")
def read_authenticated_session(
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> dict[str, object]:
    """Prove that the local API accepted the caller's current bearer token."""

    return ok(
        {
            "status": "ready",
            "user_id": str(current_user.external_subject or current_user.id),
        }
    )


__all__ = ["router"]
