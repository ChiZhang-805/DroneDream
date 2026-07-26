"""Closed, versioned decision context for DroneDream's bounded LLM Harness.

The provider-visible snapshot is deliberately compiled from trusted enums,
validated catalog entries, finite measurements, and aggregate counts. User
labels, candidate IDs, parameter values, model prose, errors, scenario IDs,
seeds, and arbitrary JSON never cross this boundary.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field

from app import models, schemas
from app.optimization.outcome_taxonomy import (
    classify_trial_outcome,
    is_optimizer_learning_failure,
    is_optimizer_learning_outcome,
)
from app.optimization.scenarios import scenario_matrix
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

HARNESS_EVIDENCE_SCHEMA_VERSION = "2.4"
HARNESS_TOOL_REGISTRY_VERSION = "2.1"
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


class HarnessJobEvidence(_ClosedModel):
    objective_profile: HarnessObjectiveProfile
    track_type: HarnessTrackType
    parameter_count: int = Field(ge=0)
    parameter_names: tuple[str, ...] = Field(max_length=64)
    objective_count: int = Field(ge=0)
    constraint_count: int = Field(ge=0)
    robust_aggregation: str


class HarnessEvidenceSnapshot(_ClosedModel):
    schema_version: Literal["2.4"] = "2.4"
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


def _candidate_evidence(
    candidate: models.CandidateParameterSet,
) -> HarnessCandidateEvidence:
    aggregate = (
        candidate.aggregated_metric_json
        if isinstance(candidate.aggregated_metric_json, dict)
        else {}
    )
    allowed_metrics: dict[str, JsonMetric] = {}
    for key in _ALLOWED_METRICS:
        if key not in aggregate:
            continue
        compiled = _safe_metric(aggregate.get(key))
        if compiled is not None:
            allowed_metrics[key] = compiled
    trial_count, completed_trial_count, failed_trial_count = _candidate_optimizer_learning_counts(
        candidate
    )
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
        aggregated_score=_finite(candidate.aggregated_score),
        metrics=allowed_metrics,
        trial_count=trial_count,
        completed_trial_count=completed_trial_count,
        failed_trial_count=failed_trial_count,
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


def _candidate_complete(candidate: models.CandidateParameterSet) -> bool:
    return _finite(candidate.aggregated_score) is not None


def _candidate_optimizer_learning_counts(
    candidate: models.CandidateParameterSet,
) -> tuple[int, int, int]:
    """Count only training outcomes allowed to shape parameter search.

    Holdout, infrastructure, cancellation, and invalid-evidence Trials remain
    available to deterministic completeness/health gates outside the provider
    prompt. They cannot make an optimizer family or parameter region look bad
    to the model router.
    """

    learning_count = 0
    completed_count = 0
    failed_count = 0
    for trial in candidate.trials:
        if bool((trial.scenario_config_json or {}).get("holdout")):
            continue
        metric = trial.metric
        usable_metric = (
            trial.status == "COMPLETED"
            and metric is not None
            and _finite(metric.rmse) is not None
            and _finite(metric.max_error) is not None
            and _finite(metric.completion_time) is not None
        )
        outcome_class = classify_trial_outcome(
            status=trial.status,
            failure_code=trial.failure_code,
            usable_metric=usable_metric,
        )
        if not is_optimizer_learning_outcome(outcome_class):
            continue
        learning_count += 1
        if outcome_class == "success":
            completed_count += 1
        elif is_optimizer_learning_failure(outcome_class):
            failed_count += 1
    return learning_count, completed_count, failed_count


def _candidate_feasibility(
    candidate: models.CandidateParameterSet,
) -> bool | None:
    aggregate = (
        candidate.aggregated_metric_json
        if isinstance(candidate.aggregated_metric_json, dict)
        else {}
    )
    value = aggregate.get("feasible")
    return value if isinstance(value, bool) else None


def _search_summary(
    candidates: list[models.CandidateParameterSet],
) -> HarnessSearchSummary:
    scored: list[tuple[models.CandidateParameterSet, float]] = []
    for candidate in candidates:
        score = _finite(candidate.aggregated_score)
        if score is not None:
            scored.append((candidate, score))
    baseline_scores = [score for candidate, score in scored if candidate.is_baseline]
    feasible_or_unknown_scores = [
        score for candidate, score in scored if _candidate_feasibility(candidate) is not False
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

    learning_counts = [_candidate_optimizer_learning_counts(candidate) for candidate in candidates]
    total_trials = sum(counts[0] for counts in learning_counts)
    failed_trials = sum(counts[2] for counts in learning_counts)
    completed_candidates = sum(1 for candidate in candidates if _candidate_complete(candidate))
    feasibility_observations = [
        value
        for candidate in candidates
        if (value := _candidate_feasibility(candidate)) is not None
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
            if (score := _finite(candidate.aggregated_score)) is not None
        ]
        feasible_or_unknown_scores = [
            score
            for candidate in owned
            if (score := _finite(candidate.aggregated_score)) is not None
            and _candidate_feasibility(candidate) is not False
        ]
        scores = feasible_or_unknown_scores or all_scores
        result.append(
            HarnessToolHistory(
                tool_id=tool_id,
                candidate_count=len(owned),
                completed_candidate_count=sum(
                    1 for candidate in owned if _candidate_complete(candidate)
                ),
                feasible_candidate_count=sum(
                    1 for candidate in owned if _candidate_feasibility(candidate) is True
                ),
                total_trial_count=sum(
                    _candidate_optimizer_learning_counts(candidate)[0] for candidate in owned
                ),
                failed_trial_count=sum(
                    _candidate_optimizer_learning_counts(candidate)[2] for candidate in owned
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


def _decision_memory(
    events: list[models.JobEvent],
) -> tuple[HarnessExecutionMemory, ...]:
    """Compile recent execution feedback without replaying provider/model text."""

    memory: list[HarnessExecutionMemory] = []
    for event in sorted(events, key=lambda item: (_event_sort_time(item), item.id)):
        if event.event_type != "harness_tool_execution_result" or not isinstance(
            event.payload_json, dict
        ):
            continue
        payload = event.payload_json
        tool_id = payload.get("tool_id")
        if tool_id not in HARNESS_TOOL_DEFINITIONS:
            continue
        raw_generation = payload.get("generation")
        generation = (
            raw_generation
            if isinstance(raw_generation, int)
            and not isinstance(raw_generation, bool)
            and raw_generation >= 0
            else 0
        )
        raw_count = payload.get("dispatched_candidates")
        dispatched_candidates = (
            raw_count
            if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0
            else 0
        )
        raw_source = payload.get("decision_source")
        decision_source = (
            raw_source if raw_source in {"model", "deterministic_fallback"} else "unknown"
        )
        raw_status = payload.get("status")
        status = raw_status if raw_status in _ALLOWED_EXECUTION_STATUSES else "unknown"
        raw_reason = payload.get("fallback_reason")
        fallback_reason = raw_reason if raw_reason in _ALLOWED_FALLBACK_REASONS else None
        memory.append(
            HarnessExecutionMemory(
                generation=generation,
                tool_id=cast(HarnessToolId, tool_id),
                decision_source=cast(
                    Literal["model", "deterministic_fallback", "unknown"],
                    decision_source,
                ),
                status=cast(
                    Literal[
                        "dispatched",
                        "max_iterations_reached",
                        "budget_exhausted",
                        "search_space_exhausted",
                        "unknown",
                    ],
                    status,
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
            )
        )
    return tuple(memory[-MAX_DECISION_MEMORY_ITEMS:])


def _candidate_sort_time(candidate: models.CandidateParameterSet) -> datetime:
    value = candidate.created_at
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _select_candidates(
    candidates: list[models.CandidateParameterSet],
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
        score = _finite(item.aggregated_score)
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
    return tuple(_candidate_evidence(candidate) for candidate in ordered)


def build_harness_evidence(
    job: models.Job,
    *,
    execution_events: Iterable[models.JobEvent] = (),
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
    scenarios = _scenario_evidence(job)
    full_trials_per_candidate = max(
        1,
        scenarios.training_replicate_count + scenarios.validation_replicate_count,
    )
    remaining_trials = max(0, max_total_trials - used_trials)
    compact_candidates = _select_candidates(candidates)
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
        search=_search_summary(candidates),
        tool_history=_tool_history(candidates),
        decision_memory=_decision_memory(list(execution_events)),
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
    if snapshot.scenarios.training_replicate_count > 1:
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
    "HARNESS_EVIDENCE_SCHEMA_VERSION",
    "HARNESS_TOOL_DEFINITIONS",
    "HARNESS_TOOL_REGISTRY",
    "HARNESS_TOOL_REGISTRY_VERSION",
    "MAX_DECISION_MEMORY_ITEMS",
    "MAX_GENERATION_TREND_ITEMS",
    "HarnessEvidenceSnapshot",
    "HarnessToolId",
    "build_harness_evidence",
    "eligible_harness_tools",
    "provider_tool_manifest",
]
