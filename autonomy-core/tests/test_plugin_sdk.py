from __future__ import annotations

import json
import zipfile

from dronedream_agent_core.plugin_contracts import PluginManifest
from dronedream_agent_core.plugin_sdk import (
    build_plugin_bundle,
    generate_publisher_key,
    sandbox_plugin_bundle,
    scaffold_plugin,
    validate_plugin_source,
)
from dronedream_agent_core.plugin_trust import PluginTrustStore


def test_ui_scaffold_pack_sign_verify_and_sandbox(tmp_path):
    source = scaffold_plugin(
        tmp_path / "source",
        plugin_id="example.telemetry-panel",
        name="Telemetry Panel",
        publisher="Example Labs",
        kind="ui",
    )
    source_state = validate_plugin_source(source)
    assert source_state["ready_to_package"] is True

    key_path = tmp_path / "publisher-key.json"
    public = generate_publisher_key(
        key_path,
        key_id="example.publisher.v1",
        publisher="Example Labs",
    )
    bundle = tmp_path / "telemetry-panel.zip"
    built = build_plugin_bundle(source, bundle, signing_key=key_path)
    assert built["signed"] is True

    with zipfile.ZipFile(bundle) as archive:
        manifest = PluginManifest.model_validate_json(archive.read("plugin.json"))
        names = set(archive.namelist())
    assert "sbom.cdx.json" in names
    assert "publisher-key.json" not in names
    assert manifest.provenance.sbom_sha256 == manifest.file_sha256["sbom.cdx.json"]

    trust = PluginTrustStore(tmp_path / "trust.json")
    trust.add_publisher(
        key_id=str(public["key_id"]),
        publisher=str(public["publisher"]),
        public_key_base64=str(public["public_key_base64"]),
    )
    decision = trust.verify(manifest, str(built["package_sha256"]))
    assert decision.status == "verified"

    sandbox = sandbox_plugin_bundle(bundle)
    assert sandbox["health"] == "healthy"
    assert sandbox["quarantined"] is False
    assert sandbox["lifecycle_events"] >= 4


def test_mcp_scaffold_requires_built_bundled_executable(tmp_path):
    source = scaffold_plugin(
        tmp_path / "mcp",
        plugin_id="example.inspector",
        name="Inspector",
        publisher="Example Labs",
    )
    state = validate_plugin_source(source)
    assert state["ready_to_package"] is False
    assert state["missing_runtime"] == ["bin/plugin.exe"]
    manifest = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["runtime"]["kind"] == "mcp-stdio"
