"""Exercise an official plugin through ZIP import, MCP health, registry, and receipt."""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dronedream_agent_app.plugin_manager import PluginManager, PluginManagerError
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.contracts import MapAsset
from dronedream_agent_core.plugin_api import ToolEnvironment
from dronedream_agent_core.plugin_contracts import PluginManifest
from dronedream_agent_core.plugin_trust import unsigned_manifest_sha256


def _map() -> MapAsset:
    return MapAsset.model_validate(
        {
            "asset_id": "plugin-verification-map",
            "name": "Plugin Verification Map",
            "nodes": [
                {
                    "node_id": "office",
                    "label": "Office",
                    "position_m": {"x": 0, "y": 0, "z": 1},
                    "semantic": "launch",
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
            "named_entities": {"office": "office", "pickup": "pickup"},
        }
    )


def _fault_bundle(
    source_archive: Path,
    output_archive: Path,
    signing_key: Ed25519PrivateKey,
) -> Path:
    with zipfile.ZipFile(source_archive) as source:
        manifest = json.loads(source.read("plugin.json"))
        executable = source.read("bin/mission-evidence-gate.exe")
    manifest["plugin_id"] = "dronedream.fault-injection"
    manifest["name"] = "Fault Injection"
    manifest["publisher"] = "DroneDream Verification"
    manifest["runtime"]["command"].append("--manifest-sha256")
    manifest.pop("signature", None)
    manifest_sha256 = unsigned_manifest_sha256(PluginManifest.model_validate(manifest))
    manifest["signature"] = {
        "algorithm": "ed25519",
        "publisher_key_id": "dronedream-verification.fault.release",
        "signed_manifest_sha256": manifest_sha256,
        "signature_base64": base64.b64encode(
            signing_key.sign(bytes.fromhex(manifest_sha256))
        ).decode("ascii"),
        "signed_at": datetime.now(UTC).isoformat(),
    }
    with zipfile.ZipFile(output_archive, "w") as output:
        output.writestr("plugin.json", json.dumps(manifest))
        output.writestr("bin/mission-evidence-gate.exe", executable)
    return output_archive


def verify(official_plugins_root: Path, plugin_isolator_path: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="dronedream-plugin-verification-") as temporary:
        root = Path(temporary)
        store = AppStore(root / "store")
        manager: PluginManager | None = None
        try:
            manager = PluginManager(
                store,
                official_plugins_root=official_plugins_root,
                plugin_isolator_path=plugin_isolator_path,
            )
            plugin_id = "dronedream.mission-evidence-gate"
            manager.enable(plugin_id)
            semantic = root / "semantic.json"
            semantic.write_text("{}\n", encoding="utf-8")
            snapshot = manager.snapshot()
            registry = manager.build_tool_registry(
                environment=ToolEnvironment(
                    map_graph=_map(),
                    semantic_path=semantic,
                    vehicle_diameter_m=0.76,
                    vehicle_height_m=0.36,
                    waypoint_hold_seconds=0.4,
                ),
                snapshot=snapshot,
            )
            output, receipt = registry.call(
                "mission.evidence-requirements",
                {
                    "goal": "取件并安全返回办公室",
                    "payload_action": "pickup",
                    "constraints": ["safety_priority"],
                    "target_node": "pickup",
                    "return_node": "office",
                },
            )
            assert isinstance(output, dict)
            assert output["accepted"] is True
            assert receipt.outcome == "accepted"
            assert receipt.plugin_id == plugin_id
            assert receipt.plugin_package_sha256
            for _ in range(5):
                manager.disable(plugin_id)
                manager.enable(plugin_id)

            index = json.loads((official_plugins_root / "index.json").read_text(encoding="utf-8"))
            entry = next(item for item in index["plugins"] if item["plugin_id"] == plugin_id)
            official_archive = (official_plugins_root / entry["file"]).resolve()
            if official_plugins_root.resolve() not in official_archive.parents:
                raise AssertionError("official plugin archive escaped its index root")
            fault_signing_key = Ed25519PrivateKey.generate()
            manager.add_trusted_publisher(
                key_id="dronedream-verification.fault.release",
                publisher="DroneDream Verification",
                public_key_base64=base64.b64encode(
                    fault_signing_key.public_key().public_bytes(
                        encoding=serialization.Encoding.Raw,
                        format=serialization.PublicFormat.Raw,
                    )
                ).decode("ascii"),
            )
            fault_archive = _fault_bundle(
                official_archive,
                root / "fault-injection.zip",
                fault_signing_key,
            )
            manager.import_bundle(fault_archive)
            try:
                manager.enable("dronedream.fault-injection")
            except PluginManagerError:
                pass
            else:
                raise AssertionError("fault-injection plugin unexpectedly became healthy")
            fault = manager.get_plugin("dronedream.fault-injection")
            assert fault["status"] == "quarantined", fault
            assert manager.get_plugin("runtime.safe-hold")["health"] == "healthy"
            return {
                "plugin_id": receipt.plugin_id,
                "version": entry["version"],
                "package_sha256": receipt.plugin_package_sha256,
                "tool_id": receipt.tool_id,
                "output_sha256": receipt.output_sha256,
                "risk_codes": output["risk_codes"],
                "required_observations": len(output["required_observations"]),
                "lifecycle_cycles": 5,
                "fault_plugin_status": fault["status"],
                "safety_kernel_health": "healthy",
            }
        finally:
            if manager is not None:
                manager.close()
            store.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("official_plugins_root", type=Path)
    parser.add_argument("plugin_isolator_path", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.official_plugins_root, args.plugin_isolator_path),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
