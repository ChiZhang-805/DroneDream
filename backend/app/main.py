"""FastAPI application entrypoint for DroneDream."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.response import err
from app.routers import artifacts as artifacts_router
from app.routers import batches as batches_router
from app.routers import capabilities as capabilities_router
from app.routers import health
from app.routers import jobs as jobs_router
from app.routers import parameter_catalog as parameter_catalog_router
from app.routers import trials as trials_router
from app.services.jobs import purge_expired_job_secrets
from app.storage.cleanup import cleanup_local_artifacts

logger = logging.getLogger("drone_dream.backend")


async def _secret_housekeeping_loop(interval_seconds: int) -> None:
    """Periodically wipe expired queued-job credentials without a worker."""

    while True:
        await asyncio.sleep(interval_seconds)

        def purge_once() -> int:
            with SessionLocal() as db:
                return purge_expired_job_secrets(db)

        try:
            purged = await asyncio.to_thread(purge_once)
            if purged:
                logger.info("purged %d expired per-job secret(s)", purged)
        except Exception:
            # Housekeeping must never terminate the API, but failures are
            # visible to operators and retried on the next interval.
            logger.exception("expired-secret housekeeping failed")


async def _artifact_housekeeping_loop(interval_seconds: int) -> None:
    """Periodically apply the opt-in local artifact lifecycle policy."""

    while True:
        await asyncio.sleep(interval_seconds)

        def cleanup_once() -> dict[str, object]:
            with SessionLocal() as db:
                return cleanup_local_artifacts(db).to_dict()

        try:
            stats = await asyncio.to_thread(cleanup_once)
            if stats["planned_files"] or stats["planned_artifact_rows"] or stats["errors"]:
                logger.info("local artifact cleanup: %s", stats)
        except Exception:
            # Retention is operational housekeeping and must never terminate
            # the API. The next configured interval retries any safe orphans.
            logger.exception("local artifact housekeeping failed")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    # Initialize the database tables. Safe to call repeatedly.
    init_db()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        tasks = [
            asyncio.create_task(
                _secret_housekeeping_loop(settings.job_secret_cleanup_interval_seconds)
            )
        ]
        if settings.artifact_cleanup_enabled:
            tasks.append(
                asyncio.create_task(
                    _artifact_housekeeping_loop(
                        settings.artifact_cleanup_interval_seconds
                    )
                )
            )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="DroneDream API",
        version=__version__,
        description=(
            "DroneDream backend — /api/v1 job, trial, report, and artifact "
            "APIs backed by SQLAlchemy persistence and the standard "
            "response envelope."
        ),
        lifespan=lifespan,
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

    # /api/v1 namespace for the real domain routes.
    api_v1 = FastAPI(title="DroneDream API v1", version=__version__)
    api_v1.include_router(jobs_router.router)
    api_v1.include_router(batches_router.router)
    api_v1.include_router(trials_router.router)
    api_v1.include_router(artifacts_router.router)
    api_v1.include_router(parameter_catalog_router.router)
    api_v1.include_router(capabilities_router.router)

    _register_exception_handlers(api_v1)
    app.mount("/api/v1", api_v1)

    _register_exception_handlers(app)

    return app


def _register_exception_handlers(target: FastAPI) -> None:
    @target.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            return JSONResponse(
                status_code=exc.status_code,
                headers=exc.headers,
                content=err(
                    code=str(detail["code"]),
                    message=str(detail["message"]),
                    details=detail.get("details"),
                ),
            )
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content=err(code=_http_code_label(exc.status_code), message=str(detail)),
        )

    @target.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=err(
                code="INVALID_INPUT",
                message="Invalid request payload",
                details=jsonable_encoder(exc.errors()),
            ),
        )


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
