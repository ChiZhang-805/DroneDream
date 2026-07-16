from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.config import get_settings
from app.storage.base import ArtifactStorage


def _resolve_allowed_path(storage_uri: str | Path) -> Path:
    raw_path = Path(storage_uri)
    if ".." in raw_path.parts:
        raise ValueError("Artifact path is outside allowed roots.")
    path = raw_path.resolve()
    if not any(path.is_relative_to(root) for root in get_settings().allowed_artifact_roots):
        raise ValueError("Artifact path is outside allowed roots.")
    return path


class LocalArtifactStorage(ArtifactStorage):
    def put_file(self, local_path: Path, key: str, content_type: str | None = None) -> str:
        _ = key
        _ = content_type
        path = _resolve_allowed_path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact source is not a regular file: {path.name}")
        return str(path)

    def read_bytes(self, storage_uri: str) -> bytes:
        return _resolve_allowed_path(storage_uri).read_bytes()

    def exists(self, storage_uri: str) -> bool:
        path = _resolve_allowed_path(storage_uri)
        return path.exists() and path.is_file()

    def delete(self, storage_uri: str) -> None:
        path = _resolve_allowed_path(storage_uri)
        if path.exists() and path.is_file():
            path.unlink()

    def presign_download(
        self, storage_uri: str, *, expires_seconds: int | None = None
    ) -> str | None:
        _ = storage_uri, expires_seconds
        return None

    def check_health(self) -> None:
        root = get_settings().default_artifact_root_path
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".health-", dir=root) as probe:
            probe.write(b"dronedream-storage-health\n")
            probe.flush()
            os.fsync(probe.fileno())
