"""FastAPI application entrypoint for DroneDream."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import get_settings
from app.response import err
from app.routers import health

logger = logging.getLogger("drone_dream.backend")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="DroneDream API",
        version=__version__,
        description="DroneDream backend — Phase 0 skeleton.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health endpoint lives outside /api/v1 by design.
    app.include_router(health.router)

    # /api/v1 namespace is reserved for the real domain routes (added in later phases).
    # We mount the router so the prefix is stable from day one.
    api_v1 = FastAPI(title="DroneDream API v1", version=__version__)
    app.mount("/api/v1", api_v1)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=err(code=_http_code_label(exc.status_code), message=str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=err(
                code="INVALID_INPUT",
                message="Invalid request payload",
                details=exc.errors(),
            ),
        )

    return app


def _http_code_label(status_code: int) -> str:
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "INVALID_INPUT",
    }
    if status_code in mapping:
        return mapping[status_code]
    if 500 <= status_code < 600:
        return "INTERNAL_ERROR"
    return "HTTP_ERROR"


app = create_app()
