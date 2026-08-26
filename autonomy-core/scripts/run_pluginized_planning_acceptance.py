"""Run a real model-planning workflow with the isolated official MCP plugin enabled."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dronedream_agent_app.plugin_manager import PluginManager
from dronedream_agent_app.storage import AppStore
from dronedream_agent_core.assets import load_school_map_catalog
from dronedream_agent_core.context import ContextStore
from dronedream_agent_core.contracts import MapAsset, MissionRequest, VehicleAsset
from dronedream_agent_core.model_port import ProviderSettings, StructuredModelPort
from dronedream_agent_core.orchestrator import MissionOrchestrator, PreparationConfig
from dronedream_agent_core.plugin_api import ToolEnvironment


def run(
    work_root: Path,
    resource_root: Path,
    official_plugins_root: Path,
    *,
    provider: str,
    model: str,
    plugin_isolator: Path | None = None,
) -> dict[str, object]:
    if work_root.exists() and any(work_root.iterdir()):
        raise FileExistsError(f"acceptance directory is not empty: {work_root}")
    work_root.mkdir(parents=True, exist_ok=True)
    provider_settings = {
        "openai": ("OPENAI_API_KEY", None, "responses"),
        "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com", "chat-completions"),
        "kimi": ("KIMI_API_KEY", "https://api.moonshot.ai/v1", "chat-completions"),
    }
    api_key_env, base_url, api_style = provider_settings[provider]
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} is not configured")
    store = AppStore(work_root / "app-store")
    context: ContextStore | None = None
    try:
        store.seed_bundled_assets(resource_root / "default-assets")
        plugin_manager = PluginManager(
            store,
            official_plugins_root=official_plugins_root,
            plugin_isolator_path=plugin_isolator,
        )
        plugin_manager.enable("dronedream.mission-evidence-gate")
        map_asset = store.get_asset("dronedream.school-map.v1", "map")
        vehicle_asset = store.get_asset("dronedream.my-drone.v1", "vehicle")
        map_manifest = map_asset["manifest"]
        vehicle_manifest = vehicle_asset["manifest"]
        assert isinstance(map_manifest, dict) and isinstance(vehicle_manifest, dict)
        map_files = map_manifest["files"]
        vehicle_files = vehicle_manifest["files"]
        assert isinstance(map_files, dict) and isinstance(vehicle_files, dict)
        map_root = Path(str(map_asset["bundle_root"]))
        vehicle_root = Path(str(vehicle_asset["bundle_root"]))
        graph = MapAsset.model_validate_json(
            (map_root / str(map_files["graph"])).read_text(encoding="utf-8")
        )
        semantic_path = map_root / str(map_files["semantic"])
        vehicle_sdf = vehicle_root / str(vehicle_files["vehicle_sdf"])
        vehicle = VehicleAsset.model_validate_json(
            (vehicle_root / str(vehicle_files["vehicle_metadata"])).read_text(encoding="utf-8")
        )
        snapshot = plugin_manager.snapshot()
        extension_registry = plugin_manager.build_extension_registry(snapshot=snapshot)
        registry = plugin_manager.build_tool_registry(
            environment=ToolEnvironment(
                map_graph=graph,
                semantic_path=semantic_path,
                vehicle_diameter_m=vehicle.body_radius_m * 2,
                vehicle_height_m=vehicle.body_height_m,
                waypoint_hold_seconds=0.4,
            ),
            snapshot=snapshot,
        )
        settings = ProviderSettings(
            name=provider,  # type: ignore[arg-type]
            model=model,
            api_key_env=api_key_env,
            base_url=base_url,
            api_style=api_style,  # type: ignore[arg-type]
        )
        primary = StructuredModelPort(
            provider,  # type: ignore[arg-type]
            settings=settings,
            api_key=api_key,
            max_attempts=3,
            timeout_seconds=180,
        )
        critic = StructuredModelPort(
            provider,  # type: ignore[arg-type]
            settings=settings,
            api_key=api_key,
            max_attempts=3,
            timeout_seconds=180,
        )
        context = ContextStore(work_root / "mission-context.sqlite3")
        orchestrator = MissionOrchestrator(
            config=PreparationConfig(
                provider=provider,  # type: ignore[arg-type]
                critic_provider=provider,  # type: ignore[arg-type]
                vehicle_diameter_m=vehicle.body_radius_m * 2,
                vehicle_height_m=vehicle.body_height_m,
            ),
            map_catalog=load_school_map_catalog(semantic_path),
            map_graph=graph,
            semantic_path=semantic_path,
            vehicle_sdf=vehicle_sdf,
            vehicle_asset_id=vehicle.asset_id,
            vehicle=vehicle,
            context_store=context,
            primary_port=primary,
            critic_port=critic,
            tool_registry=registry,
            extension_registry=extension_registry,
            plugin_snapshot=snapshot,
        )
        prepared = orchestrator.prepare(
            MissionRequest(
                conversation_id="pluginized-user-acceptance-001",
                message=(
                    "从办公室无人机起降坪起飞，到外卖取餐点取一份外卖，"
                    "安全返回办公室起降坪并降落；先只生成计划，不要开始执行。"
                ),
                start_entity="办公室无人机起降坪",
                locale="zh-CN",
            ),
            work_root / "plan",
        )
        roles = [record.role for record in prepared.model_calls]
        plugin_receipt = next(
            receipt
            for receipt in prepared.tool_receipts
            if receipt.tool_id == "mission.evidence-requirements"
        )
        assert "plugin_router" in roles
        assert plugin_receipt.outcome == "accepted"
        assert plugin_receipt.plugin_package_sha256
        summary = {
            "schema_version": "dronedream.pluginized-planning-acceptance.v1",
            "status": prepared.status,
            "conversation_id": prepared.contract.conversation_id,
            "contract_id": prepared.contract.contract_id,
            "provider": provider,
            "model": model,
            "model_roles": roles,
            "model_calls": len(prepared.model_calls),
            "model_input_tokens": sum(record.input_tokens or 0 for record in prepared.model_calls),
            "model_output_tokens": sum(
                record.output_tokens or 0 for record in prepared.model_calls
            ),
            "plugin_snapshot_id": prepared.plugin_snapshot.snapshot_id,
            "plugin_catalog_sha256": prepared.plugin_snapshot.catalog_sha256,
            "plugin_id": plugin_receipt.plugin_id,
            "plugin_package_sha256": plugin_receipt.plugin_package_sha256,
            "plugin_output_sha256": plugin_receipt.output_sha256,
            "route_node_count": len(prepared.execution_route.node_ids),
            "minimum_clearance_m": prepared.route_clearance.minimum_clearance_m,
            "planning_attempts": prepared.planning_attempts,
        }
        (work_root / "acceptance-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return summary
    finally:
        if context is not None:
            context.close()
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_root", type=Path)
    parser.add_argument("resource_root", type=Path)
    parser.add_argument("official_plugins_root", type=Path)
    parser.add_argument("--provider", choices=["openai", "deepseek", "kimi"], default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--plugin-isolator", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.work_root,
                args.resource_root,
                args.official_plugins_root,
                provider=args.provider,
                model=args.model,
                plugin_isolator=args.plugin_isolator,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
