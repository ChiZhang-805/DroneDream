from __future__ import annotations

from typing import Any

from dronedream_agent_core.contracts import (
    FlightPlan,
    GraphRoute,
    MissionContract,
    Px4Track,
    RouteClearanceReport,
    TaskGraph,
)
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _acceptance_campaign(
    *,
    contract: MissionContract,
    task_graph: TaskGraph,
    route: GraphRoute,
    clearance: RouteClearanceReport,
    **_: Any,
) -> dict[str, object]:
    return {
        "campaign": "acceptance-matrix",
        "contract_id": contract.contract_id,
        "mission_shape": {
            "payload_action": contract.payload_action,
            "task_count": len(task_graph.nodes),
            "route_length_m": route.route_length_m,
            "minimum_clearance_m": clearance.minimum_clearance_m,
        },
        "seeds": [104729, 130363, 155921],
        "required_runs": [
            "nominal",
            "user-amendment-before-takeoff",
            "user-amendment-during-stable-flight",
            "emergency-stop-during-transit",
        ],
    }


def _stress_campaign(
    *, contract: MissionContract, task_graph: TaskGraph, route: GraphRoute, **_: Any
) -> dict[str, object]:
    return {
        "campaign": "stress-matrix",
        "contract_id": contract.contract_id,
        "seeds": [7919, 104729, 130363, 155921, 196613, 262147, 327673, 393241],
        "required_runs": [
            "nominal",
            "low-battery-at-checkpoint",
            "tracking-error-spike",
            "telemetry-delay",
            "route-obstacle-change",
            "plugin-isolation-failure",
            "runtime-replan-adoption-timeout",
            "completion-evidence-mismatch",
        ],
        "task_count": len(task_graph.nodes),
        "route_length_m": route.route_length_m,
    }


def _wind_fault(*, route: GraphRoute, **_: Any) -> dict[str, object]:
    return {
        "fault_id": "wind-gust-cross-track",
        "target": "gazebo.environment.wind",
        "trigger": {"route_fraction": 0.45},
        "parameters": {"speed_mps": 3.0, "duration_s": 4.0, "direction_deg": 90},
        "required_observation": "tracking error remains inside configured runtime gate",
        "route_length_m": route.route_length_m,
    }


def _telemetry_delay_fault(**_: Any) -> dict[str, object]:
    return {
        "fault_id": "telemetry-delay",
        "target": "ros.telemetry.bridge",
        "trigger": {"checkpoint_index": 1},
        "parameters": {"latency_ms": 350, "jitter_ms": 80, "duration_s": 5.0},
        "required_observation": "stale telemetry cannot authorize continuation",
    }


def _battery_fault(*, flight_plan: FlightPlan, **_: Any) -> dict[str, object]:
    return {
        "fault_id": "battery-reserve-drop",
        "target": "px4.battery.telemetry",
        "trigger": {"after_segment_id": flight_plan.segments[0].segment_id},
        "parameters": {"reported_percent": 15.0},
        "required_observation": "battery reserve plugin vetoes checkpoint continuation",
    }


def _obstacle_fault(*, px4_track: Px4Track, **_: Any) -> dict[str, object]:
    point = px4_track.source_world_points[len(px4_track.source_world_points) // 2]
    return {
        "fault_id": "dynamic-obstacle-route-change",
        "target": "gazebo.dynamic_obstacle",
        "trigger": {"route_fraction": 0.5},
        "parameters": {
            "east_m": point.east_m,
            "north_m": point.north_m,
            "up_m": point.up_m,
            "radius_m": 0.6,
        },
        "required_observation": "old route freezes and replacement route requires new clearance",
    }


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    generators = [
        (
            "simulation.campaign-acceptance",
            "闭环验收矩阵",
            "为任务生成标称、计划修改、运行修改和紧急停止测试矩阵。",
            _acceptance_campaign,
            True,
        ),
        (
            "simulation.campaign-stress",
            "鲁棒性压力矩阵",
            "生成遥测、能源、障碍、插件和证据故障的扩展压力矩阵。",
            _stress_campaign,
            False,
        ),
    ]
    for index, (plugin_id, name, description, handler, enabled) in enumerate(generators, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.generate",
                capability_kind="scenario-generator",
                capability_name=name,
                capability_description=description,
                category_id="simulation",
                category_label="仿真与测试",
                slot_id="simulation.campaign-generator",
                slot_label="仿真测试矩阵",
                activation_mode="single",
                category_order=80,
                slot_order=20,
                plugin_order=index * 10,
                hooks={"generate_campaign": handler},
                default_enabled=enabled,
                failure_mode="isolate",
            )
        )
    faults = [
        (
            "simulation.fault-wind",
            "横向阵风故障",
            "定义 Gazebo 风场阵风及跟踪误差验收要求。",
            _wind_fault,
        ),
        (
            "simulation.fault-telemetry-delay",
            "遥测时延故障",
            "定义 ROS 遥测时延和抖动场景。",
            _telemetry_delay_fault,
        ),
        (
            "simulation.fault-battery",
            "电量余量故障",
            "定义运行检查点电量跌破余量门的场景。",
            _battery_fault,
        ),
        (
            "simulation.fault-dynamic-obstacle",
            "动态障碍故障",
            "在路线中点定义动态障碍并要求重新净空验证。",
            _obstacle_fault,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(faults, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.describe",
                capability_kind="fault-injector",
                capability_name=name,
                capability_description=description,
                category_id="simulation",
                category_label="仿真与测试",
                slot_id="simulation.fault-library",
                slot_label="故障场景定义",
                activation_mode="multiple",
                category_order=80,
                slot_order=30,
                plugin_order=index * 10,
                hooks={"describe_fault": handler},
                default_enabled=True,
                failure_mode="advisory",
            )
        )
    return definitions
