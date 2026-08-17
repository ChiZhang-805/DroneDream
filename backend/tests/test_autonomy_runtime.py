from __future__ import annotations

import pytest

from app.autonomy.models import (
    AutonomyCompileRequest,
    RuntimeObservation,
    RuntimeSessionCreateRequest,
    Vector3,
)
from app.autonomy.runtime import AutonomyRuntimeError, RuntimeSessionRegistry
from app.autonomy.school_map_artifact import TEACHING_OPEN_DOOR_PAIR_CENTER_X
from app.autonomy.service import compile_autonomy_mission


def mission(target: str = "simulation") -> AutonomyCompileRequest:
    return AutonomyCompileRequest.model_validate(
        {
            "edition": "lab" if target != "simulation" else "sim",
            "execution_target": target,
            "natural_language": "Fly through three gates and land at the goal.",
            "scene_id": "forest-gate-inspection",
            "perception_mode": "fusion",
        }
    )


def observation(sequence: int, monotonic_ms: int, **updates: object) -> RuntimeObservation:
    payload: dict[str, object] = {
        "sequence": sequence,
        "monotonic_ms": monotonic_ms,
        "armed": True,
        "landed": False,
        "position_m": Vector3(x=1.0, y=2.0, z=1.5),
        "velocity_mps": Vector3(x=0.4, y=0.0, z=0.0),
        "localization_covariance_m2": 0.04,
        "perception_age_ms": 40,
        "minimum_clearance_m": 0.8,
        "battery_percent": 82.0,
        "link_ok": True,
        "geofence_ok": True,
        "payload_mass_kg": 0.0,
        "mission_progress": 0.2,
    }
    payload.update(updates)
    return RuntimeObservation.model_validate(payload)


def test_runtime_profile_never_grants_hitl_or_hardware_authority() -> None:
    simulation = compile_autonomy_mission(mission())
    hitl = compile_autonomy_mission(mission("hitl"))
    hardware = compile_autonomy_mission(mission("hardware"))

    assert simulation.runtime_profile.mode == "simulation_contract"
    assert simulation.runtime_profile.command_authority is True
    assert hitl.runtime_profile.mode == "hitl_shadow"
    assert hitl.runtime_profile.command_authority is False
    assert hardware.runtime_profile.mode == "hardware_locked"
    assert hardware.runtime_profile.command_authority is False
    assert not any(
        component.actuator_authority for component in hardware.runtime_profile.components
    )


def test_compiler_expands_each_motion_into_perception_plan_qualification_and_evidence() -> None:
    compiled = compile_autonomy_mission(mission())
    graph = compiled.contract.task_graph
    identifiers = {node.task_id for node in graph.nodes}

    assert graph.active_node_ids == ["preflight-pack-identity"]
    assert len(graph.nodes) == 23
    assert len(identifiers) == len(graph.nodes)
    for order, action in ((1, "takeoff"), (2, "pass-gate"), (3, "land")):
        prefix = f"mission-{order:02d}-{action}"
        for stage in ("observe", "plan", "qualify", "execute", "verify"):
            assert f"{prefix}-{stage}" in identifiers
    assert graph.nodes[-2].task_id == "postflight-state"
    assert graph.nodes[-1].depends_on == ["postflight-state"]


def test_pickup_requalifies_the_loaded_vehicle_before_return_planning() -> None:
    coffee = mission().model_copy(
        update={
            "natural_language": "Fly from the office, pick up coffee, and return.",
            "scene_id": "stairwell-coffee-return",
        }
    )
    graph = compile_autonomy_mission(coffee).contract.task_graph
    nodes = {node.task_id: node for node in graph.nodes}
    payload_check = nodes["mission-04-pickup-recompute-envelope"]
    return_observation = nodes["mission-05-return-observe"]

    assert payload_check.risk == "critical"
    assert payload_check.fallback == "land"
    assert "return-energy.margin" in payload_check.completion_evidence
    assert return_observation.depends_on == [payload_check.task_id]


def test_school_map_gate_intent_compiles_gate_steps_and_visual_route() -> None:
    gate_mission = mission().model_copy(
        update={
            "natural_language": "Fly through all three circular gates and land at the goal.",
            "scene_id": "school-campus-v1",
        }
    )
    compiled = compile_autonomy_mission(gate_mission)

    assert [step.action for step in compiled.contract.steps] == [
        "takeoff",
        "pass_gate",
        "land",
    ]
    assert [point.phase for point in compiled.trajectory].count("gate") == 3
    assert compiled.trajectory[0].x == pytest.approx(-24.8)
    assert compiled.trajectory[-1].x == pytest.approx(48.0)
    assert not any(step.action == "pickup" for step in compiled.contract.steps)


def test_school_map_concrete_route_wins_over_generic_return_language() -> None:
    gate_mission = mission().model_copy(
        update={
            "natural_language": "Pass all three circular gates and return to launch.",
            "scene_id": "school-campus-v1",
        }
    )
    stair_mission = mission().model_copy(
        update={
            "natural_language": "Descend the switchback stairs, then return upstairs.",
            "scene_id": "school-campus-v1",
        }
    )

    gate_compiled = compile_autonomy_mission(gate_mission)
    stair_compiled = compile_autonomy_mission(stair_mission)

    assert [step.action for step in gate_compiled.contract.steps] == [
        "takeoff",
        "pass_gate",
        "land",
    ]
    assert [step.action for step in stair_compiled.contract.steps] == [
        "takeoff",
        "traverse_stairs",
        "land",
    ]


def test_school_map_narrow_intent_compiles_switchback_stair_route() -> None:
    narrow_mission = mission().model_copy(
        update={
            "natural_language": "Descend the narrow switchback stairs and land outside.",
            "scene_id": "school-campus-v1",
        }
    )
    compiled = compile_autonomy_mission(narrow_mission)

    assert [step.action for step in compiled.contract.steps] == [
        "takeoff",
        "traverse_stairs",
        "land",
    ]
    assert [point.phase for point in compiled.trajectory].count("stairs") == 7
    assert compiled.trajectory[0].z == pytest.approx(8.15)
    assert max(point.z for point in compiled.trajectory) == pytest.approx(8.3)
    assert compiled.trajectory[-1].z == pytest.approx(1.3)
    assert compiled.trajectory[-2].x == pytest.approx(TEACHING_OPEN_DOOR_PAIR_CENTER_X)
    assert compiled.trajectory[-1].x == pytest.approx(TEACHING_OPEN_DOOR_PAIR_CENTER_X)


def test_legacy_service_corridor_keeps_its_transit_contract() -> None:
    corridor_mission = mission().model_copy(
        update={
            "natural_language": "Follow the narrow service corridor and dock.",
            "scene_id": "service-corridor-dock",
        }
    )

    compiled = compile_autonomy_mission(corridor_mission)

    assert [step.action for step in compiled.contract.steps] == [
        "takeoff",
        "transit",
        "land",
    ]
    assert all(point.phase != "stairs" for point in compiled.trajectory)


def test_runtime_session_is_idempotent_owner_scoped_and_replay_safe() -> None:
    registry = RuntimeSessionRegistry(max_sessions=4)
    request = RuntimeSessionCreateRequest(
        mission=mission(),
        client_request_id="request-runtime-001",
    )
    created = registry.create("user-a", request)
    repeated = registry.create("user-a", request)
    assert repeated.session_id == created.session_id

    active = registry.observe(
        "user-a",
        created.session_id,
        observation(1, 100, mission_progress=0.2),
    )
    assert active.phase == "navigating"
    assert active.decision.action == "continue"
    assert active.observation_count == 1
    assert active.evidence_chain_head != created.evidence_chain_head

    with pytest.raises(AutonomyRuntimeError, match="sequence") as replay:
        registry.observe("user-a", created.session_id, observation(1, 120))
    assert replay.value.code == "AUTONOMY_OBSERVATION_REPLAYED"

    with pytest.raises(AutonomyRuntimeError) as hidden:
        registry.get("user-b", created.session_id)
    assert hidden.value.status_code == 404


def test_safety_supervisor_escalates_and_terminal_sessions_stop() -> None:
    registry = RuntimeSessionRegistry(max_sessions=4)
    created = registry.create(
        "user-a",
        RuntimeSessionCreateRequest(
            mission=mission(),
            client_request_id="request-runtime-002",
        ),
    )
    held = registry.observe(
        "user-a",
        created.session_id,
        observation(1, 100, perception_age_ms=900),
    )
    assert held.phase == "holding"
    assert held.decision.action == "hold"
    assert "safety.perception-stale" in held.decision.codes

    aborted = registry.observe(
        "user-a",
        created.session_id,
        observation(2, 200, emergency_stop=True),
    )
    assert aborted.phase == "aborted"
    assert aborted.terminal is True
    assert aborted.decision.action == "abort"

    with pytest.raises(AutonomyRuntimeError) as terminal:
        registry.observe("user-a", created.session_id, observation(3, 300))
    assert terminal.value.code == "AUTONOMY_RUNTIME_TERMINAL"


def test_thermal_stream_loss_holds_the_mission() -> None:
    registry = RuntimeSessionRegistry(max_sessions=4)
    created = registry.create(
        "user-a",
        RuntimeSessionCreateRequest(
            mission=mission(),
            client_request_id="request-runtime-thermal",
        ),
    )

    held = registry.observe(
        "user-a",
        created.session_id,
        observation(
            1,
            100,
            stream_health=[
                {
                    "stream_id": "thermal-front",
                    "kind": "thermal",
                    "status": "offline",
                    "rate_hz": 0.0,
                    "latency_ms": 0.0,
                    "dropped_percent": 100.0,
                    "source": "onboard",
                }
            ],
        ),
    )

    assert held.phase == "holding"
    assert held.decision.action == "hold"
    assert "safety.perception-stream-offline" in held.decision.codes


def test_non_simulation_session_creation_remains_denied() -> None:
    registry = RuntimeSessionRegistry()
    with pytest.raises(AutonomyRuntimeError) as denied:
        registry.create(
            "user-a",
            RuntimeSessionCreateRequest(
                mission=mission("hardware"),
                client_request_id="request-runtime-003",
            ),
        )
    assert denied.value.code == "AUTONOMY_RUNTIME_NOT_AUTHORIZED"
    assert denied.value.status_code == 403


def test_dynamic_person_inserts_a_bounded_recovery_branch() -> None:
    registry = RuntimeSessionRegistry(max_sessions=4)
    created = registry.create(
        "user-a",
        RuntimeSessionCreateRequest(
            mission=mission(),
            client_request_id="request-runtime-person",
        ),
    )
    held = registry.observe(
        "user-a",
        created.session_id,
        observation(
            1,
            100,
            perceived_entities=[
                {
                    "track_id": "person-17",
                    "kind": "person",
                    "position_m": {"x": 1.5, "y": 2.0, "z": 1.5},
                    "velocity_mps": {"x": 0.2, "y": 0.0, "z": 0.0},
                    "confidence": 0.96,
                    "age_ms": 40,
                    "safety_radius_m": 0.8,
                    "source_stream": "front-depth",
                }
            ],
            stream_health=[
                {
                    "stream_id": "front-depth",
                    "kind": "depth",
                    "status": "healthy",
                    "rate_hz": 30.0,
                    "latency_ms": 45.0,
                    "dropped_percent": 0.1,
                    "source": "onboard",
                }
            ],
        ),
    )

    assert held.phase == "holding"
    assert "safety.person-envelope" in held.decision.codes
    assert held.perceived_entities[0].track_id == "person-17"
    runtime_nodes = [node for node in held.task_graph.nodes if node.inserted_by == "runtime"]
    assert {node.executor for node in runtime_nodes} == {
        "mission_executive",
        "local_planner",
    }
    assert any(node.status == "active" for node in runtime_nodes)
    assert held.decision_events[-1].entity_ids == ["person-17"]

    repaired = registry.observe(
        "user-a",
        created.session_id,
        observation(2, 200, mission_progress=0.25, local_replan_active=True),
    )
    assert repaired.phase == "replanning"
    assert repaired.decision.action == "continue"
    assert all(
        node.status == "completed"
        for node in repaired.task_graph.nodes
        if node.inserted_by == "runtime"
    )


def test_runtime_graph_and_decision_log_remain_bounded_and_monotonic() -> None:
    registry = RuntimeSessionRegistry(max_sessions=4)
    created = registry.create(
        "user-a",
        RuntimeSessionCreateRequest(
            mission=mission(),
            client_request_id="request-runtime-bounds",
        ),
    )
    entities = [
        {
            "track_id": f"person-{index:03d}",
            "kind": "person",
            "position_m": {"x": 20.0 + index, "y": 2.0, "z": 1.5},
            "velocity_mps": {"x": 0.0, "y": 0.0, "z": 0.0},
            "confidence": 0.9,
            "age_ms": 20,
            "safety_radius_m": 0.8,
            "source_stream": "front-depth",
        }
        for index in range(80)
    ]
    bounded = registry.observe(
        "user-a",
        created.session_id,
        observation(1, 100, perceived_entities=entities),
    )
    assert len(bounded.task_graph.nodes) <= 128

    current = bounded
    for sequence in range(2, 108):
        current = registry.observe(
            "user-a",
            created.session_id,
            observation(sequence, sequence * 100, perceived_entities=[]),
        )
    revisions = [event.revision for event in current.decision_events]
    assert len(revisions) == 100
    assert revisions == sorted(set(revisions))
    assert revisions[-1] == 108
