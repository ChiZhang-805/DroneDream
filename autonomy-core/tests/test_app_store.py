from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore, AssetImportError


def test_startup_preferences_are_durable_and_safe_by_default(tmp_path):
    store = AppStore(tmp_path)

    defaults = store.get_settings()
    assert defaults["default_model_id"] == "gpt-5.4"
    assert defaults["memory_enabled"] is True
    assert defaults["last_map_id"] is None

    updated = store.patch_settings(
        {
            "locale": "en-US",
            "default_model_id": "deepseek-v4-flash",
            "remember_asset_choices": False,
        }
    )
    assert updated["locale"] == "en-US"
    assert updated["default_model_id"] == "deepseek-v4-flash"
    assert updated["remember_asset_choices"] is False


def test_asset_memory_tracks_valid_thread_choices_and_clears_when_disabled(tmp_path):
    store = AppStore(tmp_path)
    thread = store.create_thread("巡检", "gpt-5.4")

    store.patch_thread(
        str(thread["thread_id"]),
        {"selected_map_id": "school-map", "selected_vehicle_id": "dd-x4"},
    )
    remembered = store.get_settings()
    assert remembered["last_map_id"] == "school-map"
    assert remembered["last_vehicle_id"] == "dd-x4"

    cleared = store.patch_settings({"remember_asset_choices": False})
    assert cleared["last_map_id"] is None
    assert cleared["last_vehicle_id"] is None


def test_thread_messages_and_archive_are_durable(tmp_path):
    store = AppStore(tmp_path)
    thread = store.create_thread("取外卖", "gpt-5.4")
    message = store.append_message(
        str(thread["thread_id"]), role="user", kind="text", content="去保安亭取外卖"
    )

    loaded = store.get_thread(str(thread["thread_id"]))
    assert loaded["messages"] == [message]
    assert len(store.list_threads()) == 1

    store.patch_thread(str(thread["thread_id"]), {"archived": True})
    assert store.list_threads() == []
    assert len(store.list_threads(include_archived=True)) == 1


def test_builtin_plugins_are_real_core_capabilities(tmp_path):
    store = AppStore(tmp_path)
    PluginManager(store)
    plugin_ids = {item["plugin_id"] for item in store.list_plugins()}
    assert "navigation.shortest-route" in plugin_ids
    assert "safety.route-clearance" in plugin_ids
    assert "px4.export-track" in plugin_ids
    assert "simulation.gazebo-px4" in plugin_ids
    assert "model.openai" in plugin_ids


def test_asset_id_cannot_escape_asset_repository(tmp_path):
    archive = tmp_path / "escape.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "manifest.json",
            json.dumps({"kind": "map", "asset_id": "../escape", "name": "escape"}),
        )

    store = AppStore(tmp_path / "store")
    with pytest.raises(AssetImportError, match="ASSET_ID_INVALID"):
        store.import_asset_bundle(archive, "map")
    assert not (tmp_path / "store" / "escape").exists()


def test_bundled_qualified_flag_is_recomputed_from_real_receipts(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    archive = bundles / "school-map.zip"
    graph = {
        "schema_version": "dronedream.map-graph.v1",
        "asset_id": "dronedream.school-map.v1",
        "name": "School Map",
        "coordinate_frame": "map_enu",
        "nodes": [
            {
                "node_id": "office",
                "label": "Office",
                "position_m": {"x": 0, "y": 0, "z": 1},
                "semantic": "office",
            },
            {
                "node_id": "pickup",
                "label": "Pickup",
                "position_m": {"x": 1, "y": 0, "z": 1},
                "semantic": "pickup",
            },
        ],
        "edges": [
            {
                "edge_id": "office-pickup",
                "from_node": "office",
                "to_node": "pickup",
                "distance_m": 1,
                "minimum_clearance_m": 1,
                "speed_limit_mps": 1,
            }
        ],
        "named_entities": {"office-launch-pad": "office", "takeout-pickup": "pickup"},
    }
    manifest = {
        "schema_version": "dronedream.asset-bundle.v1",
        "kind": "map",
        "asset_id": "dronedream.school-map.v1",
        "name": "School Map",
        "qualification_status": "qualified",
        "files": {
            "graph": "graph.json",
            "semantic": "semantic.json",
            "world_sdf": "world.sdf",
            "qualification_receipt": "qualification/receipt.json",
        },
    }
    evidence = {
        "status": "verified",
        "gates": {"nominal_closed_loop": True},
    }
    evidence_bytes = json.dumps(evidence).encode()
    qualification = {
        "schema_version": "dronedream.asset-qualification-receipt.v1",
        "mission_evidence_file": "qualification/mission_evidence.json",
        "mission_evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "required_gates": {"nominal_closed_loop": True},
        "gazebo_runtime_verified": True,
        "px4_mission_smoke_verified": True,
        "simulation_execution_ready": True,
        "measurements": {"dynamic_clearance": {"unsafe_collision_count": 0}},
    }
    manifest["qualification"] = qualification
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("graph.json", json.dumps(graph))
        bundle.writestr("semantic.json", '{"coordinate_frame":"ENU"}')
        bundle.writestr("world.sdf", '<sdf version="1.9"/>')
        bundle.writestr("qualification/receipt.json", json.dumps(qualification))
        bundle.writestr("qualification/mission_evidence.json", evidence_bytes)
    (bundles / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "dronedream.bundled-assets.v1",
                "bundles": [
                    {
                        "kind": "map",
                        "asset_id": "dronedream.school-map.v1",
                        "file": archive.name,
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    store = AppStore(tmp_path / "store")
    first = store.seed_bundled_assets(bundles)
    second = store.seed_bundled_assets(bundles)

    assert [item["asset_id"] for item in first] == ["dronedream.school-map.v1"]
    assert second == first
    stored = store.list_assets("map")[0]
    assert stored["status"] == "draft"
    failed = [
        receipt
        for receipt in stored["manifest"]["import_qualification_receipts"]
        if receipt["accepted"] is False
    ]
    assert failed
    assert any("MAP_MATERIAL_PROFILES_MISSING" in receipt["issue_codes"] for receipt in failed)
