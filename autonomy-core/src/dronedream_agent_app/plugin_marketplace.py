"""HTTPS-only plugin catalog discovery and digest-pinned installation."""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dronedream_agent_core.plugin_contracts import (
    PluginManifest,
    PluginMarketplaceIndex,
    PluginMarketplaceSource,
)

from .plugin_manager import PluginManager, PluginManagerError
from .storage import AppStore


class PluginMarketplaceError(RuntimeError):
    """A catalog or archive failed a bounded validation step."""


class PluginMarketplaceService:
    def __init__(self, store: AppStore, manager: PluginManager) -> None:
        self.store = store
        self.manager = manager

    def sources(self) -> list[PluginMarketplaceSource]:
        raw = self.store.get_settings().get("plugin_marketplace_sources", [])
        if not isinstance(raw, list):
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_SOURCES_INVALID")
        try:
            sources = [PluginMarketplaceSource.model_validate(item) for item in raw]
        except ValidationError as error:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_SOURCES_INVALID") from error
        if len({item.source_id for item in sources}) != len(sources):
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_SOURCE_DUPLICATE")
        return sources

    def replace_sources(self, sources: list[PluginMarketplaceSource]) -> list[dict[str, Any]]:
        if len(sources) > 32 or len({item.source_id for item in sources}) != len(sources):
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_SOURCES_INVALID")
        payload = [item.model_dump(mode="json") for item in sources]
        self.store.patch_settings({"plugin_marketplace_sources": payload})
        return payload

    @staticmethod
    def _download(url: str, *, limit: int, timeout_seconds: float) -> bytes:
        if not url.startswith("https://"):
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_HTTPS_REQUIRED")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, application/zip",
                "User-Agent": "DroneDream-AUTONOMY/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if response.geturl().startswith("https://") is False:
                    raise PluginMarketplaceError("PLUGIN_MARKETPLACE_REDIRECT_DENIED")
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > limit:
                    raise PluginMarketplaceError("PLUGIN_MARKETPLACE_RESPONSE_TOO_LARGE")
                payload = response.read(limit + 1)
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_FETCH_FAILED") from error
        if len(payload) > limit:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_RESPONSE_TOO_LARGE")
        return payload

    def catalog(self) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for source in self.sources():
            if not source.enabled:
                continue
            try:
                raw = self._download(source.index_url, limit=2 * 1024 * 1024, timeout_seconds=15)
                index = PluginMarketplaceIndex.model_validate_json(raw)
                entries.extend(
                    {
                        **entry.model_dump(mode="json"),
                        "source_id": source.source_id,
                        "source_name": source.name,
                    }
                    for entry in index.entries
                )
            except (PluginMarketplaceError, ValidationError, ValueError) as error:
                errors.append({"source_id": source.source_id, "issue_code": str(error)[:160]})
        entries.sort(
            key=lambda item: (
                str(item["category_id"]),
                str(item["name"]),
                str(item["version"]),
            )
        )
        return {
            "sources": [item.model_dump(mode="json") for item in self.sources()],
            "entries": entries,
            "errors": errors,
        }

    def install(self, *, source_id: str, plugin_id: str, version: str) -> dict[str, Any]:
        source = next(
            (item for item in self.sources() if item.source_id == source_id and item.enabled),
            None,
        )
        if source is None:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_SOURCE_NOT_FOUND")
        raw_index = self._download(source.index_url, limit=2 * 1024 * 1024, timeout_seconds=15)
        try:
            index = PluginMarketplaceIndex.model_validate_json(raw_index)
        except ValidationError as error:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_INDEX_INVALID") from error
        entry = next(
            (
                item
                for item in index.entries
                if item.plugin_id == plugin_id and item.version == version
            ),
            None,
        )
        if entry is None:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_ENTRY_NOT_FOUND")
        archive = self._download(entry.archive_url, limit=512 * 1024 * 1024, timeout_seconds=60)
        if hashlib.sha256(archive).hexdigest() != entry.archive_sha256:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_ARCHIVE_HASH_MISMATCH")
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                manifest_info = bundle.getinfo("plugin.json")
                if manifest_info.file_size > 2 * 1024 * 1024:
                    raise PluginMarketplaceError("PLUGIN_MANIFEST_TOO_LARGE")
                manifest = PluginManifest.model_validate_json(bundle.read(manifest_info))
        except (KeyError, OSError, ValidationError, ValueError, zipfile.BadZipFile) as error:
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_ARCHIVE_INVALID") from error
        if (manifest.plugin_id, manifest.version) != (plugin_id, version):
            raise PluginMarketplaceError("PLUGIN_MARKETPLACE_IDENTITY_MISMATCH")
        descriptor, temporary_name = tempfile.mkstemp(prefix="dd-marketplace-", suffix=".zip")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive)
                output.flush()
                os.fsync(output.fileno())
            installed = self.manager.import_bundle(temporary)
        except PluginManagerError:
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return installed
