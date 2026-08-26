from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.plugin_marketplace import (
    PluginMarketplaceError,
    PluginMarketplaceService,
)
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.plugin_contracts import (
    PluginMarketplaceIndex,
    PluginMarketplaceSource,
)


def _bundle(path: Path) -> Path:
    panel = b'{"title":"Route audit"}\n'
    manifest = {
        "schema_version": "dronedream.plugin-manifest.v1",
        "plugin_id": "example.route-audit",
        "name": "Route Audit",
        "version": "1.0.0",
        "description": "Inspect a prepared route without actuator access.",
        "publisher": "Example",
        "runtime": {"kind": "ui-declarative"},
        "capabilities": [
            {
                "capability_id": "example.route-audit.panel",
                "kind": "ui-panel",
                "name": "Route Audit",
                "description": "Show route evidence.",
                "authority": "read",
                "metadata": {"entrypoint": "ui/panel.json"},
            }
        ],
        "permissions": ["mission.read", "ui.panel"],
        "file_sha256": {"ui/panel.json": hashlib.sha256(panel).hexdigest()},
    }
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("plugin.json", json.dumps(manifest))
        bundle.writestr("ui/panel.json", panel)
    return path


def _marketplace(tmp_path: Path) -> tuple[PluginMarketplaceService, bytes, bytes]:
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    service = PluginMarketplaceService(store, manager)
    source = PluginMarketplaceSource(
        source_id="official-lab",
        name="Official lab",
        index_url="https://plugins.example.test/index.json",
    )
    service.replace_sources([source])
    archive_path = _bundle(tmp_path / "route-audit.zip")
    archive = archive_path.read_bytes()
    index = (
        PluginMarketplaceIndex.model_validate(
            {
                "generated_at": datetime.now(UTC),
                "entries": [
                    {
                        "plugin_id": "example.route-audit",
                        "version": "1.0.0",
                        "name": "Route Audit",
                        "description": "Inspect a route.",
                        "publisher": "Example",
                        "archive_url": "https://plugins.example.test/route-audit.zip",
                        "archive_sha256": hashlib.sha256(archive).hexdigest(),
                        "category_id": "planning",
                    }
                ],
            }
        )
        .model_dump_json()
        .encode()
    )
    return service, index, archive


def test_marketplace_catalog_and_install_are_digest_pinned(tmp_path, monkeypatch):
    service, index, archive = _marketplace(tmp_path)

    def download(url: str, **_kwargs) -> bytes:
        return index if url.endswith("index.json") else archive

    monkeypatch.setattr(service, "_download", download)
    catalog = service.catalog()
    assert catalog["entries"][0]["source_id"] == "official-lab"

    installed = service.install(
        source_id="official-lab",
        plugin_id="example.route-audit",
        version="1.0.0",
    )
    assert installed["plugin_id"] == "example.route-audit"


def test_marketplace_rejects_archive_hash_drift(tmp_path, monkeypatch):
    service, index, _archive = _marketplace(tmp_path)

    def download(url: str, **_kwargs) -> bytes:
        return index if url.endswith("index.json") else b"tampered"

    monkeypatch.setattr(service, "_download", download)
    with pytest.raises(PluginMarketplaceError, match="ARCHIVE_HASH_MISMATCH"):
        service.install(
            source_id="official-lab",
            plugin_id="example.route-audit",
            version="1.0.0",
        )


def test_marketplace_sources_refuse_insecure_transport(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        PluginMarketplaceSource(
            source_id="insecure-source",
            name="Insecure",
            index_url="http://plugins.example.test/index.json",
        )
