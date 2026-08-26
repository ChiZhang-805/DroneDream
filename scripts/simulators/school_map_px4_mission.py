#!/usr/bin/env python3
"""Run the canonical School Map office round trip in real PX4/Gazebo.

This runner binds one generated School Map package, the bundled My Drone / PX4
X500 mapping, the canonical office-pickup-office route, PX4 offboard evidence,
and sampled Gazebo model poses into one auditable run directory.  It does not
call an LLM; model planning and user confirmation happen above this deterministic
safety executor.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.autonomy.catalog import get_scene  # noqa: E402
from app.autonomy.px4_x500_vehicle import (  # noqa: E402
    MY_DRONE_MODEL_NAME,
    MY_DRONE_PAYLOAD_STATE_TOPIC,
    PX4_X500_DRY_MASS_KG,
    PX4_X500_MAXIMUM_THRUST_N,
    PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT,
    TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M,
    TAKEOUT_PAYLOAD_MASS_KG,
    TAKEOUT_PAYLOAD_MAXIMUM_ATTACHMENT_ERROR_M,
    TAKEOUT_PAYLOAD_MODEL_NAME,
    export_my_drone_gazebo_artifact,
    get_my_drone_gazebo_artifact,
    px4_x500_loaded_thrust_to_weight,
)
from app.autonomy.school_map_artifact import (  # noqa: E402
    STRUCTURAL_TOLERANCE_M,
    CollisionPrimitive,
    export_school_map_gazebo_artifact,
    school_map_runtime_collision_primitives,
)
from app.autonomy.school_map_mission_validation import (  # noqa: E402
    RouteClearanceResult,
    WorldPoint,
    model_root_to_world_envelope_center,
    sample_polyline,
    validate_route_clearance,
    vehicle_clearance_to_primitive_m,
    world_envelope_center_to_px4_local_track,
)

WORLD_NAME = "school_map_world"
VEHICLE_MODEL = "x500"
VEHICLE_ENTITY = MY_DRONE_MODEL_NAME
DEFAULT_PX4_ROOT = Path("/opt/PX4-Autopilot")
DEFAULT_POSE_TOPIC = f"/world/{WORLD_NAME}/dynamic_pose/info"
MISSION_SAMPLE_INTERVAL_M = 0.04
SCHOOL_MAP_WAYPOINT_HOLD_SECONDS = 0.4
DYNAMIC_PENETRATION_TOLERANCE_M = 0.0005
LIVE_ROUTE_ERROR_LIMIT_M = 1.0
LIVE_ROUTE_ERROR_GRACE_SECONDS = 1.0
PICKUP_ACCEPTANCE_RADIUS_M = 0.20
RETURN_ACCEPTANCE_RADIUS_M = 0.45
LANDED_ROOT_HEIGHT_TOLERANCE_M = 0.12
PICKUP_PAYLOAD_SPAWN_RADIUS_M = PICKUP_ACCEPTANCE_RADIUS_M
PICKUP_PAYLOAD_ATTACHMENT_TIMEOUT_SECONDS = 5.0
ROUTE_PROGRESS_MAXIMUM_LOOKAHEAD_WAYPOINTS = 6
# The map geometry itself remains subject to STRUCTURAL_TOLERANCE_M. A rigid
# landing contact is a separate numerical solver condition: Gazebo / DART at
# the real-time-qualified 4 ms step settles the stock X500 skids within 2 mm.
# No other School Map collision is permitted to use this contact-only bound.
DESIGNATED_PAD_CONTACT_TOLERANCE_M = 0.002
DESIGNATED_PAD_CONTACT_HORIZONTAL_RADIUS_M = 0.45
DESIGNATED_PAD_CONTACT_VERTICAL_RADIUS_M = 0.08
MAX_LIVE_ABORT_REQUEST_BYTES = 4096
MAX_RUNTIME_CONTROL_REQUEST_BYTES = 512 * 1024


@dataclass(frozen=True)
class GazeboPoseSample:
    elapsed_s: float
    model_root_x: float
    model_root_y: float
    model_root_z: float

    @property
    def model_root(self) -> WorldPoint:
        return (self.model_root_x, self.model_root_y, self.model_root_z)

    @property
    def envelope_center(self) -> WorldPoint:
        return model_root_to_world_envelope_center(self.model_root)


class GazeboPoseRecorder:
    def __init__(
        self,
        gz_binary: str,
        env: dict[str, str],
        output_csv: Path,
        stderr_log: TextIO,
    ) -> None:
        self._gz_binary = gz_binary
        self._env = env
        self._output_csv = output_csv
        self._stderr_log = stderr_log
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._samples: list[GazeboPoseSample] = []
        self._payload_samples: list[GazeboPoseSample] = []
        self._started_at = 0.0
        self._lock = threading.Lock()

    @property
    def samples(self) -> list[GazeboPoseSample]:
        with self._lock:
            return list(self._samples)

    @property
    def latest_sample(self) -> GazeboPoseSample | None:
        with self._lock:
            return self._samples[-1] if self._samples else None

    @property
    def payload_samples(self) -> list[GazeboPoseSample]:
        with self._lock:
            return list(self._payload_samples)

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._process = subprocess.Popen(  # noqa: S603 - resolved Gazebo executable.
            [self._gz_binary, "topic", "-e", "-t", DEFAULT_POSE_TOPIC],
            env=self._env,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        self._thread = threading.Thread(target=self._read, name="gazebo-pose-recorder", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        pose_depth = 0
        position_depth = 0
        name: str | None = None
        coordinates: dict[str, float] = {}
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line == "pose {":
                pose_depth = 1
                position_depth = 0
                name = None
                coordinates = {}
                continue
            if pose_depth == 0:
                continue
            if line.endswith("{"):
                pose_depth += 1
                if line == "position {":
                    position_depth = pose_depth
                continue
            if line == "}":
                if position_depth == pose_depth:
                    position_depth = 0
                pose_depth -= 1
                if (
                    pose_depth == 0
                    and name
                    in {
                        VEHICLE_ENTITY,
                        TAKEOUT_PAYLOAD_MODEL_NAME,
                    }
                    and set(coordinates) == {"x", "y", "z"}
                ):
                    sample = GazeboPoseSample(
                        elapsed_s=time.monotonic() - self._started_at,
                        model_root_x=coordinates["x"],
                        model_root_y=coordinates["y"],
                        model_root_z=coordinates["z"],
                    )
                    with self._lock:
                        if name == VEHICLE_ENTITY:
                            self._samples.append(sample)
                        else:
                            self._payload_samples.append(sample)
                continue
            if line.startswith("name: "):
                match = re.fullmatch(r'name: "([^"]+)"', line)
                if match:
                    name = match.group(1)
                continue
            if position_depth and line[:2] in {"x:", "y:", "z:"}:
                axis, raw_value = line.split(":", maxsplit=1)
                try:
                    coordinates[axis] = float(raw_value.strip())
                except ValueError:
                    coordinates = {}

    def stop(self) -> None:
        if self._process is not None:
            _terminate_process_group(self._process)
        if self._thread is not None:
            self._thread.join(timeout=10)
        samples = self.samples
        self._output_csv.parent.mkdir(parents=True, exist_ok=True)
        with self._output_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                (
                    "elapsed_s",
                    "model_root_east_m",
                    "model_root_north_m",
                    "model_root_up_m",
                    "envelope_center_east_m",
                    "envelope_center_north_m",
                    "envelope_center_up_m",
                )
            )
            for sample in samples:
                center = sample.envelope_center
                writer.writerow(
                    (
                        f"{sample.elapsed_s:.6f}",
                        f"{sample.model_root_x:.9f}",
                        f"{sample.model_root_y:.9f}",
                        f"{sample.model_root_z:.9f}",
                        f"{center[0]:.9f}",
                        f"{center[1]:.9f}",
                        f"{center[2]:.9f}",
                    )
                )

        payload_output_csv = self._output_csv.with_name("gazebo_payload_pose_samples.csv")
        with payload_output_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("elapsed_s", "east_m", "north_m", "up_m"))
            for sample in self.payload_samples:
                writer.writerow(
                    (
                        f"{sample.elapsed_s:.6f}",
                        f"{sample.model_root_x:.9f}",
                        f"{sample.model_root_y:.9f}",
                        f"{sample.model_root_z:.9f}",
                    )
                )


class GazeboPayloadStateRecorder:
    def __init__(
        self,
        gz_binary: str,
        env: dict[str, str],
        output_log: Path,
        stderr_log: TextIO,
    ) -> None:
        self._gz_binary = gz_binary
        self._env = env
        self._output_log = output_log
        self._stderr_log = stderr_log
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._states: list[tuple[float, str]] = []
        self._started_at = 0.0
        self._lock = threading.Lock()

    @property
    def states(self) -> list[tuple[float, str]]:
        with self._lock:
            return list(self._states)

    @property
    def attached_observed(self) -> bool:
        return any(state == "attached" for _, state in self.states)

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._process = subprocess.Popen(  # noqa: S603 - resolved Gazebo executable.
            [self._gz_binary, "topic", "-e", "-t", MY_DRONE_PAYLOAD_STATE_TOPIC],
            env=self._env,
            stdout=subprocess.PIPE,
            stderr=self._stderr_log,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        self._thread = threading.Thread(
            target=self._read,
            name="gazebo-payload-state-recorder",
            daemon=True,
        )
        self._thread.start()

    def _read(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            match = re.fullmatch(r'\s*data:\s*"([^"]+)"\s*', raw_line)
            if match is None:
                continue
            with self._lock:
                self._states.append((time.monotonic() - self._started_at, match.group(1)))

    def stop(self) -> None:
        if self._process is not None:
            _terminate_process_group(self._process)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._output_log.write_text(
            "".join(f"{elapsed_s:.6f},{state}\n" for elapsed_s, state in self.states),
            encoding="utf-8",
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the canonical School Map office-pickup-office PX4/Gazebo mission"
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--px4-root", type=Path, default=DEFAULT_PX4_ROOT)
    parser.add_argument("--velocity-m-s", type=float, default=1.2)
    parser.add_argument("--acceleration-m-s2", type=float, default=0.8)
    parser.add_argument("--setpoint-rate-hz", type=float, default=20.0)
    parser.add_argument("--takeoff-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--landing-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--world-readiness-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--vehicle-readiness-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--post-flight-observation-seconds", type=float, default=5.0)
    parser.add_argument("--gui", action="store_true")
    return parser.parse_args(argv)


def _validated_positive(value: float, label: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and greater than zero")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pose_z(raw_pose: str) -> float:
    values = raw_pose.split()
    if len(values) < 3:
        raise ValueError("SDF pose must contain at least x, y, z")
    return float(values[2])


def _px4_x500_model_root_to_contact_m(px4_root: Path) -> float:
    base_model = px4_root / "Tools/simulation/gz/models/x500_base/model.sdf"
    raw = base_model.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("PX4 x500_base SDF exceeds the 2 MiB validation limit")
    text = raw.decode("utf-8")
    model_match = re.search(
        r"<model\s+name=['\"]x500_base['\"][^>]*>\s*<pose>([^<]+)</pose>",
        text,
    )
    if model_match is None:
        raise ValueError("PX4 x500_base SDF has no direct model pose")
    model_z = _pose_z(model_match.group(1))
    lowest_surfaces: list[float] = []
    for collision_name in ("base_link_collision_3", "base_link_collision_4"):
        collision_match = re.search(
            rf"<collision\s+name=['\"]{re.escape(collision_name)}['\"]>"
            r"(?P<body>.*?)</collision>",
            text,
            flags=re.DOTALL,
        )
        if collision_match is None:
            raise ValueError(f"PX4 x500_base SDF is missing {collision_name}")
        body = collision_match.group("body")
        pose_match = re.search(r"<pose>([^<]+)</pose>", body)
        size_match = re.search(r"<box>\s*<size>([^<]+)</size>\s*</box>", body)
        if pose_match is None or size_match is None:
            raise ValueError(f"PX4 x500_base {collision_name} is not a box")
        dimensions = [float(value) for value in size_match.group(1).split()]
        if len(dimensions) != 3:
            raise ValueError(f"PX4 x500_base {collision_name} has an invalid box size")
        lowest_surfaces.append(model_z + _pose_z(pose_match.group(1)) - dimensions[2] / 2)
    if max(lowest_surfaces) - min(lowest_surfaces) > 1e-9:
        raise ValueError("PX4 X500 landing skids do not share one contact plane")
    return min(lowest_surfaces)


def _px4_x500_runtime_physics(px4_root: Path) -> dict[str, Any]:
    base_model = px4_root / "Tools/simulation/gz/models/x500_base/model.sdf"
    flight_model = px4_root / "Tools/simulation/gz/models/x500/model.sdf"
    payloads: dict[str, str] = {}
    for label, path in (("base", base_model), ("flight", flight_model)):
        raw = path.read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError(f"PX4 X500 {label} SDF exceeds the 2 MiB validation limit")
        payloads[label] = raw.decode("utf-8")
    masses = [float(value) for value in re.findall(r"<mass>\s*([^<]+)\s*</mass>", payloads["base"])]
    motor_constants = [
        float(value)
        for value in re.findall(r"<motorConstant>\s*([^<]+)\s*</motorConstant>", payloads["flight"])
    ]
    maximum_rotor_velocities = [
        float(value)
        for value in re.findall(
            r"<maxRotVelocity>\s*([^<]+)\s*</maxRotVelocity>", payloads["flight"]
        )
    ]
    if len(masses) != 5 or len(motor_constants) != 4 or len(maximum_rotor_velocities) != 4:
        raise ValueError("PX4 X500 SDF physics layout changed from the qualified contract")
    dry_mass_kg = sum(masses)
    maximum_thrust_n = sum(
        motor_constant * maximum_velocity**2
        for motor_constant, maximum_velocity in zip(
            motor_constants,
            maximum_rotor_velocities,
            strict=True,
        )
    )
    if abs(dry_mass_kg - PX4_X500_DRY_MASS_KG) > 1e-9:
        raise ValueError(
            "PX4 X500 dry mass drifted from the qualified My Drone contract: "
            f"SDF={dry_mass_kg:g}, contract={PX4_X500_DRY_MASS_KG:g}"
        )
    if abs(maximum_thrust_n - PX4_X500_MAXIMUM_THRUST_N) > 1e-9:
        raise ValueError(
            "PX4 X500 maximum thrust drifted from the qualified My Drone contract: "
            f"SDF={maximum_thrust_n:g}, contract={PX4_X500_MAXIMUM_THRUST_N:g}"
        )
    return {
        "dry_mass_kg": dry_mass_kg,
        "maximum_thrust_n": maximum_thrust_n,
        "motor_count": len(motor_constants),
        "motor_constant": motor_constants[0],
        "maximum_rotor_velocity_rad_s": maximum_rotor_velocities[0],
        "loaded_thrust_to_weight": px4_x500_loaded_thrust_to_weight(TAKEOUT_PAYLOAD_MASS_KG),
    }


def _require_executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(f"required executable is unavailable: {name}")
    return resolved


def _run_command(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - callers pass resolved, fixed executables.
        argv,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _create_gazebo_entity(
    gz_binary: str,
    env: dict[str, str],
    *,
    sdf_filename: Path,
    entity_name: str,
    world_pose: WorldPoint,
) -> dict[str, Any]:
    if not sdf_filename.is_file():
        raise FileNotFoundError(f"Gazebo entity SDF does not exist: {sdf_filename}")
    request = (
        f'sdf_filename: "{sdf_filename}" '
        f'name: "{entity_name}" '
        "pose { position { "
        f"x: {world_pose[0]:.12g} y: {world_pose[1]:.12g} z: {world_pose[2]:.12g} "
        "} } allow_renaming: false"
    )
    result = _run_command(
        [
            gz_binary,
            "service",
            "-s",
            f"/world/{WORLD_NAME}/create",
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
        "entity_name": entity_name,
        "sdf_filename": str(sdf_filename),
        "world_pose_enu_m": world_pose,
        "exit_code": result.returncode,
        "accepted": accepted,
        "stdout": result.stdout.strip()[:1000],
        "stderr": result.stderr.strip()[:1000],
    }
    if not accepted:
        raise RuntimeError(f"Gazebo rejected entity {entity_name}: {evidence}")
    return evidence


def _wait_for_world(gz_binary: str, env: dict[str, str], timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    service = f"/world/{WORLD_NAME}/scene/info"
    while time.monotonic() < deadline:
        result = _run_command(
            [gz_binary, "service", "-i", "--service", service],
            env=env,
            timeout=5,
        )
        if result.returncode == 0 and "Service providers" in result.stdout:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Gazebo world did not expose {service} within {timeout_seconds:g}s")


def _wait_for_vehicle(gz_binary: str, env: dict[str, str], timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = _run_command([gz_binary, "topic", "-l"], env=env, timeout=5)
        if result.returncode == 0 and VEHICLE_ENTITY in result.stdout:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Gazebo did not expose {VEHICLE_ENTITY} within {timeout_seconds:g}s")


def _measure_realtime_factor(gz_binary: str, env: dict[str, str]) -> dict[str, Any]:
    result = _run_command(
        [
            gz_binary,
            "topic",
            "-e",
            "-t",
            f"/world/{WORLD_NAME}/stats",
            "-d",
            "5",
            "--json-output",
        ],
        env=env,
        timeout=12,
    )
    values: list[float] = [
        float(value)
        for value in re.findall(
            r'"(?:real_time_factor|realTimeFactor)"\s*:\s*([0-9.eE+-]+)',
            result.stdout,
        )
    ]
    if not values and result.stdout.strip():
        decoder = json.JSONDecoder()
        remaining = result.stdout.strip()
        messages: list[dict[str, Any]] = []
        while remaining:
            try:
                payload, offset = decoder.raw_decode(remaining)
            except json.JSONDecodeError:
                break
            if isinstance(payload, dict):
                messages.append(payload)
            remaining = remaining[offset:].lstrip()

        def timestamp_seconds(payload: dict[str, Any], field: str) -> float | None:
            value = payload.get(field)
            if not isinstance(value, dict):
                return None
            seconds = value.get("sec")
            nanoseconds = value.get("nsec", 0)
            if not isinstance(seconds, (int, float)) or not isinstance(nanoseconds, (int, float)):
                return None
            return float(seconds) + float(nanoseconds) / 1_000_000_000

        for previous, current in zip(messages[:-1], messages[1:], strict=True):
            previous_sim = timestamp_seconds(previous, "simTime")
            current_sim = timestamp_seconds(current, "simTime")
            previous_real = timestamp_seconds(previous, "realTime")
            current_real = timestamp_seconds(current, "realTime")
            if any(
                value is None for value in (previous_sim, current_sim, previous_real, current_real)
            ):
                continue
            sim_delta = cast(float, current_sim) - cast(float, previous_sim)
            real_delta = cast(float, current_real) - cast(float, previous_real)
            if real_delta > 0:
                values.append(sim_delta / real_delta)
    if result.returncode != 0 or not values:
        raise RuntimeError(
            "Gazebo real-time-factor probe returned no usable world statistics: "
            f"exit={result.returncode}, stderr={result.stderr.strip()!r}, "
            f"stdout={result.stdout[:1200]!r}"
        )
    steady_values = values[len(values) // 2 :]
    return {
        "sample_count": len(values),
        "minimum": min(steady_values),
        "median": statistics.median(steady_values),
        "maximum": max(steady_values),
    }


def _set_world_paused(
    gz_binary: str,
    env: dict[str, str],
    *,
    paused: bool,
) -> dict[str, Any]:
    result = _run_command(
        [
            gz_binary,
            "service",
            "-s",
            f"/world/{WORLD_NAME}/control",
            "--reqtype",
            "gz.msgs.WorldControl",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "2000",
            "--req",
            f"pause: {'true' if paused else 'false'}",
        ],
        env=env,
        timeout=5,
    )
    return {
        "exit_code": result.returncode,
        "accepted": result.returncode == 0 and "data: true" in result.stdout,
        "stdout": result.stdout.strip()[:1000],
        "stderr": result.stderr.strip()[:1000],
    }


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        os.kill(-process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.kill(-process.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except ProcessLookupError:
            return
        process.wait(timeout=10)


def _route_points() -> list[WorldPoint]:
    scene = get_scene("school-campus-v1")
    if scene is None:
        raise RuntimeError("bundled School Map compiler scene is unavailable")
    return [(point.x, point.y, point.z) for point in scene.reference_path]


def _estimated_segmented_track_seconds(
    route: list[WorldPoint],
    *,
    velocity_limit_m_s: float,
    acceleration_limit_m_s2: float,
) -> float:
    scene = get_scene("school-campus-v1")
    if scene is None or len(scene.reference_path) != len(route):
        raise RuntimeError("School Map route speed contract is unavailable")
    duration = SCHOOL_MAP_WAYPOINT_HOLD_SECONDS * max(0, len(route) - 1)
    for index, (start, end) in enumerate(zip(route[:-1], route[1:], strict=True)):
        speed_limit = min(
            velocity_limit_m_s,
            scene.reference_path[index].speed_limit_mps,
            scene.reference_path[index + 1].speed_limit_mps,
        )
        distance = math.dist(start, end)
        duration += distance / speed_limit + 2 * speed_limit / acceleration_limit_m_s2
    return duration


def _minimum_point_distance(samples: list[WorldPoint], target: WorldPoint) -> tuple[float, int]:
    if not samples:
        raise ValueError("at least one Gazebo pose sample is required")
    distances = [math.dist(sample, target) for sample in samples]
    index = min(range(len(distances)), key=distances.__getitem__)
    return distances[index], index


def _point_segment_distance(point: WorldPoint, start: WorldPoint, end: WorldPoint) -> float:
    delta = tuple(end[index] - start[index] for index in range(3))
    length_squared = sum(component * component for component in delta)
    if length_squared <= 1e-18:
        return math.dist(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            sum((point[index] - start[index]) * delta[index] for index in range(3))
            / length_squared,
        ),
    )
    closest = tuple(start[index] + ratio * delta[index] for index in range(3))
    return math.dist(point, closest)


def _maximum_track_error(samples: list[WorldPoint], route: list[WorldPoint]) -> float:
    if len(route) < 2:
        raise ValueError("reference route requires at least two points")
    return max(_route_error(sample, route) for sample in samples)


def _route_error(sample: WorldPoint, route: list[WorldPoint]) -> float:
    return min(
        _point_segment_distance(sample, start, end)
        for start, end in zip(route[:-1], route[1:], strict=True)
    )


def _monotonic_route_progress_index(
    point: WorldPoint,
    route: list[WorldPoint],
    previous_index: int,
) -> int:
    if not route:
        raise ValueError("reference route is empty")
    lower = min(max(previous_index, 0), len(route) - 1)
    upper = min(len(route), lower + ROUTE_PROGRESS_MAXIMUM_LOOKAHEAD_WAYPOINTS + 1)
    return min(
        range(lower, upper),
        key=lambda index: (math.dist(point, route[index]), index),
    )


def _clearance_payload(result: RouteClearanceResult) -> dict[str, Any]:
    return {
        "sample_count": result.sample_count,
        "collision_count": result.collision_count,
        "minimum_clearance_m": result.minimum_clearance_m,
        "minimum_clearance_point": result.minimum_clearance_point,
        "minimum_clearance_primitive": result.minimum_clearance_primitive,
        "collisions": result.collisions,
    }


def _resample_recorded_centers(
    centers: list[WorldPoint],
    *,
    interval_m: float = MISSION_SAMPLE_INTERVAL_M,
) -> list[WorldPoint]:
    """Remove stationary telemetry duplicates, then sample the traveled chords.

    Live safety checks every received pose.  Final evidence only needs a dense
    geometric trace; retaining a new anchor after 20 mm of cumulative travel and
    resampling every 40 mm preserves a sub-centimeter chord-deviation bound while
    avoiding a 40k x 4k duplicate clearance scan after landing.
    """

    if len(centers) <= 2:
        return centers
    anchors = [centers[0]]
    accumulated = 0.0
    previous = centers[0]
    for point in centers[1:-1]:
        accumulated += math.dist(previous, point)
        previous = point
        if accumulated >= interval_m / 2:
            anchors.append(point)
            accumulated = 0.0
    if math.dist(anchors[-1], centers[-1]) > 1e-12:
        anchors.append(centers[-1])
    else:
        anchors[-1] = centers[-1]
    return sample_polyline(anchors, interval_m)


def _dynamic_safety_clearance(
    centers: list[WorldPoint],
    primitives: list[CollisionPrimitive],
    launch_point: WorldPoint,
) -> dict[str, Any]:
    launch_pad_name = "office-drone-launch-pad"
    launch_pad = next(item for item in primitives if item.name == launch_pad_name)
    other_primitives = [item for item in primitives if item.name != launch_pad_name]
    designated_contact: list[WorldPoint] = []
    unrestricted: list[WorldPoint] = []
    for point in centers:
        horizontal = math.hypot(point[0] - launch_point[0], point[1] - launch_point[1])
        vertical = abs(point[2] - launch_point[2])
        target = (
            designated_contact
            if (
                horizontal <= DESIGNATED_PAD_CONTACT_HORIZONTAL_RADIUS_M
                and vertical <= DESIGNATED_PAD_CONTACT_VERTICAL_RADIUS_M
            )
            else unrestricted
        )
        target.append(point)

    checked_groups: list[RouteClearanceResult] = []
    if unrestricted:
        checked_groups.append(
            validate_route_clearance(
                unrestricted,
                primitives,
                penetration_tolerance_m=DYNAMIC_PENETRATION_TOLERANCE_M,
            )
        )
    if designated_contact:
        checked_groups.append(
            validate_route_clearance(
                designated_contact,
                other_primitives,
                penetration_tolerance_m=DYNAMIC_PENETRATION_TOLERANCE_M,
            )
        )
    unsafe_collisions = sum(result.collision_count for result in checked_groups)
    reported_unsafe_collisions = tuple(
        collision for result in checked_groups for collision in result.collisions
    )[:50]
    pad_clearances = [
        (point, vehicle_clearance_to_primitive_m(point, launch_pad)) for point in designated_contact
    ]
    minimum_pad_contact = min((item[1] for item in pad_clearances), default=math.inf)
    pad_contact_within_tolerance = (
        bool(pad_clearances) and minimum_pad_contact >= -DESIGNATED_PAD_CONTACT_TOLERANCE_M
    )
    minimum_candidates = [
        (
            result.minimum_clearance_m,
            result.minimum_clearance_point,
            result.minimum_clearance_primitive,
        )
        for result in checked_groups
    ]
    if pad_clearances:
        minimum_pad_point, _ = min(pad_clearances, key=lambda item: item[1])
        minimum_candidates.append((minimum_pad_contact, minimum_pad_point, launch_pad_name))
    minimum = min(minimum_candidates, key=lambda item: item[0])
    return {
        "sample_count": len(centers),
        "designated_contact_sample_count": len(designated_contact),
        "unsafe_collision_count": unsafe_collisions,
        "unsafe_collisions": reported_unsafe_collisions,
        "minimum_clearance_m": minimum[0],
        "minimum_clearance_point": minimum[1],
        "minimum_clearance_primitive": minimum[2],
        "designated_pad_contact": {
            "primitive": launch_pad_name,
            "minimum_clearance_m": minimum_pad_contact,
            "solver_tolerance_m": DESIGNATED_PAD_CONTACT_TOLERANCE_M,
            "within_solver_tolerance": pad_contact_within_tolerance,
        },
    }


def _payload_retention_measurements(
    vehicle_samples: list[GazeboPoseSample],
    payload_samples: list[GazeboPoseSample],
) -> dict[str, Any]:
    if not vehicle_samples or not payload_samples:
        return {
            "settled_sample_count": 0,
            "maximum_attachment_error_m": None,
            "final_attachment_error_m": None,
        }
    vehicle_times = [sample.elapsed_s for sample in vehicle_samples]
    settle_time = payload_samples[0].elapsed_s + 1.0
    errors: list[float] = []
    for payload in payload_samples:
        if payload.elapsed_s < settle_time:
            continue
        insertion = bisect.bisect_left(vehicle_times, payload.elapsed_s)
        candidates = [
            index for index in (insertion - 1, insertion) if 0 <= index < len(vehicle_samples)
        ]
        vehicle = min(candidates, key=lambda index: abs(vehicle_times[index] - payload.elapsed_s))
        vehicle_root = vehicle_samples[vehicle].model_root
        expected = (
            vehicle_root[0],
            vehicle_root[1],
            vehicle_root[2] + TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M,
        )
        errors.append(math.dist(payload.model_root, expected))
    return {
        "settled_sample_count": len(errors),
        "maximum_attachment_error_m": max(errors) if errors else None,
        "final_attachment_error_m": errors[-1] if errors else None,
    }


def _prepare_run_directory(run_dir: Path) -> None:
    """Admit an empty run directory or bounded early runtime control files."""

    if run_dir.exists():
        admitted_control_files = {
            "live_abort.request.json",
            "runtime_control.request.json",
        }
        unexpected = [
            path.name for path in run_dir.iterdir() if path.name not in admitted_control_files
        ]
        if unexpected:
            raise FileExistsError(
                f"run directory contains unexpected entries: {', '.join(sorted(unexpected))}"
            )
        early_abort = run_dir / "live_abort.request.json"
        if early_abort.exists():
            _read_live_abort_request(early_abort)
        early_control = run_dir / "runtime_control.request.json"
        if early_control.exists():
            _read_runtime_control_request(early_control)
    run_dir.mkdir(parents=True, exist_ok=True)


def _read_live_abort_request(path: Path) -> tuple[str, bool]:
    if path.stat().st_size > MAX_LIVE_ABORT_REQUEST_BYTES:
        raise RuntimeError("live abort request is oversized")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("live abort request is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("live abort request is invalid")
    reason = payload.get("reason")
    world_paused = payload.get("world_paused")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
        raise RuntimeError("live abort reason is invalid")
    if not isinstance(world_paused, bool):
        raise RuntimeError("live abort world_paused flag is invalid")
    return reason.strip(), world_paused


def _read_runtime_control_request(
    path: Path,
) -> tuple[int, str, list[WorldPoint] | None, list[str] | None]:
    if path.stat().st_size > MAX_RUNTIME_CONTROL_REQUEST_BYTES:
        raise RuntimeError("runtime control request is oversized")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("runtime control request is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("runtime control request is invalid")
    if payload.get("schema_version") != "dronedream.autonomy.runtime-control.v1":
        raise RuntimeError("runtime control schema is unsupported")
    revision = payload.get("revision")
    mission_revision = payload.get("mission_revision")
    action = payload.get("action")
    contract_id = payload.get("contract_id")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise RuntimeError("runtime control revision is invalid")
    if (
        isinstance(mission_revision, bool)
        or not isinstance(mission_revision, int)
        or mission_revision < 1
    ):
        raise RuntimeError("runtime control mission revision is invalid")
    if action not in {"hold", "resume", "replace_route"}:
        raise RuntimeError("runtime control action is invalid")
    if not isinstance(contract_id, str) or not 8 <= len(contract_id) <= 160:
        raise RuntimeError("runtime control contract id is invalid")
    raw_route = payload.get("route")
    if action != "replace_route":
        if raw_route is not None:
            raise RuntimeError("runtime hold or resume request must not include a route")
        return revision, action, None, None
    if not isinstance(raw_route, list) or not 2 <= len(raw_route) <= 10_000:
        raise RuntimeError("runtime replacement route is invalid")
    route: list[WorldPoint] = []
    phases: list[str] = []
    allowed_phases = {"launch", "transit", "stairs", "gate", "pickup", "return", "land"}
    for index, point in enumerate(raw_route):
        if not isinstance(point, dict):
            raise RuntimeError(f"runtime replacement route point {index} is invalid")
        coordinates: list[float] = []
        for axis in ("x", "y", "z"):
            raw = point.get(axis)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise RuntimeError(f"runtime replacement route point {index}.{axis} is invalid")
            value = float(raw)
            if not math.isfinite(value):
                raise RuntimeError(f"runtime replacement route point {index}.{axis} is invalid")
            coordinates.append(value)
        phase = point.get("phase")
        if phase not in allowed_phases:
            raise RuntimeError(f"runtime replacement route point {index}.phase is invalid")
        route.append((coordinates[0], coordinates[1], coordinates[2]))
        phases.append(str(phase))
    return revision, action, route, phases


def _prepare_run(
    run_dir: Path,
    px4_root: Path,
    velocity_m_s: float,
    acceleration_m_s2: float,
) -> tuple[Path, Path, Path, Path, WorldPoint, list[WorldPoint], float]:
    _prepare_run_directory(run_dir)
    if not px4_root.is_dir():
        raise FileNotFoundError(f"PX4 root does not exist: {px4_root}")
    x500_model = px4_root / "Tools/simulation/gz/models/x500/model.sdf"
    if not x500_model.is_file():
        raise FileNotFoundError(f"PX4 X500 model does not exist: {x500_model}")

    map_dir = run_dir / "school-map"
    exported = export_school_map_gazebo_artifact(map_dir)
    vehicle_dir = run_dir / "my-drone"
    vehicle_exported = export_my_drone_gazebo_artifact(vehicle_dir)
    semantic = json.loads((map_dir / "semantic.json").read_text(encoding="utf-8"))
    spawn = semantic["simulation_bindings"]["px4_recommended_spawn"]
    if spawn.get("pose_reference") != "px4-x500-model-root":
        raise RuntimeError("School Map PX4 spawn must use the PX4 X500 model-root reference")
    model_root_to_contact_m = _px4_x500_model_root_to_contact_m(px4_root)
    runtime_physics = _px4_x500_runtime_physics(px4_root)
    declared_root_to_contact_m = float(spawn["contact_surface_offset_z"])
    if abs(model_root_to_contact_m - declared_root_to_contact_m) > STRUCTURAL_TOLERANCE_M:
        raise RuntimeError(
            "PX4 X500 root-to-contact offset disagrees with the School Map contract: "
            f"SDF={model_root_to_contact_m:g}, map={declared_root_to_contact_m:g}"
        )
    model_root_world = (float(spawn["x"]), float(spawn["y"]), float(spawn["z"]))
    route = _route_points()
    scene = get_scene("school-campus-v1")
    if scene is None or len(scene.reference_path) != len(route):
        raise RuntimeError("School Map route metadata is unavailable")
    static_samples = sample_polyline(route, MISSION_SAMPLE_INTERVAL_M)
    static_clearance = validate_route_clearance(
        static_samples,
        school_map_runtime_collision_primitives(),
        penetration_tolerance_m=STRUCTURAL_TOLERANCE_M,
    )
    if static_clearance.collision_count:
        raise RuntimeError(
            f"School Map reference route intersects static geometry: {static_clearance.collisions}"
        )

    local_track = [
        world_envelope_center_to_px4_local_track(point, model_root_world=model_root_world)
        for point in route
    ]
    track_path = run_dir / "reference_track.json"
    _write_json(
        track_path,
        {
            "schema_version": "dronedream.school-map-px4-track.v1",
            "track_type": "custom",
            "stop_at_waypoints": True,
            "waypoint_hold_seconds": SCHOOL_MAP_WAYPOINT_HOLD_SECONDS,
            "coordinate_contract": {
                "source": "Gazebo ENU vehicle-collision-envelope center",
                "executor_x": "PX4 local north physically mapped to Gazebo y / School Map north",
                "executor_y": "PX4 local east physically mapped to Gazebo x / School Map east",
                "executor_z": "PX4 local up",
                "model_root_world_enu_m": model_root_world,
                "collision_center_above_model_root_m": (
                    semantic["simulation_bindings"]["vehicle_collision_center_offset"]["z"]
                ),
            },
            "source_world_points": [
                {"east_m": point[0], "north_m": point[1], "up_m": point[2]} for point in route
            ],
            "points": [
                {
                    "x": point[0],
                    "y": point[1],
                    "z": point[2],
                    "phase": source.phase,
                    "speed_limit_mps": source.speed_limit_mps,
                }
                for point, source in zip(local_track, scene.reference_path, strict=True)
            ],
        },
    )
    params_path = run_dir / "controller_params.json"
    _write_json(
        params_path,
        {
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": velocity_m_s,
            "accel_limit": acceleration_m_s2,
            "disturbance_rejection": 0.5,
        },
    )
    route_length_m = sum(
        math.dist(start, end) for start, end in zip(route[:-1], route[1:], strict=True)
    )
    _write_json(
        run_dir / "preflight_contract.json",
        {
            "schema_version": "dronedream.school-map-px4-preflight.v1",
            "school_map_package_sha256": exported,
            "my_drone_package_sha256": vehicle_exported,
            "my_drone_physics": get_my_drone_gazebo_artifact().summary,
            "px4_x500_model_sha256": _sha256(x500_model),
            "px4_x500_model_root_to_contact_m": model_root_to_contact_m,
            "px4_x500_runtime_physics": runtime_physics,
            "model_root_world_enu_m": model_root_world,
            "reference_waypoint_count": len(route),
            "reference_route_length_m": route_length_m,
            "static_clearance": _clearance_payload(static_clearance),
        },
    )
    return (
        map_dir,
        vehicle_dir,
        track_path,
        params_path,
        model_root_world,
        route,
        route_length_m,
    )


def _prepare_isolated_px4_rootfs(px4_root: Path, run_dir: Path) -> tuple[Path, Path]:
    build_root = px4_root / "build/px4_sitl_default"
    source_rootfs = build_root / "rootfs"
    px4_executable = build_root / "bin/px4"
    if not source_rootfs.is_dir() or not px4_executable.is_file():
        raise FileNotFoundError("PX4 SITL build is missing rootfs or bin/px4")
    for source in source_rootfs.rglob("*"):
        if not source.is_symlink():
            continue
        try:
            source.resolve(strict=True).relative_to(px4_root)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"PX4 rootfs contains an unsafe external symlink: {source}") from exc
    trial_rootfs = run_dir / "px4_rootfs"
    shutil.copytree(
        source_rootfs,
        trial_rootfs,
        symlinks=False,
        ignore=shutil.ignore_patterns(
            "dataman",
            "eeprom",
            "log",
            "parameters.bson",
            "parameters_backup.bson",
        ),
    )
    _write_json(
        run_dir / "px4_state_policy.json",
        {
            "schema_version": "dronedream.px4-trial-state.v1",
            "policy": "clean-copy-without-prior-params-dataman-logs-or-eeprom",
            "source_rootfs": str(source_rootfs),
            "trial_rootfs": str(trial_rootfs),
            "px4_executable": str(px4_executable),
        },
    )
    return trial_rootfs, px4_executable


def _evaluate(
    run_dir: Path,
    samples: list[GazeboPoseSample],
    payload_samples: list[GazeboPoseSample],
    payload_states: list[tuple[float, str]],
    payload_spawn_evidence: dict[str, Any] | None,
    model_root_world: WorldPoint,
    route: list[WorldPoint],
    executor_return_code: int | None,
    process_failure: str | None,
) -> tuple[dict[str, Any], bool]:
    centers = [sample.envelope_center for sample in samples]
    evaluated_centers = _resample_recorded_centers(centers) if centers else []
    timing_path = run_dir / "offboard_timing.json"
    timing_payload = (
        json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.is_file() else {}
    )
    timing: dict[str, Any] = timing_payload if isinstance(timing_payload, dict) else {}
    ulogs = sorted((run_dir / "px4_rootfs/log").rglob("*.ulg"))
    ulog_evidence = [
        {
            "path": str(path.relative_to(run_dir)).replace("\\", "/"),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for path in ulogs
    ]
    if evaluated_centers:
        dynamic_clearance = _dynamic_safety_clearance(
            evaluated_centers,
            school_map_runtime_collision_primitives(),
            model_root_to_world_envelope_center(model_root_world),
        )
        pickup_distance, pickup_index = _minimum_point_distance(centers, route[len(route) // 2])
        return_distance, _ = _minimum_point_distance(centers[pickup_index:], route[-1])
        maximum_track_error = _maximum_track_error(centers, route)
        final_root = samples[-1].model_root
        landed_root_error = math.dist(final_root, model_root_world)
    else:
        dynamic_clearance = None
        pickup_distance = math.inf
        return_distance = math.inf
        maximum_track_error = math.inf
        final_root = None
        landed_root_error = math.inf
    payload_retention = _payload_retention_measurements(samples, payload_samples)
    attached_observed = any(state == "attached" for _, state in payload_states)

    cleanup_payload = timing.get("cleanup")
    cleanup: dict[str, Any] = cleanup_payload if isinstance(cleanup_payload, dict) else {}
    takeoff_gate = timing.get("takeoff_gate")
    gates = {
        "executor_completed": executor_return_code == 0,
        "offboard_timing_complete": timing.get("status") == "complete",
        "takeoff_gate_achieved": (
            isinstance(takeoff_gate, dict) and takeoff_gate.get("status") == "achieved"
        ),
        "pickup_reached": pickup_distance <= PICKUP_ACCEPTANCE_RADIUS_M,
        "office_return_reached": return_distance <= RETURN_ACCEPTANCE_RADIUS_M,
        "zero_unsafe_dynamic_penetrations": (
            dynamic_clearance is not None
            and dynamic_clearance["unsafe_collision_count"] == 0
            and dynamic_clearance["designated_pad_contact"]["within_solver_tolerance"]
        ),
        "physical_payload_spawned": (
            payload_spawn_evidence is not None and payload_spawn_evidence.get("accepted") is True
        ),
        "physical_payload_attached": attached_observed,
        "physical_payload_retained": (
            payload_retention["settled_sample_count"] > 0
            and payload_retention["maximum_attachment_error_m"]
            <= TAKEOUT_PAYLOAD_MAXIMUM_ATTACHMENT_ERROR_M
        ),
        "loaded_thrust_to_weight_qualified": (
            px4_x500_loaded_thrust_to_weight(TAKEOUT_PAYLOAD_MASS_KG)
            >= PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT
        ),
        "px4_landing_confirmed": str(cleanup.get("land", "")).startswith("confirmed_on_ground"),
        "landed_on_office_pad": landed_root_error <= LANDED_ROOT_HEIGHT_TOLERANCE_M,
    }
    verified = all(gates.values()) and process_failure is None
    aborted = process_failure is not None and "abort" in process_failure.casefold()
    payload: dict[str, Any] = {
        "schema_version": "dronedream.school-map-px4-mission-evidence.v1",
        "status": "verified" if verified else "aborted" if aborted else "failed",
        "gazebo_runtime_verified": bool(samples),
        "px4_mission_smoke_verified": verified,
        "simulation_execution_ready": verified,
        "vehicle": VEHICLE_ENTITY,
        "world": WORLD_NAME,
        "pose_sample_count": len(samples),
        "executor_return_code": executor_return_code,
        "process_failure": process_failure,
        "gates": gates,
        "measurements": {
            "minimum_pickup_distance_m": pickup_distance
            if math.isfinite(pickup_distance)
            else None,
            "minimum_return_distance_m": return_distance
            if math.isfinite(return_distance)
            else None,
            "maximum_reference_polyline_error_m": (
                maximum_track_error if math.isfinite(maximum_track_error) else None
            ),
            "final_model_root_world_enu_m": final_root,
            "final_model_root_error_m": (
                landed_root_error if math.isfinite(landed_root_error) else None
            ),
            "dynamic_penetration_tolerance_m": DYNAMIC_PENETRATION_TOLERANCE_M,
            "dynamic_clearance": (dynamic_clearance if dynamic_clearance is not None else None),
            "payload_retention": payload_retention,
            "payload_mass_kg": TAKEOUT_PAYLOAD_MASS_KG,
            "loaded_mass_kg": PX4_X500_DRY_MASS_KG + TAKEOUT_PAYLOAD_MASS_KG,
            "maximum_thrust_n": PX4_X500_MAXIMUM_THRUST_N,
            "loaded_thrust_to_weight": px4_x500_loaded_thrust_to_weight(TAKEOUT_PAYLOAD_MASS_KG),
        },
        "artifacts": {
            "map_summary": "school-map/summary.json",
            "reference_track": "reference_track.json",
            "controller_params": "controller_params.json",
            "offboard_timing": "offboard_timing.json",
            "gazebo_performance": "gazebo_performance.json",
            "live_safety_gate": "live_safety_gate.json",
            "gazebo_pose_samples": "gazebo_pose_samples.csv",
            "gazebo_payload_pose_samples": "gazebo_payload_pose_samples.csv",
            "payload_attachment_states": "payload_attachment_states.log",
            "payload_spawn": "payload_spawn.json",
            "gazebo_log": "gazebo.log",
            "px4_log": "px4.log",
            "executor_log": "offboard_executor.log",
            "px4_state_policy": "px4_state_policy.json",
            "px4_ulogs": ulog_evidence,
        },
    }
    return payload, verified


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    velocity_m_s = _validated_positive(args.velocity_m_s, "velocity_m_s")
    acceleration_m_s2 = _validated_positive(args.acceleration_m_s2, "acceleration_m_s2")
    setpoint_rate_hz = _validated_positive(args.setpoint_rate_hz, "setpoint_rate_hz")
    run_dir = args.run_dir.resolve()
    px4_root = args.px4_root.resolve()
    (
        map_dir,
        vehicle_dir,
        track_path,
        params_path,
        model_root_world,
        route,
        route_length_m,
    ) = _prepare_run(run_dir, px4_root, velocity_m_s, acceleration_m_s2)
    designated_landing_contact_center = model_root_to_world_envelope_center(model_root_world)

    gz_binary = _require_executable("gz")
    trial_rootfs, px4_executable = _prepare_isolated_px4_rootfs(px4_root, run_dir)
    partition = f"dronedream_school_map_{os.getpid()}_{int(time.time())}"
    env = os.environ.copy()
    runtime_state_root = run_dir / "runtime-state"
    runtime_cache = runtime_state_root / "cache"
    runtime_config = runtime_state_root / "config"
    runtime_data = runtime_state_root / "data"
    for directory in (runtime_cache, runtime_config, runtime_data):
        directory.mkdir(parents=True, exist_ok=True)
    resource_paths = (
        str(map_dir),
        str(vehicle_dir.parent),
        str(px4_root / "Tools/simulation/gz/models"),
        str(px4_root / "Tools/simulation/gz/worlds"),
    )
    existing_resources = env.get("GZ_SIM_RESOURCE_PATH")
    px4_system_plugins = px4_root / "build/px4_sitl_default/src/modules/simulation/gz_plugins"
    px4_server_config = px4_root / "src/modules/simulation/gz_bridge/server.config"
    if not px4_server_config.is_file():
        raise FileNotFoundError(f"PX4 Gazebo server config does not exist: {px4_server_config}")
    existing_system_plugins = env.get("GZ_SIM_SYSTEM_PLUGIN_PATH")
    env.update(
        {
            "GZ_PARTITION": partition,
            "GZ_SIM_RESOURCE_PATH": ":".join(
                (*resource_paths, existing_resources) if existing_resources else resource_paths
            ),
            "GZ_SIM_SYSTEM_PLUGIN_PATH": ":".join(
                (str(px4_system_plugins), existing_system_plugins)
                if existing_system_plugins
                else (str(px4_system_plugins),)
            ),
            "GZ_SIM_SERVER_CONFIG_PATH": str(px4_server_config),
            "HEADLESS": "1",
            "PX4_GZ_STANDALONE": "1",
            "PX4_GZ_MODEL_NAME": VEHICLE_ENTITY,
            "PX4_SYS_AUTOSTART": "4001",
            "GZ_IP": "127.0.0.1",
            "PYTHONUNBUFFERED": "1",
            "XDG_CACHE_HOME": str(runtime_cache),
            "XDG_CONFIG_HOME": str(runtime_config),
            "XDG_DATA_HOME": str(runtime_data),
        }
    )
    estimated_track_seconds = _estimated_segmented_track_seconds(
        route,
        velocity_limit_m_s=velocity_m_s,
        acceleration_limit_m_s2=acceleration_m_s2,
    )
    track_timeout_seconds = max(180.0, estimated_track_seconds * 1.8 + 60.0)
    _write_json(
        run_dir / "launch_config.json",
        {
            "schema_version": "dronedream.school-map-px4-launch.v1",
            "partition": partition,
            "headless": not args.gui,
            "gazebo_world_file": "world.sdf" if args.gui else "world.physics.sdf",
            "world": WORLD_NAME,
            "vehicle": VEHICLE_ENTITY,
            "velocity_m_s": velocity_m_s,
            "acceleration_m_s2": acceleration_m_s2,
            "setpoint_rate_hz": setpoint_rate_hz,
            "estimated_track_seconds": estimated_track_seconds,
            "track_timeout_seconds": track_timeout_seconds,
            "px4_state_policy": "clean-copy-without-prior-params-dataman-logs-or-eeprom",
            "px4_trial_rootfs": str(trial_rootfs),
            "runtime_state_root": str(runtime_state_root),
        },
    )

    gazebo: subprocess.Popen[str] | None = None
    px4: subprocess.Popen[str] | None = None
    executor_process: subprocess.Popen[str] | None = None
    recorder: GazeboPoseRecorder | None = None
    payload_state_recorder: GazeboPayloadStateRecorder | None = None
    executor_return_code: int | None = None
    process_failure: str | None = None
    live_abort_reason: str | None = None
    payload_spawn_evidence: dict[str, Any] | None = None
    payload_spawned_at: float | None = None
    primitives = school_map_runtime_collision_primitives()
    with (
        (run_dir / "gazebo.log").open("w", encoding="utf-8") as gazebo_log,
        (run_dir / "px4.log").open("w", encoding="utf-8") as px4_log,
        (run_dir / "pose_recorder.stderr.log").open("w", encoding="utf-8") as pose_stderr,
        (run_dir / "payload_state.stderr.log").open("w", encoding="utf-8") as payload_state_stderr,
        (run_dir / "offboard_executor.stdout.log").open("w", encoding="utf-8") as executor_stdout,
        (run_dir / "offboard_executor.stderr.log").open("w", encoding="utf-8") as executor_stderr,
    ):
        try:
            gazebo_args = [gz_binary, "sim", "-r"]
            if not args.gui:
                gazebo_args.append("-s")
            world_file = map_dir / ("world.sdf" if args.gui else "world.physics.sdf")
            gazebo_args.append(str(world_file))
            gazebo = subprocess.Popen(  # noqa: S603 - resolved Gazebo executable.
                gazebo_args,
                env=env,
                stdout=gazebo_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            _wait_for_world(gz_binary, env, args.world_readiness_timeout_seconds)
            vehicle_spawn_evidence = _create_gazebo_entity(
                gz_binary,
                env,
                sdf_filename=vehicle_dir / "model.sdf",
                entity_name=VEHICLE_ENTITY,
                world_pose=model_root_world,
            )
            _write_json(run_dir / "vehicle_spawn.json", vehicle_spawn_evidence)
            payload_state_recorder = GazeboPayloadStateRecorder(
                gz_binary,
                env,
                run_dir / "payload_attachment_states.log",
                payload_state_stderr,
            )
            payload_state_recorder.start()
            recorder = GazeboPoseRecorder(
                gz_binary,
                env,
                run_dir / "gazebo_pose_samples.csv",
                pose_stderr,
            )
            recorder.start()
            px4 = subprocess.Popen(  # noqa: S603 - pinned PX4 executable and isolated rootfs.
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
            _wait_for_vehicle(gz_binary, env, args.vehicle_readiness_timeout_seconds)
            realtime_factor = _measure_realtime_factor(gz_binary, env)
            _write_json(run_dir / "gazebo_performance.json", realtime_factor)
            if realtime_factor["median"] < 0.85:
                raise RuntimeError(
                    "Gazebo median real-time factor is below the 0.85 execution gate: "
                    f"{realtime_factor['median']:.3f}"
                )
            executor_path = REPOSITORY_ROOT / "scripts/simulators/px4_offboard_track_executor.py"
            abort_file = run_dir / "live_abort.request.json"
            runtime_control_file = run_dir / "runtime_control.request.json"
            executor_args = [
                sys.executable,
                str(executor_path),
                "--run-dir",
                str(run_dir),
                "--track",
                str(track_path),
                "--params",
                str(params_path),
                "--vehicle",
                VEHICLE_MODEL,
                "--world",
                WORLD_NAME,
                "--abort-file",
                str(abort_file),
                "--runtime-control-file",
                str(runtime_control_file),
                "--setpoint-rate-hz",
                f"{setpoint_rate_hz:g}",
                "--takeoff-timeout-seconds",
                f"{args.takeoff_timeout_seconds:g}",
                "--takeoff-climb-rate-m-s",
                "0.7",
                "--track-timeout-seconds",
                f"{track_timeout_seconds:g}",
                "--landing-timeout-seconds",
                f"{args.landing_timeout_seconds:g}",
                "--takeoff-stable-window-seconds",
                "1.5",
                "--log",
                str(run_dir / "offboard_executor.log"),
            ]
            executor_process = subprocess.Popen(  # noqa: S603 - repository executor.
                executor_args,
                env=env,
                stdout=executor_stdout,
                stderr=executor_stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            executor_deadline = (
                time.monotonic() + track_timeout_seconds + args.takeoff_timeout_seconds + 180
            )
            off_route_started: float | None = None
            pause_evidence: dict[str, Any] | None = None
            route_progress_index = 0
            last_live_status_write = 0.0
            last_live_status_sample: GazeboPoseSample | None = None
            scene = get_scene("school-campus-v1")
            if scene is None or len(scene.reference_path) != len(route):
                raise RuntimeError("School Map live route metadata is unavailable")
            route_phases = [point.phase for point in scene.reference_path]
            runtime_control_revision = 0
            runtime_control_action: str | None = None
            while executor_process.poll() is None:
                if time.monotonic() >= executor_deadline:
                    live_abort_reason = "executor_wall_timeout"
                latest = recorder.latest_sample
                if latest is not None and live_abort_reason is None:
                    center = latest.envelope_center
                    if runtime_control_file.is_file():
                        (
                            candidate_revision,
                            candidate_action,
                            replacement_route,
                            replacement_phases,
                        ) = _read_runtime_control_request(runtime_control_file)
                        if candidate_revision > runtime_control_revision:
                            if replacement_route is not None and replacement_phases is not None:
                                prefix_end = min(route_progress_index + 1, len(route))
                                route = [*route[:prefix_end], *replacement_route]
                                route_phases = [
                                    *route_phases[:prefix_end],
                                    *replacement_phases,
                                ]
                            runtime_control_revision = candidate_revision
                            runtime_control_action = candidate_action
                    route_progress_index = _monotonic_route_progress_index(
                        center,
                        route,
                        route_progress_index,
                    )
                    if time.monotonic() - last_live_status_write >= 0.5:
                        vehicle_speed_m_s = 0.0
                        if last_live_status_sample is not None:
                            elapsed = latest.elapsed_s - last_live_status_sample.elapsed_s
                            if elapsed > 1e-6:
                                vehicle_speed_m_s = (
                                    math.dist(
                                        latest.model_root,
                                        last_live_status_sample.model_root,
                                    )
                                    / elapsed
                                )
                        _write_json(
                            run_dir / "mission_live_status.json",
                            {
                                "schema_version": "dronedream.school-map-mission-live.v1",
                                "status": "running",
                                "phase": (
                                    "holding"
                                    if runtime_control_action == "hold"
                                    else route_phases[route_progress_index]
                                ),
                                "route_index": route_progress_index,
                                "route_waypoint_count": len(route),
                                "progress": route_progress_index / max(1, len(route) - 1),
                                "vehicle_model_root_world_enu_m": latest.model_root,
                                "vehicle_envelope_center_world_enu_m": center,
                                "vehicle_speed_m_s": vehicle_speed_m_s,
                                "payload_spawned": payload_spawn_evidence is not None,
                                "payload_attached": (
                                    payload_state_recorder.attached_observed
                                    if payload_state_recorder is not None
                                    else False
                                ),
                                "abort_reason": live_abort_reason,
                                "runtime_control_revision": runtime_control_revision,
                                "runtime_control_action": runtime_control_action,
                            },
                        )
                        last_live_status_write = time.monotonic()
                        last_live_status_sample = latest
                    pickup_index = next(
                        (index for index, phase in enumerate(route_phases) if phase == "pickup"),
                        None,
                    )
                    if (
                        payload_spawn_evidence is None
                        and pickup_index is not None
                        and route_progress_index >= pickup_index
                        and math.dist(center, route[pickup_index]) <= PICKUP_PAYLOAD_SPAWN_RADIUS_M
                    ):
                        pickup_pause = _set_world_paused(gz_binary, env, paused=True)
                        if not pickup_pause["accepted"]:
                            raise RuntimeError(f"Gazebo rejected pickup pause: {pickup_pause}")
                        try:
                            paused_sample = recorder.latest_sample or latest
                            payload_world = (
                                paused_sample.model_root[0],
                                paused_sample.model_root[1],
                                paused_sample.model_root[2]
                                + TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M,
                            )
                            payload_spawn_evidence = _create_gazebo_entity(
                                gz_binary,
                                env,
                                sdf_filename=vehicle_dir / "takeout-payload.sdf",
                                entity_name=TAKEOUT_PAYLOAD_MODEL_NAME,
                                world_pose=payload_world,
                            )
                        finally:
                            pickup_resume = _set_world_paused(gz_binary, env, paused=False)
                        payload_spawn_evidence["world_pause"] = pickup_pause
                        payload_spawn_evidence["world_resume"] = pickup_resume
                        if not pickup_resume["accepted"]:
                            raise RuntimeError(f"Gazebo rejected pickup resume: {pickup_resume}")
                        payload_spawned_at = time.monotonic()
                        _write_json(run_dir / "payload_spawn.json", payload_spawn_evidence)
                    if (
                        payload_spawned_at is not None
                        and payload_state_recorder is not None
                        and not payload_state_recorder.attached_observed
                        and time.monotonic() - payload_spawned_at
                        >= PICKUP_PAYLOAD_ATTACHMENT_TIMEOUT_SECONDS
                    ):
                        live_abort_reason = "physical_payload_attachment_timeout"
                    route_error = _route_error(center, route)
                    if route_error > LIVE_ROUTE_ERROR_LIMIT_M:
                        off_route_started = off_route_started or time.monotonic()
                        if time.monotonic() - off_route_started >= LIVE_ROUTE_ERROR_GRACE_SECONDS:
                            live_abort_reason = (
                                "live_route_error_exceeded: "
                                f"error={route_error:.3f}m limit={LIVE_ROUTE_ERROR_LIMIT_M:.3f}m"
                            )
                    else:
                        off_route_started = None
                    live_clearance = _dynamic_safety_clearance(
                        [center],
                        primitives,
                        designated_landing_contact_center,
                    )
                    if live_clearance["unsafe_collision_count"]:
                        live_abort_reason = (
                            f"live_collision_penetration: {live_clearance['unsafe_collisions'][0]}"
                        )
                    elif (
                        live_clearance["designated_contact_sample_count"]
                        and not live_clearance["designated_pad_contact"]["within_solver_tolerance"]
                    ):
                        pad_contact = live_clearance["designated_pad_contact"]
                        live_abort_reason = (
                            "live_designated_pad_penetration: "
                            f"clearance={pad_contact['minimum_clearance_m']:.9f}m "
                            f"limit={pad_contact['solver_tolerance_m']:.9f}m"
                        )
                if live_abort_reason is not None:
                    pause_evidence = _set_world_paused(gz_binary, env, paused=True)
                    _write_json(
                        abort_file,
                        {
                            "schema_version": "dronedream.school-map-live-abort.v1",
                            "reason": live_abort_reason,
                            "world_paused": pause_evidence.get("accepted") is True,
                        },
                    )
                    try:
                        executor_process.wait(timeout=args.landing_timeout_seconds + 30)
                    except subprocess.TimeoutExpired:
                        _terminate_process_group(executor_process)
                    break
                time.sleep(0.2)
            executor_return_code = executor_process.wait(timeout=10)
            time.sleep(args.post_flight_observation_seconds)
            if live_abort_reason is None and abort_file.is_file():
                try:
                    live_abort_reason, _ = _read_live_abort_request(abort_file)
                except RuntimeError as exc:
                    live_abort_reason = f"invalid_live_abort_request: {exc}"
            if live_abort_reason is not None:
                process_failure = live_abort_reason
            elif executor_return_code != 0:
                process_failure = f"offboard executor exited with {executor_return_code}"
            _write_json(
                run_dir / "live_safety_gate.json",
                {
                    "schema_version": "dronedream.school-map-live-safety-gate.v1",
                    "route_error_limit_m": LIVE_ROUTE_ERROR_LIMIT_M,
                    "route_error_grace_seconds": LIVE_ROUTE_ERROR_GRACE_SECONDS,
                    "penetration_tolerance_m": DYNAMIC_PENETRATION_TOLERANCE_M,
                    "designated_pad_contact_tolerance_m": (DESIGNATED_PAD_CONTACT_TOLERANCE_M),
                    "abort_reason": live_abort_reason,
                    "world_pause": pause_evidence,
                    "status": "aborted" if live_abort_reason else "complete",
                },
            )
        except BaseException as exc:
            process_failure = f"{type(exc).__name__}: {exc}"
        finally:
            if executor_process is not None:
                _terminate_process_group(executor_process)
            if recorder is not None:
                recorder.stop()
            if payload_state_recorder is not None:
                payload_state_recorder.stop()
            if px4 is not None:
                _terminate_process_group(px4)
            if gazebo is not None:
                _terminate_process_group(gazebo)

    samples = recorder.samples if recorder is not None else []
    payload_samples = recorder.payload_samples if recorder is not None else []
    payload_states = payload_state_recorder.states if payload_state_recorder is not None else []
    evidence, verified = _evaluate(
        run_dir,
        samples,
        payload_samples,
        payload_states,
        payload_spawn_evidence,
        model_root_world,
        route,
        executor_return_code,
        process_failure,
    )
    _write_json(run_dir / "mission_evidence.json", evidence)
    _write_json(
        run_dir / "mission_live_status.json",
        {
            "schema_version": "dronedream.school-map-mission-live.v1",
            "status": (
                "verified"
                if verified
                else "aborted"
                if process_failure is not None and "abort" in process_failure.casefold()
                else "failed"
            ),
            "phase": "land" if verified else "abort",
            "route_index": len(route) - 1,
            "route_waypoint_count": len(route),
            "progress": 1.0 if verified else 0.0,
            "vehicle_model_root_world_enu_m": samples[-1].model_root if samples else None,
            "vehicle_envelope_center_world_enu_m": (
                samples[-1].envelope_center if samples else None
            ),
            "vehicle_speed_m_s": 0.0,
            "payload_spawned": payload_spawn_evidence is not None,
            "payload_attached": any(state == "attached" for _, state in payload_states),
            "abort_reason": process_failure,
        },
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
