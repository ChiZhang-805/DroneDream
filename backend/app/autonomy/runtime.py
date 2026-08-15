"""Process-local autonomy runtime supervisor with a fail-closed PX4 boundary.

This module accepts normalized observations and emits symbolic safety decisions.
It never opens a MAVLink connection or sends actuator commands. The simulation
bridge may be driven by a separately audited adapter; HITL and aircraft remain
shadow/locked until a signed Vehicle Pack registry is deployed.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock

from app.autonomy.models import (
    AutonomyCompileResponse,
    RuntimeObservation,
    RuntimeOperatorCommand,
    RuntimePhase,
    RuntimeSession,
    RuntimeSessionCreateRequest,
    SafetyAction,
    SafetyDecision,
    VehicleEnvelope,
)
from app.autonomy.service import compile_autonomy_mission

MAX_SESSIONS = 256
MAX_OBSERVATION_GAP_MS = 2_000
MAX_PERCEPTION_AGE_MS = 750
MAX_LOCALIZATION_COVARIANCE_M2 = 0.25
MIN_CLEARANCE_MARGIN_M = 0.12


class AutonomyRuntimeError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class _SessionRecord:
    owner_id: str
    client_request_id: str
    vehicle: VehicleEnvelope
    result: RuntimeSession


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _safety_decision(
    observation: RuntimeObservation,
    *,
    vehicle: VehicleEnvelope,
    previous_monotonic_ms: int,
) -> SafetyDecision:
    action: SafetyAction = "continue"
    codes: list[str] = []

    def escalate(candidate: SafetyAction, code: str) -> None:
        nonlocal action
        priority = {"continue": 0, "hold": 1, "land": 2, "abort": 3}
        if priority[candidate] > priority[action]:
            action = candidate
        codes.append(code)

    if observation.emergency_stop:
        escalate("abort", "safety.emergency-stop")
    if not observation.geofence_ok:
        escalate("land", "safety.geofence-violation")
    if observation.battery_percent <= vehicle.reserve_battery_percent:
        escalate("land", "safety.battery-reserve-reached")
    if not observation.link_ok:
        escalate("land" if not observation.landed else "hold", "safety.command-link-lost")
    total_mass = vehicle.dry_mass_kg + vehicle.launch_payload_kg + observation.payload_mass_kg
    if total_mass > vehicle.max_takeoff_mass_kg:
        escalate("land", "safety.measured-mass-exceeds-mtom")
    if observation.localization_covariance_m2 > MAX_LOCALIZATION_COVARIANCE_M2:
        escalate("hold", "safety.localization-uncertain")
    if observation.perception_age_ms > MAX_PERCEPTION_AGE_MS:
        escalate("hold", "safety.perception-stale")
    if observation.minimum_clearance_m < vehicle.radius_m + MIN_CLEARANCE_MARGIN_M:
        escalate("hold", "safety.clearance-envelope-violated")
    if previous_monotonic_ms and (
        observation.monotonic_ms - previous_monotonic_ms > MAX_OBSERVATION_GAP_MS
    ):
        escalate("hold", "safety.observation-gap")
    if not codes:
        codes.append("safety.nominal")
    return SafetyDecision(action=action, accepted=True, codes=sorted(set(codes)))


def _next_phase(observation: RuntimeObservation, decision: SafetyDecision) -> RuntimePhase:
    if decision.action == "abort":
        return "aborted"
    if decision.action == "land":
        return "landing"
    if decision.action == "hold":
        return "holding"
    if observation.landed and observation.mission_progress >= 0.995:
        return "completed"
    if not observation.armed or observation.landed:
        return "ready"
    if observation.local_replan_active:
        return "replanning"
    if observation.pickup_confirmed and observation.mission_progress < 0.62:
        return "pickup"
    if observation.pickup_confirmed:
        return "returning"
    if observation.mission_progress < 0.1:
        return "takeoff"
    return "navigating"


class RuntimeSessionRegistry:
    """Bounded, owner-scoped registry for simulation runtime receipts."""

    def __init__(self, *, max_sessions: int = MAX_SESSIONS) -> None:
        self._max_sessions = max_sessions
        self._lock = RLock()
        self._records: OrderedDict[str, _SessionRecord] = OrderedDict()
        self._idempotency: dict[tuple[str, str], str] = {}

    def capabilities(self) -> dict[str, object]:
        return {
            "schema_version": "dronedream.autonomy.runtime-capabilities.v1",
            "persistence": "process_local_bounded",
            "max_sessions": self._max_sessions,
            "accepted_observation_schema": "dronedream.autonomy.observation.v1",
            "simulation_command_authority": True,
            "hitl_command_authority": False,
            "hardware_command_authority": False,
            "validated_signed_vehicle_packs": 0,
            "physical_transport_bound": False,
            "safe_operator_commands": ["hold", "abort"],
        }

    def create(self, owner_id: str, request: RuntimeSessionCreateRequest) -> RuntimeSession:
        compiled = compile_autonomy_mission(request.mission)
        if not compiled.execution_policy.can_execute:
            raise AutonomyRuntimeError(
                "AUTONOMY_RUNTIME_NOT_AUTHORIZED",
                "Only a feasible simulation contract can create a runtime session.",
                403,
            )
        idempotency_key = (owner_id, request.client_request_id)
        with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id:
                existing = self._records[existing_id]
                if existing.result.contract_id != compiled.contract.contract_id:
                    raise AutonomyRuntimeError(
                        "AUTONOMY_RUNTIME_IDEMPOTENCY_CONFLICT",
                        "client_request_id was already used for another mission contract.",
                    )
                return existing.result.model_copy(deep=True)
            self._make_room()
            session_id = "runtime-" + _hash(
                [owner_id, request.client_request_id, compiled.contract.contract_id]
            )[:24]
            now = _now()
            chain_head = _hash(
                {
                    "event": "session-created",
                    "session_id": session_id,
                    "contract_id": compiled.contract.contract_id,
                    "runtime_profile": compiled.runtime_profile.model_dump(mode="json"),
                }
            )
            session = RuntimeSession(
                session_id=session_id,
                contract_id=compiled.contract.contract_id,
                execution_target=compiled.contract.execution_target,
                phase="ready",
                bridge=compiled.runtime_profile.bridge,
                command_authority=compiled.runtime_profile.command_authority,
                created_at=now,
                updated_at=now,
                latest_sequence=0,
                latest_monotonic_ms=0,
                observation_count=0,
                decision=SafetyDecision(
                    action="hold",
                    accepted=True,
                    codes=["runtime.awaiting-first-observation"],
                ),
                evidence_chain_head=chain_head,
                terminal=False,
            )
            self._records[session_id] = _SessionRecord(
                owner_id=owner_id,
                client_request_id=request.client_request_id,
                vehicle=request.mission.vehicle.model_copy(deep=True),
                result=session,
            )
            self._idempotency[idempotency_key] = session_id
            return session.model_copy(deep=True)

    def get(self, owner_id: str, session_id: str) -> RuntimeSession:
        with self._lock:
            record = self._owned(owner_id, session_id)
            return record.result.model_copy(deep=True)

    def observe(
        self,
        owner_id: str,
        session_id: str,
        observation: RuntimeObservation,
    ) -> RuntimeSession:
        with self._lock:
            record = self._owned(owner_id, session_id)
            current = record.result
            if current.terminal:
                raise AutonomyRuntimeError(
                    "AUTONOMY_RUNTIME_TERMINAL",
                    "A completed or aborted session cannot accept observations.",
                )
            if observation.sequence <= current.latest_sequence:
                raise AutonomyRuntimeError(
                    "AUTONOMY_OBSERVATION_REPLAYED",
                    "Observation sequence must increase strictly.",
                )
            if observation.monotonic_ms <= current.latest_monotonic_ms:
                raise AutonomyRuntimeError(
                    "AUTONOMY_OBSERVATION_TIME_REVERSED",
                    "Observation monotonic_ms must increase strictly.",
                )
            decision = _safety_decision(
                observation,
                vehicle=record.vehicle,
                previous_monotonic_ms=current.latest_monotonic_ms,
            )
            phase = _next_phase(observation, decision)
            chain_head = _hash(
                {
                    "previous": current.evidence_chain_head,
                    "observation": observation.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                    "phase": phase,
                }
            )
            record.result = current.model_copy(
                deep=True,
                update={
                    "phase": phase,
                    "updated_at": _now(),
                    "latest_sequence": observation.sequence,
                    "latest_monotonic_ms": observation.monotonic_ms,
                    "observation_count": current.observation_count + 1,
                    "decision": decision,
                    "evidence_chain_head": chain_head,
                    "terminal": phase in {"completed", "aborted"},
                },
            )
            self._records.move_to_end(session_id)
            return record.result.model_copy(deep=True)

    def command(
        self,
        owner_id: str,
        session_id: str,
        command: RuntimeOperatorCommand,
    ) -> RuntimeSession:
        with self._lock:
            record = self._owned(owner_id, session_id)
            current = record.result
            if current.terminal:
                raise AutonomyRuntimeError(
                    "AUTONOMY_RUNTIME_TERMINAL",
                    "A completed or aborted session cannot accept operator commands.",
                )
            phase: RuntimePhase = "holding" if command.action == "hold" else "aborted"
            decision = SafetyDecision(
                action=command.action,
                accepted=True,
                codes=[f"operator.{command.action}"],
            )
            record.result = current.model_copy(
                deep=True,
                update={
                    "phase": phase,
                    "updated_at": _now(),
                    "decision": decision,
                    "evidence_chain_head": _hash(
                        {
                            "previous": current.evidence_chain_head,
                            "operator_command": command.model_dump(mode="json"),
                        }
                    ),
                    "terminal": command.action == "abort",
                },
            )
            self._records.move_to_end(session_id)
            return record.result.model_copy(deep=True)

    def _owned(self, owner_id: str, session_id: str) -> _SessionRecord:
        record = self._records.get(session_id)
        if record is None or record.owner_id != owner_id:
            raise AutonomyRuntimeError(
                "AUTONOMY_RUNTIME_NOT_FOUND",
                "Runtime session not found.",
                404,
            )
        return record

    def _make_room(self) -> None:
        if len(self._records) < self._max_sessions:
            return
        for session_id, record in self._records.items():
            if record.result.terminal:
                del self._records[session_id]
                self._idempotency.pop((record.owner_id, record.client_request_id), None)
                return
        raise AutonomyRuntimeError(
            "AUTONOMY_RUNTIME_CAPACITY_REACHED",
            "The bounded runtime registry has no terminal session to evict.",
            503,
        )


runtime_sessions = RuntimeSessionRegistry()


def runtime_profile_payload(compiled: AutonomyCompileResponse) -> dict[str, object]:
    """Return the profile with the compile result retained as the authority."""

    return compiled.runtime_profile.model_dump(mode="json")


__all__ = [
    "AutonomyRuntimeError",
    "RuntimeSessionRegistry",
    "runtime_profile_payload",
    "runtime_sessions",
]
