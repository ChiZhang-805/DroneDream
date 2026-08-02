from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
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
    client = executor.FakeOffboardClient()
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


def test_executor_waits_for_continuously_stable_hover_before_track_entry(
    tmp_path: Path,
) -> None:
    client = executor.FakeOffboardClient()
    client.position_velocity_samples = [
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
        "land": "command_sent",
        "close": "completed",
    }


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
        "land": "command_sent_during_failure_cleanup",
        "close": "completed",
    }


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
