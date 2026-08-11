"""Artifact-specific routes."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Annotated, BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import models
from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.services.pdf_report import render_job_pdf_report
from app.services.report_entitlements import (
    ReportExportTier,
    resolve_report_export_tier,
)
from app.storage import get_artifact_storage
from app.storage.integrity import (
    ArtifactIntegrityError,
    require_artifact_integrity,
)
from app.storage.local import LocalArtifactStorage
from app.storage.s3 import S3StorageConfigError

router = APIRouter(tags=["artifacts"])
_MAX_ARTIFACT_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
_MAX_PDF_REPORT_BYTES = 64 * 1024 * 1024


class ArtifactDownloadTooLarge(ValueError):
    """Raised before an object-store download can exhaust local disk."""


class _BoundedWriter:
    def __init__(self, destination: BinaryIO, maximum_bytes: int) -> None:
        self._destination = destination
        self._maximum_bytes = maximum_bytes
        self.written = 0

    def write(self, content: bytes) -> int:
        if len(content) > self._maximum_bytes - self.written:
            raise ArtifactDownloadTooLarge(
                "artifact exceeds the configured application download limit"
            )
        count = self._destination.write(content)
        self.written += count
        return count


def _delete_temporary_download(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _temporary_download(
    *,
    storage: object,
    artifact: models.Artifact,
    maximum_bytes: int,
    verify_integrity: bool,
) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix="dronedream-artifact-", suffix=".download")
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w+b") as destination:
            descriptor = -1
            copy_to = getattr(storage, "copy_to", None)
            if not callable(copy_to):
                raise RuntimeError("artifact storage does not support bounded downloads")
            bounded_destination = _BoundedWriter(destination, maximum_bytes)
            digest = copy_to(artifact.storage_path, bounded_destination)
            if (
                not isinstance(digest, tuple)
                or len(digest) != 2
                or digest[1] != bounded_destination.written
            ):
                raise RuntimeError("artifact storage returned an invalid copy receipt")
            destination.flush()
            os.fsync(destination.fileno())
        if verify_integrity:
            require_artifact_integrity(artifact, content_digest=digest)
        return path
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        _delete_temporary_download(path)
        raise


def _is_under_allowed_root(path: Path, allowed_roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in allowed_roots)


def _safe_download_name(display_name: str | None, storage_path: str) -> str:
    """Return a header-safe leaf name for worker-supplied artifact metadata."""

    raw = (display_name or Path(storage_path).name or "artifact").strip()
    cleaned = "".join("_" if ord(char) < 32 or char in {"/", "\\"} else char for char in raw).strip(
        ". "
    )
    return (cleaned or "artifact")[:255]


def _attachment_header(filename: str) -> str:
    try:
        filename.encode("ascii")
    except UnicodeEncodeError:
        return f"attachment; filename*=UTF-8''{quote(filename)}"
    escaped = filename.replace("\\", "_").replace('"', "_")
    return f'attachment; filename="{escaped}"'


def _report_headers(
    *,
    artifact: models.Artifact,
    tier: ReportExportTier,
) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Content-Disposition": _attachment_header(
            _safe_download_name(artifact.display_name, artifact.storage_path)
        ),
        "X-DroneDream-Report-Tier": tier,
        "X-DroneDream-Report-Watermark": "applied" if tier == "free" else "none",
    }


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User, Depends(get_current_user)],
) -> Response:
    artifact = db.get(models.Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
        )

    if artifact.storage_path.startswith("mock://"):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ARTIFACT_NOT_DOWNLOADABLE",
                "message": "Mock artifacts are not downloadable.",
            },
        )

    job: models.Job | None = None
    if artifact.owner_type == "job":
        job = db.get(models.Job, artifact.owner_id)
        auth_disabled_owned_null = (
            get_settings().auth_mode == "disabled" and job is not None and job.user_id is None
        )
        if job is None or (job.user_id != user.id and not auth_disabled_owned_null):
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
            )
    elif artifact.owner_type == "trial":
        trial = db.get(models.Trial, artifact.owner_id)
        if (
            trial is None
            or trial.job is None
            or (
                trial.job.user_id != user.id
                and not (get_settings().auth_mode == "disabled" and trial.job.user_id is None)
            )
        ):
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
            )
    else:
        # Polymorphic owner rows are written by workers. Unknown owner types
        # must fail closed instead of skipping tenant authorization entirely.
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
        )

    try:
        digest_receipt = require_artifact_integrity(artifact)
    except ArtifactIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ARTIFACT_INTEGRITY_INVALID",
                "message": "Artifact integrity metadata is invalid.",
            },
        ) from exc

    report_tier: ReportExportTier | None = None
    if artifact.artifact_type == "pdf_report":
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
            )
        report_tier = resolve_report_export_tier(
            authorization_header=request.headers.get("Authorization")
        )

    if artifact.storage_path.startswith("s3://"):
        try:
            storage = get_artifact_storage()
            if not storage.exists(artifact.storage_path):
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "ARTIFACT_FILE_MISSING",
                        "message": "Artifact file does not exist.",
                    },
                )
            presign = getattr(storage, "presign_download", None)
            # Tiered PDF exports must always traverse the application so the
            # trusted entitlement decision and Free watermark cannot be
            # bypassed by a direct object-store URL. Non-report artifacts may
            # retain the presigned-download fast path.
            if report_tier is None and digest_receipt is None and callable(presign):
                signed_url = presign(
                    artifact.storage_path,
                    expires_seconds=get_settings().artifact_presign_expiry_seconds,
                )
                if signed_url:
                    return RedirectResponse(url=signed_url, status_code=307)
            temporary_download = None
            if digest_receipt is not None:
                maximum_bytes = min(
                    _MAX_ARTIFACT_DOWNLOAD_BYTES,
                    _MAX_PDF_REPORT_BYTES
                    if report_tier is not None
                    else _MAX_ARTIFACT_DOWNLOAD_BYTES,
                )
                if digest_receipt.content_size_bytes > maximum_bytes:
                    raise ArtifactDownloadTooLarge(
                        "bound artifact exceeds the configured application download limit"
                    )
                temporary_download = _temporary_download(
                    storage=storage,
                    artifact=artifact,
                    maximum_bytes=maximum_bytes,
                    verify_integrity=True,
                )
            elif report_tier != "free":
                temporary_download = _temporary_download(
                    storage=storage,
                    artifact=artifact,
                    maximum_bytes=(
                        _MAX_PDF_REPORT_BYTES
                        if report_tier is not None
                        else _MAX_ARTIFACT_DOWNLOAD_BYTES
                    ),
                    verify_integrity=False,
                )
            content = None
        except ArtifactIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ARTIFACT_INTEGRITY_INVALID",
                    "message": "Artifact bytes failed integrity verification.",
                },
            ) from exc
        except ArtifactDownloadTooLarge as exc:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "ARTIFACT_TOO_LARGE",
                    "message": "Artifact exceeds the application download limit.",
                },
            ) from exc
        except S3StorageConfigError as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "CONFIGURATION_ERROR", "message": str(exc)},
            ) from exc

        filename = _safe_download_name(artifact.display_name, artifact.storage_path)
        if report_tier is not None:
            if report_tier == "free":
                if job is None:
                    raise RuntimeError("report export tier resolved without an owning job")
                content = render_job_pdf_report(
                    job,
                    free_tier_watermark=True,
                )
                if temporary_download is not None:
                    _delete_temporary_download(temporary_download)
                temporary_download = None
            elif temporary_download is not None:
                return FileResponse(
                    path=temporary_download,
                    media_type="application/pdf",
                    headers=_report_headers(artifact=artifact, tier=report_tier),
                    background=BackgroundTask(
                        _delete_temporary_download,
                        temporary_download,
                    ),
                )
            if content is None:
                raise RuntimeError("report storage returned no download content")
            return Response(
                content=content,
                media_type="application/pdf",
                headers=_report_headers(artifact=artifact, tier=report_tier),
            )
        if temporary_download is not None:
            return FileResponse(
                path=temporary_download,
                media_type=artifact.mime_type or "application/octet-stream",
                filename=filename,
                background=BackgroundTask(
                    _delete_temporary_download,
                    temporary_download,
                ),
            )
        if content is None:
            raise RuntimeError("artifact storage returned no download content")
        return Response(
            content=content,
            media_type=artifact.mime_type or "application/octet-stream",
            headers={"Content-Disposition": _attachment_header(filename)},
        )

    raw_path = Path(artifact.storage_path)
    if ".." in raw_path.parts:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ARTIFACT_PATH_FORBIDDEN",
                "message": "Artifact path is outside allowed roots.",
            },
        )
    path = raw_path.resolve()
    if not _is_under_allowed_root(path, get_settings().allowed_artifact_roots):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ARTIFACT_PATH_FORBIDDEN",
                "message": "Artifact path is outside allowed roots.",
            },
        )

    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "ARTIFACT_FILE_MISSING", "message": "Artifact file does not exist."},
        )

    local_snapshot: Path | None = None
    try:
        if digest_receipt is not None:
            maximum_bytes = min(
                _MAX_ARTIFACT_DOWNLOAD_BYTES,
                _MAX_PDF_REPORT_BYTES if report_tier is not None else _MAX_ARTIFACT_DOWNLOAD_BYTES,
            )
            if digest_receipt.content_size_bytes > maximum_bytes:
                raise ArtifactDownloadTooLarge(
                    "bound artifact exceeds the configured application download limit"
                )
            # FileResponse opens its path after this route returns. Copy and
            # verify into a private snapshot so a cleanup task or local file
            # replacement cannot change the bytes after the integrity check.
            local_snapshot = _temporary_download(
                storage=LocalArtifactStorage(),
                artifact=artifact,
                maximum_bytes=maximum_bytes,
                verify_integrity=True,
            )
        elif report_tier is not None and report_tier != "free":
            local_snapshot = _temporary_download(
                storage=LocalArtifactStorage(),
                artifact=artifact,
                maximum_bytes=_MAX_PDF_REPORT_BYTES,
                verify_integrity=False,
            )
    except ArtifactIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ARTIFACT_INTEGRITY_INVALID",
                "message": "Artifact bytes failed integrity verification.",
            },
        ) from exc
    except ArtifactDownloadTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "ARTIFACT_TOO_LARGE",
                "message": "Artifact exceeds the application download limit.",
            },
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ARTIFACT_FILE_MISSING",
                "message": "Artifact file does not exist.",
            },
        ) from exc

    if report_tier == "free":
        if local_snapshot is not None:
            _delete_temporary_download(local_snapshot)
        if job is None:
            raise RuntimeError("report export tier resolved without an owning job")
        return Response(
            content=render_job_pdf_report(
                job,
                free_tier_watermark=True,
            ),
            media_type="application/pdf",
            headers=_report_headers(artifact=artifact, tier=report_tier),
        )

    if local_snapshot is not None:
        return FileResponse(
            path=local_snapshot,
            media_type=artifact.mime_type or "application/octet-stream",
            filename=_safe_download_name(
                artifact.display_name,
                artifact.storage_path,
            ),
            headers=(
                _report_headers(artifact=artifact, tier=report_tier)
                if report_tier is not None
                else None
            ),
            background=BackgroundTask(
                _delete_temporary_download,
                local_snapshot,
            ),
        )

    return FileResponse(
        path=path,
        media_type=artifact.mime_type or "application/octet-stream",
        filename=_safe_download_name(artifact.display_name, artifact.storage_path),
        headers=(
            _report_headers(artifact=artifact, tier=report_tier)
            if report_tier is not None
            else None
        ),
    )
