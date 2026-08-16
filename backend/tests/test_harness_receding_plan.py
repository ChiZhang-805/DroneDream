"""Deterministic contracts for AURORA's one-generation receding plan."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import ValidationError

from app import models
from app.orchestration.harness_context import (
    HarnessBudgetEvidence,
    HarnessExecutionMemory,
    HarnessObservedDecisionOutcome,
    HarnessPlanningEvidence,
    HarnessSearchSummary,
    _search_summary,
    compile_harness_plan,
)
from app.orchestration.job_manager import (
    _batch_size_for_policy,
    _required_fidelity_for_plan,
)
from app.orchestration.provider_feedback import CandidateFeedbackView


def _budget(
    *,
    remaining_generations: int = 4,
    remaining_full_candidate_capacity: int = 8,
) -> HarnessBudgetEvidence:
    return HarnessBudgetEvidence(
        current_generation=2,
        max_iterations=2 + remaining_generations,
        remaining_generations=remaining_generations,
        used_trials=12,
        max_total_trials=60,
        remaining_trials=48,
        full_trials_per_candidate=6,
        remaining_full_candidate_capacity=remaining_full_candidate_capacity,
    )


def _search(
    *,
    scored_candidate_count: int = 10,
    feasible_candidate_count: int = 6,
    observed_failure_rate: float = 0.05,
    trailing_stagnant_generations: int = 0,
) -> HarnessSearchSummary:
    return HarnessSearchSummary(
        candidate_count=scored_candidate_count,
        scored_candidate_count=scored_candidate_count,
        completed_candidate_count=scored_candidate_count,
        incomplete_candidate_count=0,
        completed_candidate_rate=1.0,
        feasibility_observed_candidate_count=scored_candidate_count,
        feasible_candidate_count=feasible_candidate_count,
        feasible_candidate_rate=(
            feasible_candidate_count / scored_candidate_count if scored_candidate_count else None
        ),
        total_trial_count=scored_candidate_count * 6,
        failed_trial_count=round(scored_candidate_count * 6 * observed_failure_rate),
        observed_failure_rate=observed_failure_rate,
        baseline_score=1.0,
        best_score=0.7,
        relative_improvement_from_baseline=0.3,
        score_gap_to_runner_up=0.05,
        relative_score_gap_to_runner_up=0.0714285714,
        trailing_stagnant_generations=trailing_stagnant_generations,
    )


def _verified_memory(
    *,
    domain_failures: int = 0,
    learning_trials: int = 8,
    improvement: float | None = 0.2,
) -> tuple[HarnessExecutionMemory, ...]:
    return (
        HarnessExecutionMemory(
            generation=2,
            tool_id="optimizer_portfolio",
            decision_source="model",
            plan_phase="balanced",
            batch_policy="balanced",
            status="dispatched",
            dispatched_candidates=2,
            planned_candidates=2,
            reflection_status="verified_complete",
            observed_outcome=HarnessObservedDecisionOutcome(
                cohort_candidate_count=2,
                accepted_attempt_count=learning_trials,
                optimizer_learning_trial_count=learning_trials,
                domain_failure_trial_count=domain_failures,
                feasible_candidate_count=1,
                completed_candidate_rate=1.0,
                incumbent_score_before=1.0,
                cohort_best_score=(1.0 - improvement if improvement is not None else 1.0),
                incumbent_score_after=(1.0 - improvement if improvement is not None else 1.0),
                observed_absolute_improvement=improvement,
                observed_relative_improvement=improvement,
            ),
        ),
    )


def test_infeasible_score_improvements_do_not_reset_safe_stagnation() -> None:
    candidates: list[models.CandidateParameterSet] = []
    feedback_by_id: dict[str, CandidateFeedbackView] = {}
    for generation, score, feasible in (
        (0, 1.0, True),
        (1, 0.8, True),
        (2, 0.1, False),
        (3, 0.05, False),
    ):
        candidate_id = f"candidate-{generation}"
        candidates.append(
            models.CandidateParameterSet(
                id=candidate_id,
                job_id="job-stagnation",
                generation_index=generation,
                parameter_json={"kp_xy": 1.0 + generation / 10},
            )
        )
        feedback_by_id[candidate_id] = CandidateFeedbackView(
            aggregate={"feasible": feasible},
            score=score,
            feedback_status="legacy_unsealed",
            learning_trial_count=1,
            completed_trial_count=1,
            failed_trial_count=0,
            feasible=feasible,
        )

    summary = _search_summary(candidates, feedback_by_id)

    assert summary.best_score == pytest.approx(0.8)
    assert summary.trailing_stagnant_generations == 2
    assert [item.best_score for item in summary.best_score_by_generation] == [
        1.0,
        0.8,
        0.8,
        0.8,
    ]


@pytest.mark.parametrize(
    ("budget", "search", "memory", "expected_phase", "expected_policy", "reason"),
    [
        (
            _budget(remaining_generations=1),
            _search(observed_failure_rate=0.8),
            _verified_memory(domain_failures=8),
            "verification",
            "conservative",
            "final_generation",
        ),
        (
            _budget(),
            _search(),
            _verified_memory(domain_failures=3),
            "recovery",
            "conservative",
            "high_domain_failure_rate",
        ),
        (
            _budget(),
            _search(scored_candidate_count=2, feasible_candidate_count=0),
            (),
            "exploration",
            "broad",
            "insufficient_scored_history",
        ),
        (
            _budget(),
            _search(trailing_stagnant_generations=3),
            (),
            "diversification",
            "broad",
            "stagnation_detected",
        ),
        (
            _budget(),
            _search(),
            _verified_memory(improvement=0.2),
            "refinement",
            "balanced",
            "recent_verified_improvement",
        ),
        (
            _budget(),
            _search(),
            (),
            "balanced",
            "balanced",
            "stable_progress",
        ),
    ],
)
def test_compile_harness_plan_is_bounded_and_precedence_ordered(
    budget: HarnessBudgetEvidence,
    search: HarnessSearchSummary,
    memory: tuple[HarnessExecutionMemory, ...],
    expected_phase: str,
    expected_policy: str,
    reason: str,
) -> None:
    plan = compile_harness_plan(
        parameter_count=4,
        budget=budget,
        search=search,
        decision_memory=memory,
    )

    assert plan.phase == expected_phase
    assert plan.batch_policy == expected_policy
    assert reason in plan.reason_codes
    assert plan.horizon_generations == 1
    assert plan.replan_after_generation is True


@pytest.mark.parametrize(
    ("safe_maximum", "policy", "expected"),
    [
        (4, "conservative", 1),
        (4, "balanced", 2),
        (3, "balanced", 2),
        (4, "broad", 4),
        (1, "broad", 1),
    ],
)
def test_batch_policy_translates_to_a_locally_bounded_cohort(
    safe_maximum: int,
    policy: Literal["conservative", "balanced", "broad"],
    expected: int,
) -> None:
    assert _batch_size_for_policy(safe_maximum, policy) == expected


def test_plan_model_rejects_policy_escalation() -> None:
    with pytest.raises(ValidationError, match="inconsistent"):
        HarnessPlanningEvidence(
            phase="recovery",
            batch_policy="broad",
            reason_codes=("high_domain_failure_rate",),
        )


def test_batch_policy_rejects_an_empty_safe_capacity() -> None:
    with pytest.raises(ValueError, match="positive"):
        _batch_size_for_policy(0, "conservative")


@pytest.mark.parametrize(
    (
        "can_schedule_reduced_fidelity",
        "plan_phase",
        "has_full_optimizer_evidence",
        "generation_index",
        "max_iterations",
        "full_candidate_capacity",
        "expected",
    ),
    [
        (True, "verification", True, 3, 8, 6, 1.0),
        (True, "verification", False, 3, 8, 6, 1.0),
        (True, "balanced", False, 8, 8, 6, 1.0),
        (True, "balanced", False, 3, 8, 1, 1.0),
        (True, "balanced", True, 3, 8, 6, None),
        (False, "verification", False, 8, 8, 1, None),
    ],
)
def test_verification_plan_forces_full_fidelity_before_dispatch(
    can_schedule_reduced_fidelity: bool,
    plan_phase: str,
    has_full_optimizer_evidence: bool,
    generation_index: int,
    max_iterations: int,
    full_candidate_capacity: int,
    expected: float | None,
) -> None:
    assert (
        _required_fidelity_for_plan(
            can_schedule_reduced_fidelity=can_schedule_reduced_fidelity,
            plan_phase=plan_phase,  # type: ignore[arg-type]
            has_full_optimizer_evidence=has_full_optimizer_evidence,
            generation_index=generation_index,
            max_iterations=max_iterations,
            full_candidate_capacity=full_candidate_capacity,
        )
        == expected
    )
