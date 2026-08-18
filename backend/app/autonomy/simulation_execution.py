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
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

from app.autonomy.credentials import (
    fixed_adapter_vehicle_identity_sha256,
)
from app.autonomy.models import (
    AutonomyPlannerAction,
    AutonomyPlannerTaskGraph,
    SimulationExecutionStartRequest,
    SimulationExecutionStatus,
    Vector3,
)
from app.autonomy.px4_x500_vehicle import (
    PX4_X500_DRY_MASS_KG,
    PX4_X500_MAXIMUM_THRUST_N,
    TAKEOUT_PAYLOAD_MASS_KG,
)
from app.autonomy.qualification import VehiclePackQualificationRequest
from app.autonomy.runtime import AutonomyRuntimeError, RuntimeSessionRegistry, runtime_sessions
from app.autonomy.school_map_artifact import VEHICLE_COLLISION_DIAMETER_M
from app.autonomy.service import school_mission_profile

MAX_EXECUTIONS = 32
MAX_JSON_EVIDENCE_BYTES = 4 * 1024 * 1024
POSIX_AUTONOMY_RUN_ROOT = Path("/var/lib/dronedream/artifacts/autonomy-runs")
CANONICAL_AIRCRAFT_ASSET_ID = "aircraft-my-drone"
CANONICAL_MAP_ASSET_ID = "map-school"
CANONICAL_ROUTE_TARGETS: dict[AutonomyPlannerAction, str] = {
    "takeoff": "office-drone-launch-pad",
    "pickup": "takeout-pickup",
    "return": "office-drone-launch-pad",
    "land": "office-drone-launch-pad",
}
CANONICAL_AIRCRAFT_VERSION = 1
CANONICAL_MAP_VERSION = 1
FIXED_RUNNER_MAXIMUM_SPEED_M_S = 1.2
FIXED_RUNNER_MAXIMUM_ACCELERATION_M_S2 = 0.8
RUNTIME_CONTROL_POLL_SECONDS = 0.1

CANONICAL_FIXED_ADAPTER_VEHICLE_REQUEST = VehiclePackQualificationRequest.model_validate(
    {
        "pack_id": CANONICAL_AIRCRAFT_ASSET_ID,
        "version": CANONICAL_AIRCRAFT_VERSION,
        "autopilot": "px4",
        "firmware": "PX4 v1.16",
        "flight_controller": "Pixhawk 6C",
        "control_interface": "mavsdk",
        "dry_mass_kg": PX4_X500_DRY_MASS_KG,
        # Keep the exact published Vehicle Pack decimal; its credential hash is
        # content-addressed and therefore stricter than the later numeric gate.
        "max_takeoff_mass_kg": 2.164307692307692,
        "max_total_thrust_n": PX4_X500_MAXIMUM_THRUST_N,
        "body_size_m": {"x": 0.36, "y": 0.36, "z": 0.33},
        "rotor_radius_m": 0.127,
        "center_of_gravity_m": {"x": 0.0, "y": 0.0, "z": -0.018},
        "inertia_kg_m2": {"x": 0.035, "y": 0.035, "z": 0.061},
        "battery_energy_wh": 74.0,
        "reserve_battery_percent": 30.0,
        "maximum_pickup_payload_kg": TAKEOUT_PAYLOAD_MASS_KG,
        "maximum_speed_mps": 4.0,
        "maximum_acceleration_mps2": 2.5,
        "maximum_climb_mps": 1.5,
        "maximum_descent_mps": 1.0,
        "maximum_tilt_deg": 30.0,
        "command_link_latency_ms": 35.0,
        "command_link_bandwidth_mbps": 40.0,
        "sensors": [
            {
                "sensor_id": "gps-primary",
                "kind": "gps",
                "calibrated": True,
                "calibration_status": "verified",
                "position_m": {"x": -0.07, "y": 0.0, "z": 0.2},
                "roll_pitch_yaw_deg": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rate_hz": 10.0,
                "calibration_age_days": 0.0,
            }
        ],
    }
)
CANONICAL_FIXED_ADAPTER_VEHICLE_IDENTITY_SHA256 = fixed_adapter_vehicle_identity_sha256(
    CANONICAL_FIXED_ADAPTER_VEHICLE_REQUEST
)


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


def _same_number(value: object, expected: float, *, tolerance: float = 1e-9) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and math.isclose(float(value), expected, rel_tol=0.0, abs_tol=tolerance)
    )


def _matches_canonical_route_graph(graph: AutonomyPlannerTaskGraph) -> bool:
    if len(graph.nodes) != len(CANONICAL_ROUTE_TARGETS):
        return False
    nodes_by_action = {node.action: node for node in graph.nodes}
    if set(nodes_by_action) != set(CANONICAL_ROUTE_TARGETS):
        return False
    if any(
        nodes_by_action[action].target != target
        for action, target in CANONICAL_ROUTE_TARGETS.items()
    ):
        return False
    takeoff = nodes_by_action["takeoff"]
    pickup = nodes_by_action["pickup"]
    return_node = nodes_by_action["return"]
    land = nodes_by_action["land"]
    return (
        takeoff.depends_on == []
        and pickup.depends_on == [takeoff.node_id]
        and return_node.depends_on == [pickup.node_id]
        and land.depends_on == [return_node.node_id]
    )


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
        (
            session,
            session_request,
            planner_receipt,
            asset_receipt,
        ) = self._runtime_sessions.execution_binding(owner_id, request.runtime_session_id)
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
        if (
            planner_receipt is None
            or planner_receipt.run_id != planner.run_id
            or planner_receipt.provider != planner.provider
            or planner_receipt.model != planner.model
            or planner_receipt.artifact_sha256 != planner.artifact_sha256
        ):
            raise AutonomyRuntimeError(
                "SIMULATION_PLANNER_RECEIPT_REQUIRED",
                "The runtime session has no matching server-verified planner receipt.",
                403,
            )
        assets = mission.asset_context
        vehicle = mission.vehicle
        localization_sources = (
            assets.aircraft.capabilities.get("localization_sources") if assets is not None else None
        )
        if (
            assets is None
            or asset_receipt is None
            or asset_receipt.owner_id != owner_id
            or assets.aircraft.asset_id != CANONICAL_AIRCRAFT_ASSET_ID
            or assets.map_pack.asset_id != CANONICAL_MAP_ASSET_ID
            or assets.aircraft.version != CANONICAL_AIRCRAFT_VERSION
            or assets.map_pack.version != CANONICAL_MAP_VERSION
            or assets.aircraft.content_hash is None
            or assets.aircraft.qualification_receipt_id is None
            or assets.map_pack.content_hash is None
            or assets.map_pack.qualification_receipt_id is None
            or asset_receipt.aircraft_receipt_id != assets.aircraft.qualification_receipt_id
            or asset_receipt.aircraft_content_sha256 != assets.aircraft.content_hash
            or asset_receipt.map_receipt_id != assets.map_pack.qualification_receipt_id
            or asset_receipt.map_content_sha256 != assets.map_pack.content_hash
            or asset_receipt.aircraft_fixed_adapter_identity_sha256
            != CANONICAL_FIXED_ADAPTER_VEHICLE_IDENTITY_SHA256
            or not _same_number(vehicle.dry_mass_kg, PX4_X500_DRY_MASS_KG)
            or not _same_number(vehicle.launch_payload_kg, 0.0)
            or not _same_number(vehicle.pickup_payload_kg, TAKEOUT_PAYLOAD_MASS_KG)
            or not _same_number(
                vehicle.max_takeoff_mass_kg,
                PX4_X500_DRY_MASS_KG + TAKEOUT_PAYLOAD_MASS_KG,
            )
            or not _same_number(vehicle.max_total_thrust_n, PX4_X500_MAXIMUM_THRUST_N)
            or not _same_number(vehicle.radius_m, VEHICLE_COLLISION_DIAMETER_M / 2)
            or not _same_number(
                assets.aircraft.capabilities.get("body_radius_m"),
                VEHICLE_COLLISION_DIAMETER_M / 2,
            )
            or not _same_number(
                assets.aircraft.capabilities.get("dry_mass_kg"),
                PX4_X500_DRY_MASS_KG,
            )
            or not _same_number(
                assets.aircraft.capabilities.get("maximum_takeoff_mass_kg"),
                PX4_X500_DRY_MASS_KG + TAKEOUT_PAYLOAD_MASS_KG,
            )
            or not _same_number(
                assets.aircraft.capabilities.get("maximum_thrust_n"),
                PX4_X500_MAXIMUM_THRUST_N,
            )
            or not _same_number(
                assets.aircraft.capabilities.get("maximum_pickup_payload_kg"),
                TAKEOUT_PAYLOAD_MASS_KG,
            )
            or not _same_number(
                assets.aircraft.capabilities.get("maximum_speed_mps"),
                vehicle.max_speed_mps,
            )
            or vehicle.max_speed_mps > 4.0
            or not _same_number(
                assets.aircraft.capabilities.get("maximum_acceleration_mps2"),
                vehicle.max_acceleration_mps2,
            )
            or vehicle.max_acceleration_mps2 > 2.5
            or not _same_number(vehicle.reserve_battery_percent, 30.0)
            or not _same_number(
                assets.aircraft.capabilities.get("reserve_battery_percent"),
                vehicle.reserve_battery_percent,
            )
            or not isinstance(localization_sources, list)
            or "gps" not in localization_sources
        ):
            raise AutonomyRuntimeError(
                "SIMULATION_ASSET_PROFILE_MISMATCH",
                "The physical adapter requires the official My Drone and School Map assets.",
            )
        if not _matches_canonical_route_graph(planner.task_graph):
            raise AutonomyRuntimeError(
                "SIMULATION_ROUTE_PROFILE_MISMATCH",
                "The model plan is not bound to the canonical office-to-takeout roundtrip.",
            )
        planner_goal_mission = mission.model_copy(update={"natural_language": planner.goal})
        if (
            school_mission_profile(mission, mission.scene_id or "school-campus-v1") != "coffee"
            or school_mission_profile(
                planner_goal_mission,
                planner_goal_mission.scene_id or "school-campus-v1",
            )
            != "coffee"
        ):
            raise AutonomyRuntimeError(
                "SIMULATION_ROUTE_PROFILE_MISMATCH",
                "The compiled mission profile is not the office-to-takeout roundtrip.",
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
                existing = self._records[existing_id]
                if (
                    existing.status.runtime_session_id != request.runtime_session_id
                    or existing.status.contract_id != request.contract_id
                    or existing.status.planner_artifact_sha256 != request.planner_artifact_sha256
                ):
                    raise AutonomyRuntimeError(
                        "SIMULATION_EXECUTION_IDEMPOTENCY_CONFLICT",
                        "client_request_id was already used for another simulation binding.",
                    )
                return existing.status.model_copy(deep=True)
            execution_id = (
                "simexec-"
                + _sha256_text([owner_id, request.client_request_id, request.contract_id])[:24]
            )
            owner_token = hashlib.sha256(owner_id.encode()).hexdigest()[:16]
            parent = _run_root() / owner_token
            run_dir = parent / execution_id
            if run_dir.exists():
                raise AutonomyRuntimeError(
                    "SIMULATION_EXECUTION_ARTIFACT_CONFLICT",
                    "A retained artifact already exists for this simulation request.",
                    409,
                )
            if any(record.process.poll() is None for record in self._records.values()):
                raise AutonomyRuntimeError(
                    "SIMULATION_EXECUTION_BUSY",
                    "Another PX4/Gazebo execution is already running.",
                    503,
                )
            self._make_room()
            runner_speed_m_s = min(FIXED_RUNNER_MAXIMUM_SPEED_M_S, vehicle.max_speed_mps)
            runner_acceleration_m_s2 = min(
                FIXED_RUNNER_MAXIMUM_ACCELERATION_M_S2,
                vehicle.max_acceleration_mps2,
            )
            argv = [
                str(Path(sys.executable).resolve()),
                str(_runner_path()),
                "--run-dir",
                str(run_dir),
                "--velocity-m-s",
                f"{runner_speed_m_s:.12g}",
                "--acceleration-m-s2",
                f"{runner_acceleration_m_s2:.12g}",
                "--setpoint-rate-hz",
                "20",
            ]
            with self._runtime_sessions.simulation_launch_binding(
                owner_id,
                request.runtime_session_id,
            ) as (launch_session, _launch_request, launch_receipt, launch_asset_receipt):
                if launch_session.contract_id != request.contract_id:
                    raise AutonomyRuntimeError(
                        "SIMULATION_CONTRACT_MISMATCH",
                        "The confirmed runtime contract changed before simulation launch.",
                    )
                if launch_receipt != planner_receipt:
                    raise AutonomyRuntimeError(
                        "SIMULATION_PLANNER_RECEIPT_CHANGED",
                        "The verified planner receipt changed before simulation launch.",
                        403,
                    )
                if launch_asset_receipt != asset_receipt:
                    raise AutonomyRuntimeError(
                        "SIMULATION_ASSET_RECEIPT_CHANGED",
                        "The verified autonomy asset receipt changed before simulation launch.",
                        403,
                    )
                parent.mkdir(parents=True, exist_ok=True)
                try:
                    run_dir.mkdir()
                except FileExistsError as exc:
                    raise AutonomyRuntimeError(
                        "SIMULATION_EXECUTION_ARTIFACT_CONFLICT",
                        "A retained artifact already exists for this simulation request.",
                        409,
                    ) from exc
                stdout_path = parent / f"{execution_id}.stdout.log"
                stderr_path = parent / f"{execution_id}.stderr.log"
                stdout: IO[str] | None = None
                stderr: IO[str] | None = None
                try:
                    stdout = stdout_path.open("w", encoding="utf-8")
                    stderr = stderr_path.open("w", encoding="utf-8")
                    process = subprocess.Popen(  # noqa: S603 - fixed executable and fixed runner argv.
                        argv,
                        cwd=_runner_path().parents[2],
                        stdout=stdout,
                        stderr=stderr,
                        text=True,
                        start_new_session=True,
                    )
                except BaseException:
                    for stream in (stdout, stderr):
                        if stream is not None:
                            stream.close()
                    for created_path in (stdout_path, stderr_path):
                        with suppress(OSError):
                            created_path.unlink(missing_ok=True)
                    with suppress(OSError):
                        run_dir.rmdir()
                    raise
                if stdout is None or stderr is None:
                    raise RuntimeError("simulation log streams were not initialized")
            now = _now()
            status = SimulationExecutionStatus(
                execution_id=execution_id,
                runtime_session_id=launch_session.session_id,
                contract_id=launch_session.contract_id,
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
            self._request_abort(record, reason, request_reason=f"operator_abort: {reason[:200]}")
            return record.status.model_copy(deep=True)

    def _request_abort(
        self,
        record: _ExecutionRecord,
        status_reason: str,
        *,
        request_reason: str,
    ) -> None:
        record.run_dir.mkdir(parents=True, exist_ok=True)
        abort_path = record.run_dir / "live_abort.request.json"
        pending_path = record.run_dir.parent / f".{record.status.execution_id}.live-abort.pending"
        try:
            pending_path.write_text(
                json.dumps(
                    {
                        "schema_version": "dronedream.school-map-live-abort.v1",
                        "reason": request_reason[:240],
                        "world_paused": False,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            pending_path.replace(abort_path)
        finally:
            with suppress(OSError):
                pending_path.unlink(missing_ok=True)
        record.status = record.status.model_copy(
            update={
                "state": "aborting",
                "updated_at": _now(),
                "abort_reason": status_reason[:240],
            }
        )

    def _sync_runtime_control(self, record: _ExecutionRecord) -> None:
        try:
            runtime = self._runtime_sessions.get(
                record.owner_id,
                record.status.runtime_session_id,
            )
        except AutonomyRuntimeError as exc:
            runtime_phase = "missing"
            runtime_reason = exc.code
        else:
            runtime_phase = runtime.phase
            runtime_reason = ",".join(runtime.decision.codes[:4])
        if runtime_phase not in {"holding", "landing", "aborted", "missing"}:
            return
        with self._lock:
            if record.process.poll() is not None or record.status.state == "aborting":
                return
            status_reason = f"runtime_session_{runtime_phase}: {runtime_reason}"[:240]
            self._request_abort(
                record,
                status_reason,
                request_reason=f"runtime_control_abort: {status_reason}",
            )

    def _refresh_live(self, record: _ExecutionRecord) -> None:
        live = _read_json(record.run_dir / "mission_live_status.json")
        if not live or record.process.poll() is not None:
            return
        root = live.get("vehicle_model_root_world_enu_m")
        center = live.get("vehicle_envelope_center_world_enu_m")
        aborting = record.status.state == "aborting"
        record.status = record.status.model_copy(
            update={
                "state": "aborting" if aborting else "running",
                "updated_at": _now(),
                "progress": self._bounded_progress(live.get("progress")),
                "phase": str(live.get("phase", "running"))[:80],
                "vehicle_model_root_world_enu_m": self._vector(root),
                "vehicle_envelope_center_world_enu_m": self._vector(center),
                "vehicle_speed_m_s": self._bounded_speed(live.get("vehicle_speed_m_s")),
                "payload_spawned": live.get("payload_spawned") is True,
                "payload_attached": live.get("payload_attached") is True,
                "abort_reason": record.status.abort_reason
                if aborting
                else (
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
        while True:
            try:
                return_code = record.process.wait(timeout=RUNTIME_CONTROL_POLL_SECONDS)
                break
            except (subprocess.TimeoutExpired, TimeoutError):
                self._sync_runtime_control(record)
        record.stdout.close()
        record.stderr.close()
        evidence_path = record.run_dir / "mission_evidence.json"
        evidence = _read_json(evidence_path)
        evidence_sha256 = _sha256_file(evidence_path) if evidence_path.is_file() else None
        verified = return_code == 0 and evidence.get("status") == "verified"
        with self._lock:
            acknowledged_abort_reason = (
                record.status.abort_reason if record.status.state == "aborting" else None
            )
        if acknowledged_abort_reason is not None:
            verified = False
        aborted = acknowledged_abort_reason is not None or (
            isinstance(evidence.get("process_failure"), str)
            and "abort" in str(evidence["process_failure"]).lower()
        )
        failure = str(evidence.get("process_failure")) if evidence.get("process_failure") else None
        if acknowledged_abort_reason is not None:
            failure = f"operator_abort: {acknowledged_abort_reason}"
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
