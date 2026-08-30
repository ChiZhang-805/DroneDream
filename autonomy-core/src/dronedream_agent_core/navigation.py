"""Generic graph construction and routing from qualified real-map artifacts."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from pathlib import Path
from typing import Any

from .contracts import GraphRoute, MapAsset, MapEdge, MapNode, RouteQuery, Vector3


class NavigationQualificationError(ValueError):
    """Input evidence is insufficient to qualify the graph."""


def _object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise NavigationQualificationError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _road_point(value: object) -> tuple[float, float]:
    if isinstance(value, list) and len(value) == 2:
        return float(value[0]), float(value[1])
    if isinstance(value, str):
        fields = value.split()
        if len(fields) == 2:
            return float(fields[0]), float(fields[1])
    raise NavigationQualificationError(f"road point must contain x and y: {value!r}")


def build_school_map_graph(
    semantic_path: Path,
    verified_track_path: Path,
    mission_evidence_path: Path,
) -> MapAsset:
    """Combine a flight-verified indoor spine with geometry-derived road topology."""

    semantic = _object(semantic_path)
    track = _object(verified_track_path)
    evidence = _object(mission_evidence_path)
    gates = evidence.get("gates")
    if evidence.get("status") != "verified" or not isinstance(gates, dict):
        raise NavigationQualificationError("PX4/Gazebo mission evidence is not verified")
    required_gates = {
        "executor_completed",
        "px4_landing_confirmed",
        "zero_unsafe_dynamic_penetrations",
    }
    if any(gates.get(gate) is not True for gate in required_gates):
        raise NavigationQualificationError("PX4/Gazebo evidence is missing required gates")
    phases = track.get("points")
    world_points = track.get("source_world_points")
    if not isinstance(phases, list) or not isinstance(world_points, list):
        raise NavigationQualificationError("verified track has no aligned world points")
    if len(phases) != len(world_points) or not phases:
        raise NavigationQualificationError("verified track point arrays are misaligned")
    pickup_index = next(
        (
            index
            for index, point in enumerate(phases)
            if isinstance(point, dict) and point.get("phase") == "pickup"
        ),
        None,
    )
    if pickup_index is None:
        raise NavigationQualificationError("verified track has no pickup terminus")

    evidence_hash = _sha256(mission_evidence_path)
    nodes: list[MapNode] = []
    edges: list[MapEdge] = []
    xy_nodes: dict[tuple[float, float], str] = {}

    def add_node(node_id: str, x: float, y: float, z: float, semantic_name: str) -> str:
        nodes.append(
            MapNode(
                node_id=node_id,
                label=node_id.replace("-", " "),
                position_m=Vector3(x=x, y=y, z=z),
                semantic=semantic_name,
            )
        )
        xy_nodes.setdefault((round(x, 3), round(y, 3)), node_id)
        return node_id

    previous_id: str | None = None
    for index in range(pickup_index + 1):
        raw = world_points[index]
        phase = phases[index]
        if not isinstance(raw, dict) or not isinstance(phase, dict):
            raise NavigationQualificationError("verified track point is malformed")
        node_id = f"verified-{index:03d}"
        phase_name = str(phase.get("phase", "transit"))
        semantic_name = (
            "launch"
            if index == 0
            else "pickup"
            if index == pickup_index
            else "stairs"
            if phase_name == "stairs"
            else "corridor"
        )
        add_node(
            node_id,
            float(raw["east_m"]),
            float(raw["north_m"]),
            float(raw["up_m"]),
            semantic_name,
        )
        if previous_id is not None:
            previous = nodes[-2].position_m
            current = nodes[-1].position_m
            distance = math.dist(
                (previous.x, previous.y, previous.z),
                (current.x, current.y, current.z),
            )
            edges.append(
                MapEdge(
                    edge_id=f"verified-edge-{index - 1:03d}",
                    from_node=previous_id,
                    to_node=node_id,
                    distance_m=distance,
                    minimum_clearance_m=0.0,
                    speed_limit_mps=float(phase.get("speed_limit_mps", 0.5)),
                    qualification="flight-verified",
                    evidence_sha256=evidence_hash,
                )
            )
        previous_id = node_id

    roads = semantic.get("roads")
    if not isinstance(roads, dict) or not isinstance(roads.get("segments"), list):
        raise NavigationQualificationError("School Map road topology is missing")
    for segment in roads["segments"]:
        if not isinstance(segment, dict) or not isinstance(segment.get("points"), list):
            raise NavigationQualificationError("road segment is malformed")
        segment_id = str(segment["id"])
        width = float(segment["width_m"])
        last_node: str | None = None
        for index, raw_point in enumerate(segment["points"]):
            x, y = _road_point(raw_point)
            key = (round(x, 3), round(y, 3))
            node_id = xy_nodes.get(key)
            if node_id is None:
                node_id = add_node(f"road-{segment_id}-{index:02d}", x, y, 1.8, "outdoor")
            if last_node is not None and last_node != node_id:
                first = next(node for node in nodes if node.node_id == last_node)
                second = next(node for node in nodes if node.node_id == node_id)
                distance = math.dist(
                    (first.position_m.x, first.position_m.y, first.position_m.z),
                    (second.position_m.x, second.position_m.y, second.position_m.z),
                )
                edge_id = f"road-edge-{segment_id}-{index - 1:02d}"
                if not any(edge.edge_id == edge_id for edge in edges):
                    edges.append(
                        MapEdge(
                            edge_id=edge_id,
                            from_node=last_node,
                            to_node=node_id,
                            distance_m=distance,
                            minimum_clearance_m=max(0.0, width / 2 - 0.38),
                            speed_limit_mps=1.1,
                            qualification="geometry-derived",
                        )
                    )
            last_node = node_id

    named_entities = {
        "office-launch-pad": "verified-000",
        "takeout-pickup-pad": f"verified-{pickup_index:03d}",
    }
    anchors = roads.get("facility_anchors")
    if isinstance(anchors, dict):
        for entity_id, raw_anchor in anchors.items():
            if not isinstance(raw_anchor, list) or len(raw_anchor) < 2:
                continue
            key = (round(float(raw_anchor[0]), 3), round(float(raw_anchor[1]), 3))
            node_id = xy_nodes.get(key)
            if node_id:
                named_entities[str(entity_id)] = node_id

    return MapAsset(
        asset_id="school-map-hybrid-graph",
        name="School Map verified spine plus road topology",
        nodes=nodes,
        edges=edges,
        named_entities=named_entities,
    )


def shortest_route(graph: MapAsset, query: RouteQuery) -> GraphRoute:
    return _weighted_route(graph, query, edge_cost=lambda edge: edge.distance_m)


def clearance_first_route(graph: MapAsset, query: RouteQuery) -> GraphRoute:
    """Prefer generous, verified corridors while still accounting for distance."""

    def edge_cost(edge: MapEdge) -> float:
        clearance_penalty = edge.distance_m * 0.65 / max(edge.minimum_clearance_m, 0.15)
        qualification_penalty = 0.0 if edge.qualification == "flight-verified" else 2.5
        return edge.distance_m + clearance_penalty + qualification_penalty

    return _weighted_route(graph, query, edge_cost=edge_cost)


def energy_efficient_route(graph: MapAsset, query: RouteQuery) -> GraphRoute:
    """Minimize distance, climb and repeated acceleration proxies."""

    nodes = {node.node_id: node for node in graph.nodes}

    def edge_cost(edge: MapEdge) -> float:
        first = nodes[edge.from_node].position_m
        second = nodes[edge.to_node].position_m
        climb = abs(second.z - first.z)
        acceleration_proxy = 0.3 / max(edge.speed_limit_mps, 0.1)
        return edge.distance_m + climb * 2.5 + acceleration_proxy

    return _weighted_route(graph, query, edge_cost=edge_cost)


def stability_first_route(graph: MapAsset, query: RouteQuery) -> GraphRoute:
    """Prefer verified edges, fewer transitions and moderate speed envelopes."""

    def edge_cost(edge: MapEdge) -> float:
        qualification_penalty = 0.0 if edge.qualification == "flight-verified" else 4.0
        transition_penalty = 0.75
        speed_penalty = max(0.0, edge.speed_limit_mps - 1.2) * 2.0
        return edge.distance_m + qualification_penalty + transition_penalty + speed_penalty

    return _weighted_route(graph, query, edge_cost=edge_cost)


def _weighted_route(
    graph: MapAsset,
    query: RouteQuery,
    *,
    edge_cost: Any,
) -> GraphRoute:
    known = {node.node_id: node for node in graph.nodes}
    if query.start_node not in known or query.goal_node not in known:
        raise ValueError("route endpoint is not present in graph")
    adjacency: dict[str, list[tuple[str, MapEdge]]] = {node_id: [] for node_id in known}
    for edge in graph.edges:
        if query.require_flight_verified_edges and edge.qualification != "flight-verified":
            continue
        adjacency[edge.from_node].append((edge.to_node, edge))
        if edge.bidirectional:
            adjacency[edge.to_node].append((edge.from_node, edge))

    queue: list[tuple[float, str]] = [(0.0, query.start_node)]
    costs = {query.start_node: 0.0}
    previous: dict[str, tuple[str, MapEdge]] = {}
    while queue:
        cost, current = heapq.heappop(queue)
        if current == query.goal_node:
            break
        if cost != costs[current]:
            continue
        for neighbor, edge in adjacency[current]:
            candidate = cost + float(edge_cost(edge))
            if candidate < costs.get(neighbor, math.inf):
                costs[neighbor] = candidate
                previous[neighbor] = (current, edge)
                heapq.heappush(queue, (candidate, neighbor))
    if query.goal_node not in costs:
        raise ValueError("no route satisfies graph qualification policy")

    node_ids = [query.goal_node]
    used_edges: list[MapEdge] = []
    while node_ids[-1] != query.start_node:
        parent, edge = previous[node_ids[-1]]
        used_edges.append(edge)
        node_ids.append(parent)
    node_ids.reverse()
    used_edges.reverse()
    return GraphRoute(
        start_node=query.start_node,
        goal_node=query.goal_node,
        node_ids=node_ids,
        edge_ids=[edge.edge_id for edge in used_edges],
        positions_m=[known[node_id].position_m for node_id in node_ids],
        route_length_m=sum(edge.distance_m for edge in used_edges),
        all_edges_flight_verified=all(
            edge.qualification == "flight-verified" for edge in used_edges
        ),
    )
