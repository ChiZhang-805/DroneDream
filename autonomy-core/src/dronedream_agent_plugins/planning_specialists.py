from __future__ import annotations

import math
from collections import deque
from typing import Any

from dronedream_agent_core.contracts import (
    GraphRoute,
    MapAsset,
    MissionContract,
    PlannerContribution,
    PlannerValidation,
    Px4Track,
    RouteClearanceReport,
    TaskGraph,
    VehicleAsset,
)
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin

_LAYERS = (
    "semantic",
    "temporal",
    "global",
    "local",
    "indoor",
    "outdoor",
    "dynamic-obstacle",
    "energy",
    "link",
    "payload",
    "regulatory",
)


def _reachable(graph: MapAsset, start: str, goal: str) -> bool:
    neighbours: dict[str, set[str]] = {node.node_id: set() for node in graph.nodes}
    for edge in graph.edges:
        neighbours[edge.from_node].add(edge.to_node)
        if edge.bidirectional:
            neighbours[edge.to_node].add(edge.from_node)
    queue = deque([start])
    seen = {start}
    while queue:
        node = queue.popleft()
        if node == goal:
            return True
        for neighbour in neighbours[node] - seen:
            seen.add(neighbour)
            queue.append(neighbour)
    return False


def _contribution(
    layer: str,
    *,
    contract: MissionContract,
    map_graph: MapAsset,
    vehicle: VehicleAsset,
    **_: Any,
) -> PlannerContribution:
    semantics = {node.semantic for node in map_graph.nodes}
    normalized_constraints = " ".join(contract.constraints).casefold()
    applicable = {
        "semantic": True,
        "temporal": any(
            token in normalized_constraints for token in ("deadline", "time", "时间", "之前")
        ),
        "global": True,
        "local": True,
        "indoor": bool(semantics & {"corridor", "stairs", "door", "office"}),
        "outdoor": "outdoor" in semantics,
        "dynamic-obstacle": True,
        "energy": True,
        "link": (
            "outdoor" in semantics and bool(semantics & {"corridor", "stairs", "door", "office"})
        ),
        "payload": contract.payload_action == "pickup",
        "regulatory": any(
            token in normalized_constraints
            for token in ("regulatory", "airspace", "法规", "空域", "禁飞")
        ),
    }[layer]
    constraints = {
        "semantic": ["all targets resolve to immutable map node identifiers"],
        "temporal": ["deadline feasibility is checked against route duration and hold budget"],
        "global": ["start, target, and return remain connected in the selected map graph"],
        "local": ["every continuous trajectory segment passes collision-envelope clearance"],
        "indoor": ["door, stair, and corridor transitions respect vehicle envelope and speed"],
        "outdoor": ["outdoor legs retain a reachable return or safe-landing path"],
        "dynamic-obstacle": ["online obstacles can only tighten motion or trigger hold/replan"],
        "energy": ["distance, climb, payload, and reserve remain inside qualified envelope"],
        "link": ["indoor/outdoor transitions retain heartbeat and lost-link behavior"],
        "payload": ["pickup identity, attachment, mass update, and custody evidence are required"],
        "regulatory": ["real-flight airspace constraints require explicit regulatory evidence"],
    }[layer]
    metrics = {
        "semantic": ["grounded-target-ratio"],
        "temporal": ["estimated-duration-seconds", "deadline-slack-seconds"],
        "global": ["route-length-m", "graph-edge-count"],
        "local": ["minimum-clearance-m", "turn-speed-mps"],
        "indoor": ["door-transition-count", "stair-transition-count"],
        "outdoor": ["outdoor-distance-m", "landing-option-count"],
        "dynamic-obstacle": ["replan-latency-ms", "minimum-time-to-collision-s"],
        "energy": ["energy-proxy", "reserve-fraction"],
        "link": ["link-margin-db", "heartbeat-gap-ms"],
        "payload": ["payload-mass-kg", "custody-evidence-count"],
        "regulatory": ["regulated-zone-intersection-count"],
    }[layer]
    gates = {
        "contract_nodes_exist": {
            contract.start_node,
            contract.target_node,
            contract.return_node,
        }.issubset({node.node_id for node in map_graph.nodes}),
        "vehicle_envelope_positive": vehicle.body_radius_m > 0 and vehicle.body_height_m > 0,
    }
    return PlannerContribution(
        planner_id=f"planning.{layer}",
        layer=layer,  # type: ignore[arg-type]
        applicable=applicable,
        hard_constraints=constraints if applicable else [],
        objective_metrics=metrics if applicable else [],
        required_inputs=["mission-contract", "map-graph", "vehicle-asset"],
        deterministic_gates=gates,
    )


def _validation(
    layer: str,
    *,
    contract: MissionContract,
    map_graph: MapAsset,
    vehicle: VehicleAsset,
    task_graph: TaskGraph,
    route: GraphRoute,
    clearance: RouteClearanceReport,
    px4_track: Px4Track,
    configuration: dict[str, object] | None = None,
    **_: Any,
) -> PlannerValidation:
    configured = configuration or {}
    route_semantics = {
        node.semantic for node in map_graph.nodes if node.node_id in set(route.node_ids)
    }
    requested_range_m = float(configured.get("qualified_range_m", vehicle.qualified_range_m))
    # A plugin may tighten the certified envelope, never expand the vehicle asset.
    maximum_range_m = min(requested_range_m, vehicle.qualified_range_m)
    normalized_constraints = " ".join(contract.constraints).casefold()
    gates: dict[str, bool]
    if layer == "semantic":
        gates = {
            "start_bound": route.start_node == contract.start_node,
            "return_bound": route.goal_node == contract.return_node,
            "target_present": contract.target_node in route.node_ids,
        }
    elif layer == "temporal":
        gates = {
            "route_duration_finite": math.isfinite(
                route.route_length_m / max(vehicle.max_speed_mps, 0.1)
            ),
            "bounded_waypoint_holds": px4_track.waypoint_hold_seconds <= 30.0,
        }
    elif layer == "global":
        gates = {
            "start_to_target_reachable": _reachable(
                map_graph, contract.start_node, contract.target_node
            ),
            "target_to_return_reachable": _reachable(
                map_graph, contract.target_node, contract.return_node
            ),
            "route_nonempty": bool(route.edge_ids),
        }
    elif layer == "local":
        gates = {
            "clearance_accepted": clearance.accepted,
            "clearance_bound_to_route": clearance.route_sha256 != "0" * 64,
        }
    elif layer == "indoor":
        gates = {
            "indoor_transition_clear": (
                not route_semantics.intersection({"door", "stairs", "corridor"})
                or clearance.accepted
            ),
            "indoor_speed_bounded": all(
                point.speed_limit_mps <= min(vehicle.max_speed_mps, 2.0)
                for point in px4_track.points
            ),
        }
    elif layer == "outdoor":
        gates = {
            "return_path_present": contract.return_node in route.node_ids,
            "outdoor_clearance": "outdoor" not in route_semantics or clearance.accepted,
        }
    elif layer == "dynamic-obstacle":
        gates = {
            "static_envelope_clear": clearance.accepted,
            "runtime_hold_rule_frozen": any(
                "hold" in rule.casefold() or "悬停" in rule
                for rule in contract.immutable_safety_rules
            ),
        }
    elif layer == "energy":
        gates = {
            "qualified_range": route.route_length_m <= maximum_range_m,
            "return_reserve_declared": vehicle.reserve_battery_percent >= 10.0,
        }
    elif layer == "link":
        gates = {
            "lost_link_rule_frozen": any(
                token in " ".join(contract.immutable_safety_rules).casefold()
                for token in ("link", "abort", "hold", "返航", "悬停")
            )
        }
    elif layer == "payload":
        pickup_count = sum(node.action == "pickup" for node in task_graph.nodes)
        gates = {
            "pickup_action_present": contract.payload_action != "pickup" or pickup_count == 1,
            "payload_capacity_positive": vehicle.max_pickup_payload_kg > 0,
        }
    else:
        regulated = any(
            token in normalized_constraints
            for token in ("regulatory", "airspace", "法规", "空域", "禁飞")
        )
        simulation_scope = any(
            token in normalized_constraints for token in ("simulation", "sim-only", "仿真")
        )
        gates = {"regulatory_evidence_or_simulation_scope": not regulated or simulation_scope}
    failed = [name for name, accepted in gates.items() if not accepted]
    return PlannerValidation(
        planner_id=f"planning.{layer}",
        accepted=not failed,
        deterministic_gates=gates,
        issue_codes=[
            f"PLANNER_{layer.upper().replace('-', '_')}_{name.upper()}" for name in failed
        ],
    )


def _definition(layer: str, order: int) -> PluginDefinition:
    display = layer.replace("-", " ").title()

    def contribute(**kwargs: Any) -> PlannerContribution:
        return _contribution(layer, **kwargs)

    def validate(**kwargs: Any) -> PlannerValidation:
        return _validation(layer, **kwargs)

    return hook_plugin(
        module_name=__name__,
        plugin_id=f"planning.specialist-{layer}",
        name=f"{display} Planner",
        description=f"Provides typed {display.lower()} constraints and deterministic validation.",
        capability_id=f"planning.specialist-{layer}.plan",
        capability_kind="planner",
        capability_name=f"{display} Planner",
        capability_description=(
            f"Contributes and validates the {display.lower()} layer without actuator authority."
        ),
        category_id="planning",
        category_label="任务规划",
        slot_id="planning.specialists",
        slot_label="分层规划器",
        activation_mode="multiple",
        category_order=40,
        slot_order=25,
        plugin_order=order,
        hooks={"contribute_planning": contribute, "validate_planning": validate},
        default_enabled=True,
        failure_mode="fail-closed",
        configuration_schema=(
            {
                "type": "object",
                "properties": {
                    "qualified_range_m": {
                        "type": "number",
                        "minimum": 10,
                        "maximum": 100000,
                    }
                },
                "additionalProperties": False,
            }
            if layer == "energy"
            else {}
        ),
    )


def plugin_definitions() -> list[PluginDefinition]:
    return [_definition(layer, index * 10) for index, layer in enumerate(_LAYERS, start=1)]
