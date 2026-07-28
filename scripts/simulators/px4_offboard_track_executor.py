#!/usr/bin/env python3
"""PX4 offboard trajectory executor for DroneDream real PX4/Gazebo runs.

This script is intended to run as a subprocess from local_px4_launch_wrapper.py.
It reads DroneDream reference and controller JSON files, builds an offboard
position setpoint schedule, and streams PositionNedYaw setpoints.

Coordinate mapping assumption (first implementation):
- DroneDream reference uses ENU-like x/y/z with z positive-up.
- PX4 offboard local frame uses NED north/east/down.
- Mapping: north=x, east=y, down=-z.

Controller parameters are applied by this executor's scheduling logic
(vel/accel-limited interpolation and progression), not PX4 internal parameters.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

MAX_REFERENCE_TRACK_POINTS = 10_000
MAX_SETPOINT_RATE_HZ = 100.0
MAX_SETPOINTS = 1_000_000
RUNTIME_EFFECT_SCHEMA_VERSION = "dronedream.scenario_runtime_effects.v1"


@dataclass(frozen=True)
class TrackPoint:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class ControllerParams:
    kp_xy: float
    kd_xy: float
    ki_xy: float
    vel_limit: float
    accel_limit: float
    disturbance_rejection: float


@dataclass(frozen=True)
class Setpoint:
    north_m: float
    east_m: float
    down_m: float
    yaw_deg: float


@dataclass(frozen=True)
class SetpointSchedulePlan:
    schedule: list[Setpoint]
    track_start_index: int
    track_end_index: int


class OffboardClientProtocol(Protocol):
    async def connect(self, connection_url: str) -> None: ...

    async def wait_until_ready(self, timeout_seconds: float) -> None: ...

    async def arm(self) -> None: ...

    async def set_position_ned(self, setpoint: Setpoint) -> None: ...

    async def start_offboard(self) -> None: ...

    async def stop_offboard(self) -> None: ...

    async def land(self) -> None: ...

    async def get_param_int(self, name: str) -> int: ...

    async def set_param_int(self, name: str, value: int) -> None: ...

    async def get_param_float(self, name: str) -> float: ...

    async def set_param_float(self, name: str, value: float) -> None: ...

    async def sample_battery(self, timeout_seconds: float) -> dict[str, float]: ...

    async def sample_gps_info(self, timeout_seconds: float) -> dict[str, int | str]: ...

    async def close(self) -> None: ...

class MavsdkOffboardClient:
    def __init__(self) -> None:
        try:
            from mavsdk import System
            from mavsdk.offboard import (
                OffboardError,
                PositionNedYaw,
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError("mavsdk is required for PX4 offboard execution") from exc

        self._system_cls = System
        self._position_cls = PositionNedYaw
        self._offboard_error_cls = OffboardError
        self._system: Any | None = None

    async def connect(self, connection_url: str) -> None:
        self._system = self._system_cls()
        await self._system.connect(system_address=connection_url)

    def _require_system(self) -> Any:
        if self._system is None:
            raise RuntimeError("PX4 offboard client is not connected")
        return self._system

    async def wait_until_ready(self, timeout_seconds: float) -> None:
        system = self._require_system()
        try:
            async with asyncio.timeout(timeout_seconds):
                connected = False
                async for state in system.core.connection_state():
                    if getattr(state, "is_connected", False):
                        connected = True
                        break
                if not connected:
                    raise RuntimeError("PX4 connection state stream ended before connecting")

                async for health in system.telemetry.health():
                    if bool(getattr(health, "is_global_position_ok", True)) and bool(
                        getattr(health, "is_home_position_ok", True)
                    ):
                        return
                raise RuntimeError("PX4 health stream ended before the vehicle became ready")
        except TimeoutError:
            raise TimeoutError(f"PX4 readiness timeout after {timeout_seconds}s") from None

    async def arm(self) -> None:
        await self._require_system().action.arm()

    async def set_position_ned(self, setpoint: Setpoint) -> None:
        await self._require_system().offboard.set_position_ned(
            self._position_cls(setpoint.north_m, setpoint.east_m, setpoint.down_m, setpoint.yaw_deg)
        )

    async def start_offboard(self) -> None:
        system = self._require_system()
        try:
            await system.offboard.start()
        except self._offboard_error_cls as exc:
            raise RuntimeError(f"offboard start failed: {exc}") from exc

    async def stop_offboard(self) -> None:
        if self._system is None:
            return
        try:
            await self._system.offboard.stop()
        except self._offboard_error_cls as exc:
            raise RuntimeError(f"offboard stop failed: {exc}") from exc

    async def land(self) -> None:
        await self._require_system().action.land()

    async def get_param_float(self, name: str) -> float:
        return float(await self._require_system().param.get_param_float(name))

    async def set_param_float(self, name: str, value: float) -> None:
        await self._require_system().param.set_param_float(name, value)

    async def get_param_int(self, name: str) -> int:
        return int(await self._require_system().param.get_param_int(name))

    async def set_param_int(self, name: str, value: int) -> None:
        await self._require_system().param.set_param_int(name, value)

    async def sample_battery(self, timeout_seconds: float) -> dict[str, float]:
        async def _sample() -> dict[str, float]:
            async for battery in self._require_system().telemetry.battery():
                return {
                    "remaining_percent": float(battery.remaining_percent),
                    "voltage_v": float(battery.voltage_v),
                }
            raise RuntimeError("PX4 battery telemetry stream ended without a sample")

        try:
            return await asyncio.wait_for(_sample(), timeout=timeout_seconds)
        except TimeoutError:
            raise TimeoutError(
                f"PX4 battery telemetry timeout after {timeout_seconds:g}s"
            ) from None

    async def sample_gps_info(self, timeout_seconds: float) -> dict[str, int | str]:
        async def _sample() -> dict[str, int | str]:
            async for gps_info in self._require_system().telemetry.gps_info():
                fix_type = gps_info.fix_type
                fix_value = int(getattr(fix_type, "value", fix_type))
                fix_name = str(getattr(fix_type, "name", fix_type))
                return {
                    "num_satellites": int(gps_info.num_satellites),
                    "fix_type": fix_value,
                    "fix_type_name": fix_name,
                }
            raise RuntimeError("PX4 GPS info telemetry stream ended without a sample")

        try:
            return await asyncio.wait_for(_sample(), timeout=timeout_seconds)
        except TimeoutError:
            raise TimeoutError(
                f"PX4 GPS info telemetry timeout after {timeout_seconds:g}s"
            ) from None

    async def close(self) -> None:
        system = self._system
        self._system = None
        if system is None:
            return
        stop_server = getattr(system, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()


class FakeOffboardClient:
    def __init__(self) -> None:
        self.connected = False
        self.armed = False
        self.offboard_started = False
        self.setpoints: list[Setpoint] = []
        self.landed = False
        self.closed = False
        self.int_params: dict[str, int] = {
            "SIM_GPS_USED": 10,
        }
        self.float_params: dict[str, float] = {
            "SIM_BAT_DRAIN": 60.0,
            "SIM_BAT_MIN_PCT": 50.0,
        }
        self.battery_samples: list[dict[str, float]] = [
            {"remaining_percent": 100.0, "voltage_v": 16.8}
        ]
        self.gps_info_samples: list[dict[str, int | str]] = [
            {"num_satellites": 10, "fix_type": 3, "fix_type_name": "FIX_3D"}
        ]

    async def connect(self, connection_url: str) -> None:
        _ = connection_url
        self.connected = True

    async def wait_until_ready(self, timeout_seconds: float) -> None:
        _ = timeout_seconds

    async def arm(self) -> None:
        self.armed = True

    async def set_position_ned(self, setpoint: Setpoint) -> None:
        self.setpoints.append(setpoint)

    async def start_offboard(self) -> None:
        self.offboard_started = True

    async def stop_offboard(self) -> None:
        self.offboard_started = False

    async def land(self) -> None:
        self.landed = True

    async def get_param_float(self, name: str) -> float:
        return self.float_params[name]

    async def set_param_float(self, name: str, value: float) -> None:
        self.float_params[name] = float(value)

    async def get_param_int(self, name: str) -> int:
        return self.int_params[name]

    async def set_param_int(self, name: str, value: int) -> None:
        self.int_params[name] = int(value)

    async def sample_battery(self, timeout_seconds: float) -> dict[str, float]:
        _ = timeout_seconds
        if len(self.battery_samples) > 1:
            return dict(self.battery_samples.pop(0))
        return dict(self.battery_samples[0])

    async def sample_gps_info(self, timeout_seconds: float) -> dict[str, int | str]:
        _ = timeout_seconds
        target_used = self.int_params["SIM_GPS_USED"]
        return {
            "num_satellites": target_used,
            "fix_type": 3 if target_used >= 4 else 0,
            "fix_type_name": "FIX_3D" if target_used >= 4 else "NO_GPS",
        }

    async def close(self) -> None:
        self.closed = True


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {raw!r}")


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    return float(raw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PX4 offboard track executor")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--track", required=True, type=Path)
    parser.add_argument("--params", required=True, type=Path)
    parser.add_argument("--vehicle", required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument(
        "--connection",
        default=os.environ.get("PX4_OFFBOARD_CONNECTION", "udp://:14540"),
    )
    parser.add_argument(
        "--setpoint-rate-hz",
        type=float,
        default=_parse_float(os.environ.get("PX4_OFFBOARD_SETPOINT_RATE_HZ"), default=10.0),
    )
    parser.add_argument(
        "--takeoff-timeout-seconds",
        type=float,
        default=_parse_float(os.environ.get("PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS"), default=30.0),
    )
    parser.add_argument(
        "--track-timeout-seconds",
        type=float,
        default=_parse_float(os.environ.get("PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS"), default=120.0),
    )
    parser.add_argument("--log", required=True, type=Path)
    return parser.parse_args(argv)


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip("\n") + "\n")


def _write_offboard_timing(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {value}")


def _load_scenario_effect_engine() -> Any:
    try:
        from app.simulator import scenario_effects as engine
    except ModuleNotFoundError:
        backend_root = Path(__file__).resolve().parents[2] / "backend"
        if not backend_root.is_dir():
            raise RuntimeError(
                "DroneDream backend package is required for flight-timed scenario effects"
            ) from None
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))
        from app.simulator import scenario_effects as engine
    return engine


def _load_runtime_effect_request() -> tuple[Any, dict[str, Any] | None, dict[str, Any] | None]:
    engine = _load_scenario_effect_engine()
    raw_path = os.environ.get("PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH", "").strip()
    if not raw_path:
        return engine, None, None
    request = engine.load_scenario_effect_request(Path(raw_path))
    return engine, request, engine.compile_bundled_runtime_profile(request)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def compile_fixed_duty_schedule(
    *,
    requested_rate: float,
    tick_count: int,
    execution_identity_sha256: str,
) -> list[bool]:
    engine = _load_scenario_effect_engine()
    try:
        raw_schedule: object = engine.compile_bundled_gps_dropout_schedule(
            requested_rate=requested_rate,
            tick_count=tick_count,
            execution_identity_sha256=execution_identity_sha256,
        )
    except engine.ScenarioEffectContractError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(raw_schedule, list) or any(
        not isinstance(item, bool) for item in raw_schedule
    ):
        raise RuntimeError("scenario engine returned an invalid GPS dropout schedule")
    return [item for item in raw_schedule if isinstance(item, bool)]


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _runtime_effect_records(
    engine: Any,
    request: dict[str, Any],
    profile: dict[str, Any],
    *,
    observations: dict[str, dict[str, Any]],
    status: str,
    error: str | None,
) -> list[dict[str, Any]]:
    requested_by_id = {effect["effect_id"]: effect for effect in request["effects"]}
    records: list[dict[str, Any]] = []
    for effect_id in profile["requested_effect_ids"]:
        effect = requested_by_id[effect_id]
        section = "gps_dropout" if effect_id in profile.get("gps_dropout", {}).get(
            "effect_ids", []
        ) else "battery"
        if status != "complete":
            reason = error or "flight-timed scenario effect did not complete"
            records.append(
                {
                    "effect_id": effect_id,
                    "mechanism": effect["mechanism"],
                    "status": "failed",
                    "capability": {
                        "status": "available",
                        "reason": reason,
                    },
                    "reason": reason,
                }
            )
            continue
        observation = observations.get(section)
        if observation is None:
            raise RuntimeError(f"runtime effect evidence omitted {section}")
        records.append(
            {
                "effect_id": effect_id,
                "mechanism": effect["mechanism"],
                "status": "applied",
                "capability": {
                    "status": "available",
                    "reason": (
                        "PX4 GPS availability parameter and telemetry verified the schedule"
                        if section == "gps_dropout"
                        else "PX4 parameter readback and battery telemetry verified the profile"
                    ),
                },
                "evidence": {
                    "requested_value_sha256": engine.scenario_effect_value_sha256(
                        effect["requested_value"]
                    ),
                    "compiled_runtime_profile": profile,
                    "verification": {
                        "status": "verified",
                        "method": (
                            "mavsdk_sim_gps_used_plus_gps_info_telemetry_and_reset"
                            if section == "gps_dropout"
                            else "mavsdk_parameter_readback_and_battery_telemetry"
                        ),
                        "observations": [observation],
                    },
                },
            }
        )
    return records


def _write_runtime_effect_artifact(
    engine: Any,
    request: dict[str, Any],
    profile: dict[str, Any],
    path: Path,
    *,
    observations: dict[str, dict[str, Any]],
    status: str,
    error: str | None = None,
) -> None:
    records = _runtime_effect_records(
        engine,
        request,
        profile,
        observations=observations,
        status=status,
        error=error,
    )
    payload = {
        "schema_version": RUNTIME_EFFECT_SCHEMA_VERSION,
        "request_sha256": request["request_sha256"],
        "compiled_runtime_profile": profile,
        "status": status,
        "error": error,
        "records": records,
    }
    _write_json_atomic(path, payload)


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a finite number") from None
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite number")
    return parsed


def load_reference_track(path: Path) -> list[TrackPoint]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_nonfinite_json,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
        raise ValueError("reference_track.json must be an object with points[]")
    if len(payload["points"]) > MAX_REFERENCE_TRACK_POINTS:
        raise ValueError(
            f"reference_track.json exceeds the {MAX_REFERENCE_TRACK_POINTS}-point limit"
        )
    points: list[TrackPoint] = []
    for idx, raw in enumerate(payload["points"]):
        if not isinstance(raw, dict):
            raise ValueError(f"reference point {idx} must be an object")
        points.append(
            TrackPoint(
                _finite_float(raw.get("x"), f"reference point {idx}.x"),
                _finite_float(raw.get("y"), f"reference point {idx}.y"),
                _finite_float(raw.get("z"), f"reference point {idx}.z"),
            )
        )
    if not points:
        raise ValueError("reference_track.json points[] cannot be empty")
    return points


def load_controller_params(path: Path) -> ControllerParams:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_nonfinite_json,
    )
    if not isinstance(payload, dict):
        raise ValueError("controller_params.json must be an object")
    params = ControllerParams(
        kp_xy=_finite_float(payload.get("kp_xy", 1.0), "kp_xy"),
        kd_xy=_finite_float(payload.get("kd_xy", 0.2), "kd_xy"),
        ki_xy=_finite_float(payload.get("ki_xy", 0.05), "ki_xy"),
        vel_limit=_finite_float(payload.get("vel_limit", 5.0), "vel_limit"),
        accel_limit=_finite_float(payload.get("accel_limit", 4.0), "accel_limit"),
        disturbance_rejection=_finite_float(
            payload.get("disturbance_rejection", 0.5),
            "disturbance_rejection",
        ),
    )
    if min(params.kp_xy, params.kd_xy, params.ki_xy) < 0:
        raise ValueError("controller gains must be non-negative")
    if params.vel_limit <= 0 or params.accel_limit <= 0:
        raise ValueError("vel_limit and accel_limit must be greater than zero")
    if not 0.0 <= params.disturbance_rejection <= 1.0:
        raise ValueError("disturbance_rejection must be between 0 and 1")
    return params


def compute_yaw_from_segment(prev_point: TrackPoint, next_point: TrackPoint) -> float:
    dx = next_point.x - prev_point.x
    dy = next_point.y - prev_point.y
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(dy, dx))


def enu_point_to_ned_setpoint(point: TrackPoint, yaw_deg: float) -> Setpoint:
    return Setpoint(north_m=point.x, east_m=point.y, down_m=-point.z, yaw_deg=yaw_deg)


def _interpolate_points(start: TrackPoint, end: TrackPoint, parts: int) -> list[TrackPoint]:
    result: list[TrackPoint] = []
    for i in range(1, parts + 1):
        ratio = i / parts
        result.append(
            TrackPoint(
                x=start.x + (end.x - start.x) * ratio,
                y=start.y + (end.y - start.y) * ratio,
                z=start.z + (end.z - start.z) * ratio,
            )
        )
    return result


def build_setpoint_schedule(
    points: list[TrackPoint], params: ControllerParams, rate_hz: float
) -> list[Setpoint]:
    return build_setpoint_schedule_plan(points, params, rate_hz).schedule


def build_setpoint_schedule_plan(
    points: list[TrackPoint], params: ControllerParams, rate_hz: float
) -> SetpointSchedulePlan:
    if not math.isfinite(rate_hz) or rate_hz <= 0 or rate_hz > MAX_SETPOINT_RATE_HZ:
        raise ValueError(f"rate_hz must be finite and in (0, {MAX_SETPOINT_RATE_HZ:g}]")
    if not points:
        raise ValueError("points cannot be empty")

    dt = 1.0 / rate_hz
    max_step = max(0.05, params.vel_limit * dt)
    takeoff = TrackPoint(0.0, 0.0, max(0.5, points[0].z))
    schedule: list[Setpoint] = []

    takeoff_hold_samples = max(3, int(rate_hz * 2.0))
    if takeoff_hold_samples > MAX_SETPOINTS:
        raise ValueError(f"setpoint schedule exceeds the {MAX_SETPOINTS}-sample limit")
    for _ in range(takeoff_hold_samples):
        schedule.append(enu_point_to_ned_setpoint(takeoff, yaw_deg=0.0))

    prev = takeoff
    smoothed_speed = 0.0
    for idx, point in enumerate(points):
        seg_dx = point.x - prev.x
        seg_dy = point.y - prev.y
        seg_dz = point.z - prev.z
        seg_dist = math.sqrt(seg_dx * seg_dx + seg_dy * seg_dy + seg_dz * seg_dz)
        speed_target = min(params.vel_limit, smoothed_speed + params.accel_limit * dt)
        smoothed_speed = speed_target
        step_limit = max(0.05, speed_target * dt)
        effective_step = min(max_step, step_limit)
        parts = max(1, int(math.ceil(seg_dist / effective_step)))
        if parts > MAX_SETPOINTS - len(schedule):
            raise ValueError(f"setpoint schedule exceeds the {MAX_SETPOINTS}-sample limit")
        yaw_deg = compute_yaw_from_segment(prev, point) if seg_dist > 1e-9 else 0.0
        for interp in _interpolate_points(prev, point, parts):
            schedule.append(enu_point_to_ned_setpoint(interp, yaw_deg=yaw_deg))
        prev = point
        if idx == len(points) - 1:
            final_hold_samples = max(2, int(rate_hz * 0.5))
            if final_hold_samples > MAX_SETPOINTS - len(schedule):
                raise ValueError(f"setpoint schedule exceeds the {MAX_SETPOINTS}-sample limit")
            for _ in range(final_hold_samples):
                schedule.append(enu_point_to_ned_setpoint(point, yaw_deg=yaw_deg))

    track_start_index = takeoff_hold_samples
    track_end_index = max(track_start_index, len(schedule) - 1)
    return SetpointSchedulePlan(
        schedule=schedule,
        track_start_index=track_start_index,
        track_end_index=track_end_index,
    )


async def _set_float_parameter_verified(
    client: OffboardClientProtocol,
    name: str,
    value: float,
) -> dict[str, float]:
    before = await client.get_param_float(name)
    await client.set_param_float(name, value)
    applied = await client.get_param_float(name)
    if not math.isclose(applied, value, rel_tol=1e-6, abs_tol=1e-6):
        raise RuntimeError(
            f"PX4 parameter {name} readback mismatch: requested={value:g}, applied={applied:g}"
        )
    return {"before": before, "requested": value, "applied": applied}


async def _set_int_parameter_verified(
    client: OffboardClientProtocol,
    name: str,
    value: int,
) -> dict[str, int]:
    before = await client.get_param_int(name)
    await client.set_param_int(name, value)
    applied = await client.get_param_int(name)
    if applied != value:
        raise RuntimeError(
            f"PX4 parameter {name} readback mismatch: requested={value}, applied={applied}"
        )
    return {"before": before, "requested": value, "applied": applied}


async def _set_gps_availability_verified(
    client: OffboardClientProtocol,
    *,
    satellites_used: int,
    unavailable: bool,
) -> dict[str, Any]:
    parameter = await _set_int_parameter_verified(
        client,
        "SIM_GPS_USED",
        satellites_used,
    )
    samples: list[dict[str, int | str]] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        sample = await client.sample_gps_info(
            min(1.0, max(0.01, deadline - time.monotonic()))
        )
        samples.append(sample)
        num_satellites = int(sample["num_satellites"])
        fix_type = int(sample["fix_type"])
        observed = (
            num_satellites < 4 and fix_type <= 1
            if unavailable
            else num_satellites >= 4 and fix_type >= 2
        )
        if observed:
            return {
                "parameter_name": "SIM_GPS_USED",
                "parameter": parameter,
                "expected_availability": "unavailable" if unavailable else "available",
                "telemetry_samples": samples,
                "physical_effect_verified": True,
            }
        await asyncio.sleep(0.1)
    expected = "unavailable" if unavailable else "available"
    raise RuntimeError(
        f"PX4 GPS telemetry did not become {expected} after SIM_GPS_USED="
        f"{satellites_used}; samples={samples!r}"
    )


async def _prepare_battery_profile(
    client: OffboardClientProtocol,
    profile: dict[str, Any],
    *,
    takeoff_hold_seconds: float,
) -> dict[str, Any]:
    target = float(profile["target_track_start_percent"])
    if target >= 100.0 - 1e-12:
        pretrack_drain_seconds = 86400.0
    else:
        pretrack_drain_seconds = max(
            1.0,
            min(86400.0, takeoff_hold_seconds / max(1e-9, 1.0 - target / 100.0)),
        )
    parameters = {
        "SIM_BAT_MIN_PCT": await _set_float_parameter_verified(
            client,
            "SIM_BAT_MIN_PCT",
            target,
        ),
        "SIM_BAT_DRAIN": await _set_float_parameter_verified(
            client,
            "SIM_BAT_DRAIN",
            pretrack_drain_seconds,
        ),
    }
    return {
        "target_track_start_percent": target,
        "takeoff_hold_seconds": takeoff_hold_seconds,
        "pretrack_drain_seconds": pretrack_drain_seconds,
        "pretrack_parameters": parameters,
    }


async def _transition_battery_at_track_start(
    client: OffboardClientProtocol,
    profile: dict[str, Any],
    prepared: dict[str, Any],
) -> dict[str, Any]:
    track_start_sample = await client.sample_battery(5.0)
    target = float(profile["target_track_start_percent"])
    sample_percent = float(track_start_sample["remaining_percent"])
    drain_seconds = float(prepared["pretrack_drain_seconds"])
    quantization_tolerance = 100.0 * 0.1 / max(1.0, drain_seconds)
    tolerance = max(5.0, quantization_tolerance + 2.0)
    if abs(sample_percent - target) > tolerance:
        raise RuntimeError(
            "PX4 battery did not reach the requested track-start state: "
            f"target={target:g}%, observed={sample_percent:g}%, tolerance={tolerance:g}%"
        )
    if bool(profile["voltage_sag"]):
        transition_values = {
            "SIM_BAT_MIN_PCT": 0.0,
            "SIM_BAT_DRAIN": float(profile["sag_drain_seconds"]),
        }
    else:
        transition_values = {
            "SIM_BAT_MIN_PCT": target,
            "SIM_BAT_DRAIN": float(profile["no_sag_hold_drain_seconds"]),
        }
    transition_parameters = {
        name: await _set_float_parameter_verified(client, name, value)
        for name, value in transition_values.items()
    }
    return {
        **prepared,
        "track_start_sample": track_start_sample,
        "track_start_tolerance_percent": tolerance,
        "track_parameters": transition_parameters,
    }


async def run_executor(
    client: OffboardClientProtocol,
    schedule: list[Setpoint],
    *,
    connection: str,
    takeoff_timeout_seconds: float,
    track_timeout_seconds: float,
    rate_hz: float,
    land_after: bool,
    log_path: Path,
    track_start_index: int = 0,
    track_end_index: int | None = None,
    timing_path: Path | None = None,
    scenario_engine: Any | None = None,
    scenario_request: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    runtime_evidence_path: Path | None = None,
) -> None:
    if not math.isfinite(rate_hz) or rate_hz <= 0 or rate_hz > MAX_SETPOINT_RATE_HZ:
        raise ValueError(f"rate_hz must be finite and in (0, {MAX_SETPOINT_RATE_HZ:g}]")
    for label, value in (
        ("takeoff_timeout_seconds", takeoff_timeout_seconds),
        ("track_timeout_seconds", track_timeout_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be finite and greater than zero")
    if not schedule:
        raise ValueError("setpoint schedule is empty")
    exec_start = time.monotonic()
    timing: dict[str, Any] = {
        "time_base": "executor_relative_seconds",
        "setpoint_count": len(schedule),
        "rate_hz": rate_hz,
    }
    track_end = (
        len(schedule) - 1
        if track_end_index is None
        else min(max(0, track_end_index), len(schedule) - 1)
    )
    track_start = min(max(0, track_start_index), track_end) if schedule else 0
    armed = False
    offboard_started = False
    offboard_stopped = False
    land_command_sent = False
    runtime_failure: str | None = None
    runtime_observations: dict[str, dict[str, Any]] = {}
    gps_transitions: list[dict[str, Any]] = []
    gps_reset_verified = False
    gps_value: dict[str, Any] | None = None
    gps_control_details: dict[str, Any] | None = None
    battery_details: dict[str, Any] | None = None
    gps_profile = runtime_profile.get("gps_dropout") if runtime_profile else None
    battery_profile = runtime_profile.get("battery") if runtime_profile else None
    gps_schedule: list[bool] = []
    gps_last_tick = -1
    gps_off = False
    if isinstance(gps_profile, dict):
        assert runtime_profile is not None
        track_sample_count = track_end - track_start + 1
        tick_period_s = float(gps_profile["tick_period_s"])
        tick_count = max(
            1,
            int(math.ceil(track_sample_count / rate_hz / tick_period_s)),
        )
        gps_schedule = compile_fixed_duty_schedule(
            requested_rate=float(gps_profile["requested_rate"]),
            tick_count=tick_count,
            execution_identity_sha256=str(runtime_profile["execution_identity_sha256"]),
        )
    try:
        await client.connect(connection)
        _log(log_path, f"connected via {connection}")
        await client.wait_until_ready(takeoff_timeout_seconds)
        if isinstance(gps_profile, dict):
            baseline_satellites = await client.get_param_int("SIM_GPS_USED")
            if baseline_satellites < 4:
                raise RuntimeError(
                    "PX4 SIM_GPS_USED baseline must be at least 4 satellites for "
                    f"deterministic GPS recovery, got {baseline_satellites}"
                )
            gps_control_details = {
                "parameter_name": "SIM_GPS_USED",
                "before": baseline_satellites,
                "dropout_value": 0,
                "recovery_value": baseline_satellites,
            }
            _log(
                log_path,
                f"SIM_GPS_USED baseline recorded as {baseline_satellites}",
            )
        if isinstance(battery_profile, dict):
            battery_details = await _prepare_battery_profile(
                client,
                battery_profile,
                takeoff_hold_seconds=max(1.0 / rate_hz, track_start / rate_hz),
            )
        await client.arm()
        armed = True
        _log(log_path, "armed")

        timing["takeoff_start_t"] = time.monotonic() - exec_start
        await client.set_position_ned(schedule[0])
        await client.start_offboard()
        offboard_started = True
        timing["offboard_start_t"] = time.monotonic() - exec_start
        _log(log_path, "offboard started")

        dt = 1.0 / rate_hz
        start = time.monotonic()
        for idx, setpoint in enumerate(schedule):
            if (time.monotonic() - start) > track_timeout_seconds:
                raise TimeoutError(f"track timeout after {track_timeout_seconds}s")
            if idx >= track_start and isinstance(gps_profile, dict):
                elapsed_track_seconds = (idx - track_start) / rate_hz
                tick_index = min(
                    len(gps_schedule) - 1,
                    int(elapsed_track_seconds / float(gps_profile["tick_period_s"])),
                )
                if tick_index != gps_last_tick:
                    gps_last_tick = tick_index
                    desired_off = gps_schedule[tick_index]
                    if desired_off != gps_off:
                        assert gps_control_details is not None
                        failure_type = "off" if desired_off else "ok"
                        target_satellites = (
                            int(gps_control_details["dropout_value"])
                            if desired_off
                            else int(gps_control_details["recovery_value"])
                        )
                        verification = await _set_gps_availability_verified(
                            client,
                            satellites_used=target_satellites,
                            unavailable=desired_off,
                        )
                        gps_off = desired_off
                        gps_transitions.append(
                            {
                                "tick_index": tick_index,
                                "track_time_s": elapsed_track_seconds,
                                "failure_type": failure_type,
                                "physical_effect_verified": True,
                                "verification": verification,
                            }
                        )
            await client.set_position_ned(setpoint)
            now_t = time.monotonic() - exec_start
            if idx == track_start:
                timing["track_start_t"] = now_t
                if isinstance(battery_profile, dict):
                    assert battery_details is not None
                    battery_details = await _transition_battery_at_track_start(
                        client,
                        battery_profile,
                        battery_details,
                    )
            if idx == track_end:
                timing["track_end_t"] = now_t
                if isinstance(battery_profile, dict):
                    assert battery_details is not None
                    track_end_sample = await client.sample_battery(5.0)
                    start_percent = float(
                        battery_details["track_start_sample"]["remaining_percent"]
                    )
                    end_percent = float(track_end_sample["remaining_percent"])
                    if bool(battery_profile["voltage_sag"]) and end_percent > start_percent + 0.5:
                        raise RuntimeError(
                            "PX4 battery telemetry increased during requested voltage sag: "
                            f"start={start_percent:g}%, end={end_percent:g}%"
                        )
                    battery_details["track_end_sample"] = track_end_sample
                    battery_details["observed_nonincrease"] = end_percent <= start_percent + 0.5
            await asyncio.sleep(dt)

        if isinstance(gps_profile, dict):
            assert gps_control_details is not None
            verification = await _set_gps_availability_verified(
                client,
                satellites_used=int(gps_control_details["recovery_value"]),
                unavailable=False,
            )
            gps_control_details["restore"] = verification
            gps_control_details["restore_verified"] = True
            gps_off = False
            gps_reset_verified = True
            gps_transitions.append(
                {
                    "tick_index": len(gps_schedule),
                    "track_time_s": max(0.0, (track_end - track_start + 1) / rate_hz),
                    "failure_type": "ok",
                    "physical_effect_verified": True,
                    "verification": verification,
                    "final_reset": True,
                }
            )
            gps_value = {
                "schedule_algorithm": gps_profile["schedule_algorithm"],
                "tick_period_s": gps_profile["tick_period_s"],
                "schedule": gps_schedule,
                "tick_count": len(gps_schedule),
                "off_tick_count": sum(gps_schedule),
                "realized_rate": sum(gps_schedule) / len(gps_schedule),
                "transitions": gps_transitions,
                "reset_verified": gps_reset_verified,
                "control_parameter": gps_control_details,
            }
        if isinstance(battery_profile, dict):
            assert battery_details is not None
            runtime_observations["battery"] = {
                "source": "mavsdk.param+telemetry/battery",
                "kind": "readback",
                "value": battery_details,
                "sha256": _canonical_sha256(battery_details),
            }
        await client.stop_offboard()
        offboard_stopped = True
        _log(log_path, "offboard stopped")
        if land_after:
            timing["land_start_t"] = time.monotonic() - exec_start
            await client.land()
            land_command_sent = True
            _log(log_path, "land command sent")
    except BaseException as exc:
        runtime_failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        reset_error: Exception | None = None
        if (
            isinstance(gps_profile, dict)
            and gps_control_details is not None
            and not gps_reset_verified
        ):
            try:
                restore = await _set_gps_availability_verified(
                    client,
                    satellites_used=int(gps_control_details["recovery_value"]),
                    unavailable=False,
                )
                gps_control_details["restore"] = restore
                gps_control_details["restore_verified"] = True
                gps_off = False
                gps_reset_verified = True
                _log(log_path, "SIM_GPS_USED restored during GPS cleanup")
            except Exception as exc:
                reset_error = exc
                gps_control_details["restore_verified"] = False
                gps_control_details["restore_error"] = f"{type(exc).__name__}: {exc}"
                _log(log_path, f"GPS availability cleanup reset failed: {exc}")
                if runtime_failure is None:
                    runtime_failure = f"{type(exc).__name__}: {exc}"
        if (
            gps_value is not None
            and gps_control_details is not None
            and gps_control_details.get("restore_verified") is True
        ):
            runtime_observations["gps_dropout"] = {
                "source": "mavsdk.param+telemetry/gps_info",
                "kind": "readback",
                "value": gps_value,
                "sha256": _canonical_sha256(gps_value),
            }
        if offboard_started and not offboard_stopped:
            try:
                await client.stop_offboard()
                _log(log_path, "offboard stopped during failure cleanup")
            except Exception as exc:
                _log(log_path, f"offboard failure cleanup could not stop offboard: {exc}")
        if armed and land_after and not land_command_sent:
            try:
                timing.setdefault("land_start_t", time.monotonic() - exec_start)
                await client.land()
                _log(log_path, "land command sent during failure cleanup")
            except Exception as exc:
                _log(log_path, f"offboard failure cleanup could not land: {exc}")
        try:
            if (
                runtime_profile is not None
                and scenario_engine is not None
                and scenario_request is not None
                and runtime_evidence_path is not None
            ):
                _write_runtime_effect_artifact(
                    scenario_engine,
                    scenario_request,
                    runtime_profile,
                    runtime_evidence_path,
                    observations=runtime_observations,
                    status="complete" if runtime_failure is None else "failed",
                    error=runtime_failure,
                )
            if timing_path is not None:
                _write_offboard_timing(timing_path, timing)
        finally:
            try:
                await client.close()
                _log(log_path, "offboard client closed")
            except Exception as exc:
                _log(log_path, f"offboard client cleanup failed: {exc}")
        reset_failure_text = (
            f"{type(reset_error).__name__}: {reset_error}"
            if reset_error is not None
            else None
        )
        if reset_error is not None and runtime_failure == reset_failure_text:
            raise RuntimeError(
                f"GPS availability cleanup reset failed: {reset_error}"
            ) from reset_error


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dry_run = _parse_bool(os.environ.get("PX4_OFFBOARD_DRY_RUN"), default=False)
    land_after = _parse_bool(os.environ.get("PX4_OFFBOARD_LAND_AFTER"), default=True)

    try:
        scenario_engine, scenario_request, runtime_profile = _load_runtime_effect_request()
        runtime_evidence_path = (
            args.run_dir / scenario_engine.RUNTIME_EVIDENCE_ARTIFACT_NAME
            if runtime_profile is not None
            else None
        )
        points = load_reference_track(args.track)
        params = load_controller_params(args.params)
        plan = build_setpoint_schedule_plan(points, params, args.setpoint_rate_hz)
        _log(
            args.log,
            f"vehicle={args.vehicle} world={args.world} points={len(points)} "
            f"setpoints={len(plan.schedule)}",
        )
        _log(
            args.log,
            "controller_params are applied by the offboard executor, not PX4 internal parameters",
        )

        if dry_run:
            _log(
                args.log,
                "PX4_OFFBOARD_DRY_RUN=true; executor exiting without MAVSDK command streaming",
            )
            dry_timing = {
                "time_base": "executor_relative_seconds",
                "setpoint_count": len(plan.schedule),
                "rate_hz": args.setpoint_rate_hz,
                "takeoff_start_t": 0.0,
                "offboard_start_t": 0.0,
                "track_start_t": plan.track_start_index / max(1e-6, args.setpoint_rate_hz),
                "track_end_t": plan.track_end_index / max(1e-6, args.setpoint_rate_hz),
            }
            _write_offboard_timing(args.run_dir / "offboard_timing.json", dry_timing)
            return 0

        client = MavsdkOffboardClient()
        asyncio.run(
            run_executor(
                client,
                plan.schedule,
                connection=args.connection,
                takeoff_timeout_seconds=args.takeoff_timeout_seconds,
                track_timeout_seconds=args.track_timeout_seconds,
                rate_hz=args.setpoint_rate_hz,
                land_after=land_after,
                log_path=args.log,
                track_start_index=plan.track_start_index,
                track_end_index=plan.track_end_index,
                timing_path=args.run_dir / "offboard_timing.json",
                scenario_engine=scenario_engine,
                scenario_request=scenario_request,
                runtime_profile=runtime_profile,
                runtime_evidence_path=runtime_evidence_path,
            )
        )
        _log(args.log, "executor completed successfully")
        return 0
    except RuntimeError as exc:
        _log(args.log, str(exc))
        if "mavsdk is required for PX4 offboard execution" in str(exc):
            print("mavsdk is required for PX4 offboard execution", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        _log(args.log, f"executor failure: {exc}")
        print(f"px4 offboard executor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
