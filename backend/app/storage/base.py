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
