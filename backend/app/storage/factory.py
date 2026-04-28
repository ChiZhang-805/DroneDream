from __future__ import annotations

from app.config import get_settings
from app.storage.base import ArtifactStorage
from app.storage.local import LocalArtifactStorage
from app.storage.s3 import S3ArtifactStorage


def get_artifact_storage() -> ArtifactStorage:
    backend = get_settings().artifact_storage_backend
    if backend == "local":
        return LocalArtifactStorage()
    if backend == "s3":
        return S3ArtifactStorage()
    raise RuntimeError(f"Unsupported ARTIFACT_STORAGE_BACKEND: {backend}")
