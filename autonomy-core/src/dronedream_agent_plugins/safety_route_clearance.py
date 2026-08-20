from __future__ import annotations

from dronedream_agent_core.collision import validate_route_clearance
from dronedream_agent_core.contracts import GraphRoute, RouteClearanceReport
from dronedream_agent_core.plugin_api import PluginDefinition, ToolEnvironment
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)
from dronedream_agent_core.tools import ToolPlugin


def _tools(environment: ToolEnvironment) -> list[ToolPlugin]:
    return [
        ToolPlugin(
            tool_id="safety.route-clearance",
            version="1.0.0",
            authority="simulate",
            input_type=GraphRoute,
            output_type=RouteClearanceReport,
            handler=lambda route: validate_route_clearance(
                route,
                environment.semantic_path,
                vehicle_diameter_m=environment.vehicle_diameter_m,
                vehicle_height_m=environment.vehicle_height_m,
            ),
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="safety.route-clearance",
            name="航路净空",
            version="1.0.0",
            description="按照无人机连续三维包络验证整条航路的障碍物净空。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python",
                entrypoint=f"{__name__}:plugin_definition",
            ),
            capabilities=[
                PluginCapability(
                    capability_id="safety.route-clearance",
                    kind="planner",
                    name="连续航路净空",
                    description="使用地图碰撞语义和机体尺寸检查连续航路。",
                    authority="simulate",
                    input_schema=GraphRoute.model_json_schema(),
                    output_schema=RouteClearanceReport.model_json_schema(),
                )
            ],
            permissions=["asset.read", "mission.read"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="safety",
                category_label="安全与验证",
                slot_id="safety.route-clearance",
                slot_label="航路净空验证",
                activation_mode="single",
                scope="runtime",
                category_order=10,
                slot_order=10,
                plugin_order=10,
            ),
        ),
        tool_factory=_tools,
    )
