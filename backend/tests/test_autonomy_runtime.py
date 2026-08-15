from __future__ import annotations

import pytest

from app.autonomy.models import (
    AutonomyCompileRequest,
    RuntimeObservation,
    RuntimeSessionCreateRequest,
    Vector3,
)
from app.autonomy.runtime import AutonomyRuntimeError, RuntimeSessionRegistry
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
