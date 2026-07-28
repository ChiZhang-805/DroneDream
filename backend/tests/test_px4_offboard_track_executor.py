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


def test_executor_boolean_environment_parser_rejects_typos():
    assert executor._parse_bool("true", default=False) is True
    assert executor._parse_bool("OFF", default=True) is False
    with pytest.raises(ValueError, match="invalid boolean value"):
        executor._parse_bool("tru", default=False)


def test_executor_rejects_nonfinite_track_coordinates(tmp_path: Path):
    track = tmp_path / "reference_track.json"
    track.write_text('{"points":[{"x":NaN,"y":0,"z":3}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-standard JSON numeric constant"):
        executor.load_reference_track(track)


@pytest.mark.parametrize(
    "override, expected_error",
    [
        ({"kp_xy": -0.1}, "controller gains must be non-negative"),
        ({"vel_limit": 0}, "vel_limit and accel_limit must be greater than zero"),
        ({"accel_limit": -1}, "vel_limit and accel_limit must be greater than zero"),
        ({"disturbance_rejection": 1.1}, "disturbance_rejection must be between 0 and 1"),
    ],
)
def test_executor_rejects_unsafe_controller_params(
    tmp_path: Path,
    override: dict[str, float],
    expected_error: str,
):
    payload = {
        "kp_xy": 1.0,
        "kd_xy": 0.2,
        "ki_xy": 0.05,
        "vel_limit": 5.0,
        "accel_limit": 4.0,
        "disturbance_rejection": 0.5,
        **override,
    }
    params = _write_json(tmp_path / "controller_params.json", payload)
    with pytest.raises(ValueError, match=expected_error):
        executor.load_controller_params(params)


def test_executor_rejects_an_unbounded_setpoint_schedule():
    params = executor.ControllerParams(1.0, 0.2, 0.05, 0.1, 0.1, 0.5)
    with pytest.raises(ValueError, match="setpoint schedule exceeds"):
        executor.build_setpoint_schedule(
            [executor.TrackPoint(1_000_000.0, 0.0, 3.0)],
            params,
            100.0,
        )


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
            (b.north_m - a.north_m) ** 2 + (b.east_m - a.east_m) ** 2 + (b.down_m - a.down_m) ** 2
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
    timing_path = tmp_path / "offboard_timing.json"

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
            track_start_index=1,
            track_end_index=2,
            timing_path=timing_path,
        )
    )

    assert [sp.north_m for sp in client.setpoints[-3:]] == [0.0, 1.0, 2.0]
    assert client.landed is True
    assert client.closed is True
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["time_base"] == "executor_relative_seconds"
    assert timing["track_start_t"] <= timing["track_end_t"]


def test_executor_stops_offboard_and_lands_after_streaming_failure(tmp_path: Path):
    class FailingClient(executor.FakeOffboardClient):
        async def set_position_ned(self, setpoint: executor.Setpoint) -> None:
            await super().set_position_ned(setpoint)
            if self.offboard_started:
                raise RuntimeError("injected setpoint failure")

    client = FailingClient()
    schedule = [
        executor.Setpoint(0.0, 0.0, -3.0, 0.0),
        executor.Setpoint(1.0, 0.0, -3.0, 0.0),
    ]
    log_path = tmp_path / "offboard.log"

    with pytest.raises(RuntimeError, match="injected setpoint failure"):
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

    assert client.offboard_started is False
    assert client.landed is True
    assert client.closed is True
    assert "offboard stopped during failure cleanup" in log_path.read_text(encoding="utf-8")
    assert "land command sent during failure cleanup" in log_path.read_text(encoding="utf-8")


def test_executor_rejects_empty_schedule_before_arming(tmp_path: Path):
    client = executor.FakeOffboardClient()
    with pytest.raises(ValueError, match="setpoint schedule is empty"):
        asyncio.run(
            executor.run_executor(
                client,
                [],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=5.0,
                rate_hz=10.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
            )
        )
    assert client.connected is False
    assert client.armed is False


def test_mavsdk_readiness_timeout_applies_when_stream_emits_nothing():
    class SilentCore:
        async def connection_state(self):
            await asyncio.sleep(1.0)
            if False:  # pragma: no cover - makes this an async generator
                yield None

    class UnusedTelemetry:
        async def health(self):
            if False:  # pragma: no cover - makes this an async generator
                yield None

    class SilentSystem:
        core = SilentCore()
        telemetry = UnusedTelemetry()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SilentSystem()
    with pytest.raises(TimeoutError, match="PX4 readiness timeout"):
        asyncio.run(client.wait_until_ready(0.01))


def test_mavsdk_actions_fail_cleanly_before_connect():
    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = None

    with pytest.raises(RuntimeError, match="offboard client is not connected"):
        asyncio.run(client.arm())


def test_mavsdk_close_stops_embedded_server_and_clears_system():
    class SystemStub:
        def __init__(self) -> None:
            self.stopped = False

        def _stop_mavsdk_server(self) -> None:
            self.stopped = True

    system = SystemStub()
    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = system

    asyncio.run(client.close())

    assert system.stopped is True
    assert client._system is None


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
