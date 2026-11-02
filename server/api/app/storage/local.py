from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings
from app.storage.base import ArtifactStorage


def _resolve_allowed_path(storage_uri: str | Path) -> Path:
    """Reject traversal and resolve symlinks before checking the configured storage roots.

    This bounds the filesystem namespace, not user ownership. Authenticated
    routes must resolve an owned Artifact before passing its stored path here.
    """
    raw_path = Path(storage_uri)
    if ".." in raw_path.parts:
        raise ValueError("Artifact path is outside allowed roots.")
    path = raw_path.resolve()
    if not any(path.is_relative_to(root) for root in get_settings().allowed_artifact_roots):
        raise ValueError("Artifact path is outside allowed roots.")
    return path


class LocalArtifactStorage(ArtifactStorage):
    """Register/read existing local output files without moving them to a second store."""
    def put_file(self, local_path: Path, key: str, content_type: str | None = None) -> str:
        """Register an existing allowed file; key/MIME belong to the separate DB metadata."""
        _ = key
        _ = content_type
        path = _resolve_allowed_path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"Artifact source is not a regular file: {path.name}")
        return str(path)

    def read_bytes(self, storage_uri: str) -> bytes:
        """Read an allowed payload in full; use copy_to for large reports or recordings."""
        return _resolve_allowed_path(storage_uri).read_bytes()

    def content_digest(self, storage_uri: str) -> tuple[str, int]:
        """Stream SHA-256 and exact byte count without loading the complete artifact."""
        digest = hashlib.sha256()
        size = 0
        with _resolve_allowed_path(storage_uri).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def copy_to(self, storage_uri: str, destination: BinaryIO) -> tuple[str, int]:
        """Copy and hash the same bytes; partial destination writes are explicit failures."""
        digest = hashlib.sha256()
        size = 0
        with _resolve_allowed_path(storage_uri).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                if destination.write(chunk) != len(chunk):
                    raise OSError("artifact destination accepted only a partial write")
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def exists(self, storage_uri: str) -> bool:
        """Test regular-file presence only, not a receipt or authorization match."""
        path = _resolve_allowed_path(storage_uri)
        return path.exists() and path.is_file()

    def delete(self, storage_uri: str) -> None:
        """Remove one allowed file after caller lifecycle checks; never recursively delete."""
        path = _resolve_allowed_path(storage_uri)
        if path.exists() and path.is_file():
            path.unlink()

    def presign_download(
        self, storage_uri: str, *, expires_seconds: int | None = None
    ) -> str | None:
        """Local files have no presigned public URL; the authenticated API streams them."""
        _ = storage_uri, expires_seconds
        return None

    def check_health(self) -> None:
        """Verify durable write access using a temporary probe removed by its context."""
        root = get_settings().default_artifact_root_path
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".health-", dir=root) as probe:
            probe.write(b"dronedream-storage-health\n")
            probe.flush()
            os.fsync(probe.fileno())
