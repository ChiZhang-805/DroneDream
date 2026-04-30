from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.storage.base import ArtifactStorage


class LocalArtifactStorage(ArtifactStorage):
    def put_file(self, local_path: Path, key: str, content_type: str | None = None) -> str:
        _ = key
        _ = content_type
        return str(local_path.resolve())

    def read_bytes(self, storage_uri: str) -> bytes:
        return Path(storage_uri).resolve().read_bytes()

    def exists(self, storage_uri: str) -> bool:
        path = Path(storage_uri).resolve()
        return path.exists() and path.is_file()

    def delete(self, storage_uri: str) -> None:
        raw_path = Path(storage_uri)
        if ".." in raw_path.parts:
            raise ValueError("Artifact path is outside allowed roots.")
        path = raw_path.resolve()
        if not any(path.is_relative_to(root) for root in get_settings().allowed_artifact_roots):
            raise ValueError("Artifact path is outside allowed roots.")
        if path.exists() and path.is_file():
            path.unlink()
