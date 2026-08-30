"""Bounded structured map context for text-only and multimodal model roles.

The language model never receives raw collision meshes as its source of truth.  This
module converts the qualified graph and semantic contract into a compact, hash-bound
description that a text-only model can reason over while deterministic tools retain
ownership of geometry, clearance, and actuator authority.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .contracts import MapAsset, MapCatalog, RouteQuery
from .hashing import sha256_json
from .navigation import shortest_route

MAX_REASONING_NODES = 384
MAX_REASONING_EDGES = 768


def _semantic_summary(semantic_path: Path) -> dict[str, object]:
    try:
        semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "available": False,
            "issue_codes": ["MAP_SEMANTIC_CONTEXT_UNAVAILABLE"],
        }
    if not isinstance(semantic, dict):
        return {
            "available": False,
            "issue_codes": ["MAP_SEMANTIC_CONTEXT_INVALID"],
        }
    limits = [str(item) for item in semantic.get("known_export_limits", [])]
    dynamic_people = semantic.get("dynamic_people")
    if not isinstance(dynamic_people, dict):
        dynamic_people = {}
    occupancy_ready = not any(
        "occupancy" in item.lower() and "must be generated" in item.lower() for item in limits
    )
    return {
        "available": True,
        "coordinate_frame": semantic.get("coordinate_frame"),
        "geometry_scope": semantic.get("geometry_scope"),
        "collision_primitive_count": len(semantic.get("collision_primitives", [])),
        "runtime_collision_primitive_count": len(
            semantic.get("runtime_collision_primitives", [])
        ),
        "occupancy_esdf_ready": occupancy_ready,
        "dynamic_obstacles_runtime_required": bool(
            dynamic_people.get("runtime_spawn_required", False)
        ),
        "dynamic_obstacles_in_static_collision": bool(
            dynamic_people.get("static_collision_present", False)
        ),
        "known_limits": limits[:16],
    }


def _corridor_node_priority(graph: MapAsset, focus_nodes: list[str]) -> list[str]:
    priority = list(dict.fromkeys(node_id for node_id in focus_nodes if node_id))
    for start, goal in zip(focus_nodes, focus_nodes[1:], strict=False):
        if not start or not goal or start == goal:
            continue
        try:
            route = shortest_route(graph, RouteQuery(start_node=start, goal_node=goal))
            priority.extend(route.node_ids)
        except ValueError:
            # The deterministic planner will fail closed later.  Retaining the endpoints
            # still lets the model explain the disconnected topology without inventing it.
            priority.extend((start, goal))
    return list(dict.fromkeys(priority))


def _selected_nodes(graph: MapAsset, focus_nodes: list[str]) -> tuple[set[str], bool]:
    known = {node.node_id for node in graph.nodes}
    priority = _corridor_node_priority(graph, focus_nodes)
    priority.extend(
        node_id
        for _entity_id, node_id in sorted(graph.named_entities.items())
        if node_id in known
    )
    required = list(dict.fromkeys(priority))[:MAX_REASONING_NODES]
    if len(graph.nodes) <= MAX_REASONING_NODES:
        return known, False

    adjacency: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.from_node].append((edge.distance_m, edge.to_node))
        if edge.bidirectional:
            adjacency[edge.to_node].append((edge.distance_m, edge.from_node))

    # Expand deterministically from the mission corridor and named anchors.  The full
    # graph hash remains in the context, so a truncated synopsis can never masquerade as
    # the complete safety artifact.
    selected = set(required)
    frontier = list(required)
    while frontier and len(selected) < MAX_REASONING_NODES:
        current = frontier.pop(0)
        for _distance, neighbor in sorted(adjacency[current]):
            if neighbor in selected:
                continue
            selected.add(neighbor)
            frontier.append(neighbor)
            if len(selected) >= MAX_REASONING_NODES:
                break
    return selected, len(selected) < len(known)


def build_map_reasoning_context(
    graph: MapAsset,
    catalog: MapCatalog,
    semantic_path: Path,
    *,
    focus_nodes: list[str] | None = None,
) -> dict[str, object]:
    """Return a deterministic, bounded topology description safe for text models."""

    focus = [item for item in (focus_nodes or []) if item]
    selected, truncated = _selected_nodes(graph, focus)
    nodes = {node.node_id: node for node in graph.nodes}
    selected_edges = [
        edge
        for edge in graph.edges
        if edge.from_node in selected and edge.to_node in selected
    ][:MAX_REASONING_EDGES]
    x_values = [node.position_m.x for node in graph.nodes]
    y_values = [node.position_m.y for node in graph.nodes]
    z_values = [node.position_m.z for node in graph.nodes]

    focus_routes: list[dict[str, object]] = []
    for start, goal in zip(focus, focus[1:], strict=False):
        if start == goal:
            continue
        try:
            route = shortest_route(graph, RouteQuery(start_node=start, goal_node=goal))
            route_nodes = route.node_ids
            route_nodes_truncated = len(route_nodes) > MAX_REASONING_NODES
            if route_nodes_truncated:
                half = MAX_REASONING_NODES // 2
                route_nodes = route_nodes[:half] + route_nodes[-half:]
            focus_routes.append(
                {
                    "start_node": start,
                    "goal_node": goal,
                    "shortest_route_node_ids": route_nodes,
                    "complete_route_node_count": len(route.node_ids),
                    "route_nodes_truncated": route_nodes_truncated,
                    "route_length_m": round(route.route_length_m, 3),
                    "all_edges_flight_verified": route.all_edges_flight_verified,
                }
            )
        except ValueError:
            focus_routes.append(
                {
                    "start_node": start,
                    "goal_node": goal,
                    "issue_codes": ["MAP_TOPOLOGY_DISCONNECTED"],
                }
            )

    return {
        "schema_version": "dronedream.model-map-context.v1",
        "source_of_truth": "qualified-structured-map-not-rendered-image",
        "visual_input_required": False,
        "graph_sha256": sha256_json(graph),
        "semantic_sha256": catalog.semantic_sha256,
        "coordinate_frame": graph.coordinate_frame,
        "bounds_m": {
            "minimum": {"x": min(x_values), "y": min(y_values), "z": min(z_values)},
            "maximum": {"x": max(x_values), "y": max(y_values), "z": max(z_values)},
        },
        "topology": {
            "complete_graph_node_count": len(graph.nodes),
            "complete_graph_edge_count": len(graph.edges),
            "included_node_count": len(selected),
            "included_edge_count": len(selected_edges),
            "truncated_for_model_context": truncated or len(selected_edges) < len(graph.edges),
            "focus_nodes": focus,
            "focus_routes": focus_routes,
        },
        "named_entities": [
            {
                "entity_id": entity_id,
                "node_id": node_id,
                "position_m": nodes[node_id].position_m.model_dump(mode="json"),
                "semantic": nodes[node_id].semantic,
            }
            for entity_id, node_id in sorted(graph.named_entities.items())
        ],
        "nodes": [
            {
                "node_id": node.node_id,
                "label": node.label,
                "position_m": node.position_m.model_dump(mode="json"),
                "semantic": node.semantic,
            }
            for node in graph.nodes
            if node.node_id in selected
        ],
        "edges": [
            {
                "edge_id": edge.edge_id,
                "from_node": edge.from_node,
                "to_node": edge.to_node,
                "distance_m": round(edge.distance_m, 3),
                "minimum_clearance_m": round(edge.minimum_clearance_m, 3),
                "speed_limit_mps": round(edge.speed_limit_mps, 3),
                "bidirectional": edge.bidirectional,
                "qualification": edge.qualification,
            }
            for edge in selected_edges
        ],
        "semantic_environment": _semantic_summary(semantic_path),
        "catalog_known_limits": catalog.known_limits[:16],
        "model_authority": {
            "may_reason_about": [
                "task-order",
                "route-objective-priority",
                "risk-flags",
                "replan-request",
            ],
            "may_not_author": [
                "collision-clearance-facts",
                "unlisted-coordinates",
                "actuator-commands",
            ],
        },
    }
