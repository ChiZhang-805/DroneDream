from __future__ import annotations

import pytest

from dronedream_agent_core.contracts import (
    IntentArtifact,
    MapAsset,
    MissionContract,
    MissionRequest,
    SemanticPlan,
    TaskGraph,
)
from dronedream_agent_core.orchestrator import (
    MissionPreparationBlocked,
    _explicit_constraint_hints,
    _missing_explicit_constraints,
    _recommended_plugin_tools,
    _validate_semantic_plan,
    _validate_task_graph,
)


def _map() -> MapAsset:
    return MapAsset.model_validate(
        {
            "asset_id": "school-map",
            "name": "School Map",
            "nodes": [
                {
                    "node_id": "office",
                    "label": "Office",
                    "position_m": {"x": 0, "y": 0, "z": 3},
                    "semantic": "launch",
                },
                {
                    "node_id": "pickup",
                    "label": "Pickup",
                    "position_m": {"x": 10, "y": 0, "z": 1},
                    "semantic": "pickup",
                },
                {
                    "node_id": "stale-gate",
                    "label": "Old destination",
                    "position_m": {"x": 5, "y": 5, "z": 1},
                    "semantic": "outdoor",
                },
            ],
            "edges": [
                {
                    "edge_id": "office-pickup",
                    "from_node": "office",
                    "to_node": "pickup",
                    "distance_m": 10,
                    "minimum_clearance_m": 1,
                    "speed_limit_mps": 1,
                },
                {
                    "edge_id": "office-gate",
                    "from_node": "office",
                    "to_node": "stale-gate",
                    "distance_m": 7,
                    "minimum_clearance_m": 1,
                    "speed_limit_mps": 1,
                },
            ],
            "named_entities": {"office": "office", "pickup": "pickup"},
        }
    )


def _contract() -> MissionContract:
    digest = "a" * 64
    return MissionContract(
        contract_id="mission-0123456789abcdef01234567",
        conversation_id="thread-1",
        goal="retrieve parcel and return",
        start_node="office",
        target_node="pickup",
        return_node="office",
        payload_action="pickup",
        map_asset_id="school-map",
        map_sha256=digest,
        map_semantic_sha256=digest,
        vehicle_asset_id="my-drone",
        vehicle_sha256=digest,
        constraints=[],
        immutable_safety_rules=["model has no actuator authority"],
    )


def _task_graph(*, include_stale_gate: bool) -> TaskGraph:
    nodes = [
        {
            "task_id": "takeoff",
            "action": "takeoff",
            "target_node": "office",
            "success_evidence": ["airborne"],
            "fallback": "abort",
        }
    ]
    if include_stale_gate:
        nodes.append(
            {
                "task_id": "old-destination",
                "action": "traverse",
                "target_node": "stale-gate",
                "depends_on": ["takeoff"],
                "success_evidence": ["arrived"],
                "fallback": "return",
            }
        )
    dependency = "old-destination" if include_stale_gate else "takeoff"
    nodes.extend(
        [
            {
                "task_id": "go-pickup",
                "action": "navigate",
                "target_node": "pickup",
                "depends_on": [dependency],
                "success_evidence": ["arrived"],
                "fallback": "return",
            },
            {
                "task_id": "pickup",
                "action": "pickup",
                "target_node": "pickup",
                "depends_on": ["go-pickup"],
                "success_evidence": ["payload verified"],
                "fallback": "return",
            },
            {
                "task_id": "return",
                "action": "return",
                "target_node": "office",
                "depends_on": ["pickup"],
                "success_evidence": ["office reached"],
                "fallback": "land",
            },
            {
                "task_id": "land",
                "action": "land",
                "target_node": "office",
                "depends_on": ["return"],
                "success_evidence": ["landed"],
                "fallback": "abort",
            },
        ]
    )
    return TaskGraph(nodes=nodes)


def test_task_graph_rejects_destination_left_over_from_superseded_plan() -> None:
    with pytest.raises(MissionPreparationBlocked, match="TASK_GRAPH_UNAUTHORIZED_MOVEMENT_TARGET"):
        _validate_task_graph(_task_graph(include_stale_gate=True), _contract(), _map())


def test_task_graph_accepts_only_contract_movement_targets() -> None:
    _validate_task_graph(_task_graph(include_stale_gate=False), _contract(), _map())


def test_semantic_plan_rejects_stale_or_model_selected_detour() -> None:
    plan = SemanticPlan(
        ordered_targets=["stale-gate", "pickup", "office"],
        rationale_summary="Old destination then current mission.",
    )
    with pytest.raises(MissionPreparationBlocked, match="SEMANTIC_PLAN_UNAUTHORIZED_TARGET"):
        _validate_semantic_plan(plan, _contract(), _map())


def test_semantic_plan_accepts_contract_target_and_return_only() -> None:
    plan = SemanticPlan(
        ordered_targets=["pickup", "office"],
        rationale_summary="Current target and contract return.",
    )
    _validate_semantic_plan(plan, _contract(), _map())


def test_explicit_safety_priority_must_be_structured_not_only_goal_prose() -> None:
    request = MissionRequest(
        conversation_id="thread-1",
        message="恢复去外卖点取件并返回办公室，同时保持安全优先。",
    )
    hints = _explicit_constraint_hints(request)
    intent = IntentArtifact(
        goal="取件并返回，保持安全优先",
        start_entity="office",
        target_entity="pickup",
        return_entity="office",
        payload_action="pickup",
        constraints=[],
    )

    assert hints == ["safety_priority"]
    assert _missing_explicit_constraints(intent, hints) == ["safety_priority"]

    intent.constraints = ["safety_priority"]
    assert _missing_explicit_constraints(intent, hints) == []


def test_manifest_conditions_recommend_plugins_without_hardcoded_plugin_ids() -> None:
    catalog = [
        {
            "tool_id": "example.payload-audit",
            "routing_metadata": {"recommended_when": {"payload_action_in": ["pickup"]}},
        },
        {
            "tool_id": "example.unrelated",
            "routing_metadata": {"recommended_when": {"payload_action_in": ["none"]}},
        },
    ]

    assert _recommended_plugin_tools(catalog, _contract()) == ["example.payload-audit"]
