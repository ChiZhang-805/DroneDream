from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore

REQUIRED_CAPABILITY_KINDS = {
    "action-pack",
    "anomaly-detector",
    "attachment-decoder",
    "budget-policy",
    "cache-policy",
    "checkpoint-policy",
    "clock-policy",
    "consensus-policy",
    "context-retriever",
    "context-store",
    "context-strategy",
    "controller",
    "entity-resolver",
    "evaluator",
    "event-bus",
    "evidence-exporter",
    "fallback-policy",
    "fault-injector",
    "harness-profile",
    "harness-scheduler",
    "input-channel",
    "locale-policy",
    "localization",
    "model-provider",
    "model-router",
    "monte-carlo-policy",
    "multimodal-preprocessor",
    "observer",
    "payload-driver",
    "perception",
    "physics-model",
    "plan-optimizer",
    "plan-scorer",
    "plan-validator",
    "planner",
    "result-fusion",
    "retry-policy",
    "runtime-adapter",
    "runtime-amendment",
    "runtime-replanner",
    "runtime-watchdog",
    "scenario-generator",
    "sensor-model",
    "simulator-adapter",
    "state-estimator",
    "structured-decoder",
    "task-decomposer",
    "telemetry-adapter",
    "timeout-policy",
    "token-meter",
    "tool-execution-policy",
    "tool-middleware",
    "tool-router",
    "transport",
    "workflow-topology",
}


def audit(
    store_root: Path,
    *,
    official_plugins_root: Path | None = None,
    plugin_isolator_path: Path | None = None,
) -> dict[str, object]:
    store = AppStore(store_root)
    manager = PluginManager(
        store,
        official_plugins_root=official_plugins_root,
        plugin_isolator_path=plugin_isolator_path,
    )
    try:
        plugins = manager.list_plugins()
    finally:
        manager.close()
        store.close()

    slots: dict[str, list[dict[str, object]]] = defaultdict(list)
    category_labels: dict[str, str] = {}
    capability_kinds: Counter[str] = Counter()
    runtime_kinds: Counter[str] = Counter()
    activation_modes: Counter[str] = Counter()

    for plugin in plugins:
        manifest = plugin["manifest"]
        placement = manifest["placement"]
        category_labels[str(placement["category_id"])] = str(placement["category_label"])
        slots[str(placement["slot_id"])].append(plugin)
        runtime_kinds.update([str(manifest["runtime"]["kind"])])
        activation_modes.update([str(placement["activation_mode"])])
        capability_kinds.update(str(item["kind"]) for item in manifest["capabilities"])

    slot_rows: list[dict[str, object]] = []
    issues: list[str] = []
    for slot_id, members in sorted(slots.items()):
        placements = [member["manifest"]["placement"] for member in members]
        modes = {str(placement["activation_mode"]) for placement in placements}
        enabled = [str(member["plugin_id"]) for member in members if member["enabled"]]
        if len(modes) != 1:
            issues.append(f"SLOT_ACTIVATION_MODE_MISMATCH:{slot_id}")
        mode = sorted(modes)[0]
        if mode == "single" and len(enabled) > 1:
            issues.append(f"SINGLE_SLOT_MULTIPLE_ENABLED:{slot_id}")
        slot_rows.append(
            {
                "slot_id": slot_id,
                "slot_label": str(placements[0]["slot_label"]),
                "category_id": str(placements[0]["category_id"]),
                "activation_mode": mode,
                "plugin_ids": sorted(str(member["plugin_id"]) for member in members),
                "enabled_plugin_ids": sorted(enabled),
                "failure_modes": sorted({str(item["failure_mode"]) for item in placements}),
                "swap_policies": sorted({str(item["swap_policy"]) for item in placements}),
            }
        )

    missing_capability_kinds = sorted(REQUIRED_CAPABILITY_KINDS - set(capability_kinds))
    issues.extend(f"REQUIRED_CAPABILITY_KIND_MISSING:{kind}" for kind in missing_capability_kinds)
    categories = {
        category_id: {
            "label": category_labels[category_id],
            "plugin_count": sum(
                1
                for plugin in plugins
                if plugin["manifest"]["placement"]["category_id"] == category_id
            ),
            "slot_count": sum(1 for row in slot_rows if row["category_id"] == category_id),
        }
        for category_id in sorted(category_labels)
    }
    return {
        "schema_version": "dronedream.plugin-catalog-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "store_root": str(store_root.resolve()),
        "status": "accepted" if not issues else "rejected",
        "issues": issues,
        "summary": {
            "plugin_count": len(plugins),
            "enabled_plugin_count": sum(bool(plugin["enabled"]) for plugin in plugins),
            "slot_count": len(slots),
            "category_count": len(categories),
            "slots_with_alternatives": sum(len(members) > 1 for members in slots.values()),
            "capability_kind_count": len(capability_kinds),
        },
        "activation_modes": dict(sorted(activation_modes.items())),
        "runtime_kinds": dict(sorted(runtime_kinds.items())),
        "capability_kinds": dict(sorted(capability_kinds.items())),
        "categories": categories,
        "slots": slot_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the resolved plugin catalog.")
    parser.add_argument("store_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--official-plugins-root", type=Path)
    parser.add_argument("--plugin-isolator-path", type=Path)
    args = parser.parse_args()
    result = audit(
        args.store_root,
        official_plugins_root=args.official_plugins_root,
        plugin_isolator_path=args.plugin_isolator_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "PLUGIN_CATALOG_AUDIT "
        f"status={result['status']} plugins={result['summary']['plugin_count']} "
        f"slots={result['summary']['slot_count']} output={args.output}"
    )
    return 0 if result["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
