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
HarnessTrackType = Literal["hover", "circle", "u_turn", "lemniscate", "custom", "unknown"]
HarnessScenarioType = Literal[
    "nominal",
    "noise_perturbed",
    "wind_perturbed",
    "combined_perturbed",
    "turbulence",
    "gps_dropout",
    "payload_changed",
    "battery_degraded",
    "actuator_delay",
    "actuator_failure",
    "custom",
]
HarnessSensorNoiseLevel = Literal["low", "medium", "high", "unknown"]
HarnessPlanPhase = Literal[
    "exploration",
    "recovery",
    "refinement",
    "diversification",
    "verification",
    "balanced",
]
HarnessBatchPolicy = Literal["conservative", "balanced", "broad"]
HarnessPlanReason = Literal[
    "final_generation",
    "single_full_candidate_remaining",
    "high_domain_failure_rate",
    "insufficient_scored_history",
    "no_feasible_candidate",
    "stagnation_detected",
    "recent_verified_improvement",
    "stable_progress",
]

HARNESS_EVIDENCE_SCHEMA_VERSION = "2.9"
HARNESS_TOOL_REGISTRY_VERSION = "2.1"
HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION = "1.1"
HARNESS_PROMPT_TEMPLATE_VERSION = "1.7"
HARNESS_DECISION_TRACE_SCHEMA_VERSION = "1.4"
MAX_EVIDENCE_CANDIDATES = 12
MAX_DECISION_MEMORY_ITEMS = 8
MAX_GENERATION_PLAN_HISTORY_ITEMS = 8
MAX_CROSS_JOB_EXPERIENCE_ITEMS = 6
MAX_GENERATION_TREND_ITEMS = 32

_ALLOWED_SOURCE_TYPES = frozenset({"baseline", "optimizer", "llm_optimizer"})
_ALLOWED_OBJECTIVE_PROFILES = frozenset({"stable", "fast", "smooth", "robust", "custom"})
_ALLOWED_TRACK_TYPES = frozenset({"hover", "circle", "u_turn", "lemniscate", "custom"})
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
        "actuator_failure",
        "custom",
    }
)
_ALLOWED_ROBUST_AGGREGATIONS = frozenset({"mean", "worst", "cvar", "percentile"})
_SAFE_SCENARIO_PERTURBATION_RANGES: dict[str, tuple[float, float]] = {
    "wind_mps": (0.0, 30.0),
    "dropout_rate": (0.0, 1.0),
    "mass_payload_kg": (0.0, 20.0),
    "delay_ms": (0.0, 250.0),
    "motor_number": (0.0, 3.0),
    "intensity": (0.0, 2.0),
}
_SAFE_PERTURBATIONS_BY_SCENARIO_TYPE: dict[str, frozenset[str]] = {
    "wind_perturbed": frozenset({"wind_mps"}),
    "gps_dropout": frozenset({"dropout_rate"}),
    "payload_changed": frozenset({"mass_payload_kg"}),
    "actuator_delay": frozenset({"delay_ms"}),
    "actuator_failure": frozenset({"motor_number"}),
    "turbulence": frozenset({"intensity"}),
    "combined_perturbed": frozenset(_SAFE_SCENARIO_PERTURBATION_RANGES),
}
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
_ALLOWED_PLAN_PHASES = frozenset(
    {
        "exploration",
        "recovery",
        "refinement",
        "diversification",
        "verification",
        "balanced",
    }
)
_ALLOWED_BATCH_POLICIES = frozenset({"conservative", "balanced", "broad"})

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

_PHASE_COMPATIBLE_SEARCH_ROLES: dict[
    HarnessPlanPhase,
    frozenset[
        Literal[
            "general",
            "constraint_aware",
            "multi_fidelity",
            "local_exploitation",
            "sparse_high_dimension",
            "surrogate_evolution",
            "restart_exploration",
            "balanced_fallback",
        ]
    ],
] = {
    "exploration": frozenset(
        {
            "general",
            "constraint_aware",
            "multi_fidelity",
            "sparse_high_dimension",
            "restart_exploration",
            "balanced_fallback",
        }
    ),
    "recovery": frozenset(
        {
            "general",
            "constraint_aware",
            "restart_exploration",
            "balanced_fallback",
        }
    ),
    "refinement": frozenset(
        {
            "general",
            "constraint_aware",
            "local_exploitation",
            "surrogate_evolution",
            "balanced_fallback",
        }
    ),
    "diversification": frozenset(
        {
            "general",
            "constraint_aware",
            "multi_fidelity",
            "sparse_high_dimension",
            "surrogate_evolution",
            "restart_exploration",
            "balanced_fallback",
        }
    ),
    "verification": frozenset(
        {
            "general",
            "constraint_aware",
            "local_exploitation",
            "surrogate_evolution",
            "balanced_fallback",
        }
    ),
    "balanced": frozenset(
        {
            "general",
            "constraint_aware",
            "multi_fidelity",
            "local_exploitation",
            "sparse_high_dimension",
            "surrogate_evolution",
            "restart_exploration",
            "balanced_fallback",
        }
    ),
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


class HarnessPlanningEvidence(_ClosedModel):
    """Deterministic receding-horizon plan for the next bounded generation.

    The plan is compiled from provider-safe evidence. The model may select a
    compatible optimizer, but it cannot enlarge the batch policy or carry a
    stale multi-step plan past the next observed generation.
    """

    schema_id: Literal["dronedream.harness-receding-plan/v1"] = (
        "dronedream.harness-receding-plan/v1"
    )
    phase: HarnessPlanPhase
    batch_policy: HarnessBatchPolicy
    horizon_generations: Literal[1] = 1
    replan_after_generation: Literal[True] = True
    reason_codes: tuple[HarnessPlanReason, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def _validate_phase_policy(self) -> HarnessPlanningEvidence:
        expected = {
            "exploration": "broad",
            "recovery": "conservative",
            "refinement": "balanced",
            "diversification": "broad",
            "verification": "conservative",
            "balanced": "balanced",
        }[self.phase]
        if self.batch_policy != expected:
            raise ValueError("planning phase and batch policy are inconsistent")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("planning reason codes must be unique")
        return self


class HarnessTrainingScenarioProfile(_ClosedModel):
    """Anonymous, bounded description of one provider-visible training case."""

    case_alias: str = Field(pattern=r"^training_case_[1-9][0-9]?$")
    scenario_type: HarnessScenarioType
    replicate_count: int = Field(ge=1, le=100)
    weight_share: float = Field(gt=0.0, le=1.0)
    safe_perturbations: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_safe_perturbations(self) -> HarnessTrainingScenarioProfile:
        for key, value in self.safe_perturbations.items():
            bounds = _SAFE_SCENARIO_PERTURBATION_RANGES.get(key)
            if (
                bounds is None
                or key
                not in _SAFE_PERTURBATIONS_BY_SCENARIO_TYPE.get(
                    self.scenario_type,
                    frozenset(),
                )
                or not math.isfinite(value)
                or not bounds[0] <= value <= bounds[1]
            ):
                raise ValueError("training scenario contains an unsafe perturbation")
        return self


class HarnessEnvironmentEvidence(_ClosedModel):
    """Provider-safe job-wide simulation conditions with no user-authored prose."""

    steady_wind_component_l1_mps: float = Field(ge=0.0, le=40.0)
    sensor_noise_level: HarnessSensorNoiseLevel
    advanced_config_present: bool
    gust_magnitude_mps: float | None = Field(default=None, ge=0.0, le=30.0)
    gust_period_s: float | None = Field(default=None, gt=0.0, le=300.0)
    obstacle_count: int = Field(ge=0, le=512)
    gps_noise_m: float = Field(ge=0.0, le=100.0)
    baro_noise_m: float = Field(ge=0.0, le=100.0)
    imu_noise_scale: float = Field(ge=0.0, le=10.0)
    sensor_dropout_rate: float = Field(ge=0.0, le=1.0)
    battery_initial_percent: float = Field(ge=0.0, le=100.0)
    voltage_sag: bool
    mass_payload_kg: float | None = Field(default=None, ge=0.0, le=20.0)

    @model_validator(mode="after")
    def _validate_gust_pair(self) -> HarnessEnvironmentEvidence:
        if (self.gust_magnitude_mps is None) != (self.gust_period_s is None):
            raise ValueError("enabled gust evidence requires both magnitude and period")
        return self


class HarnessScenarioEvidence(_ClosedModel):
    training_case_count: int = Field(ge=0)
    validation_case_count: int = Field(ge=0)
    training_replicate_count: int = Field(ge=0)
    validation_replicate_count: int = Field(ge=0)
    training_type_counts: dict[str, int] = Field(default_factory=dict)
    training_replicate_min: int = Field(ge=0)
    training_replicate_max: int = Field(ge=0)
    training_weight_concentration: float = Field(ge=0.0, le=1.0)
    effective_training_case_count: float = Field(ge=0.0, le=64.0)
    training_cases: tuple[HarnessTrainingScenarioProfile, ...] = Field(
        default=(),
        max_length=64,
    )
    environment: HarnessEnvironmentEvidence
    common_random_numbers: bool | None = None

    @model_validator(mode="after")
    def _validate_training_profile(self) -> HarnessScenarioEvidence:
        if len(self.training_cases) != self.training_case_count:
            raise ValueError("training case profile count does not match aggregate count")
        if self.training_case_count == 0:
            if (
                self.training_replicate_count != 0
                or self.training_replicate_min != 0
                or self.training_replicate_max != 0
                or self.training_weight_concentration != 0.0
                or self.effective_training_case_count != 0.0
            ):
                raise ValueError("empty training suite cannot contain profile aggregates")
            return self
        replicate_counts = [case.replicate_count for case in self.training_cases]
        if (
            sum(replicate_counts) != self.training_replicate_count
            or min(replicate_counts) != self.training_replicate_min
            or max(replicate_counts) != self.training_replicate_max
        ):
            raise ValueError("training replicate aggregates do not match case profiles")
        if not math.isclose(
            sum(case.weight_share for case in self.training_cases),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError("training case weight shares must sum to one")
        return self


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
    plan_phase: HarnessPlanPhase
    batch_policy: HarnessBatchPolicy
    status: Literal[
        "dispatched",
        "max_iterations_reached",
        "budget_exhausted",
        "search_space_exhausted",
        "unknown",
    ]
    dispatched_candidates: int = Field(ge=0)
    planned_candidates: int = Field(ge=0)
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
        if self.status == "dispatched" and not (
            1 <= self.dispatched_candidates <= self.planned_candidates
        ):
            raise ValueError("dispatched execution requires a covering positive plan")
        if self.status == "search_space_exhausted" and not (
            self.dispatched_candidates == 0 and self.planned_candidates >= 1
        ):
            raise ValueError("search exhaustion requires a positive attempted plan")
        if self.status in {"max_iterations_reached", "budget_exhausted"} and (
            self.dispatched_candidates != 0 or self.planned_candidates != 0
        ):
            raise ValueError("pre-dispatch terminal status cannot carry a candidate plan")
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


class HarnessToolCallExecutionMemory(_ClosedModel):
    """Provider-safe cost/result projection for one pure proposal-tool call."""

    tool_id: HarnessToolId
    allocation: int = Field(ge=1, le=8)
    parallel_safe: bool
    status: Literal["completed", "tool_error", "cost_budget_exceeded"]
    proposal_count: int = Field(ge=0, le=8)
    elapsed_ms: float = Field(ge=0.0, le=600_000.0)
    cpu_ms: float = Field(ge=0.0, le=600_000.0)
    latency_budget_ms: int = Field(ge=1, le=120_000)
    cpu_budget_ms: int = Field(ge=1, le=120_000)

    @model_validator(mode="after")
    def _validate_execution_result(self) -> HarnessToolCallExecutionMemory:
        if self.proposal_count > self.allocation:
            raise ValueError("tool proposal count exceeds its allocation")
        if self.status != "completed" and self.proposal_count != 0:
            raise ValueError("failed or over-budget tool calls cannot retain proposals")
        return self


class HarnessGenerationPlanMemory(_ClosedModel):
    """Verified, de-identified plan/cost/result history for one generation."""

    schema_id: Literal["dronedream.harness-generation-plan-memory/v1"] = (
        "dronedream.harness-generation-plan-memory/v1"
    )
    generation: int = Field(ge=1)
    decision_source: Literal["model", "deterministic_fallback"]
    revision_source: Literal["model", "deterministic_fallback", "not_applicable"]
    status: Literal["dispatched", "search_space_exhausted", "stop_accepted"]
    planned_candidates: int = Field(ge=0, le=8)
    usable_proposal_count: int = Field(ge=0, le=32)
    dispatched_candidates: int = Field(ge=0, le=8)
    dispatched_trials: int = Field(ge=0)
    projected_trial_upper_bound: int = Field(ge=0)
    projected_critical_path_latency_budget_ms: int = Field(ge=0, le=600_000)
    projected_cpu_budget_ms: int = Field(ge=0, le=600_000)
    plan_decision_wall_ms: float = Field(ge=0.0, le=600_000.0)
    revision_wall_ms: float = Field(ge=0.0, le=600_000.0)
    tool_execution_wall_ms: float = Field(ge=0.0, le=600_000.0)
    actual_tool_cpu_ms: float = Field(ge=0.0, le=600_000.0)
    provider_call_count: int = Field(ge=0, le=2)
    tool_calls: tuple[HarnessToolCallExecutionMemory, ...] = Field(
        default=(),
        max_length=4,
    )

    @model_validator(mode="after")
    def _validate_generation_result(self) -> HarnessGenerationPlanMemory:
        if self.status == "stop_accepted":
            if (
                self.revision_source != "not_applicable"
                or self.planned_candidates != 0
                or self.usable_proposal_count != 0
                or self.dispatched_candidates != 0
                or self.dispatched_trials != 0
                or self.projected_trial_upper_bound != 0
                or self.projected_critical_path_latency_budget_ms != 0
                or self.projected_cpu_budget_ms != 0
                or self.revision_wall_ms != 0.0
                or self.tool_execution_wall_ms != 0.0
                or self.actual_tool_cpu_ms != 0.0
                or self.tool_calls
            ):
                raise ValueError("accepted stop cannot claim plan or tool execution")
            return self
        if not self.tool_calls or self.revision_source == "not_applicable":
            raise ValueError("continued generations require tool and revision history")
        if self.planned_candidates < 1 or self.projected_trial_upper_bound < 1:
            raise ValueError("continued generations require a positive compiled plan")
        if self.usable_proposal_count > sum(
            call.proposal_count for call in self.tool_calls
        ):
            raise ValueError("usable proposals exceed completed tool output")
        if self.status == "dispatched":
            if not (
                1 <= self.dispatched_candidates <= self.usable_proposal_count
                and self.dispatched_candidates <= self.planned_candidates
                and 1 <= self.dispatched_trials <= self.projected_trial_upper_bound
            ):
                raise ValueError("dispatched generation exceeds verified plan output")
        elif self.dispatched_candidates != 0 or self.dispatched_trials != 0:
            raise ValueError("search exhaustion cannot claim a dispatch")
        return self


class HarnessCrossJobExperience(_ClosedModel):
    """Provider-safe projection of one verified prior-Job cohort.

    Ownership and source identifiers, raw text, parameters, seeds, holdout
    details, and exact timestamps are deliberately absent.
    """

    schema_id: Literal["dronedream.harness-cross-job-experience/v1"] = (
        "dronedream.harness-cross-job-experience/v1"
    )
    match_quality: Literal["exact_task_family"] = "exact_task_family"
    scenario_similarity: float = Field(ge=0.0, le=1.0)
    tool_id: HarnessToolId
    decision_source: Literal["model", "deterministic_fallback"]
    plan_phase: HarnessPlanPhase
    batch_policy: HarnessBatchPolicy
    dispatched_candidates: int = Field(ge=1)
    planned_candidates: int = Field(ge=1)
    observed_outcome: HarnessObservedDecisionOutcome

    @model_validator(mode="after")
    def _validate_dispatch(self) -> HarnessCrossJobExperience:
        if self.dispatched_candidates > self.planned_candidates:
            raise ValueError("cross-Job experience dispatch exceeds its plan")
        return self


class HarnessCrossJobMemory(_ClosedModel):
    """Closed retrieval result with an explicit non-causal claim boundary."""

    schema_id: Literal["dronedream.harness-cross-job-memory/v1"] = (
        "dronedream.harness-cross-job-memory/v1"
    )
    retrieval_policy_version: Literal["1.0"] = "1.0"
    retention_days: Literal[90] = 90
    scope: Literal["same_authenticated_user"] = "same_authenticated_user"
    task_family_policy: Literal["exact_structural_match"] = "exact_structural_match"
    claim_boundary: Literal["observational_not_causal"] = "observational_not_causal"
    experiences: tuple[HarnessCrossJobExperience, ...] = Field(
        default=(),
        max_length=MAX_CROSS_JOB_EXPERIENCE_ITEMS,
    )


class HarnessJobEvidence(_ClosedModel):
    objective_profile: HarnessObjectiveProfile
    track_type: HarnessTrackType
    parameter_count: int = Field(ge=0)
    parameter_names: tuple[str, ...] = Field(max_length=64)
    objective_count: int = Field(ge=0)
    constraint_count: int = Field(ge=0)
    robust_aggregation: str


class HarnessEvidenceSnapshot(_ClosedModel):
    schema_version: Literal["2.9"] = "2.9"
    job: HarnessJobEvidence
    budget: HarnessBudgetEvidence
    plan: HarnessPlanningEvidence
    scenarios: HarnessScenarioEvidence
    search: HarnessSearchSummary
    tool_history: tuple[HarnessToolHistory, ...] = ()
    decision_memory: tuple[HarnessExecutionMemory, ...] = Field(
        default=(),
        max_length=MAX_DECISION_MEMORY_ITEMS,
    )
    generation_plan_history: tuple[HarnessGenerationPlanMemory, ...] = Field(
        default=(),
        max_length=MAX_GENERATION_PLAN_HISTORY_ITEMS,
    )
    cross_job_memory: HarnessCrossJobMemory = Field(
        default_factory=HarnessCrossJobMemory
    )
    candidates: tuple[HarnessCandidateEvidence, ...] = Field(max_length=MAX_EVIDENCE_CANDIDATES)
    candidate_history_total: int = Field(ge=0)
    candidate_history_included: int = Field(ge=0)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _safe_training_perturbations(
    case: schemas.ScenarioCaseConfig,
) -> dict[str, float]:
    allowed = _SAFE_PERTURBATIONS_BY_SCENARIO_TYPE.get(
        case.scenario_type,
        frozenset(),
    )
    compiled: dict[str, float] = {}
    for key in sorted(allowed):
        numeric = _finite(case.config.get(key))
        bounds = _SAFE_SCENARIO_PERTURBATION_RANGES[key]
        if numeric is not None and bounds[0] <= numeric <= bounds[1]:
            compiled[key] = numeric
    return compiled


def _environment_evidence(job: models.Job) -> HarnessEnvironmentEvidence:
    wind = schemas.WindVector(
        north=float(job.wind_north),
        east=float(job.wind_east),
        south=float(job.wind_south),
        west=float(job.wind_west),
    )
    raw_advanced = job.advanced_scenario_config_json
    if raw_advanced is not None and not isinstance(raw_advanced, dict):
        raise ValueError("advanced scenario config must be an object")
    advanced = schemas.AdvancedScenarioConfig(**(raw_advanced or {}))
    gusts = advanced.wind_gusts
    sensor_noise_level = (
        job.sensor_noise_level if job.sensor_noise_level in {"low", "medium", "high"} else "unknown"
    )
    return HarnessEnvironmentEvidence(
        steady_wind_component_l1_mps=sum(
            abs(value)
            for value in (
                wind.north,
                wind.east,
                wind.south,
                wind.west,
            )
        ),
        sensor_noise_level=cast(HarnessSensorNoiseLevel, sensor_noise_level),
        advanced_config_present=raw_advanced is not None,
        gust_magnitude_mps=gusts.magnitude_mps if gusts.enabled else None,
        gust_period_s=gusts.period_s if gusts.enabled else None,
        obstacle_count=len(advanced.obstacles),
        gps_noise_m=advanced.sensor_degradation.gps_noise_m,
        baro_noise_m=advanced.sensor_degradation.baro_noise_m,
        imu_noise_scale=advanced.sensor_degradation.imu_noise_scale,
        sensor_dropout_rate=advanced.sensor_degradation.dropout_rate,
        battery_initial_percent=advanced.battery.initial_percent,
        voltage_sag=advanced.battery.voltage_sag,
        mass_payload_kg=advanced.battery.mass_payload_kg,
    )


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


def compile_harness_scenario_evidence(job: models.Job) -> HarnessScenarioEvidence:
    raw_suite = job.scenario_suite_json if isinstance(job.scenario_suite_json, dict) else {}
    environment = _environment_evidence(job)
    if not raw_suite:
        replicate_count = max(1, int(job.trials_per_candidate or 1))
        return HarnessScenarioEvidence(
            training_case_count=1,
            validation_case_count=0,
            training_replicate_count=replicate_count,
            validation_replicate_count=0,
            training_type_counts={"nominal": 1},
            training_replicate_min=replicate_count,
            training_replicate_max=replicate_count,
            training_weight_concentration=1.0,
            effective_training_case_count=1.0,
            training_cases=(
                HarnessTrainingScenarioProfile(
                    case_alias="training_case_1",
                    scenario_type="nominal",
                    replicate_count=replicate_count,
                    weight_share=1.0,
                ),
            ),
            environment=environment,
            common_random_numbers=None,
        )
    suite = schemas.ScenarioSuiteConfig(**raw_suite)
    runs = scenario_matrix(suite)
    type_counts: dict[str, int] = defaultdict(int)
    training_cases = [case for case in suite.cases if case.enabled and not case.holdout]
    validation_case_count = 0
    for case in suite.cases:
        if not case.enabled:
            continue
        if case.holdout:
            validation_case_count += 1
            continue
        if case.scenario_type in _ALLOWED_SCENARIO_TYPES:
            type_counts[str(case.scenario_type)] += 1
    total_training_weight = sum(case.weight for case in training_cases)
    case_profiles = tuple(
        HarnessTrainingScenarioProfile(
            case_alias=f"training_case_{index + 1}",
            scenario_type=case.scenario_type,
            replicate_count=len(case.seeds),
            weight_share=(case.weight / total_training_weight),
            safe_perturbations=_safe_training_perturbations(case),
        )
        for index, case in enumerate(training_cases)
    )
    replicate_counts = [case.replicate_count for case in case_profiles]
    weight_shares = [case.weight_share for case in case_profiles]
    return HarnessScenarioEvidence(
        training_case_count=len(training_cases),
        validation_case_count=validation_case_count,
        training_replicate_count=sum(1 for run in runs if not run.holdout),
        validation_replicate_count=sum(1 for run in runs if run.holdout),
        training_type_counts=dict(sorted(type_counts.items())),
        training_replicate_min=min(replicate_counts),
        training_replicate_max=max(replicate_counts),
        training_weight_concentration=max(weight_shares),
        effective_training_case_count=(1.0 / sum(share**2 for share in weight_shares)),
        training_cases=case_profiles,
        environment=environment,
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

    generation_scores: dict[int, list[tuple[float, bool | None]]] = defaultdict(list)
    for candidate, score in scored:
        generation_scores[max(0, int(candidate.generation_index or 0))].append(
            (score, _candidate_feasibility(feedback_by_id[candidate.id]))
        )
    incumbent: float | None = None
    incumbent_is_non_infeasible = False
    trailing_stagnation = 0
    full_best_items: list[HarnessGenerationBest] = []
    for generation, values in sorted(generation_scores.items()):
        non_infeasible = [score for score, feasible in values if feasible is not False]
        generation_is_non_infeasible = bool(non_infeasible)
        generation_best = min(non_infeasible or [score for score, _ in values])
        if incumbent is None:
            incumbent = generation_best
            incumbent_is_non_infeasible = generation_is_non_infeasible
            trailing_stagnation = 0
        elif generation_is_non_infeasible and not incumbent_is_non_infeasible:
            incumbent = generation_best
            incumbent_is_non_infeasible = True
            trailing_stagnation = 0
        elif generation_is_non_infeasible and generation_best < incumbent - 1e-12:
            incumbent = generation_best
            trailing_stagnation = 0
        else:
            trailing_stagnation += 1
            if incumbent_is_non_infeasible and not generation_is_non_infeasible:
                generation_best = incumbent
        full_best_items.append(
            HarnessGenerationBest(
                generation=generation,
                best_score=generation_best,
            )
        )
    full_best_by_generation = tuple(full_best_items)
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
        plan_phase = decision_payload.get("plan_phase")
        batch_policy = decision_payload.get("batch_policy")
        if (
            plan_phase not in _ALLOWED_PLAN_PHASES
            or batch_policy not in _ALLOWED_BATCH_POLICIES
            or result_payload.get("plan_phase") != plan_phase
            or result_payload.get("batch_policy") != batch_policy
        ):
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
        planned_candidates = _bounded_int(result_payload.get("planned_candidates"))
        if (
            raw_status not in _ALLOWED_EXECUTION_STATUSES
            or dispatched_candidates is None
            or planned_candidates is None
            or (raw_status == "dispatched" and dispatched_candidates == 0)
            or (raw_status != "dispatched" and dispatched_candidates != 0)
            or (raw_status == "dispatched" and planned_candidates < dispatched_candidates)
            or (raw_status == "search_space_exhausted" and planned_candidates < 1)
            or (
                raw_status in {"max_iterations_reached", "budget_exhausted"}
                and planned_candidates != 0
            )
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
                    plan_phase=cast(HarnessPlanPhase, plan_phase),
                    batch_policy=cast(HarnessBatchPolicy, batch_policy),
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
                    planned_candidates=planned_candidates,
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


def compile_harness_plan(
    *,
    parameter_count: int,
    budget: HarnessBudgetEvidence,
    search: HarnessSearchSummary,
    decision_memory: tuple[HarnessExecutionMemory, ...],
) -> HarnessPlanningEvidence:
    """Compile the next safe planning phase from bounded observed evidence.

    This is a one-generation receding-horizon plan, not an open-loop schedule.
    Every dispatched cohort must be observed before a later phase is compiled.
    Validation-only outcomes never enter the failure or improvement signals.
    """

    reasons: list[HarnessPlanReason] = []
    if budget.remaining_generations <= 1:
        reasons.append("final_generation")
    if budget.remaining_full_candidate_capacity <= 1:
        reasons.append("single_full_candidate_remaining")
    if reasons:
        return HarnessPlanningEvidence(
            phase="verification",
            batch_policy="conservative",
            reason_codes=tuple(reasons[:3]),
        )

    latest_outcome = next(
        (
            item.observed_outcome
            for item in reversed(decision_memory)
            if item.reflection_status == "verified_complete" and item.observed_outcome is not None
        ),
        None,
    )
    latest_domain_failure_rate = (
        latest_outcome.domain_failure_trial_count / latest_outcome.optimizer_learning_trial_count
        if latest_outcome is not None and latest_outcome.optimizer_learning_trial_count > 0
        else 0.0
    )
    if latest_domain_failure_rate >= 0.35 or (
        search.completed_candidate_count >= 2 and search.observed_failure_rate >= 0.45
    ):
        return HarnessPlanningEvidence(
            phase="recovery",
            batch_policy="conservative",
            reason_codes=("high_domain_failure_rate",),
        )

    minimum_history = max(4, min(8, max(0, parameter_count) + 1))
    if search.scored_candidate_count < minimum_history:
        reasons.append("insufficient_scored_history")
    if search.feasible_candidate_count == 0:
        reasons.append("no_feasible_candidate")
    if reasons:
        return HarnessPlanningEvidence(
            phase="exploration",
            batch_policy="broad",
            reason_codes=tuple(reasons[:3]),
        )

    if search.trailing_stagnant_generations >= 2:
        return HarnessPlanningEvidence(
            phase="diversification",
            batch_policy="broad",
            reason_codes=("stagnation_detected",),
        )

    if latest_outcome is not None and (
        latest_outcome.observed_absolute_improvement is not None
        and latest_outcome.observed_absolute_improvement > 0.0
    ):
        return HarnessPlanningEvidence(
            phase="refinement",
            batch_policy="balanced",
            reason_codes=("recent_verified_improvement",),
        )

    return HarnessPlanningEvidence(
        phase="balanced",
        batch_policy="balanced",
        reason_codes=("stable_progress",),
    )


def build_harness_evidence(
    job: models.Job,
    *,
    execution_events: Iterable[models.JobEvent] = (),
    verified_started_decision_ids: Iterable[str] = (),
    generation_plan_history: Iterable[HarnessGenerationPlanMemory] = (),
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
    scenarios = compile_harness_scenario_evidence(job)
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
    budget = HarnessBudgetEvidence(
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
    )
    search = _search_summary(candidates, feedback_by_id)
    decision_memory = _decision_memory(
        list(execution_events),
        current_generation=max(0, int(job.current_generation or 0)),
        verified_started_decision_ids=frozenset(verified_started_decision_ids),
        candidates=candidates,
        feedback_by_id=feedback_by_id,
    )
    plan = compile_harness_plan(
        parameter_count=len(parameter_names),
        budget=budget,
        search=search,
        decision_memory=decision_memory,
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
        budget=budget,
        plan=plan,
        scenarios=scenarios,
        search=search,
        tool_history=_tool_history(candidates, feedback_by_id),
        decision_memory=decision_memory,
        generation_plan_history=tuple(generation_plan_history)[
            -MAX_GENERATION_PLAN_HISTORY_ITEMS:
        ],
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


def selectable_harness_tools(
    snapshot: HarnessEvidenceSnapshot,
) -> tuple[HarnessToolId, ...]:
    """Apply both execution-capability and current planning-phase gates.

    The capability gate answers whether a tool can run against the current
    evidence shape. This second authority boundary removes tools whose search
    role conflicts with the deterministic one-generation plan. Provider
    schemas, manifests, response validation, and trace verification all use
    this same set, so prompt text cannot widen the executable surface.
    """

    eligible = eligible_harness_tools(snapshot)
    compatible_roles = _PHASE_COMPATIBLE_SEARCH_ROLES[snapshot.plan.phase]
    selectable = tuple(
        tool_id
        for tool_id in eligible
        if HARNESS_TOOL_DEFINITIONS[tool_id].search_role in compatible_roles
    )
    if not selectable or "optimizer_portfolio" not in selectable:
        raise ValueError("Harness phase policy must preserve a deterministic fallback")
    return selectable


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
    "MAX_GENERATION_PLAN_HISTORY_ITEMS",
    "MAX_CROSS_JOB_EXPERIENCE_ITEMS",
    "MAX_GENERATION_TREND_ITEMS",
    "HarnessEvidenceSnapshot",
    "HarnessGenerationPlanMemory",
    "HarnessCrossJobExperience",
    "HarnessCrossJobMemory",
    "HarnessEnvironmentEvidence",
    "HarnessObservedDecisionOutcome",
    "HarnessPlanningEvidence",
    "HarnessScenarioEvidence",
    "HarnessScenarioType",
    "HarnessTrainingScenarioProfile",
    "HarnessToolId",
    "HarnessToolCallExecutionMemory",
    "build_harness_evidence",
    "compile_harness_plan",
    "compile_harness_scenario_evidence",
    "compile_provider_safe_metric",
    "eligible_harness_tools",
    "optimizer_learning_outcome_for_trial",
    "provider_tool_manifest",
    "selectable_harness_tools",
]
