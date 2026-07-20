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
MAX_EFFECT_CONTRACT_BYTES = 2 * 1024 * 1024
MAX_EFFECTS_PER_REQUEST = 64
MAX_EVIDENCE_OBSERVATIONS = 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000

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
    if effect_id in {
        "job_config.wind",
        "scenario_config.wind_mps",
        "wind_gusts",
        "scenario_type.wind_perturbed",
        "scenario_type.turbulence",
    }:
        return (
            "the bundled runtime has no per-trial WindEffects world generator; "
            "exact wind vector/gust evidence must come from a configured Gazebo "
            "WindEffects plugin and /world/<world>/wind_info observation"
        )
    if effect_id in {
        "job_config.sensor_noise_level",
        "sensor_degradation.gps_noise_m",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "scenario_type.noise_perturbed",
    }:
        return (
            "Gazebo sensor noise is configured in model SDF; the bundled runtime "
            "does not yet generate and verify a per-trial sensor model"
        )
    if effect_id in {
        "sensor_degradation.dropout_rate",
        "scenario_config.dropout_rate",
        "scenario_type.gps_dropout",
    }:
        return (
            "PX4 SITL GPS failure injection supports off/stuck/wrong, not a "
            "probabilistic dropout rate; no safe schedule conversion is configured"
        )
    if effect_id in {
        "battery.initial_percent",
        "battery.voltage_sag",
        "scenario_type.battery_degraded",
    }:
        return (
            "the bundled launcher does not yet apply and read back PX4 battery "
            "simulation parameters or battery failure injection"
        )
    if effect_id in {"battery.mass_payload_kg", "scenario_type.payload_changed"}:
        return (
            "payload mass requires a per-trial Gazebo model/inertial definition; "
            "the bundled runtime does not mutate vehicle inertia"
        )
    if effect_id == "scenario_type.actuator_delay":
        return "the bundled launcher has no verified PX4/Gazebo actuator-delay injection"
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
        return "px4_failure_injection" if "dropout" in effect_id else "sdformat_sensor_noise"
    if "gps_dropout" in effect_id or effect_id.endswith("dropout_rate"):
        return "px4_failure_injection"
    if effect_id.startswith("battery") or effect_id.endswith("battery_degraded"):
        return "px4_battery_simulation"
    if "payload" in effect_id:
        return "sdformat_model_inertial"
    if "actuator_delay" in effect_id:
        return "px4_failure_injection"
    return "site_specific"


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
        capability_status = (
            "available" if effect_id == "obstacles" else "requires_runtime_extension"
        )
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
                    "reason": (
                        "the bundled launcher can create static obstacles through "
                        "Gazebo /world/<world>/create and verifies the Boolean service response"
                        if effect_id == "obstacles"
                        else _unsupported_reason(effect_id)
                    ),
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
    # ``combined_perturbed`` is only a label.  Keep the explicit unsupported
    # marker as a guard when the caller supplied no physical perturbation at
    # all, but do not poison a fully specified combined scenario with an
    # additional non-physical effect that no launcher could ever apply.
    if scenario_type == "combined_perturbed" and not requested_ids:
        add(
            "scenario_type.combined_perturbed",
            "scenario_type",
            {"scenario_type": scenario_type, "config": scenario},
        )
    elif scenario_type in concrete_by_scenario and not (
        concrete_by_scenario[scenario_type] & requested_ids
    ):
        default_value: Any = {"scenario_type": scenario_type, "config": scenario}
        if scenario_type == "gps_dropout" and not scenario:
            default_value = {"dropout_rate": 0.2, "source": "scenario_default"}
        add(f"scenario_type.{scenario_type}", "scenario_type", default_value)
    elif scenario_type in {"actuator_delay", "custom"}:
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
    if digest != _request_hash(payload):
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
        effect_id
        for effect_id, item in observed.items()
        if item["status"] in {"unsupported", "skipped"}
    )
    status = "failed" if failed else ("unsupported" if unsupported else "verified_applied")
    return {
        "requested_effects": sorted(requested_by_id),
        "applied_effects": applied,
        "unsupported_effects": unsupported,
        "failed_effects": failed,
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
        "physically_applied": ["obstacles"],
        "obstacles": {
            "status": "available",
            "mechanism": "gazebo_entity_factory",
            "requires": ["gz CLI", "/world/<world>/create UserCommands service"],
            "evidence": "Gazebo Boolean create response plus SDF SHA-256",
        },
        "requires_runtime_extension": [
            "wind vector and gust profile",
            "sensor noise and degradation",
            "probabilistic GPS dropout",
            "battery initial state and voltage sag",
            "vehicle payload mass",
            "actuator delay",
        ],
    }


__all__ = [
    "EVIDENCE_ARTIFACT_NAME",
    "EVIDENCE_SCHEMA_VERSION",
    "REQUEST_ARTIFACT_NAME",
    "REQUEST_SCHEMA_VERSION",
    "ScenarioEffectContractError",
    "build_scenario_effect_evidence",
    "build_scenario_effect_request",
    "bundled_launcher_capabilities",
    "load_scenario_effect_evidence",
    "load_scenario_effect_request",
    "validate_scenario_effect_evidence",
    "validate_scenario_effect_request",
    "write_json_atomic",
]
