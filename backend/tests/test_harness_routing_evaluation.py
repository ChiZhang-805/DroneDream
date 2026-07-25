"""Contract tests for the replayable Harness routing development corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from app.orchestration.decision_harness import build_decision_messages
from app.orchestration.harness_context import (
    HARNESS_TOOL_DEFINITIONS,
    HarnessToolId,
)
from app.orchestration.harness_evaluation import (
    build_routing_eval_report,
    compile_routing_eval_snapshot,
    grade_routing_prediction_artifact,
    load_routing_eval_cases,
    load_routing_prediction_artifact,
    routing_corpus_sha256,
    routing_prompt_suite_sha256,
    summarize_routing_baselines,
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
        assert snapshot.schema_version == "2.3"
        assert case.case_id not in system
        assert case.case_id not in user
        assert case.rationale not in system
        assert case.rationale not in user
        assert "acceptable_tools" not in user
        assert '"case_id"' not in user
        assert '"registry_version":"2.0"' in user
        assert '"schema_version":"2.3"' in user


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


def test_routing_eval_reports_non_adaptive_baselines_and_prediction_lift() -> None:
    cases = load_routing_eval_cases(CORPUS)
    baselines = summarize_routing_baselines(cases)
    by_tool = {result.tool_id: result for result in baselines.constant_tool_results}

    assert baselines.case_count == 24
    assert baselines.tool_count == 8
    assert baselines.uniform_random_expected_passed_count == pytest.approx(5.625)
    assert baselines.uniform_random_expected_pass_rate == pytest.approx(0.234375)
    assert baselines.best_constant_tools == ("optimizer_portfolio",)
    assert baselines.best_constant_passed_count == 14
    assert baselines.best_constant_pass_rate == pytest.approx(14 / 24)
    assert by_tool["optimizer_portfolio"].passed_count == 14

    predictions = {case.case_id: case.acceptable_tools[0] for case in cases}
    report = build_routing_eval_report(cases, predictions)

    assert report.predictions.pass_rate == 1.0
    assert report.absolute_lift_over_uniform_random == pytest.approx(0.765625)
    assert report.absolute_lift_over_best_constant == pytest.approx(10 / 24)
    assert report.beats_best_constant is True
    assert report.schema_version == "1.1"
    assert report.qualification.qualified is True
    assert report.qualification.failed_requirements == ()

    constant_predictions = {
        case.case_id: cast(HarnessToolId, "optimizer_portfolio")
        for case in cases
    }
    constant_report = build_routing_eval_report(cases, constant_predictions)
    assert constant_report.qualification.qualified is False
    assert "overall_pass_rate" in (
        constant_report.qualification.failed_requirements
    )
    assert "lift_over_best_constant" in (
        constant_report.qualification.failed_requirements
    )
    assert any(
        requirement.startswith("category_pass_rate:")
        for requirement in constant_report.qualification.failed_requirements
    )


def test_routing_eval_rejects_incomplete_or_unknown_predictions() -> None:
    cases = load_routing_eval_cases(CORPUS)

    with pytest.raises(ValueError, match="exactly cover"):
        summarize_routing_predictions(cases, {})

    wrong = {case.case_id: cast(HarnessToolId, "cma_es") for case in cases}
    summary = summarize_routing_predictions(cases, wrong)
    assert summary.pass_rate < 1.0


def test_prediction_artifact_binds_corpus_prompts_versions_and_model(
    tmp_path,
) -> None:
    cases = load_routing_eval_cases(CORPUS)
    payload = {
        "schema_version": "1.0",
        "corpus_sha256": routing_corpus_sha256(cases),
        "prompt_suite_sha256": routing_prompt_suite_sha256(cases),
        "evidence_schema_version": "2.3",
        "tool_registry_version": "2.0",
        "prompt_template_version": "1.0",
        "provider": "openai",
        "model_snapshot": "gpt-test-snapshot",
        "generation_config": {
            "temperature": 0.0,
            "seed": 20260726,
            "response_format": "json_schema",
        },
        "predictions": {
            case.case_id: {
                "selected_tool": case.acceptable_tools[0],
                "rationale": "Bounded test rationale.",
            }
            for case in cases
        },
    }
    artifact_path = tmp_path / "predictions.json"
    artifact_path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )

    artifact = load_routing_prediction_artifact(artifact_path, cases)
    report = grade_routing_prediction_artifact(artifact, cases)

    assert artifact.model_snapshot == "gpt-test-snapshot"
    assert report.predictions.pass_rate == 1.0
    assert report.qualification.qualified is True

    payload["corpus_sha256"] = "0" * 64
    artifact_path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="corpus_sha256"):
        load_routing_prediction_artifact(artifact_path, cases)

    artifact_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        load_routing_prediction_artifact(artifact_path, cases)


def test_routing_eval_compiler_preserves_decision_signals() -> None:
    cases = {case.case_id: case for case in load_routing_eval_cases(CORPUS)}
    case = cases["tight_budget_multifidelity_history"]

    snapshot = compile_routing_eval_snapshot(case)

    assert snapshot.job.parameter_count == 10
    assert snapshot.budget.remaining_trials == 20
    assert snapshot.budget.full_trials_per_candidate == 10
    assert snapshot.budget.remaining_full_candidate_capacity == 2
    assert snapshot.scenarios.training_case_count == 5
    assert snapshot.scenarios.training_replicate_count == 10
    assert snapshot.search.best_score == pytest.approx(0.57)
    assert snapshot.tool_history[0].tool_id == "multi_fidelity_mobo"
    assert snapshot.tool_history[0].best_score == pytest.approx(0.57)

    reflection = compile_routing_eval_snapshot(cases["stagnation_three_generations"])
    assert reflection.decision_memory[0].tool_id == "turbo"
    assert reflection.decision_memory[0].status == "search_space_exhausted"
    assert reflection.decision_memory[0].dispatched_candidates == 0

    no_feasible = compile_routing_eval_snapshot(
        cases["constraint_pressure_no_feasible_points"]
    )
    assert no_feasible.search.best_score == pytest.approx(1.0)
    assert no_feasible.search.relative_improvement_from_baseline == pytest.approx(0.0)
    assert no_feasible.search.feasibility_observed_candidate_count == 16
    assert no_feasible.search.feasible_candidate_rate == pytest.approx(0.0)
