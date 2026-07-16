from __future__ import annotations

import copy
import hashlib
import json

import pytest
from app.simulator.scenario_effects import (
    ScenarioEffectContractError,
    build_scenario_effect_evidence,
    build_scenario_effect_request,
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
    assert effects["wind_gusts"]["requested_value"] == {
        "enabled": True,
        "magnitude_mps": 4.0,
        "direction_deg": 135.0,
        "period_s": 8.0,
    }
    assert "WindEffects" in effects["wind_gusts"]["capability"]["reason"]
    assert (
        "not a probabilistic dropout rate"
        in effects["sensor_degradation.dropout_rate"]["capability"]["reason"]
    )
    assert "inertial" in effects["battery.mass_payload_kg"]["capability"]["reason"]
    assert all(
        item["launcher_input"]["request_path_env"] == "PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH"
        for item in effects.values()
    )


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


def test_extended_launcher_can_prove_an_applied_effect_with_bound_readback() -> None:
    request = _request(advanced={}, wind=True)
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
