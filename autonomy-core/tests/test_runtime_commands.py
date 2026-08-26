import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dronedream_agent_core.contracts import (
    ModelCallRecord,
    RuntimeAmendmentDirective,
    RuntimeCommandAdoption,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeMessageClassification,
    RuntimeUserMessage,
    Vector3,
)
from dronedream_agent_core.hashing import sha256_json
from dronedream_agent_core.runtime_commands import build_runtime_command


def _load_executor() -> Any:
    path = Path(__file__).parents[1] / "scripts" / "px4_checkpoint_executor.py"
    spec = importlib.util.spec_from_file_location("test_px4_checkpoint_executor", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _message() -> RuntimeUserMessage:
    return RuntimeUserMessage(
        message_id="runtime-msg-" + "a" * 32,
        conversation_id="conversation-a",
        mission_id="mission-" + "b" * 32,
        plan_revision_id="plan-" + "c" * 32,
        contract_id="mission-contract-a",
        execution_id="execution-" + "d" * 32,
        text="运行时操作",
        submitted_at=datetime.now(UTC),
    )


def _ack(message: RuntimeUserMessage) -> RuntimeHoldAcknowledgement:
    now = datetime.now(UTC)
    return RuntimeHoldAcknowledgement(
        message_sha256=sha256_json(message),
        message_id=message.message_id,
        execution_id=message.execution_id,
        interrupted_phase="TRACK",
        schedule_index=7,
        detected_at=now,
        detection_latency_ms=20,
        stable_at=now,
        stabilization_latency_ms=900,
        frozen_command_ned_m=Vector3(x=1, y=2, z=-3),
        hold_command_ned_m=Vector3(x=1, y=2, z=-3),
        observed_position_ned_m=Vector3(x=1, y=2, z=-3),
        observed_velocity_ned_mps=Vector3(x=0, y=0, z=0),
        position_error_m=0,
        speed_mps=0,
        deterministic_gates={
            "telemetry_finite": True,
            "position_stable": True,
            "velocity_stable": True,
            "old_plan_inhibited": True,
        },
    )


def _decision(
    message: RuntimeUserMessage,
    acknowledgement: RuntimeHoldAcknowledgement,
    *,
    action: str,
    parameters: dict[str, Any],
) -> RuntimeInterruptionDecision:
    return RuntimeInterruptionDecision(
        message_sha256=sha256_json(message),
        hold_ack_sha256=sha256_json(acknowledgement),
        classification=RuntimeMessageClassification(
            message_kind="motion_adjustment",
            requested_action=action,  # type: ignore[arg-type]
            requires_plan_revision=False,
            summary="Execute a bounded command.",
            parameters=parameters,
        ),
        model_call=ModelCallRecord(
            call_id="model-" + "e" * 24,
            role="runtime_message_classifier",
            attempt=1,
            input_sha256="1" * 64,
            output_sha256="2" * 64,
            output_schema="RuntimeMessageClassification",
            provider="test",
            model="test",
            latency_ms=1,
            created_at=datetime.now(UTC),
        ),
        authorized_action="apply_command",
        authorization_gates={"stable_hold": True},
        decision_reason="Stable hold permits the command.",
        amendment_directive=RuntimeAmendmentDirective(
            action=action,
            parameters=parameters,
            requires_plan_revision=False,
        ),
    )


class _Base:
    @staticmethod
    def _raise_if_external_abort_requested(_: Path) -> None:
        return None


class _Client:
    def __init__(self) -> None:
        self.hold_count = 0

    async def set_position_ned(self, _: Any) -> None:
        self.hold_count += 1

    async def execute_camera_command(self, parameters: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"confirmed": True, "transport": "test-camera", **parameters}

    async def execute_payload_command(self, parameters: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"confirmed": True, "transport": "test-payload", **parameters}

    async def execute_avoidance_command(self, enabled: bool) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"confirmed": True, "transport": "test-param", "enabled": enabled}


class _UnconfirmedClient(_Client):
    async def execute_camera_command(self, parameters: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"confirmed": False, "transport": "test-camera", **parameters}


@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        ("camera_control", {"command": "take_photo", "component_id": 100}),
        (
            "payload_control",
            {
                "operation": "detach",
                "protocol": "gazebo-transport",
                "topic": "/model/my_drone/payload/detach",
                "output_topic": "/model/my_drone/payload/state",
            },
        ),
        ("set_avoidance", {"enabled": True}),
    ],
)
def test_runtime_command_is_hash_bound_executed_and_adopted(
    tmp_path: Path, action: str, parameters: dict[str, Any]
) -> None:
    executor = _load_executor()
    message = _message()
    acknowledgement = _ack(message)
    decision = _decision(message, acknowledgement, action=action, parameters=parameters)
    command = build_runtime_command(
        message=message,
        acknowledgement=acknowledgement,
        decision=decision,
    )
    control_dir = tmp_path / "runtime-control"
    command_path = control_dir / "commands" / f"{message.message_id}.json"
    command_path.parent.mkdir(parents=True)
    command_path.write_text(command.model_dump_json(indent=2), encoding="utf-8")
    interruption = executor.RuntimeInterruptDetected(
        message,
        control_dir / "claimed" / f"{message.message_id}.json",
        datetime.now(UTC),
    )
    client = _Client()
    hold = SimpleNamespace(north_m=1.0, east_m=2.0, down_m=-3.0)

    loaded = asyncio.run(
        executor._wait_runtime_command(
            base=_Base,
            client=client,
            hold_setpoint=hold,
            interruption=interruption,
            acknowledgement=acknowledgement,
            decision=decision,
            control_dir=control_dir,
            abort_file=tmp_path / "abort.json",
            rate_hz=20.0,
            timeout_seconds=1.0,
        )
    )
    outcome = asyncio.run(
        executor._execute_runtime_command(
            base=_Base,
            client=client,
            hold_setpoint=hold,
            interruption=interruption,
            command=loaded,
            control_dir=control_dir,
            abort_file=tmp_path / "abort.json",
            rate_hz=20.0,
            timeout_seconds=1.0,
        )
    )

    assert outcome == "resume_original"
    assert client.hold_count >= 2
    adoption = RuntimeCommandAdoption.model_validate_json(
        (control_dir / "adoptions" / f"{message.message_id}.json").read_text(encoding="utf-8")
    )
    assert adoption.command_sha256 == sha256_json(command)
    assert adoption.observed_result["confirmed"] is True
    assert (control_dir / "command-results" / f"{message.message_id}.json").is_file()


def test_invalid_runtime_command_never_reaches_executor() -> None:
    message = _message()
    acknowledgement = _ack(message)
    decision = _decision(
        message,
        acknowledgement,
        action="camera_control",
        parameters={"command": "delete_all", "component_id": 100},
    )
    with pytest.raises(Exception, match="command_parameters_valid"):
        build_runtime_command(
            message=message,
            acknowledgement=acknowledgement,
            decision=decision,
        )


def test_unconfirmed_device_readback_fails_closed_and_writes_evidence(tmp_path: Path) -> None:
    executor = _load_executor()
    message = _message()
    acknowledgement = _ack(message)
    decision = _decision(
        message,
        acknowledgement,
        action="camera_control",
        parameters={"command": "take_photo", "component_id": 100},
    )
    command = build_runtime_command(
        message=message,
        acknowledgement=acknowledgement,
        decision=decision,
    )
    control_dir = tmp_path / "runtime-control"
    interruption = executor.RuntimeInterruptDetected(
        message,
        control_dir / "claimed" / f"{message.message_id}.json",
        datetime.now(UTC),
    )

    with pytest.raises(executor.UserDirectedLanding, match="positive device readback"):
        asyncio.run(
            executor._execute_runtime_command(
                base=_Base,
                client=_UnconfirmedClient(),
                hold_setpoint=SimpleNamespace(north_m=1.0, east_m=2.0, down_m=-3.0),
                interruption=interruption,
                command=command,
                control_dir=control_dir,
                abort_file=tmp_path / "abort.json",
                rate_hz=20.0,
                timeout_seconds=1.0,
            )
        )

    failure = json.loads(
        (control_dir / "command-failures" / f"{message.message_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert failure["observed_result"]["confirmed"] is False
