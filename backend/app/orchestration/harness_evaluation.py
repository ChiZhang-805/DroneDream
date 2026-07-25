"""Replayable development diagnostics for Harness optimizer-tool routing.

This module does not claim that hand-authored cases are a confirmatory benchmark.
It provides a versioned, secretless corpus and grader for detecting regressions
in context compilation, tool discrimination, and model/router changes before a
locked simulator campaign is run.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.orchestration.harness_context import (
    HARNESS_TOOL_DEFINITIONS,
    HarnessBudgetEvidence,
    HarnessCandidateEvidence,
    HarnessEvidenceSnapshot,
    HarnessExecutionMemory,
    HarnessGenerationBest,
    HarnessJobEvidence,
    HarnessScenarioEvidence,
    HarnessSearchSummary,
    HarnessToolHistory,
    HarnessToolId,
)

HARNESS_ROUTING_EVAL_SCHEMA_VERSION = "1.0"
HARNESS_ROUTING_REPORT_SCHEMA_VERSION = "1.1"
HARNESS_ROUTING_MIN_PASS_RATE = 0.75
HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE = 2 / 3
HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT = 0.15

HarnessEvalCategory = Literal[
    "cold_start",
    "local_progress",
    "stagnation",
    "constraint_pressure",
    "high_dimension",
    "tight_budget",
    "failure_recovery",
    "mixed_tool_history",
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HarnessEvalToolHistory(_ClosedModel):
    tool_id: HarnessToolId
    candidate_count: int = Field(ge=1, le=1000)
    feasible_candidate_count: int = Field(ge=0)
    best_score: float | None = None
    failed_trial_count: int = Field(ge=0)
    last_generation: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_feasible_count(self) -> HarnessEvalToolHistory:
        if self.feasible_candidate_count > self.candidate_count:
            raise ValueError("feasible_candidate_count cannot exceed candidate_count")
        return self


class HarnessRoutingStimulus(_ClosedModel):
    parameter_count: int = Field(ge=1, le=64)
    objective_count: int = Field(default=1, ge=1, le=16)
    constraint_count: int = Field(default=0, ge=0, le=32)
    current_generation: int = Field(default=1, ge=0, le=1000)
    max_iterations: int = Field(default=8, ge=1, le=1000)
    remaining_trials: int = Field(default=48, ge=1, le=100_000)
    trials_per_candidate: int = Field(default=4, ge=1, le=1000)
    training_case_count: int = Field(default=1, ge=1, le=64)
    training_replicate_count: int = Field(default=4, ge=1, le=6400)
    scored_candidate_count: int = Field(default=1, ge=1, le=10_000)
    feasible_candidate_count: int = Field(default=1, ge=0, le=10_000)
    observed_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    baseline_score: float = 1.0
    best_score: float = 1.0
    trailing_stagnant_generations: int = Field(default=0, ge=0, le=1000)
    tool_history: tuple[HarnessEvalToolHistory, ...] = ()
    last_execution: HarnessExecutionMemory | None = None

    @model_validator(mode="after")
    def _validate_counts_and_budget(self) -> HarnessRoutingStimulus:
        if self.current_generation > self.max_iterations:
            raise ValueError("current_generation cannot exceed max_iterations")
        if self.feasible_candidate_count > self.scored_candidate_count:
            raise ValueError("feasible_candidate_count cannot exceed scored_candidate_count")
        return self


class HarnessRoutingEvalCase(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    category: HarnessEvalCategory
    stimulus: HarnessRoutingStimulus
    acceptable_tools: tuple[HarnessToolId, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _validate_tools(self) -> HarnessRoutingEvalCase:
        if len(set(self.acceptable_tools)) != len(self.acceptable_tools):
            raise ValueError("acceptable_tools must be unique")
        return self


class HarnessRoutingGrade(_ClosedModel):
    case_id: str
    category: HarnessEvalCategory
    selected_tool: HarnessToolId
    acceptable: bool
    acceptable_tools: tuple[HarnessToolId, ...]


class HarnessRoutingEvalSummary(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    category_results: dict[str, dict[str, float | int]]
    grades: tuple[HarnessRoutingGrade, ...]


class HarnessConstantToolBaseline(_ClosedModel):
    tool_id: HarnessToolId
    passed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)


class HarnessRoutingBaselineSummary(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    case_count: int = Field(ge=1)
    tool_count: int = Field(ge=1)
    uniform_random_expected_passed_count: float = Field(ge=0.0)
    uniform_random_expected_pass_rate: float = Field(ge=0.0, le=1.0)
    best_constant_passed_count: int = Field(ge=0)
    best_constant_pass_rate: float = Field(ge=0.0, le=1.0)
    best_constant_tools: tuple[HarnessToolId, ...] = Field(min_length=1)
    constant_tool_results: tuple[HarnessConstantToolBaseline, ...] = Field(min_length=1)


class HarnessRoutingQualification(_ClosedModel):
    qualified: bool
    minimum_pass_rate: float = Field(ge=0.0, le=1.0)
    minimum_category_pass_rate: float = Field(ge=0.0, le=1.0)
    minimum_lift_over_best_constant: float = Field(ge=0.0, le=1.0)
    failed_requirements: tuple[str, ...] = ()


class HarnessRoutingEvalReport(_ClosedModel):
    schema_version: Literal["1.1"] = "1.1"
    predictions: HarnessRoutingEvalSummary
    baselines: HarnessRoutingBaselineSummary
    absolute_lift_over_uniform_random: float
    absolute_lift_over_best_constant: float
    beats_best_constant: bool
    qualification: HarnessRoutingQualification


def load_routing_eval_cases(path: Path) -> tuple[HarnessRoutingEvalCase, ...]:
    """Load and strictly validate a JSONL development corpus."""

    cases: list[HarnessRoutingEvalCase] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                case = HarnessRoutingEvalCase.model_validate(payload)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid Harness routing case at line {line_number}") from exc
            if case.case_id in seen_ids:
                raise ValueError(f"duplicate Harness routing case_id: {case.case_id}")
            seen_ids.add(case.case_id)
            cases.append(case)
    if not cases:
        raise ValueError("Harness routing corpus is empty")
    return tuple(cases)


def compile_routing_eval_snapshot(
    case: HarnessRoutingEvalCase,
) -> HarnessEvidenceSnapshot:
    """Compile a diagnostic stimulus into the production evidence contract."""

    stimulus = case.stimulus
    observed_best_score = min(
        stimulus.baseline_score,
        stimulus.best_score,
    )
    max_total_trials = (
        stimulus.current_generation * stimulus.trials_per_candidate + stimulus.remaining_trials
    )
    used_trials = max_total_trials - stimulus.remaining_trials
    relative_improvement = (
        (stimulus.baseline_score - observed_best_score) / abs(stimulus.baseline_score)
        if abs(stimulus.baseline_score) > 1e-12
        else None
    )
    generation_best: list[HarnessGenerationBest] = [
        HarnessGenerationBest(generation=0, best_score=stimulus.baseline_score)
    ]
    if stimulus.current_generation > 0:
        generation_best.append(
            HarnessGenerationBest(
                generation=stimulus.current_generation,
                best_score=stimulus.best_score,
            )
        )
    candidates = (
        HarnessCandidateEvidence(
            generation=0,
            source_type="baseline",
            is_baseline=True,
            aggregated_score=stimulus.baseline_score,
            metrics={"aggregated_score": stimulus.baseline_score},
            trial_count=stimulus.trials_per_candidate,
            completed_trial_count=stimulus.trials_per_candidate,
            failed_trial_count=0,
        ),
        HarnessCandidateEvidence(
            generation=stimulus.current_generation,
            source_type="optimizer",
            is_baseline=False,
            aggregated_score=stimulus.best_score,
            metrics={
                "aggregated_score": stimulus.best_score,
                "feasible": stimulus.feasible_candidate_count > 0,
            },
            trial_count=stimulus.trials_per_candidate,
            completed_trial_count=stimulus.trials_per_candidate,
            failed_trial_count=round(
                stimulus.observed_failure_rate * stimulus.trials_per_candidate
            ),
        ),
    )
    tool_history = tuple(
        HarnessToolHistory(
            tool_id=item.tool_id,
            candidate_count=item.candidate_count,
            completed_candidate_count=item.candidate_count,
            feasible_candidate_count=item.feasible_candidate_count,
            total_trial_count=item.candidate_count * stimulus.trials_per_candidate,
            failed_trial_count=item.failed_trial_count,
            best_score=item.best_score,
            last_generation=item.last_generation,
        )
        for item in stimulus.tool_history
    )
    ordered_scores = sorted(
        (stimulus.baseline_score, stimulus.best_score)
    )
    score_gap = ordered_scores[1] - ordered_scores[0]
    relative_score_gap = (
        score_gap / abs(ordered_scores[0])
        if abs(ordered_scores[0]) > 1e-12
        else None
    )
    return HarnessEvidenceSnapshot(
        job=HarnessJobEvidence(
            objective_profile="robust",
            track_type="custom",
            parameter_count=stimulus.parameter_count,
            parameter_names=(),
            objective_count=stimulus.objective_count,
            constraint_count=stimulus.constraint_count,
            robust_aggregation="mean",
        ),
        budget=HarnessBudgetEvidence(
            current_generation=stimulus.current_generation,
            max_iterations=stimulus.max_iterations,
            remaining_generations=(stimulus.max_iterations - stimulus.current_generation),
            used_trials=used_trials,
            max_total_trials=max_total_trials,
            remaining_trials=stimulus.remaining_trials,
            full_trials_per_candidate=stimulus.trials_per_candidate,
            remaining_full_candidate_capacity=(
                stimulus.remaining_trials // stimulus.trials_per_candidate
            ),
        ),
        scenarios=HarnessScenarioEvidence(
            training_case_count=stimulus.training_case_count,
            validation_case_count=1,
            training_replicate_count=stimulus.training_replicate_count,
            validation_replicate_count=1,
            training_type_counts={},
            common_random_numbers=True,
        ),
        search=HarnessSearchSummary(
            candidate_count=stimulus.scored_candidate_count,
            scored_candidate_count=stimulus.scored_candidate_count,
            completed_candidate_count=stimulus.scored_candidate_count,
            incomplete_candidate_count=0,
            completed_candidate_rate=1.0,
            feasibility_observed_candidate_count=(
                stimulus.scored_candidate_count
            ),
            feasible_candidate_count=stimulus.feasible_candidate_count,
            feasible_candidate_rate=(
                stimulus.feasible_candidate_count
                / stimulus.scored_candidate_count
            ),
            total_trial_count=(stimulus.scored_candidate_count * stimulus.trials_per_candidate),
            failed_trial_count=round(
                stimulus.observed_failure_rate
                * stimulus.scored_candidate_count
                * stimulus.trials_per_candidate
            ),
            observed_failure_rate=stimulus.observed_failure_rate,
            baseline_score=stimulus.baseline_score,
            best_score=observed_best_score,
            relative_improvement_from_baseline=relative_improvement,
            score_gap_to_runner_up=score_gap,
            relative_score_gap_to_runner_up=relative_score_gap,
            trailing_stagnant_generations=(stimulus.trailing_stagnant_generations),
            best_score_by_generation=tuple(generation_best),
        ),
        tool_history=tool_history,
        decision_memory=((stimulus.last_execution,) if stimulus.last_execution is not None else ()),
        candidates=candidates,
        candidate_history_total=stimulus.scored_candidate_count,
        candidate_history_included=len(candidates),
    )


def grade_routing_decision(
    case: HarnessRoutingEvalCase,
    selected_tool: HarnessToolId,
) -> HarnessRoutingGrade:
    if selected_tool not in HARNESS_TOOL_DEFINITIONS:
        raise ValueError(f"unknown Harness tool: {selected_tool}")
    return HarnessRoutingGrade(
        case_id=case.case_id,
        category=case.category,
        selected_tool=selected_tool,
        acceptable=selected_tool in case.acceptable_tools,
        acceptable_tools=case.acceptable_tools,
    )


def summarize_routing_predictions(
    cases: tuple[HarnessRoutingEvalCase, ...],
    predictions: dict[str, HarnessToolId],
) -> HarnessRoutingEvalSummary:
    """Grade a complete set of case-id-to-tool predictions."""

    expected_ids = {case.case_id for case in cases}
    if set(predictions) != expected_ids:
        missing = sorted(expected_ids - set(predictions))
        extra = sorted(set(predictions) - expected_ids)
        raise ValueError(
            f"predictions must exactly cover the corpus; missing={missing}, extra={extra}"
        )
    grades = tuple(grade_routing_decision(case, predictions[case.case_id]) for case in cases)
    category_totals = Counter(grade.category for grade in grades)
    category_passes = Counter(grade.category for grade in grades if grade.acceptable)
    category_results: dict[str, dict[str, float | int]] = {
        str(category): {
            "case_count": category_totals[category],
            "passed_count": category_passes[category],
            "pass_rate": (category_passes[category] / category_totals[category]),
        }
        for category in sorted(category_totals)
    }
    passed = sum(1 for grade in grades if grade.acceptable)
    return HarnessRoutingEvalSummary(
        case_count=len(grades),
        passed_count=passed,
        pass_rate=passed / len(grades) if grades else 0.0,
        category_results=category_results,
        grades=grades,
    )


def summarize_routing_baselines(
    cases: tuple[HarnessRoutingEvalCase, ...],
) -> HarnessRoutingBaselineSummary:
    """Compute non-adaptive baselines without using case categories or rationales."""

    if not cases:
        raise ValueError("cannot summarize routing baselines for an empty corpus")
    tool_ids = tuple(HARNESS_TOOL_DEFINITIONS)
    constant_result_items: list[HarnessConstantToolBaseline] = []
    for tool_id in tool_ids:
        passed = sum(1 for case in cases if tool_id in case.acceptable_tools)
        constant_result_items.append(
            HarnessConstantToolBaseline(
                tool_id=tool_id,
                passed_count=passed,
                pass_rate=passed / len(cases),
            )
        )
    constant_results = tuple(constant_result_items)
    best_passed = max(result.passed_count for result in constant_results)
    expected_random_passed = sum(
        len(case.acceptable_tools) / len(tool_ids) for case in cases
    )
    return HarnessRoutingBaselineSummary(
        case_count=len(cases),
        tool_count=len(tool_ids),
        uniform_random_expected_passed_count=expected_random_passed,
        uniform_random_expected_pass_rate=expected_random_passed / len(cases),
        best_constant_passed_count=best_passed,
        best_constant_pass_rate=best_passed / len(cases),
        best_constant_tools=tuple(
            result.tool_id
            for result in constant_results
            if result.passed_count == best_passed
        ),
        constant_tool_results=constant_results,
    )


def build_routing_eval_report(
    cases: tuple[HarnessRoutingEvalCase, ...],
    predictions: dict[str, HarnessToolId],
) -> HarnessRoutingEvalReport:
    """Compare complete predictions against chance and best constant routing."""

    summary = summarize_routing_predictions(cases, predictions)
    baselines = summarize_routing_baselines(cases)
    absolute_lift_over_best_constant = (
        summary.pass_rate - baselines.best_constant_pass_rate
    )
    failed_requirements: list[str] = []
    if summary.pass_rate < HARNESS_ROUTING_MIN_PASS_RATE:
        failed_requirements.append("overall_pass_rate")
    if (
        absolute_lift_over_best_constant
        < HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT
    ):
        failed_requirements.append("lift_over_best_constant")
    failed_requirements.extend(
        f"category_pass_rate:{category}"
        for category, result in sorted(summary.category_results.items())
        if float(result["pass_rate"]) < HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE
    )
    return HarnessRoutingEvalReport(
        predictions=summary,
        baselines=baselines,
        absolute_lift_over_uniform_random=(
            summary.pass_rate - baselines.uniform_random_expected_pass_rate
        ),
        absolute_lift_over_best_constant=absolute_lift_over_best_constant,
        beats_best_constant=summary.pass_rate > baselines.best_constant_pass_rate,
        qualification=HarnessRoutingQualification(
            qualified=not failed_requirements,
            minimum_pass_rate=HARNESS_ROUTING_MIN_PASS_RATE,
            minimum_category_pass_rate=HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE,
            minimum_lift_over_best_constant=(
                HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT
            ),
            failed_requirements=tuple(failed_requirements),
        ),
    )


__all__ = [
    "HARNESS_ROUTING_EVAL_SCHEMA_VERSION",
    "HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE",
    "HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT",
    "HARNESS_ROUTING_MIN_PASS_RATE",
    "HARNESS_ROUTING_REPORT_SCHEMA_VERSION",
    "HarnessRoutingBaselineSummary",
    "HarnessRoutingEvalCase",
    "HarnessRoutingEvalReport",
    "HarnessRoutingQualification",
    "HarnessRoutingEvalSummary",
    "HarnessRoutingGrade",
    "HarnessRoutingStimulus",
    "build_routing_eval_report",
    "compile_routing_eval_snapshot",
    "grade_routing_decision",
    "load_routing_eval_cases",
    "summarize_routing_baselines",
    "summarize_routing_predictions",
]
