"""Replayable development diagnostics for Harness optimizer-tool routing.

This module does not claim that hand-authored cases are a confirmatory benchmark.
It provides a versioned, secretless corpus and grader for detecting regressions
in context compilation, tool discrimination, and model/router changes before a
locked simulator campaign is run.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.orchestration.decision_harness import (
    HARNESS_PROMPT_TEMPLATE_VERSION,
    build_decision_messages,
)
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_DEFINITIONS,
    HARNESS_TOOL_REGISTRY_VERSION,
    HarnessBudgetEvidence,
    HarnessCandidateEvidence,
    HarnessEnvironmentEvidence,
    HarnessEvidenceSnapshot,
    HarnessExecutionMemory,
    HarnessGenerationBest,
    HarnessJobEvidence,
    HarnessScenarioEvidence,
    HarnessScenarioType,
    HarnessSearchSummary,
    HarnessToolHistory,
    HarnessToolId,
    HarnessTrainingScenarioProfile,
    compile_harness_plan,
)

HARNESS_ROUTING_EVAL_SCHEMA_VERSION = "1.0"
HARNESS_ROUTING_REPORT_SCHEMA_VERSION = "1.1"
HARNESS_ROUTING_MIN_PASS_RATE = 0.75
HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE = 2 / 3
HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT = 0.15
HARNESS_ROUTING_PREDICTION_ARTIFACT_SCHEMA_VERSION = "1.0"

HarnessRoutingCorpusRole = Literal["development", "locked_holdout"]
HarnessRoutingResultDestination = Literal[
    "evaluation_artifact",
    "development_evidence",
    "router_training",
    "runtime_feedback",
]

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


class HarnessEvalTrainingCase(_ClosedModel):
    scenario_type: HarnessScenarioType
    replicate_count: int = Field(ge=1, le=100)
    weight: float = Field(gt=0.0, le=1000.0)
    safe_perturbations: dict[str, float] = Field(default_factory=dict)


def _default_environment() -> HarnessEnvironmentEvidence:
    return HarnessEnvironmentEvidence(
        steady_wind_component_l1_mps=0.0,
        sensor_noise_level="medium",
        advanced_config_present=False,
        obstacle_count=0,
        gps_noise_m=0.0,
        baro_noise_m=0.0,
        imu_noise_scale=1.0,
        sensor_dropout_rate=0.0,
        battery_initial_percent=100.0,
        voltage_sag=False,
    )


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
    training_cases: tuple[HarnessEvalTrainingCase, ...] = Field(default=(), max_length=64)
    environment: HarnessEnvironmentEvidence = Field(default_factory=_default_environment)

    @model_validator(mode="after")
    def _validate_counts_and_budget(self) -> HarnessRoutingStimulus:
        if self.current_generation > self.max_iterations:
            raise ValueError("current_generation cannot exceed max_iterations")
        if self.feasible_candidate_count > self.scored_candidate_count:
            raise ValueError("feasible_candidate_count cannot exceed scored_candidate_count")
        if self.training_replicate_count < self.training_case_count:
            raise ValueError("each training case requires at least one replicate")
        if self.training_cases and (
            len(self.training_cases) != self.training_case_count
            or sum(case.replicate_count for case in self.training_cases)
            != self.training_replicate_count
        ):
            raise ValueError("explicit training cases must match aggregate scenario counts")
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


class HarnessRoutingGenerationConfig(_ClosedModel):
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    seed: int | None = None
    response_format: Literal["json_schema", "json_object"] = "json_schema"


class HarnessRoutingPrediction(_ClosedModel):
    selected_tool: HarnessToolId
    rationale: str = Field(min_length=1, max_length=400)


class HarnessRoutingPredictionArtifact(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_schema_version: str
    tool_registry_version: str
    prompt_template_version: str
    provider: str = Field(min_length=1, max_length=64)
    model_snapshot: str = Field(min_length=1, max_length=160)
    generation_config: HarnessRoutingGenerationConfig = Field(
        default_factory=HarnessRoutingGenerationConfig
    )
    predictions: dict[str, HarnessRoutingPrediction]

    @model_validator(mode="after")
    def _validate_versions(self) -> HarnessRoutingPredictionArtifact:
        expected = {
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        }
        for field_name, expected_value in expected.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"{field_name} must equal current version {expected_value}")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def assert_routing_result_flow(
    source_role: HarnessRoutingCorpusRole,
    destination: HarnessRoutingResultDestination,
) -> None:
    """Fail closed when locked holdout evidence could influence development.

    Holdout labels and results may only be materialized as immutable evaluation
    artifacts. They must never become prompt examples, router-training data,
    development evidence, or live optimizer feedback.
    """

    if source_role == "locked_holdout" and destination != "evaluation_artifact":
        raise ValueError(
            "locked Harness routing holdout results are evaluation-only and "
            f"cannot flow to {destination}"
        )


def routing_corpus_sha256(
    cases: tuple[HarnessRoutingEvalCase, ...],
) -> str:
    payload = [case.model_dump(mode="json") for case in cases]
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def routing_prompt_suite_sha256(
    cases: tuple[HarnessRoutingEvalCase, ...],
) -> str:
    prompts: list[dict[str, str]] = []
    for case in cases:
        system, user = build_decision_messages(compile_routing_eval_snapshot(case))
        prompts.append(
            {
                "case_id": case.case_id,
                "system": system,
                "user": user,
            }
        )
    return hashlib.sha256(_canonical_json(prompts).encode("utf-8")).hexdigest()


def load_routing_prediction_artifact(
    path: Path,
    cases: tuple[HarnessRoutingEvalCase, ...],
) -> HarnessRoutingPredictionArtifact:
    """Load predictions only when every provenance binding matches."""

    try:
        artifact = HarnessRoutingPredictionArtifact.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError("invalid Harness routing prediction artifact") from exc
    if artifact.corpus_sha256 != routing_corpus_sha256(cases):
        raise ValueError("prediction artifact corpus_sha256 does not match corpus")
    if artifact.prompt_suite_sha256 != routing_prompt_suite_sha256(cases):
        raise ValueError(
            "prediction artifact prompt_suite_sha256 does not match production prompts"
        )
    expected_ids = {case.case_id for case in cases}
    if set(artifact.predictions) != expected_ids:
        missing = sorted(expected_ids - set(artifact.predictions))
        extra = sorted(set(artifact.predictions) - expected_ids)
        raise ValueError(
            f"prediction artifact must exactly cover the corpus; missing={missing}, extra={extra}"
        )
    return artifact


def grade_routing_prediction_artifact(
    artifact: HarnessRoutingPredictionArtifact,
    cases: tuple[HarnessRoutingEvalCase, ...],
) -> HarnessRoutingEvalReport:
    return build_routing_eval_report(
        cases,
        {case_id: prediction.selected_tool for case_id, prediction in artifact.predictions.items()},
    )


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
    ordered_scores = sorted((stimulus.baseline_score, stimulus.best_score))
    score_gap = ordered_scores[1] - ordered_scores[0]
    relative_score_gap = (
        score_gap / abs(ordered_scores[0]) if abs(ordered_scores[0]) > 1e-12 else None
    )
    if stimulus.training_cases:
        eval_training_cases = stimulus.training_cases
    else:
        base_replicates, remainder = divmod(
            stimulus.training_replicate_count,
            stimulus.training_case_count,
        )
        eval_training_cases = tuple(
            HarnessEvalTrainingCase(
                scenario_type="nominal",
                replicate_count=base_replicates + (1 if index < remainder else 0),
                weight=1.0,
            )
            for index in range(stimulus.training_case_count)
        )
    total_training_weight = sum(case.weight for case in eval_training_cases)
    training_case_profiles = tuple(
        HarnessTrainingScenarioProfile(
            case_alias=f"training_case_{index + 1}",
            scenario_type=case.scenario_type,
            replicate_count=case.replicate_count,
            weight_share=case.weight / total_training_weight,
            safe_perturbations=case.safe_perturbations,
        )
        for index, case in enumerate(eval_training_cases)
    )
    training_type_counts: dict[str, int] = {
        str(scenario_type): count
        for scenario_type, count in sorted(
            Counter(case.scenario_type for case in eval_training_cases).items()
        )
    }
    replicate_counts = [case.replicate_count for case in training_case_profiles]
    weight_shares = [case.weight_share for case in training_case_profiles]
    budget = HarnessBudgetEvidence(
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
    )
    search = HarnessSearchSummary(
        candidate_count=stimulus.scored_candidate_count,
        scored_candidate_count=stimulus.scored_candidate_count,
        completed_candidate_count=stimulus.scored_candidate_count,
        incomplete_candidate_count=0,
        completed_candidate_rate=1.0,
        feasibility_observed_candidate_count=(stimulus.scored_candidate_count),
        feasible_candidate_count=stimulus.feasible_candidate_count,
        feasible_candidate_rate=(
            stimulus.feasible_candidate_count / stimulus.scored_candidate_count
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
    )
    decision_memory = (stimulus.last_execution,) if stimulus.last_execution is not None else ()
    plan = compile_harness_plan(
        parameter_count=stimulus.parameter_count,
        budget=budget,
        search=search,
        decision_memory=decision_memory,
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
        budget=budget,
        plan=plan,
        scenarios=HarnessScenarioEvidence(
            training_case_count=stimulus.training_case_count,
            validation_case_count=1,
            training_replicate_count=stimulus.training_replicate_count,
            validation_replicate_count=1,
            training_type_counts=training_type_counts,
            training_replicate_min=min(replicate_counts),
            training_replicate_max=max(replicate_counts),
            training_weight_concentration=max(weight_shares),
            effective_training_case_count=(1.0 / sum(share**2 for share in weight_shares)),
            training_cases=training_case_profiles,
            environment=stimulus.environment,
            common_random_numbers=True,
        ),
        search=search,
        tool_history=tool_history,
        decision_memory=decision_memory,
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
    expected_random_passed = sum(len(case.acceptable_tools) / len(tool_ids) for case in cases)
    return HarnessRoutingBaselineSummary(
        case_count=len(cases),
        tool_count=len(tool_ids),
        uniform_random_expected_passed_count=expected_random_passed,
        uniform_random_expected_pass_rate=expected_random_passed / len(cases),
        best_constant_passed_count=best_passed,
        best_constant_pass_rate=best_passed / len(cases),
        best_constant_tools=tuple(
            result.tool_id for result in constant_results if result.passed_count == best_passed
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
    absolute_lift_over_best_constant = summary.pass_rate - baselines.best_constant_pass_rate
    failed_requirements: list[str] = []
    if summary.pass_rate < HARNESS_ROUTING_MIN_PASS_RATE:
        failed_requirements.append("overall_pass_rate")
    if absolute_lift_over_best_constant < HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT:
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
            minimum_lift_over_best_constant=(HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT),
            failed_requirements=tuple(failed_requirements),
        ),
    )


__all__ = [
    "HARNESS_ROUTING_EVAL_SCHEMA_VERSION",
    "HARNESS_ROUTING_MIN_CATEGORY_PASS_RATE",
    "HARNESS_ROUTING_MIN_LIFT_OVER_BEST_CONSTANT",
    "HARNESS_ROUTING_MIN_PASS_RATE",
    "HARNESS_ROUTING_PREDICTION_ARTIFACT_SCHEMA_VERSION",
    "HARNESS_ROUTING_REPORT_SCHEMA_VERSION",
    "HarnessRoutingBaselineSummary",
    "HarnessRoutingCorpusRole",
    "HarnessRoutingEvalCase",
    "HarnessRoutingEvalReport",
    "HarnessRoutingGenerationConfig",
    "HarnessRoutingPrediction",
    "HarnessRoutingPredictionArtifact",
    "HarnessRoutingQualification",
    "HarnessRoutingEvalSummary",
    "HarnessRoutingGrade",
    "HarnessRoutingStimulus",
    "HarnessRoutingResultDestination",
    "assert_routing_result_flow",
    "build_routing_eval_report",
    "compile_routing_eval_snapshot",
    "grade_routing_decision",
    "grade_routing_prediction_artifact",
    "load_routing_eval_cases",
    "load_routing_prediction_artifact",
    "routing_corpus_sha256",
    "routing_prompt_suite_sha256",
    "summarize_routing_baselines",
    "summarize_routing_predictions",
]
