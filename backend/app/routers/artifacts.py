"""Artifact-specific routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.db import get_db

router = APIRouter(tags=["artifacts"])


def _is_under_allowed_root(path: Path, allowed_roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root) for root in allowed_roots)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
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

    path = Path(artifact.storage_path).resolve()
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
