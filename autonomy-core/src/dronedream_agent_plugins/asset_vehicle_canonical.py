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
    return store.import_asset_bundle(archive, "vehicle")


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="assets.canonical-vehicle-importer",
            name="DroneDream 无人机包",
            version="1.0.0",
            description="导入无人机 SDF、控制器参数和经过验证的物理包络元数据。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="assets.vehicle.canonical-import",
                    kind="vehicle-importer",
                    name="标准无人机导入",
                    description="校验并安装 DroneDream 标准无人机资产。",
                )
            ],
            permissions=["asset.read"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="assets",
                category_label="地图与无人机",
                slot_id="assets.vehicle-importer",
                slot_label="无人机导入器",
                activation_mode="single",
                scope="general",
                category_order=60,
                slot_order=20,
                plugin_order=10,
            ),
        ),
        hooks={"import": _import},
    )
