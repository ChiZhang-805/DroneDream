from __future__ import annotations

from pathlib import Path

from app.storage.base import ArtifactStorage, StorageDownload


class LocalArtifactStorage(ArtifactStorage):
    def put_file(self, local_path: str, key: str, content_type: str | None = None) -> str:
        _ = key
        _ = content_type
        return str(Path(local_path).resolve())

    def open_for_download(self, storage_uri: str) -> StorageDownload:
        path = Path(storage_uri).resolve()
        return StorageDownload(
            content=path.read_bytes(),
            content_type="application/octet-stream",
            filename=path.name,
        )

    def exists(self, storage_uri: str) -> bool:
        path = Path(storage_uri).resolve()
        return path.exists() and path.is_file()
