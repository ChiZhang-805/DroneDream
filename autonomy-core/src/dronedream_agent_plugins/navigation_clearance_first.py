from __future__ import annotations

from dronedream_agent_core.contracts import GraphRoute, RouteQuery
from dronedream_agent_core.navigation import clearance_first_route
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
            tool_id="navigation.clearance-first-route",
            version="1.0.0",
            authority="plan",
            input_type=RouteQuery,
            output_type=GraphRoute,
            handler=lambda query: clearance_first_route(environment.map_graph, query),
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="navigation.clearance-first-route",
            name="净空优先路径",
            version="1.0.0",
            description="在距离之外提高狭窄路段与未经飞行验证路段的代价，优先选择宽裕航路。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python",
                entrypoint=f"{__name__}:plugin_definition",
            ),
            capabilities=[
                PluginCapability(
                    capability_id="navigation.clearance-first-route",
                    kind="planner",
                    name="净空优先路径",
                    description="以净空、验证状态和距离的组合代价生成路径。",
                    authority="plan",
                    input_schema=RouteQuery.model_json_schema(),
                    output_schema=GraphRoute.model_json_schema(),
                )
            ],
            permissions=["asset.read", "mission.read"],
            default_enabled=False,
            removable=False,
            placement=PluginPlacement(
                category_id="planning",
                category_label="任务规划",
                slot_id="planning.route-strategy",
                slot_label="路径策略",
                activation_mode="single",
                scope="mission",
                category_order=20,
                slot_order=10,
                plugin_order=20,
            ),
        ),
        tool_factory=_tools,
    )
