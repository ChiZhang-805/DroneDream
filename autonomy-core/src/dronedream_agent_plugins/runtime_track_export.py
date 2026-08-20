from __future__ import annotations

from dronedream_agent_core.contracts import Px4Track, RuntimeTrackRequest
from dronedream_agent_core.plugin_api import PluginDefinition, ToolEnvironment
from dronedream_agent_core.plugin_contracts import (
    PluginCapability,
    PluginManifest,
    PluginPlacement,
    PluginRuntime,
)
from dronedream_agent_core.px4_track import runtime_route_to_px4_track
from dronedream_agent_core.tools import ToolPlugin


def _tools(environment: ToolEnvironment) -> list[ToolPlugin]:
    return [
        ToolPlugin(
            tool_id="runtime.track-export-standard",
            version="1.0.0",
            authority="plan",
            input_type=RuntimeTrackRequest,
            output_type=Px4Track,
            handler=lambda request: runtime_route_to_px4_track(request, environment.map_graph),
        )
    ]


def plugin_definition() -> PluginDefinition:
    return PluginDefinition(
        manifest=PluginManifest(
            plugin_id="runtime.track-export-standard",
            name="稳定悬停换路航迹",
            version="1.0.0",
            description="从实时稳定悬停点生成目标、返程与降落阶段清晰的替换航迹。",
            publisher="DroneDream",
            runtime=PluginRuntime(
                kind="builtin-python", entrypoint=f"{__name__}:plugin_definition"
            ),
            capabilities=[
                PluginCapability(
                    capability_id="runtime.track-export-standard",
                    kind="planner",
                    name="在线换路航迹转换",
                    description="保持既有坐标契约并为在线替换路线生成 PX4 航迹。",
                    authority="plan",
                    input_schema=RuntimeTrackRequest.model_json_schema(),
                    output_schema=Px4Track.model_json_schema(),
                )
            ],
            permissions=["asset.read", "mission.read", "mission.write-output"],
            default_enabled=True,
            removable=False,
            disable_allowed=False,
            placement=PluginPlacement(
                category_id="runtime",
                category_label="运行时与闭环",
                slot_id="runtime.track-export",
                slot_label="在线换路航迹",
                activation_mode="single",
                scope="runtime",
                failure_mode="fail-closed",
                swap_policy="certified-update",
                category_order=80,
                slot_order=30,
                plugin_order=10,
            ),
        ),
        tool_factory=_tools,
    )
