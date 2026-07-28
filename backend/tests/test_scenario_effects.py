from __future__ import annotations

import copy
import hashlib
import json
import math

import pytest

from app.simulator.scenario_effects import (
    ScenarioEffectContractError,
    build_scenario_effect_evidence,
    build_scenario_effect_request,
    compile_bundled_runtime_profile,
    compile_bundled_sdf_profile,
    compile_bundled_steady_wind,
    scenario_effect_value_sha256,
    validate_scenario_effect_evidence,
    validate_scenario_effect_request,
)


def _identity() -> dict[str, object]:
    return {
        "trial_id": "trial-1",
        "job_id": "job-1",
        "candidate_id": "candidate-1",
        "seed": 42,
        "attempt_count": 1,
    }


def _request(*, advanced: dict[str, object], wind: bool = False):
    return build_scenario_effect_request(
        execution_identity=_identity(),
        scenario_type="nominal",
        scenario_config={"wind_mps": 3.0} if wind else {},
        job_config={
            "wind": {
                "north": 1.0 if wind else 0.0,
                "east": 0.0,
                "south": 0.0,
                "west": 0.0,
            },
            "sensor_noise_level": "high" if wind else "medium",
        },
        advanced_config=advanced,
    )


def _wind_only_request(
    *,
    seed: int = 42,
    cardinal: dict[str, float] | None = None,
    wind_mps: float | None = 3.0,
) -> dict[str, object]:
    scenario_config = {} if wind_mps is None else {"wind_mps": wind_mps}
    return build_scenario_effect_request(
        execution_identity={**_identity(), "seed": seed},
        scenario_type="nominal",
        scenario_config=scenario_config,
        job_config={
            "wind": cardinal or {"north": 1.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )


def _wind_evidence_records(request: dict[str, object]) -> list[dict[str, object]]:
    compiled = compile_bundled_steady_wind(request)
    assert compiled is not None
    readback = {
        "linear_velocity_mps": dict(compiled["linear_velocity_mps"]),
        "enable_wind": True,
    }
    runtime_sdf = {
        "source_vehicle_model": "x500_base",
        "vehicle_model": "x500_0",
        "link_name": "base_link",
        "enable_wind": True,
        "sdf_path": "/tmp/generated_world.sdf",
        "sdf_sha256": "a" * 64,
    }
    observations = [
        {
            "source": "/world/default/wind_info",
            "kind": "readback",
            "value": readback,
            "sha256": scenario_effect_value_sha256(readback),
        },
        {
            "source": "/world/default/generate_world_sdf",
            "kind": "artifact",
            "value": runtime_sdf,
            "sha256": scenario_effect_value_sha256(runtime_sdf),
        },
    ]
    return [
        {
            "effect_id": effect["effect_id"],
            "mechanism": effect["mechanism"],
            "status": "applied",
            "capability": {"status": "available", "reason": "bundled steady wind"},
            "evidence": {
                "requested_value_sha256": scenario_effect_value_sha256(effect["requested_value"]),
                "compiled_wind": compiled,
                "verification": {
                    "status": "verified",
                    "method": "gazebo_wind_info_and_generated_world_sdf",
                    "observations": copy.deepcopy(observations),
                },
            },
        }
        for effect in request["effects"]
    ]


def test_request_maps_every_advanced_field_to_launcher_effect() -> None:
    request = _request(
        wind=True,
        advanced={
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 4.0,
                "direction_deg": 135.0,
                "period_s": 8.0,
            },
            "obstacles": [
                {
                    "type": "cylinder",
                    "x": 2.0,
                    "y": 3.0,
                    "z": 1.5,
                    "radius": 0.5,
                    "height": 3.0,
                }
            ],
            "sensor_degradation": {
                "gps_noise_m": 2.0,
                "baro_noise_m": 0.5,
                "imu_noise_scale": 1.5,
                "dropout_rate": 0.2,
            },
            "battery": {
                "initial_percent": 60.0,
                "voltage_sag": True,
                "mass_payload_kg": 1.25,
            },
        },
    )

    effects = {item["effect_id"]: item for item in request["effects"]}
    assert set(effects) == {
        "job_config.wind",
        "job_config.sensor_noise_level",
        "scenario_config.wind_mps",
        "wind_gusts",
        "obstacles",
        "sensor_degradation.gps_noise_m",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "sensor_degradation.dropout_rate",
        "battery.initial_percent",
        "battery.voltage_sag",
        "battery.mass_payload_kg",
    }
    assert effects["obstacles"]["capability"]["status"] == "available"
    assert effects["obstacles"]["mechanism"] == "gazebo_entity_factory"
    assert effects["job_config.wind"]["capability"]["status"] == "available"
    assert effects["scenario_config.wind_mps"]["capability"]["status"] == "available"
    assert effects["wind_gusts"]["capability"]["status"] == "available"
    assert effects["wind_gusts"]["requested_value"] == {
        "enabled": True,
        "magnitude_mps": 4.0,
        "direction_deg": 135.0,
        "period_s": 8.0,
    }
    assert "WindEffects" in effects["wind_gusts"]["capability"]["reason"]
    assert effects["sensor_degradation.dropout_rate"]["capability"]["status"] == "available"
    assert "trial-seed-bound" in effects["sensor_degradation.dropout_rate"]["capability"]["reason"]
    assert effects["battery.initial_percent"]["capability"]["status"] == "available"
    assert "battery telemetry" in effects["battery.initial_percent"]["capability"]["reason"]
    assert "inertial" in effects["battery.mass_payload_kg"]["capability"]["reason"]
    assert all(
        item["launcher_input"]["request_path_env"] == "PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH"
        for item in effects.values()
    )


def test_compile_bundled_sdf_profile_binds_explicit_physics() -> None:
    request = _request(
        advanced={
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 4.0,
                "direction_deg": 90.0,
                "period_s": 8.0,
            },
            "sensor_degradation": {
                "gps_noise_m": 2.0,
                "baro_noise_m": 0.5,
                "imu_noise_scale": 1.5,
            },
            "battery": {"mass_payload_kg": 1.2},
        }
    )

    profile = compile_bundled_sdf_profile(request)

    assert profile is not None
    assert profile["wind_gust"] == {
        "peak_magnitude_mps": 4.0,
        "mean_magnitude_mps": 2.0,
        "direction_deg_clockwise_from_north": 90.0,
        "period_s": 8.0,
        "time_for_rise_s": 1.0,
        "mean_linear_velocity_mps": {"x": 2.0, "y": 0.0, "z": 0.0},
        "horizontal_magnitude_sine_amplitude_percent": 1.0,
        "range_mps": [0.0, 4.0],
        "effect_ids": ["wind_gusts"],
    }
    assert profile["sensor_noise"]["gps_position_stddev_m"] == 2.0
    assert profile["sensor_noise"]["barometer_altitude_stddev_m"] == 0.5
    assert profile["sensor_noise"]["barometer_pressure_stddev_pa"] == 6.0
    assert profile["sensor_noise"]["imu_noise_scale"] == 1.5
    assert profile["payload"]["mass_kg"] == 1.2
    assert profile["payload"]["assumption"] == "centered_uniform_cuboid"
    assert profile["payload"]["inertia_increment_kg_m2"] == {
        "ixx": pytest.approx(0.005),
        "iyy": pytest.approx(0.005),
        "izz": pytest.approx(0.008),
    }


def test_compile_bundled_runtime_profile_binds_dropout_and_battery() -> None:
    request = _request(
        advanced={
            "sensor_degradation": {"dropout_rate": 0.2},
            "battery": {"initial_percent": 60.0, "voltage_sag": True},
        }
    )

    profile = compile_bundled_runtime_profile(request)

    assert profile is not None
    assert profile["requested_effect_ids"] == [
        "battery.initial_percent",
        "battery.voltage_sag",
        "sensor_degradation.dropout_rate",
    ]
    assert len(profile["execution_identity_sha256"]) == 64
    assert profile["gps_dropout"] == {
        "requested_rate": 0.2,
        "tick_period_s": 1.0,
        "schedule_algorithm": "sha256-ranked-fixed-duty-v1",
        "parameter_name": "SIM_GPS_USED",
        "dropout_value": 0,
        "availability_source": "mavsdk.telemetry.gps_info",
        "effect_ids": ["sensor_degradation.dropout_rate"],
    }
    assert profile["battery"] == {
        "target_track_start_percent": 60.0,
        "voltage_sag": True,
        "sag_drain_seconds": 300.0,
        "no_sag_hold_drain_seconds": 86400.0,
        "parameter_names": ["SIM_BAT_DRAIN", "SIM_BAT_MIN_PCT"],
        "effect_ids": ["battery.initial_percent", "battery.voltage_sag"],
    }


def test_runtime_profile_rejects_conflicting_dropout_sources() -> None:
    request = build_scenario_effect_request(
        execution_identity=_identity(),
        scenario_type="gps_dropout",
        scenario_config={"dropout_rate": 0.4},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={"sensor_degradation": {"dropout_rate": 0.2}},
    )

    with pytest.raises(ScenarioEffectContractError, match="conflicting dropout rates"):
        compile_bundled_runtime_profile(request)


@pytest.mark.parametrize(
    ("scenario_type", "config", "section", "expected"),
    [
        (
            "noise_perturbed",
            {},
            "sensor_noise",
            {"gps_position_stddev_m": 1.0, "imu_noise_scale": 2.0},
        ),
        (
            "turbulence",
            {"intensity": 0.8},
            "wind_gust",
            {"peak_magnitude_mps": 4.0, "period_s": 5.0},
        ),
        (
            "payload_changed",
            {"mass_payload_kg": 1.5},
            "payload",
            {"mass_kg": 1.5},
        ),
        (
            "actuator_delay",
            {"delay_ms": 80.0},
            "actuator_dynamics",
            {"time_constant_up_s": 0.08, "time_constant_down_s": 0.08},
        ),
        (
            "actuator_failure",
            {
                "motor_number": 2,
                "failure_mode": "stuck_stopped_at_launch",
            },
            "actuator_failure",
            {
                "target_motor_number": 2,
                "max_rot_velocity_rad_s": 0.0,
            },
        ),
    ],
)
def test_scenario_markers_compile_to_concrete_sdf_profiles(
    scenario_type: str,
    config: dict[str, object],
    section: str,
    expected: dict[str, object],
) -> None:
    request = build_scenario_effect_request(
        execution_identity=_identity(),
        scenario_type=scenario_type,
        scenario_config=config,
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )

    profile = compile_bundled_sdf_profile(request)

    assert profile is not None
    for key, value in expected.items():
        assert profile[section][key] == value


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"motor_number": True}, "motor_number must be an integer"),
        ({"motor_number": -1}, "motor_number must be an integer"),
        ({"motor_number": 4}, "motor_number must be an integer"),
        (
            {"failure_mode": "intermittent"},
            "failure_mode must be 'stuck_stopped_at_launch'",
        ),
    ],
)
def test_actuator_failure_profile_rejects_unverifiable_modes(
    config: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ScenarioEffectContractError, match=message):
        build_scenario_effect_request(
            execution_identity=_identity(),
            scenario_type="actuator_failure",
            scenario_config=config,
            job_config={
                "wind": {
                    "north": 0.0,
                    "east": 0.0,
                    "south": 0.0,
                    "west": 0.0,
                },
                "sensor_noise_level": "medium",
            },
            advanced_config={},
        )


def test_actuator_failure_default_motor_is_seed_deterministic() -> None:
    def compile_for(seed: int) -> dict[str, object]:
        request = build_scenario_effect_request(
            execution_identity={**_identity(), "seed": seed},
            scenario_type="actuator_failure",
            scenario_config={},
            job_config={
                "wind": {
                    "north": 0.0,
                    "east": 0.0,
                    "south": 0.0,
                    "west": 0.0,
                },
                "sensor_noise_level": "medium",
            },
            advanced_config={},
        )
        profile = compile_bundled_sdf_profile(request)
        assert profile is not None
        return profile["actuator_failure"]

    assert compile_for(42) == compile_for(42)
    assert 0 <= int(compile_for(42)["target_motor_number"]) <= 3


def test_request_hash_rejects_tampering() -> None:
    request = _request(advanced={}, wind=True)
    tampered = copy.deepcopy(request)
    tampered["effects"][0]["requested_value"] = {"north": 99.0}

    with pytest.raises(ScenarioEffectContractError, match="hash does not match"):
        validate_scenario_effect_request(tampered)


def test_obstacle_applied_evidence_requires_gazebo_ack_and_sdf_hash() -> None:
    request = _request(
        advanced={
            "obstacles": [
                {
                    "type": "box",
                    "x": 1.0,
                    "y": 2.0,
                    "z": 0.5,
                    "size_x": 1.0,
                    "size_y": 2.0,
                    "size_z": 1.0,
                }
            ]
        }
    )
    payload = build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=[
            {
                "effect_id": "obstacles",
                "mechanism": "gazebo_entity_factory",
                "status": "applied",
                "capability": {"status": "available", "reason": "test"},
                "evidence": {
                    "created_entities": [
                        {
                            "source_index": 0,
                            "entity_name": "dronedream_obstacle_000",
                            "service": "/world/default/create",
                            "response_data": True,
                            "sdf_sha256": "a" * 64,
                        }
                    ]
                },
            }
        ],
    )

    normalized = validate_scenario_effect_evidence(request, payload)

    assert normalized["verification_status"] == "verified_applied"
    assert normalized["applied_effects"] == ["obstacles"]

    rejected = copy.deepcopy(payload)
    rejected["effects"][0]["evidence"]["created_entities"][0]["response_data"] = False
    with pytest.raises(ScenarioEffectContractError, match="Boolean response"):
        validate_scenario_effect_evidence(request, rejected)


def test_launcher_cannot_claim_unimplemented_wind_as_applied_without_readback() -> None:
    request = _request(advanced={}, wind=True)
    payload = build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=[
            {
                "effect_id": item["effect_id"],
                "mechanism": item["mechanism"],
                "status": "applied",
                "capability": {"status": "available", "reason": "claimed"},
            }
            for item in request["effects"]
        ],
    )

    with pytest.raises(
        ScenarioEffectContractError,
        match="applied evidence must be an object",
    ):
        validate_scenario_effect_evidence(request, payload)


def test_extended_launcher_can_prove_site_specific_effect_with_bound_readback() -> None:
    request = build_scenario_effect_request(
        execution_identity=_identity(),
        scenario_type="custom",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )
    records = []
    for item in request["effects"]:
        value_hash = hashlib.sha256(
            json.dumps(
                item["requested_value"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        records.append(
            {
                "effect_id": item["effect_id"],
                "mechanism": item["mechanism"],
                "status": "applied",
                "capability": {"status": "available", "reason": "runtime extension"},
                "evidence": {
                    "requested_value_sha256": value_hash,
                    "verification": {
                        "status": "verified",
                        "method": "integration-test-readback",
                        "observations": [
                            {
                                "source": "/world/default/test_readback",
                                "kind": "readback",
                                "value": item["requested_value"],
                                "sha256": value_hash,
                            }
                        ],
                    },
                },
            }
        )
    payload = build_scenario_effect_evidence(
        request,
        launcher="extended-test-launcher",
        world="default",
        effects=records,
    )

    normalized = validate_scenario_effect_evidence(request, payload)

    assert normalized["verification_status"] == "verified_applied"
    assert normalized["applied_effects"] == sorted(item["effect_id"] for item in request["effects"])

    rejected = copy.deepcopy(payload)
    rejected["effects"][0]["evidence"]["verification"]["observations"][0]["sha256"] = "0" * 64
    with pytest.raises(ScenarioEffectContractError, match="hash does not match"):
        validate_scenario_effect_evidence(request, rejected)


def test_bundled_steady_wind_compiles_cardinal_components_into_gazebo_enu() -> None:
    request = _wind_only_request(
        cardinal={"north": 3.0, "east": 4.0, "south": 1.0, "west": 0.5},
        wind_mps=None,
    )

    compiled = compile_bundled_steady_wind(request)

    assert compiled is not None
    assert compiled["coordinate_frame"] == "GAZEBO_WORLD_ENU"
    assert compiled["linear_velocity_mps"] == {"x": 3.5, "y": 2.0, "z": 0.0}
    assert compiled["speed_mps"] == pytest.approx(math.hypot(3.5, 2.0))


def test_scalar_steady_wind_direction_is_seeded_and_repeatable() -> None:
    first = compile_bundled_steady_wind(
        _wind_only_request(
            seed=42,
            cardinal={"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
        )
    )
    repeated = compile_bundled_steady_wind(
        _wind_only_request(
            seed=42,
            cardinal={"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
        )
    )
    different = compile_bundled_steady_wind(
        _wind_only_request(
            seed=43,
            cardinal={"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
        )
    )

    assert first == repeated
    assert first is not None and different is not None
    assert first["speed_mps"] == pytest.approx(3.0)
    assert first["linear_velocity_mps"] != different["linear_velocity_mps"]


def test_combined_steady_wind_limit_is_fail_closed() -> None:
    with pytest.raises(ScenarioEffectContractError, match="combined steady wind"):
        _wind_only_request(
            cardinal={"north": 29.0, "east": 0.0, "south": 0.0, "west": 0.0},
            wind_mps=3.0,
        )


def test_bundled_steady_wind_requires_exact_readback_and_runtime_wind_mode() -> None:
    request = _wind_only_request()
    records = _wind_evidence_records(request)
    payload = build_scenario_effect_evidence(
        request,
        launcher="bundled-test-launcher",
        world="default",
        effects=records,
    )

    normalized = validate_scenario_effect_evidence(request, payload)

    assert normalized["verification_status"] == "verified_applied"
    assert normalized["applied_effects"] == [
        "job_config.wind",
        "scenario_config.wind_mps",
    ]

    mismatched = copy.deepcopy(payload)
    mismatched["effects"][0]["evidence"]["verification"]["observations"][0]["value"][
        "linear_velocity_mps"
    ]["x"] += 0.5
    mismatched["effects"][0]["evidence"]["verification"]["observations"][0]["sha256"] = (
        scenario_effect_value_sha256(
            mismatched["effects"][0]["evidence"]["verification"]["observations"][0]["value"]
        )
    )
    with pytest.raises(ScenarioEffectContractError, match="exact Gazebo wind_info"):
        validate_scenario_effect_evidence(request, mismatched)

    no_wind_mode = copy.deepcopy(payload)
    no_wind_mode["effects"][0]["evidence"]["verification"]["observations"][1]["value"][
        "enable_wind"
    ] = False
    no_wind_mode["effects"][0]["evidence"]["verification"]["observations"][1]["sha256"] = (
        scenario_effect_value_sha256(
            no_wind_mode["effects"][0]["evidence"]["verification"]["observations"][1]["value"]
        )
    )
    with pytest.raises(ScenarioEffectContractError, match="WindMode"):
        validate_scenario_effect_evidence(request, no_wind_mode)


def test_extended_evidence_rejects_requested_value_hash_mismatch() -> None:
    request = _request(advanced={}, wind=True)
    item = request["effects"][0]
    records = [
        {
            "effect_id": effect["effect_id"],
            "mechanism": effect["mechanism"],
            "status": "unsupported",
            "capability": {"status": "unsupported", "reason": "not under test"},
            "reason": "not under test",
        }
        for effect in request["effects"]
    ]
    records[0] = {
        "effect_id": item["effect_id"],
        "mechanism": item["mechanism"],
        "status": "applied",
        "capability": {"status": "available", "reason": "runtime extension"},
        "evidence": {
            "requested_value_sha256": "0" * 64,
            "verification": {
                "status": "verified",
                "method": "test",
                "observations": [{"source": "test", "kind": "readback", "value": 1.0}],
            },
        },
    }
    payload = build_scenario_effect_evidence(
        request,
        launcher="extended-test-launcher",
        world="default",
        effects=records,
    )

    with pytest.raises(ScenarioEffectContractError, match="not bound"):
        validate_scenario_effect_evidence(request, payload)


def test_evidence_must_cover_every_requested_effect() -> None:
    request = _request(advanced={}, wind=True)
    payload = build_scenario_effect_evidence(
        request,
        launcher="test",
        world="default",
        effects=[],
    )

    with pytest.raises(ScenarioEffectContractError, match="omitted requested effects"):
        validate_scenario_effect_evidence(request, payload)


def test_combined_scenario_uses_explicit_effects_without_unappliable_label() -> None:
    request = build_scenario_effect_request(
        execution_identity=_identity(),
        scenario_type="combined_perturbed",
        scenario_config={"wind_mps": 3.0},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "high",
        },
        advanced_config={},
    )

    effect_ids = {item["effect_id"] for item in request["effects"]}
    assert effect_ids == {
        "scenario_config.wind_mps",
        "job_config.sensor_noise_level",
    }
    assert "scenario_type.combined_perturbed" not in effect_ids


def test_combined_scenario_without_explicit_effects_keeps_guard_marker() -> None:
    request = build_scenario_effect_request(
        execution_identity=_identity(),
        scenario_type="combined_perturbed",
        scenario_config={},
        job_config={
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
        },
        advanced_config={},
    )

    assert [item["effect_id"] for item in request["effects"]] == [
        "scenario_type.combined_perturbed"
    ]


def test_request_builder_rejects_pathologically_deep_custom_config() -> None:
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(40):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child

    with pytest.raises(ScenarioEffectContractError, match="contract depth"):
        build_scenario_effect_request(
            execution_identity=_identity(),
            scenario_type="custom",
            scenario_config=nested,
            job_config={
                "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
                "sensor_noise_level": "medium",
            },
            advanced_config={},
        )


def test_request_rejects_tampered_launcher_input_contract() -> None:
    request = _request(advanced={}, wind=True)
    tampered = copy.deepcopy(request)
    tampered["effects"][0]["launcher_input"]["request_path_env"] = "UNTRUSTED_PATH"
    body = {key: value for key, value in tampered.items() if key != "request_sha256"}
    tampered["request_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ScenarioEffectContractError, match="launcher_input contract"):
        validate_scenario_effect_request(tampered)
