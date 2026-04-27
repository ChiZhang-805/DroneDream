from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class StorageDownload:
    content: bytes
    content_type: str
    filename: str


class ArtifactStorage(ABC):
    @abstractmethod
    def put_file(self, local_path: str, key: str, content_type: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def open_for_download(self, storage_uri: str) -> StorageDownload:
        raise NotImplementedError

    @abstractmethod
    def exists(self, storage_uri: str) -> bool:
        raise NotImplementedError
