"""Real PX4 SITL + Gazebo runner for an arbitrary validated track contract."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .collision import _clearance  # same conservative envelope used by static gate
from .contracts import GraphRoute, Px4Track, RouteClearanceReport
from .hashing import sha256_json


class SimulationRuntimeError(RuntimeError):
    """Real runtime could not satisfy an execution or evidence gate."""


def _is_tolerated_landing_contact(
    *, phase: str | None, primitive_name: str, clearance_m: float
) -> bool:
    if phase not in {"LANDING", "LANDED", "COMPLETE"}:
        return False
    if not -0.02 <= clearance_m < -0.001:
        return False
    return any(token in primitive_name.casefold() for token in ("floor", "ground", "road", "pad"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run(
    argv: list[str], *, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _wait_for_world(gz_binary: str, world_name: str, env: dict[str, str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    service = f"/world/{world_name}/scene/info"
    while time.monotonic() < deadline:
        result = _run([gz_binary, "service", "-i", "--service", service], env=env, timeout=5)
        if result.returncode == 0 and "Service providers" in result.stdout:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Gazebo world did not expose {service}")


def _wait_for_vehicle(
    gz_binary: str, vehicle_name: str, env: dict[str, str], timeout: float
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _run([gz_binary, "topic", "-l"], env=env, timeout=5)
        if result.returncode == 0 and vehicle_name in result.stdout:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Gazebo did not expose vehicle {vehicle_name}")


def _spawn_entity(
    gz_binary: str,
    *,
    world_name: str,
    entity_name: str,
    sdf_path: Path,
    pose: tuple[float, float, float],
    env: dict[str, str],
) -> dict[str, object]:
    request = (
        f'sdf_filename: "{sdf_path}" name: "{entity_name}" '
        f"pose {{ position {{ x: {pose[0]:.12g} y: {pose[1]:.12g} z: {pose[2]:.12g} }} }} "
        "allow_renaming: false"
    )
    result = _run(
        [
            gz_binary,
            "service",
            "-s",
            f"/world/{world_name}/create",
            "--reqtype",
            "gz.msgs.EntityFactory",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "5000",
            "--req",
            request,
        ],
        env=env,
        timeout=10,
    )
    accepted = result.returncode == 0 and "data: true" in result.stdout
    evidence = {
        "accepted": accepted,
        "entity_name": entity_name,
        "sdf_path": str(sdf_path),
        "sdf_sha256": _sha256(sdf_path),
        "pose_enu_m": pose,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip()[:1000],
        "stderr": result.stderr.strip()[:1000],
    }
    if not accepted:
        raise SimulationRuntimeError(f"Gazebo rejected vehicle spawn: {evidence}")
    return evidence


def _prepare_rootfs(px4_root: Path, run_dir: Path) -> tuple[Path, Path]:
    build_root = px4_root / "build/px4_sitl_default"
    source_rootfs = build_root / "rootfs"
    executable = build_root / "bin/px4"
    if not source_rootfs.is_dir() or not executable.is_file():
        raise FileNotFoundError("PX4 SITL build is missing rootfs or bin/px4")
    for source in source_rootfs.rglob("*"):
        if not source.is_symlink():
            continue
        try:
            source.resolve(strict=True).relative_to(px4_root)
        except (OSError, ValueError) as exc:
            raise SimulationRuntimeError(f"unsafe PX4 rootfs symlink: {source}") from exc
    destination = run_dir / "px4_rootfs"
    shutil.copytree(
        source_rootfs,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns(
            "dataman", "eeprom", "log", "parameters.bson", "parameters_backup.bson"
        ),
    )
    return destination, executable


def _terminate(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.kill(-process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.kill(-process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except ProcessLookupError:
            return
        process.wait(timeout=5)


def _landing_confirmed(timing: dict[str, Any]) -> bool:
    cleanup = timing.get("cleanup", {})
    return (
        isinstance(cleanup, dict)
        and str(cleanup.get("land", "")).startswith("confirmed_on_ground")
        and isinstance(cleanup.get("landing_observation"), dict)
        and cleanup["landing_observation"].get("state") == "ON_GROUND"
    )


def _publish_native_terminal_lifecycle(
    *, contract_id: str, executor_return_code: int, env: dict[str, str]
) -> dict[str, object]:
    payload = {
        "contract_id": contract_id,
        "terminal_state": "ON_GROUND",
        "executor_return_code": executor_return_code,
        "landing_confirmed": True,
        "safe_to_stop_watchdog": True,
    }
    result = _run(
        [
            "ros2",
            "topic",
            "pub",
            "--once",
            "/dronedream/mission_lifecycle",
            "dronedream_agent_msgs/msg/MissionLifecycle",
            json.dumps(payload, separators=(",", ":")),
        ],
        env=env,
        timeout=10,
    )
    if result.returncode != 0:
        raise SimulationRuntimeError(
            f"native terminal lifecycle publication failed: {result.stderr.strip()[:400]}"
        )
    return {
        **payload,
        "publisher_exit_code": result.returncode,
        "publisher_stdout": result.stdout.strip()[:400],
    }


def _distance_to_polyline(
    point: tuple[float, float, float], route: list[tuple[float, float, float]]
) -> float:
    minimum = math.inf
    for start, end in zip(route, route[1:], strict=False):
        delta = tuple(end[index] - start[index] for index in range(3))
        squared = sum(value * value for value in delta)
        ratio = (
            0.0
            if squared <= 1e-18
            else max(
                0.0,
                min(
                    1.0,
                    sum((point[index] - start[index]) * delta[index] for index in range(3))
                    / squared,
                ),
            )
        )
        nearest = tuple(start[index] + ratio * delta[index] for index in range(3))
        minimum = min(minimum, math.dist(point, nearest))
    return minimum


def run_px4_gazebo_track(
    *,
    run_dir: Path,
    world_sdf: Path,
    semantic_path: Path,
    vehicle_sdf: Path,
    route_path: Path,
    track_path: Path,
    clearance_path: Path,
    controller_params_path: Path,
    px4_root: Path,
    executor_path: Path,
    ros_workspace: Path,
    contract_id: str = "runtime-contract",
    world_name: str = "school_map_world",
    vehicle_name: str = "my_drone",
    executor_extra_args: list[str] | None = None,
) -> dict[str, object]:
    """Execute one route; success requires runtime state and evidence, not process exit alone."""

    if run_dir.exists():
        unexpected = [path for path in run_dir.iterdir() if path.name != "runtime-control"]
        if unexpected:
            raise FileExistsError(f"run directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    for required in (
        world_sdf,
        semantic_path,
        vehicle_sdf,
        route_path,
        track_path,
        clearance_path,
        controller_params_path,
        executor_path,
    ):
        if not required.is_file():
            raise FileNotFoundError(required)

    executor_help = _run(
        [sys.executable, str(executor_path), "--help"],
        env=os.environ.copy(),
        timeout=15,
    )
    required_executor_flags = {
        "--abort-file",
        "--landing-timeout-seconds",
        "--takeoff-climb-rate-m-s",
        "--takeoff-stable-window-seconds",
    }
    missing_flags = sorted(
        flag for flag in required_executor_flags if flag not in executor_help.stdout
    )
    if executor_help.returncode != 0 or missing_flags:
        raise SimulationRuntimeError(
            f"PX4 executor lacks required closed-loop flags: {missing_flags}"
        )

    route = GraphRoute.model_validate_json(route_path.read_text(encoding="utf-8"))
    track = Px4Track.model_validate_json(track_path.read_text(encoding="utf-8"))
    clearance = RouteClearanceReport.model_validate_json(clearance_path.read_text(encoding="utf-8"))
    if not clearance.accepted or clearance.route_sha256 != sha256_json(route):
        raise SimulationRuntimeError("route is not bound to an accepted static-clearance report")
    if len(route.positions_m) != len(track.source_world_points):
        raise SimulationRuntimeError("route and PX4 track point counts differ")

    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    primitives = semantic["collision_primitives"]
    vehicle = semantic["vehicle_clearance"]
    diameter = float(vehicle["collision_diameter_m"])
    height = float(vehicle["collision_height_m"])
    center_offset = track.coordinate_contract.collision_center_above_model_root_m
    model_root = tuple(track.coordinate_contract.model_root_world_enu_m)
    if len(model_root) != 3:
        raise SimulationRuntimeError("PX4 model-root contract is invalid")

    trial_rootfs, px4_executable = _prepare_rootfs(px4_root, run_dir)
    copied_track = run_dir / "reference_track.json"
    copied_params = run_dir / "controller_params.json"
    shutil.copy2(track_path, copied_track)
    shutil.copy2(controller_params_path, copied_params)

    env = os.environ.copy()
    partition = f"dronedream_agent_{os.getpid()}_{int(time.time())}"
    state = run_dir / "runtime-state"
    for name in ("cache", "config", "data"):
        (state / name).mkdir(parents=True, exist_ok=True)
    px4_plugins = px4_root / "build/px4_sitl_default/src/modules/simulation/gz_plugins"
    px4_server_config = px4_root / "src/modules/simulation/gz_bridge/server.config"
    env.update(
        {
            "GZ_PARTITION": partition,
            "GZ_CONFIG_PATH": f"/usr/share/gz:{env.get('GZ_CONFIG_PATH', '')}",
            "GZ_SIM_RESOURCE_PATH": ":".join(
                (
                    str(world_sdf.parent),
                    str(vehicle_sdf.parent.parent),
                    str(px4_root / "Tools/simulation/gz/models"),
                    str(px4_root / "Tools/simulation/gz/worlds"),
                )
            ),
            "GZ_SIM_SYSTEM_PLUGIN_PATH": str(px4_plugins),
            "GZ_SIM_SERVER_CONFIG_PATH": str(px4_server_config),
            "HEADLESS": "1",
            "PX4_GZ_STANDALONE": "1",
            "PX4_GZ_MODEL_NAME": vehicle_name,
            "PX4_SYS_AUTOSTART": "4001",
            "GZ_IP": "127.0.0.1",
            "PYTHONUNBUFFERED": "1",
            "XDG_CACHE_HOME": str(state / "cache"),
            "XDG_CONFIG_HOME": str(state / "config"),
            "XDG_DATA_HOME": str(state / "data"),
            "ROS_DOMAIN_ID": env.get("ROS_DOMAIN_ID", "74"),
            "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
            "ROS2_DISABLE_DAEMON": "1",
            "CYCLONEDDS_URI": (
                '<CycloneDDS><Domain Id="any"><General><Interfaces>'
                '<NetworkInterface address="127.0.0.1"/></Interfaces>'
                "<AllowMulticast>false</AllowMulticast></General><Discovery>"
                "<ParticipantIndex>auto</ParticipantIndex><Peers>"
                '<Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
            ),
        }
    )
    gz_binary = "/usr/bin/gz"
    # Gazebo Transport bindings in this process read the real environment,
    # while child processes receive the explicit copy above.
    os.environ["GZ_PARTITION"] = partition
    os.environ["GZ_IP"] = "127.0.0.1"
    route_points = [(point.x, point.y, point.z) for point in route.positions_m]
    estimated_seconds = sum(
        math.dist(first, second)
        / min(track.points[index].speed_limit_mps, track.points[index + 1].speed_limit_mps)
        for index, (first, second) in enumerate(zip(route_points, route_points[1:], strict=False))
    ) + track.waypoint_hold_seconds * (len(route_points) - 1)
    track_timeout = max(180.0, estimated_seconds * 1.8 + 60.0)

    processes: list[subprocess.Popen[Any] | None] = []
    samples: list[tuple[float, float, float, float]] = []
    sample_lock = threading.Lock()
    abort_reason: str | None = None
    executor_return_code: int | None = None
    native_terminal_lifecycle: dict[str, object] | None = None
    goal_observed_runtime = False
    tolerated_landing_contacts = 0
    minimum_tolerated_landing_clearance = math.inf
    started = time.monotonic()

    # Lazy imports preserve Windows-side planning and tests while using the real
    # Gazebo Python bindings inside DroneDreamRuntime.
    system_packages = "/usr/lib/python3/dist-packages"
    if system_packages not in sys.path:
        sys.path.append(system_packages)
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node as GazeboNode

    gazebo_node = GazeboNode()

    def on_pose(message: Any) -> None:
        for pose in message.pose:
            if pose.name == vehicle_name:
                with sample_lock:
                    samples.append(
                        (
                            time.monotonic() - started,
                            float(pose.position.x),
                            float(pose.position.y),
                            float(pose.position.z),
                        )
                    )
                return

    try:
        with (
            (run_dir / "gazebo.log").open("w", encoding="utf-8") as gazebo_log,
            (run_dir / "px4.log").open("w", encoding="utf-8") as px4_log,
            (run_dir / "executor.stdout.log").open("w", encoding="utf-8") as executor_out,
            (run_dir / "executor.stderr.log").open("w", encoding="utf-8") as executor_err,
            (run_dir / "ros-observer.log").open("w", encoding="utf-8") as observer_log,
            (run_dir / "ros-observations.csv").open("w", encoding="utf-8") as ros_csv,
        ):
            gazebo = subprocess.Popen(
                [gz_binary, "sim", "-r", "-s", str(world_sdf)],
                env=env,
                stdout=gazebo_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            processes.append(gazebo)
            _wait_for_world(gz_binary, world_name, env, 90)
            spawn_evidence = _spawn_entity(
                gz_binary,
                world_name=world_name,
                entity_name=vehicle_name,
                sdf_path=vehicle_sdf,
                pose=(float(model_root[0]), float(model_root[1]), float(model_root[2])),
                env=env,
            )
            _write_json(run_dir / "vehicle_spawn.json", spawn_evidence)
            gazebo_node.subscribe(Pose_V, f"/world/{world_name}/dynamic_pose/info", on_pose)
            abort_file = run_dir / "live_abort.request.json"

            bridge = subprocess.Popen(
                [
                    "ros2",
                    "run",
                    "ros_gz_bridge",
                    "parameter_bridge",
                    "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
                ],
                env=env,
                stdout=observer_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            processes.append(bridge)
            observer = subprocess.Popen(
                [
                    "ros2",
                    "run",
                    "dronedream_agent_ros",
                    "gazebo_pose_observer",
                    "--ros-args",
                    "-p",
                    "use_sim_time:=true",
                    "-p",
                    f"entity_name:={vehicle_name}",
                    "-p",
                    f"gazebo_pose_topic:=/world/{world_name}/dynamic_pose/info",
                    "-p",
                    f"contract_id:={contract_id}",
                    "-p",
                    "segment_id:=runtime-segment",
                ],
                env=env,
                stdout=observer_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            processes.append(observer)
            safety_guard = subprocess.Popen(
                [
                    "ros2",
                    "run",
                    "dronedream_agent_ros",
                    "safety_event_guard",
                    "--ros-args",
                    "-p",
                    f"contract_id:={contract_id}",
                    "-p",
                    f"abort_file:={abort_file}",
                ],
                env=env,
                stdout=observer_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            processes.append(safety_guard)
            ros_recorder = subprocess.Popen(
                [
                    "ros2",
                    "topic",
                    "echo",
                    "--no-daemon",
                    "--csv",
                    "/dronedream/mission_observation",
                    "dronedream_agent_msgs/msg/MissionObservation",
                ],
                env=env,
                stdout=ros_csv,
                stderr=observer_log,
                text=True,
                start_new_session=True,
            )
            processes.append(ros_recorder)

            px4 = subprocess.Popen(
                [
                    str(px4_executable),
                    "-d",
                    "-w",
                    str(trial_rootfs),
                    str(trial_rootfs),
                ],
                cwd=trial_rootfs,
                env=env,
                stdout=px4_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            processes.append(px4)
            _wait_for_vehicle(gz_binary, vehicle_name, env, 120)
            executor = subprocess.Popen(
                [
                    sys.executable,
                    str(executor_path),
                    "--run-dir",
                    str(run_dir),
                    "--track",
                    str(copied_track),
                    "--params",
                    str(copied_params),
                    "--vehicle",
                    "x500",
                    "--world",
                    world_name,
                    "--abort-file",
                    str(abort_file),
                    "--setpoint-rate-hz",
                    "20",
                    "--takeoff-timeout-seconds",
                    "90",
                    "--takeoff-climb-rate-m-s",
                    "0.7",
                    "--track-timeout-seconds",
                    f"{track_timeout:g}",
                    "--landing-timeout-seconds",
                    "90",
                    "--takeoff-stable-window-seconds",
                    "1.5",
                    "--log",
                    str(run_dir / "offboard_executor.log"),
                    *(executor_extra_args or []),
                ],
                env=env,
                stdout=executor_out,
                stderr=executor_err,
                text=True,
                start_new_session=True,
            )
            processes.append(executor)
            deadline = time.monotonic() + track_timeout + 270
            consumed_samples = 0
            while executor.poll() is None:
                if time.monotonic() >= deadline:
                    abort_reason = "EXECUTOR_WALL_TIMEOUT"
                with sample_lock:
                    fresh_samples = samples[consumed_samples:]
                    consumed_samples = len(samples)
                for _, x, y, z in fresh_samples:
                    center = (x, y, z + center_offset)
                    if math.dist(center, route_points[-1]) <= 0.6:
                        goal_observed_runtime = True
                    minimum, minimum_name = min(
                        (
                            _clearance(
                                center,
                                primitive,
                                radius_m=diameter / 2,
                                half_height_m=height / 2,
                            ),
                            str(primitive.get("name", "unknown")),
                        )
                        for primitive in primitives
                    )
                    if minimum < -0.001:
                        phase_path = run_dir / "runtime-phase.json"
                        phase = None
                        if phase_path.is_file():
                            try:
                                phase = json.loads(phase_path.read_text(encoding="utf-8")).get(
                                    "phase"
                                )
                            except (OSError, json.JSONDecodeError):
                                phase = None
                        if _is_tolerated_landing_contact(
                            phase=phase,
                            primitive_name=minimum_name,
                            clearance_m=minimum,
                        ):
                            tolerated_landing_contacts += 1
                            minimum_tolerated_landing_clearance = min(
                                minimum_tolerated_landing_clearance, minimum
                            )
                        else:
                            abort_reason = "LIVE_STATIC_COLLISION"
                    # Landing intentionally leaves the airborne route in the vertical
                    # direction.  Keep collision monitoring active, but close the
                    # route-following phase once the final airborne goal is observed.
                    if (
                        not goal_observed_runtime
                        and _distance_to_polyline(center, route_points) > 1.0
                    ):
                        abort_reason = "LIVE_ROUTE_DEVIATION"
                if abort_reason and not abort_file.exists():
                    _write_json(
                        abort_file,
                        {"reason": abort_reason, "world_paused": False},
                    )
                time.sleep(0.05)
            executor_return_code = executor.wait(timeout=10)
            terminal_timing_path = run_dir / "offboard_timing.json"
            terminal_timing = (
                json.loads(terminal_timing_path.read_text(encoding="utf-8"))
                if terminal_timing_path.is_file()
                else {}
            )
            if executor_return_code == 0 and _landing_confirmed(terminal_timing):
                try:
                    native_terminal_lifecycle = _publish_native_terminal_lifecycle(
                        contract_id=contract_id,
                        executor_return_code=executor_return_code,
                        env=env,
                    )
                    _write_json(
                        run_dir / "native-terminal-lifecycle.json",
                        native_terminal_lifecycle,
                    )
                except SimulationRuntimeError:
                    abort_reason = "NATIVE_TERMINAL_LIFECYCLE_FAILED"
                    raise
    finally:
        for process in reversed(processes):
            _terminate(process)

    with (run_dir / "gazebo_pose_samples.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("elapsed_s", "east_m", "north_m", "model_root_up_m"))
        writer.writerows(samples)

    centers = [(x, y, z + center_offset) for _, x, y, z in samples]
    goal = route_points[-1]
    minimum_goal_distance = min((math.dist(point, goal) for point in centers), default=math.inf)
    timing_path = run_dir / "offboard_timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.is_file() else {}
    ros_rows = 0
    ros_path = run_dir / "ros-observations.csv"
    if ros_path.is_file():
        with ros_path.open(encoding="utf-8", errors="replace") as handle:
            ros_rows = sum(1 for line in handle if line.strip())
    px4_ulogs = [
        {
            "path": str(path.relative_to(run_dir)),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted((run_dir / "px4_rootfs/log").rglob("*.ulg"))
    ]
    gates = {
        "executor_completed": executor_return_code == 0,
        "offboard_timing_complete": timing.get("status") == "complete",
        "runtime_pose_samples_present": len(samples) >= 10,
        "ros_observations_present": ros_rows >= 1,
        "goal_observed": minimum_goal_distance <= 0.6,
        "landing_confirmed": (_landing_confirmed(timing)),
        "native_terminal_lifecycle_published": native_terminal_lifecycle is not None,
        "no_live_abort": abort_reason is None,
        "px4_ulog_present": bool(px4_ulogs),
        "static_route_clearance_bound": clearance.accepted,
    }
    evidence = {
        "schema_version": "dronedream.generic-px4-gazebo-run.v1",
        "status": "verified" if all(gates.values()) else "failed",
        "world": world_name,
        "vehicle": vehicle_name,
        "gates": gates,
        "measurements": {
            "pose_sample_count": len(samples),
            "ros_observation_rows": ros_rows,
            "minimum_goal_distance_m": (
                minimum_goal_distance if math.isfinite(minimum_goal_distance) else None
            ),
            "landing_state": (
                timing.get("cleanup", {}).get("landing_observation", {}).get("state")
            ),
            "abort_reason": abort_reason,
            "executor_return_code": executor_return_code,
            "tolerated_landing_contact_samples": tolerated_landing_contacts,
            "minimum_tolerated_landing_clearance_m": (
                minimum_tolerated_landing_clearance
                if math.isfinite(minimum_tolerated_landing_clearance)
                else None
            ),
        },
        "artifacts": {
            "world_sha256": _sha256(world_sdf),
            "semantic_sha256": _sha256(semantic_path),
            "vehicle_sha256": _sha256(vehicle_sdf),
            "route_sha256": _sha256(route_path),
            "track_sha256": _sha256(track_path),
            "clearance_sha256": _sha256(clearance_path),
            "controller_params_sha256": _sha256(controller_params_path),
            "executor_sha256": _sha256(executor_path),
            "px4_ulogs": px4_ulogs,
            "ros_workspace": str(ros_workspace),
        },
    }
    _write_json(run_dir / "mission_evidence.json", evidence)
    return evidence
