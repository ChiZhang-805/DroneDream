from __future__ import annotations

import math
from typing import Any

from dronedream_agent_core.contracts import (
    FlightPlan,
    GraphRoute,
    MissionContract,
    Px4Track,
    RouteClearanceReport,
    SemanticPlan,
    TaskGraph,
    VehicleAsset,
)
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _distance_score(*, route: GraphRoute, **_: Any) -> dict[str, object]:
    return {
        "metric": "distance",
        "value": route.route_length_m,
        "unit": "m",
        "preference": "lower",
    }


def _clearance_score(*, clearance: RouteClearanceReport, **_: Any) -> dict[str, object]:
    return {
        "metric": "minimum-clearance",
        "value": clearance.minimum_clearance_m,
        "unit": "m",
        "preference": "higher",
    }


def _stability_score(*, px4_track: Px4Track, **_: Any) -> dict[str, object]:
    speeds = [point.speed_limit_mps for point in px4_track.points]
    changes = [abs(second - first) for first, second in zip(speeds, speeds[1:], strict=False)]
    return {
        "metric": "speed-transition-rms",
        "value": math.sqrt(sum(value * value for value in changes) / max(len(changes), 1)),
        "unit": "mps",
        "preference": "lower",
    }


def _energy_proxy(*, route: GraphRoute, px4_track: Px4Track, **_: Any) -> dict[str, object]:
    climb_m = sum(
        max(0.0, second.up_m - first.up_m)
        for first, second in zip(
            px4_track.source_world_points,
            px4_track.source_world_points[1:],
            strict=False,
        )
    )
    proxy = route.route_length_m + climb_m * 2.5 + len(px4_track.points) * 0.05
    return {
        "metric": "energy-proxy",
        "value": proxy,
        "unit": "weighted-m",
        "preference": "lower",
        "climb_m": climb_m,
    }


def _route_binding_gate(
    *,
    contract: MissionContract,
    semantic_plan: SemanticPlan,
    flight_plan: FlightPlan,
    route: GraphRoute,
    clearance: RouteClearanceReport,
    **_: Any,
) -> dict[str, object]:
    gates = {
        "route_start_bound": route.start_node == contract.start_node,
        "route_return_bound": route.goal_node == contract.return_node,
        "semantic_hash_bound": flight_plan.semantic_plan_sha256 == sha256_json(semantic_plan),
        "clearance_route_bound": clearance.route_sha256 == sha256_json(route),
        "continuous_clearance_accepted": clearance.accepted,
    }
    failed = [name for name, accepted in gates.items() if not accepted]
    return {
        "validator": "route-binding",
        "accepted": not failed,
        "gates": gates,
        "issue_codes": [f"ROUTE_BINDING_{name.upper()}" for name in failed],
    }


def _payload_gate(
    *, contract: MissionContract, task_graph: TaskGraph, **_: Any
) -> dict[str, object]:
    pickup_tasks = [
        task
        for task in task_graph.nodes
        if task.action == "pickup" and task.target_node == contract.target_node
    ]
    accepted = contract.payload_action != "pickup" or len(pickup_tasks) == 1
    return {
        "validator": "payload-workflow",
        "accepted": accepted,
        "pickup_task_count": len(pickup_tasks),
        "issue_codes": [] if accepted else ["PAYLOAD_PICKUP_TASK_INVALID"],
        "repair_instructions": (
            [] if accepted else ["Create exactly one pickup task at the contract target node."]
        ),
    }


def _stability_gate(*, px4_track: Px4Track, **_: Any) -> dict[str, object]:
    max_speed = max(point.speed_limit_mps for point in px4_track.points)
    accepted = max_speed <= 3.0 and px4_track.stop_at_waypoints
    return {
        "validator": "track-stability",
        "accepted": accepted,
        "maximum_speed_mps": max_speed,
        "stop_at_waypoints": px4_track.stop_at_waypoints,
        "issue_codes": [] if accepted else ["TRACK_STABILITY_POLICY_REJECTED"],
    }


def _energy_reserve_gate(
    *,
    route: GraphRoute,
    vehicle: VehicleAsset,
    configuration: dict[str, object] | None = None,
    **_: Any,
) -> dict[str, object]:
    configured = configuration or {}
    requested_range_m = float(configured.get("qualified_range_m", vehicle.qualified_range_m))
    range_m = min(requested_range_m, vehicle.qualified_range_m)
    asset_reserve = vehicle.reserve_battery_percent / 100.0
    reserve = max(float(configured.get("reserve_fraction", asset_reserve)), asset_reserve)
    # qualified_range_m already includes the asset's declared reserve. A stricter
    # plugin reserve scales that envelope down; it can never increase it.
    usable = range_m * (1.0 - reserve) / (1.0 - asset_reserve)
    accepted = route.route_length_m <= usable
    return {
        "validator": "energy-reserve",
        "accepted": accepted,
        "qualified_range_m": range_m,
        "asset_qualified_range_m": vehicle.qualified_range_m,
        "asset_reserve_fraction": asset_reserve,
        "reserve_fraction": reserve,
        "usable_range_m": usable,
        "route_length_m": route.route_length_m,
        "issue_codes": [] if accepted else ["ENERGY_RESERVE_INSUFFICIENT"],
        "repair_instructions": (
            [] if accepted else ["Shorten the route or select a qualified higher-range vehicle."]
        ),
    }


def _readiness_evaluation(
    *,
    contract: MissionContract,
    route: GraphRoute,
    clearance: RouteClearanceReport,
    runtime_checkpoints: Any,
    **_: Any,
) -> dict[str, object]:
    return {
        "evaluation": "preflight-readiness",
        "contract_id": contract.contract_id,
        "route_length_m": route.route_length_m,
        "minimum_clearance_m": clearance.minimum_clearance_m,
        "checkpoint_count": len(runtime_checkpoints.checkpoints),
        "ready": clearance.accepted and bool(runtime_checkpoints.checkpoints),
    }


def _complexity_evaluation(
    *, task_graph: TaskGraph, route: GraphRoute, px4_track: Px4Track, **_: Any
) -> dict[str, object]:
    complexity = len(task_graph.nodes) + len(route.edge_ids) + len(px4_track.points) / 10.0
    return {
        "evaluation": "mission-complexity",
        "score": round(complexity, 3),
        "task_count": len(task_graph.nodes),
        "edge_count": len(route.edge_ids),
        "track_point_count": len(px4_track.points),
    }


def plugin_definitions() -> list[PluginDefinition]:
    definitions: list[PluginDefinition] = []
    scorers = [
        ("planning.score-distance", "距离评分", "计算任务路线总长度。", _distance_score),
        (
            "planning.score-clearance",
            "净空评分",
            "记录连续碰撞检查得到的最小净空。",
            _clearance_score,
        ),
        (
            "planning.score-stability",
            "稳定性评分",
            "计算航迹速度变化的均方根指标。",
            _stability_score,
        ),
        (
            "planning.score-energy",
            "能耗代理评分",
            "根据距离、爬升和航点数量估算相对能耗。",
            _energy_proxy,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(scorers, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.score",
                capability_kind="plan-scorer",
                capability_name=name,
                capability_description=description,
                category_id="planning",
                category_label="任务规划",
                slot_id="planning.plan-scorers",
                slot_label="计划评分器",
                activation_mode="multiple",
                category_order=40,
                slot_order=30,
                plugin_order=index * 10,
                hooks={"score_plan": handler},
                default_enabled=True,
                failure_mode="advisory",
            )
        )
    validators = [
        (
            "validation.route-binding",
            "路线绑定验证",
            "验证合同、语义计划、飞行计划、路线和净空哈希的一致性。",
            _route_binding_gate,
            True,
            {},
        ),
        (
            "validation.payload-workflow",
            "载荷流程验证",
            "确保取件任务只有一个且绑定合同目标。",
            _payload_gate,
            True,
            {},
        ),
        (
            "validation.track-stability",
            "航迹稳定性验证",
            "限制过高速度并要求航点停止策略。",
            _stability_gate,
            True,
            {},
        ),
        (
            "validation.energy-reserve",
            "能源余量验证",
            "依据合格航程和预留比例否决能源不足的计划。",
            _energy_reserve_gate,
            False,
            {
                "type": "object",
                "properties": {
                    "qualified_range_m": {"type": "number", "minimum": 10, "maximum": 100000},
                    "reserve_fraction": {"type": "number", "minimum": 0.05, "maximum": 0.8},
                },
                "additionalProperties": False,
            },
        ),
    ]
    for index, (
        plugin_id,
        name,
        description,
        handler,
        enabled,
        schema,
    ) in enumerate(validators, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.validate",
                capability_kind="plan-validator",
                capability_name=name,
                capability_description=description,
                category_id="validation",
                category_label="安全与验证",
                slot_id="validation.plan-gates",
                slot_label="计划否决门",
                activation_mode="multiple",
                category_order=60,
                slot_order=30,
                plugin_order=index * 10,
                hooks={"validate_plan": handler},
                default_enabled=enabled,
                failure_mode="fail-closed",
                configuration_schema=schema,
            )
        )
    evaluations = [
        (
            "evaluation.preflight-readiness",
            "起飞前就绪度",
            "汇总路线、净空和检查点是否达到起飞前闭环要求。",
            _readiness_evaluation,
        ),
        (
            "evaluation.mission-complexity",
            "任务复杂度",
            "根据任务、图边和航迹点数量形成可比较的复杂度指标。",
            _complexity_evaluation,
        ),
    ]
    for index, (plugin_id, name, description, handler) in enumerate(evaluations, start=1):
        definitions.append(
            hook_plugin(
                module_name=__name__,
                plugin_id=plugin_id,
                name=name,
                description=description,
                capability_id=f"{plugin_id}.evaluate",
                capability_kind="evaluator",
                capability_name=name,
                capability_description=description,
                category_id="evaluation",
                category_label="证据与评测",
                slot_id="evaluation.preflight",
                slot_label="起飞前评测",
                activation_mode="multiple",
                category_order=90,
                slot_order=10,
                plugin_order=index * 10,
                hooks={"evaluate_preflight": handler},
                default_enabled=True,
                failure_mode="advisory",
            )
        )
    return definitions
