from __future__ import annotations

import json

import pytest

from app import schemas
from app.optimization.generalization_evidence import (
    GENERALIZATION_EVIDENCE_SCHEMA,
    compile_candidate_generalization_evidence,
    verify_candidate_generalization_evidence,
)


def _objective_config() -> schemas.ObjectiveConfig:
    return schemas.ObjectiveConfig(
        objectives=[
            schemas.ObjectiveSpec(
                metric="rmse",
                direction="minimize",
                weight=0.7,
            ),
            schemas.ObjectiveSpec(
                metric="pass_rate",
                direction="maximize",
                weight=0.3,
            ),
        ]
    )


def test_seed_shift_receipt_is_direction_aware_and_content_addressed() -> None:
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(
                id="train",
                scenario_type="wind_perturbed",
                seeds=[11, 12],
                config={"wind_mps": 4},
            ),
            schemas.ScenarioCaseConfig(
                id="validation",
                scenario_type="wind_perturbed",
                seeds=[91, 92],
                holdout=True,
                config={"wind_mps": 4},
            ),
        ]
    )

    evidence = compile_candidate_generalization_evidence(
        objective_config=_objective_config(),
        scenario_suite=suite,
        validation_status="passed",
        validation_trial_count=2,
        validation_completed_trial_count=2,
        training_objectives={"rmse": 0.5, "pass_rate": 0.95},
        validation_objectives={"rmse": 0.6, "pass_rate": 0.9},
        training_scalar_loss=0.25,
        validation_scalar_loss=0.31,
        outcome_contract_id="sha256:" + "a" * 64,
    )

    assert evidence.schema_id == GENERALIZATION_EVIDENCE_SCHEMA
    assert evidence.role == "validation_report_only_no_adaptive_feedback"
    assert evidence.shift_axes == ("seed_shift",)
    assert evidence.claim_scope == "seed_robustness"
    assert evidence.disjoint_seed_case_count == 1
    assert evidence.training_validation_seed_overlap_count == 0
    assert evidence.validation_replicate_count == 2
    assert evidence.validation_trial_count == 2
    assert evidence.validation_completed_trial_count == 2
    assert evidence.qualified is True
    assert evidence.assessment == "qualified_with_degradation"
    assert evidence.observed_shift == "degraded"
    assert evidence.degraded_objective_count == 2
    assert evidence.objective_gaps[0].signed_degradation == pytest.approx(0.1)
    assert evidence.objective_gaps[0].relative_degradation == pytest.approx(0.2)
    assert evidence.objective_gaps[1].signed_degradation == pytest.approx(0.05)
    assert evidence.scalar_loss_degradation == pytest.approx(0.06)
    assert evidence.scalar_loss_relative_degradation == pytest.approx(0.24)
    assert verify_candidate_generalization_evidence(evidence.model_dump(mode="json")) == evidence

    tampered = json.loads(json.dumps(evidence.model_dump(mode="json")))
    tampered["objective_gaps"][0]["validation_value"] = 0.01
    assert verify_candidate_generalization_evidence(tampered) is None

    with pytest.raises(ValueError, match="scenario suite SHA-256"):
        compile_candidate_generalization_evidence(
            objective_config=_objective_config(),
            scenario_suite=suite,
            validation_status="passed",
            validation_trial_count=2,
            validation_completed_trial_count=2,
            training_objectives={"rmse": 0.5, "pass_rate": 0.95},
            validation_objectives={"rmse": 0.6, "pass_rate": 0.9},
            training_scalar_loss=0.25,
            validation_scalar_loss=0.31,
            scenario_suite_sha256="b" * 64,
        )


def test_mixed_validation_suite_records_type_and_configuration_shift() -> None:
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(
                id="train-wind",
                scenario_type="wind_perturbed",
                seeds=[11],
                config={"wind_mps": 4},
            ),
            schemas.ScenarioCaseConfig(
                id="validation-wind",
                scenario_type="wind_perturbed",
                seeds=[91],
                holdout=True,
                config={"wind_mps": 8},
            ),
            schemas.ScenarioCaseConfig(
                id="validation-payload",
                scenario_type="payload_changed",
                seeds=[92],
                holdout=True,
                config={"mass_payload_kg": 1.2},
            ),
        ]
    )

    evidence = compile_candidate_generalization_evidence(
        objective_config=_objective_config(),
        scenario_suite=suite,
        validation_status="passed",
        validation_trial_count=2,
        validation_completed_trial_count=2,
        training_objectives={"rmse": 0.5, "pass_rate": 0.8},
        validation_objectives={"rmse": 0.45, "pass_rate": 0.85},
        training_scalar_loss=0.3,
        validation_scalar_loss=0.25,
    )

    assert evidence.shift_axes == (
        "configuration_shift",
        "scenario_type_shift",
    )
    assert evidence.claim_scope == "mixed_shift_robustness"
    assert evidence.configuration_shift_case_count == 1
    assert evidence.novel_scenario_type_case_count == 1
    assert evidence.assessment == "qualified_improved_or_equal"
    assert evidence.observed_shift == "improved_or_equal"


def test_incomplete_validation_is_not_assessable_or_qualified() -> None:
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(id="train", seeds=[1]),
            schemas.ScenarioCaseConfig(
                id="validation",
                seeds=[2, 3],
                holdout=True,
            ),
        ]
    )

    evidence = compile_candidate_generalization_evidence(
        objective_config=_objective_config(),
        scenario_suite=suite,
        validation_status="incomplete",
        validation_trial_count=2,
        validation_completed_trial_count=1,
        training_objectives={"rmse": 0.5, "pass_rate": 1.0},
        validation_objectives=None,
        training_scalar_loss=0.2,
        validation_scalar_loss=None,
    )

    assert evidence.evidence_complete is False
    assert evidence.qualified is False
    assert evidence.assessment == "not_assessable"
    assert evidence.observed_shift is None
    assert evidence.objective_gaps == ()
    assert evidence.shift_axes == ("seed_shift",)
    assert evidence.validation_replicate_count == 2
    assert evidence.validation_trial_count == 2
    assert evidence.validation_completed_trial_count == 1


def test_missing_validation_matrix_rows_cannot_qualify() -> None:
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(id="train", seeds=[1]),
            schemas.ScenarioCaseConfig(
                id="validation",
                seeds=[2, 3],
                holdout=True,
            ),
        ]
    )

    evidence = compile_candidate_generalization_evidence(
        objective_config=_objective_config(),
        scenario_suite=suite,
        validation_status="passed",
        validation_trial_count=1,
        validation_completed_trial_count=1,
        training_objectives={"rmse": 0.5, "pass_rate": 1.0},
        validation_objectives={"rmse": 0.4, "pass_rate": 1.0},
        training_scalar_loss=0.2,
        validation_scalar_loss=0.1,
    )

    assert evidence.validation_replicate_count == 2
    assert evidence.validation_trial_count == 1
    assert evidence.validation_completed_trial_count == 1
    assert evidence.evidence_complete is False
    assert evidence.qualified is False
    assert evidence.assessment == "not_assessable"
    assert evidence.objective_gaps == ()


def test_compiler_rejects_unsupported_status_and_missing_training_domain() -> None:
    suite = schemas.ScenarioSuiteConfig.model_construct(
        cases=[
            schemas.ScenarioCaseConfig(
                id="validation",
                seeds=[2],
                holdout=True,
            )
        ],
        common_random_numbers=True,
    )

    with pytest.raises(ValueError, match="unsupported validation status"):
        compile_candidate_generalization_evidence(
            objective_config=_objective_config(),
            scenario_suite=suite,
            validation_status="unknown",
            validation_trial_count=1,
            validation_completed_trial_count=1,
            training_objectives=None,
            validation_objectives=None,
            training_scalar_loss=None,
            validation_scalar_loss=None,
        )

    with pytest.raises(
        ValueError,
        match="requires training and validation cases",
    ):
        compile_candidate_generalization_evidence(
            objective_config=_objective_config(),
            scenario_suite=suite,
            validation_status="incomplete",
            validation_trial_count=1,
            validation_completed_trial_count=0,
            training_objectives=None,
            validation_objectives=None,
            training_scalar_loss=None,
            validation_scalar_loss=None,
        )
