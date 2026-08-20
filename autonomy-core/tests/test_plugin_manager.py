from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from dronedream_agent_app.plugin_manager import PluginManager, PluginManagerError
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.contracts import MapAsset, RouteQuery
from dronedream_agent_core.extensions import ExtensionExecutionError
from dronedream_agent_core.plugin_api import (
    ToolEnvironment,
    build_discovered_extension_registry,
    build_snapshot_tool_registry,
)
from dronedream_agent_core.plugin_contracts import PluginGovernancePolicy, PluginManifest


def _manifest(*, version: str = "1.0.0") -> dict[str, object]:
    panel = b'{"title":"Route audit"}\n'
    return {
        "schema_version": "dronedream.plugin-manifest.v1",
        "plugin_id": "example.route-audit",
        "name": "Route Audit",
        "version": version,
        "description": "Inspect a prepared route without actuator access.",
        "publisher": "Example",
        "api_version": "1.0",
        "minimum_app_version": "0.1.0",
        "runtime": {
            "kind": "ui-declarative",
            "protocol_version": "dronedream.plugin.v1",
            "startup_timeout_seconds": 15,
            "call_timeout_seconds": 60,
        },
        "capabilities": [
            {
                "capability_id": "example.route-audit.panel",
                "kind": "ui-panel",
                "name": "Route Audit",
                "description": "Show route evidence.",
                "authority": "read",
                "input_schema": {},
                "output_schema": {},
                "metadata": {"entrypoint": "ui/panel.json"},
            }
        ],
        "permissions": ["mission.read", "ui.panel"],
        "dependencies": [],
        "file_sha256": {"ui/panel.json": hashlib.sha256(panel).hexdigest()},
        "default_enabled": False,
        "removable": True,
        "configuration_schema": {},
    }


def _bundle(path: Path, *, version: str = "1.0.0") -> Path:
    panel = b'{"title":"Route audit"}\n'
    manifest = _manifest(version=version)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest))
        archive.writestr("ui/panel.json", panel)
    return path


def _official_index(root: Path, *, version: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    archive = _bundle(root / f"route-audit-{version}.zip", version=version)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (root / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "dronedream.official-plugin-index.v1",
                "plugins": [
                    {
                        "plugin_id": "example.route-audit",
                        "version": version,
                        "file": archive.name,
                        "sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _graph() -> MapAsset:
    return MapAsset.model_validate(
        {
            "asset_id": "test.map",
            "name": "Test",
            "nodes": [
                {
                    "node_id": "start",
                    "label": "Start",
                    "position_m": {"x": 0, "y": 0, "z": 1},
                    "semantic": "launch",
                },
                {
                    "node_id": "goal",
                    "label": "Goal",
                    "position_m": {"x": 2, "y": 0, "z": 1},
                    "semantic": "pickup",
                },
            ],
            "edges": [
                {
                    "edge_id": "start-goal",
                    "from_node": "start",
                    "to_node": "goal",
                    "distance_m": 2,
                    "minimum_clearance_m": 1,
                    "speed_limit_mps": 1,
                    "qualification": "flight-verified",
                    "evidence_sha256": "a" * 64,
                }
            ],
            "named_entities": {"start": "start", "goal": "goal"},
        }
    )


def _external_harness_manifest(root: Path) -> PluginManifest:
    executable = b"snapshot-bound MCP executable"
    (root / "plugin.exe").write_bytes(executable)
    return PluginManifest.model_validate(
        {
            "plugin_id": "example.external-harness",
            "name": "External Harness",
            "version": "1.0.0",
            "description": "Extends prompt preparation and provides a task tool.",
            "publisher": "Example",
            "runtime": {
                "kind": "mcp-stdio",
                "command": ["plugin.exe"],
                "protocol_version": "dronedream.plugin.v1",
                "startup_timeout_seconds": 15,
                "call_timeout_seconds": 60,
            },
            "capabilities": [
                {
                    "capability_id": "example.external-harness.prompt",
                    "kind": "prompt-pack",
                    "name": "External prompt",
                    "description": "Adds a tested external prompt fragment.",
                    "authority": "plan",
                    "input_schema": {"type": "object"},
                    "output_schema": {
                        "type": "object",
                        "required": ["value"],
                        "properties": {"value": {"type": "object"}},
                    },
                    "required_permissions": ["mission.read"],
                    "metadata": {"extension_hook": "augment_prompt"},
                },
                {
                    "capability_id": "example.external-harness.echo",
                    "kind": "tool",
                    "name": "External echo",
                    "description": "Returns structured task data through MCP.",
                    "authority": "plan",
                    "input_schema": {"type": "object"},
                    "output_schema": {
                        "type": "object",
                        "required": ["echo", "configuration"],
                        "properties": {
                            "echo": {"type": "object"},
                            "configuration": {"type": "object"},
                        },
                    },
                    "required_permissions": [],
                    "metadata": {},
                },
                {
                    "capability_id": "example.external-harness.output-guard",
                    "kind": "plan-validator",
                    "name": "External output guard",
                    "description": "Validates a structured output with its own permission scope.",
                    "authority": "plan",
                    "input_schema": {"type": "object"},
                    "output_schema": {
                        "type": "object",
                        "required": ["value"],
                        "properties": {"value": {"type": "object"}},
                    },
                    "required_permissions": ["mission.read", "evidence.write"],
                    "metadata": {"extension_hook": "validate_output"},
                },
            ],
            "permissions": ["process.spawn", "mission.read", "evidence.write"],
            "file_sha256": {"plugin.exe": hashlib.sha256(executable).hexdigest()},
            "placement": {
                "category_id": "models",
                "category_label": "模型与提示词",
                "slot_id": "models.prompt-packs",
                "slot_label": "提示词包",
                "activation_mode": "pipeline",
                "scope": "mission",
                "failure_mode": "fail-closed",
                "swap_policy": "next-mission",
            },
            "configuration_schema": {"type": "object"},
        }
    )


def _external_map_importer_manifest(root: Path) -> PluginManifest:
    executable = b"asset converter"
    (root / "plugin.exe").write_bytes(executable)
    return PluginManifest.model_validate(
        {
            "plugin_id": "example.external-map-importer",
            "name": "External map importer",
            "version": "1.0.0",
            "description": "Converts an external map into a canonical staged bundle.",
            "publisher": "Example",
            "runtime": {"kind": "mcp-stdio", "command": ["plugin.exe"]},
            "capabilities": [
                {
                    "capability_id": "example.external-map-importer.convert",
                    "kind": "map-importer",
                    "name": "Map converter",
                    "description": "Writes a hash-declared canonical map bundle.",
                    "authority": "plan",
                    "input_schema": {"type": "object"},
                    "output_schema": {
                        "type": "object",
                        "required": ["output_sha256"],
                        "properties": {"output_sha256": {"type": "string", "minLength": 64}},
                    },
                    "metadata": {"extension_hook": "import_asset"},
                }
            ],
            "permissions": ["process.spawn", "asset.read", "asset.write-staging"],
            "file_sha256": {"plugin.exe": hashlib.sha256(executable).hexdigest()},
            "placement": {
                "category_id": "assets",
                "category_label": "地图与无人机",
                "slot_id": "assets.map-importer",
                "slot_label": "地图导入器",
                "activation_mode": "single",
                "scope": "general",
                "failure_mode": "fail-closed",
                "swap_policy": "next-mission",
            },
        }
    )


class _FakeMcpClient:
    instances: list[_FakeMcpClient] = []

    def __init__(self, *, configuration=None, **_kwargs):
        self.configuration = configuration or {}
        self.permissions = list(_kwargs.get("permissions", []))
        self.host_services = _kwargs.get("host_services")
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return None

    def call_tool(self, name, arguments):
        if name == "example.external-map-importer.convert":
            assert self.host_services is not None
            read_result = self.host_services(
                "dronedream/filesystem/read",
                {"root": arguments["input_root"], "path": arguments["input_path"]},
            )
            assert base64.b64decode(read_result["body_base64"]) == b"source"
            rendered = b"canonical map bundle"
            self.host_services(
                "dronedream/filesystem/write",
                {
                    "root": arguments["output_root"],
                    "path": arguments["output_path"],
                    "body_base64": base64.b64encode(rendered).decode("ascii"),
                },
            )
            return {"output_sha256": hashlib.sha256(rendered).hexdigest()}
        if name == "example.external-harness.prompt":
            return {
                "value": {
                    **arguments["value"],
                    "external_prompt": self.configuration.get("tone"),
                }
            }
        if name == "example.external-harness.output-guard":
            return {"value": {**arguments["value"], "external_guard": True}}
        return {"echo": arguments, "configuration": self.configuration}


class _InvalidOutputMcpClient(_FakeMcpClient):
    def call_tool(self, name, arguments):
        if name == "example.external-harness.prompt":
            return {"unexpected": arguments}
        return super().call_tool(name, arguments)


def test_builtin_plugins_are_discovered_and_model_catalog_is_live(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    plugins = manager.list_plugins()

    assert len(plugins) >= 8
    assert {item["id"] for item in manager.model_catalog()} == {
        "gpt-4.1",
        "gpt-5.1",
        "gpt-5.4",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "kimi-k2.6",
        "kimi-k3",
    }
    assert all(item["package_sha256"] for item in plugins)


def test_tool_registry_is_built_from_plugin_snapshot_and_receipts_bind_package(tmp_path):
    store = AppStore(tmp_path)
    manager = PluginManager(store)
    semantic = tmp_path / "semantic.json"
    semantic.write_text("{}", encoding="utf-8")
    snapshot = manager.snapshot()
    registry = manager.build_tool_registry(
        environment=ToolEnvironment(
            map_graph=_graph(),
            semantic_path=semantic,
            vehicle_diameter_m=0.6,
            vehicle_height_m=0.4,
            waypoint_hold_seconds=0.4,
        ),
        snapshot=snapshot,
    )

    route, receipt = registry.call(
        "navigation.shortest-route", RouteQuery(start_node="start", goal_node="goal")
    )

    assert route.node_ids == ["start", "goal"]
    assert receipt.plugin_id == "navigation.shortest-route"
    assert receipt.plugin_package_sha256
    assert receipt.plugin_package_sha256 == next(
        item.package_sha256
        for item in snapshot.plugins
        if item.plugin_id == "navigation.shortest-route"
    )
    usage = store.summarize_plugin_usage("navigation.shortest-route")
    assert usage["calls"] == 1
    assert usage["successes"] == 1
    assert usage["input_bytes"] > 0
    assert usage["output_bytes"] > 0


def test_enterprise_governance_rejects_unapproved_publisher_and_local_trust(tmp_path):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    policy = PluginGovernancePolicy(
        policy_id="managed-flight-lab",
        mode="managed",
        allowed_publishers=["DroneDream"],
        require_verified_signatures=True,
        allow_local_approval=False,
    )
    manager.set_governance_policy(policy)

    with pytest.raises(PluginManagerError, match="GOVERNANCE_PUBLISHER_NOT_ALLOWED"):
        manager.import_bundle(_bundle(tmp_path / "route-audit.zip"))

    relaxed = policy.model_copy(update={"allowed_publishers": ["Example"]})
    manager.set_governance_policy(relaxed)
    imported = manager.import_bundle(_bundle(tmp_path / "route-audit-allowed.zip"))
    assert imported["plugin_id"] == "example.route-audit"
    with pytest.raises(PluginManagerError, match="GOVERNANCE_LOCAL_APPROVAL_DISABLED"):
        manager.approve_local_package("example.route-audit")
    decisions = store.list_plugin_governance_decisions("example.route-audit")
    assert any(not bool(item["accepted"]) for item in decisions)


def test_single_slot_switches_implementation_without_leaving_required_slot_empty(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    switched = manager.enable("navigation.clearance-first-route")

    assert switched["replaced_plugins"] == ["navigation.shortest-route"]
    by_id = {item["plugin_id"]: item for item in manager.list_plugins()}
    assert by_id["navigation.clearance-first-route"]["enabled"] is True
    assert by_id["navigation.shortest-route"]["enabled"] is False
    with pytest.raises(PluginManagerError, match="SLOT_REQUIRES_ONE_ENABLED"):
        manager.disable("navigation.clearance-first-route")


def test_required_single_slots_have_exactly_one_active_implementation(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    snapshot = manager.snapshot()
    active_ids = {entry.plugin_id for entry in snapshot.plugins}

    assert "navigation.shortest-route" in active_ids
    assert "navigation.clearance-first-route" not in active_ids
    assert "workflow.balanced" in active_ids
    assert "workflow.deliberate" not in active_ids


def test_multiple_slot_keeps_independent_plugins_enabled(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    first = manager.enable("general.mission-risk-profile")
    second = manager.enable("general.constraint-coverage")

    assert first["replaced_plugins"] == []
    assert second["replaced_plugins"] == []
    enabled = {
        item["plugin_id"]
        for item in manager.list_plugins()
        if item["enabled"] and item["placement"]["slot_id"] == "general.mission-advisors"
    }
    assert enabled == {"general.mission-risk-profile", "general.constraint-coverage"}


def test_plugin_configuration_is_bound_into_task_snapshot(tmp_path):
    store = AppStore(tmp_path)
    manager = PluginManager(store)
    first = manager.snapshot()

    store.save_plugin_configuration("model.openai", {"region": "us"})
    second = manager.snapshot()

    first_entry = next(item for item in first.plugins if item.plugin_id == "model.openai")
    second_entry = next(item for item in second.plugins if item.plugin_id == "model.openai")
    assert first_entry.configuration_sha256 != second_entry.configuration_sha256
    assert first_entry.configuration == {}
    assert second_entry.configuration == {"region": "us"}


def test_plugin_configuration_rejects_inline_secrets_and_allows_safe_runtime_settings(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    saved = manager.configure(
        "runtime.anomaly-battery",
        {"minimum_battery_percent": 25},
    )

    assert saved["configuration"] == {"minimum_battery_percent": 25}
    with pytest.raises(PluginManagerError, match="INLINE_SECRET_FORBIDDEN"):
        manager.configure("runtime.anomaly-battery", {"api_key": "must-not-be-stored"})


def test_external_mcp_hooks_and_tools_rebuild_from_frozen_snapshot(tmp_path, monkeypatch):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    bundle_root = tmp_path / "external"
    bundle_root.mkdir()
    manifest = _external_harness_manifest(bundle_root)
    store.upsert_plugin(
        manifest=manifest,
        package_sha256="c" * 64,
        bundle_root=bundle_root,
        builtin=False,
        enabled=True,
        status="healthy",
        health="healthy",
    )
    store.save_plugin_configuration(manifest.plugin_id, {"tone": "concise"})
    snapshot = manager.snapshot()

    _FakeMcpClient.instances.clear()
    monkeypatch.setattr("dronedream_agent_app.plugin_manager.McpStdioClient", _FakeMcpClient)
    manager_extensions = manager.build_extension_registry(snapshot=snapshot)
    prompt, receipts = manager_extensions.invoke_pipeline(
        "models.prompt-packs", "augment_prompt", {"base": True}
    )
    assert prompt == {"base": True, "external_prompt": "concise"}
    assert receipts[-1].plugin_id == manifest.plugin_id
    guarded, guard_receipts = manager_extensions.invoke_pipeline(
        "models.prompt-packs", "validate_output", {"structured": True}
    )
    assert guarded == {"structured": True, "external_guard": True}
    assert guard_receipts[-1].capability_id == "example.external-harness.output-guard"

    manager.disable(manifest.plugin_id)
    prompt_after_disable, _ = manager_extensions.invoke_pipeline(
        "models.prompt-packs", "augment_prompt", {"base": True}
    )
    assert prompt_after_disable["external_prompt"] == "concise"

    monkeypatch.setattr("dronedream_agent_core.plugin_api.McpStdioClient", _FakeMcpClient)
    restored_extensions = build_discovered_extension_registry(snapshot)
    restored_prompt, _ = restored_extensions.invoke_pipeline(
        "models.prompt-packs", "augment_prompt", {"base": True}
    )
    assert restored_prompt["external_prompt"] == "concise"

    semantic = tmp_path / "semantic.json"
    semantic.write_text("{}", encoding="utf-8")
    registry = build_snapshot_tool_registry(
        ToolEnvironment(
            map_graph=_graph(),
            semantic_path=semantic,
            vehicle_diameter_m=0.6,
            vehicle_height_m=0.4,
            waypoint_hold_seconds=0.4,
        ),
        snapshot,
    )
    output, receipt = registry.call("example.external-harness.echo", {"mission": "inspect"})
    assert output == {
        "echo": {"mission": "inspect"},
        "configuration": {"tone": "concise"},
    }
    assert receipt.plugin_id == manifest.plugin_id
    assert {tuple(client.permissions) for client in _FakeMcpClient.instances} == {
        (),
        ("mission.read",),
        ("mission.read", "evidence.write"),
    }


def test_external_mcp_hook_invalid_output_is_fail_closed_and_quarantined(tmp_path, monkeypatch):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    bundle_root = tmp_path / "external"
    bundle_root.mkdir()
    manifest = _external_harness_manifest(bundle_root)
    store.upsert_plugin(
        manifest=manifest,
        package_sha256="e" * 64,
        bundle_root=bundle_root,
        builtin=False,
        enabled=True,
        status="healthy",
        health="healthy",
    )
    snapshot = manager.snapshot()
    monkeypatch.setattr(
        "dronedream_agent_app.plugin_manager.McpStdioClient",
        _InvalidOutputMcpClient,
    )

    extensions = manager.build_extension_registry(snapshot=snapshot)
    with pytest.raises(ExtensionExecutionError, match="PLUGIN_HOOK_FAILED"):
        extensions.invoke_pipeline("models.prompt-packs", "augment_prompt", {"base": True})

    quarantined = store.get_plugin(manifest.plugin_id)
    assert quarantined["enabled"] is False
    assert quarantined["status"] == "quarantined"
    assert quarantined["health"] == "failed"


def test_uninstall_keeps_active_task_bundle_and_catalog_unchanged(tmp_path):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    manager.import_bundle(_bundle(tmp_path / "plugin.zip"))
    manager.approve_local_package("example.route-audit")
    manager.enable("example.route-audit")
    manager.set_disable_guard(
        lambda _plugin_id, policy: (_ for _ in ()).throw(RuntimeError(policy))
    )

    with pytest.raises(PluginManagerError, match="UNINSTALL_REQUIRES_IDLE:restart"):
        manager.uninstall("example.route-audit")

    plugin = store.get_plugin("example.route-audit")
    assert plugin["enabled"] is True
    assert plugin["status"] == "healthy"
    assert (store.plugins_root / "example.route-audit").is_dir()


def test_external_asset_importer_only_writes_staging_then_core_installs(tmp_path, monkeypatch):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    root = tmp_path / "map-importer"
    root.mkdir()
    manifest = _external_map_importer_manifest(root)
    store.upsert_plugin(
        manifest=manifest,
        package_sha256="d" * 64,
        bundle_root=root,
        builtin=False,
        enabled=True,
        status="healthy",
        health="healthy",
    )
    store.set_plugin_lifecycles(
        {
            "assets.canonical-map-importer": {
                "enabled": False,
                "status": "disabled",
                "health": "unknown",
            },
            manifest.plugin_id: {
                "enabled": True,
                "status": "healthy",
                "health": "healthy",
            },
        }
    )
    source = tmp_path / "source-map.bin"
    source.write_bytes(b"source")
    installed: dict[str, object] = {}

    def install(path, kind):
        installed.update({"kind": kind, "payload": Path(path).read_bytes()})
        return {"asset_id": "converted.map", "kind": kind}

    monkeypatch.setattr(store, "import_asset_bundle", install)
    monkeypatch.setattr("dronedream_agent_app.plugin_manager.McpStdioClient", _FakeMcpClient)

    result = manager.import_asset(kind="map", archive=source)

    assert installed == {"kind": "map", "payload": b"canonical map bundle"}
    assert result["asset_id"] == "converted.map"
    assert result["importer_plugin_id"] == manifest.plugin_id
    assert result["source_sha256"] == hashlib.sha256(b"source").hexdigest()


def test_pipeline_plugins_coexist_and_snapshot_configuration_is_immutable(tmp_path):
    manager = PluginManager(AppStore(tmp_path))
    snapshot = manager.snapshot()

    enabled = manager.enable("prompt.payload-custody")
    manager.configure("runtime.anomaly-battery", {"minimum_battery_percent": 30})

    assert enabled["replaced_plugins"] == []
    prompt_plugins = {
        item.plugin_id
        for item in manager.snapshot().plugins
        if item.plugin_id.startswith("prompt.")
    }
    assert {"prompt.structured-discipline", "prompt.payload-custody"} <= prompt_plugins
    frozen_battery = next(
        item for item in snapshot.plugins if item.plugin_id == "runtime.anomaly-battery"
    )
    assert frozen_battery.configuration == {}


def test_persona_profile_atomically_selects_single_slots_and_optional_plugins(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    applied = manager.apply_profile("harness.profile-payload-delivery")
    active = {item.plugin_id for item in manager.snapshot().plugins}

    assert applied["profile_plugin_id"] == "harness.profile-payload-delivery"
    assert {
        "harness.profile-payload-delivery",
        "workflow.deliberate",
        "models.role-adversarial",
        "context.structured-window",
        "tools.router-safety-first",
        "navigation.stability-first-route",
        "safety.conservative-route-clearance",
        "px4.stability-track",
        "prompt.payload-custody",
        "validation.energy-reserve",
    } <= active
    assert {
        "harness.profile-balanced",
        "workflow.balanced",
        "navigation.shortest-route",
        "safety.route-clearance",
        "px4.export-track",
    }.isdisjoint(active)


def test_all_first_party_persona_profiles_produce_a_valid_snapshot(tmp_path):
    manager = PluginManager(AppStore(tmp_path))
    profile_ids = [
        item["plugin_id"]
        for item in manager.list_plugins()
        if item["placement"]["slot_id"] == "harness.profile"
    ]

    for profile_id in profile_ids:
        manager.apply_profile(str(profile_id))
        snapshot = manager.snapshot()
        assert (
            sum(entry.plugin_id.startswith("harness.profile-") for entry in snapshot.plugins) == 1
        )


def test_profile_failure_restores_the_previous_enabled_catalog(tmp_path, monkeypatch):
    manager = PluginManager(AppStore(tmp_path))
    before = {str(item["plugin_id"]): bool(item["enabled"]) for item in manager.list_plugins()}

    def fail_snapshot(*, thread_id=None):
        raise PluginManagerError("SYNTHETIC_PROFILE_COMMIT_FAILURE")

    monkeypatch.setattr(manager, "snapshot", fail_snapshot)
    with pytest.raises(PluginManagerError, match="SYNTHETIC_PROFILE_COMMIT_FAILURE"):
        manager.apply_profile("harness.profile-indoor-guardian")

    after = {str(item["plugin_id"]): bool(item["enabled"]) for item in manager.list_plugins()}
    assert after == before


def test_manifest_swap_policy_is_passed_to_runtime_guard(tmp_path):
    manager = PluginManager(AppStore(tmp_path))
    calls: list[tuple[str, str]] = []
    manager.set_disable_guard(
        lambda plugin_id, swap_policy: calls.append((plugin_id, swap_policy)) or []
    )

    manager.disable("runtime.anomaly-tracking")
    manager.enable("navigation.clearance-first-route")

    assert ("runtime.anomaly-tracking", "safe-hold") in calls
    assert ("navigation.shortest-route", "next-mission") in calls


def test_failed_single_slot_guard_restores_the_previous_live_plugin(tmp_path):
    store = AppStore(tmp_path)
    manager = PluginManager(store)
    manager.set_disable_guard(
        lambda _plugin_id, _policy: (_ for _ in ()).throw(RuntimeError("busy"))
    )

    with pytest.raises(PluginManagerError, match="PLUGIN_SWAP_FAILED:busy"):
        manager.enable("navigation.clearance-first-route")

    original = store.get_plugin("navigation.shortest-route")
    replacement = store.get_plugin("navigation.clearance-first-route")
    assert original["enabled"] is True
    assert original["status"] == "healthy"
    assert replacement["enabled"] is False


def test_failed_profile_guard_restores_all_draining_plugins(tmp_path):
    store = AppStore(tmp_path)
    manager = PluginManager(store)
    before = {
        str(item["plugin_id"]): (bool(item["enabled"]), str(item["status"]))
        for item in store.list_plugins()
    }
    manager.set_disable_guard(
        lambda _plugin_id, _policy: (_ for _ in ()).throw(RuntimeError("busy"))
    )

    with pytest.raises(PluginManagerError, match="PLUGIN_PROFILE_DRAIN_FAILED:busy"):
        manager.apply_profile("harness.profile-indoor-guardian")

    after = {
        str(item["plugin_id"]): (bool(item["enabled"]), str(item["status"]))
        for item in store.list_plugins()
    }
    assert after == before


def test_batch_plugin_lifecycle_update_rolls_back_on_missing_member(tmp_path):
    store = AppStore(tmp_path)
    PluginManager(store)
    before = store.get_plugin("prompt.payload-custody")

    with pytest.raises(KeyError):
        store.set_plugin_lifecycles(
            {
                "prompt.payload-custody": {
                    "enabled": True,
                    "status": "healthy",
                    "health": "healthy",
                },
                "missing.plugin": {"enabled": True},
            }
        )

    after = store.get_plugin("prompt.payload-custody")
    assert after["enabled"] == before["enabled"]
    assert after["status"] == before["status"]


def test_disabled_official_plugin_activates_new_staged_version_on_app_upgrade(tmp_path):
    store = AppStore(tmp_path / "store")
    official_root = _official_index(tmp_path / "official", version="1.0.0")
    PluginManager(store, official_plugins_root=official_root)

    _official_index(official_root, version="1.1.0")
    PluginManager(store, official_plugins_root=official_root)

    upgraded = store.get_plugin("example.route-audit")
    assert upgraded["version"] == "1.1.0"
    assert upgraded["enabled"] is False


def test_plugin_bundle_install_enable_disable_update_rollback_and_uninstall(tmp_path):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)

    installed = manager.import_bundle(_bundle(tmp_path / "plugin-1.zip"))
    assert installed["status"] == "disabled"
    assert installed["trust_status"] == "unverified"
    manager.approve_local_package("example.route-audit")
    assert manager.enable("example.route-audit")["health"] == "healthy"
    assert manager.disable("example.route-audit")["status"] == "disabled"

    updated = manager.import_bundle(_bundle(tmp_path / "plugin-2.zip", version="1.1.0"))
    assert updated["version"] == "1.0.0"
    assert updated["staged_version"] == "1.1.0"
    assert len(store.list_plugin_versions("example.route-audit")) == 2
    assert manager.activate_version("example.route-audit", "1.1.0")["version"] == "1.1.0"
    assert manager.rollback("example.route-audit", "1.0.0")["version"] == "1.0.0"

    removed = manager.uninstall("example.route-audit")
    assert removed["status"] == "uninstalled"
    assert not (store.plugins_root / "example.route-audit").exists()


def test_health_gated_promotion_automatically_restores_enabled_previous_version(
    tmp_path, monkeypatch
):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    manager.import_bundle(_bundle(tmp_path / "plugin-1.zip"))
    manager.approve_local_package("example.route-audit")
    manager.enable("example.route-audit")
    manager.import_bundle(_bundle(tmp_path / "plugin-2.zip", version="1.1.0"))
    approved = manager.approve_local_version("example.route-audit", "1.1.0")
    assert approved["trust_status"] == "local-approved"
    assert store.get_plugin("example.route-audit")["version"] == "1.0.0"
    original_healthcheck = manager.healthcheck

    def version_healthcheck(plugin_id: str):
        if store.get_plugin(plugin_id)["version"] == "1.1.0":
            raise PluginManagerError("NEW_VERSION_HEALTH_FAILED")
        return original_healthcheck(plugin_id)

    monkeypatch.setattr(manager, "healthcheck", version_healthcheck)
    with pytest.raises(PluginManagerError, match="PROMOTION_ROLLED_BACK"):
        manager.promote_version("example.route-audit", "1.1.0")

    restored = store.get_plugin("example.route-audit")
    assert restored["version"] == "1.0.0"
    assert restored["enabled"] is True
    assert any(
        event["operation"] == "rollback"
        and bool(event["accepted"])
        and "PLUGIN_PROMOTION_AUTO_ROLLBACK" in event["receipt"]["issue_codes"]
        for event in store.list_plugin_events("example.route-audit")
    )


def test_plugin_import_rejects_path_traversal_and_uncertified_actuation(tmp_path):
    manager = PluginManager(AppStore(tmp_path / "store"))
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../plugin.json", "{}")
    with pytest.raises(PluginManagerError, match="PATH_TRAVERSAL"):
        manager.import_bundle(traversal)

    manifest = _manifest()
    manifest["permissions"] = ["process.spawn", "vehicle.actuate"]
    manifest["runtime"] = {
        "kind": "mcp-stdio",
        "command": ["plugin.exe"],
        "protocol_version": "2025-06-18",
        "startup_timeout_seconds": 15,
        "call_timeout_seconds": 60,
    }
    capability = manifest["capabilities"][0]  # type: ignore[index]
    capability["authority"] = "actuate"  # type: ignore[index]
    capability["kind"] = "tool"  # type: ignore[index]
    capability["input_schema"] = {"type": "object"}  # type: ignore[index]
    capability["output_schema"] = {"type": "object"}  # type: ignore[index]
    archive_path = tmp_path / "actuate.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("plugin.json", json.dumps(manifest))
        archive.writestr("ui/panel.json", b'{"title":"Route audit"}\n')
    with pytest.raises(PluginManagerError, match="ACTUATION_NOT_CERTIFIED"):
        manager.import_bundle(archive_path)


def test_safety_kernel_plugins_cannot_be_disabled_or_uninstalled(tmp_path):
    manager = PluginManager(AppStore(tmp_path))

    with pytest.raises(PluginManagerError, match="REQUIRED_BY_SAFETY_KERNEL"):
        manager.disable("runtime.safe-hold")
    with pytest.raises(PluginManagerError, match="NOT_UNINSTALLABLE"):
        manager.uninstall("simulation.gazebo-px4")


def test_disabling_model_provider_removes_its_models_without_affecting_others(tmp_path):
    manager = PluginManager(AppStore(tmp_path))
    snapshot = manager.snapshot()

    manager.disable("model.kimi")

    providers = {item["provider"] for item in manager.model_catalog()}
    assert providers == {"openai", "deepseek"}
    assert manager.provider_for_model("gpt-5.4") == "openai"
    with pytest.raises(PluginManagerError, match="MODEL_PROVIDER_PLUGIN_UNAVAILABLE"):
        manager.provider_for_model("kimi-k3")
    with pytest.raises(PluginManagerError, match="PLUGIN_SNAPSHOT_CAPABILITY_DRIFT"):
        manager.assert_snapshot_active(snapshot, {"model.kimi.structured"})


def test_enabled_dependency_prevents_unsafe_plugin_withdrawal(tmp_path):
    store = AppStore(tmp_path / "store")
    manager = PluginManager(store)
    manager.import_bundle(_bundle(tmp_path / "plugin.zip"))
    manager.approve_local_package("example.route-audit")
    manager.enable("example.route-audit")
    dependent_value = _manifest()
    dependent_value.update(
        {
            "plugin_id": "example.dependent-panel",
            "name": "Dependent Panel",
            "dependencies": [
                {
                    "plugin_id": "example.route-audit",
                    "version": ">=1.0.0",
                    "optional": False,
                }
            ],
        }
    )
    dependent = PluginManifest.model_validate(dependent_value)
    store.upsert_plugin(
        manifest=dependent,
        package_sha256="b" * 64,
        bundle_root=tmp_path,
        builtin=False,
        enabled=True,
        status="healthy",
        health="healthy",
    )

    with pytest.raises(PluginManagerError, match="PLUGIN_REQUIRED_BY_ENABLED"):
        manager.disable("example.route-audit")
    with pytest.raises(PluginManagerError, match="PLUGIN_REQUIRED_BY"):
        manager.uninstall("example.route-audit")
