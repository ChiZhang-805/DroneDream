from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest

from app.optimization.generalization_evidence import (
    verify_candidate_generalization_evidence,
)
from app.optimization.scenario_generalization_campaign import (
    SCENARIO_GENERALIZATION_SCHEMA_VERSION,
    ScenarioGeneralizationArtifact,
    _enabled_cases,
    _evaluate_case_set,
    _optimizer_search,
    _scenario_suite,
    _search_space,
    run_scenario_generalization_campaign,
    write_frozen_scenario_generalization_artifact,
)
from app.schemas import ScenarioCaseConfig

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation_artifacts"
    / "scenario-generalization-mock-v1.json"
)


@pytest.fixture(scope="module")
def campaign() -> ScenarioGeneralizationArtifact:
    return run_scenario_generalization_campaign()


def test_committed_scenario_generalization_freeze_matches_current_campaign(
    campaign: ScenarioGeneralizationArtifact,
) -> None:
    committed = ScenarioGeneralizationArtifact.model_validate_json(
        ARTIFACT_PATH.read_text(encoding="utf-8")
    )
    assert committed == campaign
    assert campaign.schema_version == SCENARIO_GENERALIZATION_SCHEMA_VERSION
    assert campaign.qualified is True
    assert campaign.failed_requirements == ()


def test_scenario_generalization_is_report_only_and_complete(
    campaign: ScenarioGeneralizationArtifact,
) -> None:
    evidence = verify_candidate_generalization_evidence(campaign.generalization_evidence)
    assert evidence is not None
    assert campaign.validation_outcomes_used_for_selection is False
    assert evidence.qualified is True
    assert evidence.claim_scope == "mixed_shift_robustness"
    assert evidence.shift_axes == ("configuration_shift", "scenario_type_shift")
    assert evidence.configuration_shift_case_count == 5
    assert evidence.novel_scenario_type_case_count == 5
    assert evidence.validation_case_count == 10
    assert evidence.validation_trial_count == 10
    assert evidence.validation_completed_trial_count == 10
    assert not (set(campaign.training_seeds.values()) & set(campaign.validation_seeds.values()))


def test_optimizer_selection_has_no_validation_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.optimization.scenario_generalization_campaign as module

    original = module._evaluate_case_set
    validation_calls = 0

    def guarded_evaluate(
        parameters: dict[str, float],
        *,
        cases: tuple[ScenarioCaseConfig, ...],
        phase: Literal["training", "validation"],
    ) -> tuple[float, dict[str, float], bool]:
        nonlocal validation_calls
        if phase == "validation":
            validation_calls += 1
            raise AssertionError("validation reached the training-only optimizer")
        return original(parameters, cases=cases, phase=phase)

    monkeypatch.setattr(module, "_evaluate_case_set", guarded_evaluate)
    selected, transcript = _optimizer_search(
        space=_search_space(),
        training_cases=_enabled_cases(_scenario_suite(), holdout=False),
    )
    assert selected
    assert len(transcript) == 61
    assert validation_calls == 0


def test_each_declared_configuration_shift_changes_the_aggregated_score() -> None:
    suite = _scenario_suite()
    training_by_type = {case.scenario_type: case for case in _enabled_cases(suite, holdout=False)}
    validation_cases = _enabled_cases(suite, holdout=True)
    parameters = _search_space().baseline()

    for validation_case in validation_cases[:5]:
        training_case = training_by_type[validation_case.scenario_type]
        training_same_seed = training_case.model_copy(update={"seeds": [4242]})
        validation_same_seed = validation_case.model_copy(update={"seeds": [4242]})
        training_loss, _training_rows, _training_pass = _evaluate_case_set(
            parameters,
            cases=(training_same_seed,),
            phase="training",
        )
        validation_loss, _validation_rows, _validation_pass = _evaluate_case_set(
            parameters,
            cases=(validation_same_seed,),
            phase="validation",
        )
        assert validation_loss != pytest.approx(training_loss, abs=1e-6), (
            f"{validation_case.id} changed configuration without changing score"
        )


def test_scenario_generalization_evidence_rejects_tampering(
    campaign: ScenarioGeneralizationArtifact,
) -> None:
    payload = campaign.generalization_evidence.model_dump(mode="json")
    payload["validation_scalar_loss"] += 0.1
    assert verify_candidate_generalization_evidence(payload) is None


def test_scenario_generalization_freeze_refuses_overwrite(
    tmp_path: Path,
    campaign: ScenarioGeneralizationArtifact,
) -> None:
    destination = tmp_path / "scenario-generalization.json"
    write_frozen_scenario_generalization_artifact(destination, campaign)
    first = json.loads(destination.read_text(encoding="utf-8"))
    assert first["schema_version"] == SCENARIO_GENERALIZATION_SCHEMA_VERSION

    with pytest.raises(FileExistsError):
        write_frozen_scenario_generalization_artifact(destination, campaign)
