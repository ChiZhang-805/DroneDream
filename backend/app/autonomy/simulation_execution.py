"""Owner-scoped launcher for the audited School Map PX4/Gazebo mission.

Only the canonical School Map mission runner can be launched.  User input is
never interpolated into a shell command, and a model-bound deterministic
mission contract plus an explicit operator confirmation are required first.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from app.autonomy.models import (
    SimulationExecutionStartRequest,
    SimulationExecutionStatus,
    Vector3,
)
from app.autonomy.px4_x500_vehicle import TAKEOUT_PAYLOAD_MASS_KG
from app.autonomy.runtime import AutonomyRuntimeError, RuntimeSessionRegistry, runtime_sessions

MAX_EXECUTIONS = 32
MAX_JSON_EVIDENCE_BYTES = 4 * 1024 * 1024
POSIX_AUTONOMY_RUN_ROOT = Path("/var/lib/dronedream/artifacts/autonomy-runs")
CANONICAL_AIRCRAFT_ASSET_ID = "aircraft-my-drone"
CANONICAL_MAP_ASSET_ID = "map-school"
CANONICAL_ROUTE_TARGETS = {
    "takeoff": "office-drone-launch-pad",
    "pickup": "takeout-pickup",
    "return": "office-drone-launch-pad",
    "land": "office-drone-launch-pad",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_text(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, maximum_bytes: int = MAX_JSON_EVIDENCE_BYTES) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _runner_path() -> Path:
    installed_candidates = (
        Path("/opt/dronedream/engine/current/scripts/simulators/school_map_px4_mission.py"),
        Path("/opt/dronedream/source/scripts/simulators/school_map_px4_mission.py"),
    )
    for candidate in installed_candidates:
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parents[3] / "scripts/simulators/school_map_px4_mission.py"


def _run_root() -> Path:
    if os.name == "posix":
        # runtime-init creates artifacts as the dronedream service user while
        # /var/lib/dronedream itself remains root-owned and non-writable.
        return POSIX_AUTONOMY_RUN_ROOT
    return Path(__file__).resolve().parents[3] / "artifacts/runtime-executions"


@dataclass
class _ExecutionRecord:
    owner_id: str
    client_request_id: str
    run_dir: Path
    process: subprocess.Popen[str]
    stdout: IO[str]
    stderr: IO[str]
    status: SimulationExecutionStatus


class SimulationExecutionRegistry:
    def __init__(
        self,
        runtime_sessions: RuntimeSessionRegistry,
        *,
        max_executions: int = MAX_EXECUTIONS,
    ) -> None:
        self._runtime_sessions = runtime_sessions
        self._max_executions = max_executions
        self._lock = threading.RLock()
        self._records: OrderedDict[str, _ExecutionRecord] = OrderedDict()
        self._idempotency: dict[tuple[str, str], str] = {}

    def capabilities(self) -> dict[str, object]:
        runner = _runner_path()
        px4 = Path("/opt/PX4-Autopilot/build/px4_sitl_default/bin/px4")
        gazebo = Path("/usr/bin/gz")
        available = os.name == "posix" and runner.is_file() and px4.is_file() and gazebo.is_file()
        return {
            "schema_version": "dronedream.autonomy.simulation-execution-capabilities.v1",
            "available": available,
            "adapter": "school-map-px4-gazebo-mavsdk-v1",
            "world": "School Map",
            "vehicle": "My Drone",
            "mission_profile": "school-map-office-takeout-roundtrip-v1",
            "physical_transport_bound": available,
            "ros2_bound": False,
            "operator_confirmation_required": True,
            "model_planner_binding_required": True,
            "maximum_concurrent_executions": 1,
        }

    def start(
        self,
        owner_id: str,
        request: SimulationExecutionStartRequest,
    ) -> SimulationExecutionStatus:
        session, session_request = self._runtime_sessions.execution_binding(
            owner_id,
            request.runtime_session_id,
        )
        mission = session_request.mission
        planner = mission.asset_context.planner_binding if mission.asset_context else None
        if session.contract_id != request.contract_id:
            raise AutonomyRuntimeError(
                "SIMULATION_CONTRACT_MISMATCH",
                "The confirmed runtime contract changed before simulation launch.",
            )
        if planner is None or planner.artifact_sha256 != request.planner_artifact_sha256:
            raise AutonomyRuntimeError(
                "SIMULATION_PLANNER_BINDING_MISMATCH",
                "The confirmed model planner artifact is missing or changed.",
            )
        assets = mission.asset_context
        if (
            assets is None
            or assets.aircraft.asset_id != CANONICAL_AIRCRAFT_ASSET_ID
            or assets.map_pack.asset_id != CANONICAL_MAP_ASSET_ID
        ):
            raise AutonomyRuntimeError(
                "SIMULATION_ASSET_PROFILE_MISMATCH",
                "The physical adapter requires the official My Drone and School Map assets.",
            )
        bound_targets = {(node.action, node.target) for node in planner.task_graph.nodes}
        if any(
            (action, target) not in bound_targets
            for action, target in CANONICAL_ROUTE_TARGETS.items()
        ):
            raise AutonomyRuntimeError(
                "SIMULATION_ROUTE_PROFILE_MISMATCH",
                "The model plan is not bound to the canonical office-to-takeout roundtrip.",
            )
        if mission.scene_id != "school-campus-v1":
            raise AutonomyRuntimeError(
                "SIMULATION_SCENE_UNSUPPORTED",
                "The physical adapter currently accepts only School Map.",
            )
        if abs(mission.vehicle.pickup_payload_kg - TAKEOUT_PAYLOAD_MASS_KG) > 1e-9:
            raise AutonomyRuntimeError(
                "SIMULATION_PAYLOAD_CONTRACT_MISMATCH",
                "The School Map adapter requires the qualified 0.10 kg payload.",
            )
        capabilities = self.capabilities()
        if capabilities["available"] is not True:
            raise AutonomyRuntimeError(
                "SIMULATION_ADAPTER_UNAVAILABLE",
                "The managed PX4/Gazebo Runtime is not installed or ready.",
                503,
            )
        idempotency_key = (owner_id, request.client_request_id)
        with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                return self._records[existing_id].status.model_copy(deep=True)
            if any(record.process.poll() is None for record in self._records.values()):
                raise AutonomyRuntimeError(
                    "SIMULATION_EXECUTION_BUSY",
                    "Another PX4/Gazebo execution is already running.",
                    503,
                )
            self._make_room()
            execution_id = (
                "simexec-"
                + _sha256_text([owner_id, request.client_request_id, request.contract_id])[:24]
            )
            owner_token = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
            parent = _run_root() / owner_token
            parent.mkdir(parents=True, exist_ok=True)
            run_dir = parent / execution_id
            stdout = (parent / f"{execution_id}.stdout.log").open("w", encoding="utf-8")
            stderr = (parent / f"{execution_id}.stderr.log").open("w", encoding="utf-8")
            argv = [
                str(Path(sys.executable).resolve()),
                str(_runner_path()),
                "--run-dir",
                str(run_dir),
                "--velocity-m-s",
                "1.2",
                "--acceleration-m-s2",
                "0.8",
                "--setpoint-rate-hz",
                "20",
            ]
            process = subprocess.Popen(  # noqa: S603 - fixed executable and fixed runner argv.
                argv,
                cwd=_runner_path().parents[2],
                stdout=stdout,
                stderr=stderr,
                text=True,
                start_new_session=True,
            )
            now = _now()
            status = SimulationExecutionStatus(
                execution_id=execution_id,
                runtime_session_id=session.session_id,
                contract_id=session.contract_id,
                planner_artifact_sha256=planner.artifact_sha256,
                state="starting",
                created_at=now,
                updated_at=now,
                progress=0.0,
                phase="preflight",
            )
            record = _ExecutionRecord(
                owner_id=owner_id,
                client_request_id=request.client_request_id,
                run_dir=run_dir,
                process=process,
                stdout=stdout,
                stderr=stderr,
                status=status,
            )
            self._records[execution_id] = record
            self._idempotency[idempotency_key] = execution_id
            watcher = threading.Thread(
                target=self._watch,
                args=(execution_id,),
                name=f"simulation-execution-{execution_id}",
                daemon=True,
            )
            watcher.start()
            return status.model_copy(deep=True)

    def get(self, owner_id: str, execution_id: str) -> SimulationExecutionStatus:
        with self._lock:
            record = self._owned(owner_id, execution_id)
            self._refresh_live(record)
            return record.status.model_copy(deep=True)

    def abort(self, owner_id: str, execution_id: str, reason: str) -> SimulationExecutionStatus:
        with self._lock:
            record = self._owned(owner_id, execution_id)
            if record.process.poll() is not None:
                return record.status.model_copy(deep=True)
            record.run_dir.mkdir(parents=True, exist_ok=True)
            abort_path = record.run_dir / "live_abort.request.json"
            abort_path.write_text(
                json.dumps(
                    {
                        "schema_version": "dronedream.school-map-live-abort.v1",
                        "reason": f"operator_abort: {reason[:200]}",
                        "world_paused": False,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            record.status = record.status.model_copy(
                update={
                    "state": "aborting",
                    "updated_at": _now(),
                    "abort_reason": reason[:240],
                }
            )
            return record.status.model_copy(deep=True)

    def _refresh_live(self, record: _ExecutionRecord) -> None:
        live = _read_json(record.run_dir / "mission_live_status.json")
        if not live or record.process.poll() is not None:
            return
        root = live.get("vehicle_model_root_world_enu_m")
        center = live.get("vehicle_envelope_center_world_enu_m")
        record.status = record.status.model_copy(
            update={
                "state": "running",
                "updated_at": _now(),
                "progress": self._bounded_progress(live.get("progress")),
                "phase": str(live.get("phase", "running"))[:80],
                "vehicle_model_root_world_enu_m": self._vector(root),
                "vehicle_envelope_center_world_enu_m": self._vector(center),
                "vehicle_speed_m_s": self._bounded_speed(live.get("vehicle_speed_m_s")),
                "payload_spawned": live.get("payload_spawned") is True,
                "payload_attached": live.get("payload_attached") is True,
                "abort_reason": (
                    str(live["abort_reason"])[:240]
                    if live.get("abort_reason") is not None
                    else record.status.abort_reason
                ),
            }
        )

    @staticmethod
    def _bounded_progress(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.0
        progress = float(value)
        if not math.isfinite(progress):
            return 0.0
        return max(0.0, min(1.0, progress))

    @staticmethod
    def _vector(value: object) -> Vector3 | None:
        if (
            not isinstance(value, list)
            or len(value) != 3
            or any(isinstance(component, bool) for component in value)
        ):
            return None
        try:
            components = tuple(float(component) for component in value)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(component) for component in components):
            return None
        return Vector3(x=components[0], y=components[1], z=components[2])

    @staticmethod
    def _bounded_speed(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        speed = float(value)
        return speed if 0.0 <= speed <= 100.0 else None

    def _watch(self, execution_id: str) -> None:
        with self._lock:
            record = self._records[execution_id]
        return_code = record.process.wait()
        record.stdout.close()
        record.stderr.close()
        evidence_path = record.run_dir / "mission_evidence.json"
        evidence = _read_json(evidence_path)
        evidence_sha256 = _sha256_file(evidence_path) if evidence_path.is_file() else None
        verified = return_code == 0 and evidence.get("status") == "verified"
        aborted = record.status.state == "aborting" or (
            isinstance(evidence.get("process_failure"), str)
            and "abort" in str(evidence["process_failure"]).lower()
        )
        failure = str(evidence.get("process_failure")) if evidence.get("process_failure") else None
        try:
            sealed_runtime = self._runtime_sessions.finalize_simulation(
                record.owner_id,
                record.status.runtime_session_id,
                verified=verified,
                evidence_sha256=evidence_sha256,
                failure=failure,
            )
            verified_runtime_seal = (
                sealed_runtime.terminal
                and sealed_runtime.phase == "completed"
                and sealed_runtime.decision.accepted
                and "runtime.simulation-verified" in sealed_runtime.decision.codes
            )
            if verified and not verified_runtime_seal:
                verified = False
                aborted = sealed_runtime.phase == "aborted"
                finalization_error = (
                    "runtime evidence finalization did not seal the verified simulation"
                )
            else:
                finalization_error = None
        except Exception as exc:  # fail closed if the evidence chain cannot be sealed
            finalization_error = (
                f"runtime evidence finalization failed: {type(exc).__name__}: {exc}"
            )
            verified = False
            aborted = False
        with self._lock:
            record.status = record.status.model_copy(
                update={
                    "state": "verified" if verified else "aborted" if aborted else "failed",
                    "updated_at": _now(),
                    "progress": 1.0 if verified else record.status.progress,
                    "phase": "land" if verified else "abort",
                    "payload_spawned": bool(
                        evidence.get("gates", {}).get("physical_payload_spawned")
                        if isinstance(evidence.get("gates"), dict)
                        else record.status.payload_spawned
                    ),
                    "payload_attached": bool(
                        evidence.get("gates", {}).get("physical_payload_attached")
                        if isinstance(evidence.get("gates"), dict)
                        else record.status.payload_attached
                    ),
                    "abort_reason": (
                        finalization_error
                        or (failure[:240] if failure is not None else record.status.abort_reason)
                    ),
                    "mission_evidence_sha256": evidence_sha256,
                    "mission_evidence": evidence or None,
                }
            )

    def _owned(self, owner_id: str, execution_id: str) -> _ExecutionRecord:
        record = self._records.get(execution_id)
        if record is None or record.owner_id != owner_id:
            raise AutonomyRuntimeError(
                "SIMULATION_EXECUTION_NOT_FOUND",
                "Simulation execution not found.",
                404,
            )
        return record

    def _make_room(self) -> None:
        if len(self._records) < self._max_executions:
            return
        for execution_id, record in self._records.items():
            if record.process.poll() is not None:
                del self._records[execution_id]
                self._idempotency.pop((record.owner_id, record.client_request_id), None)
                return
        raise AutonomyRuntimeError(
            "SIMULATION_EXECUTION_CAPACITY_REACHED",
            "No completed simulation execution can be evicted.",
            503,
        )


simulation_executions = SimulationExecutionRegistry(runtime_sessions)


__all__ = ["SimulationExecutionRegistry", "simulation_executions"]
