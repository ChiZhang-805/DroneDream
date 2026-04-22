"""Health router — liveness probe that uses the standard response envelope."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.response import ok

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    """Return a simple liveness payload in the standard envelope."""

    return ok({"status": "ok", "service": "drone-dream-backend", "version": __version__})
