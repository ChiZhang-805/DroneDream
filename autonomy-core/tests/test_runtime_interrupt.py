from datetime import UTC, datetime

import pytest

from dronedream_agent_core.contracts import (
    RuntimeHoldAcknowledgement,
    RuntimeMessageClassification,
    RuntimeUserMessage,
    Vector3,
)
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.runtime_interrupt import (
    RuntimeMessageRejected,
    authorize_runtime_action,
    close_runtime_control_session,
    create_runtime_control_session,
    submit_runtime_message,
)


def _message(text: str) -> RuntimeUserMessage:
    return RuntimeUserMessage(
        message_id="runtime-msg-" + "a" * 32,
        conversation_id="conversation-a",
        mission_id="mission-" + "b" * 32,
        plan_revision_id="plan-" + "c" * 32,
        contract_id="mission-contract-a",
        execution_id="execution-" + "d" * 32,
        text=text,
        submitted_at=datetime.now(UTC),
    )


def _ack(message: RuntimeUserMessage, **gate_updates: bool) -> RuntimeHoldAcknowledgement:
    gates = {
        "telemetry_finite": True,
        "position_error_within_0_50_m": True,
        "speed_within_0_35_mps": True,
        "old_plan_advancement_inhibited": True,
        "semantic_side_effects_inhibited": True,
    }
    gates.update(gate_updates)
    now = datetime.now(UTC)
    return RuntimeHoldAcknowledgement(
        message_sha256=sha256_json(message),
        message_id=message.message_id,
        execution_id=message.execution_id,
        interrupted_phase="TRACK",
        schedule_index=17,
        detected_at=now,
        detection_latency_ms=25,
        stable_at=now,
        stabilization_latency_ms=1100,
        frozen_command_ned_m=Vector3(x=1.0, y=2.0, z=-3.0),
        hold_command_ned_m=Vector3(x=1.1, y=2.1, z=-3.0),
        observed_position_ned_m=Vector3(x=1.1, y=2.1, z=-3.0),
        observed_velocity_ned_mps=Vector3(x=0.0, y=0.0, z=0.0),
        position_error_m=0.0,
        speed_mps=0.0,
        deterministic_gates=gates,
    )


def test_emergency_wording_forces_land_even_if_model_says_informational() -> None:
    message = _message("请立即停止并降落")
    action, gates, _ = authorize_runtime_action(
        message=message,
        acknowledgement=_ack(message),
        classification=RuntimeMessageClassification(
            message_kind="informational",
            requested_action="resume",
            requires_plan_revision=False,
            summary="No change.",
        ),
    )
    assert all(gates.values())
    assert action == "land"


def test_destination_change_can_never_resume_the_old_plan() -> None:
    message = _message("不是原来的外卖点，改到保安亭")
    action, _, _ = authorize_runtime_action(
        message=message,
        acknowledgement=_ack(message),
        classification=RuntimeMessageClassification(
            message_kind="informational",
            requested_action="resume",
            requires_plan_revision=False,
            summary="No change.",
        ),
    )
    assert action == "hold_for_replan"


def test_destination_change_with_safe_hover_wording_cannot_become_persistent_pause() -> None:
    message = _message("不要继续去原来的外卖点了，请先安全悬停，再改道去校园门口的保安亭")
    action, _, _ = authorize_runtime_action(
        message=message,
        acknowledgement=_ack(message),
        classification=RuntimeMessageClassification(
            message_kind="mission_amendment",
            requested_action="pause",
            target_entity="校园门口的保安亭",
            requires_plan_revision=False,
            summary="Change destination after reaching stable hold.",
        ),
    )

    assert action == "hold_for_replan"


def test_failed_hold_gate_forces_landing() -> None:
    message = _message("只是告诉你天气不错")
    action, gates, _ = authorize_runtime_action(
        message=message,
        acknowledgement=_ack(message, telemetry_finite=False),
        classification=RuntimeMessageClassification(
            message_kind="informational",
            requested_action="resume",
            requires_plan_revision=False,
            summary="No task change.",
        ),
    )
    assert not gates["hold_deterministic_gates_passed"]
    assert action == "land"


@pytest.mark.parametrize(
    ("requested_action", "message_kind", "expected"),
    [
        ("redirect", "mission_amendment", "hold_for_replan"),
        ("set_speed", "motion_adjustment", "hold_for_replan"),
        ("pause", "motion_adjustment", "hold"),
        ("resume", "informational", "resume_original"),
        ("return_home", "mission_amendment", "hold_for_replan"),
        ("safe_land", "mission_amendment", "land"),
        ("set_return_point", "mission_amendment", "hold_for_replan"),
        ("set_coverage", "mission_amendment", "hold_for_replan"),
        ("camera_control", "motion_adjustment", "apply_command"),
        ("payload_control", "mission_amendment", "apply_command"),
        ("set_avoidance", "motion_adjustment", "apply_command"),
        ("follow_target", "mission_amendment", "hold_for_replan"),
        ("operator_takeover", "mission_amendment", "hold"),
    ],
)
def test_every_runtime_amendment_first_enters_a_code_authorized_safe_state(
    requested_action: str,
    message_kind: str,
    expected: str,
) -> None:
    message = _message("用户运行时改令")
    action, gates, _ = authorize_runtime_action(
        message=message,
        acknowledgement=_ack(message),
        classification=RuntimeMessageClassification(
            message_kind=message_kind,  # type: ignore[arg-type]
            requested_action=requested_action,  # type: ignore[arg-type]
            target_entity="guard-house",
            requires_plan_revision=requested_action not in {"pause", "resume", "safe_land"},
            summary="A typed runtime amendment.",
            parameters={"maximum_speed_mps": 0.3} if requested_action == "set_speed" else {},
        ),
    )

    assert all(gates.values())
    assert action == expected


def test_runtime_ingress_binds_message_to_exact_session_and_closes(tmp_path) -> None:
    control_dir = tmp_path / "run" / "runtime-control"
    create_runtime_control_session(
        control_dir=control_dir,
        conversation_id="conversation-a",
        mission_id="mission-" + "b" * 32,
        plan_revision_id="plan-" + "c" * 32,
        contract_id="mission-contract-a",
        execution_id="execution-" + "d" * 32,
        prepared_mission_sha256="e" * 64,
    )
    message = submit_runtime_message(control_dir=control_dir, text="请先悬停")
    assert message.execution_id == "execution-" + "d" * 32
    assert (control_dir / "inbox" / f"{message.message_id}.json").is_file()

    close_runtime_control_session(control_dir)
    with pytest.raises(RuntimeMessageRejected, match="RUNTIME_CONTROL_SESSION_CLOSED"):
        submit_runtime_message(control_dir=control_dir, text="第二条消息")
