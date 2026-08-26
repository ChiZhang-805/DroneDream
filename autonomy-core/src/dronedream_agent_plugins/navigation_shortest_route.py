from __future__ import annotations

from dronedream_agent_core.contracts import GraphRoute, RouteQuery
from dronedream_agent_core.navigation import shortest_route
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
            tool_id="navigation.shortest-route",
            version="1.0.0",
            authority="plan",
            input_type=RouteQuery,
            output_type=GraphRoute,
            handler=lambda query: shortest_route(environment.map_graph, query),
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="navigation.shortest-route",
            name="最短路径",
            version="1.0.0",
            description="在合格三维地图图结构上生成可验证的最短航路。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python",
                entrypoint=f"{__name__}:plugin_definition",
            ),
            capabilities=[
                PluginCapability(
                    capability_id="navigation.shortest-route",
                    kind="planner",
                    name="三维最短路径",
                    description="按地图节点和飞行边界计算从起点到目标点的航路。",
                    authority="plan",
                    input_schema=RouteQuery.model_json_schema(),
                    output_schema=GraphRoute.model_json_schema(),
                )
            ],
            permissions=["asset.read", "mission.read"],
            default_enabled=True,
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
                plugin_order=10,
            ),
        ),
        tool_factory=_tools,
    )
