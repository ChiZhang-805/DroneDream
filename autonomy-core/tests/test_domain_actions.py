from __future__ import annotations

import pytest

from dronedream_agent_core.contracts import MapAsset, MissionContract, TaskGraph
from dronedream_agent_core.domain_actions import (
    DomainActionError,
    action_by_id,
    action_ids,
    merge_action_packs,
    movement_action_ids,
)
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.orchestrator import MissionPreparationBlocked, _validate_task_graph
from dronedream_agent_core.plugin_api import build_discovered_extension_registry


def _catalog():
    registry = build_discovered_extension_registry()
    outputs, receipts = registry.invoke_multiple("mission.action-packs", "declare_actions")
    assert outputs
    assert all(receipt.outcome == "accepted" for receipt in receipts)
    return merge_action_packs(outputs)


def _map() -> MapAsset:
    return MapAsset.model_validate(
        {
            "asset_id": "school-map",
            "name": "School Map",
            "nodes": [
                {
                    "node_id": "office",
                    "label": "Office",
                    "position_m": {"x": 0, "y": 0, "z": 1},
                    "semantic": "launch",
                },
                {
                    "node_id": "pickup",
                    "label": "Pickup",
                    "position_m": {"x": 2, "y": 0, "z": 1},
                    "semantic": "pickup",
                },
            ],
            "edges": [
                {
                    "edge_id": "office-pickup",
                    "from_node": "office",
                    "to_node": "pickup",
                    "distance_m": 2,
                    "minimum_clearance_m": 1,
                    "speed_limit_mps": 1,
                }
            ],
            "named_entities": {"office": "office", "pickup": "pickup"},
        }
    )


def _contract(catalog) -> MissionContract:
    return MissionContract(
        contract_id="mission-0123456789abcdef01234567",
        conversation_id="thread-1",
        goal="retrieve parcel",
        start_node="office",
        target_node="pickup",
        return_node="office",
        payload_action="pickup",
        domain_ids=catalog.domain_ids,
        authorized_actions=sorted(action_ids(catalog)),
        action_catalog_sha256=sha256_json(catalog),
        map_asset_id="school-map",
        map_sha256="a" * 64,
        map_semantic_sha256="b" * 64,
        vehicle_asset_id="drone",
        vehicle_sha256="c" * 64,
        constraints=[],
        immutable_safety_rules=["model has no actuator authority"],
    )


def test_first_party_action_packs_merge_without_conflict() -> None:
    catalog = _catalog()

    assert {"core.flight", "delivery.custody", "inspection.infrastructure"}.issubset(
        set(catalog.domain_ids)
    )
    assert {"takeoff", "land", "pickup", "inspection.capture-thermal"}.issubset(action_ids(catalog))
    assert "survey.grid-capture" in movement_action_ids(catalog)
    assert action_by_id(catalog, "delivery.release-payload").authority == "actuate"


def test_action_pack_conflict_is_rejected() -> None:
    base = {
        "schema_version": "dronedream.action-definition.v1",
        "action_id": "takeoff",
        "domain_id": "core.flight",
        "label": "Takeoff",
        "description": "Takeoff action",
        "movement": False,
        "payload": False,
        "flight_boundary": "takeoff",
        "input_schema": {},
        "required_success_evidence": ["airborne"],
        "allowed_fallbacks": ["land"],
        "simulator_executor": "sim.flight.takeoff",
        "runtime_executor": None,
        "authority": "plan",
    }
    with pytest.raises(DomainActionError, match="DOMAIN_ACTION_CONFLICT"):
        merge_action_packs(
            [
                {"domain_id": "core.flight", "actions": [base]},
                {
                    "domain_id": "core.flight",
                    "actions": [{**base, "description": "Different bytes"}],
                },
            ]
        )


def test_task_graph_enforces_registered_action_fallback_and_evidence() -> None:
    catalog = _catalog()
    contract = _contract(catalog)
    valid = TaskGraph.model_validate(
        {
            "nodes": [
                {
                    "task_id": "takeoff",
                    "action": "takeoff",
                    "target_node": "office",
                    "success_evidence": ["airborne", "stable hover"],
                    "fallback": "land",
                },
                {
                    "task_id": "navigate",
                    "action": "navigate",
                    "target_node": "pickup",
                    "depends_on": ["takeoff"],
                    "success_evidence": ["target reached", "pose stable"],
                    "fallback": "hold",
                },
                {
                    "task_id": "pickup",
                    "action": "pickup",
                    "target_node": "pickup",
                    "depends_on": ["navigate"],
                    "success_evidence": [
                        "recipient or parcel verified",
                        "payload attached",
                    ],
                    "fallback": "return",
                },
                {
                    "task_id": "return",
                    "action": "return",
                    "target_node": "office",
                    "depends_on": ["pickup"],
                    "success_evidence": ["return node reached"],
                    "fallback": "land",
                },
                {
                    "task_id": "land",
                    "action": "land",
                    "target_node": "office",
                    "depends_on": ["return"],
                    "success_evidence": ["landed", "motors safe"],
                    "fallback": "hold",
                },
            ]
        }
    )
    _validate_task_graph(valid, contract, _map(), catalog)

    invalid = valid.model_copy(deep=True)
    invalid.nodes[2].fallback = "continue"
    with pytest.raises(MissionPreparationBlocked, match="TASK_GRAPH_ACTION_FALLBACK_UNAUTHORIZED"):
        _validate_task_graph(invalid, contract, _map(), catalog)
