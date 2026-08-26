import pytest

from dronedream_agent_core.contracts import (
    MapAsset,
    MapEdge,
    MapNode,
    RouteQuery,
    Vector3,
)
from dronedream_agent_core.navigation import shortest_route


def _graph() -> MapAsset:
    return MapAsset(
        asset_id="test-graph",
        name="routing contract fixture",
        nodes=[
            MapNode(node_id="a", label="A", position_m=Vector3(x=0, y=0, z=1), semantic="launch"),
            MapNode(node_id="b", label="B", position_m=Vector3(x=1, y=0, z=1), semantic="outdoor"),
            MapNode(node_id="c", label="C", position_m=Vector3(x=2, y=0, z=1), semantic="pickup"),
        ],
        edges=[
            MapEdge(
                edge_id="ab",
                from_node="a",
                to_node="b",
                distance_m=1,
                minimum_clearance_m=1,
                speed_limit_mps=1,
                qualification="flight-verified",
                evidence_sha256="1" * 64,
            ),
            MapEdge(
                edge_id="bc",
                from_node="b",
                to_node="c",
                distance_m=1,
                minimum_clearance_m=1,
                speed_limit_mps=1,
                qualification="geometry-derived",
            ),
        ],
        named_entities={"start": "a", "goal": "c"},
    )


def test_route_reports_mixed_qualification():
    route = shortest_route(_graph(), RouteQuery(start_node="a", goal_node="c"))
    assert route.node_ids == ["a", "b", "c"]
    assert route.all_edges_flight_verified is False


def test_verified_only_policy_fails_closed():
    with pytest.raises(ValueError, match="qualification"):
        shortest_route(
            _graph(),
            RouteQuery(start_node="a", goal_node="c", require_flight_verified_edges=True),
        )
