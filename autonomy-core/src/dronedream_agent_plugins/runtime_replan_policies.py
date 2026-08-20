from __future__ import annotations

import math
from typing import Any

from dronedream_agent_core.contracts import MapAsset, Vector3
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _nearest_anchor(
    *, current_world: Vector3, graph: MapAsset, configuration: dict[str, Any], **_: Any
) -> dict[str, object]:
    maximum = float(configuration.get("maximum_join_distance_m", 6.0))
    anchor = min(
        graph.nodes,
        key=lambda node: math.dist(
            (node.position_m.x, node.position_m.y, node.position_m.z),
            (current_world.x, current_world.y, current_world.z),
        ),
    )
    return {
        "anchor_node": anchor.node_id,
        "maximum_join_distance_m": maximum,
        "requires_flight_verified_anchor": False,
    }


def _verified_anchor(
    *, current_world: Vector3, graph: MapAsset, configuration: dict[str, Any], **_: Any
) -> dict[str, object]:
    maximum = float(configuration.get("maximum_join_distance_m", 4.0))
    verified_nodes = {
        node_id
        for edge in graph.edges
        if edge.qualification == "flight-verified"
        for node_id in (edge.from_node, edge.to_node)
    }
    candidates = [node for node in graph.nodes if node.node_id in verified_nodes]
    if not candidates:
        raise ValueError("RUNTIME_REPLAN_VERIFIED_ANCHOR_UNAVAILABLE")
    anchor = min(
        candidates,
        key=lambda node: math.dist(
            (node.position_m.x, node.position_m.y, node.position_m.z),
            (current_world.x, current_world.y, current_world.z),
        ),
    )
    return {
        "anchor_node": anchor.node_id,
        "maximum_join_distance_m": maximum,
        "requires_flight_verified_anchor": True,
    }


def plugin_definitions() -> list[PluginDefinition]:
    values = [
        (
            "runtime.replan-nearest-anchor",
            "最近安全锚点换路",
            "从稳定悬停位置接入最近图节点，并对接入距离设置硬上限。",
            _nearest_anchor,
            6.0,
            True,
        ),
        (
            "runtime.replan-verified-anchor",
            "已验证锚点换路",
            "只允许接入至少连接一条飞行验证边的图节点，适合高风险任务。",
            _verified_anchor,
            4.0,
            False,
        ),
    ]
    return [
        hook_plugin(
            module_name=__name__,
            plugin_id=plugin_id,
            name=name,
            description=description,
            capability_id=f"{plugin_id}.select",
            capability_kind="runtime-replanner",
            capability_name=name,
            capability_description=description,
            category_id="runtime",
            category_label="运行期与在线换路",
            slot_id="runtime.replan-policy",
            slot_label="在线换路锚点策略",
            activation_mode="single",
            category_order=70,
            slot_order=25,
            plugin_order=index * 10,
            hooks={"select_anchor": handler},
            default_enabled=enabled,
            failure_mode="fail-closed",
            swap_policy="safe-hold",
            configuration_schema={
                "type": "object",
                "properties": {
                    "maximum_join_distance_m": {
                        "type": "number",
                        "exclusiveMinimum": 0.0,
                        "maximum": 20.0,
                        "default": default_maximum,
                    }
                },
                "additionalProperties": False,
            },
            permissions=["mission.read", "telemetry.read", "configuration.read"],
        )
        for index, (
            plugin_id,
            name,
            description,
            handler,
            default_maximum,
            enabled,
        ) in enumerate(values, start=1)
    ]
