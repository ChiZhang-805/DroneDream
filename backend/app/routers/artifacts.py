"""Artifact-specific routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app import models
from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.storage import get_artifact_storage
from app.storage.s3 import S3StorageConfigError

router = APIRouter(tags=["artifacts"])


def _is_under_allowed_root(path: Path, allowed_roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in allowed_roots)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[models.User | None, Depends(get_current_user)],
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

    if artifact.owner_type == "job":
        job = db.get(models.Job, artifact.owner_id)
        if job is None or (user is not None and job.user_id != user.id):
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
            )
    elif artifact.owner_type == "trial":
        trial = db.get(models.Trial, artifact.owner_id)
        if trial is None or trial.job is None or (
            user is not None and trial.job.user_id != user.id
        ):
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": "Artifact not found."},
            )

    if artifact.storage_path.startswith("s3://"):
        try:
            storage = get_artifact_storage()
            downloaded = storage.open_for_download(artifact.storage_path)
        except S3StorageConfigError as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": "CONFIGURATION_ERROR", "message": str(exc)},
            ) from exc
        if not downloaded.content:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "ARTIFACT_FILE_MISSING",
                    "message": "Artifact file does not exist.",
                },
            )
        return Response(
            content=downloaded.content,
            media_type=artifact.mime_type or downloaded.content_type,
            headers={
                "Content-Disposition": (
                    f"attachment; filename={artifact.display_name or downloaded.filename}"
                )
            },
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

    return FileResponse(
        path=path,
        media_type=artifact.mime_type or "application/octet-stream",
        filename=artifact.display_name or path.name,
    )
