from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import app.autonomy.simulation_execution as simulation_execution_module
from app.autonomy.credentials import (
    VerifiedAutonomyAssetReceipt,
    fixed_adapter_vehicle_identity_sha256,
)
from app.autonomy.models import (
    AutonomyCompileRequest,
    RuntimeOperatorCommand,
    RuntimeSessionCreateRequest,
    SimulationExecutionStartRequest,
)
from app.autonomy.planner_artifact import VerifiedPlannerArtifactReceipt
from app.autonomy.qualification import VehiclePackQualificationRequest, qualify_vehicle_pack
from app.autonomy.runtime import AutonomyRuntimeError, RuntimeSessionRegistry
from app.autonomy.simulation_execution import SimulationExecutionRegistry


def _mission() -> AutonomyCompileRequest:
    return AutonomyCompileRequest.model_validate(
        {
            "edition": "sim",
            "execution_target": "simulation",
            "natural_language": (
                "Fly from the office to the takeout pickup, attach the payload, "
                "and return to the office."
            ),
            "scene_id": "school-campus-v1",
            "perception_mode": "fusion",
            "vehicle": {
                "dry_mass_kg": 2.0643076923076924,
                "launch_payload_kg": 0.0,
                "pickup_payload_kg": 0.10,
                "max_takeoff_mass_kg": 2.164307692307692,
                "max_total_thrust_n": 34.19432,
                "radius_m": 0.38,
                "max_speed_mps": 4.0,
                "max_acceleration_mps2": 2.5,
                "reserve_battery_percent": 30.0,
            },
            "asset_context": {
                "schema_version": "dronedream.autonomy.compile-assets.v1",
                "harness_context_sha256": "a" * 64,
                "aircraft": {
                    "kind": "aircraft",
                    "asset_id": "aircraft-my-drone",
                    "name": "My Drone",
                    "version": 1,
                    "status": "validated-unsigned",
                    "content_hash": "b" * 64,
                    "qualification_receipt_id": "vehicle-receipt-test",
                    "capabilities": {
                        "body_radius_m": 0.38,
                        "dry_mass_kg": 2.0643076923076924,
                        "maximum_takeoff_mass_kg": 2.164307692307692,
                        "maximum_thrust_n": 34.19432,
                        "maximum_pickup_payload_kg": 0.10,
                        "maximum_speed_mps": 4.0,
                        "maximum_acceleration_mps2": 2.5,
                        "reserve_battery_percent": 30.0,
                        "localization_sources": ["gps"],
                    },
                },
                "map_pack": {
                    "kind": "map",
                    "asset_id": "map-school",
                    "name": "School Map",
                    "version": 1,
                    "status": "qualified",
                    "content_hash": "c" * 64,
                    "qualification_receipt_id": "map-receipt-test",
                    "capabilities": {},
                },
                "planner_binding": {
                    "schema_version": "dronedream.autonomy.planner-binding.v1",
                    "status": "draft",
                    "run_id": "planner-run-school-map-001",
                    "provider": "test",
                    "model": "test-model",
                    "artifact_sha256": "d" * 64,
                    "goal": "Office to takeout pickup and return.",
                    "aircraft_id": "aircraft-my-drone",
                    "aircraft_version": 1,
                    "map_id": "map-school",
                    "map_version": 1,
                    "context_sha256": "a" * 64,
                    "task_graph": {
                        "nodes": [
                            {
                                "node_id": "takeoff",
                                "action": "takeoff",
                                "target": "office-drone-launch-pad",
                                "depends_on": [],
                                "success_evidence": ["airborne telemetry"],
                            },
                            {
                                "node_id": "pickup",
                                "action": "pickup",
                                "target": "takeout-pickup",
                                "depends_on": ["takeoff"],
                                "success_evidence": ["payload joint attached"],
                            },
                            {
                                "node_id": "return",
                                "action": "return",
                                "target": "office-drone-launch-pad",
                                "depends_on": ["pickup"],
                                "success_evidence": ["office return reached"],
                            },
                            {
                                "node_id": "land",
                                "action": "land",
                                "target": "office-drone-launch-pad",
                                "depends_on": ["return"],
                                "success_evidence": ["landed telemetry"],
                            },
                        ]
                    },
                },
            },
        }
    )


def test_installed_run_root_stays_under_the_service_owned_artifact_directory() -> None:
    assert Path("/var/lib/dronedream/artifacts/autonomy-runs") == (
        simulation_execution_module.POSIX_AUTONOMY_RUN_ROOT
    )


@pytest.mark.parametrize(
    "value",
    ([True, 0.0, 0.0], [float("nan"), 0.0, 0.0], [float("inf"), 0.0, 0.0]),
)
def test_live_pose_parser_rejects_nonfinite_or_boolean_coordinates(value: list[object]) -> None:
    assert SimulationExecutionRegistry._vector(value) is None


class _FakeProcess:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self._done = threading.Event()
        self._return_code = 0

    def poll(self) -> int | None:
        return self._return_code if self._done.is_set() else None

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise TimeoutError("fake simulation process did not finish")
        return self._return_code

    def finish(self, return_code: int = 0) -> None:
        self._return_code = return_code
        self._done.set()


def _registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[SimulationExecutionRegistry, RuntimeSessionRegistry, list[_FakeProcess]]:
    processes: list[_FakeProcess] = []

    def fake_popen(argv: list[str], **_: Any) -> _FakeProcess:
        process = _FakeProcess(argv)
        processes.append(process)
        return process

    monkeypatch.setattr(simulation_execution_module, "_run_root", lambda: tmp_path)
    monkeypatch.setattr(simulation_execution_module.subprocess, "Popen", fake_popen)
    sessions = RuntimeSessionRegistry(max_sessions=4)
    registry = SimulationExecutionRegistry(sessions, max_executions=4)
    monkeypatch.setattr(
        registry,
        "capabilities",
        lambda: {"available": True},
    )
    return registry, sessions, processes


def _start_request(session_id: str, contract_id: str) -> SimulationExecutionStartRequest:
    return SimulationExecutionStartRequest(
        runtime_session_id=session_id,
        contract_id=contract_id,
        planner_artifact_sha256="d" * 64,
        client_request_id="simulation-request-001",
        operator_confirmed=True,
    )


def _create_session(
    sessions: RuntimeSessionRegistry,
    owner_id: str,
    request: RuntimeSessionCreateRequest,
):
    assets = request.mission.asset_context
    assert assets is not None
    planner = assets.planner_binding
    assert planner is not None
    return sessions.create(
        owner_id,
        request,
        planner_receipt=VerifiedPlannerArtifactReceipt(
            owner_subject=owner_id,
            run_id=planner.run_id,
            provider=planner.provider,
            model=planner.model,
            artifact_sha256=planner.artifact_sha256,
        ),
        asset_receipt=VerifiedAutonomyAssetReceipt(
            owner_id=owner_id,
            aircraft_receipt_id=assets.aircraft.qualification_receipt_id or "",
            aircraft_content_sha256=assets.aircraft.content_hash or "",
            aircraft_fixed_adapter_identity_sha256=(
                simulation_execution_module.CANONICAL_FIXED_ADAPTER_VEHICLE_IDENTITY_SHA256
            ),
            map_receipt_id=assets.map_pack.qualification_receipt_id or "",
            map_content_sha256=assets.map_pack.content_hash or "",
        ),
    )


def test_simulation_execution_is_model_bound_owner_scoped_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-001"),
    )
    request = _start_request(session.session_id, session.contract_id)

    created = registry.start("owner-a", request)
    repeated = registry.start("owner-a", request)

    assert repeated.execution_id == created.execution_id
    assert len(processes) == 1
    assert processes[0].argv[1].endswith("school_map_px4_mission.py")
    assert "--run-dir" in processes[0].argv
    assert processes[0].argv[processes[0].argv.index("--velocity-m-s") + 1] == "1.2"
    assert processes[0].argv[processes[0].argv.index("--acceleration-m-s2") + 1] == "0.8"
    assert _mission().natural_language not in processes[0].argv
    with pytest.raises(AutonomyRuntimeError) as hidden:
        registry.get("owner-b", created.execution_id)
    assert hidden.value.status_code == 404

    processes[0].finish(1)


def test_simulation_execution_requires_a_server_verified_planner_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = sessions.create(
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=_mission(),
            client_request_id="runtime-request-unverified-planner",
        ),
    )

    with pytest.raises(AutonomyRuntimeError) as rejected:
        registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    assert rejected.value.code == "SIMULATION_PLANNER_RECEIPT_REQUIRED"
    assert rejected.value.status_code == 403
    assert processes == []


def test_simulation_execution_rejects_conflicting_idempotency_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    first = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-idem-a"),
    )
    second = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-idem-b"),
    )
    first_request = _start_request(first.session_id, first.contract_id)
    registry.start("owner-a", first_request)

    with pytest.raises(AutonomyRuntimeError) as conflict:
        registry.start(
            "owner-a",
            first_request.model_copy(update={"runtime_session_id": second.session_id}),
        )

    assert conflict.value.code == "SIMULATION_EXECUTION_IDEMPOTENCY_CONFLICT"
    assert len(processes) == 1
    processes[0].finish(1)


@pytest.mark.parametrize("action", ["hold", "abort"])
def test_simulation_execution_rejects_nonlaunchable_runtime_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=_mission(),
            client_request_id=f"runtime-request-{action}-before-launch",
        ),
    )
    sessions.command(
        "owner-a",
        session.session_id,
        RuntimeOperatorCommand.model_validate(
            {"action": action, "reason": f"operator selected {action} before launch"}
        ),
    )

    with pytest.raises(AutonomyRuntimeError) as blocked:
        registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    assert blocked.value.code == "AUTONOMY_RUNTIME_NOT_LAUNCHABLE"
    assert processes == []


def test_live_pose_and_signed_final_evidence_come_from_runner_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-002"),
    )
    created = registry.start("owner-a", _start_request(session.session_id, session.contract_id))
    run_dir = next(tmp_path.rglob(created.execution_id), None)
    if run_dir is None:
        run_dir = next(tmp_path.iterdir()) / created.execution_id
        run_dir.mkdir()
    (run_dir / "mission_live_status.json").write_text(
        json.dumps(
            {
                "progress": 0.5,
                "phase": "pickup",
                "vehicle_model_root_world_enu_m": [48.5, 1.5, 1.03],
                "vehicle_envelope_center_world_enu_m": [48.5, 1.5, 1.258],
                "vehicle_speed_m_s": 1.25,
                "payload_spawned": True,
                "payload_attached": True,
                "abort_reason": None,
            }
        ),
        encoding="utf-8",
    )

    live = registry.get("owner-a", created.execution_id)
    assert live.state == "running"
    assert live.progress == pytest.approx(0.5)
    assert live.vehicle_envelope_center_world_enu_m is not None
    assert live.vehicle_envelope_center_world_enu_m.z == pytest.approx(1.258)
    assert live.vehicle_speed_m_s == pytest.approx(1.25)
    assert live.payload_attached is True

    (run_dir / "mission_evidence.json").write_text(
        json.dumps(
            {
                "status": "verified",
                "pose_sample_count": 1234,
                "gates": {
                    "physical_payload_spawned": True,
                    "physical_payload_attached": True,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    processes[0].finish(0)
    deadline = time.monotonic() + 2
    final = registry.get("owner-a", created.execution_id)
    while final.state not in {"verified", "failed", "aborted"} and time.monotonic() < deadline:
        time.sleep(0.01)
        final = registry.get("owner-a", created.execution_id)

    assert final.state == "verified"
    assert final.progress == pytest.approx(1.0)
    assert final.mission_evidence_sha256 is not None
    assert final.mission_evidence == {
        "gates": {
            "physical_payload_attached": True,
            "physical_payload_spawned": True,
        },
        "pose_sample_count": 1234,
        "status": "verified",
    }
    sealed_session = sessions.get("owner-a", session.session_id)
    assert sealed_session.terminal is True
    assert sealed_session.phase == "completed"
    assert sealed_session.decision.codes == ["runtime.simulation-verified"]
    assert sealed_session.evidence_chain_head != session.evidence_chain_head


def test_operator_abort_writes_bounded_runner_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_replace = Path.replace
    replace_paths: list[tuple[Path, Path]] = []

    def observe_replace(source: Path, target: Path) -> Path:
        if source.name.endswith(".live-abort.pending"):
            replace_paths.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", observe_replace)
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-003"),
    )
    created = registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    aborting = registry.abort("owner-a", created.execution_id, "Operator requested stop")
    abort_request = next(tmp_path.rglob("live_abort.request.json"))
    payload = json.loads(abort_request.read_text(encoding="utf-8"))

    assert aborting.state == "aborting"
    assert payload["reason"] == "operator_abort: Operator requested stop"
    assert payload["world_paused"] is False
    assert len(replace_paths) == 1
    pending_path, observed_abort_path = replace_paths[0]
    assert pending_path.parent == observed_abort_path.parent.parent
    assert pending_path.parent != observed_abort_path.parent
    assert not list(tmp_path.rglob("*.pending"))
    processes[0].finish(1)


@pytest.mark.parametrize("action", ["hold", "abort"])
def test_runtime_operator_control_stops_an_active_simulator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=_mission(),
            client_request_id=f"runtime-request-active-{action}",
        ),
    )
    created = registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    sessions.command(
        "owner-a",
        session.session_id,
        RuntimeOperatorCommand.model_validate(
            {"action": action, "reason": f"operator selected {action}"}
        ),
    )
    abort_request = next(tmp_path.rglob("live_abort.request.json"), None)
    deadline = time.monotonic() + 2
    while abort_request is None and time.monotonic() < deadline:
        time.sleep(0.01)
        abort_request = next(tmp_path.rglob("live_abort.request.json"), None)

    assert abort_request is not None
    payload = json.loads(abort_request.read_text(encoding="utf-8"))
    assert payload["reason"].startswith("runtime_control_abort: runtime_session_")
    assert registry.get("owner-a", created.execution_id).state == "aborting"
    processes[0].finish(1)


def test_spawn_failure_cleans_owned_artifacts_and_allows_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    original_popen = simulation_execution_module.subprocess.Popen
    attempts = 0

    def fail_once(argv: list[str], **kwargs: Any):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("transient spawn failure")
        return original_popen(argv, **kwargs)

    monkeypatch.setattr(simulation_execution_module.subprocess, "Popen", fail_once)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=_mission(),
            client_request_id="runtime-request-spawn-retry",
        ),
    )
    request = _start_request(session.session_id, session.contract_id)

    with pytest.raises(OSError, match="transient spawn failure"):
        registry.start("owner-a", request)

    assert not list(tmp_path.rglob("*.log"))
    assert not list(tmp_path.rglob("simexec-*"))
    created = registry.start("owner-a", request)
    assert created.state == "starting"
    assert attempts == 2
    assert len(processes) == 1
    processes[0].finish(1)


def test_log_open_failure_cleans_owned_artifacts_and_allows_safe_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    original_open = Path.open
    attempts = 0

    def fail_stderr_once(path: Path, *args: Any, **kwargs: Any):
        nonlocal attempts
        if path.name.endswith(".stderr.log") and attempts == 0:
            attempts += 1
            raise OSError("transient log open failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_stderr_once)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=_mission(),
            client_request_id="runtime-request-log-open-retry",
        ),
    )
    request = _start_request(session.session_id, session.contract_id)

    with pytest.raises(OSError, match="transient log open failure"):
        registry.start("owner-a", request)

    assert not list(tmp_path.rglob("*.log"))
    assert not list(tmp_path.rglob("simexec-*"))
    created = registry.start("owner-a", request)
    assert created.state == "starting"
    assert attempts == 1
    assert len(processes) == 1
    processes[0].finish(1)


def test_contract_or_planner_digest_mismatch_never_starts_a_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-004"),
    )
    request = _start_request(session.session_id, "contract-mismatch")

    with pytest.raises(AutonomyRuntimeError, match="contract changed"):
        registry.start("owner-a", request)
    assert processes == []


def test_verified_runner_cannot_override_an_already_aborted_runtime_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-race"),
    )
    created = registry.start(
        "owner-a",
        SimulationExecutionStartRequest(
            runtime_session_id=session.session_id,
            contract_id=session.contract_id,
            planner_artifact_sha256="d" * 64,
            client_request_id="simulation-request-race",
            operator_confirmed=True,
        ),
    )
    run_dir = next(tmp_path.rglob(created.execution_id), None)
    if run_dir is None:
        run_dir = next(tmp_path.iterdir()) / created.execution_id
        run_dir.mkdir()
    (run_dir / "mission_evidence.json").write_text(
        json.dumps({"status": "verified", "gates": {"all": True}}),
        encoding="utf-8",
    )
    sessions.command(
        "owner-a",
        session.session_id,
        RuntimeOperatorCommand(action="abort", reason="operator stopped runtime"),
    )

    processes[0].finish(0)
    deadline = time.monotonic() + 2
    final = registry.get("owner-a", created.execution_id)
    while final.state not in {"verified", "failed", "aborted"} and time.monotonic() < deadline:
        time.sleep(0.01)
        final = registry.get("owner-a", created.execution_id)

    assert final.state == "aborted"
    assert final.abort_reason == (
        "runtime evidence finalization did not seal the verified simulation"
    )
    assert sessions.get("owner-a", session.session_id).phase == "aborted"


def test_execution_abort_cannot_be_overwritten_by_late_verified_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=_mission(), client_request_id="runtime-request-abort"),
    )
    created = registry.start(
        "owner-a",
        _start_request(session.session_id, session.contract_id),
    )
    run_dir = next(tmp_path.rglob(created.execution_id))
    (run_dir / "mission_evidence.json").write_text(
        json.dumps({"status": "verified", "gates": {"all": True}}),
        encoding="utf-8",
    )

    registry.abort("owner-a", created.execution_id, "operator stopped execution")
    (run_dir / "mission_live_status.json").write_text(
        json.dumps({"progress": 0.9, "phase": "return", "abort_reason": None}),
        encoding="utf-8",
    )
    assert registry.get("owner-a", created.execution_id).state == "aborting"
    processes[0].finish(0)

    deadline = time.monotonic() + 2
    final = registry.get("owner-a", created.execution_id)
    while final.state not in {"verified", "failed", "aborted"} and time.monotonic() < deadline:
        time.sleep(0.01)
        final = registry.get("owner-a", created.execution_id)

    assert final.state == "aborted"
    assert final.abort_reason == "operator_abort: operator stopped execution"
    assert sessions.get("owner-a", session.session_id).phase == "aborted"


def test_fixed_runner_obeys_lower_qualified_motion_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    mission_payload = _mission().model_dump(mode="json")
    mission_payload["vehicle"]["max_speed_mps"] = 0.4
    mission_payload["vehicle"]["max_acceleration_mps2"] = 0.3
    capabilities = mission_payload["asset_context"]["aircraft"]["capabilities"]
    capabilities["maximum_speed_mps"] = 0.4
    capabilities["maximum_acceleration_mps2"] = 0.3
    mission = AutonomyCompileRequest.model_validate(mission_payload)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(mission=mission, client_request_id="runtime-request-slow"),
    )

    registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    argv = processes[0].argv
    assert argv[argv.index("--velocity-m-s") + 1] == "0.4"
    assert argv[argv.index("--acceleration-m-s2") + 1] == "0.3"
    processes[0].finish(1)


def test_fixed_runner_rejects_a_server_verified_noncanonical_vehicle_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    mission = _mission()
    assets = mission.asset_context
    assert assets is not None
    planner = assets.planner_binding
    assert planner is not None
    session = sessions.create(
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=mission,
            client_request_id="runtime-request-noncanonical-fixed-identity",
        ),
        planner_receipt=VerifiedPlannerArtifactReceipt(
            owner_subject="owner-a",
            run_id=planner.run_id,
            provider=planner.provider,
            model=planner.model,
            artifact_sha256=planner.artifact_sha256,
        ),
        asset_receipt=VerifiedAutonomyAssetReceipt(
            owner_id="owner-a",
            aircraft_receipt_id=assets.aircraft.qualification_receipt_id or "",
            aircraft_content_sha256=assets.aircraft.content_hash or "",
            aircraft_fixed_adapter_identity_sha256="f" * 64,
            map_receipt_id=assets.map_pack.qualification_receipt_id or "",
            map_content_sha256=assets.map_pack.content_hash or "",
        ),
    )

    with pytest.raises(AutonomyRuntimeError) as rejected:
        registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    assert rejected.value.code == "SIMULATION_ASSET_PROFILE_MISMATCH"
    assert processes == []


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("firmware", "PX4 v1.17"),
        ("control_interface", "mavlink"),
        ("body_size_m", {"x": 0.4, "y": 0.36, "z": 0.33}),
        ("center_of_gravity_m", {"x": 0.01, "y": 0.0, "z": -0.018}),
        ("inertia_kg_m2", {"x": 0.04, "y": 0.035, "z": 0.061}),
        ("battery_energy_wh", 80.0),
        ("maximum_climb_mps", 1.6),
        ("maximum_tilt_deg", 32.0),
    ),
)
def test_fixed_adapter_identity_binds_every_nonoverridable_vehicle_field(
    field: str,
    value: object,
) -> None:
    canonical = simulation_execution_module.CANONICAL_FIXED_ADAPTER_VEHICLE_REQUEST
    payload = canonical.model_dump(mode="json")
    payload[field] = value
    changed = VehiclePackQualificationRequest.model_validate(payload)

    assert fixed_adapter_vehicle_identity_sha256(changed) != (
        simulation_execution_module.CANONICAL_FIXED_ADAPTER_VEHICLE_IDENTITY_SHA256
    )


def test_fixed_adapter_identity_allows_only_the_supported_motion_limit_overrides() -> None:
    canonical = simulation_execution_module.CANONICAL_FIXED_ADAPTER_VEHICLE_REQUEST
    payload = canonical.model_dump(mode="json")
    payload["maximum_speed_mps"] = 0.4
    payload["maximum_acceleration_mps2"] = 0.3
    slowed = VehiclePackQualificationRequest.model_validate(payload)

    assert fixed_adapter_vehicle_identity_sha256(slowed) == (
        simulation_execution_module.CANONICAL_FIXED_ADAPTER_VEHICLE_IDENTITY_SHA256
    )


def test_official_vehicle_qualification_uses_the_gazebo_collision_envelope() -> None:
    receipt = qualify_vehicle_pack(
        simulation_execution_module.CANONICAL_FIXED_ADAPTER_VEHICLE_REQUEST
    )

    assert receipt.status == "validated_unsigned"
    assert receipt.planning_radius_m == pytest.approx(0.38, abs=1e-12)


def test_noncanonical_assets_or_model_targets_never_start_the_fixed_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    wrong_asset = _mission().model_dump(mode="json")
    wrong_asset["asset_context"]["aircraft"]["asset_id"] = "aircraft-custom"
    wrong_asset["asset_context"]["planner_binding"]["aircraft_id"] = "aircraft-custom"
    asset_session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=AutonomyCompileRequest.model_validate(wrong_asset),
            client_request_id="runtime-request-wrong-asset",
        ),
    )

    with pytest.raises(AutonomyRuntimeError, match="official My Drone"):
        registry.start(
            "owner-a",
            _start_request(asset_session.session_id, asset_session.contract_id),
        )

    wrong_target = _mission().model_dump(mode="json")
    wrong_target["asset_context"]["planner_binding"]["task_graph"]["nodes"][1]["target"] = (
        "cafeteria-counter"
    )
    with pytest.raises(ValueError, match="canonical route targets"):
        AutonomyCompileRequest.model_validate(wrong_target)
    assert processes == []


@pytest.mark.parametrize(
    "natural_language",
    (
        "Fly through every circular training gate and land.",
        "Traverse the narrow stair corridor and dock in the lobby.",
    ),
)
def test_noncoffee_compiler_profiles_cannot_reuse_the_coffee_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    natural_language: str,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    payload = _mission().model_dump(mode="json")
    payload["natural_language"] = natural_language
    mission = AutonomyCompileRequest.model_validate(payload)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=mission,
            client_request_id=f"runtime-request-profile-{len(natural_language)}",
        ),
    )

    with pytest.raises(AutonomyRuntimeError) as rejected:
        registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    assert rejected.value.code == "SIMULATION_ROUTE_PROFILE_MISMATCH"
    assert processes == []


def test_noncoffee_server_planner_goal_cannot_reuse_the_coffee_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    payload = _mission().model_dump(mode="json")
    payload["asset_context"]["planner_binding"]["goal"] = (
        "Inspect every circular training gate and land."
    )
    mission = AutonomyCompileRequest.model_validate(payload)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=mission,
            client_request_id="runtime-request-noncoffee-planner-goal",
        ),
    )

    with pytest.raises(AutonomyRuntimeError) as rejected:
        registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    assert rejected.value.code == "SIMULATION_ROUTE_PROFILE_MISMATCH"
    assert processes == []


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    (
        (
            lambda payload: payload["asset_context"]["planner_binding"]["task_graph"][
                "nodes"
            ].append(
                {
                    "node_id": "detour",
                    "action": "navigate",
                    "target": "cafeteria-counter",
                    "depends_on": ["takeoff"],
                    "success_evidence": ["detour reached"],
                }
            ),
            "SIMULATION_ROUTE_PROFILE_MISMATCH",
        ),
        (
            lambda payload: payload["vehicle"].__setitem__("dry_mass_kg", 2.0),
            "SIMULATION_ASSET_PROFILE_MISMATCH",
        ),
        (
            lambda payload: (
                payload["asset_context"]["aircraft"].__setitem__("version", 2),
                payload["asset_context"]["planner_binding"].__setitem__("aircraft_version", 2),
            ),
            "SIMULATION_ASSET_PROFILE_MISMATCH",
        ),
    ),
)
def test_edited_or_route_extended_profiles_never_start_the_fixed_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
    error_code: str,
) -> None:
    registry, sessions, processes = _registry(monkeypatch, tmp_path)
    payload = _mission().model_dump(mode="json")
    mutation(payload)
    mission = AutonomyCompileRequest.model_validate(payload)
    session = _create_session(
        sessions,
        "owner-a",
        RuntimeSessionCreateRequest(
            mission=mission,
            client_request_id=f"runtime-request-{error_code.casefold()}",
        ),
    )

    with pytest.raises(AutonomyRuntimeError) as rejected:
        registry.start("owner-a", _start_request(session.session_id, session.contract_id))

    assert rejected.value.code == error_code
    assert processes == []
