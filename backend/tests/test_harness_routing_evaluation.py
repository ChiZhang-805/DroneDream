"""Contract tests for the replayable Harness routing development corpus."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from app.orchestration.decision_harness import build_decision_messages
from app.orchestration.harness_context import (
    HARNESS_TOOL_DEFINITIONS,
    HarnessToolId,
)
from app.orchestration.harness_evaluation import (
    compile_routing_eval_snapshot,
    load_routing_eval_cases,
    summarize_routing_predictions,
)

CORPUS = Path(__file__).parent / "fixtures" / "harness_routing_eval_v1.jsonl"


def test_routing_eval_corpus_is_broad_unique_and_schema_valid() -> None:
    cases = load_routing_eval_cases(CORPUS)

    assert len(cases) == 24
    assert len({case.case_id for case in cases}) == len(cases)
    assert {case.category for case in cases} == {
        "cold_start",
        "local_progress",
        "stagnation",
        "constraint_pressure",
        "high_dimension",
        "tight_budget",
        "failure_recovery",
        "mixed_tool_history",
    }
    for case in cases:
        assert set(case.acceptable_tools) <= set(HARNESS_TOOL_DEFINITIONS)


def test_routing_eval_uses_exact_production_prompt_without_answer_leakage() -> None:
    cases = load_routing_eval_cases(CORPUS)

    for case in cases:
        snapshot = compile_routing_eval_snapshot(case)
        system, user = build_decision_messages(snapshot)
        assert snapshot.schema_version == "2.0"
        assert case.case_id not in system
        assert case.case_id not in user
        assert case.rationale not in system
        assert case.rationale not in user
        assert "acceptable_tools" not in user
        assert '"case_id"' not in user
        assert '"registry_version":"2.0"' in user
        assert '"schema_version":"2.0"' in user


def test_routing_eval_grades_complete_predictions_by_category() -> None:
    cases = load_routing_eval_cases(CORPUS)
    predictions = {case.case_id: case.acceptable_tools[0] for case in cases}

    summary = summarize_routing_predictions(cases, predictions)

    assert summary.case_count == 24
    assert summary.passed_count == 24
    assert summary.pass_rate == 1.0
    assert set(summary.category_results) == {case.category for case in cases}
    assert all(
        result["case_count"] == 3 and result["pass_rate"] == 1.0
        for result in summary.category_results.values()
    )


def test_routing_eval_rejects_incomplete_or_unknown_predictions() -> None:
    cases = load_routing_eval_cases(CORPUS)

    with pytest.raises(ValueError, match="exactly cover"):
        summarize_routing_predictions(cases, {})

    wrong = {case.case_id: cast(HarnessToolId, "cma_es") for case in cases}
    summary = summarize_routing_predictions(cases, wrong)
    assert summary.pass_rate < 1.0


def test_routing_eval_compiler_preserves_decision_signals() -> None:
    cases = {case.case_id: case for case in load_routing_eval_cases(CORPUS)}
    case = cases["tight_budget_multifidelity_history"]

    snapshot = compile_routing_eval_snapshot(case)

    assert snapshot.job.parameter_count == 10
    assert snapshot.budget.remaining_trials == 20
    assert snapshot.budget.trials_per_candidate == 10
    assert snapshot.scenarios.training_case_count == 5
    assert snapshot.scenarios.training_replicate_count == 10
    assert snapshot.search.best_score == pytest.approx(0.57)
    assert snapshot.tool_history[0].tool_id == "multi_fidelity_mobo"
    assert snapshot.tool_history[0].best_score == pytest.approx(0.57)

    reflection = compile_routing_eval_snapshot(cases["stagnation_three_generations"])
    assert reflection.decision_memory[0].tool_id == "turbo"
    assert reflection.decision_memory[0].status == "search_space_exhausted"
    assert reflection.decision_memory[0].dispatched_candidates == 0
