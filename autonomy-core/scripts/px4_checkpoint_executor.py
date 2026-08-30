#!/usr/bin/env python3
"""Real MAVSDK Offboard executor with model-reviewed segment hover checkpoints."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import math
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from dronedream_agent_core.collision import validate_route_clearance
from dronedream_agent_core.contracts import (
    GraphRoute,
    Px4CoordinateContract,
    Px4Track,
    RuntimeAuthorizedCommand,
    RuntimeCheckpointContract,
    RuntimeCheckpointDecision,
    RuntimeCheckpointRequest,
    RuntimeCommandAdoption,
    RuntimeControlSession,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeLocalSafetyCommand,
    RuntimeLocalSafetyObservation,
    RuntimeOperatorControlCommand,
    RuntimeOperatorTakeoverAdoption,
    RuntimeOperatorTakeoverGrant,
    RuntimeReplacementTrack,
    RuntimeUserMessage,
    Vector3,
    VehicleAsset,
)
from dronedream_agent_core.hashing import sha256_json


def _load_base(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("dronedream_proven_px4_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load proven PX4 executor dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if hasattr(payload, "model_dump_json"):
        rendered = payload.model_dump_json(indent=2)
    else:
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    temporary.write_text(rendered + "\n", encoding="utf-8")
    temporary.replace(path)


class UserDirectedLanding(RuntimeError):
    """A user interruption intentionally superseded the prepared mission."""


class RuntimeInterruptDetected(RuntimeError):
    def __init__(
        self, message: RuntimeUserMessage, claimed_path: Path, detected_at: datetime
    ) -> None:
        super().__init__(message.message_id)
        self.message = message
        self.claimed_path = claimed_path
        self.detected_at = detected_at


class RuntimeTrackReplacement(RuntimeError):
    def __init__(
        self,
        *,
        message_id: str,
        schedule: list[Any],
        track_sha256: str,
        replacement_sequence: int,
        amendment_action: str,
        amendment_parameters: dict[str, Any],
        coordinate_contract: Px4CoordinateContract,
    ) -> None:
        super().__init__(message_id)
        self.message_id = message_id
        self.schedule = schedule
        self.track_sha256 = track_sha256
        self.replacement_sequence = replacement_sequence
        self.amendment_action = amendment_action
        self.amendment_parameters = amendment_parameters
        self.coordinate_contract = coordinate_contract


def _compile_replacement_schedule(
    *,
    base: ModuleType,
    replacement: RuntimeReplacementTrack,
    params: Any,
    rate_hz: float,
) -> list[Any]:
    points = [
        base.TrackPoint(point.x, point.y, point.z, point.speed_limit_mps)
        for point in replacement.track.points
    ]
    if len(points) < 2:
        raise RuntimeError("runtime replacement track contains fewer than two points")
    schedule = [base.enu_point_to_ned_setpoint(points[0], yaw_deg=0.0)]
    hold_samples = int(math.ceil(rate_hz * replacement.track.waypoint_hold_seconds))
    previous = points[0]
    previous_yaw = 0.0
    for waypoint in points[1:]:
        speed_limits = [params.vel_limit]
        if previous.speed_limit_mps is not None:
            speed_limits.append(previous.speed_limit_mps)
        if waypoint.speed_limit_mps is not None:
            speed_limits.append(waypoint.speed_limit_mps)
        segment_params = replace(params, vel_limit=min(speed_limits))
        segment = base._build_motion_setpoints(
            previous,
            [waypoint],
            segment_params,
            rate_hz,
            max_samples=base.MAX_SETPOINTS - len(schedule),
        )
        schedule.extend(segment)
        if segment:
            previous_yaw = segment[-1].yaw_deg
        if hold_samples > base.MAX_SETPOINTS - len(schedule):
            raise RuntimeError("runtime replacement schedule exceeds setpoint limit")
        hold = base.enu_point_to_ned_setpoint(waypoint, yaw_deg=previous_yaw)
        schedule.extend(hold for _ in range(hold_samples))
        previous = waypoint
    final = base.enu_point_to_ned_setpoint(points[-1], yaw_deg=previous_yaw)
    final_samples = max(2, int(rate_hz * 0.5))
    if final_samples > base.MAX_SETPOINTS - len(schedule):
        raise RuntimeError("runtime replacement schedule exceeds setpoint limit")
    schedule.extend(final for _ in range(final_samples))
    return schedule


def _runtime_session(control_dir: Path | None) -> RuntimeControlSession | None:
    if control_dir is None:
        return None
    return RuntimeControlSession.model_validate_json(
        (control_dir / "session.json").read_text(encoding="utf-8")
    )


def _claim_runtime_message(
    control_dir: Path | None, session: RuntimeControlSession | None
) -> RuntimeInterruptDetected | None:
    if control_dir is None or session is None:
        return None
    for inbox_path in sorted((control_dir / "inbox").glob("runtime-msg-*.json")):
        claimed_path = control_dir / "claimed" / inbox_path.name
        try:
            inbox_path.replace(claimed_path)
        except FileNotFoundError:
            continue
        message = RuntimeUserMessage.model_validate_json(claimed_path.read_text(encoding="utf-8"))
        gates = {
            "conversation": message.conversation_id == session.conversation_id,
            "mission": message.mission_id == session.mission_id,
            "plan_revision": message.plan_revision_id == session.plan_revision_id,
            "contract": message.contract_id == session.contract_id,
            "execution": message.execution_id == session.execution_id,
            "session_accepting": session.state == "accepting",
        }
        if not all(gates.values()):
            _atomic_json(
                control_dir / "rejected" / claimed_path.name,
                {
                    "message": message.model_dump(mode="json"),
                    "identity_gates": gates,
                    "rejected_at": datetime.now(UTC).isoformat(),
                },
            )
            raise RuntimeError("RUNTIME_MESSAGE_SESSION_BINDING_MISMATCH")
        detected_at = datetime.now(UTC)
        _atomic_json(
            control_dir / "side-effects.state.json",
            {
                "enabled": False,
                "execution_id": message.execution_id,
                "message_id": message.message_id,
                "reason": "runtime user message preempted the confirmed plan",
                "updated_at": detected_at.isoformat(),
            },
        )
        _atomic_json(
            control_dir / "detected" / claimed_path.name,
            {
                "message_sha256": sha256_json(message),
                "message_id": message.message_id,
                "detected_at": detected_at.isoformat(),
                "old_plan_advancement_inhibited": True,
                "semantic_side_effects_inhibited": True,
            },
        )
        return RuntimeInterruptDetected(message, claimed_path, detected_at)
    return None


async def _stabilize_runtime_hold(
    *,
    client: Any,
    frozen_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    control_dir: Path,
    phase: str,
    schedule_index: int | None,
    rate_hz: float,
    timeout_seconds: float,
) -> tuple[RuntimeHoldAcknowledgement, Any]:
    detected_at = interruption.detected_at
    detection_latency_ms = max(
        0,
        round((detected_at - interruption.message.submitted_at).total_seconds() * 1000),
    )
    await client.set_position_ned(frozen_setpoint)
    observed = await client.sample_position_velocity_ned(1.0)
    hold_setpoint = type(frozen_setpoint)(
        north_m=observed.north_m,
        east_m=observed.east_m,
        down_m=observed.down_m,
        yaw_deg=frozen_setpoint.yaw_deg,
    )
    started = time.monotonic()
    stable_since: float | None = None
    latest = observed
    position_error = math.inf
    speed = math.inf
    while time.monotonic() - started < timeout_seconds:
        await client.set_position_ned(hold_setpoint)
        latest = await client.sample_position_velocity_ned(1.0)
        position_error = math.dist(
            (latest.north_m, latest.east_m, latest.down_m),
            (hold_setpoint.north_m, hold_setpoint.east_m, hold_setpoint.down_m),
        )
        speed = math.sqrt(latest.north_m_s**2 + latest.east_m_s**2 + latest.down_m_s**2)
        now = time.monotonic()
        if position_error <= 0.5 and speed <= 0.35:
            stable_since = now if stable_since is None else stable_since
            if now - stable_since >= 1.0:
                break
        else:
            stable_since = None
        await asyncio.sleep(1.0 / rate_hz)
    else:
        _atomic_json(
            control_dir / "hold-failures" / f"{interruption.message.message_id}.json",
            {
                "message_sha256": sha256_json(interruption.message),
                "phase": phase,
                "position_error_m": position_error,
                "speed_mps": speed,
                "failure": "RUNTIME_HOLD_STABILITY_TIMEOUT",
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )
        raise TimeoutError("runtime interruption could not establish stable hover")

    gates = {
        "telemetry_finite": all(
            math.isfinite(value)
            for value in (
                latest.north_m,
                latest.east_m,
                latest.down_m,
                latest.north_m_s,
                latest.east_m_s,
                latest.down_m_s,
                position_error,
                speed,
            )
        ),
        "position_error_within_0_50_m": position_error <= 0.5,
        "speed_within_0_35_mps": speed <= 0.35,
        "old_plan_advancement_inhibited": True,
        "semantic_side_effects_inhibited": True,
    }
    if not all(gates.values()):
        raise RuntimeError("runtime hold failed deterministic telemetry gates")
    stable_at = datetime.now(UTC)
    acknowledgement = RuntimeHoldAcknowledgement(
        message_sha256=sha256_json(interruption.message),
        message_id=interruption.message.message_id,
        execution_id=interruption.message.execution_id,
        interrupted_phase=phase,
        schedule_index=schedule_index,
        detected_at=detected_at,
        detection_latency_ms=detection_latency_ms,
        stable_at=stable_at,
        stabilization_latency_ms=round((time.monotonic() - started) * 1000),
        frozen_command_ned_m=Vector3(
            x=frozen_setpoint.north_m,
            y=frozen_setpoint.east_m,
            z=frozen_setpoint.down_m,
        ),
        hold_command_ned_m=Vector3(
            x=hold_setpoint.north_m,
            y=hold_setpoint.east_m,
            z=hold_setpoint.down_m,
        ),
        observed_position_ned_m=Vector3(x=latest.north_m, y=latest.east_m, z=latest.down_m),
        observed_velocity_ned_mps=Vector3(x=latest.north_m_s, y=latest.east_m_s, z=latest.down_m_s),
        position_error_m=position_error,
        speed_mps=speed,
        deterministic_gates=gates,
    )
    _atomic_json(
        control_dir / "acks" / f"{interruption.message.message_id}.json",
        acknowledgement,
    )
    return acknowledgement, hold_setpoint


async def _wait_runtime_decision(
    *,
    base: ModuleType,
    client: Any,
    hold_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    acknowledgement: RuntimeHoldAcknowledgement,
    control_dir: Path,
    abort_file: Path,
    rate_hz: float,
    timeout_seconds: float,
) -> RuntimeInterruptionDecision:
    decision_path = control_dir / "decisions" / f"{interruption.message.message_id}.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        base._raise_if_external_abort_requested(abort_file)
        await client.set_position_ned(hold_setpoint)
        if decision_path.is_file():
            decision = RuntimeInterruptionDecision.model_validate_json(
                decision_path.read_text(encoding="utf-8")
            )
            if decision.message_sha256 != sha256_json(interruption.message):
                raise RuntimeError("runtime decision message hash mismatch")
            if decision.hold_ack_sha256 != sha256_json(acknowledgement):
                raise RuntimeError("runtime decision hold acknowledgement hash mismatch")
            if not all(decision.authorization_gates.values()):
                raise RuntimeError("runtime decision contains a failed authorization gate")
            return decision
        await asyncio.sleep(1.0 / rate_hz)
    raise TimeoutError("runtime interruption model decision timeout")


async def _wait_runtime_replacement(
    *,
    base: ModuleType,
    client: Any,
    hold_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
    control_dir: Path,
    abort_file: Path,
    rate_hz: float,
    timeout_seconds: float,
    active_track_sha256: str,
) -> RuntimeReplacementTrack:
    replacement_path = control_dir / "replacements" / f"{interruption.message.message_id}.json"
    failure_path = control_dir / "replan-failures" / f"{interruption.message.message_id}.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        base._raise_if_external_abort_requested(abort_file)
        await client.set_position_ned(hold_setpoint)
        if failure_path.is_file():
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            raise UserDirectedLanding(
                f"runtime replacement rejected: {failure.get('reason', 'unknown')}"
            )
        if replacement_path.is_file():
            replacement = RuntimeReplacementTrack.model_validate_json(
                replacement_path.read_text(encoding="utf-8")
            )
            gates = {
                "message_id": replacement.message_id == interruption.message.message_id,
                "execution_id": replacement.execution_id == interruption.message.execution_id,
                "message_hash": replacement.message_sha256 == sha256_json(interruption.message),
                "hold_hash": replacement.hold_ack_sha256 == sha256_json(acknowledgement),
                "decision_hash": replacement.decision_sha256 == sha256_json(decision),
                "prior_track_hash": replacement.prior_track_sha256 == active_track_sha256,
                "planner_gates": all(replacement.deterministic_gates.values()),
                "clearance": replacement.clearance.accepted,
                "starts_at_hold": (
                    math.dist(
                        (
                            replacement.track.points[0].x,
                            replacement.track.points[0].y,
                            -replacement.track.points[0].z,
                        ),
                        (
                            hold_setpoint.north_m,
                            hold_setpoint.east_m,
                            hold_setpoint.down_m,
                        ),
                    )
                    <= 0.75
                ),
            }
            if not all(gates.values()):
                failed = ",".join(name for name, accepted in gates.items() if not accepted)
                raise UserDirectedLanding(f"runtime replacement binding failed: {failed}")
            return replacement
        await asyncio.sleep(1.0 / rate_hz)
    raise UserDirectedLanding("runtime replan was not supplied within the bounded safe-hold window")


async def _wait_runtime_command(
    *,
    base: ModuleType,
    client: Any,
    hold_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
    control_dir: Path,
    abort_file: Path,
    rate_hz: float,
    timeout_seconds: float,
) -> RuntimeAuthorizedCommand:
    command_path = control_dir / "commands" / f"{interruption.message.message_id}.json"
    failure_path = control_dir / "command-failures" / f"{interruption.message.message_id}.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        base._raise_if_external_abort_requested(abort_file)
        await client.set_position_ned(hold_setpoint)
        if failure_path.is_file():
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            raise UserDirectedLanding(
                f"runtime command rejected: {failure.get('reason', 'unknown')}"
            )
        if command_path.is_file():
            command = RuntimeAuthorizedCommand.model_validate_json(
                command_path.read_text(encoding="utf-8")
            )
            gates = {
                "message_id": command.message_id == interruption.message.message_id,
                "execution_id": command.execution_id == interruption.message.execution_id,
                "message_hash": command.message_sha256 == sha256_json(interruption.message),
                "hold_hash": command.hold_ack_sha256 == sha256_json(acknowledgement),
                "decision_hash": command.decision_sha256 == sha256_json(decision),
                "command_gates": all(command.deterministic_gates.values()),
            }
            if not all(gates.values()):
                failed = ",".join(name for name, accepted in gates.items() if not accepted)
                raise UserDirectedLanding(f"runtime command binding failed: {failed}")
            return command
        await asyncio.sleep(1.0 / rate_hz)
    raise UserDirectedLanding(
        "runtime command was not supplied within the bounded safe-hold window"
    )


async def _execute_runtime_command(
    *,
    base: ModuleType,
    client: Any,
    hold_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    command: RuntimeAuthorizedCommand,
    control_dir: Path,
    abort_file: Path,
    rate_hz: float,
    timeout_seconds: float,
) -> str:
    if command.action == "camera_control":
        operation = client.execute_camera_command(dict(command.parameters))
    elif command.action == "payload_control":
        operation = client.execute_payload_command(dict(command.parameters))
    elif command.action == "set_avoidance":
        operation = client.execute_avoidance_command(bool(command.parameters["enabled"]))
    else:
        raise UserDirectedLanding(f"unsupported runtime command action: {command.action}")

    task = asyncio.create_task(operation)
    deadline = time.monotonic() + timeout_seconds
    try:
        while not task.done() and time.monotonic() < deadline:
            base._raise_if_external_abort_requested(abort_file)
            await client.set_position_ned(hold_setpoint)
            await asyncio.sleep(1.0 / rate_hz)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise UserDirectedLanding("runtime command execution timed out during stable hold")
        observed_result = await task
    except Exception as exc:
        _atomic_json(
            control_dir / "command-failures" / f"{interruption.message.message_id}.json",
            {
                "message_id": interruption.message.message_id,
                "command_sha256": sha256_json(command),
                "reason": str(exc),
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )
        raise
    if not isinstance(observed_result, dict) or observed_result.get("confirmed") is not True:
        reason = "runtime command completed without a positive device readback"
        _atomic_json(
            control_dir / "command-failures" / f"{interruption.message.message_id}.json",
            {
                "message_id": interruption.message.message_id,
                "command_sha256": sha256_json(command),
                "reason": reason,
                "observed_result": observed_result,
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )
        raise UserDirectedLanding(reason)
    result = {
        "message_id": interruption.message.message_id,
        "execution_id": interruption.message.execution_id,
        "action": command.action,
        "command_sha256": sha256_json(command),
        "observed_result": observed_result,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _atomic_json(
        control_dir / "command-results" / f"{interruption.message.message_id}.json", result
    )
    adoption = RuntimeCommandAdoption(
        message_id=interruption.message.message_id,
        execution_id=interruption.message.execution_id,
        action=command.action,
        command_sha256=sha256_json(command),
        result_sha256=sha256_json(result),
        observed_result=observed_result,
        adopted_at=datetime.now(UTC),
    )
    _atomic_json(control_dir / "adoptions" / f"{interruption.message.message_id}.json", adoption)
    _atomic_json(
        control_dir / "side-effects.state.json",
        {
            "enabled": True,
            "execution_id": interruption.message.execution_id,
            "message_id": interruption.message.message_id,
            "reason": "hash-bound runtime command executed and device-confirmed",
            "command_sha256": sha256_json(command),
            "result_sha256": sha256_json(result),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    return "resume_original"


async def _handle_runtime_interruption(
    *,
    base: ModuleType,
    client: Any,
    frozen_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    control_dir: Path,
    phase: str,
    schedule_index: int | None,
    abort_file: Path,
    rate_hz: float,
    hold_timeout_seconds: float,
    decision_timeout_seconds: float,
    replan_hold_seconds: float,
    active_track_sha256: str,
    params: Any,
    semantic_path: Path | None = None,
    vehicle_metadata_path: Path | None = None,
    coordinate_contract: Px4CoordinateContract | None = None,
) -> str:
    acknowledgement, hold_setpoint = await _stabilize_runtime_hold(
        client=client,
        frozen_setpoint=frozen_setpoint,
        interruption=interruption,
        control_dir=control_dir,
        phase=phase,
        schedule_index=schedule_index,
        rate_hz=rate_hz,
        timeout_seconds=hold_timeout_seconds,
    )
    decision = await _wait_runtime_decision(
        base=base,
        client=client,
        hold_setpoint=hold_setpoint,
        interruption=interruption,
        acknowledgement=acknowledgement,
        control_dir=control_dir,
        abort_file=abort_file,
        rate_hz=rate_hz,
        timeout_seconds=decision_timeout_seconds,
    )
    processed_path = control_dir / "processed" / interruption.claimed_path.name
    interruption.claimed_path.replace(processed_path)
    if decision.authorized_action == "land":
        raise UserDirectedLanding(
            f"runtime user message requested landing: {interruption.message.message_id}"
        )
    if decision.authorized_action == "apply_command":
        command = await _wait_runtime_command(
            base=base,
            client=client,
            hold_setpoint=hold_setpoint,
            interruption=interruption,
            acknowledgement=acknowledgement,
            decision=decision,
            control_dir=control_dir,
            abort_file=abort_file,
            rate_hz=rate_hz,
            timeout_seconds=decision_timeout_seconds,
        )
        return await _execute_runtime_command(
            base=base,
            client=client,
            hold_setpoint=hold_setpoint,
            interruption=interruption,
            command=command,
            control_dir=control_dir,
            abort_file=abort_file,
            rate_hz=rate_hz,
            timeout_seconds=decision_timeout_seconds,
        )
    if decision.authorized_action == "hold_for_replan":
        _atomic_json(
            control_dir / "replan-required.json",
            {
                "message_id": interruption.message.message_id,
                "message_sha256": sha256_json(interruption.message),
                "hold_ack_sha256": sha256_json(acknowledgement),
                "decision_sha256": sha256_json(decision),
                "old_plan_resume_authorized": False,
                "required_artifact": "new code-validated plan revision and replacement track",
            },
        )
        replacement = await _wait_runtime_replacement(
            base=base,
            client=client,
            hold_setpoint=hold_setpoint,
            interruption=interruption,
            acknowledgement=acknowledgement,
            decision=decision,
            control_dir=control_dir,
            abort_file=abort_file,
            rate_hz=rate_hz,
            timeout_seconds=replan_hold_seconds,
            active_track_sha256=active_track_sha256,
        )
        schedule = _compile_replacement_schedule(
            base=base,
            replacement=replacement,
            params=params,
            rate_hz=rate_hz,
        )
        track_sha256 = sha256_json(replacement.track)
        adoption = {
            "message_id": interruption.message.message_id,
            "execution_id": interruption.message.execution_id,
            "replacement_sequence": replacement.replacement_sequence,
            "replacement_sha256": sha256_json(replacement),
            "track_sha256": track_sha256,
            "schedule_setpoints": len(schedule),
            "adopted_at": datetime.now(UTC).isoformat(),
        }
        _atomic_json(
            control_dir / "adoptions" / f"{interruption.message.message_id}.json",
            adoption,
        )
        _atomic_json(control_dir / "active-track.json", adoption)
        _atomic_json(
            control_dir / "side-effects.state.json",
            {
                "enabled": True,
                "execution_id": interruption.message.execution_id,
                "message_id": interruption.message.message_id,
                "reason": "code-validated runtime replacement track adopted",
                "replacement_sha256": sha256_json(replacement),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        raise RuntimeTrackReplacement(
            message_id=interruption.message.message_id,
            schedule=schedule,
            track_sha256=track_sha256,
            replacement_sequence=replacement.replacement_sequence,
            amendment_action=replacement.amendment_action,
            amendment_parameters=dict(replacement.amendment_parameters),
            coordinate_contract=replacement.track.coordinate_contract,
        )
    if decision.authorized_action == "hold":
        if decision.classification.requested_action == "operator_takeover":
            if (
                semantic_path is None
                or vehicle_metadata_path is None
                or coordinate_contract is None
            ):
                raise UserDirectedLanding(
                    "operator takeover is unavailable without collision and vehicle contracts"
                )
            grant = await _wait_operator_takeover_grant(
                base=base,
                client=client,
                hold_setpoint=hold_setpoint,
                interruption=interruption,
                acknowledgement=acknowledgement,
                decision=decision,
                control_dir=control_dir,
                abort_file=abort_file,
                rate_hz=rate_hz,
                timeout_seconds=replan_hold_seconds,
            )
            return await _run_operator_takeover(
                base=base,
                client=client,
                hold_setpoint=hold_setpoint,
                interruption=interruption,
                grant=grant,
                control_dir=control_dir,
                abort_file=abort_file,
                rate_hz=rate_hz,
                runtime_session=_runtime_session(control_dir),
                active_track_sha256=active_track_sha256,
                params=params,
                hold_timeout_seconds=hold_timeout_seconds,
                decision_timeout_seconds=decision_timeout_seconds,
                replan_hold_seconds=replan_hold_seconds,
                semantic_path=semantic_path,
                vehicle_metadata_path=vehicle_metadata_path,
                coordinate_contract=coordinate_contract,
            )
        _atomic_json(
            control_dir / "side-effects.state.json",
            {
                "enabled": False,
                "execution_id": interruption.message.execution_id,
                "message_id": interruption.message.message_id,
                "reason": "code-authorized persistent stable hold",
                "decision_sha256": sha256_json(decision),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        session = _runtime_session(control_dir)
        hold_deadline = time.monotonic() + replan_hold_seconds
        while time.monotonic() < hold_deadline:
            base._raise_if_external_abort_requested(abort_file)
            await client.set_position_ned(hold_setpoint)
            next_interruption = _claim_runtime_message(control_dir, session)
            if next_interruption is not None:
                return await _handle_runtime_interruption(
                    base=base,
                    client=client,
                    frozen_setpoint=hold_setpoint,
                    interruption=next_interruption,
                    control_dir=control_dir,
                    phase="PAUSED",
                    schedule_index=schedule_index,
                    abort_file=abort_file,
                    rate_hz=rate_hz,
                    hold_timeout_seconds=hold_timeout_seconds,
                    decision_timeout_seconds=decision_timeout_seconds,
                    replan_hold_seconds=replan_hold_seconds,
                    active_track_sha256=active_track_sha256,
                    params=params,
                    semantic_path=semantic_path,
                    vehicle_metadata_path=vehicle_metadata_path,
                    coordinate_contract=coordinate_contract,
                )
            await asyncio.sleep(1.0 / rate_hz)
        raise UserDirectedLanding("runtime pause exceeded the bounded safe-hold window")
    _atomic_json(
        control_dir / "side-effects.state.json",
        {
            "enabled": True,
            "execution_id": interruption.message.execution_id,
            "message_id": interruption.message.message_id,
            "reason": "code-authorized informational resume",
            "decision_sha256": sha256_json(decision),
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    return "resume_original"


async def _wait_operator_takeover_grant(
    *,
    base: ModuleType,
    client: Any,
    hold_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    acknowledgement: RuntimeHoldAcknowledgement,
    decision: RuntimeInterruptionDecision,
    control_dir: Path,
    abort_file: Path,
    rate_hz: float,
    timeout_seconds: float,
) -> RuntimeOperatorTakeoverGrant:
    path = control_dir / "takeover-grants" / f"{interruption.message.message_id}.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        base._raise_if_external_abort_requested(abort_file)
        await client.set_position_ned(hold_setpoint)
        if path.is_file():
            grant = RuntimeOperatorTakeoverGrant.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            gates = {
                "message_id": grant.message_id == interruption.message.message_id,
                "execution_id": grant.execution_id == interruption.message.execution_id,
                "message_hash": grant.message_sha256 == sha256_json(interruption.message),
                "hold_hash": grant.hold_ack_sha256 == sha256_json(acknowledgement),
                "decision_hash": grant.decision_sha256 == sha256_json(decision),
                "grant_gates": all(grant.deterministic_gates.values()),
                "not_expired": datetime.now(UTC) < grant.expires_at,
            }
            if not all(gates.values()):
                failed = ",".join(name for name, accepted in gates.items() if not accepted)
                raise UserDirectedLanding(f"operator takeover grant binding failed: {failed}")
            return grant
        await asyncio.sleep(1.0 / rate_hz)
    raise UserDirectedLanding("operator takeover grant was not supplied during stable hold")


async def _run_operator_takeover(
    *,
    base: ModuleType,
    client: Any,
    hold_setpoint: Any,
    interruption: RuntimeInterruptDetected,
    grant: RuntimeOperatorTakeoverGrant,
    control_dir: Path,
    abort_file: Path,
    rate_hz: float,
    runtime_session: RuntimeControlSession | None,
    active_track_sha256: str,
    params: Any,
    hold_timeout_seconds: float,
    decision_timeout_seconds: float,
    replan_hold_seconds: float,
    semantic_path: Path,
    vehicle_metadata_path: Path,
    coordinate_contract: Px4CoordinateContract,
) -> str:
    vehicle = VehicleAsset.model_validate_json(vehicle_metadata_path.read_text(encoding="utf-8"))
    current_setpoint = hold_setpoint
    current_world = _setpoint_world_enu(current_setpoint, coordinate_contract)
    grant_hash = sha256_json(grant)
    next_sequence = 1
    commands: list[dict[str, Any]] = []
    evidence_path = control_dir / "takeover-evidence" / f"{grant.message_id}.json"
    evidence: dict[str, Any] = {
        "schema_version": "dronedream.runtime-operator-takeover-evidence.v1",
        "message_id": grant.message_id,
        "execution_id": grant.execution_id,
        "operator_id": grant.operator_id,
        "grant_sha256": grant_hash,
        "status": "active",
        "started_at": datetime.now(UTC).isoformat(),
        "commands": commands,
    }
    _atomic_json(evidence_path, evidence)
    _atomic_json(
        control_dir / "takeover-adoptions" / f"{grant.message_id}.json",
        RuntimeOperatorTakeoverAdoption(
            message_id=grant.message_id,
            execution_id=grant.execution_id,
            grant_sha256=grant_hash,
            adopted_at=datetime.now(UTC),
        ),
    )
    command_dir = control_dir / "operator-commands"
    processed_dir = control_dir / "processed-operator-commands"
    processed_dir.mkdir(parents=True, exist_ok=True)
    period = 1.0 / rate_hz
    try:
        while datetime.now(UTC) < grant.expires_at:
            base._raise_if_external_abort_requested(abort_file)
            new_interruption = _claim_runtime_message(control_dir, runtime_session)
            if new_interruption is not None:
                outcome = await _handle_runtime_interruption(
                    base=base,
                    client=client,
                    frozen_setpoint=current_setpoint,
                    interruption=new_interruption,
                    control_dir=control_dir,
                    phase="TRACK",
                    schedule_index=None,
                    abort_file=abort_file,
                    rate_hz=rate_hz,
                    hold_timeout_seconds=hold_timeout_seconds,
                    decision_timeout_seconds=decision_timeout_seconds,
                    replan_hold_seconds=replan_hold_seconds,
                    active_track_sha256=active_track_sha256,
                    params=params,
                    semantic_path=semantic_path,
                    vehicle_metadata_path=vehicle_metadata_path,
                    coordinate_contract=coordinate_contract,
                )
                if outcome != "resume_original":
                    return outcome
            command_path = command_dir / f"{next_sequence:08d}.json"
            if not command_path.is_file():
                await client.set_position_ned(current_setpoint)
                await asyncio.sleep(period)
                continue
            command = RuntimeOperatorControlCommand.model_validate_json(
                command_path.read_text(encoding="utf-8")
            )
            gates = {
                "message_id": command.message_id == grant.message_id,
                "execution_id": command.execution_id == grant.execution_id,
                "grant_hash": command.grant_sha256 == grant_hash,
                "sequence": command.sequence == next_sequence,
                "fresh": abs((datetime.now(UTC) - command.issued_at).total_seconds()) <= 2.0,
                "horizontal_speed": math.hypot(
                    command.velocity_ned_mps.x, command.velocity_ned_mps.y
                )
                <= grant.maximum_horizontal_speed_mps,
                "vertical_speed": (
                    abs(command.velocity_ned_mps.z) <= grant.maximum_vertical_speed_mps
                ),
                "yaw_rate": abs(command.yaw_rate_dps) <= grant.maximum_yaw_rate_dps,
            }
            if not all(gates.values()):
                failed = ",".join(name for name, accepted in gates.items() if not accepted)
                raise UserDirectedLanding(f"operator control command rejected: {failed}")
            if command.action == "release":
                command_path.replace(processed_dir / command_path.name)
                commands.append(
                    {
                        "sequence": command.sequence,
                        "action": command.action,
                        "command_sha256": sha256_json(command),
                        "outcome": "controlled_landing",
                    }
                )
                raise UserDirectedLanding("operator released takeover; controlled landing required")
            steps = max(1, math.ceil(command.duration_seconds * rate_hz))
            step_seconds = command.duration_seconds / steps
            for _ in range(steps):
                desired_setpoint = base.Setpoint(
                    north_m=current_setpoint.north_m + command.velocity_ned_mps.x * step_seconds,
                    east_m=current_setpoint.east_m + command.velocity_ned_mps.y * step_seconds,
                    down_m=current_setpoint.down_m + command.velocity_ned_mps.z * step_seconds,
                    yaw_deg=(current_setpoint.yaw_deg + command.yaw_rate_dps * step_seconds)
                    % 360.0,
                )
                desired_world = _setpoint_world_enu(desired_setpoint, coordinate_contract)
                route = GraphRoute(
                    start_node="runtime-operator-current",
                    goal_node="runtime-operator-command",
                    node_ids=["runtime-operator-current", "runtime-operator-command"],
                    edge_ids=["runtime-operator-segment"],
                    positions_m=[current_world, desired_world],
                    route_length_m=math.dist(
                        (current_world.x, current_world.y, current_world.z),
                        (desired_world.x, desired_world.y, desired_world.z),
                    ),
                    all_edges_flight_verified=False,
                )
                clearance = validate_route_clearance(
                    route,
                    semantic_path,
                    vehicle_diameter_m=vehicle.body_radius_m * 2.0,
                    vehicle_height_m=vehicle.body_height_m,
                )
                if not clearance.accepted:
                    raise UserDirectedLanding(
                        "operator control clearance gate rejected the next command segment"
                    )
                current_setpoint = desired_setpoint
                current_world = desired_world
                await client.set_position_ned(current_setpoint)
                await asyncio.sleep(step_seconds)
            command_path.replace(processed_dir / command_path.name)
            commands.append(
                {
                    "sequence": command.sequence,
                    "action": command.action,
                    "command_sha256": sha256_json(command),
                    "final_world_enu_m": current_world.model_dump(mode="json"),
                    "deterministic_gates": gates,
                }
            )
            next_sequence += 1
            _atomic_json(evidence_path, evidence)
        raise UserDirectedLanding("operator takeover grant expired; controlled landing required")
    except BaseException as exc:
        evidence["status"] = "released" if "released takeover" in str(exc) else "failed"
        evidence["ended_at"] = datetime.now(UTC).isoformat()
        evidence["outcome"] = f"{type(exc).__name__}: {exc}"
        _atomic_json(evidence_path, evidence)
        raise


async def _wait_checkpoint_stable(
    *,
    client: Any,
    setpoint: Any,
    rate_hz: float,
    timeout_seconds: float = 12.0,
    stable_window_seconds: float = 1.0,
    runtime_interrupt_probe: Callable[[], RuntimeInterruptDetected | None] | None = None,
) -> tuple[Any, float, float]:
    started = time.monotonic()
    stable_since: float | None = None
    latest: Any | None = None
    latest_error = math.inf
    latest_speed = math.inf
    while time.monotonic() - started < timeout_seconds:
        if runtime_interrupt_probe is not None:
            interruption = runtime_interrupt_probe()
            if interruption is not None:
                raise interruption
        await client.set_position_ned(setpoint)
        latest = await client.sample_position_velocity_ned(1.0)
        latest_error = math.dist(
            (latest.north_m, latest.east_m, latest.down_m),
            (setpoint.north_m, setpoint.east_m, setpoint.down_m),
        )
        latest_speed = math.sqrt(latest.north_m_s**2 + latest.east_m_s**2 + latest.down_m_s**2)
        now = time.monotonic()
        if latest_error <= 0.75 and latest_speed <= 0.5:
            stable_since = now if stable_since is None else stable_since
            if now - stable_since >= stable_window_seconds:
                return latest, latest_error, latest_speed
        else:
            stable_since = None
        await asyncio.sleep(1.0 / rate_hz)
    raise TimeoutError(
        "checkpoint stability timeout: "
        f"position_error_m={latest_error:.3f}, speed_mps={latest_speed:.3f}"
    )


def _schedule_checkpoint_indices(
    base: ModuleType,
    schedule: list[Any],
    points: list[Any],
    checkpoints: RuntimeCheckpointContract,
    track_start_index: int,
) -> dict[int, RuntimeCheckpointRequest | Any]:
    requested = {item.track_point_index: item for item in checkpoints.checkpoints}
    if any(index >= len(points) for index in requested):
        raise ValueError("checkpoint track_point_index exceeds the reference track")
    found: dict[int, Any] = {}
    cursor = max(0, track_start_index)
    for point_index, point in enumerate(points):
        if point_index not in requested:
            continue
        target = base.enu_point_to_ned_setpoint(point, yaw_deg=0.0)
        match: int | None = None
        for schedule_index in range(cursor, len(schedule)):
            candidate = schedule[schedule_index]
            if (
                math.dist(
                    (candidate.north_m, candidate.east_m, candidate.down_m),
                    (target.north_m, target.east_m, target.down_m),
                )
                <= 1e-8
            ):
                match = schedule_index
                break
        if match is None:
            raise ValueError(f"checkpoint point {point_index} is absent from schedule")
        found[match] = requested[point_index]
        cursor = match + 1
    if len(found) != len(requested):
        raise ValueError("not every checkpoint mapped to the setpoint schedule")
    return found


def _setpoint_world_enu(
    setpoint: Any,
    coordinate_contract: Px4CoordinateContract,
) -> Vector3:
    root_east, root_north, root_up = coordinate_contract.model_root_world_enu_m
    return Vector3(
        x=root_east + float(setpoint.east_m),
        y=root_north + float(setpoint.north_m),
        z=(
            root_up
            + coordinate_contract.collision_center_above_model_root_m
            - float(setpoint.down_m)
        ),
    )


def _world_enu_setpoint(
    *,
    base: ModuleType,
    world: Vector3,
    yaw_deg: float,
    coordinate_contract: Px4CoordinateContract,
) -> Any:
    root_east, root_north, root_up = coordinate_contract.model_root_world_enu_m
    return base.Setpoint(
        north_m=world.y - root_north,
        east_m=world.x - root_east,
        down_m=-(world.z - root_up - coordinate_contract.collision_center_above_model_root_m),
        yaw_deg=yaw_deg,
    )


def _publish_local_safety_target(
    *,
    path: Path | None,
    setpoint: Any,
    coordinate_contract: Px4CoordinateContract,
) -> None:
    if path is None:
        return
    target = _setpoint_world_enu(setpoint, coordinate_contract)
    _atomic_json(
        path,
        {
            "schema_version": "dronedream.local-safety-target.v1",
            "target_position_m": target.model_dump(mode="json"),
            "updated_at_unix_ms": int(time.time() * 1_000),
        },
    )


def _read_local_safety_command(args: argparse.Namespace) -> RuntimeLocalSafetyCommand | None:
    if args.local_safety_command is None or not args.local_safety_command.is_file():
        return None
    try:
        command = RuntimeLocalSafetyCommand.model_validate_json(
            args.local_safety_command.read_text(encoding="utf-8")
        )
        if command.valid_until_unix_ms < int(time.time() * 1_000):
            return None
        if args.local_safety_observation is not None:
            observation = RuntimeLocalSafetyObservation.model_validate_json(
                args.local_safety_observation.read_text(encoding="utf-8")
            )
            if command.observation_sequence != observation.sequence:
                return None
            if command.observation_sha256 != sha256_json(observation):
                raise RuntimeError("local safety observation hash mismatch")
        return command
    except FileNotFoundError:
        return None


async def _apply_local_safety(
    *,
    args: argparse.Namespace,
    base: ModuleType,
    client: Any,
    planned_setpoint: Any,
    coordinate_contract: Px4CoordinateContract,
    phase_path: Path,
) -> None:
    """Hold schedule advancement while a live local repair command is active."""

    _publish_local_safety_target(
        path=args.local_safety_target,
        setpoint=planned_setpoint,
        coordinate_contract=coordinate_contract,
    )
    if args.local_safety_command is None:
        await client.set_position_ned(planned_setpoint)
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + args.local_safety_repair_timeout_seconds
    waited_for_first_command = False
    while True:
        command = _read_local_safety_command(args)
        if command is None:
            if not waited_for_first_command:
                waited_for_first_command = True
                await client.set_position_ned(planned_setpoint)
                await asyncio.sleep(min(0.1, 1.0 / args.setpoint_rate_hz))
                continue
            await client.set_position_ned(planned_setpoint)
            return
        action = command.decision.action
        if action == "continue":
            await client.set_position_ned(planned_setpoint)
            return
        if loop.time() >= deadline:
            raise UserDirectedLanding("local safety repair exceeded its bounded hold window")
        safe_setpoint = _world_enu_setpoint(
            base=base,
            world=command.command_position_m,
            yaw_deg=float(planned_setpoint.yaw_deg),
            coordinate_contract=coordinate_contract,
        )
        _atomic_json(
            phase_path,
            {
                "phase": "HOLDING" if action == "hold" else "LOCAL_REPLAN",
                "local_safety_action": action,
                "observation_sequence": command.observation_sequence,
                "threat_obstacle_id": command.decision.threat_obstacle_id,
                "minimum_predicted_clearance_m": (
                    command.decision.minimum_predicted_clearance_m
                ),
            },
        )
        await client.set_position_ned(safe_setpoint)
        await asyncio.sleep(1.0 / args.setpoint_rate_hz)
        _publish_local_safety_target(
            path=args.local_safety_target,
            setpoint=planned_setpoint,
            coordinate_contract=coordinate_contract,
        )


async def _follow_runtime_target(
    *,
    args: argparse.Namespace,
    base: ModuleType,
    client: Any,
    params: Any,
    runtime_session: RuntimeControlSession | None,
    replacement: RuntimeTrackReplacement,
    initial_setpoint: Any,
    phase_path: Path,
    timing: dict[str, Any],
) -> Any:
    """Continuously follow a Gazebo target while retaining the fail-closed runtime envelope."""

    if args.semantic is None or args.vehicle_metadata is None:
        raise UserDirectedLanding("dynamic follow requires semantic and vehicle metadata artifacts")
    vehicle = VehicleAsset.model_validate_json(args.vehicle_metadata.read_text(encoding="utf-8"))
    parameters = dict(replacement.amendment_parameters)
    duration = float(parameters.get("follow_duration_seconds", 30.0))
    update_rate_hz = float(parameters.get("target_update_rate_hz", 2.0))
    standoff_m = float(parameters.get("standoff_m", 2.0))
    altitude_offset_m = float(parameters.get("altitude_offset_m", 1.0))
    maximum_speed_mps = min(
        float(parameters.get("maximum_speed_mps", 1.0)),
        vehicle.max_speed_mps,
    )
    if not (
        1.0 <= duration <= 300.0
        and 0.5 <= update_rate_hz <= 10.0
        and 0.5 <= standoff_m <= 20.0
        and -5.0 <= altitude_offset_m <= 20.0
        and 0.1 <= maximum_speed_mps <= 3.0
    ):
        raise UserDirectedLanding(
            "dynamic follow parameters are outside the bounded safety contract"
        )

    control_period = 1.0 / args.setpoint_rate_hz
    observation_period = 1.0 / update_rate_hz
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + duration
    next_observation_at = started
    current_setpoint = initial_setpoint
    current_world = _setpoint_world_enu(current_setpoint, replacement.coordinate_contract)
    standoff_unit: tuple[float, float] | None = None
    observation_task: asyncio.Task[dict[str, float | str]] | None = None
    observations: list[dict[str, Any]] = []
    evidence_path = args.runtime_control_dir / "follow" / f"{replacement.message_id}.evidence.json"
    evidence: dict[str, Any] = {
        "schema_version": "dronedream.runtime-follow-evidence.v1",
        "message_id": replacement.message_id,
        "replacement_sequence": replacement.replacement_sequence,
        "target_pose_topic": parameters.get("target_pose_topic"),
        "parameters": parameters,
        "semantic_sha256": hashlib.sha256(args.semantic.read_bytes()).hexdigest(),
        "vehicle_asset_id": vehicle.asset_id,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "observations": observations,
    }
    _atomic_json(evidence_path, evidence)
    _atomic_json(
        phase_path,
        {
            "phase": "TRACK",
            "mode": "FOLLOW_TARGET",
            "message_id": replacement.message_id,
            "replacement_sequence": replacement.replacement_sequence,
        },
    )
    try:
        while loop.time() < deadline:
            base._raise_if_external_abort_requested(args.abort_file)
            interruption = _claim_runtime_message(args.runtime_control_dir, runtime_session)
            if interruption is not None:
                started_hold = loop.time()
                await _handle_runtime_interruption(
                    base=base,
                    client=client,
                    frozen_setpoint=current_setpoint,
                    interruption=interruption,
                    control_dir=args.runtime_control_dir,
                    phase="TRACK",
                    schedule_index=None,
                    abort_file=args.abort_file,
                    rate_hz=args.setpoint_rate_hz,
                    hold_timeout_seconds=args.runtime_hold_timeout_seconds,
                    decision_timeout_seconds=args.runtime_decision_timeout_seconds,
                    replan_hold_seconds=args.runtime_replan_hold_seconds,
                    active_track_sha256=replacement.track_sha256,
                    params=params,
                    semantic_path=args.semantic,
                    vehicle_metadata_path=args.vehicle_metadata,
                    coordinate_contract=replacement.coordinate_contract,
                )
                hold_duration = loop.time() - started_hold
                deadline += hold_duration
                next_observation_at = loop.time()
                timing["runtime_interruptions"].append(
                    {
                        "message_id": interruption.message.message_id,
                        "interrupted_phase": "FOLLOW_TARGET",
                        "outcome": "resume_follow_target",
                        "duration_seconds": hold_duration,
                    }
                )

            now = loop.time()
            if observation_task is None and now >= next_observation_at:
                observation_task = asyncio.create_task(client.sample_gazebo_pose(parameters))
                next_observation_at = now + observation_period
            if observation_task is not None and observation_task.done():
                sample = observation_task.result()
                observation_task = None
                target = Vector3(
                    x=float(sample["x"]),
                    y=float(sample["y"]),
                    z=float(sample["z"]),
                )
                if standoff_unit is None:
                    delta_x = current_world.x - target.x
                    delta_y = current_world.y - target.y
                    horizontal = math.hypot(delta_x, delta_y)
                    standoff_unit = (
                        (delta_x / horizontal, delta_y / horizontal)
                        if horizontal > 1e-6
                        else (-1.0, 0.0)
                    )
                desired = Vector3(
                    x=target.x + standoff_unit[0] * standoff_m,
                    y=target.y + standoff_unit[1] * standoff_m,
                    z=target.z + altitude_offset_m,
                )
                distance = math.dist(
                    (current_world.x, current_world.y, current_world.z),
                    (desired.x, desired.y, desired.z),
                )
                max_step = maximum_speed_mps * observation_period
                if distance > max_step:
                    ratio = max_step / distance
                    desired = Vector3(
                        x=current_world.x + (desired.x - current_world.x) * ratio,
                        y=current_world.y + (desired.y - current_world.y) * ratio,
                        z=current_world.z + (desired.z - current_world.z) * ratio,
                    )
                route = GraphRoute(
                    start_node="runtime-follow-current",
                    goal_node="runtime-follow-command",
                    node_ids=["runtime-follow-current", "runtime-follow-command"],
                    edge_ids=["runtime-follow-segment"],
                    positions_m=[current_world, desired],
                    route_length_m=math.dist(
                        (current_world.x, current_world.y, current_world.z),
                        (desired.x, desired.y, desired.z),
                    ),
                    all_edges_flight_verified=False,
                )
                clearance = validate_route_clearance(
                    route,
                    args.semantic,
                    vehicle_diameter_m=vehicle.body_radius_m * 2.0,
                    vehicle_height_m=vehicle.body_height_m,
                )
                if not clearance.accepted:
                    raise UserDirectedLanding(
                        "dynamic follow clearance gate rejected the next command segment"
                    )
                current_world = desired
                current_setpoint = _world_enu_setpoint(
                    base=base,
                    world=desired,
                    yaw_deg=float(current_setpoint.yaw_deg),
                    coordinate_contract=replacement.coordinate_contract,
                )
                observations.append(
                    {
                        "elapsed_seconds": loop.time() - started,
                        "target_world_enu_m": target.model_dump(mode="json"),
                        "command_world_enu_m": desired.model_dump(mode="json"),
                        "clearance_sha256": sha256_json(clearance),
                        "minimum_clearance_m": clearance.minimum_clearance_m,
                    }
                )
                if len(observations) > 3_000:
                    del observations[:-3_000]
            await client.set_position_ned(current_setpoint)
            await asyncio.sleep(control_period)
        evidence["status"] = "complete"
        evidence["completed_at"] = datetime.now(UTC).isoformat()
        evidence["final_command_world_enu_m"] = current_world.model_dump(mode="json")
        _atomic_json(evidence_path, evidence)
        timing["runtime_interruptions"].append(
            {
                "message_id": replacement.message_id,
                "outcome": "follow_target_complete",
                "observation_count": len(observations),
                "evidence_sha256": sha256_json(evidence),
            }
        )
        return current_setpoint
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        evidence["failed_at"] = datetime.now(UTC).isoformat()
        _atomic_json(evidence_path, evidence)
        raise
    finally:
        if observation_task is not None and not observation_task.done():
            observation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await observation_task


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--track", type=Path, required=True)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--vehicle", required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument("--abort-file", type=Path, required=True)
    parser.add_argument("--setpoint-rate-hz", type=float, required=True)
    parser.add_argument("--takeoff-timeout-seconds", type=float, required=True)
    parser.add_argument("--takeoff-climb-rate-m-s", type=float, required=True)
    parser.add_argument("--track-timeout-seconds", type=float, required=True)
    parser.add_argument("--landing-timeout-seconds", type=float, required=True)
    parser.add_argument("--takeoff-stable-window-seconds", type=float, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--connection", default="udp://:14540")
    parser.add_argument("--base-executor", type=Path, required=True)
    parser.add_argument("--checkpoint-contract", type=Path, required=True)
    parser.add_argument("--checkpoint-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--runtime-control-dir", type=Path)
    parser.add_argument("--runtime-hold-timeout-seconds", type=float, default=12.0)
    parser.add_argument("--runtime-decision-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--runtime-replan-hold-seconds", type=float, default=30.0)
    parser.add_argument("--local-safety-command", type=Path)
    parser.add_argument("--local-safety-observation", type=Path)
    parser.add_argument("--local-safety-target", type=Path)
    parser.add_argument("--local-safety-repair-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--semantic", type=Path)
    parser.add_argument("--vehicle-metadata", type=Path)
    return parser.parse_args()


async def _wait_checkpoint_decision(
    *,
    base: ModuleType,
    client: Any,
    setpoint: Any,
    request: RuntimeCheckpointRequest,
    decision_path: Path,
    abort_file: Path,
    rate_hz: float,
    timeout_seconds: float,
    runtime_interrupt_probe: Callable[[], RuntimeInterruptDetected | None] | None = None,
) -> RuntimeCheckpointDecision:
    deadline = time.monotonic() + timeout_seconds
    request_hash = sha256_json(request)
    while time.monotonic() < deadline:
        base._raise_if_external_abort_requested(abort_file)
        if runtime_interrupt_probe is not None:
            interruption = runtime_interrupt_probe()
            if interruption is not None:
                raise interruption
        await client.set_position_ned(setpoint)
        if decision_path.is_file():
            decision = RuntimeCheckpointDecision.model_validate_json(
                decision_path.read_text(encoding="utf-8")
            )
            if decision.request_sha256 != request_hash:
                raise RuntimeError("checkpoint decision request hash mismatch")
            return decision
        await asyncio.sleep(1.0 / rate_hz)
    raise TimeoutError(f"checkpoint decision timeout: {request.checkpoint.checkpoint_id}")


async def _fly_runtime_replacement(
    *,
    args: argparse.Namespace,
    base: ModuleType,
    client: Any,
    params: Any,
    runtime_session: RuntimeControlSession | None,
    phase_path: Path,
    timing: dict[str, Any],
    initial: RuntimeTrackReplacement,
) -> str:
    replacement = initial
    loop = asyncio.get_running_loop()
    while True:
        active_track_sha256 = replacement.track_sha256
        schedule = replacement.schedule
        timing["runtime_interruptions"].append(
            {
                "message_id": replacement.message_id,
                "outcome": "replacement_track_adopted",
                "replacement_sequence": replacement.replacement_sequence,
                "track_sha256": replacement.track_sha256,
                "setpoint_count": len(schedule),
            }
        )
        _atomic_json(
            phase_path,
            {
                "phase": "TRACK",
                "checkpoint_id": None,
                "replacement_sequence": replacement.replacement_sequence,
            },
        )
        deadline = loop.time() + args.track_timeout_seconds
        last_setpoint = schedule[0]
        try:
            for index, setpoint in enumerate(schedule):
                base._raise_if_external_abort_requested(args.abort_file)
                if loop.time() >= deadline:
                    raise TimeoutError("runtime replacement track timeout")
                interruption = _claim_runtime_message(args.runtime_control_dir, runtime_session)
                if interruption is not None:
                    _atomic_json(
                        phase_path,
                        {
                            "phase": "HOLDING",
                            "interrupted_phase": "TRACK",
                            "message_id": interruption.message.message_id,
                            "replacement_sequence": replacement.replacement_sequence,
                        },
                    )
                    started = loop.time()
                    await _handle_runtime_interruption(
                        base=base,
                        client=client,
                        frozen_setpoint=last_setpoint,
                        interruption=interruption,
                        control_dir=args.runtime_control_dir,
                        phase="TRACK",
                        schedule_index=index,
                        abort_file=args.abort_file,
                        rate_hz=args.setpoint_rate_hz,
                        hold_timeout_seconds=args.runtime_hold_timeout_seconds,
                        decision_timeout_seconds=args.runtime_decision_timeout_seconds,
                        replan_hold_seconds=args.runtime_replan_hold_seconds,
                        active_track_sha256=active_track_sha256,
                        params=params,
                        semantic_path=args.semantic,
                        vehicle_metadata_path=args.vehicle_metadata,
                        coordinate_contract=replacement.coordinate_contract,
                    )
                    deadline += loop.time() - started
                    timing["runtime_interruptions"].append(
                        {
                            "message_id": interruption.message.message_id,
                            "outcome": "resume_replacement_track",
                            "replacement_sequence": replacement.replacement_sequence,
                        }
                    )
                    _atomic_json(
                        phase_path,
                        {
                            "phase": "TRACK",
                            "checkpoint_id": None,
                            "replacement_sequence": replacement.replacement_sequence,
                        },
                    )
                await _apply_local_safety(
                    args=args,
                    base=base,
                    client=client,
                    planned_setpoint=setpoint,
                    coordinate_contract=replacement.coordinate_contract,
                    phase_path=phase_path,
                )
                last_setpoint = setpoint
                await asyncio.sleep(1.0 / args.setpoint_rate_hz)
            if replacement.amendment_action == "follow_target":
                last_setpoint = await _follow_runtime_target(
                    args=args,
                    base=base,
                    client=client,
                    params=params,
                    runtime_session=runtime_session,
                    replacement=replacement,
                    initial_setpoint=last_setpoint,
                    phase_path=phase_path,
                    timing=timing,
                )
            return active_track_sha256
        except RuntimeTrackReplacement as next_replacement:
            replacement = next_replacement


async def _run(args: argparse.Namespace, base: ModuleType) -> None:
    frozen_track = Px4Track.model_validate_json(args.track.read_text(encoding="utf-8"))
    reference = base.load_reference_track_plan(args.track)
    coordinate_contract = frozen_track.coordinate_contract
    active_track_sha256 = sha256_json(frozen_track)
    params = base.load_controller_params(args.params)
    plan = base.build_setpoint_schedule_plan(
        reference.points,
        params,
        args.setpoint_rate_hz,
        hover_duration_seconds=reference.hover_duration_seconds,
        stop_at_waypoints=reference.stop_at_waypoints,
        waypoint_hold_seconds=reference.waypoint_hold_seconds,
    )
    checkpoint_contract = RuntimeCheckpointContract.model_validate_json(
        args.checkpoint_contract.read_text(encoding="utf-8")
    )
    checkpoint_indices = _schedule_checkpoint_indices(
        base,
        plan.schedule,
        reference.points,
        checkpoint_contract,
        plan.track_start_index,
    )
    base._log(
        args.log,
        f"vehicle={args.vehicle} world={args.world} points={len(reference.points)} "
        f"setpoints={len(plan.schedule)} checkpoints={len(checkpoint_indices)}",
    )
    phase_path = args.run_dir / "runtime-phase.json"
    _atomic_json(phase_path, {"phase": "TAKEOFF", "checkpoint_id": None})
    runtime_session = _runtime_session(args.runtime_control_dir)

    client = base.MavsdkOffboardClient()
    timing: dict[str, Any] = {
        "time_base": "executor_relative_seconds",
        "setpoint_count": len(plan.schedule),
        "rate_hz": args.setpoint_rate_hz,
        "status": "running",
        "takeoff_gate": {"status": "not_started"},
        "checkpoints": [],
        "runtime_interruptions": [],
        "cleanup": {"stop_offboard": "not_needed", "land": "not_needed", "close": "pending"},
    }
    started = time.monotonic()
    armed = False
    offboard_started = False
    landed = False
    pending_interruption: RuntimeInterruptDetected | None = None

    def runtime_interrupt_probe() -> RuntimeInterruptDetected | None:
        nonlocal pending_interruption
        if pending_interruption is None:
            pending_interruption = _claim_runtime_message(args.runtime_control_dir, runtime_session)
        return pending_interruption

    def abort_check() -> None:
        base._raise_if_external_abort_requested(args.abort_file)
        runtime_interrupt_probe()

    try:
        await base._await_with_abort_polling(
            client.connect(args.connection), abort_check=abort_check
        )
        base._log(args.log, f"connected via {args.connection}")
        health = await base._await_with_abort_polling(
            client.wait_until_ready(args.takeoff_timeout_seconds), abort_check=abort_check
        )
        if not health.armable or not health.home_position_ok or not health.local_position_ok:
            raise RuntimeError("PX4 readiness gate rejected checkpointed flight")
        origin = await base._await_with_abort_polling(
            client.sample_position_velocity_ned(min(2.0, args.takeoff_timeout_seconds)),
            abort_check=abort_check,
        )
        initial_hold = base.Setpoint(
            north_m=plan.schedule[0].north_m,
            east_m=plan.schedule[0].east_m,
            down_m=origin.down_m,
            yaw_deg=plan.schedule[0].yaw_deg,
        )
        await base._await_with_abort_polling(
            client.set_position_ned(initial_hold), abort_check=abort_check
        )
        await base._await_with_abort_polling(client.arm(), abort_check=abort_check)
        armed = True
        base._log(args.log, "armed")
        timing["takeoff_start_t"] = time.monotonic() - started
        await base._await_with_abort_polling(client.start_offboard(), abort_check=abort_check)
        offboard_started = True
        timing["offboard_start_t"] = time.monotonic() - started
        base._log(args.log, "offboard started")
        await base._wait_for_takeoff_stability(
            client,
            plan.schedule[0],
            takeoff_origin=origin,
            climb_rate_m_s=args.takeoff_climb_rate_m_s,
            timeout_seconds=args.takeoff_timeout_seconds,
            sample_rate_hz=args.setpoint_rate_hz,
            stable_window_seconds=args.takeoff_stable_window_seconds,
            horizontal_tolerance_m=0.35,
            vertical_tolerance_m=0.25,
            horizontal_speed_tolerance_m_s=0.35,
            vertical_speed_tolerance_m_s=0.25,
            evidence=timing["takeoff_gate"],
            abort_check=abort_check,
        )
        timing["takeoff_stable_t"] = time.monotonic() - started
        base._log(args.log, "takeoff telemetry gate achieved stable hover")
        if pending_interruption is not None:
            _atomic_json(
                phase_path,
                {
                    "phase": "HOLDING",
                    "interrupted_phase": "TAKEOFF",
                    "message_id": pending_interruption.message.message_id,
                },
            )
            interruption_started = time.monotonic()
            await _handle_runtime_interruption(
                base=base,
                client=client,
                frozen_setpoint=plan.schedule[0],
                interruption=pending_interruption,
                control_dir=args.runtime_control_dir,
                phase="TAKEOFF",
                schedule_index=None,
                abort_file=args.abort_file,
                rate_hz=args.setpoint_rate_hz,
                hold_timeout_seconds=args.runtime_hold_timeout_seconds,
                decision_timeout_seconds=args.runtime_decision_timeout_seconds,
                replan_hold_seconds=args.runtime_replan_hold_seconds,
                active_track_sha256=active_track_sha256,
                params=params,
                semantic_path=args.semantic,
                vehicle_metadata_path=args.vehicle_metadata,
                coordinate_contract=coordinate_contract,
            )
            timing["runtime_interruptions"].append(
                {
                    "message_id": pending_interruption.message.message_id,
                    "interrupted_phase": "TAKEOFF",
                    "outcome": "resume_original",
                    "duration_seconds": time.monotonic() - interruption_started,
                }
            )
            pending_interruption = None
        _atomic_json(phase_path, {"phase": "TRACK", "checkpoint_id": None})

        loop = asyncio.get_running_loop()
        motion_deadline = loop.time() + args.track_timeout_seconds
        last_setpoint = plan.schedule[0]
        for index, setpoint in enumerate(plan.schedule):
            abort_check()
            if loop.time() >= motion_deadline:
                raise TimeoutError("track timeout")
            if pending_interruption is not None:
                _atomic_json(
                    phase_path,
                    {
                        "phase": "HOLDING",
                        "interrupted_phase": "TRACK",
                        "message_id": pending_interruption.message.message_id,
                    },
                )
                interruption_started = loop.time()
                await _handle_runtime_interruption(
                    base=base,
                    client=client,
                    frozen_setpoint=last_setpoint,
                    interruption=pending_interruption,
                    control_dir=args.runtime_control_dir,
                    phase="TRACK",
                    schedule_index=index,
                    abort_file=args.abort_file,
                    rate_hz=args.setpoint_rate_hz,
                    hold_timeout_seconds=args.runtime_hold_timeout_seconds,
                    decision_timeout_seconds=args.runtime_decision_timeout_seconds,
                    replan_hold_seconds=args.runtime_replan_hold_seconds,
                    active_track_sha256=active_track_sha256,
                    params=params,
                    semantic_path=args.semantic,
                    vehicle_metadata_path=args.vehicle_metadata,
                    coordinate_contract=coordinate_contract,
                )
                duration = loop.time() - interruption_started
                motion_deadline += duration
                timing["runtime_interruptions"].append(
                    {
                        "message_id": pending_interruption.message.message_id,
                        "interrupted_phase": "TRACK",
                        "schedule_index": index,
                        "outcome": "resume_original",
                        "duration_seconds": duration,
                    }
                )
                pending_interruption = None
                _atomic_json(phase_path, {"phase": "TRACK", "checkpoint_id": None})
            await _apply_local_safety(
                args=args,
                base=base,
                client=client,
                planned_setpoint=setpoint,
                coordinate_contract=coordinate_contract,
                phase_path=phase_path,
            )
            last_setpoint = setpoint
            if index == plan.track_start_index:
                timing["track_start_t"] = time.monotonic() - started
            checkpoint = checkpoint_indices.get(index)
            if checkpoint is not None:
                _atomic_json(
                    phase_path,
                    {"phase": "CHECKPOINT", "checkpoint_id": checkpoint.checkpoint_id},
                )
                while True:
                    try:
                        observed, position_error, speed = await _wait_checkpoint_stable(
                            client=client,
                            setpoint=setpoint,
                            rate_hz=args.setpoint_rate_hz,
                            runtime_interrupt_probe=runtime_interrupt_probe,
                        )
                        break
                    except RuntimeInterruptDetected as interruption:
                        _atomic_json(
                            phase_path,
                            {
                                "phase": "HOLDING",
                                "interrupted_phase": "CHECKPOINT",
                                "message_id": interruption.message.message_id,
                            },
                        )
                        await _handle_runtime_interruption(
                            base=base,
                            client=client,
                            frozen_setpoint=setpoint,
                            interruption=interruption,
                            control_dir=args.runtime_control_dir,
                            phase="CHECKPOINT",
                            schedule_index=index,
                            abort_file=args.abort_file,
                            rate_hz=args.setpoint_rate_hz,
                            hold_timeout_seconds=args.runtime_hold_timeout_seconds,
                            decision_timeout_seconds=args.runtime_decision_timeout_seconds,
                            replan_hold_seconds=args.runtime_replan_hold_seconds,
                            active_track_sha256=active_track_sha256,
                            params=params,
                            semantic_path=args.semantic,
                            vehicle_metadata_path=args.vehicle_metadata,
                            coordinate_contract=coordinate_contract,
                        )
                        timing["runtime_interruptions"].append(
                            {
                                "message_id": interruption.message.message_id,
                                "interrupted_phase": "CHECKPOINT",
                                "schedule_index": index,
                                "outcome": "resume_original",
                            }
                        )
                        pending_interruption = None
                        _atomic_json(
                            phase_path,
                            {
                                "phase": "CHECKPOINT",
                                "checkpoint_id": checkpoint.checkpoint_id,
                            },
                        )
                battery = await client.sample_battery(3.0)
                raw_battery = float(battery["remaining_percent"])
                battery_percent = raw_battery * 100.0 if raw_battery <= 1.0 else raw_battery
                gates = {
                    "position_error_within_0_75_m": position_error <= 0.75,
                    "speed_within_0_50_mps": speed <= 0.5,
                    "battery_above_10_percent": battery_percent > 10.0,
                    "telemetry_finite": all(
                        math.isfinite(value)
                        for value in (
                            observed.north_m,
                            observed.east_m,
                            observed.down_m,
                            speed,
                            battery_percent,
                        )
                    ),
                }
                request = RuntimeCheckpointRequest(
                    contract_id=checkpoint_contract.contract_id,
                    checkpoint=checkpoint,
                    observed_position_ned_m=Vector3(
                        x=observed.north_m, y=observed.east_m, z=observed.down_m
                    ),
                    observed_velocity_ned_mps=Vector3(
                        x=observed.north_m_s,
                        y=observed.east_m_s,
                        z=observed.down_m_s,
                    ),
                    commanded_position_ned_m=Vector3(
                        x=setpoint.north_m, y=setpoint.east_m, z=setpoint.down_m
                    ),
                    position_error_m=position_error,
                    speed_mps=speed,
                    battery_percent=battery_percent,
                    deterministic_gates=gates,
                )
                request_path = (
                    args.run_dir / "checkpoints" / f"{checkpoint.checkpoint_id}.request.json"
                )
                decision_path = (
                    args.run_dir / "checkpoints" / f"{checkpoint.checkpoint_id}.decision.json"
                )
                _atomic_json(request_path, request)
                base._log(args.log, f"checkpoint requested {checkpoint.checkpoint_id}")
                if not all(gates.values()):
                    raise RuntimeError(
                        f"deterministic checkpoint gate failed: {checkpoint.checkpoint_id}"
                    )
                checkpoint_started = loop.time()
                while True:
                    try:
                        decision = await _wait_checkpoint_decision(
                            base=base,
                            client=client,
                            setpoint=setpoint,
                            request=request,
                            decision_path=decision_path,
                            abort_file=args.abort_file,
                            rate_hz=args.setpoint_rate_hz,
                            timeout_seconds=args.checkpoint_timeout_seconds,
                            runtime_interrupt_probe=runtime_interrupt_probe,
                        )
                        break
                    except RuntimeInterruptDetected as interruption:
                        _atomic_json(
                            phase_path,
                            {
                                "phase": "HOLDING",
                                "interrupted_phase": "CHECKPOINT",
                                "message_id": interruption.message.message_id,
                            },
                        )
                        await _handle_runtime_interruption(
                            base=base,
                            client=client,
                            frozen_setpoint=setpoint,
                            interruption=interruption,
                            control_dir=args.runtime_control_dir,
                            phase="CHECKPOINT",
                            schedule_index=index,
                            abort_file=args.abort_file,
                            rate_hz=args.setpoint_rate_hz,
                            hold_timeout_seconds=args.runtime_hold_timeout_seconds,
                            decision_timeout_seconds=args.runtime_decision_timeout_seconds,
                            replan_hold_seconds=args.runtime_replan_hold_seconds,
                            active_track_sha256=active_track_sha256,
                            params=params,
                            semantic_path=args.semantic,
                            vehicle_metadata_path=args.vehicle_metadata,
                            coordinate_contract=coordinate_contract,
                        )
                        timing["runtime_interruptions"].append(
                            {
                                "message_id": interruption.message.message_id,
                                "interrupted_phase": "CHECKPOINT",
                                "schedule_index": index,
                                "outcome": "resume_original",
                            }
                        )
                        pending_interruption = None
                        _atomic_json(
                            phase_path,
                            {
                                "phase": "CHECKPOINT",
                                "checkpoint_id": checkpoint.checkpoint_id,
                            },
                        )
                motion_deadline += loop.time() - checkpoint_started
                timing["checkpoints"].append(
                    {
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "request_sha256": sha256_json(request),
                        "decision_sha256": sha256_json(decision),
                        "continue_authorized": decision.continue_authorized,
                        "assessment_action": decision.assessment.action,
                    }
                )
                if not decision.continue_authorized or decision.assessment.action != "accept":
                    raise RuntimeError(
                        f"checkpoint continuation rejected: {checkpoint.checkpoint_id}"
                    )
                base._log(args.log, f"checkpoint accepted {checkpoint.checkpoint_id}")
                _atomic_json(phase_path, {"phase": "TRACK", "checkpoint_id": None})
            await asyncio.sleep(1.0 / args.setpoint_rate_hz)
        timing["track_end_t"] = time.monotonic() - started
        await client.stop_offboard()
        offboard_started = False
        timing["cleanup"]["stop_offboard"] = "completed"
        base._log(args.log, "offboard stopped")
        _atomic_json(phase_path, {"phase": "LANDING", "checkpoint_id": None})
        timing["land_start_t"] = time.monotonic() - started
        await client.land()
        observation = await client.wait_until_landed(args.landing_timeout_seconds)
        landed = True
        timing["cleanup"]["land"] = "confirmed_on_ground"
        timing["cleanup"]["landing_observation"] = observation
        timing["land_confirmed_t"] = time.monotonic() - started
        timing["status"] = "complete"
        _atomic_json(phase_path, {"phase": "COMPLETE", "checkpoint_id": None})
        base._log(args.log, "landing confirmed ON_GROUND by PX4 telemetry")
    except RuntimeTrackReplacement as replacement:
        try:
            active_track_sha256 = await _fly_runtime_replacement(
                args=args,
                base=base,
                client=client,
                params=params,
                runtime_session=runtime_session,
                phase_path=phase_path,
                timing=timing,
                initial=replacement,
            )
            timing["active_track_sha256"] = active_track_sha256
            timing["track_end_t"] = time.monotonic() - started
            await client.stop_offboard()
            offboard_started = False
            timing["cleanup"]["stop_offboard"] = "completed"
            base._log(args.log, "replacement offboard track completed")
            _atomic_json(phase_path, {"phase": "LANDING", "checkpoint_id": None})
            timing["land_start_t"] = time.monotonic() - started
            await client.land()
            observation = await client.wait_until_landed(args.landing_timeout_seconds)
            landed = True
            timing["cleanup"]["land"] = "confirmed_on_ground"
            timing["cleanup"]["landing_observation"] = observation
            timing["land_confirmed_t"] = time.monotonic() - started
            timing["status"] = "complete"
            _atomic_json(phase_path, {"phase": "COMPLETE", "checkpoint_id": None})
            base._log(args.log, "replacement track landing confirmed ON_GROUND")
        except BaseException as exc:
            timing["status"] = "failed"
            timing["failure"] = f"{type(exc).__name__}: {exc}"
            raise
    except BaseException as exc:
        timing["status"] = "failed"
        timing["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if offboard_started:
            try:
                await client.stop_offboard()
                timing["cleanup"]["stop_offboard"] = "completed_during_failure_cleanup"
            except Exception as exc:
                timing["cleanup"]["stop_offboard"] = f"failed: {exc}"
        if armed and not landed:
            try:
                _atomic_json(phase_path, {"phase": "LANDING", "checkpoint_id": None})
                await client.land()
                observation = await client.wait_until_landed(args.landing_timeout_seconds)
                timing["cleanup"]["land"] = "confirmed_on_ground_during_failure_cleanup"
                timing["cleanup"]["landing_observation"] = observation
            except Exception as exc:
                timing["cleanup"]["land"] = f"failed: {exc}"
        if timing["status"] != "complete":
            cleanup_land = str(timing["cleanup"].get("land", ""))
            phase = "LANDED" if cleanup_land.startswith("confirmed_on_ground") else "FAILED"
            _atomic_json(phase_path, {"phase": phase, "checkpoint_id": None})
        await client.close()
        timing["cleanup"]["close"] = "completed"
        base._write_offboard_timing(args.run_dir / "offboard_timing.json", timing)


def main() -> int:
    args = _parse_args()
    base = _load_base(args.base_executor)
    try:
        asyncio.run(_run(args, base))
        base._log(args.log, "checkpoint executor completed successfully")
        return 0
    except Exception as exc:
        base._log(args.log, f"checkpoint executor failure: {exc}")
        print(f"checkpoint PX4 executor failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
