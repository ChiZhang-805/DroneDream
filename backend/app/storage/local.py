from __future__ import annotations

from pathlib import Path

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
