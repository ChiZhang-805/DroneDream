from __future__ import annotations

from dronedream_agent_core.contracts import Px4Track, Px4TrackRequest
from dronedream_agent_core.plugin_api import PluginDefinition, ToolEnvironment
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)
from dronedream_agent_core.px4_track import route_to_px4_track
from dronedream_agent_core.tools import ToolPlugin


def _tools(environment: ToolEnvironment) -> list[ToolPlugin]:
    return [
        ToolPlugin(
            tool_id="px4.export-track",
            version="1.0.0",
            authority="plan",
            input_type=Px4TrackRequest,
            output_type=Px4Track,
            handler=lambda request: route_to_px4_track(
                request.route,
                environment.map_graph,
                environment.semantic_path,
                waypoint_hold_seconds=request.waypoint_hold_seconds,
            ),
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="px4.export-track",
            name="PX4 航迹",
            version="1.0.0",
            description="把已验证图航路转换为带约束的 PX4 Offboard 航迹。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python",
                entrypoint=f"{__name__}:plugin_definition",
            ),
            capabilities=[
                PluginCapability(
                    capability_id="px4.export-track",
                    kind="planner",
                    name="PX4 Offboard 航迹",
                    description="生成具有时间、速度和坐标系约束的飞行 setpoint。",
                    authority="plan",
                    input_schema=Px4TrackRequest.model_json_schema(),
                    output_schema=Px4Track.model_json_schema(),
                )
            ],
            permissions=["asset.read", "mission.read", "mission.write-output"],
            default_enabled=True,
            removable=False,
            placement=PluginPlacement(
                category_id="flight-control",
                category_label="飞行与控制",
                slot_id="flight-control.track-export",
                slot_label="航迹转换",
                activation_mode="single",
                scope="runtime",
                category_order=30,
                slot_order=10,
                plugin_order=10,
            ),
        ),
        tool_factory=_tools,
    )
