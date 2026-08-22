from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.simulator import scenario_effects

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


@pytest.mark.parametrize("world_paused", [False, True])
def test_external_abort_contract_distinguishes_operator_and_paused_world(
    tmp_path: Path,
    world_paused: bool,
) -> None:
    abort_path = _write_json(
        tmp_path / "abort.json",
        {
            "schema_version": "dronedream.school-map-live-abort.v1",
            "reason": "operator_abort" if not world_paused else "live_collision_penetration",
            "world_paused": world_paused,
        },
    )

    reason, observed_world_paused = executor._read_external_abort_request(abort_path)

    assert reason
    assert observed_world_paused is world_paused


def test_external_abort_contract_rejects_missing_world_pause_state(tmp_path: Path) -> None:
    abort_path = _write_json(tmp_path / "abort.json", {"reason": "operator_abort"})

    with pytest.raises(RuntimeError, match="world_paused flag"):
        executor._read_external_abort_request(abort_path)


def _runtime_control_payload(
    *,
    revision: int,
    action: str,
    route: list[dict[str, float]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "dronedream.autonomy.runtime-control.v1",
        "revision": revision,
        "action": action,
        "runtime_session_id": "runtime-0123456789abcdef01234567",
        "mission_revision": 2 if action == "replace_route" else 1,
        "contract_id": "contract-runtime-test",
        "issued_at": "2026-08-21T00:00:00Z",
        "reason_codes": ["operator.interruption-hold"],
        "route": route,
    }


@pytest.mark.parametrize("action", ["hold", "resume"])
def test_runtime_control_reader_accepts_route_free_hold_and_resume(
    tmp_path: Path,
    action: str,
) -> None:
    path = _write_json(
        tmp_path / "runtime_control.request.json",
        _runtime_control_payload(revision=1, action=action),
    )

    request = executor._read_runtime_control_request(path)

    assert request.revision == 1
    assert request.action == action
    assert request.route is None


def test_runtime_control_reader_accepts_a_bounded_replacement_route(tmp_path: Path) -> None:
    route = [
        {"x": 1.0, "y": 2.0, "z": 3.0, "speed_limit_mps": 0.6},
        {"x": 2.0, "y": 2.5, "z": 3.0, "speed_limit_mps": 0.8},
    ]
    path = _write_json(
        tmp_path / "runtime_control.request.json",
        _runtime_control_payload(revision=2, action="replace_route", route=route),
    )

    request = executor._read_runtime_control_request(path)

    assert request.action == "replace_route"
    assert request.route == [
        executor.TrackPoint(1.0, 2.0, 3.0, 0.6),
        executor.TrackPoint(2.0, 2.5, 3.0, 0.8),
    ]


@pytest.mark.parametrize(
    "override, expected_error",
    [
        ({"revision": True}, "runtime control revision is invalid"),
        ({"action": "teleport"}, "runtime control action is invalid"),
        ({"contract_id": "short"}, "runtime control contract id is invalid"),
        ({"action": "hold", "route": []}, "must not include a route"),
        ({"action": "replace_route", "route": []}, "replacement route is invalid"),
        (
            {
                "action": "replace_route",
                "route": [
                    {"x": 0.0, "y": 0.0, "z": 1.0},
                    {"x": float("nan"), "y": 0.0, "z": 1.0},
                ],
            },
            "must be a finite number",
        ),
    ],
)
def test_runtime_control_reader_rejects_invalid_or_unsafe_requests(
    tmp_path: Path,
    override: dict[str, object],
    expected_error: str,
) -> None:
    payload = _runtime_control_payload(revision=1, action="hold")
    payload.update(override)
    path = _write_json(tmp_path / "runtime_control.request.json", payload)

    with pytest.raises(RuntimeError, match=expected_error):
        executor._read_runtime_control_request(path)


def test_runtime_control_reader_rejects_oversized_requests(tmp_path: Path) -> None:
    path = tmp_path / "runtime_control.request.json"
    path.write_text("x" * (executor.MAX_RUNTIME_CONTROL_BYTES + 1), encoding="utf-8")

    with pytest.raises(RuntimeError, match="runtime control request is oversized"):
        executor._read_runtime_control_request(path)


def test_runtime_replan_schedule_starts_at_the_held_setpoint_and_respects_bounds() -> None:
    current = executor.Setpoint(1.0, -2.0, -3.0, 15.0)
    route = [
        executor.TrackPoint(1.0, -2.0, 3.0, 0.5),
        executor.TrackPoint(2.0, -1.0, 3.0, 0.5),
    ]
    params = executor.ControllerParams(1.0, 0.2, 0.05, 0.5, 0.4, 0.5)
    rate_hz = 20.0

    schedule = executor._runtime_replan_schedule(current, route, params, rate_hz)

    assert schedule[0].north_m == pytest.approx(current.north_m)
    assert schedule[0].east_m == pytest.approx(current.east_m)
    assert schedule[0].down_m == pytest.approx(current.down_m)
    assert schedule[-1].north_m == pytest.approx(2.0)
    assert schedule[-1].east_m == pytest.approx(-1.0)
    assert schedule[-1].down_m == pytest.approx(-3.0)
    assert (
        max(
            math.dist(
                (first.north_m, first.east_m, first.down_m),
                (second.north_m, second.east_m, second.down_m),
            )
            for first, second in zip(schedule, schedule[1:], strict=False)
        )
        <= params.vel_limit / rate_hz + 1e-6
    )


def test_executor_honors_preexisting_abort_before_connecting_or_commanding(
    tmp_path: Path,
) -> None:
    abort_path = _write_json(
        tmp_path / "abort.json",
        {"reason": "operator_abort", "world_paused": False},
    )
    timing_path = tmp_path / "offboard_timing.json"
    client = executor.FakeOffboardClient()

    with pytest.raises(executor.ExternalSafetyAbort, match="operator_abort"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -1.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
                abort_file=abort_path,
            )
        )

    assert client.connected is False
    assert client.armed is False
    assert client.setpoints == []
    assert client.landed is False
    assert client.closed is True
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["external_abort"] == {
        "reason": "operator_abort",
        "world_paused": False,
    }


def test_executor_rejects_oversized_preflight_abort_before_connecting(tmp_path: Path) -> None:
    abort_path = tmp_path / "abort.json"
    abort_path.write_text("x" * (executor.MAX_ABORT_REQUEST_BYTES + 1), encoding="utf-8")
    client = executor.FakeOffboardClient()

    with pytest.raises(RuntimeError, match="abort request is oversized"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -1.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                abort_file=abort_path,
            )
        )

    assert client.connected is False
    assert client.armed is False
    assert client.setpoints == []
    assert client.closed is True


def test_executor_polls_abort_while_waiting_for_preflight_readiness(tmp_path: Path) -> None:
    abort_path = tmp_path / "abort.json"

    class ReadinessAbortClient(executor.FakeOffboardClient):
        async def wait_until_ready(self, timeout_seconds: float) -> executor.TelemetryHealth:
            _ = timeout_seconds
            _write_json(abort_path, {"reason": "operator_abort", "world_paused": False})
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    client = ReadinessAbortClient()
    with pytest.raises(executor.ExternalSafetyAbort, match="operator_abort"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -1.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                abort_file=abort_path,
            )
        )

    assert client.connected is True
    assert client.armed is False
    assert client.setpoints == []
    assert client.landed is False
    assert client.closed is True


def test_executor_does_not_start_offboard_when_abort_arrives_with_arm_ack(
    tmp_path: Path,
) -> None:
    abort_path = tmp_path / "abort.json"

    class ArmBoundaryAbortClient(executor.FakeOffboardClient):
        async def arm(self) -> None:
            await super().arm()
            _write_json(abort_path, {"reason": "operator_abort", "world_paused": False})

    client = ArmBoundaryAbortClient()
    with pytest.raises(executor.ExternalSafetyAbort, match="operator_abort"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -1.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                abort_file=abort_path,
            )
        )

    assert client.armed is True
    assert client.offboard_started is False
    assert client.landed is True
    assert client.closed is True


@pytest.mark.parametrize("world_paused", [False, True])
def test_executor_stops_takeoff_commands_when_external_abort_appears(
    tmp_path: Path,
    world_paused: bool,
) -> None:
    abort_path = tmp_path / "abort.json"

    class TakeoffAbortClient(executor.FakeOffboardClient):
        sample_calls = 0
        setpoint_count_at_abort: int | None = None

        async def sample_position_velocity_ned(
            self,
            timeout_seconds: float,
        ) -> executor.PositionVelocityNed:
            _ = timeout_seconds
            self.sample_calls += 1
            if self.sample_calls == 1:
                return executor.PositionVelocityNed(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            _write_json(
                abort_path,
                {"reason": "live_collision_penetration", "world_paused": world_paused},
            )
            self.setpoint_count_at_abort = len(self.setpoints)
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    timing_path = tmp_path / "offboard_timing.json"
    client = TakeoffAbortClient()
    with pytest.raises(executor.ExternalSafetyAbort, match="live_collision_penetration"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -1.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
                abort_file=abort_path,
            )
        )

    assert client.armed is True
    assert client.offboard_started is False
    assert client.setpoint_count_at_abort is not None
    assert len(client.setpoints) == client.setpoint_count_at_abort
    assert client.landed is (not world_paused)
    assert client.closed is True
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["takeoff_gate"]["failure_reason"] == "external_safety_abort"
    assert timing["external_abort"]["world_paused"] is world_paused
    expected_land = (
        "suppressed_world_paused_external_safety_abort"
        if world_paused
        else "confirmed_on_ground_during_failure_cleanup"
    )
    assert timing["cleanup"]["land"] == expected_land


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


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_executor_float_environment_parser_rejects_nonfinite_values(raw: str):
    with pytest.raises(ValueError, match="must be a finite number"):
        executor._parse_float(raw, default=1.0)


def test_executor_rejects_nonfinite_track_coordinates(tmp_path: Path):
    track = tmp_path / "reference_track.json"
    track.write_text('{"points":[{"x":NaN,"y":0,"z":3}]}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-standard JSON numeric constant"):
        executor.load_reference_track(track)


def test_executor_rejects_oversized_reference_track_before_json_decode(tmp_path: Path):
    track = tmp_path / "reference_track.json"
    track.write_bytes(b" " * (executor.MAX_INPUT_JSON_BYTES + 1))

    with pytest.raises(ValueError, match="exceeds the .* byte limit"):
        executor.load_reference_track(track)


def test_offboard_timing_write_is_atomic_and_preserves_previous_receipt_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    timing_path = tmp_path / "offboard_timing.json"
    timing_path.write_text('{"status":"previous"}\n', encoding="utf-8")

    def fail_replace(self: Path, target: Path) -> Path:
        _ = self, target
        raise OSError("injected replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        executor._write_offboard_timing(timing_path, {"status": "new"})

    assert timing_path.read_text(encoding="utf-8") == '{"status":"previous"}\n'
    assert list(tmp_path.glob(".offboard_timing.json.*.tmp")) == []


def test_offboard_timing_rejects_nonfinite_json(tmp_path: Path):
    timing_path = tmp_path / "offboard_timing.json"

    with pytest.raises(ValueError, match="Out of range float values"):
        executor._write_offboard_timing(timing_path, {"elapsed": math.nan})

    assert not timing_path.exists()


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


def test_reference_track_loads_segment_speed_and_waypoint_stop_contract(tmp_path: Path) -> None:
    track = _write_json(
        tmp_path / "reference_track.json",
        {
            "track_type": "custom",
            "stop_at_waypoints": True,
            "waypoint_hold_seconds": 0.4,
            "points": [
                {"x": 0.0, "y": 0.0, "z": 1.0, "speed_limit_mps": 0.42},
                {"x": 1.0, "y": 0.0, "z": 1.0, "speed_limit_mps": 0.7},
            ],
        },
    )

    plan = executor.load_reference_track_plan(track)

    assert plan.stop_at_waypoints is True
    assert plan.waypoint_hold_seconds == pytest.approx(0.4)
    assert [point.speed_limit_mps for point in plan.points] == pytest.approx([0.42, 0.7])


def test_waypoint_stop_schedule_decelerates_and_holds_at_a_right_angle() -> None:
    points = [
        executor.TrackPoint(0.0, 0.0, 3.0, 0.5),
        executor.TrackPoint(1.0, 0.0, 3.0, 0.5),
        executor.TrackPoint(1.0, 1.0, 3.0, 0.5),
    ]
    params = executor.ControllerParams(1.0, 0.2, 0.1, 2.0, 0.8, 0.5)
    rate_hz = 10.0

    plan = executor.build_setpoint_schedule_plan(
        points,
        params,
        rate_hz,
        stop_at_waypoints=True,
        waypoint_hold_seconds=0.4,
    )
    track = plan.schedule[plan.track_start_index : plan.track_end_index + 1]
    corner = [
        index
        for index, setpoint in enumerate(track)
        if (
            setpoint.north_m,
            setpoint.east_m,
            setpoint.down_m,
        )
        == pytest.approx((1.0, 0.0, -3.0))
    ]

    assert len(corner) >= 4
    assert (
        max(
            math.dist(
                (first.north_m, first.east_m, first.down_m),
                (second.north_m, second.east_m, second.down_m),
            )
            for first, second in zip(track, track[1:], strict=False)
        )
        <= 0.5 / rate_hz + 1e-9
    )


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
        assert d <= max_step + 1e-6


def test_build_setpoint_schedule_respects_low_velocity_limits() -> None:
    points = [executor.TrackPoint(0.2, 0.0, 3.0)]
    params = executor.ControllerParams(
        1.0,
        0.2,
        0.1,
        vel_limit=0.1,
        accel_limit=0.1,
        disturbance_rejection=0.5,
    )
    rate_hz = 10.0

    schedule = executor.build_setpoint_schedule(points, params, rate_hz)

    max_step = params.vel_limit / rate_hz
    assert (
        max(
            math.dist(
                (first.north_m, first.east_m, first.down_m),
                (second.north_m, second.east_m, second.down_m),
            )
            for first, second in zip(schedule, schedule[1:], strict=False)
        )
        <= max_step + 1e-9
    )


def test_track_start_follows_safe_ingress_to_the_first_reference_point() -> None:
    points = [executor.TrackPoint(5.0, 0.0, 3.0), executor.TrackPoint(5.0, 5.0, 3.0)]
    params = executor.ControllerParams(1.0, 0.2, 0.1, 1.0, 1.0, 0.5)

    plan = executor.build_setpoint_schedule_plan(points, params, 10.0)

    entry = plan.schedule[plan.track_start_index]
    assert (entry.north_m, entry.east_m, entry.down_m) == pytest.approx((5.0, 0.0, -3.0))
    assert any(
        0.0 < setpoint.north_m < entry.north_m
        for setpoint in plan.schedule[: plan.track_start_index]
    )


def test_straight_track_schedule_respects_scalar_acceleration_limit() -> None:
    points = [executor.TrackPoint(0.0, 0.0, 3.0), executor.TrackPoint(10.0, 0.0, 3.0)]
    params = executor.ControllerParams(1.0, 0.2, 0.1, 2.0, 0.5, 0.5)
    rate_hz = 10.0

    plan = executor.build_setpoint_schedule_plan(points, params, rate_hz)
    track = plan.schedule[plan.track_start_index : plan.track_end_index + 1]
    speeds = [
        math.dist(
            (first.north_m, first.east_m, first.down_m),
            (second.north_m, second.east_m, second.down_m),
        )
        * rate_hz
        for first, second in zip(track, track[1:], strict=False)
    ]

    assert max(speeds) <= params.vel_limit + 1e-9
    assert (
        max(abs(first - second) for first, second in zip([0.0, *speeds], speeds, strict=False))
        <= params.accel_limit / rate_hz + 1e-9
    )


def test_track_schedule_is_invariant_to_collinear_waypoint_density() -> None:
    params = executor.ControllerParams(1.0, 0.2, 0.1, 2.0, 0.5, 0.5)
    sparse = executor.build_setpoint_schedule_plan(
        [executor.TrackPoint(0.0, 0.0, 3.0), executor.TrackPoint(10.0, 0.0, 3.0)],
        params,
        10.0,
    )
    dense = executor.build_setpoint_schedule_plan(
        [
            executor.TrackPoint(0.0, 0.0, 3.0),
            executor.TrackPoint(2.5, 0.0, 3.0),
            executor.TrackPoint(5.0, 0.0, 3.0),
            executor.TrackPoint(7.5, 0.0, 3.0),
            executor.TrackPoint(10.0, 0.0, 3.0),
        ],
        params,
        10.0,
    )

    assert sparse.track_start_index == dense.track_start_index
    assert sparse.track_end_index == dense.track_end_index


def test_hover_schedule_has_rate_independent_ten_second_stationary_window(
    tmp_path: Path,
) -> None:
    track = _write_json(
        tmp_path / "reference_track.json",
        {
            "track_type": "hover",
            "hover_duration_s": 10.0,
            "points": [{"x": 0.0, "y": 0.0, "z": 3.0}] * 101,
        },
    )
    reference_plan = executor.load_reference_track_plan(track)
    params = executor.ControllerParams(1.0, 0.2, 0.05, 5.0, 4.0, 0.5)

    plan = executor.build_setpoint_schedule_plan(
        reference_plan.points,
        params,
        20.0,
        hover_duration_seconds=reference_plan.hover_duration_seconds,
    )

    assert plan.track_start_index == 40
    assert (plan.track_end_index - plan.track_start_index) / 20.0 == pytest.approx(10.0)
    hover_window = plan.schedule[plan.track_start_index : plan.track_end_index + 1]
    assert len(hover_window) == 201
    assert {(setpoint.north_m, setpoint.east_m, setpoint.down_m) for setpoint in hover_window} == {
        (0.0, 0.0, -3.0)
    }


def test_hover_schedule_rejects_a_moving_or_non_origin_reference() -> None:
    params = executor.ControllerParams(1.0, 0.2, 0.05, 5.0, 4.0, 0.5)

    with pytest.raises(ValueError, match="stationary anchor"):
        executor.build_setpoint_schedule_plan(
            [
                executor.TrackPoint(0.0, 0.0, 3.0),
                executor.TrackPoint(1.0, 0.0, 3.0),
            ],
            params,
            10.0,
            hover_duration_seconds=10.0,
        )
    with pytest.raises(ValueError, match="local origin"):
        executor.build_setpoint_schedule_plan(
            [executor.TrackPoint(1.0, 0.0, 3.0)],
            params,
            10.0,
            hover_duration_seconds=10.0,
        )


def test_coordinate_conversion_maps_positive_up_to_ned_down():
    sp = executor.enu_point_to_ned_setpoint(executor.TrackPoint(1.0, -2.0, 3.5), yaw_deg=45.0)
    assert sp.north_m == 1.0
    assert sp.east_m == -2.0
    assert sp.down_m == -3.5


def test_fixed_duty_dropout_schedule_is_seeded_and_rate_bounded():
    first = executor.compile_fixed_duty_schedule(
        requested_rate=0.3,
        tick_count=10,
        execution_identity_sha256="a" * 64,
    )
    repeated = executor.compile_fixed_duty_schedule(
        requested_rate=0.3,
        tick_count=10,
        execution_identity_sha256="a" * 64,
    )
    other_seed = executor.compile_fixed_duty_schedule(
        requested_rate=0.3,
        tick_count=10,
        execution_identity_sha256="b" * 64,
    )

    assert first == repeated
    assert first != other_seed
    assert sum(first) == 3


def test_gazebo_wind_activator_publishes_and_reads_back_exact_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            # Gazebo uses proto3 text formatting and omits default-zero scalar
            # fields in real wind_info responses.
            stdout="linear_velocity { y: 3 }\nenable_wind: true\n",
            stderr="",
        ),
    ]
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(executor.shutil, "which", lambda _name: "/usr/bin/gz")
    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    result = executor._activate_gazebo_wind_profile(
        world="default",
        profile={"linear_velocity_mps": {"x": 0.0, "y": 3.0, "z": 0.0}},
        activation_t_s=2.5,
    )

    assert commands[0][1:4] == ["topic", "-t", "/world/default/wind"]
    assert commands[0][commands[0].index("-p") + 1] == (
        "linear_velocity { x: 0 y: 3 z: 0 } enable_wind: true"
    )
    assert commands[1][1:4] == ["service", "-s", "/world/default/wind_info"]
    assert result["readback"]["value"] == {
        "linear_velocity_mps": {"x": 0.0, "y": 3.0, "z": 0.0},
        "enable_wind": True,
    }
    assert result["activation"]["value"]["activation_t_s"] == 2.5
    assert result["activation"]["value"]["delivery_verification"] == ("wind_info_exact_readback")
    assert result["activation"]["value"]["publish_attempts"] == 1
    assert result["activation"]["value"]["publisher"] == "gazebo_cli_topic"
    assert result["activation"]["value"]["publisher_connections_observed"] is None


def test_gazebo_wind_activator_rejects_mismatched_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="linear_velocity { x: 0 y: 2 z: 0 }\nenable_wind: true\n",
            stderr="",
        ),
    ]
    monkeypatch.setattr(executor.shutil, "which", lambda _name: "/usr/bin/gz")
    monkeypatch.setattr(executor.subprocess, "run", lambda *_args, **_kwargs: responses.pop(0))
    monkeypatch.setenv("PX4_GAZEBO_WIND_READBACK_ATTEMPTS", "1")

    with pytest.raises(RuntimeError, match="post-hover wind activation was not verified"):
        executor._activate_gazebo_wind_profile(
            world="default",
            profile={"linear_velocity_mps": {"x": 0.0, "y": 3.0, "z": 0.0}},
            activation_t_s=2.5,
        )


def test_gazebo_wind_activator_republishes_until_exact_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="linear_velocity {}\nenable_wind: true\n",
            stderr="",
        ),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="linear_velocity { y: 3 }\nenable_wind: true\n",
            stderr="",
        ),
    ]
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(executor.shutil, "which", lambda _name: "/usr/bin/gz")
    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    result = executor._activate_gazebo_wind_profile(
        world="default",
        profile={"linear_velocity_mps": {"x": 0.0, "y": 3.0, "z": 0.0}},
        activation_t_s=2.5,
    )

    assert [command[1] for command in commands] == ["topic", "service", "topic", "service"]
    assert result["readback"]["value"]["linear_velocity_mps"] == {
        "x": 0.0,
        "y": 3.0,
        "z": 0.0,
    }


def test_gazebo_wind_activator_retries_failed_cli_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="publisher unavailable",
        ),
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="linear_velocity { y: 3 }\nenable_wind: true\n",
            stderr="",
        ),
    ]
    commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return responses.pop(0)

    monkeypatch.setattr(executor.shutil, "which", lambda _name: "/usr/bin/gz")
    monkeypatch.setattr(executor.subprocess, "run", fake_run)
    result = executor._activate_gazebo_wind_profile(
        world="default",
        profile={"linear_velocity_mps": {"x": 0.0, "y": 3.0, "z": 0.0}},
        activation_t_s=2.5,
    )

    assert [command[1] for command in commands] == ["topic", "topic", "service"]
    assert result["readback"]["value"]["linear_velocity_mps"]["y"] == 3.0
    assert result["activation"]["value"]["publish_attempts"] == 2
    assert result["activation"]["value"]["publisher_connections_observed"] is None


def test_gazebo_wind_message_text_is_explicit_and_deterministic() -> None:
    assert executor._gazebo_wind_message_text({"x": -1.25, "y": 3.0, "z": 0.0}) == (
        "linear_velocity { x: -1.25 y: 3 z: 0 } enable_wind: true"
    )


def test_runtime_effects_write_request_bound_gps_and_battery_evidence(
    tmp_path: Path,
) -> None:
    request = scenario_effects.build_scenario_effect_request(
        execution_identity={
            "trial_id": "trial-runtime",
            "job_id": "job-runtime",
            "candidate_id": "candidate-runtime",
            "seed": 17,
            "attempt_count": 1,
        },
        scenario_type="nominal",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={
            "sensor_degradation": {"dropout_rate": 0.5},
            "battery": {"initial_percent": 60.0, "voltage_sag": True},
        },
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None

    class KeepaliveDemandingClient(executor.FakeOffboardClient):
        gps_parameter_keepalive_observed = False

        async def get_param_int(self, name: str) -> int:
            if self.offboard_started and not self.gps_parameter_keepalive_observed:
                required_count = len(self.setpoints) + 1
                for _ in range(10_000):
                    if len(self.setpoints) >= required_count:
                        self.gps_parameter_keepalive_observed = True
                        break
                    await asyncio.sleep(0)
                else:
                    raise TimeoutError("GPS parameter readback received no Offboard keepalive")
            return await super().get_param_int(name)

    client = KeepaliveDemandingClient()
    client.battery_samples = [
        {"remaining_percent": 60.0, "voltage_v": 15.2},
        {"remaining_percent": 58.0, "voltage_v": 15.0},
    ]
    evidence_path = tmp_path / scenario_effects.RUNTIME_EVIDENCE_ARTIFACT_NAME

    asyncio.run(
        executor.run_executor(
            client,
            [
                executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                executor.Setpoint(1.0, 0.0, -3.0, 0.0),
                executor.Setpoint(2.0, 0.0, -3.0, 0.0),
            ],
            connection="udp://:14540",
            takeoff_timeout_seconds=1.0,
            takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S,
            track_timeout_seconds=5.0,
            rate_hz=100.0,
            land_after=True,
            log_path=tmp_path / "offboard.log",
            track_start_index=1,
            track_end_index=2,
            timing_path=tmp_path / "offboard_timing.json",
            scenario_engine=scenario_effects,
            scenario_request=request,
            runtime_profile=profile,
            runtime_evidence_path=evidence_path,
        )
    )

    artifact = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "complete"
    assert artifact["request_sha256"] == request["request_sha256"]
    assert [item["effect_id"] for item in artifact["records"]] == [
        "battery.initial_percent",
        "battery.voltage_sag",
        "sensor_degradation.dropout_rate",
    ]
    gps_value = artifact["records"][2]["evidence"]["verification"]["observations"][0]["value"]
    assert gps_value["reset_verified"] is True
    assert gps_value["off_tick_count"] == 1
    assert gps_value["control_parameter"]["parameter_name"] == "SIM_GPS_USED"
    assert gps_value["control_parameter"]["before"] == 10
    assert gps_value["control_parameter"]["dropout_value"] == 0
    assert gps_value["control_parameter"]["recovery_value"] == 10
    assert gps_value["control_parameter"]["restore_verified"] is True
    assert gps_value["control_parameter"]["restore"]["telemetry_samples"][-1] == {
        "num_satellites": 10,
        "fix_type": 3,
        "fix_type_name": "FIX_3D",
    }
    assert client.int_params["SIM_GPS_USED"] == 10
    assert client.gps_parameter_keepalive_observed is True
    battery_value = artifact["records"][0]["evidence"]["verification"]["observations"][0]["value"]
    assert battery_value["takeoff_gate_parameters"]["SIM_BAT_MIN_PCT"]["applied"] == 100.0
    assert battery_value["takeoff_gate_parameters"]["SIM_BAT_DRAIN"]["applied"] == 86400.0
    assert battery_value["track_start_sample"]["remaining_percent"] == 60.0
    assert battery_value["track_end_sample"]["remaining_percent"] == 58.0
    final_payload = scenario_effects.build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=artifact["records"],
    )
    assert (
        scenario_effects.validate_scenario_effect_evidence(
            request,
            final_payload,
        )["verification_status"]
        == "verified_applied"
    )
    tampered_reset = json.loads(json.dumps(final_payload))
    gps_record = next(
        item
        for item in tampered_reset["effects"]
        if item["effect_id"] == "sensor_degradation.dropout_rate"
    )
    gps_record["evidence"]["verification"]["observations"][0]["value"]["reset_verified"] = False
    gps_observation = gps_record["evidence"]["verification"]["observations"][0]
    gps_observation["sha256"] = scenario_effects.scenario_effect_value_sha256(
        gps_observation["value"]
    )
    with pytest.raises(
        scenario_effects.ScenarioEffectContractError,
        match="verified GPS availability/reset",
    ):
        scenario_effects.validate_scenario_effect_evidence(request, tampered_reset)

    tampered_control = json.loads(json.dumps(final_payload))
    control_record = next(
        item
        for item in tampered_control["effects"]
        if item["effect_id"] == "sensor_degradation.dropout_rate"
    )
    control_observation = control_record["evidence"]["verification"]["observations"][0]
    control_observation["value"]["control_parameter"]["restore_verified"] = False
    control_observation["sha256"] = scenario_effects.scenario_effect_value_sha256(
        control_observation["value"]
    )
    with pytest.raises(
        scenario_effects.ScenarioEffectContractError,
        match="GPS schedule/telemetry evidence",
    ):
        scenario_effects.validate_scenario_effect_evidence(request, tampered_control)

    tampered_battery = json.loads(json.dumps(final_payload))
    battery_record = next(
        item
        for item in tampered_battery["effects"]
        if item["effect_id"] == "battery.initial_percent"
    )
    battery_record["evidence"]["verification"]["observations"][0]["value"]["track_start_sample"][
        "remaining_percent"
    ] = 90.0
    battery_observation = battery_record["evidence"]["verification"]["observations"][0]
    battery_observation["sha256"] = scenario_effects.scenario_effect_value_sha256(
        battery_observation["value"]
    )
    with pytest.raises(
        scenario_effects.ScenarioEffectContractError,
        match="track-start battery state",
    ):
        scenario_effects.validate_scenario_effect_evidence(request, tampered_battery)

    tampered_tolerance = json.loads(json.dumps(tampered_battery))
    tolerance_record = next(
        item
        for item in tampered_tolerance["effects"]
        if item["effect_id"] == "battery.initial_percent"
    )
    tolerance_observation = tolerance_record["evidence"]["verification"]["observations"][0]
    tolerance_observation["value"]["track_start_tolerance_percent"] = 1_000_000.0
    tolerance_observation["sha256"] = scenario_effects.scenario_effect_value_sha256(
        tolerance_observation["value"]
    )
    with pytest.raises(
        scenario_effects.ScenarioEffectContractError,
        match="battery tolerance",
    ):
        scenario_effects.validate_scenario_effect_evidence(
            request,
            tampered_tolerance,
        )


def test_battery_track_start_waits_for_telemetry_convergence() -> None:
    client = executor.FakeOffboardClient()
    client.battery_samples = [
        {"remaining_percent": 81.0, "voltage_v": 16.1},
        {"remaining_percent": 79.0, "voltage_v": 16.0},
        {"remaining_percent": 76.0, "voltage_v": 15.9},
        {"remaining_percent": 74.0, "voltage_v": 15.8},
    ]
    hold = executor.Setpoint(0.0, 0.0, -3.0, 0.0)

    details = asyncio.run(
        executor._transition_battery_at_track_start(
            client,
            {
                "target_track_start_percent": 70.0,
                "voltage_sag": True,
                "sag_drain_seconds": 300.0,
                "no_sag_hold_drain_seconds": 86400.0,
            },
            {"pretrack_drain_seconds": 6.666666666666667},
            hold_setpoint=hold,
            rate_hz=100.0,
            settle_timeout_seconds=1.0,
        )
    )

    assert details["conditioning_sample_count"] == 4
    assert details["track_start_sample"]["remaining_percent"] == 74.0
    assert len(client.setpoints) >= 5
    assert all(setpoint == hold for setpoint in client.setpoints)
    assert client.float_params["SIM_BAT_MIN_PCT"] == 0.0
    assert client.float_params["SIM_BAT_DRAIN"] == 300.0


def test_battery_track_start_keeps_offboard_setpoints_alive_during_slow_sample() -> None:
    class SlowBatteryClient(executor.FakeOffboardClient):
        async def sample_battery(self, timeout_seconds: float) -> dict[str, float]:
            del timeout_seconds
            # Avoid wall-clock scheduling assumptions on loaded Windows hosts:
            # the sample becomes available only after three hold heartbeats.
            while len(self.setpoints) < 3:
                await asyncio.sleep(0)
            return {"remaining_percent": 74.0, "voltage_v": 15.8}

    client = SlowBatteryClient()
    hold = executor.Setpoint(0.0, 0.0, -3.0, 0.0)

    details = asyncio.run(
        executor._transition_battery_at_track_start(
            client,
            {
                "target_track_start_percent": 70.0,
                "voltage_sag": True,
                "sag_drain_seconds": 300.0,
                "no_sag_hold_drain_seconds": 86400.0,
            },
            {"pretrack_drain_seconds": 6.666666666666667},
            hold_setpoint=hold,
            rate_hz=100.0,
            settle_timeout_seconds=1.0,
        )
    )

    assert details["conditioning_sample_count"] == 1
    assert len(client.setpoints) >= 3
    assert all(setpoint == hold for setpoint in client.setpoints)


def test_battery_track_start_keeps_offboard_alive_during_parameter_readback() -> None:
    class SlowParameterClient(executor.FakeOffboardClient):
        require_parameter_keepalive = False
        required_setpoint_count = 0

        async def sample_battery(self, timeout_seconds: float) -> dict[str, float]:
            del timeout_seconds
            self.required_setpoint_count = len(self.setpoints) + 2
            self.require_parameter_keepalive = True
            return {"remaining_percent": 74.0, "voltage_v": 15.8}

        async def get_param_float(self, name: str) -> float:
            if self.require_parameter_keepalive:
                for _ in range(10_000):
                    if len(self.setpoints) >= self.required_setpoint_count:
                        self.require_parameter_keepalive = False
                        break
                    await asyncio.sleep(0)
                else:
                    raise TimeoutError("parameter readback received no Offboard keepalive")
            return await super().get_param_float(name)

    client = SlowParameterClient()
    hold = executor.Setpoint(0.0, 0.0, -3.0, 0.0)

    details = asyncio.run(
        executor._transition_battery_at_track_start(
            client,
            {
                "target_track_start_percent": 70.0,
                "voltage_sag": True,
                "sag_drain_seconds": 300.0,
                "no_sag_hold_drain_seconds": 86400.0,
            },
            {"pretrack_drain_seconds": 6.666666666666667},
            hold_setpoint=hold,
            rate_hz=100.0,
            settle_timeout_seconds=1.0,
        )
    )

    assert details["track_parameters"]["SIM_BAT_DRAIN"]["applied"] == 300.0
    assert len(client.setpoints) >= client.required_setpoint_count
    assert all(setpoint == hold for setpoint in client.setpoints)


def test_battery_track_start_retries_transient_telemetry_timeout() -> None:
    class IntermittentBatteryClient(executor.FakeOffboardClient):
        battery_call_count = 0

        async def sample_battery(self, timeout_seconds: float) -> dict[str, float]:
            del timeout_seconds
            self.battery_call_count += 1
            if self.battery_call_count == 1:
                raise TimeoutError("first subscription sample unavailable")
            return {"remaining_percent": 74.0, "voltage_v": 15.8}

    client = IntermittentBatteryClient()

    details = asyncio.run(
        executor._transition_battery_at_track_start(
            client,
            {
                "target_track_start_percent": 70.0,
                "voltage_sag": True,
                "sag_drain_seconds": 300.0,
                "no_sag_hold_drain_seconds": 86400.0,
            },
            {"pretrack_drain_seconds": 6.666666666666667},
            hold_setpoint=executor.Setpoint(0.0, 0.0, -3.0, 0.0),
            rate_hz=100.0,
            settle_timeout_seconds=1.0,
        )
    )

    assert details["conditioning_sample_timeout_count"] == 1
    assert details["conditioning_sample_count"] == 1
    assert details["track_start_sample"]["remaining_percent"] == 74.0


def test_battery_track_start_fails_closed_when_telemetry_does_not_converge() -> None:
    client = executor.FakeOffboardClient()
    client.battery_samples = [{"remaining_percent": 81.0, "voltage_v": 16.1}]

    with pytest.raises(RuntimeError, match="did not reach.*before timeout"):
        asyncio.run(
            executor._transition_battery_at_track_start(
                client,
                {
                    "target_track_start_percent": 70.0,
                    "voltage_sag": True,
                    "sag_drain_seconds": 300.0,
                    "no_sag_hold_drain_seconds": 86400.0,
                },
                {"pretrack_drain_seconds": 6.666666666666667},
                hold_setpoint=executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                rate_hz=100.0,
                settle_timeout_seconds=0.01,
            )
        )


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
            takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S,
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


def test_executor_holds_the_current_setpoint_then_splices_a_runtime_route(
    tmp_path: Path,
) -> None:
    runtime_control_path = tmp_path / "runtime_control.request.json"

    class RuntimeControlClient(executor.FakeOffboardClient):
        def __init__(self) -> None:
            super().__init__()
            self.hold_anchor: executor.Setpoint | None = None
            self.hold_setpoints: list[executor.Setpoint] = []
            self.replacement_written = False

        async def set_position_ned(self, setpoint: executor.Setpoint) -> None:
            await super().set_position_ned(setpoint)
            if not self.offboard_started:
                return
            if self.hold_anchor is None:
                if setpoint != schedule[0]:
                    return
                self.hold_anchor = setpoint
                _write_json(
                    runtime_control_path,
                    _runtime_control_payload(revision=1, action="hold"),
                )
                return
            if self.replacement_written:
                return
            self.hold_setpoints.append(setpoint)
            if len(self.hold_setpoints) >= 3:
                _write_json(
                    runtime_control_path,
                    _runtime_control_payload(
                        revision=2,
                        action="replace_route",
                        route=[
                            {"x": 0.0, "y": 0.0, "z": 0.01, "speed_limit_mps": 0.4},
                            {"x": 0.4, "y": 0.2, "z": 0.01, "speed_limit_mps": 0.4},
                        ],
                    ),
                )
                self.replacement_written = True

    client = RuntimeControlClient()
    schedule = [
        executor.Setpoint(0.0, 0.0, -0.01, 0.0),
        executor.Setpoint(0.1, 0.0, -0.01, 0.0),
        executor.Setpoint(0.2, 0.0, -0.01, 0.0),
    ]
    timing_path = tmp_path / "offboard_timing.json"
    params = executor.ControllerParams(1.0, 0.2, 0.05, 0.4, 0.4, 0.5)

    asyncio.run(
        executor.run_executor(
            client,
            schedule,
            connection="udp://:14540",
            takeoff_timeout_seconds=1.0,
            takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S,
            track_timeout_seconds=5.0,
            rate_hz=100.0,
            land_after=True,
            log_path=tmp_path / "offboard.log",
            timing_path=timing_path,
            runtime_control_file=runtime_control_path,
            controller_params=params,
        )
    )

    assert client.hold_anchor is not None
    assert len(client.hold_setpoints) >= 3
    assert all(point == client.hold_anchor for point in client.hold_setpoints[:3])
    assert client.setpoints[-1].north_m == pytest.approx(0.4)
    assert client.setpoints[-1].east_m == pytest.approx(0.2)
    assert client.setpoints[-1].down_m == pytest.approx(-0.01)
    assert client.landed is True
    assert client.closed is True
    acknowledgement = json.loads(
        (tmp_path / "runtime_control.ack.json").read_text(encoding="utf-8")
    )
    assert acknowledgement["revision"] == 2
    assert acknowledgement["state"] == "route_replaced"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert [event["action"] for event in timing["runtime_controls"]] == ["replace_route"]


@pytest.mark.parametrize(
    "track_start_index, track_end_index",
    [
        (-1, None),
        (2, None),
        (1, 0),
        (0, 2),
        (True, None),
        (0, True),
    ],
)
def test_executor_rejects_invalid_track_bounds_before_connecting(
    tmp_path: Path,
    track_start_index: int,
    track_end_index: int | None,
) -> None:
    client = executor.FakeOffboardClient()
    schedule = [
        executor.Setpoint(0.0, 0.0, -3.0, 0.0),
        executor.Setpoint(1.0, 0.0, -3.0, 0.0),
    ]

    with pytest.raises(ValueError, match="track .* index"):
        asyncio.run(
            executor.run_executor(
                client,
                schedule,
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                track_start_index=track_start_index,
                track_end_index=track_end_index,
            )
        )

    assert client.connected is False
    assert client.armed is False


def test_executor_track_timeout_interrupts_a_hung_setpoint_call(tmp_path: Path) -> None:
    class HangingClient(executor.FakeOffboardClient):
        async def set_position_ned(self, setpoint: executor.Setpoint) -> None:
            if self.offboard_started and setpoint.north_m == 1.0:
                await asyncio.Event().wait()
            await super().set_position_ned(setpoint)

    client = HangingClient()
    schedule = [
        executor.Setpoint(0.0, 0.0, -0.01, 0.0),
        executor.Setpoint(1.0, 0.0, -0.01, 0.0),
    ]

    with pytest.raises(TimeoutError, match="track timeout after 0.05s"):
        asyncio.run(
            asyncio.wait_for(
                executor.run_executor(
                    client,
                    schedule,
                    connection="udp://:14540",
                    takeoff_timeout_seconds=1.0,
                    track_timeout_seconds=0.05,
                    rate_hz=100.0,
                    land_after=True,
                    log_path=tmp_path / "offboard.log",
                ),
                timeout=0.5,
            )
        )

    assert client.landed is True
    assert client.closed is True


def test_executor_streams_prearm_hold_and_bounded_vertical_takeoff_ramp(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class RecordingClient(executor.FakeOffboardClient):
        async def set_position_ned(self, setpoint: executor.Setpoint) -> None:
            events.append("setpoint")
            await super().set_position_ned(setpoint)

        async def arm(self) -> None:
            events.append("arm")
            await super().arm()

        async def start_offboard(self) -> None:
            events.append("start_offboard")
            await super().start_offboard()

    client = RecordingClient()
    timing_path = tmp_path / "offboard_timing.json"
    asyncio.run(
        executor.run_executor(
            client,
            [executor.Setpoint(0.0, 0.0, -0.2, 0.0)],
            connection="udp://:14540",
            takeoff_timeout_seconds=0.5,
            takeoff_climb_rate_m_s=1.0,
            track_timeout_seconds=1.0,
            rate_hz=100.0,
            land_after=True,
            log_path=tmp_path / "offboard.log",
            timing_path=timing_path,
            takeoff_vertical_tolerance_m=1e-6,
        )
    )

    assert events[:3] == ["setpoint", "arm", "start_offboard"]
    assert client.setpoints[0].down_m == pytest.approx(0.0)
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    gate = timing["takeoff_gate"]
    assert gate["schema_version"] == "dronedream.takeoff_gate.v2"
    assert gate["takeoff_profile"]["mode"] == "telemetry_anchored_bounded_vertical_ramp"
    assert gate["takeoff_profile"]["origin_ned"]["down_m"] == pytest.approx(0.0)
    assert gate["takeoff_profile"]["ramp_completed_after_s"] >= 0.2
    commanded_down = [
        observation["commanded_setpoint_ned"]["down_m"] for observation in gate["observations"]
    ]
    assert commanded_down == sorted(commanded_down, reverse=True)
    assert any(-0.2 < value < 0.0 for value in commanded_down)
    assert commanded_down[-1] == pytest.approx(-0.2)
    for observation in gate["observations"]:
        commanded_delta = abs(observation["commanded_setpoint_ned"]["down_m"])
        assert commanded_delta <= observation["takeoff_ramp_elapsed_s"] + 1e-9


def test_executor_rejects_unsafe_takeoff_climb_rate_before_connecting(tmp_path: Path) -> None:
    client = executor.FakeOffboardClient()

    with pytest.raises(ValueError, match="takeoff_climb_rate_m_s must be no greater"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -3.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=30.0,
                takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S + 0.1,
                track_timeout_seconds=5.0,
                rate_hz=10.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
            )
        )

    assert client.connected is False
    assert client.armed is False


def test_executor_waits_for_continuously_stable_hover_before_track_entry(
    tmp_path: Path,
) -> None:
    client = executor.FakeOffboardClient()
    client.position_velocity_samples = [
        executor.PositionVelocityNed(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        executor.PositionVelocityNed(0.0, 0.0, -1.0, 0.0, 0.0, -1.5),
        executor.PositionVelocityNed(0.0, 0.0, -3.0, 0.0, 0.0, 0.0),
        executor.PositionVelocityNed(0.0, 0.0, -3.0, 0.0, 0.0, 0.0),
        executor.PositionVelocityNed(0.0, 0.0, -3.0, 0.0, 0.0, 0.0),
    ]
    schedule = [
        executor.Setpoint(0.0, 0.0, -3.0, 0.0),
        executor.Setpoint(2.0, 0.0, -3.0, 0.0),
    ]
    timing_path = tmp_path / "offboard_timing.json"

    asyncio.run(
        executor.run_executor(
            client,
            schedule,
            connection="udp://:14540",
            takeoff_timeout_seconds=1.0,
            takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S,
            track_timeout_seconds=5.0,
            rate_hz=100.0,
            land_after=True,
            log_path=tmp_path / "offboard.log",
            track_start_index=1,
            track_end_index=1,
            timing_path=timing_path,
            takeoff_stable_window_seconds=0.015,
        )
    )

    first_track_setpoint = next(
        index for index, setpoint in enumerate(client.setpoints) if setpoint.north_m == 2.0
    )
    assert first_track_setpoint >= 5
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    gate = timing["takeoff_gate"]
    assert gate["status"] == "achieved"
    assert gate["readiness_observed"] is True
    assert gate["readiness_policy"] == "local_ned_with_px4_preflight_authority"
    assert gate["px4_arm_command"] == "accepted"
    assert gate["sample_count"] >= 3
    assert gate["observations"][0]["within_all_limits"] is False
    assert gate["latest_observation"]["within_all_limits"] is True
    assert timing["takeoff_stable_t"] <= timing["track_start_t"]
    assert timing["cleanup"] == {
        "stop_offboard": "completed",
        "land": "confirmed_on_ground",
        "landing_observation": {"state": "ON_GROUND", "confirmed": True},
        "close": "completed",
    }


def test_executor_activates_wind_after_hover_and_before_track_entry(tmp_path: Path) -> None:
    request = scenario_effects.build_scenario_effect_request(
        execution_identity={
            "trial_id": "trial-wind",
            "job_id": "job-wind",
            "candidate_id": "candidate-wind",
            "seed": 17,
            "attempt_count": 1,
        },
        scenario_type="nominal",
        scenario_config={"wind_mps": 3.0},
        job_config={
            "wind": {"north": 3.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None
    events: list[str] = []
    wind_activation_started = threading.Event()
    wind_keepalive_observed = threading.Event()

    class RecordingClient(executor.FakeOffboardClient):
        async def set_position_ned(self, setpoint: executor.Setpoint) -> None:
            if wind_activation_started.is_set():
                wind_keepalive_observed.set()
            if setpoint.north_m == 2.0:
                events.append("track")
            await super().set_position_ned(setpoint)

    def activate_wind(**kwargs):
        wind_activation_started.set()
        if not wind_keepalive_observed.wait(timeout=1.0):
            raise TimeoutError("wind activation received no Offboard keepalive")
        events.append("wind")
        value = {
            "linear_velocity_mps": kwargs["profile"]["linear_velocity_mps"],
            "enable_wind": True,
        }
        return {
            "readback": {
                "source": "/world/default/wind_info",
                "kind": "readback",
                "value": value,
                "sha256": scenario_effects.scenario_effect_value_sha256(value),
            },
            "activation": {
                "source": "/world/default/wind",
                "kind": "acknowledgement",
                "value": {
                    "phase": "after_stable_hover_before_track_entry",
                    "activation_t_s": kwargs["activation_t_s"],
                },
            },
        }

    evidence_path = tmp_path / scenario_effects.RUNTIME_EVIDENCE_ARTIFACT_NAME
    timing_path = tmp_path / "offboard_timing.json"
    client = RecordingClient()
    asyncio.run(
        executor.run_executor(
            client,
            [
                executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                executor.Setpoint(2.0, 0.0, -3.0, 0.0),
            ],
            connection="udp://:14540",
            takeoff_timeout_seconds=1.0,
            takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S,
            track_timeout_seconds=5.0,
            rate_hz=100.0,
            land_after=True,
            log_path=tmp_path / "offboard.log",
            track_start_index=1,
            track_end_index=1,
            timing_path=timing_path,
            scenario_engine=scenario_effects,
            scenario_request=request,
            runtime_profile=profile,
            runtime_evidence_path=evidence_path,
            world="default",
            wind_activator=activate_wind,
        )
    )

    assert events == ["wind", "track"]
    assert wind_keepalive_observed.is_set()
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["takeoff_stable_t"] <= timing["wind_activation"]["activation_t_s"]
    assert timing["wind_activation"]["activation_t_s"] <= timing["track_start_t"]
    artifact = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "complete"
    assert {item["effect_id"] for item in artifact["records"]} == {
        "job_config.wind",
        "scenario_config.wind_mps",
    }


def test_executor_fails_closed_when_post_hover_wind_readback_fails(tmp_path: Path) -> None:
    request = scenario_effects.build_scenario_effect_request(
        execution_identity={
            "trial_id": "trial-wind-fail",
            "job_id": "job-wind-fail",
            "candidate_id": "candidate-wind-fail",
            "seed": 18,
            "attempt_count": 1,
        },
        scenario_type="nominal",
        scenario_config={"wind_mps": 3.0},
        job_config={
            "wind": {"north": 3.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None
    client = executor.FakeOffboardClient()
    evidence_path = tmp_path / scenario_effects.RUNTIME_EVIDENCE_ARTIFACT_NAME

    def reject_wind(**_kwargs):
        raise RuntimeError("wind readback mismatch")

    with pytest.raises(RuntimeError, match="wind readback mismatch"):
        asyncio.run(
            executor.run_executor(
                client,
                [
                    executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                    executor.Setpoint(2.0, 0.0, -3.0, 0.0),
                ],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                takeoff_climb_rate_m_s=executor.MAX_TAKEOFF_CLIMB_RATE_M_S,
                track_timeout_seconds=5.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                track_start_index=1,
                track_end_index=1,
                scenario_engine=scenario_effects,
                scenario_request=request,
                runtime_profile=profile,
                runtime_evidence_path=evidence_path,
                wind_activator=reject_wind,
            )
        )

    assert all(setpoint.north_m == 0.0 for setpoint in client.setpoints)
    assert client.landed is True
    assert client.closed is True
    artifact = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "failed"
    assert all(item["status"] == "failed" for item in artifact["records"])
    assert artifact["attempted_sections"] == ["wind_activation"]


def test_executor_marks_wind_skipped_when_takeoff_fails_before_activation(
    tmp_path: Path,
) -> None:
    request = scenario_effects.build_scenario_effect_request(
        execution_identity={
            "trial_id": "trial-pre-wind-fail",
            "job_id": "job-pre-wind-fail",
            "candidate_id": "candidate-pre-wind-fail",
            "seed": 19,
            "attempt_count": 1,
        },
        scenario_type="nominal",
        scenario_config={"wind_mps": 3.0},
        job_config={
            "wind": {"north": 3.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None
    client = executor.FakeOffboardClient()
    client.position_velocity_samples = [executor.PositionVelocityNed(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
    evidence_path = tmp_path / scenario_effects.RUNTIME_EVIDENCE_ARTIFACT_NAME

    with pytest.raises(TimeoutError, match="continuously stable hover"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -3.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=0.03,
                track_timeout_seconds=5.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                scenario_engine=scenario_effects,
                scenario_request=request,
                runtime_profile=profile,
                runtime_evidence_path=evidence_path,
            )
        )

    artifact = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "failed"
    assert artifact["attempted_sections"] == []
    assert all(item["status"] == "skipped" for item in artifact["records"])
    assert all(
        "before wind_activation activation" in item["reason"] for item in artifact["records"]
    )


def test_runtime_effect_evidence_preserves_applied_effect_after_later_failure() -> None:
    request = scenario_effects.build_scenario_effect_request(
        execution_identity={"trial_id": "trial-post-wind-failure"},
        scenario_type="nominal",
        scenario_config={"wind_mps": 3.0},
        job_config={
            "wind": {"north": 3.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )
    profile = scenario_effects.compile_bundled_runtime_profile(request)
    assert profile is not None
    observation = {
        "readback": {"kind": "readback"},
        "activation": {"kind": "acknowledgement"},
    }

    records = executor._runtime_effect_records(
        scenario_effects,
        request,
        profile,
        observations={"wind_activation": observation},
        attempted_sections={"wind_activation"},
        status="failed",
        error="track timeout after verified wind activation",
    )

    assert all(item["status"] == "applied" for item in records)
    assert all(
        item["evidence"]["verification"]["observations"]
        == [observation["readback"], observation["activation"]]
        for item in records
    )


def test_takeoff_deadline_after_valid_samples_is_not_reported_as_telemetry_loss() -> None:
    class DeadlineClient(executor.FakeOffboardClient):
        sample_calls = 0

        async def sample_position_velocity_ned(
            self, timeout_seconds: float
        ) -> executor.PositionVelocityNed:
            self.sample_calls += 1
            if self.sample_calls == 1:
                return executor.PositionVelocityNed(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            await asyncio.sleep(timeout_seconds + 0.01)
            raise TimeoutError(f"telemetry timeout after {timeout_seconds:.3f}s")

    evidence: dict = {}
    with pytest.raises(TimeoutError, match="continuously stable hover"):
        asyncio.run(
            executor._wait_for_takeoff_stability(
                DeadlineClient(),
                executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                timeout_seconds=0.1,
                sample_rate_hz=100.0,
                stable_window_seconds=0.01,
                horizontal_tolerance_m=0.35,
                vertical_tolerance_m=0.25,
                horizontal_speed_tolerance_m_s=0.35,
                vertical_speed_tolerance_m_s=0.25,
                evidence=evidence,
            )
        )
    assert evidence["sample_count"] == 1
    assert evidence["failure_reason"] == "takeoff_stability_timeout"
    assert "telemetry timeout" in evidence["terminal_telemetry_error"]


def test_takeoff_initial_telemetry_failure_remains_fail_closed() -> None:
    class NoTelemetryClient(executor.FakeOffboardClient):
        async def sample_position_velocity_ned(
            self, timeout_seconds: float
        ) -> executor.PositionVelocityNed:
            raise TimeoutError(f"telemetry timeout after {timeout_seconds:.3f}s")

    evidence: dict = {}
    with pytest.raises(TimeoutError, match="telemetry timeout"):
        asyncio.run(
            executor._wait_for_takeoff_stability(
                NoTelemetryClient(),
                executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                timeout_seconds=0.1,
                sample_rate_hz=100.0,
                stable_window_seconds=0.01,
                horizontal_tolerance_m=0.35,
                vertical_tolerance_m=0.25,
                horizontal_speed_tolerance_m_s=0.35,
                vertical_speed_tolerance_m_s=0.25,
                evidence=evidence,
            )
        )
    assert evidence["sample_count"] == 0
    assert evidence["failure_reason"] == "position_velocity_telemetry_unavailable"


def test_executor_rejects_missing_initial_position_telemetry_before_arming(
    tmp_path: Path,
) -> None:
    class NoInitialTelemetryClient(executor.FakeOffboardClient):
        async def sample_position_velocity_ned(
            self, timeout_seconds: float
        ) -> executor.PositionVelocityNed:
            raise TimeoutError(f"telemetry timeout after {timeout_seconds:.3f}s")

    client = NoInitialTelemetryClient()
    timing_path = tmp_path / "offboard_timing.json"

    with pytest.raises(TimeoutError, match="telemetry timeout"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -3.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=5.0,
                rate_hz=10.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
            )
        )

    assert client.armed is False
    assert client.offboard_started is False
    assert client.landed is False
    assert client.closed is True
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    gate = timing["takeoff_gate"]
    assert gate["status"] == "failed"
    assert gate["failure_reason"] == "initial_position_velocity_telemetry_unavailable"
    assert "telemetry timeout" in gate["telemetry_error"]


def test_executor_fails_closed_when_hover_velocity_never_stabilizes(
    tmp_path: Path,
) -> None:
    client = executor.FakeOffboardClient()
    client.position_velocity_samples = [executor.PositionVelocityNed(0.0, 0.0, -3.0, 1.0, 0.0, 0.0)]
    timing_path = tmp_path / "offboard_timing.json"

    with pytest.raises(TimeoutError, match="continuously stable hover"):
        asyncio.run(
            executor.run_executor(
                client,
                [
                    executor.Setpoint(0.0, 0.0, -3.0, 0.0),
                    executor.Setpoint(2.0, 0.0, -3.0, 0.0),
                ],
                connection="udp://:14540",
                takeoff_timeout_seconds=0.04,
                track_timeout_seconds=5.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                track_start_index=1,
                track_end_index=1,
                timing_path=timing_path,
                takeoff_stable_window_seconds=0.01,
            )
        )

    assert all(setpoint.north_m == 0.0 for setpoint in client.setpoints)
    assert client.offboard_started is False
    assert client.landed is True
    assert client.closed is True
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["status"] == "failed"
    assert timing["takeoff_gate"]["status"] == "failed"
    assert timing["takeoff_gate"]["failure_reason"] == "takeoff_stability_timeout"
    assert timing["takeoff_gate"]["latest_observation"]["horizontal_speed_m_s"] == 1.0
    assert timing["cleanup"] == {
        "stop_offboard": "completed_during_failure_cleanup",
        "land": "confirmed_on_ground_during_failure_cleanup",
        "landing_observation": {"state": "ON_GROUND", "confirmed": True},
        "close": "completed",
    }


def test_executor_fails_when_landing_is_not_confirmed_by_telemetry(tmp_path: Path) -> None:
    class LandingTimeoutClient(executor.FakeOffboardClient):
        async def wait_until_landed(self, timeout_seconds: float) -> dict[str, object]:
            raise TimeoutError(f"PX4 landing confirmation timeout after {timeout_seconds:g}s")

    client = LandingTimeoutClient()
    timing_path = tmp_path / "offboard_timing.json"

    with pytest.raises(TimeoutError, match="landing confirmation timeout"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -1.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                landing_timeout_seconds=0.01,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
            )
        )

    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["status"] == "failed"
    assert timing["cleanup"]["land"].startswith("failed: TimeoutError:")
    assert "land_confirmed_t" not in timing
    assert client.landed is True
    assert client.closed is True


def test_executor_fails_closed_when_px4_rejects_arm_after_preflight_readiness(
    tmp_path: Path,
) -> None:
    class ArmRejectingClient(executor.FakeOffboardClient):
        async def wait_until_ready(self, timeout_seconds: float) -> executor.TelemetryHealth:
            _ = timeout_seconds
            return executor.TelemetryHealth(
                connected=True,
                global_position_ok=False,
                home_position_ok=True,
                local_position_ok=True,
                armable=True,
            )

        async def arm(self) -> None:
            raise RuntimeError("PX4 rejected arm command")

    client = ArmRejectingClient()
    timing_path = tmp_path / "offboard_timing.json"

    with pytest.raises(RuntimeError, match="PX4 rejected arm command"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -3.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=5.0,
                rate_hz=10.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
            )
        )

    assert client.armed is False
    assert client.offboard_started is False
    assert client.landed is False
    assert client.closed is True
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    gate = timing["takeoff_gate"]
    assert gate["readiness_observed"] is True
    assert gate["advisory_readiness"] == {"global_position_ok": False}
    assert "px4_arm_command" not in gate
    assert gate["failure_reason"] == "readiness_or_preflight_failure"


def test_executor_never_bypasses_non_armable_sensor_degradation(
    tmp_path: Path,
) -> None:
    class GnssWarningClient(executor.FakeOffboardClient):
        allow_policy_seen = False

        async def wait_until_ready(
            self,
            timeout_seconds: float,
        ) -> executor.TelemetryHealth:
            _ = timeout_seconds
            self.allow_policy_seen = False
            return executor.TelemetryHealth(
                connected=True,
                global_position_ok=False,
                home_position_ok=True,
                local_position_ok=True,
                armable=False,
            )

    client = GnssWarningClient()
    timing_path = tmp_path / "offboard_timing.json"
    scenario_request = {
        "effects": [
            {
                "effect_id": "sensor_degradation.gps_noise_m",
                "mechanism": "sdformat_sensor_noise",
                "requested_value": 0.6,
            }
        ]
    }

    with pytest.raises(RuntimeError, match="must never bypass the preflight safety gate"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -3.0, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=5.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
                scenario_request=scenario_request,
            )
        )

    assert client.allow_policy_seen is False
    assert client.armed is False
    assert client.landed is False
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    gate = timing["takeoff_gate"]
    assert gate["readiness_observed"] is False
    assert gate["advisory_readiness"] == {"global_position_ok": False}
    assert "gnss_warning_arm_authority" not in gate
    assert gate["failure_reason"] == "readiness_or_preflight_failure"


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


def test_executor_preserves_primary_failure_when_timing_write_also_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient(executor.FakeOffboardClient):
        async def set_position_ned(self, setpoint: executor.Setpoint) -> None:
            await super().set_position_ned(setpoint)
            if self.offboard_started:
                raise RuntimeError("primary setpoint failure")

    def fail_timing_write(path: Path, payload: dict) -> None:
        _ = path, payload
        raise OSError("secondary timing write failure")

    monkeypatch.setattr(executor, "_write_offboard_timing", fail_timing_write)
    client = FailingClient()

    with pytest.raises(RuntimeError, match="primary setpoint failure"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -0.01, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=tmp_path / "offboard_timing.json",
            )
        )

    assert "secondary timing write failure" in (tmp_path / "offboard.log").read_text(
        encoding="utf-8"
    )


def test_executor_fails_closed_when_client_close_fails_after_flight(
    tmp_path: Path,
) -> None:
    class CloseFailingClient(executor.FakeOffboardClient):
        async def close(self) -> None:
            raise OSError("injected client close failure")

    client = CloseFailingClient()
    timing_path = tmp_path / "offboard_timing.json"

    with pytest.raises(RuntimeError, match="offboard client cleanup failed"):
        asyncio.run(
            executor.run_executor(
                client,
                [executor.Setpoint(0.0, 0.0, -0.01, 0.0)],
                connection="udp://:14540",
                takeoff_timeout_seconds=1.0,
                track_timeout_seconds=1.0,
                rate_hz=100.0,
                land_after=True,
                log_path=tmp_path / "offboard.log",
                timing_path=timing_path,
            )
        )

    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    assert timing["status"] == "failed"
    assert timing["cleanup"]["close"].startswith("failed: OSError:")


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


def test_mavsdk_readiness_returns_observed_health_state():
    class CoreStub:
        async def connection_state(self):
            yield type("ConnectionState", (), {"is_connected": True})()

    class TelemetryStub:
        async def health(self):
            yield type(
                "Health",
                (),
                {
                    "is_global_position_ok": True,
                    "is_home_position_ok": True,
                    "is_local_position_ok": True,
                    "is_armable": True,
                },
            )()

    class SystemStub:
        core = CoreStub()
        telemetry = TelemetryStub()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SystemStub()

    assert asyncio.run(client.wait_until_ready(1.0)) == executor.TelemetryHealth(
        connected=True,
        global_position_ok=True,
        home_position_ok=True,
        local_position_ok=True,
        armable=True,
    )


def test_mavsdk_landing_confirmation_requires_on_ground_state() -> None:
    class TelemetryStub:
        async def landed_state(self):
            yield type("LandedState", (), {"name": "IN_AIR"})()
            yield type("LandedState", (), {"name": "ON_GROUND"})()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = type("SystemStub", (), {"telemetry": TelemetryStub()})()

    assert asyncio.run(client.wait_until_landed(1.0)) == {
        "state": "ON_GROUND",
        "confirmed": True,
    }


def test_mavsdk_landing_confirmation_times_out_without_on_ground_state() -> None:
    class TelemetryStub:
        async def landed_state(self):
            await asyncio.sleep(1.0)
            yield type("LandedState", (), {"name": "IN_AIR"})()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = type("SystemStub", (), {"telemetry": TelemetryStub()})()

    with pytest.raises(TimeoutError, match="landing confirmation timeout"):
        asyncio.run(client.wait_until_landed(0.01))


def test_mavsdk_readiness_accepts_armable_local_navigation_without_global_position():
    class CoreStub:
        async def connection_state(self):
            yield type("ConnectionState", (), {"is_connected": True})()

    class TelemetryStub:
        async def health(self):
            yield type(
                "Health",
                (),
                {
                    "is_global_position_ok": False,
                    "is_home_position_ok": True,
                    "is_local_position_ok": True,
                    "is_armable": True,
                },
            )()

    class SystemStub:
        core = CoreStub()
        telemetry = TelemetryStub()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SystemStub()

    assert asyncio.run(client.wait_until_ready(1.0)) == executor.TelemetryHealth(
        connected=True,
        global_position_ok=False,
        home_position_ok=True,
        local_position_ok=True,
        armable=True,
    )


def test_mavsdk_readiness_rejects_local_navigation_that_is_not_armable():
    class CoreStub:
        async def connection_state(self):
            yield type("ConnectionState", (), {"is_connected": True})()

    class TelemetryStub:
        async def health(self):
            while True:
                yield type(
                    "Health",
                    (),
                    {
                        "is_global_position_ok": False,
                        "is_home_position_ok": True,
                        "is_local_position_ok": True,
                        "is_armable": False,
                    },
                )()
                await asyncio.sleep(0.001)

    class SystemStub:
        core = CoreStub()
        telemetry = TelemetryStub()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SystemStub()

    with pytest.raises(TimeoutError, match="armable=false"):
        asyncio.run(client.wait_until_ready(0.01))


def test_mavsdk_readiness_timeout_reports_last_observed_health_state():
    class CoreStub:
        async def connection_state(self):
            yield type("ConnectionState", (), {"is_connected": True})()

    class TelemetryStub:
        async def health(self):
            while True:
                yield type(
                    "Health",
                    (),
                    {
                        "is_global_position_ok": False,
                        "is_home_position_ok": False,
                        "is_local_position_ok": False,
                        "is_armable": False,
                    },
                )()
                await asyncio.sleep(0.001)

    class SystemStub:
        core = CoreStub()
        telemetry = TelemetryStub()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SystemStub()

    with pytest.raises(
        TimeoutError,
        match=(
            "connected=true, global_position_ok=false, home_position_ok=false, "
            "local_position_ok=false, armable=false"
        ),
    ):
        asyncio.run(client.wait_until_ready(0.01))


def test_mavsdk_position_velocity_sample_preserves_ned_units():
    class TelemetryStub:
        async def position_velocity_ned(self):
            yield type(
                "PositionVelocity",
                (),
                {
                    "position": type(
                        "Position",
                        (),
                        {"north_m": 1.0, "east_m": -2.0, "down_m": -3.0},
                    )(),
                    "velocity": type(
                        "Velocity",
                        (),
                        {"north_m_s": 0.1, "east_m_s": -0.2, "down_m_s": 0.3},
                    )(),
                },
            )()

    class SystemStub:
        telemetry = TelemetryStub()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SystemStub()

    assert asyncio.run(client.sample_position_velocity_ned(1.0)) == (
        executor.PositionVelocityNed(
            north_m=1.0,
            east_m=-2.0,
            down_m=-3.0,
            north_m_s=0.1,
            east_m_s=-0.2,
            down_m_s=0.3,
        )
    )


def test_mavsdk_battery_remaining_percent_keeps_documented_zero_to_100_units():
    class TelemetryStub:
        async def battery(self):
            yield type("Battery", (), {"remaining_percent": 91.0, "voltage_v": 15.7})()

    class SystemStub:
        telemetry = TelemetryStub()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = SystemStub()

    sample = asyncio.run(client.sample_battery(1.0))

    assert sample == {"remaining_percent": 91.0, "voltage_v": 15.7}


@pytest.mark.parametrize(
    "remaining_percent, voltage_v",
    [(math.nan, 15.7), (91.0, math.inf), (True, 15.7)],
)
def test_mavsdk_battery_rejects_invalid_numeric_telemetry(
    remaining_percent: float,
    voltage_v: float,
) -> None:
    class TelemetryStub:
        async def battery(self):
            yield type(
                "Battery",
                (),
                {"remaining_percent": remaining_percent, "voltage_v": voltage_v},
            )()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = type("SystemStub", (), {"telemetry": TelemetryStub()})()

    with pytest.raises(ValueError, match="must be a finite number"):
        asyncio.run(client.sample_battery(1.0))


def test_mavsdk_integer_parameter_bridge_uses_exact_int_api():
    class ParamStub:
        def __init__(self) -> None:
            self.value = 10

        async def get_param_int(self, name: str) -> int:
            assert name == "SIM_GPS_USED"
            return self.value

        async def set_param_int(self, name: str, value: int) -> None:
            assert name == "SIM_GPS_USED"
            self.value = value

    param = ParamStub()
    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = type("SystemStub", (), {"param": param})()

    assert asyncio.run(client.get_param_int("SIM_GPS_USED")) == 10
    asyncio.run(client.set_param_int("SIM_GPS_USED", 0))
    assert asyncio.run(client.get_param_int("SIM_GPS_USED")) == 0


def test_mavsdk_gps_info_preserves_fix_type_and_satellite_count():
    class FixTypeStub:
        value = 3
        name = "FIX_3D"

    class TelemetryStub:
        async def gps_info(self):
            yield type(
                "GpsInfo",
                (),
                {"num_satellites": 10, "fix_type": FixTypeStub()},
            )()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = type("SystemStub", (), {"telemetry": TelemetryStub()})()

    assert asyncio.run(client.sample_gps_info(1.0)) == {
        "num_satellites": 10,
        "fix_type": 3,
        "fix_type_name": "FIX_3D",
    }


@pytest.mark.parametrize(
    "num_satellites, fix_type",
    [(True, 3), (10.5, 3), (10, False), (10, 3.5)],
)
def test_mavsdk_gps_info_rejects_non_integer_telemetry(
    num_satellites: int | float | bool,
    fix_type: int | float | bool,
) -> None:
    class TelemetryStub:
        async def gps_info(self):
            yield type(
                "GpsInfo",
                (),
                {"num_satellites": num_satellites, "fix_type": fix_type},
            )()

    client = executor.MavsdkOffboardClient.__new__(executor.MavsdkOffboardClient)
    client._system = type("SystemStub", (), {"telemetry": TelemetryStub()})()

    with pytest.raises(ValueError, match="must be an integer"):
        asyncio.run(client.sample_gps_info(1.0))


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
