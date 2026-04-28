from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.db import get_db

_DEFAULT_USER_EMAIL = "default@drone-dream.local"
_DEFAULT_USER_NAME = "Default User"


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _get_or_create_user(db: Session, *, email: str, display_name: str | None = None) -> models.User:
    existing = db.scalars(select(models.User).where(models.User.email == email).limit(1)).first()
    if existing is not None:
        return existing

    user = models.User(email=email, display_name=display_name or email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> models.User:
    settings = get_settings()
    if settings.auth_mode == "disabled":
        return _get_or_create_user(db, email=_DEFAULT_USER_EMAIL, display_name=_DEFAULT_USER_NAME)

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

    return _get_or_create_user(db, email=email, display_name=email)
