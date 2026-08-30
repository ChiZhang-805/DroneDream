"""Real PX4 SITL + Gazebo runner for an arbitrary validated track contract."""

from __future__ import annotations

import binascii
import csv
import hashlib
import json
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from .collision import _clearance  # same conservative envelope used by static gate
from .contracts import (
    DynamicObstacleObservation,
    GraphRoute,
    LocalPlannerRequest,
    Px4Track,
    RouteClearanceReport,
    RuntimeLocalSafetyCommand,
    RuntimeLocalSafetyObservation,
    Vector3,
)
from .dynamic_safety import predictive_safety_decision
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


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _png_chunk(name: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", binascii.crc32(name + payload) & 0xFFFFFFFF)
    )


def _gazebo_image_png(message: Any) -> bytes:
    """Encode Gazebo RGB/RGBA frames without adding a heavyweight image dependency."""

    width = int(message.width)
    height = int(message.height)
    if width <= 0 or height <= 0 or width > 4096 or height > 2160:
        raise ValueError("Gazebo live frame dimensions are invalid")
    formats = {
        3: (3, 2, False),  # RGB_INT8
        4: (4, 6, False),  # RGBA_INT8
        8: (3, 2, True),  # BGR_INT8
        5: (4, 6, True),  # BGRA_INT8
    }
    channels, color_type, swap_red_blue = formats.get(
        int(message.pixel_format_type), (0, 0, False)
    )
    if channels == 0:
        raise ValueError("Gazebo live frame format is not supported")
    row_bytes = width * channels
    step = max(row_bytes, int(message.step or 0))
    source = bytes(message.data)
    if len(source) < step * height:
        raise ValueError("Gazebo live frame payload is incomplete")
    rows: list[bytes] = []
    for row_index in range(height):
        row = bytearray(source[row_index * step : row_index * step + row_bytes])
        if swap_red_blue:
            for offset in range(0, len(row), channels):
                row[offset], row[offset + 2] = row[offset + 2], row[offset]
        rows.append(b"\x00" + bytes(row))
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), level=3))
        + _png_chunk(b"IEND", b"")
    )


def _live_camera_sdf(
    route_points: list[tuple[float, float, float]],
) -> tuple[str, tuple[float, float, float]]:
    xs = [point[0] for point in route_points]
    ys = [point[1] for point in route_points]
    zs = [point[2] for point in route_points]
    target = (
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
        (min(zs) + max(zs)) / 2,
    )
    span = max(max(xs) - min(xs), max(ys) - min(ys), 6.0)
    camera = (
        target[0] - span * 0.9,
        target[1] - span * 0.9,
        max(zs) + span * 0.7 + 3.0,
    )
    dx, dy, dz = (target[index] - camera[index] for index in range(3))
    yaw = math.atan2(dy, dx)
    pitch = math.atan2(-dz, math.hypot(dx, dy))
    model = f"""<?xml version="1.0"?>
<sdf version="1.10">
  <model name="dronedream_live_camera">
    <static>true</static>
    <pose>0 0 0 0 {pitch:.12g} {yaw:.12g}</pose>
    <link name="camera_link">
      <sensor name="live_camera" type="camera">
        <always_on>true</always_on>
        <update_rate>12</update_rate>
        <topic>/dronedream/live/camera</topic>
        <camera>
          <horizontal_fov>1.0472</horizontal_fov>
          <image><width>1280</width><height>720</height><format>R8G8B8</format></image>
          <clip><near>0.1</near><far>5000</far></clip>
        </camera>
      </sensor>
    </link>
  </model>
</sdf>
"""
    return model, camera


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
    controller_params = json.loads(controller_params_path.read_text(encoding="utf-8"))
    local_max_speed_mps = float(controller_params.get("vel_limit", 2.0))
    local_max_acceleration_mps2 = float(controller_params.get("accel_limit", 4.0))
    local_safety_supported = "--local-safety-command" in executor_help.stdout
    local_safety_target_path = run_dir / "local-safety-target.json"
    local_safety_observation_path = run_dir / "local-safety-observation.json"
    local_safety_command_path = run_dir / "local-safety-command.json"

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
    frame_lock = threading.Lock()
    last_frame_at = 0.0
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
    from gz.msgs10.image_pb2 import Image
    from gz.msgs10.pose_v_pb2 import Pose_V
    from gz.transport13 import Node as GazeboNode

    gazebo_node = GazeboNode()
    pose_lock = threading.Lock()
    previous_vehicle_pose: tuple[float, tuple[float, float, float]] | None = None
    dynamic_pose_history: dict[str, tuple[float, tuple[float, float, float]]] = {}
    local_safety_sequence = 0
    last_local_safety_at = 0.0
    runtime_primitives = semantic.get("runtime_collision_primitives", primitives)

    def dynamic_model_name(name: str) -> bool:
        normalized = name.casefold()
        return "::" not in name and normalized.startswith(
            ("dronedream_dynamic_", "person_", "pedestrian_", "vehicle_dynamic_")
        )

    def nearby_primitives(position: tuple[float, float, float]) -> list[dict[str, Any]]:
        search_radius = max(5.0, local_max_speed_mps * 3.0 + 2.0)
        selected: list[dict[str, Any]] = []
        for primitive in runtime_primitives:
            center = (
                float(primitive.get("center_x", 0.0)),
                float(primitive.get("center_y", 0.0)),
                float(primitive.get("center_z", 0.0)),
            )
            half_size = (
                float(primitive.get("size_x", 0.0)) / 2.0,
                float(primitive.get("size_y", 0.0)) / 2.0,
                float(primitive.get("size_z", 0.0)) / 2.0,
            )
            if all(
                abs(position[index] - center[index]) - half_size[index] <= search_radius
                for index in range(3)
            ):
                selected.append(primitive)
        return selected

    def on_pose(message: Any) -> None:
        nonlocal previous_vehicle_pose, local_safety_sequence, last_local_safety_at
        elapsed = time.monotonic() - started
        vehicle_pose: tuple[float, float, float] | None = None
        dynamic_poses: dict[str, tuple[float, float, float]] = {}
        for pose in message.pose:
            position = (
                float(pose.position.x),
                float(pose.position.y),
                float(pose.position.z),
            )
            if pose.name == vehicle_name:
                vehicle_pose = position
            elif dynamic_model_name(str(pose.name)):
                dynamic_poses[str(pose.name)] = position
        if vehicle_pose is None:
            return
        east, north, up = vehicle_pose
        with sample_lock:
            samples.append((elapsed, east, north, up))
        now_unix_ms = int(time.time() * 1000)
        try:
            rendered = json.dumps(
                {
                    "schema_version": "dronedream.live-telemetry.v1",
                    "mode": "simulation",
                    "coordinate_frame": "gazebo-enu",
                    "elapsed_s": elapsed,
                    "east_m": east,
                    "north_m": north,
                    "up_m": up,
                    "updated_at_unix_ms": now_unix_ms,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            _write_bytes_atomic(run_dir / "live-telemetry.json", rendered)
        except OSError:
            pass
        if not local_safety_supported or not local_safety_target_path.is_file():
            previous_vehicle_pose = elapsed, vehicle_pose
            return
        with pose_lock:
            if elapsed - last_local_safety_at < 0.08:
                return
            previous = previous_vehicle_pose
            previous_vehicle_pose = elapsed, vehicle_pose
            dt = elapsed - previous[0] if previous is not None else 0.0
            velocity = (
                tuple((vehicle_pose[index] - previous[1][index]) / dt for index in range(3))
                if previous is not None and dt > 1e-4
                else (0.0, 0.0, 0.0)
            )
            obstacles: list[DynamicObstacleObservation] = []
            for name, root_position in sorted(dynamic_poses.items()):
                history = dynamic_pose_history.get(name)
                obstacle_dt = elapsed - history[0] if history is not None else 0.0
                obstacle_velocity = (
                    tuple(
                        (root_position[index] - history[1][index]) / obstacle_dt
                        for index in range(3)
                    )
                    if history is not None and obstacle_dt > 1e-4
                    else (0.0, 0.0, 0.0)
                )
                dynamic_pose_history[name] = elapsed, root_position
                obstacle_id = re.sub(r"[^a-z0-9._-]+", "-", name.casefold()).strip("-.")
                obstacles.append(
                    DynamicObstacleObservation(
                        obstacle_id=obstacle_id,
                        position_m=Vector3(
                            x=root_position[0],
                            y=root_position[1],
                            z=root_position[2] + 0.85,
                        ),
                        velocity_mps=Vector3(
                            x=obstacle_velocity[0],
                            y=obstacle_velocity[1],
                            z=obstacle_velocity[2],
                        ),
                        radius_m=0.35,
                        height_m=1.7,
                        confidence=1.0,
                        age_seconds=0.0,
                    )
                )
            try:
                target_payload = json.loads(local_safety_target_path.read_text(encoding="utf-8"))
                target = Vector3.model_validate(target_payload["target_position_m"])
                current = Vector3(x=east, y=north, z=up + center_offset)
                local_safety_sequence += 1
                observation = RuntimeLocalSafetyObservation(
                    sequence=local_safety_sequence,
                    observed_at_unix_ms=now_unix_ms,
                    source="simulation-ground-truth",
                    stream_healthy=True,
                    stream_age_seconds=0.0,
                    localization_covariance_m2=0.0,
                    current_position_m=current,
                    current_velocity_mps=Vector3(
                        x=velocity[0],
                        y=velocity[1],
                        z=velocity[2],
                    ),
                    target_position_m=target,
                    dynamic_obstacles=obstacles,
                )
                request = LocalPlannerRequest(
                    current_position_m=current,
                    current_velocity_mps=observation.current_velocity_mps,
                    target_position_m=target,
                    dynamic_obstacles=obstacles,
                    vehicle_radius_m=diameter / 2.0,
                    vehicle_height_m=height,
                    max_speed_mps=local_max_speed_mps,
                    max_acceleration_mps2=local_max_acceleration_mps2,
                    required_clearance_m=0.35,
                    prediction_horizon_seconds=3.0,
                    prediction_step_seconds=0.2,
                )
                decision = predictive_safety_decision(
                    request,
                    nearby_primitives((current.x, current.y, current.z)),
                )
                command_position = Vector3(
                    x=current.x + decision.selected_velocity_mps.x * 0.2,
                    y=current.y + decision.selected_velocity_mps.y * 0.2,
                    z=current.z + decision.selected_velocity_mps.z * 0.2,
                )
                command = RuntimeLocalSafetyCommand(
                    observation_sha256=sha256_json(observation),
                    observation_sequence=observation.sequence,
                    generated_at_unix_ms=now_unix_ms,
                    valid_until_unix_ms=now_unix_ms + 500,
                    source=observation.source,
                    command_position_m=command_position,
                    decision=decision,
                )
                _write_bytes_atomic(
                    local_safety_observation_path,
                    observation.model_dump_json(indent=2).encode("utf-8"),
                )
                _write_bytes_atomic(
                    local_safety_command_path,
                    command.model_dump_json(indent=2).encode("utf-8"),
                )
                last_local_safety_at = elapsed
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                return

    def on_live_frame(message: Any) -> None:
        nonlocal last_frame_at
        now = time.monotonic()
        with frame_lock:
            if now - last_frame_at < 0.08:
                return
            try:
                payload = _gazebo_image_png(message)
                _write_bytes_atomic(run_dir / "live-frame.png", payload)
                last_frame_at = now
            except (OSError, ValueError):
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
                [gz_binary, "sim", "-r", "-s", "--headless-rendering", str(world_sdf)],
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
            camera_sdf, camera_pose = _live_camera_sdf(route_points)
            camera_sdf_path = run_dir / "live-camera.sdf"
            camera_sdf_path.write_text(camera_sdf, encoding="utf-8")
            camera_ready = False
            try:
                camera_spawn = _spawn_entity(
                    gz_binary,
                    world_name=world_name,
                    entity_name="dronedream_live_camera",
                    sdf_path=camera_sdf_path,
                    pose=camera_pose,
                    env=env,
                )
                camera_ready = True
                _write_json(run_dir / "live-camera-spawn.json", camera_spawn)
            except SimulationRuntimeError as error:
                _write_json(
                    run_dir / "live-camera-spawn.json",
                    {"accepted": False, "issue": str(error)},
                )
            gazebo_node.subscribe(Pose_V, f"/world/{world_name}/dynamic_pose/info", on_pose)
            if camera_ready:
                gazebo_node.subscribe(Image, "/dronedream/live/camera", on_live_frame)
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
                    *(
                        [
                            "--local-safety-command",
                            str(local_safety_command_path),
                            "--local-safety-observation",
                            str(local_safety_observation_path),
                            "--local-safety-target",
                            str(local_safety_target_path),
                        ]
                        if local_safety_supported
                        else []
                    ),
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
    if local_safety_supported:
        gates.update(
            {
                "local_safety_observation_present": local_safety_observation_path.is_file(),
                "local_safety_command_present": local_safety_command_path.is_file(),
                "local_safety_observation_sequence_advanced": local_safety_sequence >= 1,
            }
        )
    evidence = {
        "schema_version": "dronedream.generic-px4-gazebo-run.v1",
        "status": "verified" if all(gates.values()) else "failed",
        "world": world_name,
        "vehicle": vehicle_name,
        "gates": gates,
        "local_safety": {
            "supported_by_executor": local_safety_supported,
            "observation_sequence": local_safety_sequence,
            "observation_path": (
                local_safety_observation_path.name
                if local_safety_observation_path.is_file()
                else None
            ),
            "command_path": (
                local_safety_command_path.name if local_safety_command_path.is_file() else None
            ),
        },
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
