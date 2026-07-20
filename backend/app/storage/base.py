from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ArtifactStorage(Protocol):
    def put_file(self, local_path: Path, key: str, content_type: str | None = None) -> str:
        """Persist a local file and return a storage URI/path."""

    def read_bytes(self, storage_uri: str) -> bytes:
        """Read an artifact payload from storage."""

    def exists(self, storage_uri: str) -> bool:
        """Return whether the artifact exists in storage."""

    def delete(self, storage_uri: str) -> None:
        """Delete an artifact payload from storage."""

    def presign_download(
        self, storage_uri: str, *, expires_seconds: int | None = None
    ) -> str | None:
        """Return a temporary download URL when the backend supports it.

        Local storage intentionally returns ``None`` so existing API streaming
        remains the compatibility path.
        """

    def check_health(self) -> None:
        """Raise when the backing store is not currently usable."""
