"""Standard API response envelope helpers.

Every ``/api/v1`` endpoint (and ``/health``) must return this shape:

Success::

    {"success": true,  "data": {...}, "error": null}

Error::

    {"success": false, "data": null,
     "error": {"code": "INVALID_INPUT", "message": "...", "details": null}}
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorPayload(BaseModel):
    """Structured error body returned inside the envelope."""

    code: str
    message: str
    details: Any | None = None


class SuccessEnvelope(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    error: None = None


class ErrorEnvelope(BaseModel):
    success: Literal[False] = False
    data: None = None
    error: ErrorPayload


def ok(data: Any = None) -> dict[str, Any]:
    """Build a success envelope as a plain dict (for JSONResponse / tests)."""

    return {"success": True, "data": data, "error": None}


def err(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    """Build an error envelope as a plain dict."""

    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details},
    }


__all__ = [
    "ErrorEnvelope",
    "ErrorPayload",
    "SuccessEnvelope",
    "err",
    "ok",
]


# Silence an unused-import style warning for the Field import kept available
# for future schema reuse without triggering ruff's F401.
_ = Field
