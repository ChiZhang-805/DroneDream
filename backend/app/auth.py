from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.db import get_db


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def get_current_user_optional(
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> models.User | None:
    settings = get_settings()
    if settings.auth_mode == "disabled":
        return None

    if settings.auth_mode != "demo_token":
        raise HTTPException(
            status_code=500,
            detail={"code": "CONFIGURATION_ERROR", "message": "Unsupported AUTH_MODE."},
        )

    token = _extract_bearer_token(request.headers.get("Authorization"))
    if token is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Missing bearer token."},
        )

    email = settings.demo_auth_token_map.get(token)
    if email is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid bearer token."},
        )
    existing = db.scalars(select(models.User).where(models.User.email == email).limit(1)).first()
    if existing is not None:
        return existing
    return models.User(email=email, display_name=email)


def get_current_user(
    user: Annotated[models.User | None, Depends(get_current_user_optional)],
) -> models.User | None:
    return user
