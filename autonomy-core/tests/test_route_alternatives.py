from __future__ import annotations

from types import SimpleNamespace

from dronedream_agent_core.contracts import (
    GraphRoute,
    RouteAlternativeCandidate,
    RouteAlternativeSet,
    RouteClearanceReport,
    Vector3,
)
from dronedream_agent_plugins.route_alternative_plugins import plugin_definitions


def _route(*, length: float, verified: bool) -> GraphRoute:
    return GraphRoute(
        start_node="start",
        goal_node="return",
        node_ids=["start", "target", "return"],
        edge_ids=["out", "back"],
        positions_m=[
            Vector3(x=0, y=0, z=1),
            Vector3(x=1, y=0, z=1),
            Vector3(x=0, y=0, z=1),
        ],
        route_length_m=length,
        all_edges_flight_verified=verified,
    )


def _candidate(
    candidate_id: str,
    *,
    length: float,
    clearance: float,
    energy: float,
    verified: bool = True,
    feasible: bool = True,
) -> RouteAlternativeCandidate:
    route = _route(length=length, verified=verified)
    report = RouteClearanceReport(
        accepted=feasible,
        route_sha256="a" * 64,
        semantic_sha256="b" * 64,
        sample_interval_m=0.1,
        sample_count=10,
        primitive_count=1,
        collision_count=0 if feasible else 1,
        minimum_clearance_m=clearance,
        minimum_clearance_point=Vector3(x=0, y=0, z=1),
        minimum_clearance_primitive="wall",
    )
    return RouteAlternativeCandidate(
        alternative_id=candidate_id,
        strategy_tool_id=f"strategy.{candidate_id}",
        route=route,
        clearance=report,
        objectives={
            "distance_m": length,
            "minimum_clearance_m": clearance,
            "energy_proxy": energy,
            "transition_count": 2.0,
            "qualification_penalty": 0.0 if verified else 1.0,
        },
        hard_gates={"continuous_clearance": feasible},
        feasible=feasible,
        issue_codes=[] if feasible else ["CONTINUOUS_CLEARANCE_REJECTED"],
    )


def test_multi_objective_ranker_excludes_infeasible_route_and_explains_choice():
    definition = next(
        value
        for value in plugin_definitions()
        if value.manifest.plugin_id == "planning.multi-objective-ranker"
    )
    assert definition.tool_factory is not None
    tool = definition.tool_factory(
        SimpleNamespace(plugin_configuration=None)  # type: ignore[arg-type]
    )[0]
    values = RouteAlternativeSet(
        contract_id="contract-1",
        candidates=[
            _candidate("short-narrow", length=10, clearance=0.4, energy=11),
            _candidate("wide-safe", length=12, clearance=1.8, energy=12.5),
            _candidate("collision", length=5, clearance=-0.1, energy=5, feasible=False),
        ],
        objective_weights={
            "distance_m": 0.20,
            "minimum_clearance_m": 0.46,
            "energy_proxy": 0.14,
            "transition_count": 0.10,
            "qualification_penalty": 0.10,
        },
    )
    decision = tool.handler(values)
    assert decision.selected_alternative_id == "wide-safe"
    assert "collision" not in decision.ranked_alternative_ids
    assert decision.rejected_alternatives == {"collision": ["CONTINUOUS_CLEARANCE_REJECTED"]}
    assert any("综合得分" in reason for reason in decision.selection_reasons)
