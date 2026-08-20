from __future__ import annotations

from pathlib import Path
from typing import Any

from dronedream_agent_core.plugin_api import PluginDefinition
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)


def _import(*, store: Any, archive: Path) -> dict[str, object]:
    return store.import_asset_bundle(archive, "map")


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="assets.canonical-map-importer",
            name="DroneDream 地图包",
            version="1.0.0",
            description="导入带图结构、语义、SDF 世界和 qualification 状态的标准地图包。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="assets.map.canonical-import",
                    kind="map-importer",
                    name="标准地图导入",
                    description="校验并安装 DroneDream 标准地图资产。",
                )
            ],
            permissions=["asset.read"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="assets",
                category_label="地图与无人机",
                slot_id="assets.map-importer",
                slot_label="地图导入器",
                activation_mode="single",
                scope="general",
                category_order=60,
                slot_order=10,
                plugin_order=10,
            ),
        ),
        hooks={"import": _import},
    )
