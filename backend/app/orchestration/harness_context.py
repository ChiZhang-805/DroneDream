"""Closed, versioned decision context for DroneDream's bounded LLM Harness.

The provider-visible snapshot is deliberately compiled from trusted enums,
validated catalog entries, finite measurements, and aggregate counts. User
labels, candidate IDs, parameter values, model prose, errors, scenario IDs,
seeds, and arbitrary JSON never cross this boundary.
"""

from __future__ import annotations

import math
import string
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import models, schemas
from app.optimization.candidate_evidence_ledger import (
    CandidateEvidenceReceiptV2,
    current_candidate_evidence_receipt,
)
from app.optimization.outcome_taxonomy import (
    TrialOutcomeClass,
    classify_trial_outcome,
    is_optimizer_learning_outcome,
)
from app.optimization.scenarios import scenario_matrix
from app.orchestration.provider_feedback import (
    CandidateFeedbackView,
    compile_candidate_feedback,
)
from app.parameters import get_parameter

HarnessToolId = Literal[
    "cma_es",
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
]
HarnessSourceType = Literal["baseline", "optimizer", "llm_optimizer", "unknown"]
HarnessObjectiveProfile = Literal["stable", "fast", "smooth", "robust", "custom", "unknown"]
HarnessTrackType = Literal["circle", "u_turn", "lemniscate", "custom", "unknown"]

HARNESS_EVIDENCE_SCHEMA_VERSION = "2.5"
HARNESS_TOOL_REGISTRY_VERSION = "2.1"
HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION = "1.1"
HARNESS_PROMPT_TEMPLATE_VERSION = "1.2"
HARNESS_DECISION_TRACE_SCHEMA_VERSION = "1.1"
MAX_EVIDENCE_CANDIDATES = 12
MAX_DECISION_MEMORY_ITEMS = 8
MAX_GENERATION_TREND_ITEMS = 32

_ALLOWED_SOURCE_TYPES = frozenset({"baseline", "optimizer", "llm_optimizer"})
_ALLOWED_OBJECTIVE_PROFILES = frozenset({"stable", "fast", "smooth", "robust", "custom"})
_ALLOWED_TRACK_TYPES = frozenset({"circle", "u_turn", "lemniscate", "custom"})
_ALLOWED_SCENARIO_TYPES = frozenset(
    {
        "nominal",
        "noise_perturbed",
        "wind_perturbed",
        "combined_perturbed",
        "turbulence",
        "gps_dropout",
        "payload_changed",
        "battery_degraded",
        "actuator_delay",
        "custom",
    }
)
_ALLOWED_ROBUST_AGGREGATIONS = frozenset({"mean", "worst", "cvar", "percentile"})
_ALLOWED_METRICS = (
    "rmse",
    "max_error",
    "max_error_worst",
    "completion_time",
    "aggregated_score",
    "scalar_loss",
    "feasible",
    "total_constraint_violation",
    "optimizer_learning_failure_rate",
)
_ALLOWED_EXECUTION_STATUSES = frozenset(
    {
        "dispatched",
        "max_iterations_reached",
        "budget_exhausted",
        "search_space_exhausted",
    }
)
_ALLOWED_FALLBACK_REASONS = frozenset(
    {
        "missing_model",
        "insufficient_evidence",
        "prompt_too_large",
        "missing_api_key",
        "client_error",
        "invalid_response",
    }
)

JsonScalar: TypeAlias = bool | int | float | None
JsonMetric: TypeAlias = JsonScalar | list[JsonScalar]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HarnessToolDefinition(_ClosedModel):
    tool_id: HarnessToolId
    summary: str = Field(min_length=1, max_length=240)
    search_role: Literal[
        "general",
        "constraint_aware",
        "multi_fidelity",
        "local_exploitation",
        "sparse_high_dimension",
        "surrogate_evolution",
        "restart_exploration",
        "balanced_fallback",
    ]
    best_when: tuple[str, ...] = Field(min_length=1, max_length=4)
    supports_explicit_constraints: bool
    supports_multi_objective: bool
    supports_multi_fidelity: bool


HARNESS_TOOL_DEFINITIONS: dict[HarnessToolId, HarnessToolDefinition] = {
    "cma_es": HarnessToolDefinition(
        tool_id="cma_es",
        summary="Dependency-free evolutionary search using one bounded proposal.",
        search_role="general",
        best_when=(
            "little trustworthy history exists",
            "a conservative derivative-free step is preferable",
        ),
        supports_explicit_constraints=False,
        supports_multi_objective=False,
        supports_multi_fidelity=False,
    ),
    "constrained_mobo": HarnessToolDefinition(
        tool_id="constrained_mobo",
        summary="Constraint-aware multi-objective Bayesian proposal search.",
        search_role="constraint_aware",
        best_when=(
            "multiple objectives or explicit violations must be balanced",
            "completed numerical evidence is available for surrogate fitting",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=True,
        supports_multi_fidelity=False,
    ),
    "multi_fidelity_mobo": HarnessToolDefinition(
        tool_id="multi_fidelity_mobo",
        summary="Bayesian search that can screen candidates at reduced scenario coverage.",
        search_role="multi_fidelity",
        best_when=(
            "simulation budget is tight relative to scenario-matrix cost",
            "cheap screening can preserve budget for full verification",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=True,
        supports_multi_fidelity=True,
    ),
    "turbo": HarnessToolDefinition(
        tool_id="turbo",
        summary="Trust-region Bayesian search around the strongest local evidence.",
        search_role="local_exploitation",
        best_when=(
            "a promising feasible region has already been found",
            "recent local progress justifies focused exploitation",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=False,
        supports_multi_fidelity=False,
    ),
    "saasbo": HarnessToolDefinition(
        tool_id="saasbo",
        summary="Sparse-axis Bayesian approximation for larger parameter spaces.",
        search_role="sparse_high_dimension",
        best_when=(
            "the parameter dimension is comparatively high",
            "only a subset of axes is likely to dominate improvement",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=False,
        supports_multi_fidelity=False,
    ),
    "surrogate_cma_es": HarnessToolDefinition(
        tool_id="surrogate_cma_es",
        summary="Evolutionary search assisted by a fitted numerical surrogate.",
        search_role="surrogate_evolution",
        best_when=(
            "enough completed observations exist to fit a useful surrogate",
            "global evolutionary search still benefits from learned ranking",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=False,
        supports_multi_fidelity=False,
    ),
    "bipop_cma_es": HarnessToolDefinition(
        tool_id="bipop_cma_es",
        summary="Restarting CMA-ES with alternating small and large populations.",
        search_role="restart_exploration",
        best_when=(
            "several generations have stagnated",
            "escaping a local basin is more important than local refinement",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=False,
        supports_multi_fidelity=False,
    ),
    "optimizer_portfolio": HarnessToolDefinition(
        tool_id="optimizer_portfolio",
        summary="Deterministic budget allocation across all available optimizer families.",
        search_role="balanced_fallback",
        best_when=(
            "evidence is insufficient for a confident specialized choice",
            "robust exploration across optimizer families is preferable",
        ),
        supports_explicit_constraints=True,
        supports_multi_objective=True,
        supports_multi_fidelity=True,
    ),
}

# Preserve the existing public capability contract while the richer, versioned
# definitions are used in provider requests.
HARNESS_TOOL_REGISTRY: dict[HarnessToolId, str] = {
    tool_id: definition.summary for tool_id, definition in HARNESS_TOOL_DEFINITIONS.items()
}


class HarnessCandidateEvidence(_ClosedModel):
    generation: int = Field(ge=0)
    source_type: HarnessSourceType
    is_baseline: bool
    aggregated_score: float | None = None
    metrics: dict[str, JsonMetric] = Field(default_factory=dict)
    trial_count: int = Field(ge=0)
    completed_trial_count: int = Field(ge=0)
    failed_trial_count: int = Field(ge=0)


class HarnessBudgetEvidence(_ClosedModel):
    current_generation: int = Field(ge=0)
    max_iterations: int = Field(ge=0)
    remaining_generations: int = Field(ge=0)
    used_trials: int = Field(ge=0)
    max_total_trials: int = Field(ge=0)
    remaining_trials: int = Field(ge=0)
    full_trials_per_candidate: int = Field(ge=1)
    remaining_full_candidate_capacity: int = Field(ge=0)


class HarnessScenarioEvidence(_ClosedModel):
    training_case_count: int = Field(ge=0)
    validation_case_count: int = Field(ge=0)
    training_replicate_count: int = Field(ge=0)
    validation_replicate_count: int = Field(ge=0)
    training_type_counts: dict[str, int] = Field(default_factory=dict)
    common_random_numbers: bool | None = None


class HarnessGenerationBest(_ClosedModel):
    generation: int = Field(ge=0)
    best_score: float


class HarnessSearchSummary(_ClosedModel):
    candidate_count: int = Field(ge=0)
    scored_candidate_count: int = Field(ge=0)
    completed_candidate_count: int = Field(ge=0)
    incomplete_candidate_count: int = Field(ge=0)
    completed_candidate_rate: float = Field(ge=0.0, le=1.0)
    feasibility_observed_candidate_count: int = Field(ge=0)
    feasible_candidate_count: int = Field(ge=0)
    feasible_candidate_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    total_trial_count: int = Field(ge=0)
    failed_trial_count: int = Field(ge=0)
    observed_failure_rate: float = Field(ge=0.0, le=1.0)
    baseline_score: float | None = None
    best_score: float | None = None
    relative_improvement_from_baseline: float | None = None
    score_gap_to_runner_up: float | None = Field(default=None, ge=0.0)
    relative_score_gap_to_runner_up: float | None = Field(default=None, ge=0.0)
    trailing_stagnant_generations: int = Field(ge=0)
    best_score_by_generation: tuple[HarnessGenerationBest, ...] = Field(
        default=(),
        max_length=MAX_GENERATION_TREND_ITEMS,
    )


class HarnessToolHistory(_ClosedModel):
    tool_id: HarnessToolId
    candidate_count: int = Field(ge=0)
    completed_candidate_count: int = Field(ge=0)
    feasible_candidate_count: int = Field(ge=0)
    total_trial_count: int = Field(ge=0)
    failed_trial_count: int = Field(ge=0)
    best_score: float | None = None
    last_generation: int = Field(ge=0)


class HarnessObservedDecisionOutcome(_ClosedModel):
    """Provider-safe, observational result for one dispatched generation.

    This is a verified association between a decision receipt and the
    generation cohort that followed it. It is deliberately not a causal reward
    or child-tool credit assignment.
    """

    schema_id: Literal["dronedream.harness-decision-observed-outcome/v1"] = (
        "dronedream.harness-decision-observed-outcome/v1"
    )
    cohort_candidate_count: int = Field(ge=1)
    accepted_attempt_count: int = Field(ge=0)
    optimizer_learning_trial_count: int = Field(ge=0)
    domain_failure_trial_count: int = Field(ge=0)
    feasible_candidate_count: int = Field(ge=0)
    completed_candidate_rate: float = Field(ge=0.0, le=1.0)
    incumbent_score_before: float | None = None
    cohort_best_score: float
    incumbent_score_after: float
    observed_absolute_improvement: float | None = Field(default=None, ge=0.0)
    observed_relative_improvement: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _validate_counts_and_incumbent(self) -> HarnessObservedDecisionOutcome:
        if self.domain_failure_trial_count > self.optimizer_learning_trial_count:
            raise ValueError("domain failures cannot exceed optimizer-learning trials")
        if self.feasible_candidate_count > self.cohort_candidate_count:
            raise ValueError("feasible candidates cannot exceed the cohort")
        if self.incumbent_score_before is None:
            if (
                self.observed_absolute_improvement is not None
                or self.observed_relative_improvement is not None
                or self.incumbent_score_after != self.cohort_best_score
            ):
                raise ValueError("first observed cohort cannot claim prior-incumbent improvement")
        elif self.incumbent_score_after > self.incumbent_score_before:
            raise ValueError("incumbent score cannot regress")
        return self


class HarnessExecutionMemory(_ClosedModel):
    generation: int = Field(ge=0)
    tool_id: HarnessToolId
    decision_source: Literal["model", "deterministic_fallback", "unknown"]
    status: Literal[
        "dispatched",
        "max_iterations_reached",
        "budget_exhausted",
        "search_space_exhausted",
        "unknown",
    ]
    dispatched_candidates: int = Field(ge=0)
    reflection_status: Literal[
        "verified_complete",
        "not_applicable",
        "unavailable",
    ] = "unavailable"
    observed_outcome: HarnessObservedDecisionOutcome | None = None
    fallback_reason: (
        Literal[
            "missing_model",
            "insufficient_evidence",
            "prompt_too_large",
            "missing_api_key",
            "client_error",
            "invalid_response",
        ]
        | None
    ) = None

    @model_validator(mode="before")
    @classmethod
    def _default_reflection_status(cls, value: object) -> object:
        if isinstance(value, dict) and "reflection_status" not in value:
            value = dict(value)
            value["reflection_status"] = (
                "unavailable" if value.get("status") == "dispatched" else "not_applicable"
            )
        return value

    @model_validator(mode="after")
    def _validate_reflection_state(self) -> HarnessExecutionMemory:
        if self.reflection_status == "verified_complete":
            if self.status != "dispatched" or self.observed_outcome is None:
                raise ValueError("verified reflection requires a dispatched observed outcome")
        elif self.observed_outcome is not None:
            raise ValueError("only verified reflection may carry an observed outcome")
        elif self.reflection_status == "not_applicable" and self.status == "dispatched":
            raise ValueError("a dispatched generation requires reflection or unavailable status")
        elif self.reflection_status == "unavailable" and self.status != "dispatched":
            raise ValueError("non-dispatched execution has no applicable cohort")
        return self


class HarnessJobEvidence(_ClosedModel):
    objective_profile: HarnessObjectiveProfile
    track_type: HarnessTrackType
    parameter_count: int = Field(ge=0)
    parameter_names: tuple[str, ...] = Field(max_length=64)
    objective_count: int = Field(ge=0)
    constraint_count: int = Field(ge=0)
    robust_aggregation: str


class HarnessEvidenceSnapshot(_ClosedModel):
    schema_version: Literal["2.5"] = "2.5"
    job: HarnessJobEvidence
    budget: HarnessBudgetEvidence
    scenarios: HarnessScenarioEvidence
    search: HarnessSearchSummary
    tool_history: tuple[HarnessToolHistory, ...] = ()
    decision_memory: tuple[HarnessExecutionMemory, ...] = Field(
        default=(),
        max_length=MAX_DECISION_MEMORY_ITEMS,
    )
    candidates: tuple[HarnessCandidateEvidence, ...] = Field(max_length=MAX_EVIDENCE_CANDIDATES)
    candidate_history_total: int = Field(ge=0)
    candidate_history_included: int = Field(ge=0)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _safe_metric(value: object, *, depth: int = 0) -> JsonMetric | None:
    """Compile only finite numeric/boolean metric values and bounded arrays."""

    if depth > 4:
        return None
    if value is None or isinstance(value, bool):
        return value
    numeric = _finite(value)
    if numeric is not None:
        return numeric
    if isinstance(value, list):
        compiled: list[JsonScalar] = []
        for item in value[:64]:
            child = _safe_metric(item, depth=depth + 1)
            if isinstance(child, list) or (child is None and item is not None):
                return None
            compiled.append(child)
        return compiled
    # Mappings and strings can contain prompt-injection payloads and are never
    # part of the provider-visible evidence contract.
    return None


def compile_provider_safe_metric(value: object) -> JsonMetric | None:
    """Compile one metric through the production provider trust boundary.

    The public wrapper exists so deterministic contract audits can exercise
    the same filter as live context compilation without copying its rules.
    A ``None`` result means the value must not enter provider-visible metrics.
    """

    return _safe_metric(value)


def optimizer_learning_outcome_for_trial(
    *,
    scenario_matched: bool,
    scenario_holdout: bool,
    status: object,
    failure_code: object,
    usable_metric: bool,
) -> TrialOutcomeClass | None:
    """Return the trusted training outcome, or ``None`` when quarantined.

    Holdout and unresolved scenario rows are isolated before the closed
    outcome taxonomy is applied. Infrastructure, cancellation, malformed,
    and unknown evidence therefore cannot become optimizer observations.
    """

    if not scenario_matched or scenario_holdout:
        return None
    outcome_class = classify_trial_outcome(
        status=status,
        failure_code=failure_code,
        usable_metric=usable_metric,
    )
    return outcome_class if is_optimizer_learning_outcome(outcome_class) else None


def _candidate_evidence(
    candidate: models.CandidateParameterSet,
    feedback: CandidateFeedbackView,
) -> HarnessCandidateEvidence:
    allowed_metrics: dict[str, JsonMetric] = {}
    for key in _ALLOWED_METRICS:
        if key not in feedback.aggregate:
            continue
        compiled = _safe_metric(feedback.aggregate.get(key))
        if compiled is not None:
            allowed_metrics[key] = compiled
    return HarnessCandidateEvidence(
        generation=max(0, int(candidate.generation_index or 0)),
        source_type=cast(
            HarnessSourceType,
            (
                candidate.source_type
                if candidate.source_type in _ALLOWED_SOURCE_TYPES
                else "unknown"
            ),
        ),
        is_baseline=bool(candidate.is_baseline),
        aggregated_score=feedback.score,
        metrics=allowed_metrics,
        trial_count=feedback.learning_trial_count,
        completed_trial_count=feedback.completed_trial_count,
        failed_trial_count=feedback.failed_trial_count,
    )


def _registered_parameter_names(job: models.Job) -> tuple[str, ...]:
    parameter_space = job.parameter_space_json if isinstance(job.parameter_space_json, list) else []
    vehicle_profile = job.vehicle_profile_json if isinstance(job.vehicle_profile_json, dict) else {}
    context = {
        key: value
        for key, value in {
            "px4_version": vehicle_profile.get("px4_version"),
            "vehicle_type": vehicle_profile.get("vehicle_type"),
            "airframe": vehicle_profile.get("airframe"),
        }.items()
        if isinstance(value, str)
    }
    names: list[str] = []
    for item in parameter_space:
        if (
            not isinstance(item, dict)
            or item.get("enabled", True) is not True
            or item.get("locked", False) is True
            or not isinstance(item.get("name"), str)
        ):
            continue
        try:
            parameter = get_parameter(item["name"], **context)
        except ValueError:
            parameter = None
        if parameter is not None:
            names.append(parameter.name)
    return tuple(names[:64])


def _scenario_evidence(job: models.Job) -> HarnessScenarioEvidence:
    raw_suite = job.scenario_suite_json if isinstance(job.scenario_suite_json, dict) else {}
    if not raw_suite:
        return HarnessScenarioEvidence(
            training_case_count=1,
            validation_case_count=0,
            training_replicate_count=max(1, int(job.trials_per_candidate or 1)),
            validation_replicate_count=0,
            training_type_counts={},
            common_random_numbers=None,
        )
    suite = schemas.ScenarioSuiteConfig(**raw_suite)
    runs = scenario_matrix(suite)
    type_counts: dict[str, int] = defaultdict(int)
    training_case_count = 0
    validation_case_count = 0
    for case in suite.cases:
        if not case.enabled:
            continue
        if case.holdout:
            validation_case_count += 1
            continue
        training_case_count += 1
        if case.scenario_type in _ALLOWED_SCENARIO_TYPES:
            type_counts[str(case.scenario_type)] += 1
    return HarnessScenarioEvidence(
        training_case_count=training_case_count,
        validation_case_count=validation_case_count,
        training_replicate_count=sum(1 for run in runs if not run.holdout),
        validation_replicate_count=sum(1 for run in runs if run.holdout),
        training_type_counts=dict(sorted(type_counts.items())),
        common_random_numbers=suite.common_random_numbers,
    )


def _candidate_complete(feedback: CandidateFeedbackView) -> bool:
    return feedback.score is not None


def _candidate_optimizer_learning_counts(
    candidate: models.CandidateParameterSet,
    scenario_suite: schemas.ScenarioSuiteConfig | None,
) -> tuple[int, int, int]:
    """Compatibility wrapper around the shared verified feedback compiler."""

    feedback = compile_candidate_feedback(
        candidate,
        scenario_suite=scenario_suite,
    )
    return (
        feedback.learning_trial_count,
        feedback.completed_trial_count,
        feedback.failed_trial_count,
    )


def _candidate_feasibility(
    feedback: CandidateFeedbackView,
) -> bool | None:
    return feedback.feasible


def _search_summary(
    candidates: list[models.CandidateParameterSet],
    feedback_by_id: dict[str, CandidateFeedbackView],
) -> HarnessSearchSummary:
    scored: list[tuple[models.CandidateParameterSet, float]] = []
    for candidate in candidates:
        score = feedback_by_id[candidate.id].score
        if score is not None:
            scored.append((candidate, score))
    baseline_scores = [score for candidate, score in scored if candidate.is_baseline]
    feasible_or_unknown_scores = [
        score
        for candidate, score in scored
        if _candidate_feasibility(feedback_by_id[candidate.id]) is not False
    ]
    ordered_scores = sorted(
        feasible_or_unknown_scores if feasible_or_unknown_scores else [score for _, score in scored]
    )
    best_score = ordered_scores[0] if ordered_scores else None
    baseline_score = min(baseline_scores, default=None)
    relative_improvement: float | None = None
    if baseline_score is not None and best_score is not None and abs(baseline_score) > 1e-12:
        relative_improvement = (baseline_score - best_score) / abs(baseline_score)
    score_gap = ordered_scores[1] - ordered_scores[0] if len(ordered_scores) >= 2 else None
    relative_score_gap = (
        score_gap / abs(best_score)
        if score_gap is not None and best_score is not None and abs(best_score) > 1e-12
        else None
    )

    generation_scores: dict[int, list[float]] = defaultdict(list)
    for candidate, score in scored:
        generation_scores[max(0, int(candidate.generation_index or 0))].append(score)
    full_best_by_generation = tuple(
        HarnessGenerationBest(
            generation=generation,
            best_score=min(values),
        )
        for generation, values in sorted(generation_scores.items())
    )
    incumbent: float | None = None
    trailing_stagnation = 0
    for item in full_best_by_generation:
        if incumbent is None or item.best_score < incumbent - 1e-12:
            incumbent = item.best_score
            trailing_stagnation = 0
        else:
            trailing_stagnation += 1
    best_by_generation = full_best_by_generation
    if len(best_by_generation) > MAX_GENERATION_TREND_ITEMS:
        best_by_generation = (
            best_by_generation[0],
            *best_by_generation[-(MAX_GENERATION_TREND_ITEMS - 1) :],
        )

    learning_counts = [
        (
            feedback_by_id[candidate.id].learning_trial_count,
            feedback_by_id[candidate.id].completed_trial_count,
            feedback_by_id[candidate.id].failed_trial_count,
        )
        for candidate in candidates
    ]
    total_trials = sum(counts[0] for counts in learning_counts)
    failed_trials = sum(counts[2] for counts in learning_counts)
    completed_candidates = sum(
        1 for candidate in candidates if _candidate_complete(feedback_by_id[candidate.id])
    )
    feasibility_observations = [
        value
        for candidate in candidates
        if (value := _candidate_feasibility(feedback_by_id[candidate.id])) is not None
    ]
    feasible_candidates = sum(1 for value in feasibility_observations if value)
    return HarnessSearchSummary(
        candidate_count=len(candidates),
        scored_candidate_count=len(scored),
        completed_candidate_count=completed_candidates,
        incomplete_candidate_count=len(candidates) - completed_candidates,
        completed_candidate_rate=(completed_candidates / len(candidates) if candidates else 0.0),
        feasibility_observed_candidate_count=len(feasibility_observations),
        feasible_candidate_count=feasible_candidates,
        feasible_candidate_rate=(
            feasible_candidates / len(feasibility_observations)
            if feasibility_observations
            else None
        ),
        total_trial_count=total_trials,
        failed_trial_count=failed_trials,
        observed_failure_rate=failed_trials / total_trials if total_trials else 0.0,
        baseline_score=baseline_score,
        best_score=best_score,
        relative_improvement_from_baseline=relative_improvement,
        score_gap_to_runner_up=score_gap,
        relative_score_gap_to_runner_up=relative_score_gap,
        trailing_stagnant_generations=trailing_stagnation,
        best_score_by_generation=best_by_generation,
    )


def _candidate_tool(
    candidate: models.CandidateParameterSet,
) -> HarnessToolId | None:
    metadata = (
        candidate.optimizer_metadata_json
        if isinstance(candidate.optimizer_metadata_json, dict)
        else {}
    )
    for key in ("child_strategy", "strategy"):
        value = metadata.get(key)
        if value in HARNESS_TOOL_DEFINITIONS:
            return cast(HarnessToolId, value)
    return None


def _tool_history(
    candidates: list[models.CandidateParameterSet],
    feedback_by_id: dict[str, CandidateFeedbackView],
) -> tuple[HarnessToolHistory, ...]:
    grouped: dict[HarnessToolId, list[models.CandidateParameterSet]] = defaultdict(list)
    for candidate in candidates:
        tool_id = _candidate_tool(candidate)
        if tool_id is not None:
            grouped[tool_id].append(candidate)

    result: list[HarnessToolHistory] = []
    for tool_id in HARNESS_TOOL_DEFINITIONS:
        owned = grouped.get(tool_id)
        if not owned:
            continue
        all_scores = [
            score
            for candidate in owned
            if (score := feedback_by_id[candidate.id].score) is not None
        ]
        feasible_or_unknown_scores = [
            score
            for candidate in owned
            if (score := feedback_by_id[candidate.id].score) is not None
            and _candidate_feasibility(feedback_by_id[candidate.id]) is not False
        ]
        scores = feasible_or_unknown_scores or all_scores
        result.append(
            HarnessToolHistory(
                tool_id=tool_id,
                candidate_count=len(owned),
                completed_candidate_count=sum(
                    1 for candidate in owned if _candidate_complete(feedback_by_id[candidate.id])
                ),
                feasible_candidate_count=sum(
                    1
                    for candidate in owned
                    if _candidate_feasibility(feedback_by_id[candidate.id]) is True
                ),
                total_trial_count=sum(
                    feedback_by_id[candidate.id].learning_trial_count for candidate in owned
                ),
                failed_trial_count=sum(
                    feedback_by_id[candidate.id].failed_trial_count for candidate in owned
                ),
                best_score=min(scores, default=None),
                last_generation=max(
                    max(0, int(candidate.generation_index or 0)) for candidate in owned
                ),
            )
        )
    return tuple(result)


def _event_sort_time(event: models.JobEvent) -> datetime:
    value = event.created_at
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _bounded_int(value: object, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _hex_id(value: object, *, length: int) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(char not in string.hexdigits for char in value)
    ):
        return None
    return value.lower()


def _common_decision_binding(
    payload: dict[str, object],
) -> tuple[str, int, str, str | None] | None:
    decision_id = _hex_id(payload.get("decision_id"), length=32)
    generation = _bounded_int(payload.get("generation"), minimum=1)
    evidence_sha256 = _hex_id(payload.get("evidence_sha256"), length=64)
    raw_prompt_sha256 = payload.get("prompt_sha256")
    prompt_sha256 = None if raw_prompt_sha256 is None else _hex_id(raw_prompt_sha256, length=64)
    if (
        decision_id is None
        or generation is None
        or evidence_sha256 is None
        or (raw_prompt_sha256 is not None and prompt_sha256 is None)
        or payload.get("evidence_schema_version") != HARNESS_EVIDENCE_SCHEMA_VERSION
        or payload.get("tool_registry_version") != HARNESS_TOOL_REGISTRY_VERSION
        or payload.get("prompt_template_version") != HARNESS_PROMPT_TEMPLATE_VERSION
    ):
        return None
    return decision_id, generation, evidence_sha256, prompt_sha256


def _trusted_incumbent_score(
    candidates: Iterable[models.CandidateParameterSet],
    feedback_by_id: dict[str, CandidateFeedbackView],
) -> float | None:
    verified: list[tuple[float, bool | None]] = []
    for candidate in candidates:
        feedback = feedback_by_id[candidate.id]
        receipt = current_candidate_evidence_receipt(candidate)
        if (
            not isinstance(receipt, CandidateEvidenceReceiptV2)
            or feedback.feedback_status != "verified"
            or feedback.score is None
        ):
            continue
        verified.append((feedback.score, feedback.feasible))
    feasible_or_unknown = [score for score, feasible in verified if feasible is not False]
    scores = feasible_or_unknown or [score for score, _ in verified]
    return min(scores, default=None)


def _observed_outcome_for_execution(
    execution: HarnessExecutionMemory,
    *,
    candidates: list[models.CandidateParameterSet],
    feedback_by_id: dict[str, CandidateFeedbackView],
) -> HarnessExecutionMemory:
    """Attach one fail-closed, training-only observational cohort result."""

    if execution.status != "dispatched":
        return execution.model_copy(
            update={
                "reflection_status": "not_applicable",
                "observed_outcome": None,
            }
        )

    cohort = [
        candidate
        for candidate in candidates
        if candidate.source_type == "optimizer"
        and max(0, int(candidate.generation_index or 0)) == execution.generation
    ]
    if len(cohort) != execution.dispatched_candidates:
        return execution.model_copy(
            update={
                "reflection_status": "unavailable",
                "observed_outcome": None,
            }
        )

    accepted_attempt_count = 0
    learning_trial_count = 0
    domain_failure_trial_count = 0
    completed_candidate_count = 0
    feasible_candidate_count = 0
    for candidate in cohort:
        feedback = feedback_by_id[candidate.id]
        receipt = current_candidate_evidence_receipt(candidate)
        if (
            not isinstance(receipt, CandidateEvidenceReceiptV2)
            or receipt.source_type != "optimizer"
            or feedback.feedback_status != "verified"
            or feedback.score is None
            or feedback.learning_trial_count
            != feedback.completed_trial_count + feedback.failed_trial_count
        ):
            return execution.model_copy(
                update={
                    "reflection_status": "unavailable",
                    "observed_outcome": None,
                }
            )
        accepted_attempt_count += receipt.report_accepted_attempt_count
        learning_trial_count += feedback.learning_trial_count
        domain_failure_trial_count += feedback.failed_trial_count
        completed_candidate_count += int(feedback.completed_trial_count > 0)
        feasible_candidate_count += int(feedback.feasible is True)

    prior = [
        candidate
        for candidate in candidates
        if max(0, int(candidate.generation_index or 0)) < execution.generation
    ]
    incumbent_before = _trusted_incumbent_score(prior, feedback_by_id)
    cohort_best = _trusted_incumbent_score(cohort, feedback_by_id)
    if cohort_best is None:
        return execution.model_copy(
            update={
                "reflection_status": "unavailable",
                "observed_outcome": None,
            }
        )

    incumbent_after = (
        cohort_best if incumbent_before is None else min(incumbent_before, cohort_best)
    )
    absolute_improvement = (
        None
        if incumbent_before is None
        else round(max(0.0, incumbent_before - incumbent_after), 12)
    )
    relative_improvement = (
        None
        if incumbent_before is None or abs(incumbent_before) <= 1e-12
        else round(
            max(0.0, incumbent_before - incumbent_after) / abs(incumbent_before),
            12,
        )
    )
    outcome = HarnessObservedDecisionOutcome(
        cohort_candidate_count=len(cohort),
        accepted_attempt_count=accepted_attempt_count,
        optimizer_learning_trial_count=learning_trial_count,
        domain_failure_trial_count=domain_failure_trial_count,
        feasible_candidate_count=feasible_candidate_count,
        completed_candidate_rate=completed_candidate_count / len(cohort),
        incumbent_score_before=incumbent_before,
        cohort_best_score=cohort_best,
        incumbent_score_after=incumbent_after,
        observed_absolute_improvement=absolute_improvement,
        observed_relative_improvement=relative_improvement,
    )
    return execution.model_copy(
        update={
            "reflection_status": "verified_complete",
            "observed_outcome": outcome,
        }
    )


def _decision_memory(
    events: list[models.JobEvent],
    *,
    current_generation: int,
    verified_started_decision_ids: frozenset[str],
    candidates: list[models.CandidateParameterSet],
    feedback_by_id: dict[str, CandidateFeedbackView],
) -> tuple[HarnessExecutionMemory, ...]:
    """Compile only decision/result pairs with a complete provenance binding.

    JobEvent is an operator-facing audit stream rather than an authority ledger.
    Runtime memory fails closed unless one execution result has exactly one
    matching accepted/fallback decision, the model path has its preceding
    started trace, every content/version binding agrees, and the generation is
    reachable from current Job state.
    """

    ordered = sorted(events, key=lambda item: (_event_sort_time(item), item.id))
    started: dict[str, tuple[models.JobEvent, dict[str, object]]] = {}
    rejected: dict[str, tuple[models.JobEvent, dict[str, object]]] = {}
    decisions: dict[
        str,
        tuple[models.JobEvent, dict[str, object], str],
    ] = {}
    results: dict[
        str,
        list[tuple[models.JobEvent, dict[str, object]]],
    ] = defaultdict(list)
    invalid_decision_ids: set[str] = set()

    for event in ordered:
        if not isinstance(event.payload_json, dict):
            continue
        payload = cast(dict[str, object], event.payload_json)
        binding = _common_decision_binding(payload)
        if binding is None:
            continue
        decision_id, generation, _, _ = binding
        if generation > max(0, current_generation) + 1:
            continue
        if event.event_type == "harness_decision_started":
            if decision_id in started:
                invalid_decision_ids.add(decision_id)
            else:
                started[decision_id] = (event, payload)
        elif event.event_type == "harness_decision_rejected":
            if decision_id in rejected:
                invalid_decision_ids.add(decision_id)
            else:
                rejected[decision_id] = (event, payload)
        elif event.event_type in {
            "harness_decision_accepted",
            "harness_decision_fallback",
        }:
            if decision_id in decisions:
                invalid_decision_ids.add(decision_id)
            else:
                decisions[decision_id] = (
                    event,
                    payload,
                    event.event_type,
                )
        elif event.event_type == "harness_tool_execution_result":
            results[decision_id].append((event, payload))

    verified: list[tuple[models.JobEvent, HarnessExecutionMemory]] = []
    for decision_id, result_rows in results.items():
        if (
            decision_id in invalid_decision_ids
            or len(result_rows) != 1
            or decision_id not in decisions
        ):
            continue
        decision_event, decision_payload, decision_type = decisions[decision_id]
        result_event, result_payload = result_rows[0]
        decision_binding = _common_decision_binding(decision_payload)
        result_binding = _common_decision_binding(result_payload)
        if decision_binding is None or result_binding is None or decision_binding != result_binding:
            continue
        _, generation, _, prompt_sha256 = decision_binding
        if _event_sort_time(decision_event) > _event_sort_time(result_event):
            continue

        tool_id = decision_payload.get("tool_id")
        if tool_id not in HARNESS_TOOL_DEFINITIONS or result_payload.get("tool_id") != tool_id:
            continue
        raw_source = result_payload.get("decision_source")
        raw_reason = decision_payload.get("reason")
        if decision_type == "harness_decision_accepted":
            started_row = started.get(decision_id)
            if (
                started_row is None
                or prompt_sha256 is None
                or decision_id not in verified_started_decision_ids
                or decision_id in rejected
            ):
                continue
            started_event, started_payload = started_row
            started_binding = _common_decision_binding(started_payload)
            allowed_tools = started_payload.get("allowed_tools")
            if (
                started_binding != decision_binding
                or _event_sort_time(started_event) > _event_sort_time(decision_event)
                or started_payload.get("trace_schema_version")
                != HARNESS_DECISION_TRACE_SCHEMA_VERSION
                or not isinstance(allowed_tools, list)
                or not allowed_tools
                or any(
                    not isinstance(item, str) or item not in HARNESS_TOOL_DEFINITIONS
                    for item in allowed_tools
                )
                or tool_id not in allowed_tools
                or raw_source != "model"
                or result_payload.get("fallback_reason") is not None
            ):
                continue
            decision_source = "model"
            fallback_reason = None
        else:
            rejected_row = rejected.get(decision_id)
            if rejected_row is None:
                continue
            rejected_event, rejected_payload = rejected_row
            rejected_binding = _common_decision_binding(rejected_payload)
            if (
                rejected_binding != decision_binding
                or _event_sort_time(rejected_event) > _event_sort_time(decision_event)
                or rejected_payload.get("reason") != raw_reason
                or tool_id != "optimizer_portfolio"
                or raw_reason not in _ALLOWED_FALLBACK_REASONS
                or raw_source != "deterministic_fallback"
                or result_payload.get("fallback_reason") != raw_reason
            ):
                continue
            decision_source = "deterministic_fallback"
            fallback_reason = raw_reason

        raw_status = result_payload.get("status")
        dispatched_candidates = _bounded_int(result_payload.get("dispatched_candidates"))
        if (
            raw_status not in _ALLOWED_EXECUTION_STATUSES
            or dispatched_candidates is None
            or (raw_status == "dispatched" and dispatched_candidates == 0)
            or (raw_status != "dispatched" and dispatched_candidates != 0)
            or (raw_status == "dispatched" and generation > max(0, current_generation))
        ):
            continue
        verified.append(
            (
                result_event,
                HarnessExecutionMemory(
                    generation=generation,
                    tool_id=tool_id,
                    decision_source=cast(
                        Literal["model", "deterministic_fallback"],
                        decision_source,
                    ),
                    status=cast(
                        Literal[
                            "dispatched",
                            "max_iterations_reached",
                            "budget_exhausted",
                            "search_space_exhausted",
                        ],
                        raw_status,
                    ),
                    dispatched_candidates=dispatched_candidates,
                    fallback_reason=cast(
                        Literal[
                            "missing_model",
                            "insufficient_evidence",
                            "prompt_too_large",
                            "missing_api_key",
                            "client_error",
                            "invalid_response",
                        ]
                        | None,
                        fallback_reason,
                    ),
                ),
            )
        )

    # Multiple otherwise-valid receipts for one generation indicate a replay or
    # concurrent duplicate dispatch. Exclude that generation entirely rather
    # than letting event ordering choose an authoritative history.
    generation_counts: dict[int, int] = defaultdict(int)
    for _, item in verified:
        generation_counts[item.generation] += 1
    memory = [
        _observed_outcome_for_execution(
            item,
            candidates=candidates,
            feedback_by_id=feedback_by_id,
        )
        for _, item in sorted(
            verified,
            key=lambda pair: (_event_sort_time(pair[0]), pair[0].id),
        )
        if generation_counts[item.generation] == 1
    ]
    return tuple(memory[-MAX_DECISION_MEMORY_ITEMS:])


def _candidate_sort_time(candidate: models.CandidateParameterSet) -> datetime:
    value = candidate.created_at
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _select_candidates(
    candidates: list[models.CandidateParameterSet],
    feedback_by_id: dict[str, CandidateFeedbackView],
) -> tuple[HarnessCandidateEvidence, ...]:
    selected: dict[str, models.CandidateParameterSet] = {}

    def add(candidate: models.CandidateParameterSet) -> None:
        if len(selected) >= MAX_EVIDENCE_CANDIDATES:
            return
        selected[candidate.id] = candidate

    # Preserve the baseline, the strongest measured points, and recent search
    # behavior. This lets the planner see both the incumbent and whether the
    # latest generations are still improving.
    for candidate in sorted(
        (item for item in candidates if item.is_baseline),
        key=lambda item: (_candidate_sort_time(item), item.id),
    ):
        add(candidate)

    def score_order(
        item: models.CandidateParameterSet,
    ) -> tuple[bool, float, int, str]:
        score = feedback_by_id[item.id].score
        return (
            score is None,
            float("inf") if score is None else score,
            item.generation_index,
            item.id,
        )

    strongest = sorted(
        candidates,
        key=score_order,
    )
    best_quota = max(1, (MAX_EVIDENCE_CANDIDATES - len(selected)) // 2)
    for candidate in strongest[:best_quota]:
        add(candidate)

    for candidate in sorted(
        candidates,
        key=lambda item: (
            item.generation_index,
            _candidate_sort_time(item),
            item.id,
        ),
        reverse=True,
    ):
        add(candidate)
    # If recent rows overlap the strongest rows, backfill from the remaining
    # measured history without sacrificing the reserved recent window.
    for candidate in strongest:
        add(candidate)

    ordered = sorted(
        selected.values(),
        key=lambda item: (
            0 if item.is_baseline else 1,
            item.generation_index,
            _candidate_sort_time(item),
            item.id,
        ),
    )
    return tuple(
        _candidate_evidence(candidate, feedback_by_id[candidate.id]) for candidate in ordered
    )


def build_harness_evidence(
    job: models.Job,
    *,
    execution_events: Iterable[models.JobEvent] = (),
    verified_started_decision_ids: Iterable[str] = (),
) -> tuple[HarnessEvidenceSnapshot, bool]:
    """Compile one deterministic provider-safe decision snapshot."""

    candidates = list(job.candidates)
    parameter_names = _registered_parameter_names(job)
    objective_config = (
        job.objective_config_json if isinstance(job.objective_config_json, dict) else {}
    )
    objectives = objective_config.get("objectives")
    constraints = objective_config.get("constraints")
    robust_aggregation = objective_config.get("robust_aggregation")
    if robust_aggregation not in _ALLOWED_ROBUST_AGGREGATIONS:
        robust_aggregation = "unknown"
    used_trials = max(0, int(job.progress_total_trials or 0))
    max_total_trials = max(0, int(job.max_total_trials or 0))
    scenario_suite = (
        schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
        if isinstance(job.scenario_suite_json, dict) and job.scenario_suite_json
        else None
    )
    scenarios = _scenario_evidence(job)
    full_trials_per_candidate = max(
        1,
        scenarios.training_replicate_count + scenarios.validation_replicate_count,
    )
    remaining_trials = max(0, max_total_trials - used_trials)
    feedback_by_id = {
        candidate.id: compile_candidate_feedback(
            candidate,
            scenario_suite=scenario_suite,
        )
        for candidate in candidates
    }
    compact_candidates = _select_candidates(candidates, feedback_by_id)
    objective_profile = cast(
        HarnessObjectiveProfile,
        (
            job.objective_profile
            if job.objective_profile in _ALLOWED_OBJECTIVE_PROFILES
            else "unknown"
        ),
    )
    track_type = cast(
        HarnessTrackType,
        job.track_type if job.track_type in _ALLOWED_TRACK_TYPES else "unknown",
    )
    snapshot = HarnessEvidenceSnapshot(
        job=HarnessJobEvidence(
            objective_profile=objective_profile,
            track_type=track_type,
            parameter_count=len(parameter_names),
            parameter_names=parameter_names,
            objective_count=len(objectives) if isinstance(objectives, list) else 0,
            constraint_count=len(constraints) if isinstance(constraints, list) else 0,
            robust_aggregation=str(robust_aggregation),
        ),
        budget=HarnessBudgetEvidence(
            current_generation=max(0, int(job.current_generation or 0)),
            max_iterations=max(0, int(job.max_iterations or 0)),
            remaining_generations=max(
                0,
                int(job.max_iterations or 0) - int(job.current_generation or 0),
            ),
            used_trials=used_trials,
            max_total_trials=max_total_trials,
            remaining_trials=remaining_trials,
            full_trials_per_candidate=full_trials_per_candidate,
            remaining_full_candidate_capacity=(remaining_trials // full_trials_per_candidate),
        ),
        scenarios=scenarios,
        search=_search_summary(candidates, feedback_by_id),
        tool_history=_tool_history(candidates, feedback_by_id),
        decision_memory=_decision_memory(
            list(execution_events),
            current_generation=max(0, int(job.current_generation or 0)),
            verified_started_decision_ids=frozenset(verified_started_decision_ids),
            candidates=candidates,
            feedback_by_id=feedback_by_id,
        ),
        candidates=compact_candidates,
        candidate_history_total=len(candidates),
        candidate_history_included=len(compact_candidates),
    )
    has_scored_evidence = snapshot.search.scored_candidate_count > 0
    return snapshot, has_scored_evidence


def eligible_harness_tools(
    snapshot: HarnessEvidenceSnapshot,
) -> tuple[HarnessToolId, ...]:
    """Derive the context-compatible closed tool subset.

    This is a capability/precondition gate, not a performance heuristic. The
    model may choose only tools whose minimum evidence and problem-shape
    requirements are already present; the general CMA-ES and deterministic
    portfolio remain available in every state.
    """

    eligible: set[HarnessToolId] = {"cma_es", "optimizer_portfolio"}
    if snapshot.job.constraint_count > 0 or snapshot.job.objective_count > 1:
        eligible.add("constrained_mobo")
    # Reduced-fidelity execution is allowed to remove replicates, but it must
    # preserve at least one run from every configured training case. Therefore
    # a matrix made only of one run per case has no executable lower-fidelity
    # level even when its total run count is greater than one.
    if (
        snapshot.scenarios.training_case_count > 0
        and snapshot.scenarios.training_replicate_count > snapshot.scenarios.training_case_count
    ):
        eligible.add("multi_fidelity_mobo")
    if snapshot.search.scored_candidate_count >= 4 and snapshot.search.feasible_candidate_count > 0:
        eligible.add("turbo")
    if snapshot.job.parameter_count >= 12:
        eligible.add("saasbo")
    if snapshot.search.scored_candidate_count >= 6:
        eligible.add("surrogate_cma_es")
    if snapshot.budget.current_generation >= 2 and (
        snapshot.search.scored_candidate_count >= 6
        or snapshot.search.trailing_stagnant_generations >= 2
    ):
        eligible.add("bipop_cma_es")
    return tuple(tool_id for tool_id in HARNESS_TOOL_DEFINITIONS if tool_id in eligible)


def provider_tool_manifest(
    allowed_tools: Iterable[HarnessToolId] | None = None,
) -> dict[str, object]:
    """Return the deterministic versioned tool manifest shown to the model."""

    selected = (
        tuple(HARNESS_TOOL_DEFINITIONS)
        if allowed_tools is None
        else tuple(dict.fromkeys(allowed_tools))
    )
    if not selected or any(tool_id not in HARNESS_TOOL_DEFINITIONS for tool_id in selected):
        raise ValueError("provider tool manifest requires known allowed tools")

    return {
        "registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        "tools": [
            HARNESS_TOOL_DEFINITIONS[tool_id].model_dump(mode="json") for tool_id in selected
        ],
    }


__all__ = [
    "HARNESS_DECISION_TRACE_SCHEMA_VERSION",
    "HARNESS_EVIDENCE_SCHEMA_VERSION",
    "HARNESS_PROMPT_TEMPLATE_VERSION",
    "HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION",
    "HARNESS_TOOL_DEFINITIONS",
    "HARNESS_TOOL_REGISTRY",
    "HARNESS_TOOL_REGISTRY_VERSION",
    "MAX_DECISION_MEMORY_ITEMS",
    "MAX_GENERATION_TREND_ITEMS",
    "HarnessEvidenceSnapshot",
    "HarnessObservedDecisionOutcome",
    "HarnessToolId",
    "build_harness_evidence",
    "compile_provider_safe_metric",
    "eligible_harness_tools",
    "optimizer_learning_outcome_for_trial",
    "provider_tool_manifest",
]
