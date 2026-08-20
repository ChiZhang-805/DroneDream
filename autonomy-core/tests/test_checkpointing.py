from dronedream_agent_core.checkpointing import checkpoint_continue_authorized
from dronedream_agent_core.contracts import (
    RuntimeAssessment,
    RuntimeCheckpoint,
    RuntimeCheckpointRequest,
    Vector3,
)


def _request(**gate_updates: bool) -> RuntimeCheckpointRequest:
    gates = {
        "position_within_tolerance": True,
        "speed_within_hold_limit": True,
        "battery_above_reserve": True,
        "no_collision": True,
    }
    gates.update(gate_updates)
    return RuntimeCheckpointRequest(
        contract_id="mission-test",
        checkpoint=RuntimeCheckpoint(
            checkpoint_id="checkpoint-001",
            segment_id="segment-001",
            task_id="task-001",
            track_point_index=1,
            target_node="node-b",
        ),
        observed_position_ned_m=Vector3(x=1.0, y=2.0, z=-3.0),
        observed_velocity_ned_mps=Vector3(x=0.0, y=0.0, z=0.0),
        commanded_position_ned_m=Vector3(x=1.0, y=2.0, z=-3.0),
        position_error_m=0.0,
        speed_mps=0.0,
        battery_percent=70.0,
        deterministic_gates=gates,
    )


def test_model_accept_requires_every_code_gate() -> None:
    assert not checkpoint_continue_authorized(
        request=_request(no_collision=False),
        assessment=RuntimeAssessment(action="accept"),
        binding_gates={"checkpoint_binding": True},
    )


def test_code_accepts_only_bound_safe_model_accept() -> None:
    request = _request()
    binding = {"checkpoint_binding": True, "track_point_binding": True}
    assert checkpoint_continue_authorized(
        request=request,
        assessment=RuntimeAssessment(action="accept"),
        binding_gates=binding,
    )
    assert not checkpoint_continue_authorized(
        request=request,
        assessment=RuntimeAssessment(action="hold"),
        binding_gates=binding,
    )
