"""Contract tests for the replayable Harness routing development corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from app.orchestration.decision_harness import build_decision_messages
from app.orchestration.harness_context import (
    HARNESS_TOOL_DEFINITIONS,
    HarnessExecutionMemory,
    HarnessObservedDecisionOutcome,
    HarnessToolId,
    eligible_harness_tools,
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
FROZEN_GPT_4_1 = (
    Path(__file__).parents[1] / "evaluation_artifacts" / "harness-routing-gpt-4.1-2025-04-14.json"
)


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
        eligible = set(eligible_harness_tools(compile_routing_eval_snapshot(case)))
        assert set(case.acceptable_tools) & eligible


def test_routing_eval_uses_exact_production_prompt_without_answer_leakage() -> None:
    cases = load_routing_eval_cases(CORPUS)

    for case in cases:
        snapshot = compile_routing_eval_snapshot(case)
        system, user = build_decision_messages(snapshot)
        assert snapshot.schema_version == "2.5"
        assert case.case_id not in system
        assert case.case_id not in user
        assert case.rationale not in system
        assert case.rationale not in user
        assert "acceptable_tools" not in user
        assert '"case_id"' not in user
        assert '"registry_version":"2.1"' in user
        assert '"schema_version":"2.5"' in user
        payload = json.loads(user)
        assert tuple(
            tool["tool_id"] for tool in payload["tool_manifest"]["tools"]
        ) == eligible_harness_tools(snapshot)


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
        case.case_id: cast(HarnessToolId, "optimizer_portfolio") for case in cases
    }
    constant_report = build_routing_eval_report(cases, constant_predictions)
    assert constant_report.qualification.qualified is False
    assert "overall_pass_rate" in (constant_report.qualification.failed_requirements)
    assert "lift_over_best_constant" in (constant_report.qualification.failed_requirements)
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
        "evidence_schema_version": "2.5",
        "tool_registry_version": "2.1",
        "prompt_template_version": "1.2",
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


def test_previous_online_provider_freeze_is_rejected_after_contract_upgrade() -> None:
    cases = load_routing_eval_cases(CORPUS)

    with pytest.raises(ValueError, match="invalid Harness routing prediction artifact"):
        load_routing_prediction_artifact(FROZEN_GPT_4_1, cases)


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

    no_feasible = compile_routing_eval_snapshot(cases["constraint_pressure_no_feasible_points"])
    assert no_feasible.search.best_score == pytest.approx(1.0)
    assert no_feasible.search.relative_improvement_from_baseline == pytest.approx(0.0)
    assert no_feasible.search.feasibility_observed_candidate_count == 16
    assert no_feasible.search.feasible_candidate_rate == pytest.approx(0.0)


def test_routing_eval_prompt_preserves_verified_observational_reflection() -> None:
    case = load_routing_eval_cases(CORPUS)[0]
    outcome = HarnessObservedDecisionOutcome(
        cohort_candidate_count=4,
        accepted_attempt_count=16,
        optimizer_learning_trial_count=12,
        domain_failure_trial_count=1,
        feasible_candidate_count=3,
        completed_candidate_rate=1.0,
        incumbent_score_before=1.0,
        cohort_best_score=0.6,
        incumbent_score_after=0.6,
        observed_absolute_improvement=0.4,
        observed_relative_improvement=0.4,
    )
    execution = HarnessExecutionMemory(
        generation=1,
        tool_id="optimizer_portfolio",
        decision_source="model",
        status="dispatched",
        dispatched_candidates=4,
        reflection_status="verified_complete",
        observed_outcome=outcome,
    )
    snapshot = compile_routing_eval_snapshot(
        case.model_copy(
            update={
                "stimulus": case.stimulus.model_copy(
                    update={
                        "current_generation": 1,
                        "last_execution": execution,
                    }
                )
            }
        )
    )

    system, user = build_decision_messages(snapshot)
    payload = json.loads(user)
    reflected = payload["evidence"]["decision_memory"][0]

    assert reflected["reflection_status"] == "verified_complete"
    assert reflected["observed_outcome"] == outcome.model_dump(mode="json")
    assert "not causal rewards" in system
    assert "do not infer causality" in payload["instructions"]
    assert "candidate_id" not in user
    assert "decision_id" not in user
    assert '"seed"' not in user
    assert "holdout" not in user


def test_eight_verified_reflections_remain_bounded() -> None:
    case = load_routing_eval_cases(CORPUS)[0]
    snapshot = compile_routing_eval_snapshot(case)
    memory = tuple(
        HarnessExecutionMemory(
            generation=generation,
            tool_id="optimizer_portfolio",
            decision_source="deterministic_fallback",
            status="dispatched",
            dispatched_candidates=4,
            fallback_reason="missing_api_key",
            reflection_status="verified_complete",
            observed_outcome=HarnessObservedDecisionOutcome(
                cohort_candidate_count=4,
                accepted_attempt_count=16,
                optimizer_learning_trial_count=12,
                domain_failure_trial_count=generation % 3,
                feasible_candidate_count=3,
                completed_candidate_rate=1.0,
                incumbent_score_before=1.0,
                cohort_best_score=0.9,
                incumbent_score_after=0.9,
                observed_absolute_improvement=0.1,
                observed_relative_improvement=0.1,
            ),
        )
        for generation in range(1, 9)
    )

    system, user = build_decision_messages(
        snapshot.model_copy(update={"decision_memory": memory})
    )

    assert len((system + user).encode("utf-8")) < 32_768
    assert user.count("dronedream.harness-decision-observed-outcome/v1") == 8


def test_tool_eligibility_changes_only_at_explicit_precondition_boundaries() -> None:
    cases = load_routing_eval_cases(CORPUS)
    base = compile_routing_eval_snapshot(cases[0])

    def tools(**updates: object) -> set[HarnessToolId]:
        snapshot = base.model_copy(
            update={
                "job": base.job.model_copy(
                    update={
                        "parameter_count": 11,
                        "objective_count": 1,
                        "constraint_count": 0,
                    }
                ),
                "budget": base.budget.model_copy(update={"current_generation": 0}),
                "scenarios": base.scenarios.model_copy(update={"training_replicate_count": 1}),
                "search": base.search.model_copy(
                    update={
                        "scored_candidate_count": 3,
                        "feasible_candidate_count": 1,
                        "trailing_stagnant_generations": 0,
                    }
                ),
                **updates,
            }
        )
        return set(eligible_harness_tools(snapshot))

    assert "saasbo" not in tools()
    assert "saasbo" in tools(
        job=base.job.model_copy(
            update={
                "parameter_count": 12,
                "objective_count": 1,
                "constraint_count": 0,
            }
        )
    )
    assert "constrained_mobo" in tools(
        job=base.job.model_copy(
            update={
                "parameter_count": 11,
                "objective_count": 1,
                "constraint_count": 1,
            }
        )
    )
    assert "multi_fidelity_mobo" in tools(
        scenarios=base.scenarios.model_copy(update={"training_replicate_count": 2})
    )
    assert "turbo" not in tools()
    assert "turbo" in tools(
        search=base.search.model_copy(
            update={
                "scored_candidate_count": 4,
                "feasible_candidate_count": 1,
                "trailing_stagnant_generations": 0,
            }
        )
    )
    assert "surrogate_cma_es" not in tools()
    assert "surrogate_cma_es" in tools(
        search=base.search.model_copy(
            update={
                "scored_candidate_count": 6,
                "feasible_candidate_count": 1,
                "trailing_stagnant_generations": 0,
            }
        )
    )
    assert "bipop_cma_es" not in tools(
        budget=base.budget.model_copy(update={"current_generation": 1}),
        search=base.search.model_copy(
            update={
                "scored_candidate_count": 3,
                "feasible_candidate_count": 1,
                "trailing_stagnant_generations": 2,
            }
        ),
    )
    assert "bipop_cma_es" in tools(
        budget=base.budget.model_copy(update={"current_generation": 2}),
        search=base.search.model_copy(
            update={
                "scored_candidate_count": 3,
                "feasible_candidate_count": 1,
                "trailing_stagnant_generations": 2,
            }
        ),
    )
