from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.benchmarking.contracts import CompositeExecutionInventoryV1, canonical_sha256
from app.benchmarking.physical_stability import (
    build_physical_stability_manifest,
    compile_physical_stability_trial_plan,
)
from app.benchmarking.physical_stability_assessment import (
    PhysicalStabilityMetricsV1,
    PhysicalStabilityTrialObservationV1,
    assess_physical_stability_campaign,
    write_physical_stability_assessment,
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


def _contract():
    manifest = build_physical_stability_manifest(
        repository_subject_commit=_SOURCE,
        composite_execution_inventory=_inventory(),
    )
    return manifest, compile_physical_stability_trial_plan(manifest)


def _observations(*, saturated_scenario: str | None = None):
    manifest, plan = _contract()
    manifest_sha = canonical_sha256(manifest)
    plan_sha = canonical_sha256(plan)
    observations = []
    scenario_ordinals: dict[str, int] = {}
    for item in plan.trials:
        index = scenario_ordinals.get(item.scenario_id, 0)
        scenario_ordinals[item.scenario_id] = index + 1
        pass_flag = item.scenario_id == saturated_scenario or index < 5
        observations.append(
            PhysicalStabilityTrialObservationV1(
                manifest_sha256=manifest_sha,
                plan_sha256=plan_sha,
                repository_subject_commit=plan.repository_subject_commit,
                composite_execution_inventory_sha256=(plan.composite_execution_inventory_sha256),
                trial_id=item.trial_id,
                scenario_id=item.scenario_id,
                seed=item.seed,
                input_contract_sha256=item.input_contract_sha256,
                scenario_effect_request_sha256=item.scenario_effect_request_sha256,
                terminal_status="completed",
                metrics=PhysicalStabilityMetricsV1(
                    rmse=0.5 + index * 0.005,
                    max_error=1.0 + index * 0.01,
                    completion_time_seconds=30.0 + index * 0.1,
                    pass_flag=pass_flag,
                    crash_flag=False,
                    timeout_flag=False,
                    instability_flag=False,
                ),
                effect_request_applied=True,
                effect_readback_verified=True,
                parameter_readback_verified=True,
                telemetry_evidence_sha256="b" * 64,
                metric_evidence_sha256="c" * 64,
                artifact_inventory_sha256="d" * 64,
            )
        )
    return manifest, plan, observations


def test_p5_assessment_keeps_sixty_trials_and_selects_only_graded_scenarios() -> None:
    manifest, plan, observations = _observations()
    assessment = assess_physical_stability_campaign(
        manifest=manifest,
        plan=plan,
        observations=observations,
    )

    assert assessment.trial_count == 60
    assert assessment.terminal_status_counts == {"completed": 60}
    assert assessment.provider_logical_turns_attempted == 0
    assert assessment.provider_network_requests_attempted == 0
    assert assessment.comparative_arm_outcomes_observed is False
    assert len(assessment.eligible_scenario_ids) == 6
    assert assessment.pilot_selection_ready is True
    assert assessment.all_preregistered_candidates_eligible is True
    assert assessment.final_scenario_freeze_ready is False
    assert all(item.pass_count == 5 for item in assessment.scenarios)
    assert all(item.difficulty_signal == "graded" for item in assessment.scenarios)


def test_p5_assessment_marks_saturated_baseline_for_replacement_without_pruning_others() -> None:
    manifest, plan, observations = _observations(saturated_scenario="hover-mild-crosswind")
    assessment = assess_physical_stability_campaign(
        manifest=manifest,
        plan=plan,
        observations=observations,
    )
    by_id = {item.scenario_id: item for item in assessment.scenarios}

    assert by_id["hover-mild-crosswind"].difficulty_signal == ("baseline_trivially_saturated")
    assert by_id["hover-mild-crosswind"].final_candidate_status == "replacement_required"
    assert "hover-mild-crosswind" not in assessment.eligible_scenario_ids
    assert len(assessment.eligible_scenario_ids) == 5


def test_p5_failure_remains_in_denominator_and_invalidates_physical_contract() -> None:
    manifest, plan, observations = _observations()
    failed_item = plan.trials[0]
    failed = PhysicalStabilityTrialObservationV1(
        manifest_sha256=canonical_sha256(manifest),
        plan_sha256=canonical_sha256(plan),
        repository_subject_commit=plan.repository_subject_commit,
        composite_execution_inventory_sha256=plan.composite_execution_inventory_sha256,
        trial_id=failed_item.trial_id,
        scenario_id=failed_item.scenario_id,
        seed=failed_item.seed,
        input_contract_sha256=failed_item.input_contract_sha256,
        scenario_effect_request_sha256=failed_item.scenario_effect_request_sha256,
        terminal_status="timeout",
        effect_request_applied=False,
        effect_readback_verified=False,
        parameter_readback_verified=False,
        failure_code="SIMULATOR_TIMEOUT",
    )
    observations[0] = failed
    assessment = assess_physical_stability_campaign(
        manifest=manifest,
        plan=plan,
        observations=observations,
    )
    first = assessment.scenarios[0]

    assert assessment.terminal_status_counts == {"completed": 59, "timeout": 1}
    assert first.trial_count == 10
    assert first.completed_count == 9
    assert first.safety_critical_failure_count == 1
    assert first.final_candidate_status == "physical_contract_invalid"


def test_p5_assessment_rejects_missing_duplicate_and_drifted_observations() -> None:
    manifest, plan, observations = _observations()
    with pytest.raises(ValueError, match="incomplete"):
        assess_physical_stability_campaign(
            manifest=manifest,
            plan=plan,
            observations=observations[:-1],
        )
    with pytest.raises(ValueError, match="duplicate"):
        assess_physical_stability_campaign(
            manifest=manifest,
            plan=plan,
            observations=[*observations[:-1], observations[0]],
        )

    drifted = observations[0].model_copy(update={"input_contract_sha256": "e" * 64})
    with pytest.raises(ValueError, match="input_contract_sha256"):
        assess_physical_stability_campaign(
            manifest=manifest,
            plan=plan,
            observations=[drifted, *observations[1:]],
        )


def test_p5_observation_terminal_schema_is_fail_closed() -> None:
    manifest, plan, observations = _observations()
    payload = observations[0].model_dump(mode="python")
    payload["terminal_status"] = "failed"
    payload["failure_code"] = "SIM_ERROR"

    with pytest.raises(ValidationError, match="forbid metrics"):
        PhysicalStabilityTrialObservationV1.model_validate(payload)


def test_p5_assessment_writer_is_atomic_and_refuses_overwrite(tmp_path: Path) -> None:
    manifest, plan, observations = _observations()
    assessment = assess_physical_stability_campaign(
        manifest=manifest,
        plan=plan,
        observations=observations,
    )
    path = tmp_path / "assessment.json"

    write_physical_stability_assessment(path, assessment)
    first = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_physical_stability_assessment(path, assessment)
    assert path.read_bytes() == first
    assert canonical_sha256(assessment) == canonical_sha256(assessment.model_dump(mode="json"))
