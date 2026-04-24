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
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


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


class MavsdkOffboardClient:
    def __init__(self) -> None:
        try:
            from mavsdk import System
            from mavsdk.offboard import OffboardError, PositionNedYaw
        except ModuleNotFoundError as exc:
            raise RuntimeError("mavsdk is required for PX4 offboard execution") from exc

        self._system_cls = System
        self._position_cls = PositionNedYaw
        self._offboard_error_cls = OffboardError
        self._system: Any | None = None

    async def connect(self, connection_url: str) -> None:
        self._system = self._system_cls()
        await self._system.connect(system_address=connection_url)

    async def wait_until_ready(self, timeout_seconds: float) -> None:
        assert self._system is not None
        start = time.monotonic()
        async for state in self._system.core.connection_state():
            if getattr(state, "is_connected", False):
                break
            if time.monotonic() - start > timeout_seconds:
                raise TimeoutError(f"PX4 connection timeout after {timeout_seconds}s")
        async for health in self._system.telemetry.health():
            if bool(getattr(health, "is_global_position_ok", True)) and bool(getattr(health, "is_home_position_ok", True)):
                return
            if time.monotonic() - start > timeout_seconds:
                raise TimeoutError(f"PX4 health timeout after {timeout_seconds}s")

    async def arm(self) -> None:
        assert self._system is not None
        await self._system.action.arm()

    async def set_position_ned(self, setpoint: Setpoint) -> None:
        assert self._system is not None
        await self._system.offboard.set_position_ned(
            self._position_cls(setpoint.north_m, setpoint.east_m, setpoint.down_m, setpoint.yaw_deg)
        )

    async def start_offboard(self) -> None:
        assert self._system is not None
        try:
            await self._system.offboard.start()
        except self._offboard_error_cls as exc:
            raise RuntimeError(f"offboard start failed: {exc}") from exc

    async def stop_offboard(self) -> None:
        if self._system is None:
            return
        try:
            await self._system.offboard.stop()
        except Exception:
            return

    async def land(self) -> None:
        assert self._system is not None
        await self._system.action.land()


class FakeOffboardClient:
    def __init__(self) -> None:
        self.connected = False
        self.armed = False
        self.offboard_started = False
        self.setpoints: list[Setpoint] = []
        self.landed = False

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


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    parser.add_argument("--connection", default=os.environ.get("PX4_OFFBOARD_CONNECTION", "udp://:14540"))
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


def load_reference_track(path: Path) -> list[TrackPoint]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
        raise ValueError("reference_track.json must be an object with points[]")
    points: list[TrackPoint] = []
    for idx, raw in enumerate(payload["points"]):
        if not isinstance(raw, dict):
            raise ValueError(f"reference point {idx} must be an object")
        points.append(TrackPoint(float(raw["x"]), float(raw["y"]), float(raw["z"])))
    if not points:
        raise ValueError("reference_track.json points[] cannot be empty")
    return points


def load_controller_params(path: Path) -> ControllerParams:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("controller_params.json must be an object")
    return ControllerParams(
        kp_xy=float(payload.get("kp_xy", 1.0)),
        kd_xy=float(payload.get("kd_xy", 0.2)),
        ki_xy=float(payload.get("ki_xy", 0.05)),
        vel_limit=max(0.1, float(payload.get("vel_limit", 5.0))),
        accel_limit=max(0.1, float(payload.get("accel_limit", 4.0))),
        disturbance_rejection=float(payload.get("disturbance_rejection", 0.5)),
    )


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


def build_setpoint_schedule(points: list[TrackPoint], params: ControllerParams, rate_hz: float) -> list[Setpoint]:
    return build_setpoint_schedule_plan(points, params, rate_hz).schedule


def build_setpoint_schedule_plan(points: list[TrackPoint], params: ControllerParams, rate_hz: float) -> SetpointSchedulePlan:
    if rate_hz <= 0:
        raise ValueError("rate_hz must be > 0")
    if not points:
        raise ValueError("points cannot be empty")

    dt = 1.0 / rate_hz
    max_step = max(0.05, params.vel_limit * dt)
    takeoff = TrackPoint(0.0, 0.0, max(0.5, points[0].z))
    schedule: list[Setpoint] = []

    takeoff_hold_samples = max(3, int(rate_hz * 2.0))
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
        yaw_deg = compute_yaw_from_segment(prev, point) if seg_dist > 1e-9 else 0.0
        for interp in _interpolate_points(prev, point, parts):
            schedule.append(enu_point_to_ned_setpoint(interp, yaw_deg=yaw_deg))
        prev = point
        if idx == len(points) - 1:
            for _ in range(max(2, int(rate_hz * 0.5))):
                schedule.append(enu_point_to_ned_setpoint(point, yaw_deg=yaw_deg))

    track_start_index = takeoff_hold_samples
    track_end_index = max(track_start_index, len(schedule) - 1)
    return SetpointSchedulePlan(
        schedule=schedule,
        track_start_index=track_start_index,
        track_end_index=track_end_index,
    )


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
) -> None:
    exec_start = time.monotonic()
    timing: dict[str, Any] = {
        "time_base": "executor_relative_seconds",
        "setpoint_count": len(schedule),
        "rate_hz": rate_hz,
    }
    track_end = len(schedule) - 1 if track_end_index is None else min(max(0, track_end_index), len(schedule) - 1)
    track_start = min(max(0, track_start_index), track_end) if schedule else 0
    await client.connect(connection)
    _log(log_path, f"connected via {connection}")
    await client.wait_until_ready(takeoff_timeout_seconds)
    await client.arm()
    _log(log_path, "armed")

    if not schedule:
        raise ValueError("setpoint schedule is empty")

    try:
        timing["takeoff_start_t"] = time.monotonic() - exec_start
        await client.set_position_ned(schedule[0])
        await client.start_offboard()
        timing["offboard_start_t"] = time.monotonic() - exec_start
        _log(log_path, "offboard started")

        dt = 1.0 / rate_hz
        start = time.monotonic()
        for idx, setpoint in enumerate(schedule):
            if (time.monotonic() - start) > track_timeout_seconds:
                raise TimeoutError(f"track timeout after {track_timeout_seconds}s")
            await client.set_position_ned(setpoint)
            now_t = time.monotonic() - exec_start
            if idx == track_start:
                timing["track_start_t"] = now_t
            if idx == track_end:
                timing["track_end_t"] = now_t
            await asyncio.sleep(dt)

        await client.stop_offboard()
        _log(log_path, "offboard stopped")
        if land_after:
            timing["land_start_t"] = time.monotonic() - exec_start
            await client.land()
            _log(log_path, "land command sent")
    finally:
        if timing_path is not None:
            _write_offboard_timing(timing_path, timing)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dry_run = _parse_bool(os.environ.get("PX4_OFFBOARD_DRY_RUN"), default=False)
    land_after = _parse_bool(os.environ.get("PX4_OFFBOARD_LAND_AFTER"), default=True)

    try:
        points = load_reference_track(args.track)
        params = load_controller_params(args.params)
        plan = build_setpoint_schedule_plan(points, params, args.setpoint_rate_hz)
        _log(args.log, f"vehicle={args.vehicle} world={args.world} points={len(points)} setpoints={len(plan.schedule)}")
        _log(
            args.log,
            "controller_params are applied by the offboard executor, not PX4 internal parameters",
        )

        if dry_run:
            _log(args.log, "PX4_OFFBOARD_DRY_RUN=true; executor exiting without MAVSDK command streaming")
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
