"""Focused contracts for AURORA's provider-safe observed-outcome memory."""

from __future__ import annotations

import pytest

from app import models
from app.optimization.candidate_evidence_ledger import CandidateEvidenceReceiptV2
from app.orchestration import harness_context
from app.orchestration.provider_feedback import CandidateFeedbackView


def _receipt(
    candidate: models.CandidateParameterSet,
    *,
    accepted_attempt_count: int,
) -> CandidateEvidenceReceiptV2:
    digest = "sha256:" + "a" * 64
    return CandidateEvidenceReceiptV2(
        evidence_id=digest,
        candidate_id=candidate.id,
        job_id=candidate.job_id,
        revision=1,
        previous_evidence_id=None,
        generation_index=candidate.generation_index,
        parameter_sha256=digest,
        aggregate_sha256=digest,
        outcome_evidence_id=digest,
        training_trial_evidence_sha256=digest,
        training_accepted_attempt_count=accepted_attempt_count,
        report_evidence_id=digest,
        report_trial_evidence_sha256=digest,
        report_accepted_attempt_count=accepted_attempt_count,
        source_type=candidate.source_type,
        optimizer_source_evidence_required=(candidate.source_type == "optimizer"),
        optimizer_metadata_sha256=digest,
    )


def _feedback(
    score: float,
    *,
    completed: int,
    failed: int,
    feasible: bool,
) -> CandidateFeedbackView:
    return CandidateFeedbackView(
        aggregate={},
        score=score,
        feedback_status="verified",
        learning_trial_count=completed + failed,
        completed_trial_count=completed,
        failed_trial_count=failed,
        feasible=feasible,
    )


def _candidate(
    candidate_id: str,
    *,
    generation: int,
    source_type: str,
) -> models.CandidateParameterSet:
    return models.CandidateParameterSet(
        id=candidate_id,
        job_id="job_reflection",
        generation_index=generation,
        source_type=source_type,
        parameter_json={"kp_xy": 1.0 + generation / 10},
        optimizer_metadata_json={
            "optimizer_source_evidence_required": source_type == "optimizer",
        },
    )


def test_observed_outcome_compiles_verified_generation_without_causal_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _candidate("cand_baseline", generation=0, source_type="baseline")
    first = _candidate("cand_first", generation=1, source_type="optimizer")
    second = _candidate("cand_second", generation=1, source_type="optimizer")
    candidates = [baseline, first, second]
    receipts = {
        candidate.id: _receipt(candidate, accepted_attempt_count=3) for candidate in candidates
    }
    monkeypatch.setattr(
        harness_context,
        "current_candidate_evidence_receipt",
        lambda candidate: receipts.get(candidate.id),
    )
    feedback = {
        baseline.id: _feedback(1.0, completed=2, failed=0, feasible=True),
        first.id: _feedback(0.7, completed=2, failed=1, feasible=True),
        second.id: _feedback(1.2, completed=3, failed=0, feasible=False),
    }
    execution = harness_context.HarnessExecutionMemory(
        generation=1,
        tool_id="optimizer_portfolio",
        decision_source="model",
        plan_phase="balanced",
        batch_policy="balanced",
        status="dispatched",
        dispatched_candidates=2,
        planned_candidates=2,
    )

    reflected = harness_context._observed_outcome_for_execution(
        execution,
        candidates=candidates,
        feedback_by_id=feedback,
    )

    assert reflected.reflection_status == "verified_complete"
    outcome = reflected.observed_outcome
    assert outcome is not None
    assert outcome.schema_id == "dronedream.harness-decision-observed-outcome/v1"
    assert outcome.cohort_candidate_count == 2
    assert outcome.accepted_attempt_count == 6
    assert outcome.optimizer_learning_trial_count == 6
    assert outcome.domain_failure_trial_count == 1
    assert outcome.feasible_candidate_count == 1
    assert outcome.completed_candidate_rate == pytest.approx(1.0)
    assert outcome.incumbent_score_before == pytest.approx(1.0)
    assert outcome.cohort_best_score == pytest.approx(0.7)
    assert outcome.incumbent_score_after == pytest.approx(0.7)
    assert outcome.observed_absolute_improvement == pytest.approx(0.3)
    assert outcome.observed_relative_improvement == pytest.approx(0.3)
    serialized = reflected.model_dump_json()
    for forbidden in ("cand_baseline", "cand_first", "cand_second", "job_reflection"):
        assert forbidden not in serialized


@pytest.mark.parametrize("tamper", ["count_mismatch", "broken_receipt", "quarantined_feedback"])
def test_observed_outcome_fails_closed_for_incomplete_generation_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    baseline = _candidate("cand_baseline", generation=0, source_type="baseline")
    child = _candidate("cand_child", generation=1, source_type="optimizer")
    candidates = [baseline, child]
    receipts = {
        candidate.id: _receipt(candidate, accepted_attempt_count=2) for candidate in candidates
    }
    if tamper == "broken_receipt":
        receipts.pop(child.id)
    monkeypatch.setattr(
        harness_context,
        "current_candidate_evidence_receipt",
        lambda candidate: receipts.get(candidate.id),
    )
    feedback = {
        baseline.id: _feedback(1.0, completed=2, failed=0, feasible=True),
        child.id: (
            CandidateFeedbackView(
                aggregate={},
                score=None,
                feedback_status="quarantined",
                learning_trial_count=0,
                completed_trial_count=0,
                failed_trial_count=0,
                feasible=None,
            )
            if tamper == "quarantined_feedback"
            else _feedback(0.8, completed=2, failed=0, feasible=True)
        ),
    }
    execution = harness_context.HarnessExecutionMemory(
        generation=1,
        tool_id="cma_es",
        decision_source="model",
        plan_phase="balanced",
        batch_policy="balanced",
        status="dispatched",
        dispatched_candidates=2 if tamper == "count_mismatch" else 1,
        planned_candidates=2 if tamper == "count_mismatch" else 1,
    )

    reflected = harness_context._observed_outcome_for_execution(
        execution,
        candidates=candidates,
        feedback_by_id=feedback,
    )

    assert reflected.reflection_status == "unavailable"
    assert reflected.observed_outcome is None


def test_zero_dispatch_result_never_manufactures_an_outcome() -> None:
    execution = harness_context.HarnessExecutionMemory(
        generation=2,
        tool_id="turbo",
        decision_source="model",
        plan_phase="diversification",
        batch_policy="broad",
        status="search_space_exhausted",
        dispatched_candidates=0,
        planned_candidates=1,
    )

    reflected = harness_context._observed_outcome_for_execution(
        execution,
        candidates=[],
        feedback_by_id={},
    )

    assert reflected.reflection_status == "not_applicable"
    assert reflected.observed_outcome is None
