"""Regression tests for the shared model-facing feedback trust boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.optimization.outcome_evidence import (
    candidate_training_trial_evidence_rows,
    compile_candidate_outcome_evidence,
)
from app.orchestration.provider_feedback import compile_candidate_feedback


def _metric(*, rmse: float = 0.4) -> SimpleNamespace:
    return SimpleNamespace(
        rmse=rmse,
        max_error=0.8,
        overshoot_count=1,
        completion_time=9.0,
        crash_flag=False,
        timeout_flag=False,
        score=0.4,
        final_error=0.1,
        pass_flag=True,
        instability_flag=False,
    )


def _trial(*, rmse: float = 0.4) -> SimpleNamespace:
    return SimpleNamespace(
        id="trial-1",
        status="COMPLETED",
        seed=101,
        scenario_type="nominal",
        scenario_config_json={"holdout": False},
        failure_code=None,
        metric=_metric(rmse=rmse),
    )


def _aggregate() -> dict[str, object]:
    return {
        "training_trial_count": 1,
        "training_completed_trial_count": 1,
        "training_failed_trial_count": 0,
        "training_passing_trial_count": 1,
        "training_trial_outcome_counts": {
            "success": 1,
            "domain_failure": 0,
            "infrastructure_failure": 0,
            "cancelled": 0,
            "invalid_evidence": 0,
            "unknown_failure": 0,
        },
        "training_trial_outcome_rates": {
            "success": 1.0,
            "domain_failure": 0.0,
            "infrastructure_failure": 0.0,
            "cancelled": 0.0,
            "invalid_evidence": 0.0,
            "unknown_failure": 0.0,
        },
        "optimizer_learning_failure_rate": 0.0,
        "objective_values": {"rmse": 0.4},
        "constraint_values": {},
        "constraint_violations": {},
        "feasible": True,
        "preference_loss": 0.3,
        "soft_constraint_penalty": 0.0,
        "scalar_loss": 0.3,
        "selection_key": {
            "schema_version": "1.0",
            "evidence_complete": True,
            "hard_feasible": True,
            "hard_constraint_violation": 0.0,
            "training_failure_rate": 0.0,
            "decision_loss": 0.3,
        },
        "acceptance_rmse": 0.4,
        "acceptance_max_error": 0.8,
        "acceptance_pass_rate": 1.0,
        "acceptance_completion_rate": 1.0,
    }


def _verified_candidate() -> SimpleNamespace:
    candidate = SimpleNamespace(
        id="candidate-1",
        job_id="job-1",
        generation_index=1,
        parameter_json={"kp_xy": 1.2},
        aggregated_metric_json={},
        aggregated_score=999.0,
        trials=[_trial()],
    )
    rows = candidate_training_trial_evidence_rows(candidate)
    assert rows is not None
    aggregate = _aggregate()
    evidence = compile_candidate_outcome_evidence(
        outcome_contract_id="sha256:" + "a" * 64,
        candidate_id=candidate.id,
        generation_index=candidate.generation_index,
        parameter_snapshot=candidate.parameter_json,
        trial_evidence_rows=rows,
        aggregate=aggregate,
    )
    candidate.aggregated_metric_json = {
        **aggregate,
        "candidate_outcome_evidence_required": True,
        "candidate_outcome_evidence": evidence.model_dump(mode="json"),
    }
    return candidate


def test_verified_feedback_ignores_mutable_sibling_score_and_metrics() -> None:
    candidate = _verified_candidate()
    candidate.aggregated_metric_json["scalar_loss"] = -999.0
    candidate.aggregated_metric_json["rmse"] = 0.000001

    feedback = compile_candidate_feedback(candidate, scenario_suite=None)

    assert feedback.feedback_status == "verified"
    assert feedback.usable is True
    assert feedback.score == pytest.approx(0.3)
    assert feedback.aggregate["scalar_loss"] == pytest.approx(0.3)
    assert feedback.aggregate["rmse"] == pytest.approx(0.4)
    assert feedback.learning_trial_count == 1
    assert feedback.completed_trial_count == 1
    assert feedback.failed_trial_count == 0
    assert feedback.feasible is True


def test_verified_feedback_quarantines_parameter_or_trial_divergence() -> None:
    candidate = _verified_candidate()
    candidate.parameter_json = {"kp_xy": 2.0}

    parameter_tamper = compile_candidate_feedback(candidate, scenario_suite=None)

    assert parameter_tamper.feedback_status == "quarantined"
    assert parameter_tamper.usable is False
    assert parameter_tamper.score is None
    assert parameter_tamper.aggregate == {}
    assert parameter_tamper.learning_trial_count == 0

    candidate = _verified_candidate()
    candidate.trials[0].metric.rmse = 0.9

    trial_tamper = compile_candidate_feedback(candidate, scenario_suite=None)

    assert trial_tamper.feedback_status == "quarantined"
    assert trial_tamper.score is None
    assert trial_tamper.aggregate == {}


def test_legacy_feedback_remains_available_but_explicitly_unsealed() -> None:
    candidate = SimpleNamespace(
        id="legacy-candidate",
        job_id="job-1",
        generation_index=0,
        parameter_json={"kp_xy": 1.0},
        aggregated_metric_json={"rmse": 0.7, "feasible": True},
        aggregated_score=0.7,
        trials=[_trial(rmse=0.7)],
    )

    feedback = compile_candidate_feedback(candidate, scenario_suite=None)

    assert feedback.feedback_status == "legacy_unsealed"
    assert feedback.score == pytest.approx(0.7)
    assert feedback.aggregate["rmse"] == pytest.approx(0.7)
    assert feedback.learning_trial_count == 1
    assert feedback.completed_trial_count == 1
    assert feedback.feasible is True
