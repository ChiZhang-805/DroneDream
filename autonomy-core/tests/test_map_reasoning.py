import json

from dronedream_agent_core.contracts import (
    CatalogEntity,
    MapAsset,
    MapCatalog,
    MapEdge,
    MapNode,
    Vector3,
)
from dronedream_agent_core.map_reasoning import build_map_reasoning_context


def test_text_model_receives_hash_bound_topology_and_environment_limits(tmp_path) -> None:
    graph = MapAsset(
        asset_id="school-map",
        name="School map",
        nodes=[
            MapNode(
                node_id="office",
                label="Office",
                position_m=Vector3(x=0, y=0, z=1.5),
                semantic="office",
            ),
            MapNode(
                node_id="hall",
                label="Hall",
                position_m=Vector3(x=3, y=0, z=1.5),
                semantic="corridor",
            ),
            MapNode(
                node_id="lab",
                label="Lab",
                position_m=Vector3(x=6, y=0, z=1.5),
                semantic="pickup",
            ),
        ],
        edges=[
            MapEdge(
                edge_id="office-hall",
                from_node="office",
                to_node="hall",
                distance_m=3,
                minimum_clearance_m=1.2,
                speed_limit_mps=1,
                qualification="flight-verified",
                evidence_sha256="1" * 64,
            ),
            MapEdge(
                edge_id="hall-lab",
                from_node="hall",
                to_node="lab",
                distance_m=3,
                minimum_clearance_m=0.8,
                speed_limit_mps=0.7,
            ),
        ],
        named_entities={"office": "office", "lab": "lab"},
    )
    catalog = MapCatalog(
        scene_id="school-map",
        semantic_sha256="2" * 64,
        entities=[
            CatalogEntity(
                entity_id="office",
                aliases=["office"],
                position_m=Vector3(x=0, y=0, z=1.5),
                semantic="office",
                source_pointer="/office",
            )
        ],
        topology_available=True,
        known_limits=["dynamic people are supplied by the runtime"],
    )
    semantic_path = tmp_path / "semantic.json"
    semantic_path.write_text(
        json.dumps(
            {
                "coordinate_frame": "ENU",
                "collision_primitives": [{"name": "wall"}],
                "known_export_limits": [
                    "Occupancy and ESDF must be generated from collision geometry"
                ],
                "dynamic_people": {
                    "runtime_spawn_required": True,
                    "static_collision_present": False,
                },
            }
        ),
        encoding="utf-8",
    )

    context = build_map_reasoning_context(
        graph,
        catalog,
        semantic_path,
        focus_nodes=["office", "lab", "office"],
    )

    assert context["source_of_truth"] == "qualified-structured-map-not-rendered-image"
    assert context["visual_input_required"] is False
    assert context["graph_sha256"]
    assert context["topology"]["focus_routes"][0]["shortest_route_node_ids"] == [
        "office",
        "hall",
        "lab",
    ]
    assert context["edges"][1]["qualification"] == "geometry-derived"
    environment = context["semantic_environment"]
    assert environment["occupancy_esdf_ready"] is False
    assert environment["dynamic_obstacles_runtime_required"] is True
    assert environment["dynamic_obstacles_in_static_collision"] is False
    assert "actuator-commands" in context["model_authority"]["may_not_author"]
