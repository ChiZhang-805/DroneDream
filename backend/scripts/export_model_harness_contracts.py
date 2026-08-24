"""Export or verify the public Model + Harness JSON Schemas."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "model_harness"
MANAGED_PLUGIN_ROOT = CONTRACT_ROOT / "managed_plugins"
MANAGED_PLUGIN_IMPLEMENTATIONS: dict[str, tuple[str, str]] = {
    "asset_adapter": ("app.autonomy.asset_connectors", "get_asset_connector_catalog"),
    "model_provider": ("app.experiment_assistant", "_provider_generate"),
    "optimizer": ("app.orchestration.decision_harness", "select_optimizer_tool"),
    "planner": ("app.autonomy.service", "compile_autonomy_mission"),
    "simulator_adapter": ("app.simulator.factory", "get_simulator_adapter"),
    "telemetry_adapter": (
        "app.simulator.telemetry_evidence",
        "compile_telemetry_semantic_contract",
    ),
    "validator": (
        "app.model_harness.control_plane",
        "validate_output_against_control_plane",
    ),
}


def _render(schema: dict[str, object]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _managed_plugin_manifests() -> dict[str, dict[str, object]]:
    manifests: dict[str, dict[str, object]] = {}
    for slot, (module, entrypoint) in MANAGED_PLUGIN_IMPLEMENTATIONS.items():
        source_path = "backend/" + module.replace(".", "/") + ".py"
        source_bytes = (REPOSITORY_ROOT / source_path).read_bytes()
        manifests[f"{slot}.manifest.json"] = {
            "schema_version": "dronedream.managed-plugin-manifest.v1",
            "slot": slot,
            "plugin_id": f"dronedream.managed.{slot.replace('_', '-')}",
            "version": "1.0.0",
            "trust": "managed",
            "implementation": {
                "module": module,
                "entrypoint": entrypoint,
                "source_path": source_path,
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
            "api_contract": {
                "contract_id": f"dronedream.managed.{slot.replace('_', '-')}.v1",
                "input_schema_version": "dronedream.model-harness-input.v1",
                "output_schema_version": "dronedream.model-harness-output.v1",
            },
        }
    return manifests


def main() -> int:
    sys.path.insert(0, str(BACKEND_ROOT))
    from app.model_harness.control_plane import (
        canonical_contract_json_schemas,
        canonical_domain_policy_contract,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when a checked-in schema differs.",
    )
    arguments = parser.parse_args()
    failures: list[str] = []
    for filename, schema in canonical_contract_json_schemas().items():
        path = CONTRACT_ROOT / filename
        expected = _render(schema)
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                failures.append(filename)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8", newline="\n")
    policy_path = CONTRACT_ROOT / "domain-policy.v1.json"
    expected_policy = _render(canonical_domain_policy_contract())
    if arguments.check:
        if not policy_path.is_file() or policy_path.read_text(encoding="utf-8") != expected_policy:
            failures.append(policy_path.name)
    else:
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(expected_policy, encoding="utf-8", newline="\n")
    for filename, manifest in _managed_plugin_manifests().items():
        path = MANAGED_PLUGIN_ROOT / filename
        expected = _render(manifest)
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                failures.append(f"managed_plugins/{filename}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8", newline="\n")
    if failures:
        parser.error("canonical schema drift: " + ", ".join(sorted(failures)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
