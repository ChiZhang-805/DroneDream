"""Core-owned validation for bounded runtime commands that do not replace a track."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .contracts import (
    RuntimeAuthorizedCommand,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeUserMessage,
)
from .hashing import sha256_json


class RuntimeCommandError(RuntimeError):
    """A runtime command failed deterministic construction or adoption."""


_GAZEBO_TOPIC = re.compile(r"^/[A-Za-z0-9_./-]{1,240}$")


def build_runtime_command(
    *,
    message: RuntimeUserMessage,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
) -> RuntimeAuthorizedCommand:
    action = decision.classification.requested_action
    if decision.authorized_action != "apply_command" or action not in {
        "camera_control",
        "payload_control",
        "set_avoidance",
    }:
        raise RuntimeCommandError("RUNTIME_COMMAND_NOT_AUTHORIZED")
    parameters = dict(
        decision.amendment_directive.parameters
        if decision.amendment_directive is not None
        else decision.classification.parameters
    )
    parameter_gate = False
    if action == "camera_control":
        parameter_gate = (
            parameters.get("command")
            in {
                "take_photo",
                "start_video",
                "stop_video",
            }
            and isinstance(parameters.get("component_id"), int)
            and 1 <= int(parameters["component_id"]) <= 255
        )
    elif action == "payload_control":
        protocol = parameters.get("protocol")
        if protocol == "gazebo-transport":
            parameter_gate = (
                parameters.get("operation") in {"attach", "detach"}
                and isinstance(parameters.get("topic"), str)
                and _GAZEBO_TOPIC.fullmatch(str(parameters["topic"])) is not None
                and isinstance(parameters.get("output_topic"), str)
                and _GAZEBO_TOPIC.fullmatch(str(parameters["output_topic"])) is not None
            )
        elif protocol == "mavsdk-actuator":
            parameter_gate = (
                isinstance(parameters.get("actuator_index"), int)
                and 1 <= int(parameters["actuator_index"]) <= 16
                and isinstance(parameters.get("actuator_value"), int | float)
                and -1.0 <= float(parameters["actuator_value"]) <= 1.0
            )
    elif action == "set_avoidance":
        parameter_gate = isinstance(parameters.get("enabled"), bool)
    gates = {
        "message_matches_decision": decision.message_sha256 == sha256_json(message),
        "hold_matches_decision": decision.hold_ack_sha256 == sha256_json(acknowledgement),
        "stable_hold_gates_passed": all(acknowledgement.deterministic_gates.values()),
        "semantic_side_effects_inhibited": acknowledgement.side_effects_inhibited,
        "command_parameters_valid": parameter_gate,
        "core_authorized_command": decision.authorized_action == "apply_command",
    }
    if not all(gates.values()):
        failed = ",".join(name for name, accepted in gates.items() if not accepted)
        raise RuntimeCommandError(f"RUNTIME_COMMAND_GATE_FAILED:{failed}")
    return RuntimeAuthorizedCommand(
        message_id=message.message_id,
        execution_id=message.execution_id,
        action=action,
        parameters=parameters,
        message_sha256=sha256_json(message),
        hold_ack_sha256=sha256_json(acknowledgement),
        decision_sha256=sha256_json(decision),
        deterministic_gates=gates,
        plugin_hook_receipts=decision.plugin_hook_receipts,
        generated_at=datetime.now(UTC),
    )
