"""Convert validated ENU graph routes into the real PX4 executor contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .contracts import (
    GraphRoute,
    MapAsset,
    Px4CoordinateContract,
    Px4Track,
    Px4TrackPoint,
    RuntimeTrackRequest,
    WorldTrackPoint,
)


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def route_to_px4_track(
    route: GraphRoute,
    graph: MapAsset,
    semantic_path: Path,
    *,
    waypoint_hold_seconds: float = 0.4,
) -> Px4Track:
    semantic = _load(semantic_path)
    bindings = semantic.get("simulation_bindings")
    if not isinstance(bindings, dict):
        raise ValueError("semantic simulation bindings are missing")
    spawn = bindings.get("px4_recommended_spawn")
    offset = bindings.get("vehicle_collision_center_offset")
    launch = bindings.get("mission_launch_waypoint")
    if not all(isinstance(value, dict) for value in (spawn, offset, launch)):
        raise ValueError("PX4 spawn, collision offset, or launch waypoint is missing")
    model_root = (float(spawn["x"]), float(spawn["y"]), float(spawn["z"]))
    center_offset_z = float(offset["z"])
    expected_launch = (float(launch["x"]), float(launch["y"]), float(launch["z"]))
    first = route.positions_m[0]
    if math.dist((first.x, first.y, first.z), expected_launch) > 0.02:
        raise ValueError("route does not begin at the qualified PX4 launch waypoint")

    edge_by_id = {edge.edge_id: edge for edge in graph.edges}
    speed_limits = []
    for edge_id in route.edge_ids:
        edge = edge_by_id.get(edge_id)
        if edge is None:
            raise ValueError(f"route references an unknown edge: {edge_id}")
        speed_limits.append(edge.speed_limit_mps)
    if len(speed_limits) != len(route.positions_m) - 1:
        raise ValueError("route point and edge counts do not align")

    points: list[Px4TrackPoint] = []
    world_points: list[WorldTrackPoint] = []
    for index, world in enumerate(route.positions_m):
        phase = (
            "launch" if index == 0 else "land" if index == len(route.positions_m) - 1 else "transit"
        )
        node_id = route.node_ids[index]
        node = next(item for item in graph.nodes if item.node_id == node_id)
        if node.semantic == "stairs" and phase == "transit":
            phase = "stairs"
        speed = speed_limits[index - 1] if index > 0 else speed_limits[0]
        points.append(
            Px4TrackPoint(
                x=world.y - model_root[1],
                y=world.x - model_root[0],
                z=world.z - model_root[2] - center_offset_z,
                phase=phase,
                speed_limit_mps=speed,
            )
        )
        world_points.append(WorldTrackPoint(east_m=world.x, north_m=world.y, up_m=world.z))
    return Px4Track(
        coordinate_contract=Px4CoordinateContract(
            model_root_world_enu_m=list(model_root),
            collision_center_above_model_root_m=center_offset_z,
        ),
        points=points,
        source_world_points=world_points,
        waypoint_hold_seconds=waypoint_hold_seconds,
    )


def runtime_route_to_px4_track(
    request: RuntimeTrackRequest,
    graph: MapAsset,
) -> Px4Track:
    """Convert a stable-hold replacement route without assuming the launch origin."""

    route = request.route
    prior_track = request.prior_track
    vehicle = request.vehicle
    root_east, root_north, root_up = prior_track.coordinate_contract.model_root_world_enu_m
    center_offset = prior_track.coordinate_contract.collision_center_above_model_root_m
    edges = {edge.edge_id: edge for edge in graph.edges}
    nodes = {node.node_id: node for node in graph.nodes}
    join_speed = min(0.6, vehicle.max_speed_mps)
    points: list[Px4TrackPoint] = []
    world_points: list[WorldTrackPoint] = []
    target_seen = False
    for index, (node_id, world) in enumerate(zip(route.node_ids, route.positions_m, strict=True)):
        if index == len(route.positions_m) - 1:
            phase = "land"
        elif node_id == request.target_node and not target_seen:
            phase = "pickup"
            target_seen = True
        elif target_seen:
            phase = "return"
        else:
            semantic = nodes[node_id].semantic if node_id in nodes else "outdoor"
            phase = "stairs" if semantic == "stairs" else "transit"
        edge_id = route.edge_ids[max(0, index - 1)] if route.edge_ids else "runtime-safe-join"
        edge_speed = edges[edge_id].speed_limit_mps if edge_id in edges else join_speed
        points.append(
            Px4TrackPoint(
                x=world.y - root_north,
                y=world.x - root_east,
                z=world.z - root_up - center_offset,
                phase=phase,
                speed_limit_mps=min(edge_speed, vehicle.max_speed_mps),
            )
        )
        world_points.append(WorldTrackPoint(east_m=world.x, north_m=world.y, up_m=world.z))
    return Px4Track(
        coordinate_contract=prior_track.coordinate_contract,
        points=points,
        source_world_points=world_points,
        stop_at_waypoints=True,
        waypoint_hold_seconds=prior_track.waypoint_hold_seconds,
    )
