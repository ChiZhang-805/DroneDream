from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.benchmarking.contracts import CompositeExecutionInventoryV1, canonical_sha256
from app.benchmarking.physical_stability import (
    PHYSICAL_STABILITY_PROTOCOL_SHA256,
    PHYSICAL_STABILITY_SEEDS,
    build_physical_stability_manifest,
    compile_physical_stability_trial_plan,
)

_SOURCE = "3" * 40
_SHA = "a" * 64


def _inventory() -> CompositeExecutionInventoryV1:
    component = {
        "component_id": "fixture",
        "version": "fixture-v1",
        "source_commit": _SOURCE,
        "artifact_sha256": _SHA,
        "manifest_sha256": _SHA,
    }
    return CompositeExecutionInventoryV1(
        repository_subject_commit=_SOURCE,
        evaluator_subject_commit=_SOURCE,
        campaign_coordinator_subject_commit=_SOURCE,
        runtime_base={**component, "component_id": "runtime-base"},
        engine_pack={**component, "component_id": "engine-pack"},
        px4={**component, "component_id": "px4"},
        gazebo={**component, "component_id": "gazebo"},
        prompt_registry_sha256=_SHA,
        response_schema_sha256=_SHA,
        tool_registry_sha256=_SHA,
        model_matrix_sha256=_SHA,
        machine_profile_sha256=_SHA,
        concurrency_profile_sha256=_SHA,
    )


def test_p5_manifest_freezes_six_scenarios_and_sixty_zero_provider_trials() -> None:
    manifest = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(),
    )
    plan = compile_physical_stability_trial_plan(manifest)

    assert manifest.protocol_sha256 == PHYSICAL_STABILITY_PROTOCOL_SHA256
    assert manifest.execution_authorized is False
    assert manifest.provider_access is False
    assert manifest.optimizer_access is False
    assert len(manifest.scenarios) == 6
    assert all(item.seeds == PHYSICAL_STABILITY_SEEDS for item in manifest.scenarios)
    assert plan.trial_count == len(plan.trials) == 60
    assert plan.provider_logical_turn_cap == plan.provider_network_request_cap == 0
    assert plan.execution_authorized is False
    assert {item.scenario_id for item in plan.trials} == {
        "hover-mild-crosswind",
        "circle-mild-crosswind",
        "u-turn-steady-wind",
        "figure-eight-light-gust",
        "circle-sensor-degradation",
        "composite-stress",
    }
    assert all(len(item.input_contract_sha256) == 64 for item in plan.trials)
    assert all(len(item.scenario_effect_request_sha256) == 64 for item in plan.trials)


def test_p5_derivations_are_bounded_and_keep_gps_prearm_injection_disabled() -> None:
    manifest = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(),
    )
    by_id = {item.scenario_id: item for item in manifest.scenarios}

    assert by_id["figure-eight-light-gust"].job_config.track_type == "lemniscate"
    assert by_id["figure-eight-light-gust"].task_family == "continuous_turning"
    assert "figure-eight" in by_id["figure-eight-light-gust"].user_relevance.lower()
    sensor = by_id["circle-sensor-degradation"].scenario_config["advanced_scenario_config"][
        "sensor_degradation"
    ]
    assert sensor == {
        "gps_noise_m": 0.0,
        "baro_noise_m": 0.1,
        "imu_noise_scale": 1.1,
        "dropout_rate": 0.0,
    }
    assert by_id["circle-sensor-degradation"].task_family == "orbit_inspection"
    composite = by_id["composite-stress"].scenario_config["advanced_scenario_config"]
    assert composite["sensor_degradation"]["gps_noise_m"] == 0.0
    assert composite["battery"]["mass_payload_kg"] == 0.25
    assert by_id["composite-stress"].job_config.wind_north == 2.0


def test_p5_manifest_and_plan_are_byte_reproducible() -> None:
    first = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(),
    )
    second = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(),
    )

    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256(compile_physical_stability_trial_plan(first)) == canonical_sha256(
        compile_physical_stability_trial_plan(second)
    )


def test_p5_rejects_subject_drift_and_post_execution_evidence_heads() -> None:
    inventory = _inventory()
    with pytest.raises(ValidationError, match="subjects must be identical"):
        build_physical_stability_manifest(
            repository_subject_commit="4" * 40,
            composite_execution_inventory=inventory,
        )

    tampered = inventory.model_copy(update={"evidence_head_commit": "5" * 40})
    with pytest.raises(ValidationError, match="post-execution evidence head"):
        build_physical_stability_manifest(
            repository_subject_commit=_SOURCE,
            composite_execution_inventory=tampered,
        )


def test_p5_rejects_manifest_tamper_before_plan_compilation() -> None:
    manifest = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(),
    )
    payload = manifest.model_dump(mode="python")
    payload["scenarios"] = list(payload["scenarios"])
    payload["scenarios"][0] = deepcopy(payload["scenarios"][0])
    payload["scenarios"][0]["seeds"] = tuple(range(1, 11))
    payload["scenarios"] = tuple(payload["scenarios"])

    with pytest.raises(ValidationError, match="frozen ten-seed CRN block"):
        type(manifest).model_validate(payload)
