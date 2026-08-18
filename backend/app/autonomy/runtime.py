"""Process-local autonomy runtime supervisor with a fail-closed PX4 boundary.

This module accepts normalized observations and emits symbolic safety decisions.
It never opens a MAVLink connection or sends actuator commands. The simulation
bridge may be driven by a separately audited adapter; HITL and aircraft remain
shadow/locked until a signed Vehicle Pack registry is deployed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock

from app.autonomy.models import (
    AutonomyCompileResponse,
    MissionTaskGraph,
    MissionTaskNode,
    PerceivedEntity,
    RuntimeDecisionEvent,
    RuntimeDecisionKind,
    RuntimeObservation,
    RuntimeOperatorCommand,
    RuntimePhase,
    RuntimeSession,
    RuntimeSessionCreateRequest,
    SafetyAction,
    SafetyDecision,
    VehicleEnvelope,
)
from app.autonomy.planner_artifact import VerifiedPlannerArtifactReceipt
from app.autonomy.service import compile_autonomy_mission

MAX_SESSIONS = 256
MAX_OBSERVATION_GAP_MS = 2_000
MAX_PERCEPTION_AGE_MS = 750
MAX_LOCALIZATION_COVARIANCE_M2 = 0.25
MIN_CLEARANCE_MARGIN_M = 0.12
MAX_TASK_GRAPH_NODES = 128
MAX_ACTIVE_TASK_NODES = 16


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
    mission: RuntimeSessionCreateRequest
    planner_receipt: VerifiedPlannerArtifactReceipt | None
    result: RuntimeSession
    last_observation: RuntimeObservation | None = None


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
    for stream in observation.stream_health:
        if stream.kind in {"rgb", "depth", "stereo", "thermal", "lidar", "vio", "slam"} and (
            stream.status in {"stale", "offline"}
        ):
            escalate("hold", f"safety.perception-stream-{stream.status}")
    for entity in observation.perceived_entities:
        if entity.confidence < 0.5 or entity.age_ms > 1_000:
            continue
        distance = math.dist(
            (observation.position_m.x, observation.position_m.y, observation.position_m.z),
            (entity.position_m.x, entity.position_m.y, entity.position_m.z),
        )
        aircraft_speed = math.sqrt(
            observation.velocity_mps.x**2
            + observation.velocity_mps.y**2
            + observation.velocity_mps.z**2
        )
        stop_envelope = (
            vehicle.radius_m
            + entity.safety_radius_m
            + max(
                0.5,
                aircraft_speed * 0.75,
            )
        )
        if distance <= stop_envelope:
            suffix = "person" if entity.kind == "person" else "dynamic-entity"
            escalate("hold", f"safety.{suffix}-envelope")
        elif distance <= stop_envelope + 1.5:
            codes.append("world.dynamic-entity-nearby")
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


def _runtime_track_suffix(track_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", track_id.casefold()).strip("-.")
    return normalized[:48] or "entity"


def _dynamic_entities(observation: RuntimeObservation) -> list[PerceivedEntity]:
    return [
        entity
        for entity in observation.perceived_entities
        if entity.confidence >= 0.5 and entity.age_ms <= 1_000
    ]


def _next_decision_revision(events: list[RuntimeDecisionEvent]) -> int:
    return events[-1].revision + 1 if events else 1


def _advance_task_graph(
    graph: MissionTaskGraph,
    observation: RuntimeObservation,
    decision: SafetyDecision,
) -> MissionTaskGraph:
    """Advance compiler nodes and insert deterministic runtime recovery branches."""

    original_nodes = [node.model_copy(deep=True) for node in graph.nodes]
    base_nodes = [node for node in original_nodes if node.inserted_by != "runtime"]
    maximum_entity_branches = max(
        0,
        min(
            (MAX_TASK_GRAPH_NODES - len(base_nodes)) // 2,
            (MAX_ACTIVE_TASK_NODES - 1) // 2,
        ),
    )
    entities = sorted(
        _dynamic_entities(observation),
        key=lambda entity: math.dist(
            (observation.position_m.x, observation.position_m.y, observation.position_m.z),
            (entity.position_m.x, entity.position_m.y, entity.position_m.z),
        ),
    )[:maximum_entity_branches]
    current_suffixes = {_runtime_track_suffix(entity.track_id) for entity in entities}
    nodes = [
        *base_nodes,
        *[
            node
            for node in original_nodes
            if node.inserted_by == "runtime"
            and node.task_id.removeprefix("runtime-hold-").removeprefix("runtime-replan-")
            in current_suffixes
        ],
    ]
    compiler_nodes = [node for node in nodes if node.inserted_by == "compiler"]
    if observation.landed and observation.mission_progress >= 0.995:
        completed_count = len(compiler_nodes)
    else:
        completed_count = min(
            len(compiler_nodes) - 1,
            int(observation.mission_progress * len(compiler_nodes)),
        )
    for index, node in enumerate(compiler_nodes):
        if index < completed_count:
            node.status = "completed"
        elif index == completed_count:
            node.status = "blocked" if decision.action != "continue" else "active"
        else:
            node.status = "pending"

    entity_ids: set[str] = set()
    anchor = next(
        (node.task_id for node in reversed(compiler_nodes) if node.status == "completed"),
        compiler_nodes[0].task_id,
    )
    for entity in entities:
        suffix = _runtime_track_suffix(entity.track_id)
        entity_ids.add(suffix)
        hold_id = f"runtime-hold-{suffix}"
        replan_id = f"runtime-replan-{suffix}"
        hold = next((node for node in nodes if node.task_id == hold_id), None)
        if hold is None:
            hold = MissionTaskNode(
                task_id=hold_id,
                label=f"Protect the safety envelope around tracked {entity.kind} {entity.track_id}",
                status="active" if decision.action == "hold" else "completed",
                depends_on=[anchor],
                executor="mission_executive",
                risk="critical" if entity.kind == "person" else "high",
                max_retries=0,
                timeout_s=120.0,
                fallback="land",
                expected_output="Clearance restored or a bounded alternative corridor selected",
                completion_evidence=["entity.track", "entity.range", "safety.decision"],
                inserted_by="runtime",
            )
            nodes.append(hold)
        else:
            hold.status = "active" if decision.action == "hold" else "completed"
        replan = next((node for node in nodes if node.task_id == replan_id), None)
        if replan is None:
            replan = MissionTaskNode(
                task_id=replan_id,
                label=(
                    f"Repair the local corridor around {entity.track_id} and rejoin "
                    "the mission graph"
                ),
                status=(
                    "blocked"
                    if decision.action == "hold"
                    else ("active" if observation.local_replan_active else "completed")
                ),
                depends_on=[hold_id],
                executor="local_planner",
                risk="high",
                max_retries=3,
                timeout_s=20.0,
                fallback="hold",
                expected_output=(
                    "A collision-checked trajectory revision inside the approved corridor"
                ),
                completion_evidence=["trajectory.revision", "clearance.minimum", "planner.receipt"],
                inserted_by="runtime",
            )
            nodes.append(replan)
        else:
            replan.status = (
                "blocked"
                if decision.action == "hold"
                else ("active" if observation.local_replan_active else "completed")
            )

    for node in nodes:
        if node.inserted_by != "runtime":
            continue
        suffix = node.task_id.removeprefix("runtime-hold-").removeprefix("runtime-replan-")
        if suffix in entity_ids:
            continue
        node.status = "completed"

    active = [node.task_id for node in nodes if node.status == "active"][:MAX_ACTIVE_TASK_NODES]
    signature_before = [(node.task_id, node.status) for node in graph.nodes]
    signature_after = [(node.task_id, node.status) for node in nodes]
    changed = signature_after != signature_before
    if entity_ids:
        reason = "dynamic entities updated the executable task graph"
    elif decision.action != "continue":
        reason = f"safety supervisor selected {decision.action}"
    elif changed:
        reason = "mission progress advanced compiler tasks"
    else:
        reason = graph.change_reason
    return MissionTaskGraph(
        revision=graph.revision + (1 if changed else 0),
        nodes=nodes,
        active_node_ids=active,
        change_reason=reason,
    )


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
            "safe_operator_commands": ["hold", "resume-if-safe", "abort"],
            "dynamic_task_graph": True,
            "tracked_entity_contract": True,
            "perception_stream_health_contract": True,
        }

    def create(
        self,
        owner_id: str,
        request: RuntimeSessionCreateRequest,
        *,
        planner_receipt: VerifiedPlannerArtifactReceipt | None = None,
    ) -> RuntimeSession:
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
                if (
                    existing.result.contract_id != compiled.contract.contract_id
                    or existing.planner_receipt != planner_receipt
                ):
                    raise AutonomyRuntimeError(
                        "AUTONOMY_RUNTIME_IDEMPOTENCY_CONFLICT",
                        "client_request_id was already used for another mission contract.",
                    )
                return existing.result.model_copy(deep=True)
            self._make_room()
            session_id = (
                "runtime-"
                + _hash([owner_id, request.client_request_id, compiled.contract.contract_id])[:24]
            )
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
                task_graph=compiled.contract.task_graph.model_copy(deep=True),
                perceived_entities=[],
                stream_health=[],
                decision_events=[
                    RuntimeDecisionEvent(
                        revision=1,
                        created_at=now,
                        kind="session",
                        code="runtime.session-created",
                        summary=(
                            "Simulation supervision session created without hardware authority."
                        ),
                        task_ids=compiled.contract.task_graph.active_node_ids,
                    )
                ],
                evidence_chain_head=chain_head,
                terminal=False,
            )
            self._records[session_id] = _SessionRecord(
                owner_id=owner_id,
                client_request_id=request.client_request_id,
                vehicle=request.mission.vehicle.model_copy(deep=True),
                mission=request.model_copy(deep=True),
                planner_receipt=planner_receipt,
                result=session,
            )
            self._idempotency[idempotency_key] = session_id
            return session.model_copy(deep=True)

    def get(self, owner_id: str, session_id: str) -> RuntimeSession:
        with self._lock:
            record = self._owned(owner_id, session_id)
            return record.result.model_copy(deep=True)

    def execution_binding(
        self,
        owner_id: str,
        session_id: str,
    ) -> tuple[
        RuntimeSession,
        RuntimeSessionCreateRequest,
        VerifiedPlannerArtifactReceipt | None,
    ]:
        """Return the owner-scoped runtime session and immutable launch request."""

        with self._lock:
            record = self._owned(owner_id, session_id)
            return (
                record.result.model_copy(deep=True),
                record.mission.model_copy(deep=True),
                record.planner_receipt,
            )

    @contextmanager
    def simulation_launch_binding(
        self,
        owner_id: str,
        session_id: str,
    ) -> Iterator[
        tuple[
            RuntimeSession,
            RuntimeSessionCreateRequest,
            VerifiedPlannerArtifactReceipt | None,
        ]
    ]:
        """Hold the session lock while a ready session crosses the launch boundary."""

        with self._lock:
            record = self._owned(owner_id, session_id)
            current = record.result
            if current.terminal or current.phase != "ready":
                raise AutonomyRuntimeError(
                    "AUTONOMY_RUNTIME_NOT_LAUNCHABLE",
                    "Only a ready, nonterminal runtime session can launch the simulator.",
                )
            yield (
                current.model_copy(deep=True),
                record.mission.model_copy(deep=True),
                record.planner_receipt,
            )

    def finalize_simulation(
        self,
        owner_id: str,
        session_id: str,
        *,
        verified: bool,
        evidence_sha256: str | None,
        failure: str | None,
    ) -> RuntimeSession:
        """Seal a physical simulator result into the runtime evidence chain."""

        with self._lock:
            record = self._owned(owner_id, session_id)
            current = record.result
            if current.terminal:
                return current.model_copy(deep=True)
            now = _now()
            code = "runtime.simulation-verified" if verified else "runtime.simulation-failed"
            summary = (
                "PX4/Gazebo mission evidence passed every physical qualification gate."
                if verified
                else f"PX4/Gazebo mission failed closed: {(failure or 'unknown failure')[:180]}"
            )
            task_graph = current.task_graph.model_copy(deep=True)
            if verified:
                task_graph = task_graph.model_copy(
                    update={
                        "nodes": [
                            node.model_copy(update={"status": "completed"})
                            for node in task_graph.nodes
                        ],
                        "active_node_ids": [],
                        "change_reason": "physical_simulation_verified",
                    }
                )
            revision = current.decision_events[-1].revision + 1
            event = RuntimeDecisionEvent(
                revision=revision,
                created_at=now,
                kind="session",
                code=code,
                summary=summary,
                task_ids=[node.task_id for node in task_graph.nodes[:MAX_ACTIVE_TASK_NODES]],
            )
            record.result = current.model_copy(
                update={
                    "phase": "completed" if verified else "aborted",
                    "updated_at": now,
                    "decision": SafetyDecision(
                        action="continue" if verified else "abort",
                        accepted=verified,
                        codes=[code],
                    ),
                    "task_graph": task_graph,
                    "decision_events": [*current.decision_events, event][-100:],
                    "evidence_chain_head": _hash(
                        {
                            "previous": current.evidence_chain_head,
                            "event": code,
                            "mission_evidence_sha256": evidence_sha256,
                        }
                    ),
                    "terminal": True,
                }
            )
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
            task_graph = _advance_task_graph(current.task_graph, observation, decision)
            all_entity_ids = [entity.track_id for entity in _dynamic_entities(observation)]
            entity_ids = all_entity_ids[:32]
            event_kind: RuntimeDecisionKind = (
                "dynamic_entity"
                if entity_ids
                else ("safety" if decision.action != "continue" else "task_transition")
            )
            event_code = decision.codes[0]
            event_summary = (
                f"Tracked {len(all_entity_ids)} dynamic entities and selected {decision.action}."
                if all_entity_ids
                else f"Task graph revision {task_graph.revision}; safety action {decision.action}."
            )
            decision_events = [
                *current.decision_events,
                RuntimeDecisionEvent(
                    revision=_next_decision_revision(current.decision_events),
                    created_at=_now(),
                    kind=event_kind,
                    code=event_code,
                    summary=event_summary,
                    task_ids=task_graph.active_node_ids,
                    entity_ids=entity_ids,
                ),
            ][-100:]
            chain_head = _hash(
                {
                    "previous": current.evidence_chain_head,
                    "observation": observation.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                    "phase": phase,
                    "task_graph": task_graph.model_dump(mode="json"),
                    "perceived_entities": [
                        entity.model_dump(mode="json") for entity in observation.perceived_entities
                    ],
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
                    "task_graph": task_graph,
                    "perceived_entities": observation.perceived_entities,
                    "stream_health": observation.stream_health,
                    "decision_events": decision_events,
                    "evidence_chain_head": chain_head,
                    "terminal": phase in {"completed", "aborted"},
                },
            )
            record.last_observation = observation.model_copy(deep=True)
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
            if command.action == "resume":
                if current.phase != "holding" or record.last_observation is None:
                    raise AutonomyRuntimeError(
                        "AUTONOMY_RUNTIME_RESUME_NOT_AVAILABLE",
                        "Resume requires a held session with a current observation.",
                    )
                rechecked = _safety_decision(
                    record.last_observation,
                    vehicle=record.vehicle,
                    previous_monotonic_ms=record.last_observation.monotonic_ms,
                )
                if rechecked.action != "continue":
                    raise AutonomyRuntimeError(
                        "AUTONOMY_RUNTIME_RESUME_UNSAFE",
                        "The latest observation still requires a safety hold.",
                    )
                phase = _next_phase(record.last_observation, rechecked)
                decision = SafetyDecision(
                    action="continue",
                    accepted=True,
                    codes=["operator.resume-safe"],
                )
                task_graph = _advance_task_graph(
                    current.task_graph,
                    record.last_observation,
                    decision,
                )
            else:
                phase = "holding" if command.action == "hold" else "aborted"
                decision = SafetyDecision(
                    action=command.action,
                    accepted=True,
                    codes=[f"operator.{command.action}"],
                )
                task_graph = current.task_graph.model_copy(deep=True)
                for node in task_graph.nodes:
                    if node.status == "active":
                        node.status = "blocked"
                task_graph.active_node_ids = []
                task_graph.revision += 1
                task_graph.change_reason = f"operator selected {command.action}"
            event = RuntimeDecisionEvent(
                revision=_next_decision_revision(current.decision_events),
                created_at=_now(),
                kind="operator",
                code=f"operator.{command.action}",
                summary=command.reason,
                task_ids=task_graph.active_node_ids,
            )
            record.result = current.model_copy(
                deep=True,
                update={
                    "phase": phase,
                    "updated_at": _now(),
                    "decision": decision,
                    "task_graph": task_graph,
                    "decision_events": [*current.decision_events, event][-100:],
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
