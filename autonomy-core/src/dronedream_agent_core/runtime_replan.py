"""Deterministic online rerouting from a telemetry-confirmed stable hold."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path

from .contracts import (
    CoveragePattern,
    CoveragePlanRequest,
    GraphRoute,
    MapAsset,
    MapCatalog,
    Px4Track,
    RouteClearanceReport,
    RouteQuery,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeReplacementTrack,
    RuntimeToolReceipt,
    RuntimeTrackRequest,
    RuntimeUserMessage,
    Vector3,
    VehicleAsset,
)
from .extensions import ExtensionExecutionError
from .hashing import sha256_json
from .plugin_api import (
    ToolEnvironment,
    build_discovered_extension_registry,
    build_discovered_tool_registry,
    build_snapshot_tool_registry,
)
from .plugin_contracts import PluginSnapshot
from .tools import ToolReceipt, ToolRegistry


class RuntimeReplanError(RuntimeError):
    """No safe, fully bound replacement route could be produced."""


def _resolve_target(entity: str, catalog: MapCatalog, graph: MapAsset) -> str:
    node_ids = {node.node_id for node in graph.nodes}
    if entity in node_ids:
        return entity
    direct = graph.named_entities.get(entity)
    if direct is not None:
        return direct
    normalized = entity.casefold().strip()
    partial_matches: set[str] = set()
    for item in catalog.entities:
        candidates = {item.entity_id.casefold(), *(alias.casefold() for alias in item.aliases)}
        if normalized in candidates:
            resolved = graph.named_entities.get(item.entity_id)
            if resolved is not None:
                return resolved
        # Runtime classifiers preserve the user's complete named phrase, while
        # catalog aliases are intentionally concise. Accept a containment match
        # only when it identifies exactly one graph node; competing aliases fail
        # closed instead of guessing between destinations.
        if any(len(candidate) >= 2 and candidate in normalized for candidate in candidates):
            resolved = graph.named_entities.get(item.entity_id)
            if resolved is not None:
                partial_matches.add(resolved)
    if len(partial_matches) == 1:
        return partial_matches.pop()
    if partial_matches:
        raise RuntimeReplanError(f"RUNTIME_TARGET_AMBIGUOUS:{entity}")
    raise RuntimeReplanError(f"RUNTIME_TARGET_UNRESOLVED:{entity}")


def _current_world_position(ack: RuntimeHoldAcknowledgement, prior_track: Px4Track) -> Vector3:
    root_east, root_north, root_up = prior_track.coordinate_contract.model_root_world_enu_m
    center_offset = prior_track.coordinate_contract.collision_center_above_model_root_m
    observed = ack.observed_position_ned_m
    return Vector3(
        x=root_east + observed.y,
        y=root_north + observed.x,
        z=root_up + center_offset - observed.z,
    )


def _replacement_route(
    graph: MapAsset,
    registry: ToolRegistry,
    *,
    current_world: Vector3,
    anchor: str,
    target_node: str,
    return_node: str,
) -> tuple[GraphRoute, list[ToolReceipt]]:
    outbound_value, outbound_receipt = registry.call_slot(
        "planning.route-strategy", RouteQuery(start_node=anchor, goal_node=target_node)
    )
    outbound = GraphRoute.model_validate(outbound_value)
    anchor_position = next(node.position_m for node in graph.nodes if node.node_id == anchor)
    join_distance = math.dist(
        (current_world.x, current_world.y, current_world.z),
        (anchor_position.x, anchor_position.y, anchor_position.z),
    )
    receipts = [outbound_receipt]
    if target_node == return_node:
        node_ids = ["runtime-current", *outbound.node_ids]
        edge_ids = ["runtime-safe-join", *outbound.edge_ids]
        positions = [current_world, *outbound.positions_m]
        route_length = join_distance + outbound.route_length_m
    else:
        inbound_value, inbound_receipt = registry.call_slot(
            "planning.route-strategy", RouteQuery(start_node=target_node, goal_node=return_node)
        )
        inbound = GraphRoute.model_validate(inbound_value)
        receipts.append(inbound_receipt)
        node_ids = ["runtime-current", *outbound.node_ids, *inbound.node_ids[1:]]
        edge_ids = ["runtime-safe-join", *outbound.edge_ids, *inbound.edge_ids]
        positions = [current_world, *outbound.positions_m, *inbound.positions_m[1:]]
        route_length = join_distance + outbound.route_length_m + inbound.route_length_m
    return (
        GraphRoute(
            start_node="runtime-current",
            goal_node=return_node,
            node_ids=node_ids,
            edge_ids=edge_ids,
            positions_m=positions,
            route_length_m=route_length,
            all_edges_flight_verified=False,
        ),
        receipts,
    )


def build_runtime_replacement(
    *,
    message: RuntimeUserMessage,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
    replacement_sequence: int,
    prior_track_sha256: str,
    prior_track: Px4Track,
    graph: MapAsset,
    catalog: MapCatalog,
    semantic_path: Path,
    vehicle: VehicleAsset,
    expected_map_sha256: str,
    expected_semantic_sha256: str,
    expected_vehicle_asset_id: str,
    return_node: str,
    active_target_node: str | None = None,
    plugin_snapshot: PluginSnapshot | None = None,
) -> RuntimeReplacementTrack:
    target_entity = decision.classification.target_entity
    if decision.authorized_action != "hold_for_replan" or not target_entity:
        raise RuntimeReplanError("RUNTIME_REPLAN_TARGET_REQUIRED")
    target_node = _resolve_target(target_entity, catalog, graph)
    requested_return_node: str | None = None
    if decision.classification.requested_action == "set_return_point":
        requested_return_node = target_node
        return_node = target_node
    current_world = _current_world_position(acknowledgement, prior_track)
    if requested_return_node is not None:
        nearest_index = min(
            range(len(prior_track.source_world_points)),
            key=lambda index: math.dist(
                (current_world.x, current_world.y, current_world.z),
                (
                    prior_track.source_world_points[index].east_m,
                    prior_track.source_world_points[index].north_m,
                    prior_track.source_world_points[index].up_m,
                ),
            ),
        )
        pickup_indices = [
            index for index, point in enumerate(prior_track.points) if point.phase == "pickup"
        ]
        target_already_reached = bool(pickup_indices and nearest_index > pickup_indices[0])
        target_node = (
            requested_return_node
            if target_already_reached
            else active_target_node or requested_return_node
        )
    environment = ToolEnvironment(
        map_graph=graph,
        semantic_path=semantic_path,
        vehicle_diameter_m=vehicle.body_radius_m * 2.0,
        vehicle_height_m=vehicle.body_height_m,
        waypoint_hold_seconds=prior_track.waypoint_hold_seconds,
    )
    if plugin_snapshot is None:
        registry, _snapshot = build_discovered_tool_registry(environment)
    else:
        registry = build_snapshot_tool_registry(environment, plugin_snapshot)
    extensions = build_discovered_extension_registry(plugin_snapshot)
    try:
        replan_policy, hook_receipts = extensions.invoke_single(
            "runtime.replan-policy",
            "select_anchor",
            required=True,
            current_world=current_world,
            graph=graph,
            target_node=target_node,
            return_node=return_node,
            acknowledgement=acknowledgement,
        )
    except ExtensionExecutionError as error:
        raise RuntimeReplanError(str(error)) from error
    if not isinstance(replan_policy, dict):
        raise RuntimeReplanError("RUNTIME_REPLAN_POLICY_INVALID")
    anchor = replan_policy.get("anchor_node")
    maximum_join_distance = replan_policy.get("maximum_join_distance_m")
    require_verified_anchor = replan_policy.get("requires_flight_verified_anchor")
    if (
        not isinstance(anchor, str)
        or not isinstance(maximum_join_distance, (int, float))
        or maximum_join_distance <= 0
        or not isinstance(require_verified_anchor, bool)
    ):
        raise RuntimeReplanError("RUNTIME_REPLAN_POLICY_INVALID")
    try:
        anchor_position = next(node.position_m for node in graph.nodes if node.node_id == anchor)
    except StopIteration:
        raise RuntimeReplanError("RUNTIME_REPLAN_ANCHOR_UNKNOWN") from None
    join_distance = math.dist(
        (current_world.x, current_world.y, current_world.z),
        (anchor_position.x, anchor_position.y, anchor_position.z),
    )
    if join_distance > float(maximum_join_distance):
        raise RuntimeReplanError("RUNTIME_REPLAN_ANCHOR_TOO_FAR")
    if require_verified_anchor and not any(
        edge.qualification == "flight-verified" and anchor in {edge.from_node, edge.to_node}
        for edge in graph.edges
    ):
        raise RuntimeReplanError("RUNTIME_REPLAN_ANCHOR_NOT_FLIGHT_VERIFIED")
    amendment_action = decision.classification.requested_action
    active_return_node = target_node if amendment_action == "follow_target" else return_node
    route, receipts = _replacement_route(
        graph,
        registry,
        current_world=current_world,
        anchor=anchor,
        target_node=target_node,
        return_node=active_return_node,
    )
    clearance_value, clearance_receipt = registry.call_slot("safety.route-clearance", route)
    clearance = RouteClearanceReport.model_validate(clearance_value)
    track_value, track_receipt = registry.call_slot(
        "runtime.track-export",
        RuntimeTrackRequest(
            route=route,
            prior_track=prior_track,
            target_node=target_node,
            vehicle=vehicle,
        ),
    )
    track = Px4Track.model_validate(track_value)
    receipts.extend([clearance_receipt, track_receipt])
    gates = {
        "message_matches_decision": decision.message_sha256 == sha256_json(message),
        "hold_matches_decision": decision.hold_ack_sha256 == sha256_json(acknowledgement),
        "decision_authorized_replan": decision.authorized_action == "hold_for_replan",
        "stable_hold_gates_passed": all(acknowledgement.deterministic_gates.values()),
        "map_hash_matches_contract": sha256_json(graph) == expected_map_sha256,
        "semantic_hash_matches_contract": (
            hashlib.sha256(semantic_path.read_bytes()).hexdigest() == expected_semantic_sha256
        ),
        "vehicle_identity_matches_contract": vehicle.asset_id == expected_vehicle_asset_id,
        "replacement_clearance_accepted": clearance.accepted,
        "replacement_begins_at_stable_hold": (
            math.dist(
                (track.points[0].x, track.points[0].y, -track.points[0].z),
                (
                    acknowledgement.observed_position_ned_m.x,
                    acknowledgement.observed_position_ned_m.y,
                    acknowledgement.observed_position_ned_m.z,
                ),
            )
            <= 0.05
        ),
    }
    if not all(gates.values()):
        failed = ",".join(name for name, accepted in gates.items() if not accepted)
        raise RuntimeReplanError(f"RUNTIME_REPLAN_GATE_FAILED:{failed}")
    return RuntimeReplacementTrack(
        message_id=message.message_id,
        execution_id=message.execution_id,
        replacement_sequence=replacement_sequence,
        message_sha256=sha256_json(message),
        hold_ack_sha256=sha256_json(acknowledgement),
        decision_sha256=sha256_json(decision),
        prior_track_sha256=prior_track_sha256,
        amendment_action=(
            amendment_action
            if amendment_action
            in {
                "replan",
                "redirect",
                "return_home",
                "set_return_point",
                "set_coverage",
                "follow_target",
            }
            else "replan"
        ),
        amendment_parameters=dict(
            {
                **(
                    decision.amendment_directive.parameters
                    if decision.amendment_directive is not None
                    else decision.classification.parameters
                ),
                **(
                    {"new_return_node": requested_return_node}
                    if requested_return_node is not None
                    else {}
                ),
            }
        ),
        target_node=target_node,
        return_node=return_node,
        route=route,
        clearance=clearance,
        track=track,
        plugin_tool_receipts=[
            RuntimeToolReceipt(
                tool_id=receipt.tool_id,
                plugin_id=receipt.plugin_id,
                plugin_package_sha256=receipt.plugin_package_sha256,
                outcome=receipt.outcome,
                input_sha256=receipt.input_sha256,
                output_sha256=receipt.output_sha256,
            )
            for receipt in receipts
        ],
        plugin_hook_receipts=hook_receipts,
        deterministic_gates=gates,
        generated_at=datetime.now(UTC),
    )


def build_runtime_speed_replacement(
    *,
    message: RuntimeUserMessage,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
    replacement_sequence: int,
    prior_track_sha256: str,
    prior_track: Px4Track,
    graph: MapAsset,
    semantic_path: Path,
    vehicle: VehicleAsset,
    expected_map_sha256: str,
    expected_semantic_sha256: str,
    expected_vehicle_asset_id: str,
    plugin_snapshot: PluginSnapshot | None = None,
) -> RuntimeReplacementTrack:
    """Rebuild only the remaining trajectory with a deterministic speed ceiling."""

    if (
        decision.authorized_action != "hold_for_replan"
        or decision.classification.requested_action != "set_speed"
    ):
        raise RuntimeReplanError("RUNTIME_SPEED_REPLACEMENT_NOT_AUTHORIZED")
    raw_speed = decision.classification.parameters.get("maximum_speed_mps")
    if not isinstance(raw_speed, int | float) or isinstance(raw_speed, bool):
        raise RuntimeReplanError("RUNTIME_SPEED_VALUE_REQUIRED")
    speed_limit = float(raw_speed)
    if not 0.1 <= speed_limit <= vehicle.max_speed_mps:
        raise RuntimeReplanError("RUNTIME_SPEED_OUTSIDE_VEHICLE_ENVELOPE")
    current_world = _current_world_position(acknowledgement, prior_track)
    prior_world = prior_track.source_world_points
    nearest_index = min(
        range(len(prior_world)),
        key=lambda index: math.dist(
            (current_world.x, current_world.y, current_world.z),
            (
                prior_world[index].east_m,
                prior_world[index].north_m,
                prior_world[index].up_m,
            ),
        ),
    )
    suffix = prior_world[nearest_index + 1 :]
    if not suffix:
        suffix = [prior_world[-1]]
    positions = [
        current_world,
        *[Vector3(x=point.east_m, y=point.north_m, z=point.up_m) for point in suffix],
    ]
    node_ids = [
        "runtime-current",
        *[f"runtime-speed-{index:04d}" for index in range(1, len(positions))],
    ]
    edge_ids = [f"runtime-speed-edge-{index:04d}" for index in range(len(positions) - 1)]
    route = GraphRoute(
        start_node=node_ids[0],
        goal_node=node_ids[-1],
        node_ids=node_ids,
        edge_ids=edge_ids,
        positions_m=positions,
        route_length_m=sum(
            math.dist(
                (start.x, start.y, start.z),
                (end.x, end.y, end.z),
            )
            for start, end in zip(positions, positions[1:], strict=False)
        ),
        all_edges_flight_verified=False,
    )
    environment = ToolEnvironment(
        map_graph=graph,
        semantic_path=semantic_path,
        vehicle_diameter_m=vehicle.body_radius_m * 2.0,
        vehicle_height_m=vehicle.body_height_m,
        waypoint_hold_seconds=prior_track.waypoint_hold_seconds,
    )
    registry = (
        build_discovered_tool_registry(environment)[0]
        if plugin_snapshot is None
        else build_snapshot_tool_registry(environment, plugin_snapshot)
    )
    clearance_value, clearance_receipt = registry.call_slot("safety.route-clearance", route)
    clearance = RouteClearanceReport.model_validate(clearance_value)
    track_value, track_receipt = registry.call_slot(
        "runtime.track-export",
        RuntimeTrackRequest(
            route=route,
            prior_track=prior_track,
            target_node=node_ids[-1],
            vehicle=vehicle,
        ),
    )
    exported = Px4Track.model_validate(track_value)
    track = exported.model_copy(
        update={
            "points": [
                point.model_copy(
                    update={"speed_limit_mps": min(point.speed_limit_mps, speed_limit)}
                )
                for point in exported.points
            ]
        }
    )
    gates = {
        "message_matches_decision": decision.message_sha256 == sha256_json(message),
        "hold_matches_decision": decision.hold_ack_sha256 == sha256_json(acknowledgement),
        "decision_authorized_replan": decision.authorized_action == "hold_for_replan",
        "stable_hold_gates_passed": all(acknowledgement.deterministic_gates.values()),
        "map_hash_matches_contract": sha256_json(graph) == expected_map_sha256,
        "semantic_hash_matches_contract": (
            hashlib.sha256(semantic_path.read_bytes()).hexdigest() == expected_semantic_sha256
        ),
        "vehicle_identity_matches_contract": vehicle.asset_id == expected_vehicle_asset_id,
        "replacement_clearance_accepted": clearance.accepted,
        "replacement_begins_at_stable_hold": (
            math.dist(
                (track.points[0].x, track.points[0].y, -track.points[0].z),
                (
                    acknowledgement.observed_position_ned_m.x,
                    acknowledgement.observed_position_ned_m.y,
                    acknowledgement.observed_position_ned_m.z,
                ),
            )
            <= 0.05
        ),
        "all_points_respect_speed_ceiling": all(
            point.speed_limit_mps <= speed_limit for point in track.points
        ),
    }
    if not all(gates.values()):
        failed = ",".join(name for name, accepted in gates.items() if not accepted)
        raise RuntimeReplanError(f"RUNTIME_SPEED_REPLACEMENT_GATE_FAILED:{failed}")
    return RuntimeReplacementTrack(
        message_id=message.message_id,
        execution_id=message.execution_id,
        replacement_sequence=replacement_sequence,
        message_sha256=sha256_json(message),
        hold_ack_sha256=sha256_json(acknowledgement),
        decision_sha256=sha256_json(decision),
        prior_track_sha256=prior_track_sha256,
        amendment_action="set_speed",
        amendment_parameters={"maximum_speed_mps": speed_limit},
        target_node=node_ids[-1],
        return_node=node_ids[-1],
        route=route,
        clearance=clearance,
        track=track,
        plugin_tool_receipts=[
            RuntimeToolReceipt(
                tool_id=receipt.tool_id,
                plugin_id=receipt.plugin_id,
                plugin_package_sha256=receipt.plugin_package_sha256,
                outcome=receipt.outcome,
                input_sha256=receipt.input_sha256,
                output_sha256=receipt.output_sha256,
            )
            for receipt in (clearance_receipt, track_receipt)
        ],
        deterministic_gates=gates,
        generated_at=datetime.now(UTC),
    )


def build_runtime_coverage_replacement(
    *,
    message: RuntimeUserMessage,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
    replacement_sequence: int,
    prior_track_sha256: str,
    prior_track: Px4Track,
    graph: MapAsset,
    catalog: MapCatalog,
    semantic_path: Path,
    vehicle: VehicleAsset,
    expected_map_sha256: str,
    expected_semantic_sha256: str,
    expected_vehicle_asset_id: str,
    return_node: str,
    plugin_snapshot: PluginSnapshot | None = None,
) -> RuntimeReplacementTrack:
    """Build a real lane/spiral coverage track through a selected coverage plugin."""

    if (
        decision.authorized_action != "hold_for_replan"
        or decision.classification.requested_action != "set_coverage"
    ):
        raise RuntimeReplanError("RUNTIME_COVERAGE_NOT_AUTHORIZED")
    parameters = dict(
        decision.amendment_directive.parameters
        if decision.amendment_directive is not None
        else decision.classification.parameters
    )
    target_entity = decision.classification.target_entity
    raw_polygon = parameters.get("polygon_enu_m", [])
    if not isinstance(raw_polygon, list):
        raise RuntimeReplanError("RUNTIME_COVERAGE_POLYGON_INVALID")
    try:
        polygon = [Vector3.model_validate(point) for point in raw_polygon]
    except ValueError as exc:
        raise RuntimeReplanError("RUNTIME_COVERAGE_POLYGON_INVALID") from exc
    if target_entity:
        target_node = _resolve_target(target_entity, catalog, graph)
        center = next(node.position_m for node in graph.nodes if node.node_id == target_node)
    elif len(polygon) >= 3:
        center = Vector3(
            x=sum(point.x for point in polygon) / len(polygon),
            y=sum(point.y for point in polygon) / len(polygon),
            z=sum(point.z for point in polygon) / len(polygon),
        )
        target_node = min(
            graph.nodes,
            key=lambda node: math.dist(
                (node.position_m.x, node.position_m.y, node.position_m.z),
                (center.x, center.y, center.z),
            ),
        ).node_id
    else:
        raise RuntimeReplanError("RUNTIME_COVERAGE_TARGET_OR_POLYGON_REQUIRED")
    lane_spacing = float(parameters.get("lane_spacing_m", max(vehicle.body_radius_m * 2.5, 0.5)))
    boundary_margin = float(parameters.get("boundary_margin_m", vehicle.body_radius_m + 0.15))
    request = CoveragePlanRequest(
        center_enu_m=center,
        polygon_enu_m=polygon,
        width_m=float(parameters.get("width_m", 6.0)),
        height_m=float(parameters.get("height_m", 6.0)),
        lane_spacing_m=lane_spacing,
        boundary_margin_m=boundary_margin,
        altitude_m=float(parameters.get("altitude_m", center.z)),
    )
    environment = ToolEnvironment(
        map_graph=graph,
        semantic_path=semantic_path,
        vehicle_diameter_m=vehicle.body_radius_m * 2.0,
        vehicle_height_m=vehicle.body_height_m,
        waypoint_hold_seconds=prior_track.waypoint_hold_seconds,
    )
    registry = (
        build_discovered_tool_registry(environment)[0]
        if plugin_snapshot is None
        else build_snapshot_tool_registry(environment, plugin_snapshot)
    )
    extensions = build_discovered_extension_registry(plugin_snapshot)
    current_world = _current_world_position(acknowledgement, prior_track)
    try:
        anchor_value, anchor_receipts = extensions.invoke_single(
            "runtime.replan-policy",
            "select_anchor",
            required=True,
            current_world=current_world,
            graph=graph,
            target_node=target_node,
            return_node=return_node,
            acknowledgement=acknowledgement,
        )
        pattern_value, coverage_receipts = extensions.invoke_single(
            "runtime.coverage-planner",
            "plan_coverage",
            required=True,
            request=request,
        )
    except ExtensionExecutionError as error:
        raise RuntimeReplanError(str(error)) from error
    if not isinstance(anchor_value, dict) or not isinstance(anchor_value.get("anchor_node"), str):
        raise RuntimeReplanError("RUNTIME_COVERAGE_ANCHOR_INVALID")
    anchor = str(anchor_value["anchor_node"])
    pattern = CoveragePattern.model_validate(pattern_value)
    if not all(pattern.deterministic_gates.values()):
        raise RuntimeReplanError("RUNTIME_COVERAGE_PATTERN_GATE_FAILED")
    outbound_value, outbound_receipt = registry.call_slot(
        "planning.route-strategy", RouteQuery(start_node=anchor, goal_node=target_node)
    )
    inbound_value, inbound_receipt = registry.call_slot(
        "planning.route-strategy", RouteQuery(start_node=target_node, goal_node=return_node)
    )
    outbound = GraphRoute.model_validate(outbound_value)
    inbound = GraphRoute.model_validate(inbound_value)
    anchor_position = next(node.position_m for node in graph.nodes if node.node_id == anchor)
    coverage_nodes = [f"runtime-coverage-{index:04d}" for index in range(len(pattern.points_enu_m))]
    positions = [
        current_world,
        *outbound.positions_m,
        *pattern.points_enu_m,
        *inbound.positions_m,
    ]
    node_ids = [
        "runtime-current",
        *outbound.node_ids,
        *coverage_nodes,
        *inbound.node_ids,
    ]
    edge_ids = [f"runtime-coverage-edge-{index:04d}" for index in range(len(positions) - 1)]
    route = GraphRoute(
        start_node="runtime-current",
        goal_node=return_node,
        node_ids=node_ids,
        edge_ids=edge_ids,
        positions_m=positions,
        route_length_m=sum(
            math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
            for a, b in zip(positions, positions[1:], strict=False)
        ),
        all_edges_flight_verified=False,
    )
    clearance_value, clearance_receipt = registry.call_slot("safety.route-clearance", route)
    clearance = RouteClearanceReport.model_validate(clearance_value)
    track_value, track_receipt = registry.call_slot(
        "runtime.track-export",
        RuntimeTrackRequest(
            route=route,
            prior_track=prior_track,
            target_node=target_node,
            vehicle=vehicle,
        ),
    )
    track = Px4Track.model_validate(track_value)
    join_distance = math.dist(
        (current_world.x, current_world.y, current_world.z),
        (anchor_position.x, anchor_position.y, anchor_position.z),
    )
    max_join = float(anchor_value.get("maximum_join_distance_m", 0.0))
    gates = {
        "message_matches_decision": decision.message_sha256 == sha256_json(message),
        "hold_matches_decision": decision.hold_ack_sha256 == sha256_json(acknowledgement),
        "decision_authorized_coverage": decision.authorized_action == "hold_for_replan",
        "stable_hold_gates_passed": all(acknowledgement.deterministic_gates.values()),
        "map_hash_matches_contract": sha256_json(graph) == expected_map_sha256,
        "semantic_hash_matches_contract": (
            hashlib.sha256(semantic_path.read_bytes()).hexdigest() == expected_semantic_sha256
        ),
        "vehicle_identity_matches_contract": vehicle.asset_id == expected_vehicle_asset_id,
        "coverage_pattern_gates_passed": all(pattern.deterministic_gates.values()),
        "coverage_has_multiple_points": len(pattern.points_enu_m) >= 2,
        "safe_anchor_join": max_join > 0 and join_distance <= max_join,
        "replacement_clearance_accepted": clearance.accepted,
        "replacement_begins_at_stable_hold": (
            math.dist(
                (track.points[0].x, track.points[0].y, -track.points[0].z),
                (
                    acknowledgement.observed_position_ned_m.x,
                    acknowledgement.observed_position_ned_m.y,
                    acknowledgement.observed_position_ned_m.z,
                ),
            )
            <= 0.05
        ),
    }
    if not all(gates.values()):
        failed = ",".join(name for name, accepted in gates.items() if not accepted)
        raise RuntimeReplanError(f"RUNTIME_COVERAGE_GATE_FAILED:{failed}")
    return RuntimeReplacementTrack(
        message_id=message.message_id,
        execution_id=message.execution_id,
        replacement_sequence=replacement_sequence,
        message_sha256=sha256_json(message),
        hold_ack_sha256=sha256_json(acknowledgement),
        decision_sha256=sha256_json(decision),
        prior_track_sha256=prior_track_sha256,
        amendment_action="set_coverage",
        amendment_parameters={
            **parameters,
            "pattern": pattern.pattern,
            "lane_count": pattern.lane_count,
            "estimated_area_m2": pattern.estimated_area_m2,
        },
        target_node=target_node,
        return_node=return_node,
        route=route,
        clearance=clearance,
        track=track,
        plugin_tool_receipts=[
            RuntimeToolReceipt(
                tool_id=receipt.tool_id,
                plugin_id=receipt.plugin_id,
                plugin_package_sha256=receipt.plugin_package_sha256,
                outcome=receipt.outcome,
                input_sha256=receipt.input_sha256,
                output_sha256=receipt.output_sha256,
            )
            for receipt in (
                outbound_receipt,
                inbound_receipt,
                clearance_receipt,
                track_receipt,
            )
        ],
        plugin_hook_receipts=[*anchor_receipts, *coverage_receipts],
        deterministic_gates=gates,
        generated_at=datetime.now(UTC),
    )
