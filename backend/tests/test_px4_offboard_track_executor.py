from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

EXECUTOR = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "simulators"
    / "px4_offboard_track_executor.py"
)
SPEC = importlib.util.spec_from_file_location("px4_offboard_track_executor", EXECUTOR)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_reference_track_and_controller_params(tmp_path: Path):
    track = _write_json(
        tmp_path / "reference_track.json",
        {"points": [{"x": 1.0, "y": 2.0, "z": 3.0}]},
    )
    params = _write_json(
        tmp_path / "controller_params.json",
        {
            "kp_xy": 1.2,
            "kd_xy": 0.3,
            "ki_xy": 0.1,
            "vel_limit": 2.5,
            "accel_limit": 1.0,
            "disturbance_rejection": 0.7,
        },
    )

    points = executor.load_reference_track(track)
    cfg = executor.load_controller_params(params)

    assert points[0].x == 1.0 and points[0].z == 3.0
    assert cfg.vel_limit == 2.5


def test_build_setpoint_schedule_respects_vel_limit_and_takeoff_phase():
    points = [executor.TrackPoint(5.0, 0.0, 3.0), executor.TrackPoint(7.0, 0.0, 3.0)]
    params = executor.ControllerParams(
        1.0,
        0.2,
        0.1,
        vel_limit=1.0,
        accel_limit=1.0,
        disturbance_rejection=0.5,
    )
    rate_hz = 10.0

    schedule = executor.build_setpoint_schedule(points, params, rate_hz)

    assert len(schedule) > 2
    assert schedule[0].north_m == pytest.approx(0.0)
    assert schedule[0].down_m == pytest.approx(-3.0)

    max_step = params.vel_limit / rate_hz
    for a, b in zip(schedule, schedule[1:], strict=False):
        d = (
            (b.north_m - a.north_m) ** 2
            + (b.east_m - a.east_m) ** 2
            + (b.down_m - a.down_m) ** 2
        ) ** 0.5
        assert d <= max_step + 1e-6 or d <= 0.11


def test_coordinate_conversion_maps_positive_up_to_ned_down():
    sp = executor.enu_point_to_ned_setpoint(executor.TrackPoint(1.0, -2.0, 3.5), yaw_deg=45.0)
    assert sp.north_m == 1.0
    assert sp.east_m == -2.0
    assert sp.down_m == -3.5


def test_fake_offboard_client_receives_setpoints_in_order(tmp_path: Path):
    client = executor.FakeOffboardClient()
    schedule = [
        executor.Setpoint(0.0, 0.0, -3.0, 0.0),
        executor.Setpoint(1.0, 0.0, -3.0, 0.0),
        executor.Setpoint(2.0, 0.0, -3.0, 0.0),
    ]
    log_path = tmp_path / "offboard.log"

    asyncio.run(
        executor.run_executor(
            client,
            schedule,
            connection="udp://:14540",
            takeoff_timeout_seconds=1.0,
            track_timeout_seconds=5.0,
            rate_hz=100.0,
            land_after=True,
            log_path=log_path,
        )
    )

    assert [sp.north_m for sp in client.setpoints[-3:]] == [0.0, 1.0, 2.0]
    assert client.landed is True


def test_mavsdk_missing_exits_non_zero_with_clear_message(tmp_path: Path):
    run_dir = tmp_path / "run"
    track = _write_json(tmp_path / "track.json", {"points": [{"x": 1.0, "y": 0.0, "z": 3.0}]})
    params = _write_json(tmp_path / "params.json", {"vel_limit": 1.0, "accel_limit": 1.0})
    log_path = run_dir / "offboard.log"

    proc = subprocess.run(
        [
            sys.executable,
            str(EXECUTOR),
            "--run-dir",
            str(run_dir),
            "--track",
            str(track),
            "--params",
            str(params),
            "--vehicle",
            "x500",
            "--world",
            "default",
            "--connection",
            "udp://:14540",
            "--setpoint-rate-hz",
            "10",
            "--takeoff-timeout-seconds",
            "1",
            "--track-timeout-seconds",
            "1",
            "--log",
            str(log_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "mavsdk is required for PX4 offboard execution" in (proc.stderr + proc.stdout)
