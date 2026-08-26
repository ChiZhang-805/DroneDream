"""Scenario-effect request and evidence contracts for PX4/Gazebo trials.

The API/worker side describes *what* a trial asks the simulator to change.  A
launcher must then report, effect by effect, whether it applied the request or
why the runtime cannot support it.  The outer runner validates that evidence
before any trial can pass; merely receiving an input field is never considered
proof of a physical Gazebo/PX4 effect.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

REQUEST_SCHEMA_VERSION = "dronedream.scenario_effect_request.v1"
EVIDENCE_SCHEMA_VERSION = "dronedream.scenario_effect_evidence.v1"
REQUEST_ARTIFACT_NAME = "scenario_effects.request.json"
EVIDENCE_ARTIFACT_NAME = "scenario_effects.applied.json"
RUNTIME_EVIDENCE_ARTIFACT_NAME = "scenario_effects.runtime.json"
MAX_EFFECT_CONTRACT_BYTES = 2 * 1024 * 1024
MAX_EFFECTS_PER_REQUEST = 64
MAX_EVIDENCE_OBSERVATIONS = 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
MAX_BUNDLED_STEADY_WIND_MPS = 30.0
DEFAULT_SCENARIO_STEADY_WIND_MPS = 3.0
BUNDLED_STEADY_WIND_EFFECT_IDS = frozenset(
    {
        "job_config.wind",
        "scenario_config.wind_mps",
        "scenario_type.wind_perturbed",
    }
)
BUNDLED_SDF_PROFILE_EFFECT_IDS = frozenset(
    {
        "wind_gusts",
        "scenario_type.turbulence",
        "job_config.sensor_noise_level",
        "sensor_degradation.gps_noise_m",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "scenario_type.noise_perturbed",
        "battery.mass_payload_kg",
        "scenario_type.payload_changed",
        "scenario_type.actuator_delay",
        "scenario_type.actuator_failure",
    }
)
BUNDLED_RUNTIME_EFFECT_IDS = frozenset(
    {
        "sensor_degradation.dropout_rate",
        "scenario_config.dropout_rate",
        "scenario_type.gps_dropout",
        "battery.initial_percent",
        "battery.voltage_sag",
        "scenario_type.battery_degraded",
    }
)
BUNDLED_WIND_ACTIVATION_EFFECT_IDS = frozenset(
    {
        *BUNDLED_STEADY_WIND_EFFECT_IDS,
        "wind_gusts",
        "scenario_type.turbulence",
    }
)
BAROMETER_PRESSURE_PA_PER_ALTITUDE_M = 12.0
NAVSAT_WHITE_NOISE_FRACTION = 0.01
NAVSAT_DYNAMIC_BIAS_CORRELATION_TIME_S = 60.0
DEFAULT_TURBULENCE_PEAK_MPS = 5.0
DEFAULT_TURBULENCE_PERIOD_S = 5.0
DEFAULT_PAYLOAD_MASS_KG = 1.0
DEFAULT_ACTUATOR_DELAY_MS = 80.0
DEFAULT_ACTUATOR_FAILURE_MODE = "stuck_stopped_at_launch"
ACTUATOR_FAILURE_JOINT_STATE_TOPIC = "/dronedream/actuator_failure/joint_state"
MAX_FAILED_MOTOR_ABS_VELOCITY_RAD_S = 0.05
MIN_HEALTHY_MOTOR_ABS_VELOCITY_RAD_S = 1.0
DEFAULT_GPS_DROPOUT_RATE = 0.2
DEFAULT_BATTERY_INITIAL_PERCENT = 45.0
DEFAULT_BATTERY_SAG_DRAIN_SECONDS = 300.0
_SENSOR_NOISE_PRESETS = {
    "low": {
        # Static NavSat noise is present before PX4 arms.  Even modest
        # continuous position drift can correctly trip PX4's estimator health
        # gate, so general low/high presets keep GNSS nominal.  Expert GPS
        # stress remains available through the explicit gps_noise_m field.
        "gps_position_stddev_m": 0.0,
        "barometer_pressure_stddev_pa": 1.5,
        "imu_noise_scale": 0.5,
    },
    "high": {
        "gps_position_stddev_m": 0.0,
        "barometer_pressure_stddev_pa": 6.0,
        "imu_noise_scale": 2.0,
    },
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ScenarioEffectContractError(ValueError):
    """Raised when an effect request or launcher evidence is malformed."""


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _request_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "request_sha256"}
    return hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _value_hash(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def scenario_effect_value_sha256(value: object) -> str:
    """Return the canonical digest used by scenario-effect evidence."""

    _validate_json_tree(value, path="scenario effect value")
    return _value_hash(value)


def scenario_effect_request_sha256(payload: object) -> str:
    """Return the canonical digest used by a scenario-effect request."""

    if not isinstance(payload, dict):
        raise ScenarioEffectContractError("scenario effect request must be an object")
    _validate_json_tree(payload, path="scenario effect request")
    return _request_hash(payload)


def _validate_json_tree(
    value: object,
    *,
    path: str,
    depth: int = 0,
    budget: list[int] | None = None,
) -> None:
    """Reject non-finite or pathologically large contract subtrees.

    Contracts normally arrive from files with a byte limit, but the same
    validators are also called directly by custom launchers and tests.  A node
    and depth budget keeps those in-memory calls bounded as well.
    """

    if budget is None:
        budget = [MAX_JSON_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        raise ScenarioEffectContractError(
            f"{path} exceeds the {MAX_JSON_NODES}-node contract limit"
        )
    if depth > MAX_JSON_DEPTH:
        raise ScenarioEffectContractError(
            f"{path} exceeds the {MAX_JSON_DEPTH}-level contract depth"
        )
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ScenarioEffectContractError(f"{path} must contain only finite numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_tree(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                budget=budget,
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ScenarioEffectContractError(f"{path} object keys must be strings")
            _validate_json_tree(
                item,
                path=f"{path}.{key}",
                depth=depth + 1,
                budget=budget,
            )
        return
    raise ScenarioEffectContractError(f"{path} contains a non-JSON value")


def _finite_number(
    section: dict[str, Any],
    name: str,
    *,
    path: str,
    default: float,
) -> float:
    value = section.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioEffectContractError(f"{path}.{name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ScenarioEffectContractError(f"{path}.{name} must be finite")
    return normalized


def _unsupported_reason(effect_id: str) -> str:
    if effect_id == "scenario_type.combined_perturbed":
        return (
            "combined_perturbed is a scenario label, not a physical injection; "
            "provide explicit wind/noise/degradation inputs supported by the launcher"
        )
    if effect_id == "scenario_type.custom":
        return (
            "custom scenario effects require a site-specific launcher capability and "
            "verifiable applied-effects evidence"
        )
    return "the bundled launcher has no verified implementation for this effect"


def _mechanism_for(effect_id: str) -> str:
    if effect_id == "obstacles":
        return "gazebo_entity_factory"
    if "wind" in effect_id or effect_id.endswith("turbulence"):
        return "gazebo_wind_effects"
    if effect_id.startswith("sensor_degradation") or "noise" in effect_id:
        return "px4_sim_gps_used" if "dropout" in effect_id else "sdformat_sensor_noise"
    if "gps_dropout" in effect_id or effect_id.endswith("dropout_rate"):
        return "px4_sim_gps_used"
    if "payload" in effect_id:
        return "sdformat_model_inertial"
    if effect_id.startswith("battery") or effect_id.endswith("battery_degraded"):
        return "px4_battery_simulation"
    if "actuator_delay" in effect_id:
        return "sdformat_actuator_dynamics"
    if "actuator_failure" in effect_id:
        return "sdformat_actuator_hard_stop"
    return "site_specific"


def _available_reason(effect_id: str) -> str:
    if effect_id == "obstacles":
        return (
            "the bundled launcher can create static obstacles through Gazebo "
            "/world/<world>/create and verifies the Boolean service response"
        )
    if effect_id in BUNDLED_STEADY_WIND_EFFECT_IDS:
        return (
            "the bundled launcher generates a Trial-local Gazebo WindEffects world/model "
            "overlay, verifies /world/<world>/wind_info, and inspects generated runtime SDF"
        )
    if effect_id in {"wind_gusts", "scenario_type.turbulence"}:
        return (
            "the bundled launcher compiles a deterministic Gazebo WindEffects sinusoidal "
            "profile and verifies its generated runtime SDF"
        )
    if effect_id in {
        "job_config.sensor_noise_level",
        "sensor_degradation.gps_noise_m",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "scenario_type.noise_perturbed",
    }:
        return (
            "the bundled launcher generates a Trial-local x500 sensor SDF and verifies "
            "the exact noise fields in Gazebo generated runtime SDF"
        )
    if effect_id in {"battery.mass_payload_kg", "scenario_type.payload_changed"}:
        return (
            "the bundled launcher adds a documented centered cuboid payload to the x500 "
            "inertial mass and tensor in a Trial-local model and verifies generated runtime SDF"
        )
    if effect_id == "scenario_type.actuator_delay":
        return (
            "the bundled launcher maps delay_ms to x500 motor first-order response time "
            "constants in Trial-local SDF and verifies every runtime motor plugin"
        )
    if effect_id == "scenario_type.actuator_failure":
        return (
            "the bundled launcher hard-clamps one deterministic x500 motor to zero "
            "maximum rotational velocity in Trial-local SDF, verifies generated runtime "
            "SDF, and requires Gazebo joint-state proof that the failed rotor remains "
            "stopped while at least one healthy rotor turns"
        )
    if effect_id in {
        "sensor_degradation.dropout_rate",
        "scenario_config.dropout_rate",
        "scenario_type.gps_dropout",
    }:
        return (
            "the bundled offboard executor compiles the requested dropout rate into "
            "a trial-seed-bound one-second schedule, verifies each transition from the "
            "PX4 physical failure handler's STATUSTEXT, and verifies reset to GPS OK"
        )
    if effect_id in {
        "battery.initial_percent",
        "battery.voltage_sag",
        "scenario_type.battery_degraded",
    }:
        return (
            "the bundled offboard executor applies and reads back SIM_BAT_DRAIN and "
            "SIM_BAT_MIN_PCT, observes battery telemetry at the track boundary, and "
            "records the continuing sag or target floor without treating a parameter "
            "write alone as physical proof"
        )
    raise ScenarioEffectContractError(f"no bundled capability reason for {effect_id}")


def _seed_bearing_deg(execution_identity: dict[str, Any]) -> float:
    seed = execution_identity.get("seed")
    seed_material: object
    if isinstance(seed, int) and not isinstance(seed, bool):
        seed_material = {"seed": seed}
    else:
        seed_material = {"execution_identity": execution_identity}
    digest = hashlib.sha256(_canonical_bytes(seed_material)).digest()
    # A millidegree grid is deterministic across Python/platform versions and
    # covers every horizontal direction without importing a PRNG.
    return (int.from_bytes(digest[:8], "big") % 360_000) / 1000.0


def _seed_motor_number(execution_identity: dict[str, Any]) -> int:
    seed = execution_identity.get("seed")
    seed_material: object
    if isinstance(seed, int) and not isinstance(seed, bool):
        seed_material = {"seed": seed, "purpose": "actuator_failure_motor"}
    else:
        seed_material = {
            "execution_identity": execution_identity,
            "purpose": "actuator_failure_motor",
        }
    digest = hashlib.sha256(_canonical_bytes(seed_material)).digest()
    return int.from_bytes(digest[:8], "big") % 4


def _wind_vector_from_bearing(magnitude_mps: float, bearing_deg: float) -> dict[str, float]:
    """Convert a compass bearing into Gazebo ENU x/east, y/north, z/up."""

    radians = math.radians(bearing_deg)
    return {
        "x": round(magnitude_mps * math.sin(radians), 12),
        "y": round(magnitude_mps * math.cos(radians), 12),
        "z": 0.0,
    }


def _compile_bundled_steady_wind_unchecked(request: dict[str, Any]) -> dict[str, Any] | None:
    steady_effects = [
        effect
        for effect in request.get("effects", [])
        if effect.get("effect_id") in BUNDLED_STEADY_WIND_EFFECT_IDS
    ]
    if not steady_effects:
        return None

    components: list[dict[str, Any]] = []
    total = {"x": 0.0, "y": 0.0, "z": 0.0}
    seed_bearing = _seed_bearing_deg(request.get("execution_identity", {}))
    for effect in steady_effects:
        effect_id = effect["effect_id"]
        requested_value = effect["requested_value"]
        if effect_id == "job_config.wind":
            if not isinstance(requested_value, dict):
                raise ScenarioEffectContractError("job_config.wind effect value must be an object")
            vector = {
                # Gazebo's world frame is ENU: x=east, y=north, z=up.
                "x": round(
                    float(requested_value.get("east", 0.0))
                    - float(requested_value.get("west", 0.0)),
                    12,
                ),
                "y": round(
                    float(requested_value.get("north", 0.0))
                    - float(requested_value.get("south", 0.0)),
                    12,
                ),
                "z": 0.0,
            }
            rule = "cardinal_components_to_gazebo_enu"
            bearing: float | None = None
        elif effect_id == "scenario_config.wind_mps":
            magnitude = float(requested_value)
            vector = _wind_vector_from_bearing(magnitude, seed_bearing)
            rule = "trial_seed_compass_bearing_clockwise_from_north"
            bearing = seed_bearing
        else:
            vector = _wind_vector_from_bearing(
                DEFAULT_SCENARIO_STEADY_WIND_MPS,
                seed_bearing,
            )
            rule = "wind_perturbed_default_trial_seed_compass_bearing"
            bearing = seed_bearing

        component_speed = math.hypot(vector["x"], vector["y"])
        if component_speed > MAX_BUNDLED_STEADY_WIND_MPS + 1e-9:
            raise ScenarioEffectContractError(
                f"{effect_id} steady wind magnitude exceeds {MAX_BUNDLED_STEADY_WIND_MPS:g} m/s"
            )
        total["x"] = round(total["x"] + vector["x"], 12)
        total["y"] = round(total["y"] + vector["y"], 12)
        components.append(
            {
                "effect_id": effect_id,
                "linear_velocity_mps": vector,
                "direction_rule": rule,
                "bearing_deg_clockwise_from_north": bearing,
            }
        )

    total_speed = math.hypot(total["x"], total["y"])
    if total_speed > MAX_BUNDLED_STEADY_WIND_MPS + 1e-9:
        raise ScenarioEffectContractError(
            f"combined steady wind magnitude exceeds {MAX_BUNDLED_STEADY_WIND_MPS:g} m/s"
        )
    return {
        "coordinate_frame": "GAZEBO_WORLD_ENU",
        "linear_velocity_mps": total,
        "speed_mps": round(total_speed, 12),
        "aggregation": "vector_sum",
        "components": components,
        "requested_effect_ids": sorted(effect["effect_id"] for effect in steady_effects),
    }


def compile_bundled_steady_wind(request: dict[str, Any]) -> dict[str, Any] | None:
    """Compile all bundled steady-wind effects into one deterministic ENU vector."""

    validate_scenario_effect_request(request)
    return _compile_bundled_steady_wind_unchecked(request)


def _compose_collinear_steady_wind_and_gust(
    request: dict[str, Any],
    gust_profile: dict[str, Any],
) -> dict[str, Any]:
    """Express an exact same-direction steady + sinusoidal gust profile.

    Gazebo's bundled WindEffects system modulates the magnitude of one
    horizontal wind vector.  It can therefore represent a non-zero steady
    component plus a ``0..peak`` gust exactly only when both components share
    one direction.  Reject other vector combinations instead of silently
    rotating or weakening either requested effect.
    """

    steady = _compile_bundled_steady_wind_unchecked(request)
    if steady is None or float(steady["speed_mps"]) <= 1e-9:
        return gust_profile

    steady_vector = steady["linear_velocity_mps"]
    gust_vector = gust_profile["mean_linear_velocity_mps"]
    steady_speed = math.hypot(float(steady_vector["x"]), float(steady_vector["y"]))
    gust_mean_speed = math.hypot(float(gust_vector["x"]), float(gust_vector["y"]))
    if gust_mean_speed <= 1e-9:
        combined_vector = {
            "x": round(float(steady_vector["x"]), 12),
            "y": round(float(steady_vector["y"]), 12),
            "z": 0.0,
        }
        combined_mean_speed = steady_speed
        direction_deg = math.degrees(
            math.atan2(combined_vector["x"], combined_vector["y"])
        ) % 360.0
    else:
        alignment = (
            float(steady_vector["x"]) * float(gust_vector["x"])
            + float(steady_vector["y"]) * float(gust_vector["y"])
        ) / (steady_speed * gust_mean_speed)
        if not math.isclose(alignment, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ScenarioEffectContractError(
                "bundled WindEffects requires non-zero steady wind and sinusoidal "
                "gusts to share the same horizontal direction; align the gust "
                "direction with the steady-wind vector or split them into separate "
                "physical scenarios"
            )
        combined_vector = {
            "x": round(float(steady_vector["x"]) + float(gust_vector["x"]), 12),
            "y": round(float(steady_vector["y"]) + float(gust_vector["y"]), 12),
            "z": 0.0,
        }
        combined_mean_speed = math.hypot(combined_vector["x"], combined_vector["y"])
        direction_deg = float(gust_profile["direction_deg_clockwise_from_north"])

    gust_peak_speed = float(gust_profile["peak_magnitude_mps"])
    amplitude_percent = (
        0.0 if combined_mean_speed <= 1e-9 else gust_mean_speed / combined_mean_speed
    )
    composed = dict(gust_profile)
    composed.update(
        {
            "mean_magnitude_mps": round(combined_mean_speed, 12),
            "direction_deg_clockwise_from_north": round(direction_deg, 12),
            "mean_linear_velocity_mps": combined_vector,
            "horizontal_magnitude_sine_amplitude_percent": round(
                amplitude_percent,
                12,
            ),
            "range_mps": [
                round(steady_speed, 12),
                round(steady_speed + gust_peak_speed, 12),
            ],
            "composition_policy": "collinear-vector-superposition-v1",
            "steady_component_magnitude_mps": round(steady_speed, 12),
            "steady_component_linear_velocity_mps": dict(steady_vector),
            "gust_component_peak_magnitude_mps": round(gust_peak_speed, 12),
            "gust_component_mean_magnitude_mps": round(gust_mean_speed, 12),
        }
    )
    return composed


def _scenario_marker_config(effect: dict[str, Any], *, effect_id: str) -> dict[str, Any]:
    value = effect.get("requested_value")
    if not isinstance(value, dict):
        raise ScenarioEffectContractError(f"{effect_id} value must be an object")
    config = value.get("config", {})
    if not isinstance(config, dict):
        raise ScenarioEffectContractError(f"{effect_id} config must be an object")
    return config


def _bounded_profile_number(
    value: object,
    *,
    path: str,
    lower: float,
    upper: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioEffectContractError(f"{path} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not lower <= normalized <= upper:
        raise ScenarioEffectContractError(f"{path} must be finite and in [{lower:g}, {upper:g}]")
    return normalized


def _compile_bundled_sdf_profile_unchecked(
    request: dict[str, Any],
) -> dict[str, Any] | None:
    effects = [
        effect
        for effect in request.get("effects", [])
        if effect.get("effect_id") in BUNDLED_SDF_PROFILE_EFFECT_IDS
    ]
    if not effects:
        return None

    requested_effect_ids = sorted(str(effect["effect_id"]) for effect in effects)
    by_id = {str(effect["effect_id"]): effect for effect in effects}
    profile: dict[str, Any] = {
        "requested_effect_ids": requested_effect_ids,
        "vehicle_family": "x500",
    }

    sensor_ids = {
        "job_config.sensor_noise_level",
        "sensor_degradation.gps_noise_m",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "scenario_type.noise_perturbed",
    }
    if sensor_ids & set(by_id):
        preset_name = "high" if "scenario_type.noise_perturbed" in by_id else None
        preset_effect = by_id.get("job_config.sensor_noise_level")
        if preset_effect is not None:
            requested_preset = preset_effect.get("requested_value")
            if requested_preset not in _SENSOR_NOISE_PRESETS:
                raise ScenarioEffectContractError(
                    "job_config.sensor_noise_level physical profile must be low or high"
                )
            preset_name = str(requested_preset)
        preset = dict(_SENSOR_NOISE_PRESETS.get(preset_name or "", {}))
        gps_stddev = float(preset.get("gps_position_stddev_m", 0.0))
        barometer_stddev_pa = float(preset.get("barometer_pressure_stddev_pa", 3.0))
        imu_scale = float(preset.get("imu_noise_scale", 1.0))

        gps_effect = by_id.get("sensor_degradation.gps_noise_m")
        if gps_effect is not None:
            gps_stddev = _bounded_profile_number(
                gps_effect.get("requested_value"),
                path="sensor_degradation.gps_noise_m",
                lower=0.0,
                upper=100.0,
            )
        baro_effect = by_id.get("sensor_degradation.baro_noise_m")
        barometer_altitude_stddev_m: float | None = None
        if baro_effect is not None:
            barometer_altitude_stddev_m = _bounded_profile_number(
                baro_effect.get("requested_value"),
                path="sensor_degradation.baro_noise_m",
                lower=0.0,
                upper=100.0,
            )
            barometer_stddev_pa = round(
                barometer_altitude_stddev_m * BAROMETER_PRESSURE_PA_PER_ALTITUDE_M,
                12,
            )
        imu_effect = by_id.get("sensor_degradation.imu_noise_scale")
        if imu_effect is not None:
            imu_scale = _bounded_profile_number(
                imu_effect.get("requested_value"),
                path="sensor_degradation.imu_noise_scale",
                lower=0.0,
                upper=10.0,
            )
        navsat_white_stddev_m = gps_stddev * NAVSAT_WHITE_NOISE_FRACTION
        navsat_dynamic_bias_stddev_m = math.sqrt(
            max(0.0, gps_stddev**2 - navsat_white_stddev_m**2)
        )
        profile["sensor_noise"] = {
            "preset": preset_name,
            "gps_position_stddev_m": gps_stddev,
            # SDFormat 1.11 defines both NavSat position_sensing noise
            # directions in metres.  Gazebo converts the horizontal offset to
            # geodetic coordinates internally; pre-converting it to degrees
            # made the applied disturbance 111,319x smaller than requested.
            "gazebo_navsat_white_stddev_m": navsat_white_stddev_m,
            "gazebo_navsat_dynamic_bias_stddev_m": navsat_dynamic_bias_stddev_m,
            "gazebo_navsat_dynamic_bias_correlation_time_s": (
                NAVSAT_DYNAMIC_BIAS_CORRELATION_TIME_S
            ),
            "gazebo_navsat_noise_composition_policy": (
                "requested-total-stddev-as-slow-bias-with-one-percent-white-noise-v1"
            ),
            "gazebo_navsat_unit_policy": "sdformat-1.11-horizontal-metres-vertical-metres-v2",
            "barometer_pressure_stddev_pa": barometer_stddev_pa,
            "barometer_altitude_stddev_m": barometer_altitude_stddev_m,
            "barometer_pressure_pa_per_altitude_m": BAROMETER_PRESSURE_PA_PER_ALTITUDE_M,
            "imu_noise_scale": imu_scale,
            "effect_ids": sorted(sensor_ids & set(by_id)),
        }

    gust_effect = by_id.get("wind_gusts")
    turbulence_effect = by_id.get("scenario_type.turbulence")
    if gust_effect is not None or turbulence_effect is not None:
        if gust_effect is not None:
            value = gust_effect.get("requested_value")
            if not isinstance(value, dict):
                raise ScenarioEffectContractError("wind_gusts value must be an object")
            peak_mps = _bounded_profile_number(
                value.get("magnitude_mps"),
                path="wind_gusts.magnitude_mps",
                lower=0.0,
                upper=MAX_BUNDLED_STEADY_WIND_MPS,
            )
            direction_deg = _bounded_profile_number(
                value.get("direction_deg"),
                path="wind_gusts.direction_deg",
                lower=0.0,
                upper=359.999999999999,
            )
            period_s = _bounded_profile_number(
                value.get("period_s"),
                path="wind_gusts.period_s",
                lower=1e-9,
                upper=300.0,
            )
        else:
            config = _scenario_marker_config(
                turbulence_effect or {},
                effect_id="scenario_type.turbulence",
            )
            intensity = _bounded_profile_number(
                config.get("intensity", 1.0),
                path="scenario_type.turbulence.config.intensity",
                lower=0.0,
                upper=6.0,
            )
            peak_mps = round(DEFAULT_TURBULENCE_PEAK_MPS * intensity, 12)
            direction_deg = _seed_bearing_deg(request.get("execution_identity", {}))
            period_s = DEFAULT_TURBULENCE_PERIOD_S
        mean_mps = round(peak_mps / 2.0, 12)
        time_for_rise_s = round(min(1.0, period_s), 12)
        gust_profile = {
            "peak_magnitude_mps": peak_mps,
            "mean_magnitude_mps": mean_mps,
            "direction_deg_clockwise_from_north": direction_deg,
            "period_s": period_s,
            "time_for_rise_s": time_for_rise_s,
            "mean_linear_velocity_mps": _wind_vector_from_bearing(mean_mps, direction_deg),
            "horizontal_magnitude_sine_amplitude_percent": 1.0,
            "range_mps": [0.0, peak_mps],
            "effect_ids": sorted({"wind_gusts", "scenario_type.turbulence"} & set(by_id)),
        }
        profile["wind_gust"] = _compose_collinear_steady_wind_and_gust(
            request,
            gust_profile,
        )

    payload_effect = by_id.get("battery.mass_payload_kg")
    payload_marker = by_id.get("scenario_type.payload_changed")
    if payload_effect is not None or payload_marker is not None:
        if payload_effect is not None:
            mass_kg = _bounded_profile_number(
                payload_effect.get("requested_value"),
                path="battery.mass_payload_kg",
                lower=0.0,
                upper=20.0,
            )
        else:
            config = _scenario_marker_config(
                payload_marker or {},
                effect_id="scenario_type.payload_changed",
            )
            mass_kg = _bounded_profile_number(
                config.get("mass_payload_kg", DEFAULT_PAYLOAD_MASS_KG),
                path="scenario_type.payload_changed.config.mass_payload_kg",
                lower=0.0,
                upper=20.0,
            )
        dimensions_m = {"x": 0.2, "y": 0.2, "z": 0.1}
        profile["payload"] = {
            "mass_kg": mass_kg,
            "center_m": {"x": 0.0, "y": 0.0, "z": 0.0},
            "dimensions_m": dimensions_m,
            "inertia_increment_kg_m2": {
                "ixx": round(
                    mass_kg * (dimensions_m["y"] ** 2 + dimensions_m["z"] ** 2) / 12.0,
                    15,
                ),
                "iyy": round(
                    mass_kg * (dimensions_m["x"] ** 2 + dimensions_m["z"] ** 2) / 12.0,
                    15,
                ),
                "izz": round(
                    mass_kg * (dimensions_m["x"] ** 2 + dimensions_m["y"] ** 2) / 12.0,
                    15,
                ),
            },
            "assumption": "centered_uniform_cuboid",
            "effect_ids": sorted(
                {"battery.mass_payload_kg", "scenario_type.payload_changed"} & set(by_id)
            ),
        }

    actuator_effect = by_id.get("scenario_type.actuator_delay")
    if actuator_effect is not None:
        config = _scenario_marker_config(
            actuator_effect,
            effect_id="scenario_type.actuator_delay",
        )
        delay_ms = _bounded_profile_number(
            config.get("delay_ms", DEFAULT_ACTUATOR_DELAY_MS),
            path="scenario_type.actuator_delay.config.delay_ms",
            lower=0.0,
            upper=1000.0,
        )
        time_constant_s = round(delay_ms / 1000.0, 12)
        profile["actuator_dynamics"] = {
            "requested_delay_ms": delay_ms,
            "model": "first_order_motor_response",
            "time_constant_up_s": time_constant_s,
            "time_constant_down_s": time_constant_s,
            "motor_numbers": [0, 1, 2, 3],
            "effect_ids": ["scenario_type.actuator_delay"],
        }

    actuator_failure_effect = by_id.get("scenario_type.actuator_failure")
    if actuator_failure_effect is not None:
        config = _scenario_marker_config(
            actuator_failure_effect,
            effect_id="scenario_type.actuator_failure",
        )
        motor_number_raw = config.get(
            "motor_number",
            _seed_motor_number(request.get("execution_identity", {})),
        )
        if (
            isinstance(motor_number_raw, bool)
            or not isinstance(motor_number_raw, int)
            or not 0 <= motor_number_raw <= 3
        ):
            raise ScenarioEffectContractError(
                "scenario_type.actuator_failure.config.motor_number must be an integer in [0, 3]"
            )
        failure_mode = config.get("failure_mode", DEFAULT_ACTUATOR_FAILURE_MODE)
        if failure_mode != DEFAULT_ACTUATOR_FAILURE_MODE:
            raise ScenarioEffectContractError(
                "scenario_type.actuator_failure.config.failure_mode must be "
                f"{DEFAULT_ACTUATOR_FAILURE_MODE!r}"
            )
        profile["actuator_failure"] = {
            "failure_mode": failure_mode,
            "failure_start": "launch",
            "target_motor_number": motor_number_raw,
            "target_joint_name": f"rotor_{motor_number_raw}_joint",
            "max_rot_velocity_rad_s": 0.0,
            "joint_state_topic": ACTUATOR_FAILURE_JOINT_STATE_TOPIC,
            "joint_state_update_rate_hz": 20.0,
            "max_failed_motor_abs_velocity_rad_s": (MAX_FAILED_MOTOR_ABS_VELOCITY_RAD_S),
            "min_healthy_motor_abs_velocity_rad_s": (MIN_HEALTHY_MOTOR_ABS_VELOCITY_RAD_S),
            "effect_ids": ["scenario_type.actuator_failure"],
        }
    return profile


def compile_bundled_sdf_profile(request: dict[str, Any]) -> dict[str, Any] | None:
    """Compile Trial-local x500 SDF perturbations without mutating pinned PX4."""

    validate_scenario_effect_request(request)
    return _compile_bundled_sdf_profile_unchecked(request)


def _compile_bundled_runtime_profile_unchecked(
    request: dict[str, Any],
) -> dict[str, Any] | None:
    effects = [
        effect
        for effect in request.get("effects", [])
        if effect.get("effect_id")
        in (BUNDLED_RUNTIME_EFFECT_IDS | BUNDLED_WIND_ACTIVATION_EFFECT_IDS)
    ]
    if not effects:
        return None

    by_id = {str(effect["effect_id"]): effect for effect in effects}
    profile: dict[str, Any] = {
        "requested_effect_ids": sorted(by_id),
        "execution_identity_sha256": _value_hash(request.get("execution_identity", {})),
    }

    requested_wind_ids = sorted(BUNDLED_WIND_ACTIVATION_EFFECT_IDS & set(by_id))
    if requested_wind_ids:
        compiled_wind = _compile_bundled_steady_wind_unchecked(request)
        compiled_sdf = _compile_bundled_sdf_profile_unchecked(request)
        gust_profile = compiled_sdf.get("wind_gust") if compiled_sdf is not None else None
        vector = (
            gust_profile["mean_linear_velocity_mps"]
            if isinstance(gust_profile, dict)
            else compiled_wind["linear_velocity_mps"]
            if compiled_wind is not None
            else None
        )
        if vector is None:
            raise ScenarioEffectContractError(
                "wind activation effects did not compile a target Gazebo wind vector"
            )
        profile["wind_activation"] = {
            "linear_velocity_mps": vector,
            "activation_phase": "after_stable_hover_before_track_entry",
            "topic_suffix": "/wind",
            "readback_service_suffix": "/wind_info",
            "effect_ids": requested_wind_ids,
        }

    gps_ids = {
        "sensor_degradation.dropout_rate",
        "scenario_config.dropout_rate",
        "scenario_type.gps_dropout",
    }
    requested_gps_ids = sorted(gps_ids & set(by_id))
    if requested_gps_ids:
        rates: list[float] = []
        for effect_id in requested_gps_ids:
            raw = by_id[effect_id].get("requested_value")
            if effect_id == "scenario_type.gps_dropout":
                raw = (
                    raw.get("dropout_rate", DEFAULT_GPS_DROPOUT_RATE)
                    if isinstance(raw, dict)
                    else raw
                )
            rates.append(
                _bounded_profile_number(
                    raw,
                    path=effect_id,
                    lower=0.0,
                    upper=1.0,
                )
            )
        reference = rates[0]
        if any(not math.isclose(rate, reference, rel_tol=0.0, abs_tol=1e-12) for rate in rates[1:]):
            raise ScenarioEffectContractError(
                "GPS dropout sources request conflicting dropout rates"
            )
        profile["gps_dropout"] = {
            "requested_rate": reference,
            "tick_period_s": 1.0,
            "schedule_algorithm": "sha256-ranked-fixed-duty-v1",
            "parameter_name": "SIM_GPS_USED",
            "dropout_value": 0,
            "availability_source": "mavsdk.telemetry.gps_info",
            "effect_ids": requested_gps_ids,
        }

    battery_ids = {
        "battery.initial_percent",
        "battery.voltage_sag",
        "scenario_type.battery_degraded",
    }
    requested_battery_ids = sorted(battery_ids & set(by_id))
    if requested_battery_ids:
        initial_percent = DEFAULT_BATTERY_INITIAL_PERCENT
        voltage_sag = False
        initial_effect = by_id.get("battery.initial_percent")
        if initial_effect is not None:
            initial_percent = _bounded_profile_number(
                initial_effect.get("requested_value"),
                path="battery.initial_percent",
                lower=0.0,
                upper=100.0,
            )
        sag_effect = by_id.get("battery.voltage_sag")
        if sag_effect is not None:
            if sag_effect.get("requested_value") is not True:
                raise ScenarioEffectContractError("battery.voltage_sag must request true")
            voltage_sag = True
        marker = by_id.get("scenario_type.battery_degraded")
        if marker is not None:
            marker_value = marker.get("requested_value")
            marker_config = marker_value.get("config", {}) if isinstance(marker_value, dict) else {}
            if not isinstance(marker_config, dict):
                raise ScenarioEffectContractError(
                    "scenario_type.battery_degraded config must be an object"
                )
            initial_percent = _bounded_profile_number(
                marker_config.get("initial_percent", DEFAULT_BATTERY_INITIAL_PERCENT),
                path="scenario_type.battery_degraded.config.initial_percent",
                lower=0.0,
                upper=100.0,
            )
            raw_sag = marker_config.get("voltage_sag", True)
            if not isinstance(raw_sag, bool):
                raise ScenarioEffectContractError(
                    "scenario_type.battery_degraded.config.voltage_sag must be boolean"
                )
            voltage_sag = raw_sag
        profile["battery"] = {
            "target_track_start_percent": initial_percent,
            "voltage_sag": voltage_sag,
            "sag_drain_seconds": DEFAULT_BATTERY_SAG_DRAIN_SECONDS,
            "no_sag_hold_drain_seconds": 86400.0,
            "parameter_names": ["SIM_BAT_DRAIN", "SIM_BAT_MIN_PCT"],
            "effect_ids": requested_battery_ids,
        }
    return profile


def compile_bundled_runtime_profile(request: dict[str, Any]) -> dict[str, Any] | None:
    """Compile flight-timed PX4 effects for the bundled offboard executor."""

    validate_scenario_effect_request(request)
    return _compile_bundled_runtime_profile_unchecked(request)


def compile_bundled_gps_dropout_schedule(
    *,
    requested_rate: float,
    tick_count: int,
    execution_identity_sha256: str,
) -> list[bool]:
    """Select an exact, seed-bound dropout duty set without a platform PRNG."""

    if not math.isfinite(requested_rate) or not 0.0 <= requested_rate <= 1.0:
        raise ScenarioEffectContractError("requested_rate must be finite and in [0, 1]")
    if not 1 <= tick_count <= 3600:
        raise ScenarioEffectContractError("tick_count must be in [1, 3600]")
    if not _SHA256.fullmatch(execution_identity_sha256):
        raise ScenarioEffectContractError("execution_identity_sha256 must be a lowercase SHA-256")
    off_count = int(math.floor(requested_rate * tick_count + 0.5))
    if requested_rate > 0.0 and off_count == 0:
        off_count = 1
    if requested_rate < 1.0 and off_count == tick_count and tick_count > 1:
        off_count -= 1
    ranked = sorted(
        range(tick_count),
        key=lambda index: hashlib.sha256(
            f"{execution_identity_sha256}:{index}".encode("ascii")
        ).digest(),
    )
    off_ticks = set(ranked[:off_count])
    return [index in off_ticks for index in range(tick_count)]


def build_scenario_effect_request(
    *,
    execution_identity: dict[str, Any],
    scenario_type: str,
    scenario_config: dict[str, Any] | None,
    job_config: dict[str, Any],
    advanced_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Normalize all physical scenario requests into one launcher contract."""

    if not isinstance(execution_identity, dict):
        raise ScenarioEffectContractError("execution_identity must be an object")
    _validate_json_tree(execution_identity, path="execution_identity")
    if not isinstance(scenario_type, str) or not scenario_type.strip() or len(scenario_type) > 128:
        raise ScenarioEffectContractError("scenario_type must be a non-empty bounded string")
    if scenario_config is not None and not isinstance(scenario_config, dict):
        raise ScenarioEffectContractError("scenario_config must be an object")
    if not isinstance(job_config, dict):
        raise ScenarioEffectContractError("job_config must be an object")
    if advanced_config is not None and not isinstance(advanced_config, dict):
        raise ScenarioEffectContractError("advanced_scenario_config must be an object")
    scenario = dict(scenario_config or {})
    advanced = dict(advanced_config or {})
    effects: list[dict[str, Any]] = []

    def add(effect_id: str, source: str, value: Any) -> None:
        if any(item["effect_id"] == effect_id for item in effects):
            return
        bundled = (
            effect_id == "obstacles"
            or effect_id in BUNDLED_STEADY_WIND_EFFECT_IDS
            or effect_id in BUNDLED_SDF_PROFILE_EFFECT_IDS
            or effect_id in BUNDLED_RUNTIME_EFFECT_IDS
        )
        capability_status = "available" if bundled else "requires_runtime_extension"
        effects.append(
            {
                "effect_id": effect_id,
                "source": source,
                "requested_value": value,
                "launcher_input": {
                    "request_path_env": "PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH",
                    "scenario_config_path_env": "PX4_TRIAL_SCENARIO_CONFIG_PATH",
                },
                "mechanism": _mechanism_for(effect_id),
                "capability": {
                    "status": capability_status,
                    "reason": _available_reason(effect_id)
                    if bundled
                    else _unsupported_reason(effect_id),
                },
            }
        )

    wind_raw = job_config.get("wind", {})
    if not isinstance(wind_raw, dict):
        raise ScenarioEffectContractError("job_config.wind must be an object")
    wind = {
        direction: _finite_number(
            wind_raw,
            direction,
            path="job_config.wind",
            default=0.0,
        )
        for direction in ("north", "east", "south", "west")
    }
    if any(abs(value) > 1e-12 for value in wind.values()):
        add("job_config.wind", "job_config.wind", wind)

    sensor_noise = job_config.get("sensor_noise_level", "medium")
    if not isinstance(sensor_noise, str):
        raise ScenarioEffectContractError("job_config.sensor_noise_level must be a string")
    if sensor_noise != "medium":
        add(
            "job_config.sensor_noise_level",
            "job_config.sensor_noise_level",
            sensor_noise,
        )

    if "wind_mps" in scenario:
        wind_mps = _finite_number(
            scenario,
            "wind_mps",
            path="scenario_config",
            default=0.0,
        )
        if wind_mps < 0.0:
            raise ScenarioEffectContractError(
                "scenario_config.wind_mps must be finite and non-negative"
            )
        if wind_mps > MAX_BUNDLED_STEADY_WIND_MPS:
            raise ScenarioEffectContractError(
                f"scenario_config.wind_mps must not exceed {MAX_BUNDLED_STEADY_WIND_MPS:g} m/s"
            )
        if wind_mps > 0.0:
            add("scenario_config.wind_mps", "scenario_config.wind_mps", wind_mps)

    if "dropout_rate" in scenario:
        dropout = _finite_number(
            scenario,
            "dropout_rate",
            path="scenario_config",
            default=0.0,
        )
        if not 0.0 <= dropout <= 1.0:
            raise ScenarioEffectContractError("scenario_config.dropout_rate must be in [0, 1]")
        if dropout > 0.0:
            add(
                "scenario_config.dropout_rate",
                "scenario_config.dropout_rate",
                dropout,
            )

    wind_gusts = advanced.get("wind_gusts", {})
    if not isinstance(wind_gusts, dict):
        raise ScenarioEffectContractError("advanced_scenario_config.wind_gusts must be an object")
    wind_enabled = wind_gusts.get("enabled", False)
    if not isinstance(wind_enabled, bool):
        raise ScenarioEffectContractError(
            "advanced_scenario_config.wind_gusts.enabled must be boolean"
        )
    normalized_gust = {
        "enabled": wind_enabled,
        "magnitude_mps": _finite_number(
            wind_gusts,
            "magnitude_mps",
            path="advanced_scenario_config.wind_gusts",
            default=0.0,
        ),
        "direction_deg": _finite_number(
            wind_gusts,
            "direction_deg",
            path="advanced_scenario_config.wind_gusts",
            default=0.0,
        ),
        "period_s": _finite_number(
            wind_gusts,
            "period_s",
            path="advanced_scenario_config.wind_gusts",
            default=10.0,
        ),
    }
    if not 0.0 <= normalized_gust["magnitude_mps"] <= 30.0:
        raise ScenarioEffectContractError(
            "advanced_scenario_config.wind_gusts.magnitude_mps must be in [0, 30]"
        )
    if not 0.0 <= normalized_gust["direction_deg"] < 360.0:
        raise ScenarioEffectContractError(
            "advanced_scenario_config.wind_gusts.direction_deg must be in [0, 360)"
        )
    if not 0.0 < normalized_gust["period_s"] <= 300.0:
        raise ScenarioEffectContractError(
            "advanced_scenario_config.wind_gusts.period_s must be in (0, 300]"
        )
    if wind_enabled:
        add("wind_gusts", "advanced_scenario_config.wind_gusts", normalized_gust)

    obstacles = advanced.get("obstacles", [])
    if not isinstance(obstacles, list):
        raise ScenarioEffectContractError("advanced_scenario_config.obstacles must be an array")
    if len(obstacles) > 512:
        raise ScenarioEffectContractError(
            "advanced_scenario_config.obstacles exceeds the 512-item limit"
        )
    normalized_obstacles: list[dict[str, Any]] = []
    for index, obstacle in enumerate(obstacles):
        if not isinstance(obstacle, dict):
            raise ScenarioEffectContractError(
                f"advanced_scenario_config.obstacles[{index}] must be an object"
            )
        obstacle_type = obstacle.get("type")
        if obstacle_type not in {"cylinder", "box"}:
            raise ScenarioEffectContractError(
                f"advanced_scenario_config.obstacles[{index}].type must be cylinder or box"
            )
        normalized: dict[str, Any] = {"type": obstacle_type}
        for coordinate in ("x", "y", "z"):
            normalized[coordinate] = _finite_number(
                obstacle,
                coordinate,
                path=f"advanced_scenario_config.obstacles[{index}]",
                default=float("nan"),
            )
        required = (
            ("radius", "height") if obstacle_type == "cylinder" else ("size_x", "size_y", "size_z")
        )
        forbidden = (
            ("size_x", "size_y", "size_z") if obstacle_type == "cylinder" else ("radius", "height")
        )
        for dimension in required:
            if dimension not in obstacle or obstacle[dimension] is None:
                raise ScenarioEffectContractError(
                    f"advanced_scenario_config.obstacles[{index}].{dimension} "
                    "must be finite and greater than zero"
                )
            value = _finite_number(
                obstacle,
                dimension,
                path=f"advanced_scenario_config.obstacles[{index}]",
                default=float("nan"),
            )
            if value <= 0.0:
                raise ScenarioEffectContractError(
                    f"advanced_scenario_config.obstacles[{index}].{dimension} "
                    "must be finite and greater than zero"
                )
            normalized[dimension] = value
        if any(obstacle.get(name) is not None for name in forbidden):
            raise ScenarioEffectContractError(
                f"advanced_scenario_config.obstacles[{index}] contains dimensions "
                "for the wrong shape"
            )
        normalized_obstacles.append(normalized)
    if normalized_obstacles:
        add("obstacles", "advanced_scenario_config.obstacles", normalized_obstacles)

    sensor = advanced.get("sensor_degradation", {})
    if not isinstance(sensor, dict):
        raise ScenarioEffectContractError(
            "advanced_scenario_config.sensor_degradation must be an object"
        )
    sensor_defaults = {
        "gps_noise_m": 0.0,
        "baro_noise_m": 0.0,
        "imu_noise_scale": 1.0,
        "dropout_rate": 0.0,
    }
    sensor_limits = {
        "gps_noise_m": (0.0, 100.0),
        "baro_noise_m": (0.0, 100.0),
        "imu_noise_scale": (0.0, 10.0),
        "dropout_rate": (0.0, 1.0),
    }
    for name, default in sensor_defaults.items():
        value = _finite_number(
            sensor,
            name,
            path="advanced_scenario_config.sensor_degradation",
            default=default,
        )
        lower, upper = sensor_limits[name]
        if not lower <= value <= upper:
            raise ScenarioEffectContractError(
                f"advanced_scenario_config.sensor_degradation.{name} must be in "
                f"[{lower:g}, {upper:g}]"
            )
        if not math.isclose(value, default, rel_tol=0.0, abs_tol=1e-12):
            add(
                f"sensor_degradation.{name}",
                f"advanced_scenario_config.sensor_degradation.{name}",
                value,
            )

    battery = advanced.get("battery", {})
    if not isinstance(battery, dict):
        raise ScenarioEffectContractError("advanced_scenario_config.battery must be an object")
    initial_percent = _finite_number(
        battery,
        "initial_percent",
        path="advanced_scenario_config.battery",
        default=100.0,
    )
    if not 0.0 <= initial_percent <= 100.0:
        raise ScenarioEffectContractError(
            "advanced_scenario_config.battery.initial_percent must be in [0, 100]"
        )
    voltage_sag = battery.get("voltage_sag", False)
    if not isinstance(voltage_sag, bool):
        raise ScenarioEffectContractError(
            "advanced_scenario_config.battery.voltage_sag must be boolean"
        )
    payload_raw = battery.get("mass_payload_kg")
    payload_mass = (
        0.0
        if payload_raw is None
        else _finite_number(
            battery,
            "mass_payload_kg",
            path="advanced_scenario_config.battery",
            default=0.0,
        )
    )
    if not 0.0 <= payload_mass <= 20.0:
        raise ScenarioEffectContractError(
            "advanced_scenario_config.battery.mass_payload_kg must be in [0, 20]"
        )
    if not math.isclose(initial_percent, 100.0, rel_tol=0.0, abs_tol=1e-12):
        add(
            "battery.initial_percent",
            "advanced_scenario_config.battery.initial_percent",
            initial_percent,
        )
    if voltage_sag:
        add(
            "battery.voltage_sag",
            "advanced_scenario_config.battery.voltage_sag",
            True,
        )
    if payload_mass > 0.0:
        add(
            "battery.mass_payload_kg",
            "advanced_scenario_config.battery.mass_payload_kg",
            payload_mass,
        )

    concrete_by_scenario = {
        "noise_perturbed": {
            "job_config.sensor_noise_level",
            "sensor_degradation.gps_noise_m",
            "sensor_degradation.baro_noise_m",
            "sensor_degradation.imu_noise_scale",
        },
        "wind_perturbed": {"job_config.wind", "scenario_config.wind_mps", "wind_gusts"},
        "turbulence": {"wind_gusts"},
        "gps_dropout": {
            "scenario_config.dropout_rate",
            "sensor_degradation.dropout_rate",
        },
        "payload_changed": {"battery.mass_payload_kg"},
        "battery_degraded": {"battery.initial_percent", "battery.voltage_sag"},
    }
    requested_ids = {item["effect_id"] for item in effects}
    # A combined scenario must represent at least two independently applied
    # physical effect families.  The API's default combined holdout does not
    # carry explicit effect values, so compile deterministic launcher-supported
    # defaults instead of emitting the non-physical combined label that a real
    # PX4/Gazebo runner must reject.  When the caller supplied one family, keep
    # it unchanged and add only the missing default family.
    if scenario_type == "combined_perturbed":
        physical_families = {
            str(item["mechanism"])
            for item in effects
            if item["capability"]["status"] == "available"
        }
        if len(physical_families) < 2 and "gazebo_wind_effects" not in physical_families:
            add(
                "scenario_type.wind_perturbed",
                "scenario_type.combined_perturbed.default_wind",
                {"scenario_type": "wind_perturbed", "config": {}},
            )
            physical_families.add("gazebo_wind_effects")
        if len(physical_families) < 2 and "sdformat_sensor_noise" not in physical_families:
            add(
                "scenario_type.noise_perturbed",
                "scenario_type.combined_perturbed.default_sensor_noise",
                {"scenario_type": "noise_perturbed", "config": {}},
            )
    elif scenario_type in concrete_by_scenario and not (
        concrete_by_scenario[scenario_type] & requested_ids
    ):
        default_value: Any = {"scenario_type": scenario_type, "config": scenario}
        if scenario_type == "gps_dropout" and not scenario:
            default_value = {"dropout_rate": 0.2, "source": "scenario_default"}
        add(f"scenario_type.{scenario_type}", "scenario_type", default_value)
    elif scenario_type in {"actuator_delay", "actuator_failure", "custom"}:
        add(
            f"scenario_type.{scenario_type}",
            "scenario_type",
            {"scenario_type": scenario_type, "config": scenario},
        )

    body: dict[str, Any] = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "execution_identity": dict(execution_identity),
        "scenario_type": scenario_type,
        "effects": effects,
    }
    body["request_sha256"] = _request_hash(body)
    return validate_scenario_effect_request(body)


def validate_scenario_effect_request(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ScenarioEffectContractError("scenario effect request must be an object")
    _validate_json_tree(payload, path="scenario effect request")
    if payload.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ScenarioEffectContractError("unsupported scenario effect request schema")
    digest = payload.get("request_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise ScenarioEffectContractError("scenario effect request hash is invalid")
    if digest != scenario_effect_request_sha256(payload):
        raise ScenarioEffectContractError("scenario effect request hash does not match")
    identity = payload.get("execution_identity")
    if not isinstance(identity, dict):
        raise ScenarioEffectContractError(
            "scenario effect request execution_identity must be an object"
        )
    _validate_json_tree(identity, path="scenario effect request execution_identity")
    scenario_type = payload.get("scenario_type")
    if not isinstance(scenario_type, str) or not scenario_type.strip() or len(scenario_type) > 128:
        raise ScenarioEffectContractError("scenario effect request scenario_type is invalid")
    effects = payload.get("effects")
    if not isinstance(effects, list):
        raise ScenarioEffectContractError("scenario effect request effects must be an array")
    if len(effects) > MAX_EFFECTS_PER_REQUEST:
        raise ScenarioEffectContractError(
            f"scenario effect request exceeds the {MAX_EFFECTS_PER_REQUEST}-effect limit"
        )
    seen: set[str] = set()
    for index, effect in enumerate(effects):
        if not isinstance(effect, dict):
            raise ScenarioEffectContractError(f"scenario effect {index} must be an object")
        effect_id = effect.get("effect_id")
        if (
            not isinstance(effect_id, str)
            or not effect_id.strip()
            or len(effect_id) > 256
            or effect_id in seen
        ):
            raise ScenarioEffectContractError("scenario effect ids must be non-empty and unique")
        seen.add(effect_id)
        if (
            not isinstance(effect.get("source"), str)
            or not effect["source"].strip()
            or len(effect["source"]) > 1024
        ):
            raise ScenarioEffectContractError(f"scenario effect {effect_id} source is invalid")
        if (
            not isinstance(effect.get("mechanism"), str)
            or not effect["mechanism"].strip()
            or len(effect["mechanism"]) > 256
        ):
            raise ScenarioEffectContractError(f"scenario effect {effect_id} mechanism is invalid")
        if "requested_value" not in effect:
            raise ScenarioEffectContractError(
                f"scenario effect {effect_id} requested_value is missing"
            )
        _validate_json_tree(
            effect["requested_value"],
            path=f"scenario effect {effect_id} requested_value",
        )
        launcher_input = effect.get("launcher_input")
        if not isinstance(launcher_input, dict):
            raise ScenarioEffectContractError(
                f"scenario effect {effect_id} launcher_input is invalid"
            )
        expected_launcher_input = {
            "request_path_env": "PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH",
            "scenario_config_path_env": "PX4_TRIAL_SCENARIO_CONFIG_PATH",
        }
        if any(launcher_input.get(key) != value for key, value in expected_launcher_input.items()):
            raise ScenarioEffectContractError(
                f"scenario effect {effect_id} launcher_input contract is invalid"
            )
        capability = effect.get("capability")
        if not isinstance(capability, dict):
            raise ScenarioEffectContractError(f"scenario effect {effect_id} capability is invalid")
        if capability.get("status") not in {"available", "requires_runtime_extension"}:
            raise ScenarioEffectContractError(
                f"scenario effect {effect_id} capability status is invalid"
            )
        reason = capability.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
            raise ScenarioEffectContractError(
                f"scenario effect {effect_id} capability reason is invalid"
            )
    _compile_bundled_steady_wind_unchecked(payload)
    _compile_bundled_sdf_profile_unchecked(payload)
    _compile_bundled_runtime_profile_unchecked(payload)
    return payload


def load_scenario_effect_request(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_EFFECT_CONTRACT_BYTES:
        raise ScenarioEffectContractError("scenario effect request file is missing or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScenarioEffectContractError(f"could not read scenario effect request: {exc}") from exc
    return validate_scenario_effect_request(payload)


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    temp.replace(path)


def build_scenario_effect_evidence(
    request: dict[str, Any],
    *,
    launcher: str,
    world: str,
    effects: list[dict[str, Any]],
) -> dict[str, Any]:
    validate_scenario_effect_request(request)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "request_sha256": request["request_sha256"],
        "execution_identity": dict(request["execution_identity"]),
        "launcher": launcher,
        "world": world,
        "effects": effects,
    }


def _validate_obstacle_evidence(requested: dict[str, Any], evidence: dict[str, Any]) -> None:
    if evidence.get("mechanism") != "gazebo_entity_factory":
        raise ScenarioEffectContractError("obstacle evidence must use gazebo_entity_factory")
    details = evidence.get("evidence")
    if not isinstance(details, dict):
        raise ScenarioEffectContractError("obstacle applied evidence must be an object")
    entities = details.get("created_entities")
    requested_items = requested.get("requested_value")
    if not isinstance(entities, list) or not isinstance(requested_items, list):
        raise ScenarioEffectContractError("obstacle evidence entity list is invalid")
    if len(entities) != len(requested_items):
        raise ScenarioEffectContractError(
            "obstacle evidence count does not match the requested obstacles"
        )
    indices: set[int] = set()
    for entity in entities:
        if not isinstance(entity, dict) or entity.get("response_data") is not True:
            raise ScenarioEffectContractError(
                "obstacle evidence requires a successful Gazebo Boolean response"
            )
        index = entity.get("source_index")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ScenarioEffectContractError("obstacle evidence source_index is invalid")
        indices.add(index)
        service = entity.get("service")
        if not isinstance(service, str) or not service.endswith("/create"):
            raise ScenarioEffectContractError("obstacle evidence create service is invalid")
        sdf_sha = entity.get("sdf_sha256")
        if not isinstance(sdf_sha, str) or not _SHA256.fullmatch(sdf_sha):
            raise ScenarioEffectContractError("obstacle evidence SDF hash is invalid")
    if indices != set(range(len(requested_items))):
        raise ScenarioEffectContractError(
            "obstacle evidence does not cover every requested obstacle"
        )


def _validate_extension_evidence(
    requested: dict[str, Any],
    evidence_record: dict[str, Any],
) -> None:
    """Validate fail-closed evidence emitted by an extended launcher.

    DroneDream cannot independently query every site-specific Gazebo plugin,
    but it can require a stable, request-bound proof envelope.  This permits a
    custom launcher to add real effects without weakening the bundled launcher's
    default refusal of unsupported effects.
    """

    expected_mechanism = requested["mechanism"]
    if evidence_record.get("mechanism") != expected_mechanism:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} evidence mechanism does not match the request"
        )
    details = evidence_record.get("evidence")
    if not isinstance(details, dict):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} applied evidence must be an object"
        )
    expected_value_hash = _value_hash(requested["requested_value"])
    if details.get("requested_value_sha256") != expected_value_hash:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} evidence is not bound to its requested value"
        )
    verification = details.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "verified":
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires verified launcher readback"
        )
    method = verification.get("method")
    if not isinstance(method, str) or not method.strip() or len(method) > 256:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} verification method is invalid"
        )
    observations = verification.get("observations")
    if (
        not isinstance(observations, list)
        or not observations
        or len(observations) > MAX_EVIDENCE_OBSERVATIONS
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires bounded verification observations"
        )
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} observation {index} must be an object"
            )
        source = observation.get("source")
        if not isinstance(source, str) or not source.strip() or len(source) > 1024:
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} observation {index} source is invalid"
            )
        if observation.get("kind") not in {
            "readback",
            "acknowledgement",
            "sample",
            "artifact",
        }:
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} observation {index} kind is invalid"
            )
        if "value" not in observation:
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} observation {index} value is missing"
            )
        _validate_json_tree(
            observation["value"],
            path=f"effect {requested['effect_id']} observation {index} value",
        )
        digest = observation.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} observation {index} hash is invalid"
            )
        if digest is not None and digest != _value_hash(observation["value"]):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} observation {index} hash does not match"
            )


def _validate_bundled_steady_wind_evidence(
    request: dict[str, Any],
    requested: dict[str, Any],
    evidence_record: dict[str, Any],
) -> None:
    _validate_extension_evidence(requested, evidence_record)
    details = evidence_record["evidence"]
    expected = _compile_bundled_steady_wind_unchecked(request)
    if expected is None or details.get("compiled_wind") != expected:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} compiled wind does not match the request"
        )

    observations = details["verification"]["observations"]
    readbacks = [
        item
        for item in observations
        if item.get("kind") == "readback"
        and isinstance(item.get("source"), str)
        and item["source"].endswith("/wind_info")
    ]
    runtime_profile = _compile_bundled_runtime_profile_unchecked(request)
    wind_activation = (
        runtime_profile.get("wind_activation") if isinstance(runtime_profile, dict) else None
    )
    activation_vector = (
        wind_activation.get("linear_velocity_mps")
        if isinstance(wind_activation, dict)
        else None
    )
    if not isinstance(activation_vector, dict):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} did not compile a runtime wind activation vector"
        )
    expected_readback = {
        # Preserve ``compiled_wind`` above as the exact request-bound steady
        # component, but verify the vector Gazebo actually receives.  When a
        # compatible gust is present the runtime compiler deliberately activates
        # their composed mean after stable hover.
        "linear_velocity_mps": activation_vector,
        "enable_wind": True,
    }
    if len(readbacks) != 1 or readbacks[0].get("value") != expected_readback:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires exact Gazebo wind_info readback"
        )

    runtime_sdf = [
        item
        for item in observations
        if item.get("kind") == "artifact"
        and isinstance(item.get("source"), str)
        and item["source"].endswith("/generate_world_sdf")
    ]
    if len(runtime_sdf) != 1:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires one generated-world-SDF observation"
        )
    sdf_value = runtime_sdf[0].get("value")
    vehicle_model = sdf_value.get("vehicle_model") if isinstance(sdf_value, dict) else None
    if (
        not isinstance(sdf_value, dict)
        or sdf_value.get("source_vehicle_model") != "x500_base"
        or not isinstance(vehicle_model, str)
        or not re.fullmatch(r"x500(?:_depth|_vision)?_0", vehicle_model)
        or sdf_value.get("link_name") != "base_link"
        or sdf_value.get("enable_wind") is not True
        or not isinstance(sdf_value.get("sdf_sha256"), str)
        or not _SHA256.fullmatch(sdf_value["sdf_sha256"])
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} runtime SDF does not prove "
            "an allowed PX4 x500-family runtime instance/base_link WindMode"
        )


def _validate_bundled_sdf_profile_evidence(
    request: dict[str, Any],
    requested: dict[str, Any],
    evidence_record: dict[str, Any],
) -> None:
    _validate_extension_evidence(requested, evidence_record)
    details = evidence_record["evidence"]
    expected = _compile_bundled_sdf_profile_unchecked(request)
    if expected is None or details.get("compiled_sdf_profile") != expected:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} compiled SDF profile does not match the request"
        )
    observations = details["verification"]["observations"]
    runtime_sdf = [
        item
        for item in observations
        if item.get("kind") == "artifact"
        and isinstance(item.get("source"), str)
        and item["source"].endswith("/generate_world_sdf")
    ]
    if len(runtime_sdf) != 1:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires one generated-world-SDF observation"
        )
    sdf_value = runtime_sdf[0].get("value")
    vehicle_model = sdf_value.get("vehicle_model") if isinstance(sdf_value, dict) else None
    verified_sections = (
        sdf_value.get("verified_profile_sections") if isinstance(sdf_value, dict) else None
    )
    effect_sections = {
        section
        for section in (
            "wind_gust",
            "sensor_noise",
            "payload",
            "actuator_dynamics",
            "actuator_failure",
        )
        if section in expected and requested["effect_id"] in expected[section].get("effect_ids", [])
    }
    if (
        not isinstance(sdf_value, dict)
        or sdf_value.get("source_vehicle_model") != "x500_base"
        or vehicle_model != "x500_0"
        or not isinstance(sdf_value.get("sdf_sha256"), str)
        or not _SHA256.fullmatch(sdf_value["sdf_sha256"])
        or not isinstance(verified_sections, list)
        or not effect_sections.issubset(set(verified_sections))
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} runtime SDF does not prove its exact "
            "x500 perturbation profile"
        )
    if requested["effect_id"] == "scenario_type.actuator_failure":
        expected_failure = expected.get("actuator_failure")
        joint_readbacks = [
            item
            for item in observations
            if item.get("kind") == "readback"
            and item.get("source")
            == (
                expected_failure.get("joint_state_topic")
                if isinstance(expected_failure, dict)
                else None
            )
        ]
        if len(joint_readbacks) != 1 or not isinstance(expected_failure, dict):
            raise ScenarioEffectContractError(
                "actuator failure evidence requires one exact Gazebo joint-state readback"
            )
        joint_value = joint_readbacks[0].get("value")
        healthy_maxima = (
            joint_value.get("healthy_joint_max_abs_velocity_rad_s")
            if isinstance(joint_value, dict)
            else None
        )
        target_max = (
            joint_value.get("target_max_abs_velocity_rad_s")
            if isinstance(joint_value, dict)
            else None
        )
        if (
            not isinstance(joint_value, dict)
            or joint_value.get("target_motor_number") != expected_failure["target_motor_number"]
            or joint_value.get("target_joint_name") != expected_failure["target_joint_name"]
            or not isinstance(target_max, (int, float))
            or isinstance(target_max, bool)
            or not math.isfinite(float(target_max))
            or float(target_max) > float(expected_failure["max_failed_motor_abs_velocity_rad_s"])
            or not isinstance(healthy_maxima, dict)
            or set(healthy_maxima)
            != {
                f"rotor_{number}_joint"
                for number in range(4)
                if number != expected_failure["target_motor_number"]
            }
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) >= float(expected_failure["min_healthy_motor_abs_velocity_rad_s"])
                for value in healthy_maxima.values()
            )
            or joint_value.get("hard_stop_verified") is not True
            or joint_value.get("healthy_motion_verified") is not True
        ):
            raise ScenarioEffectContractError(
                "actuator failure joint-state readback does not prove one stopped "
                "target rotor and three moving healthy rotors"
            )


def _validate_bundled_runtime_evidence(
    request: dict[str, Any],
    requested: dict[str, Any],
    evidence_record: dict[str, Any],
) -> None:
    _validate_extension_evidence(requested, evidence_record)
    details = evidence_record["evidence"]
    expected = _compile_bundled_runtime_profile_unchecked(request)
    if expected is None or details.get("compiled_runtime_profile") != expected:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} compiled runtime profile does not match the request"
        )
    observations = details["verification"]["observations"]
    if len(observations) != 1:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires exactly one runtime observation"
        )
    observation = observations[0]
    value = observation.get("value")
    if not isinstance(value, dict):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} runtime observation must be an object"
        )
    gps_ids = set(expected.get("gps_dropout", {}).get("effect_ids", []))
    if requested["effect_id"] in gps_ids:
        if (
            observation.get("kind") != "readback"
            or observation.get("source") != "mavsdk.param+telemetry/gps_info"
            or value.get("schedule_algorithm") != "sha256-ranked-fixed-duty-v1"
            or value.get("reset_verified") is not True
        ):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} requires verified GPS availability/reset evidence"
            )
        schedule = value.get("schedule")
        tick_count = value.get("tick_count")
        transitions = value.get("transitions")
        control = value.get("control_parameter")
        control_before = control.get("before") if isinstance(control, dict) else None
        control_restore = control.get("restore") if isinstance(control, dict) else None
        if (
            not isinstance(schedule, list)
            or not schedule
            or any(not isinstance(item, bool) for item in schedule)
            or not isinstance(tick_count, int)
            or isinstance(tick_count, bool)
            or tick_count != len(schedule)
            or not isinstance(transitions, list)
            or not transitions
            or any(
                not isinstance(item, dict)
                or item.get("physical_effect_verified") is not True
                or not isinstance(item.get("verification"), dict)
                or item["verification"].get("physical_effect_verified") is not True
                for item in transitions
            )
            or not any(item.get("final_reset") is True for item in transitions)
            or not isinstance(control, dict)
            or control.get("parameter_name") != "SIM_GPS_USED"
            or control.get("dropout_value") != 0
            or not isinstance(control_before, int)
            or isinstance(control_before, bool)
            or control_before < 4
            or control.get("recovery_value") != control_before
            or not isinstance(control_restore, dict)
            or control_restore.get("physical_effect_verified") is not True
            or control.get("restore_verified") is not True
        ):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} GPS schedule/telemetry evidence is invalid"
            )
        for transition in transitions:
            verification = transition["verification"]
            parameter = verification.get("parameter")
            samples = verification.get("telemetry_samples")
            failure_type = transition.get("failure_type")
            expected_satellites = 0 if failure_type == "off" else control_before
            if (
                failure_type not in {"off", "ok"}
                or verification.get("parameter_name") != "SIM_GPS_USED"
                or not isinstance(parameter, dict)
                or parameter.get("requested") != expected_satellites
                or parameter.get("applied") != expected_satellites
                or not isinstance(samples, list)
                or not samples
                or not all(isinstance(sample, dict) for sample in samples)
            ):
                raise ScenarioEffectContractError(
                    f"effect {requested['effect_id']} GPS transition evidence is invalid"
                )
            final_sample = samples[-1]
            num_satellites = final_sample.get("num_satellites")
            fix_type = final_sample.get("fix_type")
            if (
                not isinstance(num_satellites, int)
                or isinstance(num_satellites, bool)
                or not isinstance(fix_type, int)
                or isinstance(fix_type, bool)
                or (failure_type == "off" and not (num_satellites < 4 and fix_type <= 1))
                or (failure_type == "ok" and not (num_satellites >= 4 and fix_type >= 2))
            ):
                raise ScenarioEffectContractError(
                    f"effect {requested['effect_id']} GPS telemetry state is invalid"
                )
        gps_profile = expected["gps_dropout"]
        expected_schedule = compile_bundled_gps_dropout_schedule(
            requested_rate=float(gps_profile["requested_rate"]),
            tick_count=tick_count,
            execution_identity_sha256=expected["execution_identity_sha256"],
        )
        off_tick_count = sum(schedule)
        realized_rate = value.get("realized_rate")
        if (
            schedule != expected_schedule
            or value.get("off_tick_count") != off_tick_count
            or not isinstance(realized_rate, (int, float))
            or isinstance(realized_rate, bool)
            or not math.isclose(
                float(realized_rate),
                off_tick_count / tick_count,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} GPS duty schedule is not request-bound"
            )
        return

    battery_ids = set(expected.get("battery", {}).get("effect_ids", []))
    if requested["effect_id"] not in battery_ids:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} is absent from its runtime profile"
        )
    if (
        observation.get("kind") != "readback"
        or observation.get("source") != "mavsdk.param+telemetry/battery"
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} requires battery parameter/telemetry readback"
        )
    battery_profile = expected["battery"]
    start_sample = value.get("track_start_sample")
    end_sample = value.get("track_end_sample")
    tolerance = value.get("track_start_tolerance_percent")
    pretrack_drain_seconds = value.get("pretrack_drain_seconds")
    if (
        not isinstance(start_sample, dict)
        or not isinstance(end_sample, dict)
        or not isinstance(tolerance, (int, float))
        or isinstance(tolerance, bool)
        or not math.isfinite(float(tolerance))
        or not isinstance(pretrack_drain_seconds, (int, float))
        or isinstance(pretrack_drain_seconds, bool)
        or not math.isfinite(float(pretrack_drain_seconds))
        or not 1.0 <= float(pretrack_drain_seconds) <= 86400.0
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} battery samples are incomplete"
        )
    expected_tolerance = max(
        5.0,
        100.0 * 0.1 / max(1.0, float(pretrack_drain_seconds)) + 2.0,
    )
    if not math.isclose(
        float(tolerance),
        expected_tolerance,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} battery tolerance is not bound "
            "to the pre-track drain profile"
        )
    try:
        start_percent = float(start_sample["remaining_percent"])
        end_percent = float(end_sample["remaining_percent"])
        target_percent = float(battery_profile["target_track_start_percent"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} battery percentages are invalid"
        ) from exc
    if not all(math.isfinite(item) for item in (start_percent, end_percent, target_percent)) or abs(
        start_percent - target_percent
    ) > float(tolerance):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} did not verify its track-start battery state"
        )
    track_parameters = value.get("track_parameters")
    expected_track_values = (
        {
            "SIM_BAT_MIN_PCT": 0.0,
            "SIM_BAT_DRAIN": float(battery_profile["sag_drain_seconds"]),
        }
        if battery_profile["voltage_sag"]
        else {
            "SIM_BAT_MIN_PCT": target_percent,
            "SIM_BAT_DRAIN": float(battery_profile["no_sag_hold_drain_seconds"]),
        }
    )
    if not isinstance(track_parameters, dict) or set(track_parameters) != set(
        expected_track_values
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} battery parameter readback is incomplete"
        )
    for name, expected_value in expected_track_values.items():
        record = track_parameters[name]
        if (
            not isinstance(record, dict)
            or not math.isclose(
                float(record.get("requested", math.nan)),
                expected_value,
                rel_tol=1e-6,
                abs_tol=1e-6,
            )
            or not math.isclose(
                float(record.get("applied", math.nan)),
                expected_value,
                rel_tol=1e-6,
                abs_tol=1e-6,
            )
        ):
            raise ScenarioEffectContractError(
                f"effect {requested['effect_id']} battery parameter {name} did not read back"
            )
    if battery_profile["voltage_sag"] and (
        value.get("observed_nonincrease") is not True or end_percent > start_percent + 0.5
    ):
        raise ScenarioEffectContractError(
            f"effect {requested['effect_id']} battery telemetry did not verify voltage sag"
        )


def validate_scenario_effect_evidence(request: dict[str, Any], payload: object) -> dict[str, Any]:
    validate_scenario_effect_request(request)
    if not isinstance(payload, dict):
        raise ScenarioEffectContractError("scenario effect evidence must be an object")
    _validate_json_tree(payload, path="scenario effect evidence")
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ScenarioEffectContractError("unsupported scenario effect evidence schema")
    if payload.get("request_sha256") != request["request_sha256"]:
        raise ScenarioEffectContractError(
            "scenario effect evidence does not match the request hash"
        )
    if payload.get("execution_identity") != request["execution_identity"]:
        raise ScenarioEffectContractError(
            "scenario effect evidence execution identity does not match"
        )
    for field in ("launcher", "world"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 1024:
            raise ScenarioEffectContractError(f"scenario effect evidence {field} is invalid")
    effects = payload.get("effects")
    if not isinstance(effects, list):
        raise ScenarioEffectContractError("scenario effect evidence effects must be an array")
    if len(effects) > MAX_EFFECTS_PER_REQUEST:
        raise ScenarioEffectContractError(
            f"scenario effect evidence exceeds the {MAX_EFFECTS_PER_REQUEST}-effect limit"
        )
    requested_by_id = {item["effect_id"]: item for item in request["effects"]}
    observed: dict[str, dict[str, Any]] = {}
    for index, effect in enumerate(effects):
        if not isinstance(effect, dict):
            raise ScenarioEffectContractError(f"effect evidence {index} must be an object")
        effect_id = effect.get("effect_id")
        if not isinstance(effect_id, str) or effect_id not in requested_by_id:
            raise ScenarioEffectContractError(
                f"effect evidence {index} references an unrequested effect"
            )
        if effect_id in observed:
            raise ScenarioEffectContractError("effect evidence ids must be unique")
        status = effect.get("status")
        if status not in {"applied", "unsupported", "skipped", "failed"}:
            raise ScenarioEffectContractError(f"effect evidence {effect_id} has an invalid status")
        capability = effect.get("capability")
        if not isinstance(capability, dict) or capability.get("status") not in {
            "available",
            "unsupported",
        }:
            raise ScenarioEffectContractError(f"effect evidence {effect_id} capability is invalid")
        capability_reason = capability.get("reason")
        if (
            not isinstance(capability_reason, str)
            or not capability_reason.strip()
            or len(capability_reason) > 4096
        ):
            raise ScenarioEffectContractError(
                f"effect evidence {effect_id} capability reason is invalid"
            )
        if status == "applied":
            if capability.get("status") != "available":
                raise ScenarioEffectContractError(
                    f"effect evidence {effect_id} cannot be applied by an unavailable capability"
                )
            if effect_id == "obstacles":
                _validate_obstacle_evidence(requested_by_id[effect_id], effect)
            elif effect_id in BUNDLED_STEADY_WIND_EFFECT_IDS:
                _validate_bundled_steady_wind_evidence(
                    request,
                    requested_by_id[effect_id],
                    effect,
                )
            elif effect_id in BUNDLED_SDF_PROFILE_EFFECT_IDS:
                _validate_bundled_sdf_profile_evidence(
                    request,
                    requested_by_id[effect_id],
                    effect,
                )
            elif effect_id in BUNDLED_RUNTIME_EFFECT_IDS:
                _validate_bundled_runtime_evidence(
                    request,
                    requested_by_id[effect_id],
                    effect,
                )
            else:
                _validate_extension_evidence(requested_by_id[effect_id], effect)
        else:
            reason = effect.get("reason")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
                raise ScenarioEffectContractError(f"effect evidence {effect_id} requires a reason")
        observed[effect_id] = effect
    missing = sorted(set(requested_by_id) - set(observed))
    if missing:
        raise ScenarioEffectContractError(
            "scenario effect evidence omitted requested effects: " + ", ".join(missing)
        )

    applied = sorted(
        effect_id for effect_id, item in observed.items() if item["status"] == "applied"
    )
    failed = sorted(effect_id for effect_id, item in observed.items() if item["status"] == "failed")
    unsupported = sorted(
        effect_id for effect_id, item in observed.items() if item["status"] == "unsupported"
    )
    skipped = sorted(
        effect_id for effect_id, item in observed.items() if item["status"] == "skipped"
    )
    status = (
        "failed"
        if failed or skipped
        else ("unsupported" if unsupported else "verified_applied")
    )
    return {
        "requested_effects": sorted(requested_by_id),
        "applied_effects": applied,
        "unsupported_effects": unsupported,
        "failed_effects": failed,
        "skipped_effects": skipped,
        "verification_status": status,
        "capabilities": [observed[effect_id] for effect_id in sorted(observed)],
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "request_sha256": request["request_sha256"],
    }


def load_scenario_effect_evidence(path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_EFFECT_CONTRACT_BYTES:
        raise ScenarioEffectContractError("scenario effect evidence file is missing or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScenarioEffectContractError(
            f"could not read scenario effect evidence: {exc}"
        ) from exc
    return validate_scenario_effect_evidence(request, payload)


def bundled_launcher_capabilities() -> dict[str, Any]:
    """Static discovery payload; per-run evidence remains authoritative."""

    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "physically_applied": [
            "actuator_first_order_delay",
            "actuator_hard_failure",
            "battery_initial_state_and_voltage_sag",
            "deterministic_seeded_gps_dropout",
            "gust_and_turbulence",
            "obstacles",
            "payload_mass_and_inertia",
            "sensor_noise",
            "steady_wind",
        ],
        "obstacles": {
            "status": "available",
            "mechanism": "gazebo_entity_factory",
            "requires": ["gz CLI", "/world/<world>/create UserCommands service"],
            "evidence": "Gazebo Boolean create response plus SDF SHA-256",
        },
        "steady_wind": {
            "status": "available",
            "effect_ids": sorted(BUNDLED_STEADY_WIND_EFFECT_IDS),
            "mechanism": "gazebo_wind_effects",
            "maximum_combined_speed_mps": MAX_BUNDLED_STEADY_WIND_MPS,
            "requires": [
                "gz CLI",
                "Gazebo WindEffects system",
                "/world/<world>/wind_info",
                "/world/<world>/generate_world_sdf",
                "PX4 x500_base model",
            ],
            "evidence": (
                "exact Wind readback plus generated runtime SDF proving "
                "the exact x500-family runtime instance/base_link enable_wind"
            ),
        },
        "trial_local_sdf_profiles": {
            "status": "available",
            "effect_ids": sorted(BUNDLED_SDF_PROFILE_EFFECT_IDS),
            "mechanisms": [
                "gazebo_wind_effects",
                "sdformat_sensor_noise",
                "sdformat_model_inertial",
                "sdformat_actuator_dynamics",
                "sdformat_actuator_hard_stop",
                "gazebo_joint_state_publisher",
            ],
            "requires": [
                "Gazebo /world/<world>/generate_world_sdf",
                "PX4 x500 model",
            ],
            "evidence": (
                "request-bound compiled profile plus exact generated runtime SDF "
                "read-back for every affected sensor, inertial, motor, and wind field"
            ),
        },
        "flight_timed_runtime_profiles": {
            "status": "available",
            "effect_ids": sorted(BUNDLED_RUNTIME_EFFECT_IDS),
            "mechanisms": [
                "mavsdk_sim_gps_used_plus_gps_info_telemetry",
                "px4_battery_simulation",
            ],
            "requires": [
                "MAVSDK Param and Telemetry plugins",
                "PX4 gz_bridge SIM_GPS_USED support",
                "PX4 battery simulator",
                "offboard executor",
            ],
            "evidence": (
                "request-bound deterministic schedule, exact SIM_GPS_USED transition/restore "
                "readback, physical GPS fix/satellite telemetry, and flight-timed battery telemetry"
            ),
        },
        "requires_runtime_extension": [],
    }


__all__ = [
    "BUNDLED_RUNTIME_EFFECT_IDS",
    "BUNDLED_STEADY_WIND_EFFECT_IDS",
    "BUNDLED_WIND_ACTIVATION_EFFECT_IDS",
    "BUNDLED_SDF_PROFILE_EFFECT_IDS",
    "DEFAULT_SCENARIO_STEADY_WIND_MPS",
    "EVIDENCE_ARTIFACT_NAME",
    "EVIDENCE_SCHEMA_VERSION",
    "MAX_BUNDLED_STEADY_WIND_MPS",
    "REQUEST_ARTIFACT_NAME",
    "REQUEST_SCHEMA_VERSION",
    "ScenarioEffectContractError",
    "build_scenario_effect_evidence",
    "build_scenario_effect_request",
    "bundled_launcher_capabilities",
    "compile_bundled_steady_wind",
    "compile_bundled_gps_dropout_schedule",
    "compile_bundled_sdf_profile",
    "compile_bundled_runtime_profile",
    "load_scenario_effect_evidence",
    "load_scenario_effect_request",
    "scenario_effect_request_sha256",
    "scenario_effect_value_sha256",
    "RUNTIME_EVIDENCE_ARTIFACT_NAME",
    "validate_scenario_effect_evidence",
    "validate_scenario_effect_request",
    "write_json_atomic",
]
