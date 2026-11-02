"""Strict, cost-accounted multi-tool plans for bounded Harness generations.

The provider may propose allocations and a stop recommendation, but this module
keeps authority in deterministic code.  A plan is accepted only against one
immutable budget opportunity, compiled into canonical tool order, and optionally
followed by one bounded candidate-strategy turn after pure proposal tools return.
That second turn may author one candidate hypothesis inside an explicit parameter
domain. Deterministic code validates it and remains the sole owner of Trials,
seeds, execution, qualification, holdout, and the frozen budget.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.orchestration.harness_context import HarnessToolId

HARNESS_BUDGET_PLAN_SCHEMA_VERSION = "1.0"
HARNESS_BUDGET_POLICY_VERSION = "1.0"
HARNESS_BUDGET_PROMPT_VERSION = "1.0"
HARNESS_PLAN_REVISION_SCHEMA_VERSION = "1.0"
HARNESS_PLAN_REVISION_PROMPT_VERSION = "1.1"

HarnessPlanDecision = Literal["continue", "stop"]
HarnessFidelityMode = Literal["auto", "force_full"]
HarnessStopReason = Literal[
    "acceptance_satisfied",
    "converged",
    "budget_efficiency_stalled",
]
HarnessPlanFocus = Literal[
    "constraints",
    "diversity",
    "failure_recovery",
    "local_improvement",
    "multi_fidelity_screening",
    "sparse_axes",
    "verification",
]
HarnessUncertaintyLevel = Literal["low", "medium", "high"]
HarnessMissingEvidence = Literal[
    "constraint_boundary",
    "cross_job_transfer",
    "feasible_incumbent",
    "full_fidelity_outcome",
    "local_curvature",
    "tool_cost_history",
]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class HarnessToolBudget(_ClosedModel):
    """One eligible proposal tool and its deterministic allocation ceilings."""

    tool_id: HarnessToolId
    maximum_allocation: int = Field(ge=1, le=8)
    parallel_safe: bool
    base_latency_budget_ms: int = Field(ge=1, le=120_000)
    per_candidate_latency_budget_ms: int = Field(ge=0, le=120_000)
    base_cpu_budget_ms: int = Field(ge=1, le=120_000)
    per_candidate_cpu_budget_ms: int = Field(ge=0, le=120_000)

    def latency_budget_ms(self, allocation: int) -> int:
        if isinstance(allocation, bool) or not isinstance(allocation, int) or allocation < 1:
            raise ValueError("allocation must be a positive integer")
        return self.base_latency_budget_ms + self.per_candidate_latency_budget_ms * allocation

    def cpu_budget_ms(self, allocation: int) -> int:
        if isinstance(allocation, bool) or not isinstance(allocation, int) or allocation < 1:
            raise ValueError("allocation must be a positive integer")
        return self.base_cpu_budget_ms + self.per_candidate_cpu_budget_ms * allocation


_DEFAULT_TOOL_BUDGETS: dict[HarnessToolId, HarnessToolBudget] = {
    "cma_es": HarnessToolBudget(
        tool_id="cma_es",
        maximum_allocation=1,
        parallel_safe=True,
        base_latency_budget_ms=400,
        per_candidate_latency_budget_ms=200,
        base_cpu_budget_ms=400,
        per_candidate_cpu_budget_ms=200,
    ),
    "constrained_mobo": HarnessToolBudget(
        tool_id="constrained_mobo",
        maximum_allocation=4,
        parallel_safe=True,
        base_latency_budget_ms=2_500,
        per_candidate_latency_budget_ms=750,
        base_cpu_budget_ms=2_500,
        per_candidate_cpu_budget_ms=750,
    ),
    "multi_fidelity_mobo": HarnessToolBudget(
        tool_id="multi_fidelity_mobo",
        maximum_allocation=4,
        parallel_safe=True,
        base_latency_budget_ms=2_500,
        per_candidate_latency_budget_ms=750,
        base_cpu_budget_ms=2_500,
        per_candidate_cpu_budget_ms=750,
    ),
    "turbo": HarnessToolBudget(
        tool_id="turbo",
        maximum_allocation=4,
        parallel_safe=True,
        base_latency_budget_ms=2_000,
        per_candidate_latency_budget_ms=600,
        base_cpu_budget_ms=2_000,
        per_candidate_cpu_budget_ms=600,
    ),
    "saasbo": HarnessToolBudget(
        tool_id="saasbo",
        maximum_allocation=4,
        parallel_safe=True,
        base_latency_budget_ms=2_250,
        per_candidate_latency_budget_ms=650,
        base_cpu_budget_ms=2_250,
        per_candidate_cpu_budget_ms=650,
    ),
    "surrogate_cma_es": HarnessToolBudget(
        tool_id="surrogate_cma_es",
        maximum_allocation=4,
        parallel_safe=True,
        base_latency_budget_ms=1_500,
        per_candidate_latency_budget_ms=500,
        base_cpu_budget_ms=1_500,
        per_candidate_cpu_budget_ms=500,
    ),
    "bipop_cma_es": HarnessToolBudget(
        tool_id="bipop_cma_es",
        maximum_allocation=4,
        parallel_safe=True,
        base_latency_budget_ms=1_500,
        per_candidate_latency_budget_ms=500,
        base_cpu_budget_ms=1_500,
        per_candidate_cpu_budget_ms=500,
    ),
    # The portfolio already invokes several children and therefore occupies the
    # serial lane when mixed with separately selected tools.
    "optimizer_portfolio": HarnessToolBudget(
        tool_id="optimizer_portfolio",
        maximum_allocation=4,
        parallel_safe=False,
        base_latency_budget_ms=6_000,
        per_candidate_latency_budget_ms=1_500,
        base_cpu_budget_ms=6_000,
        per_candidate_cpu_budget_ms=1_500,
    ),
}


class HarnessBudgetOpportunity(_ClosedModel):
    """Immutable server budget exposed to one model planning turn."""

    schema_id: Literal["dronedream.harness-budget-opportunity/v1"] = (
        "dronedream.harness-budget-opportunity/v1"
    )
    policy_version: Literal["1.0"] = "1.0"
    generation: int = Field(ge=1)
    remaining_trials: int = Field(ge=1)
    full_trials_per_candidate: int = Field(ge=1)
    candidate_capacity: int = Field(ge=1, le=8)
    discretionary_candidates: int = Field(ge=1, le=8)
    maximum_tool_calls: int = Field(ge=1, le=4)
    generation_latency_budget_ms: int = Field(ge=1, le=600_000)
    generation_cpu_budget_ms: int = Field(ge=1, le=600_000)
    stop_eligible: bool
    accepted_stop_reasons: tuple[HarnessStopReason, ...] = ()
    tool_budgets: tuple[HarnessToolBudget, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _validate_budget(self) -> HarnessBudgetOpportunity:
        if self.discretionary_candidates > self.candidate_capacity:
            raise ValueError("discretionary candidates cannot exceed candidate capacity")
        if self.candidate_capacity > self.remaining_trials // self.full_trials_per_candidate:
            raise ValueError("candidate capacity exceeds remaining full-trial budget")
        tool_ids = [item.tool_id for item in self.tool_budgets]
        if len(set(tool_ids)) != len(tool_ids):
            raise ValueError("tool budgets must have unique tool IDs")
        if any(
            item.maximum_allocation > self.discretionary_candidates
            for item in self.tool_budgets
        ):
            raise ValueError("per-tool allocation exceeds discretionary capacity")
        if self.stop_eligible != bool(self.accepted_stop_reasons):
            raise ValueError("stop eligibility and accepted stop reasons must agree")
        return self

    def tool_budget(self, tool_id: HarnessToolId) -> HarnessToolBudget | None:
        return next((item for item in self.tool_budgets if item.tool_id == tool_id), None)


class HarnessToolAllocation(_ClosedModel):
    tool_id: HarnessToolId
    allocation: int = Field(ge=1, le=8)
    fidelity_mode: HarnessFidelityMode
    focus: tuple[HarnessPlanFocus, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def _validate_focus(self) -> HarnessToolAllocation:
        if len(set(self.focus)) != len(self.focus):
            raise ValueError("focus values must be unique")
        return self


class HarnessStopRecommendation(_ClosedModel):
    recommended: bool
    reason_code: HarnessStopReason | None

    @model_validator(mode="after")
    def _validate_shape(self) -> HarnessStopRecommendation:
        if self.recommended != (self.reason_code is not None):
            raise ValueError("stop recommendation and reason code must agree")
        return self


class HarnessPlanUncertainty(_ClosedModel):
    level: HarnessUncertaintyLevel
    missing_evidence: tuple[HarnessMissingEvidence, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def _validate_missing_evidence(self) -> HarnessPlanUncertainty:
        if len(set(self.missing_evidence)) != len(self.missing_evidence):
            raise ValueError("missing-evidence codes must be unique")
        return self


class HarnessGenerationPlan(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    decision: HarnessPlanDecision
    generation_goal: str = Field(min_length=1, max_length=256)
    tool_calls: tuple[HarnessToolAllocation, ...] = Field(default=(), max_length=4)
    stop: HarnessStopRecommendation
    uncertainty: HarnessPlanUncertainty

    @model_validator(mode="after")
    def _validate_decision_shape(self) -> HarnessGenerationPlan:
        if self.decision == "continue":
            if not self.tool_calls:
                raise ValueError("continue plans require at least one tool call")
            if self.stop.recommended:
                raise ValueError("continue plans cannot recommend stop")
        else:
            if self.tool_calls:
                raise ValueError("stop plans cannot allocate tools")
            if not self.stop.recommended:
                raise ValueError("stop plans require a stop recommendation")
        return self


class HarnessPlanRuleResult(_ClosedModel):
    rule: str = Field(min_length=1, max_length=64)
    passed: bool
    code: str = Field(min_length=1, max_length=64)


class HarnessPlanValidation(_ClosedModel):
    schema_id: Literal["dronedream.harness-plan-validation/v1"] = (
        "dronedream.harness-plan-validation/v1"
    )
    accepted: bool
    rule_results: tuple[HarnessPlanRuleResult, ...] = Field(min_length=1)
    projected_candidate_count: int = Field(ge=0)
    projected_trial_upper_bound: int = Field(ge=0)
    projected_serial_latency_budget_ms: int = Field(ge=0)
    projected_critical_path_latency_budget_ms: int = Field(ge=0)
    projected_cpu_budget_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_result(self) -> HarnessPlanValidation:
        if self.accepted != all(item.passed for item in self.rule_results):
            raise ValueError("validation acceptance must equal the conjunction of rules")
        return self


class HarnessCompiledToolCall(_ClosedModel):
    call_id: str = Field(pattern=r"^call_[0-9a-f]{24}$")
    ordinal: int = Field(ge=0, le=7)
    tool_id: HarnessToolId
    allocation: int = Field(ge=1, le=8)
    fidelity_mode: HarnessFidelityMode
    focus: tuple[HarnessPlanFocus, ...] = Field(default=(), max_length=3)
    allocation_authority: Literal["model"] = "model"
    parallel_safe: bool
    latency_budget_ms: int = Field(ge=1)
    cpu_budget_ms: int = Field(ge=1)
    projected_trial_upper_bound: int = Field(ge=1)


class HarnessCompiledGenerationPlan(_ClosedModel):
    schema_id: Literal["dronedream.compiled-generation-plan/v1"] = (
        "dronedream.compiled-generation-plan/v1"
    )
    budget_policy_version: Literal["1.0"] = "1.0"
    generation: int = Field(ge=1)
    generation_goal: str = Field(min_length=1, max_length=256)
    calls: tuple[HarnessCompiledToolCall, ...] = Field(min_length=1, max_length=4)
    projected_candidate_count: int = Field(ge=1, le=8)
    projected_trial_upper_bound: int = Field(ge=1)
    projected_serial_latency_budget_ms: int = Field(ge=1)
    projected_critical_path_latency_budget_ms: int = Field(ge=1)
    projected_cpu_budget_ms: int = Field(ge=1)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HarnessProposalSummary(_ClosedModel):
    proposal_ref: str = Field(pattern=r"^proposal_[0-9]{1,2}$")
    tool_id: HarnessToolId
    tool_candidate_ordinal: int = Field(ge=0, le=7)
    requested_fidelity: float = Field(gt=0.0, le=1.0)
    effective_fidelity: float = Field(gt=0.0, le=1.0)
    normalized_distance_from_incumbent: float = Field(ge=0.0, le=1.0)


class HarnessModelCandidateDomain(_ClosedModel):
    """One bounded parameter domain exposed to the revision turn."""

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    minimum: float
    maximum: float
    incumbent: float
    step: float | None = Field(default=None, gt=0.0)
    value_type: Literal["float", "integer", "boolean", "enum"]
    choices: tuple[float, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _validate_domain(self) -> HarnessModelCandidateDomain:
        values = (self.minimum, self.maximum, self.incumbent, *self.choices)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("model-candidate domains require finite values")
        if self.minimum > self.maximum:
            raise ValueError("model-candidate domain bounds are reversed")
        if not self.minimum <= self.incumbent <= self.maximum:
            raise ValueError("model-candidate incumbent is outside its domain")
        if any(not self.minimum <= value <= self.maximum for value in self.choices):
            raise ValueError("model-candidate choices must remain inside the domain")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("model-candidate choices must be unique")
        return self


class HarnessModelCandidateContext(_ClosedModel):
    """Deterministic authority for one optional model-authored candidate."""

    schema_id: Literal["dronedream.harness-model-candidate-context/v1"] = (
        "dronedream.harness-model-candidate-context/v1"
    )
    domains: tuple[HarnessModelCandidateDomain, ...] = Field(
        min_length=1,
        max_length=128,
    )
    maximum_changed_parameters: int = Field(ge=1, le=16)

    @model_validator(mode="after")
    def _validate_context(self) -> HarnessModelCandidateContext:
        names = [domain.name for domain in self.domains]
        if len(set(names)) != len(names):
            raise ValueError("model-candidate domains must have unique names")
        if self.maximum_changed_parameters > len(self.domains):
            raise ValueError("model-candidate change cap exceeds the domain count")
        return self


class HarnessModelParameterValue(_ClosedModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
    value: float

    @model_validator(mode="after")
    def _validate_finite(self) -> HarnessModelParameterValue:
        if not math.isfinite(self.value):
            raise ValueError("model-candidate parameter values must be finite")
        return self


class HarnessModelCandidateDraft(_ClosedModel):
    """Provider-authored hypothesis; it has no execution authority."""

    label: str = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=512)
    expected_effect: str = Field(min_length=1, max_length=512)
    risk_assessment: str = Field(min_length=1, max_length=512)
    parameters: tuple[HarnessModelParameterValue, ...] = Field(
        min_length=1,
        max_length=16,
    )

    @model_validator(mode="after")
    def _validate_unique_parameters(self) -> HarnessModelCandidateDraft:
        names = [item.name for item in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("model-candidate parameter names must be unique")
        return self


class HarnessCompiledModelCandidate(_ClosedModel):
    """Harness-validated full candidate derived from a model hypothesis."""

    schema_id: Literal["dronedream.compiled-model-candidate/v1"] = (
        "dronedream.compiled-model-candidate/v1"
    )
    label: str = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=512)
    expected_effect: str = Field(min_length=1, max_length=512)
    risk_assessment: str = Field(min_length=1, max_length=512)
    changed_parameters: tuple[str, ...] = Field(min_length=1, max_length=16)
    parameters: dict[str, float] = Field(min_length=1, max_length=128)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HarnessPlanRevision(_ClosedModel):
    schema_version: Literal["1.0"] = "1.0"
    decision: Literal["dispatch", "abandon"]
    selected_proposal_refs: tuple[str, ...] = Field(default=(), max_length=8)
    model_candidate: HarnessModelCandidateDraft | None = None
    rationale: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_shape(self) -> HarnessPlanRevision:
        if len(set(self.selected_proposal_refs)) != len(self.selected_proposal_refs):
            raise ValueError("selected proposal references must be unique")
        if (
            self.decision == "dispatch"
            and not self.selected_proposal_refs
            and self.model_candidate is None
        ):
            raise ValueError("dispatch revisions require a tool or model candidate")
        if self.decision == "abandon" and (
            self.selected_proposal_refs or self.model_candidate is not None
        ):
            raise ValueError("abandon revisions cannot select proposals")
        return self


class HarnessRevisionValidation(_ClosedModel):
    schema_id: Literal["dronedream.harness-plan-revision-validation/v1"] = (
        "dronedream.harness-plan-revision-validation/v1"
    )
    accepted: bool
    selected_proposal_refs: tuple[str, ...] = ()
    model_candidate: HarnessCompiledModelCandidate | None = None
    rejection_code: str | None = Field(default=None, max_length=64)
    fallback_used: bool = False

    @model_validator(mode="after")
    def _validate_result(self) -> HarnessRevisionValidation:
        if self.accepted == (self.rejection_code is not None):
            raise ValueError("accepted revisions cannot carry a rejection code")
        if not self.accepted and self.model_candidate is not None:
            raise ValueError("rejected revisions cannot carry a model candidate")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_budget_opportunity(
    *,
    generation: int,
    remaining_trials: int,
    full_trials_per_candidate: int,
    candidate_capacity: int,
    allowed_tools: Sequence[HarnessToolId],
    stop_reasons: Sequence[HarnessStopReason] = (),
    maximum_tool_calls: int = 4,
    generation_latency_budget_ms: int = 30_000,
    generation_cpu_budget_ms: int = 60_000,
) -> HarnessBudgetOpportunity:
    """Compile one bounded opportunity from trusted server-side budget facts."""

    if len(set(allowed_tools)) != len(allowed_tools):
        raise ValueError("allowed tools must be unique")
    bounded_capacity = min(
        candidate_capacity,
        remaining_trials // full_trials_per_candidate,
        8,
    )
    if bounded_capacity < 1:
        raise ValueError("budget opportunity requires at least one full candidate")
    budgets: list[HarnessToolBudget] = []
    for tool_id in allowed_tools:
        default = _DEFAULT_TOOL_BUDGETS[tool_id]
        budgets.append(
            default.model_copy(
                update={
                    "maximum_allocation": min(
                        default.maximum_allocation,
                        bounded_capacity,
                    )
                }
            )
        )
    if not budgets:
        raise ValueError("budget opportunity requires at least one eligible tool")
    normalized_stop_reasons = tuple(dict.fromkeys(stop_reasons))
    return HarnessBudgetOpportunity(
        generation=generation,
        remaining_trials=remaining_trials,
        full_trials_per_candidate=full_trials_per_candidate,
        candidate_capacity=bounded_capacity,
        discretionary_candidates=bounded_capacity,
        maximum_tool_calls=min(maximum_tool_calls, len(budgets)),
        generation_latency_budget_ms=generation_latency_budget_ms,
        generation_cpu_budget_ms=generation_cpu_budget_ms,
        stop_eligible=bool(normalized_stop_reasons),
        accepted_stop_reasons=normalized_stop_reasons,
        tool_budgets=tuple(budgets),
    )


def _plan_costs(
    plan: HarnessGenerationPlan,
    opportunity: HarnessBudgetOpportunity,
) -> tuple[int, int, int, int, int]:
    candidate_count = sum(item.allocation for item in plan.tool_calls)
    trial_upper_bound = candidate_count * opportunity.full_trials_per_candidate
    serial_latency = 0
    serial_lane_latency = 0
    parallel_lane_latency = 0
    cpu_budget = 0
    for allocation in plan.tool_calls:
        tool_budget = opportunity.tool_budget(allocation.tool_id)
        if tool_budget is None:
            continue
        latency = tool_budget.latency_budget_ms(allocation.allocation)
        cpu = tool_budget.cpu_budget_ms(allocation.allocation)
        serial_latency += latency
        cpu_budget += cpu
        if tool_budget.parallel_safe:
            parallel_lane_latency = max(parallel_lane_latency, latency)
        else:
            serial_lane_latency += latency
    critical_path = serial_lane_latency + parallel_lane_latency
    return candidate_count, trial_upper_bound, serial_latency, critical_path, cpu_budget


def validate_generation_plan(
    raw: object,
    opportunity: HarnessBudgetOpportunity,
) -> tuple[HarnessGenerationPlan | None, HarnessPlanValidation]:
    """Validate a model plan without repairing tool identity or allocation."""

    try:
        plan = HarnessGenerationPlan.model_validate_json(_canonical_json(raw))
    except (TypeError, ValueError, ValidationError):
        rule = HarnessPlanRuleResult(
            rule="schema",
            passed=False,
            code="invalid_schema",
        )
        return None, HarnessPlanValidation(
            accepted=False,
            rule_results=(rule,),
            projected_candidate_count=0,
            projected_trial_upper_bound=0,
            projected_serial_latency_budget_ms=0,
            projected_critical_path_latency_budget_ms=0,
            projected_cpu_budget_ms=0,
        )

    candidate_count, trials, serial_latency, critical_path, cpu_budget = _plan_costs(
        plan,
        opportunity,
    )
    calls_unique = len({item.tool_id for item in plan.tool_calls}) == len(plan.tool_calls)
    calls_allowed = all(
        opportunity.tool_budget(item.tool_id) is not None for item in plan.tool_calls
    )
    per_tool_allocation_valid = all(
        (budget := opportunity.tool_budget(item.tool_id)) is not None
        and item.allocation <= budget.maximum_allocation
        for item in plan.tool_calls
    )
    stop_valid = (
        plan.decision != "stop"
        or (
            opportunity.stop_eligible
            and plan.stop.reason_code in opportunity.accepted_stop_reasons
        )
    )
    rules = (
        HarnessPlanRuleResult(rule="schema", passed=True, code="valid_schema"),
        HarnessPlanRuleResult(
            rule="tool_set",
            passed=calls_unique and calls_allowed,
            code=(
                "valid_tool_set"
                if calls_unique and calls_allowed
                else "duplicate_or_ineligible_tool"
            ),
        ),
        HarnessPlanRuleResult(
            rule="tool_call_count",
            passed=len(plan.tool_calls) <= opportunity.maximum_tool_calls,
            code=(
                "valid_tool_call_count"
                if len(plan.tool_calls) <= opportunity.maximum_tool_calls
                else "too_many_tool_calls"
            ),
        ),
        HarnessPlanRuleResult(
            rule="allocation",
            passed=(
                per_tool_allocation_valid
                and candidate_count <= opportunity.discretionary_candidates
            ),
            code=(
                "valid_allocation"
                if per_tool_allocation_valid
                and candidate_count <= opportunity.discretionary_candidates
                else "allocation_exceeds_budget"
            ),
        ),
        HarnessPlanRuleResult(
            rule="trial_budget",
            passed=trials <= opportunity.remaining_trials,
            code=(
                "valid_trial_budget"
                if trials <= opportunity.remaining_trials
                else "trial_budget_exceeded"
            ),
        ),
        HarnessPlanRuleResult(
            rule="latency_budget",
            passed=critical_path <= opportunity.generation_latency_budget_ms,
            code=(
                "valid_latency_budget"
                if critical_path <= opportunity.generation_latency_budget_ms
                else "latency_budget_exceeded"
            ),
        ),
        HarnessPlanRuleResult(
            rule="cpu_budget",
            passed=cpu_budget <= opportunity.generation_cpu_budget_ms,
            code=(
                "valid_cpu_budget"
                if cpu_budget <= opportunity.generation_cpu_budget_ms
                else "cpu_budget_exceeded"
            ),
        ),
        HarnessPlanRuleResult(
            rule="stop_policy",
            passed=stop_valid,
            code="valid_stop_policy" if stop_valid else "stop_not_authorized",
        ),
    )
    report = HarnessPlanValidation(
        accepted=all(item.passed for item in rules),
        rule_results=rules,
        projected_candidate_count=candidate_count,
        projected_trial_upper_bound=trials,
        projected_serial_latency_budget_ms=serial_latency,
        projected_critical_path_latency_budget_ms=critical_path,
        projected_cpu_budget_ms=cpu_budget,
    )
    return (plan if report.accepted else None), report


def compile_generation_plan(
    plan: HarnessGenerationPlan,
    opportunity: HarnessBudgetOpportunity,
) -> HarnessCompiledGenerationPlan:
    """Compile one accepted continue plan into stable executable call identities."""

    accepted, report = validate_generation_plan(plan.model_dump(mode="json"), opportunity)
    if accepted is None or not report.accepted or accepted.decision != "continue":
        raise ValueError("only accepted continue plans can be compiled")
    order = {item.tool_id: index for index, item in enumerate(opportunity.tool_budgets)}
    ordered_allocations = tuple(
        sorted(accepted.tool_calls, key=lambda item: order[item.tool_id])
    )
    unsigned_calls: list[dict[str, object]] = []
    for ordinal, allocation_item in enumerate(ordered_allocations):
        allocation_budget = opportunity.tool_budget(allocation_item.tool_id)
        if allocation_budget is None:
            raise RuntimeError("compiled tool disappeared from opportunity")
        unsigned_calls.append(
            {
                "ordinal": ordinal,
                "tool_id": allocation_item.tool_id,
                "allocation": allocation_item.allocation,
                "fidelity_mode": allocation_item.fidelity_mode,
                "focus": list(allocation_item.focus),
                "parallel_safe": allocation_budget.parallel_safe,
            }
        )
    plan_identity = {
        "schema_id": "dronedream.compiled-generation-plan/v1",
        "budget_policy_version": HARNESS_BUDGET_POLICY_VERSION,
        "generation": opportunity.generation,
        "generation_goal": accepted.generation_goal,
        "opportunity": opportunity.model_dump(mode="json"),
        "calls": unsigned_calls,
    }
    plan_sha256 = _sha256(plan_identity)
    compiled_calls: list[HarnessCompiledToolCall] = []
    for ordinal, allocation_item in enumerate(ordered_allocations):
        budget = opportunity.tool_budget(allocation_item.tool_id)
        if budget is None:
            raise RuntimeError("compiled tool disappeared from opportunity")
        call_id = "call_" + hashlib.sha256(
            f"{plan_sha256}:{ordinal}:{allocation_item.tool_id}".encode()
        ).hexdigest()[:24]
        compiled_calls.append(
            HarnessCompiledToolCall(
                call_id=call_id,
                ordinal=ordinal,
                tool_id=allocation_item.tool_id,
                allocation=allocation_item.allocation,
                fidelity_mode=allocation_item.fidelity_mode,
                focus=allocation_item.focus,
                parallel_safe=budget.parallel_safe,
                latency_budget_ms=budget.latency_budget_ms(
                    allocation_item.allocation
                ),
                cpu_budget_ms=budget.cpu_budget_ms(allocation_item.allocation),
                projected_trial_upper_bound=(
                    allocation_item.allocation
                    * opportunity.full_trials_per_candidate
                ),
            )
        )
    return HarnessCompiledGenerationPlan(
        generation=opportunity.generation,
        generation_goal=accepted.generation_goal,
        calls=tuple(compiled_calls),
        projected_candidate_count=report.projected_candidate_count,
        projected_trial_upper_bound=report.projected_trial_upper_bound,
        projected_serial_latency_budget_ms=report.projected_serial_latency_budget_ms,
        projected_critical_path_latency_budget_ms=(
            report.projected_critical_path_latency_budget_ms
        ),
        projected_cpu_budget_ms=report.projected_cpu_budget_ms,
        plan_sha256=plan_sha256,
    )


def deterministic_fallback_plan(
    opportunity: HarnessBudgetOpportunity,
) -> HarnessCompiledGenerationPlan:
    """Use the strong deterministic portfolio without mislabeling it as model choice."""

    portfolio = opportunity.tool_budget("optimizer_portfolio")
    if portfolio is None:
        first = opportunity.tool_budgets[0]
        tool_id = first.tool_id
        allocation = min(first.maximum_allocation, opportunity.discretionary_candidates)
    else:
        tool_id = portfolio.tool_id
        allocation = min(portfolio.maximum_allocation, opportunity.discretionary_candidates)
    plan = HarnessGenerationPlan(
        decision="continue",
        generation_goal="Continue with the deterministic bounded fallback allocation.",
        tool_calls=(
            HarnessToolAllocation(
                tool_id=tool_id,
                allocation=allocation,
                fidelity_mode="auto",
                focus=(),
            ),
        ),
        stop=HarnessStopRecommendation(recommended=False, reason_code=None),
        uncertainty=HarnessPlanUncertainty(level="high", missing_evidence=()),
    )
    return compile_generation_plan(plan, opportunity)


def generation_plan_schema(opportunity: HarnessBudgetOpportunity) -> dict[str, object]:
    """Return a provider strict-schema object with a request-specific tool enum."""

    tool_ids = [item.tool_id for item in opportunity.tool_budgets]
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "decision": {"type": "string", "enum": ["continue", "stop"]},
            "generation_goal": {"type": "string", "minLength": 1, "maxLength": 256},
            "tool_calls": {
                "type": "array",
                "maxItems": opportunity.maximum_tool_calls,
                "items": {
                    "type": "object",
                    "properties": {
                        "tool_id": {"type": "string", "enum": tool_ids},
                        "allocation": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": opportunity.discretionary_candidates,
                        },
                        "fidelity_mode": {
                            "type": "string",
                            "enum": ["auto", "force_full"],
                        },
                        "focus": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "string",
                                "enum": [
                                    "constraints",
                                    "diversity",
                                    "failure_recovery",
                                    "local_improvement",
                                    "multi_fidelity_screening",
                                    "sparse_axes",
                                    "verification",
                                ],
                            },
                        },
                    },
                    "required": [
                        "tool_id",
                        "allocation",
                        "fidelity_mode",
                        "focus",
                    ],
                    "additionalProperties": False,
                },
            },
            "stop": {
                "type": "object",
                "properties": {
                    "recommended": {"type": "boolean"},
                    "reason_code": {
                        "anyOf": [
                            {
                                "type": "string",
                                "enum": [
                                    "acceptance_satisfied",
                                    "converged",
                                    "budget_efficiency_stalled",
                                ],
                            },
                            {"type": "null"},
                        ]
                    },
                },
                "required": ["recommended", "reason_code"],
                "additionalProperties": False,
            },
            "uncertainty": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "missing_evidence": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "string",
                            "enum": [
                                "constraint_boundary",
                                "cross_job_transfer",
                                "feasible_incumbent",
                                "full_fidelity_outcome",
                                "local_curvature",
                                "tool_cost_history",
                            ],
                        },
                    },
                },
                "required": ["level", "missing_evidence"],
                "additionalProperties": False,
            },
        },
        "required": [
            "schema_version",
            "decision",
            "generation_goal",
            "tool_calls",
            "stop",
            "uncertainty",
        ],
        "additionalProperties": False,
    }


def build_budget_plan_messages(
    *,
    evidence_snapshot: Mapping[str, object],
    opportunity: HarnessBudgetOpportunity,
    tool_manifest: Mapping[str, object],
) -> tuple[str, str]:
    """Build the first-turn prompt with explicit cost, latency, and authority limits."""

    system = (
        "You are DroneDream's bounded multi-tool optimization planner. Submit one "
        "complete declarative generation plan. You may allocate several eligible "
        "pure proposal tools, choose their candidate allocations and fidelity intent, "
        "or recommend stopping. Deterministic code owns eligibility, budgets, stop "
        "authority, seeds, parameter values, simulation dispatch, and final acceptance. "
        "Never exceed the supplied discretionary candidate, Trial, CPU, latency, or "
        "tool-call ceilings. Treat observed outcomes as associations, not causal tool "
        "credit. Return only JSON matching the strict schema."
    )
    payload = {
        "schema_version": HARNESS_BUDGET_PROMPT_VERSION,
        "evidence": dict(evidence_snapshot),
        "budget_opportunity": opportunity.model_dump(mode="json"),
        "tool_manifest": dict(tool_manifest),
        "instructions": (
            "Use multiple tools only when their roles are complementary under the "
            "same fixed simulation budget. Allocations are upper bounds for pure "
            "proposal generation; a second bounded turn may select a smaller final "
            "batch after typed proposal summaries return."
        ),
    }
    return system, _canonical_json(payload)


def validate_plan_revision(
    raw: object,
    *,
    proposals: Sequence[HarnessProposalSummary],
    maximum_dispatch_candidates: int,
    model_candidate_context: HarnessModelCandidateContext | None = None,
    allow_abandon: bool = False,
) -> tuple[HarnessPlanRevision | None, HarnessRevisionValidation]:
    """Validate the optional second turn without exposing parameter values."""

    try:
        revision = HarnessPlanRevision.model_validate_json(_canonical_json(raw))
    except (TypeError, ValueError, ValidationError):
        return None, HarnessRevisionValidation(
            accepted=False,
            rejection_code="invalid_schema",
        )
    available = {item.proposal_ref for item in proposals}
    selected = revision.selected_proposal_refs
    if any(reference not in available for reference in selected):
        return None, HarnessRevisionValidation(
            accepted=False,
            rejection_code="unknown_proposal_reference",
        )
    candidate_count = 1 if revision.model_candidate is not None else 0
    if len(selected) + candidate_count > maximum_dispatch_candidates:
        return None, HarnessRevisionValidation(
            accepted=False,
            rejection_code="dispatch_capacity_exceeded",
        )
    if revision.decision == "abandon" and not allow_abandon:
        return None, HarnessRevisionValidation(
            accepted=False,
            rejection_code="abandon_not_authorized",
        )
    compiled_candidate = None
    if revision.model_candidate is not None:
        if model_candidate_context is None:
            return None, HarnessRevisionValidation(
                accepted=False,
                rejection_code="model_candidate_not_authorized",
            )
        compiled_candidate, rejection_code = _compile_model_candidate(
            revision.model_candidate,
            context=model_candidate_context,
        )
        if compiled_candidate is None:
            return None, HarnessRevisionValidation(
                accepted=False,
                rejection_code=rejection_code,
            )
    return revision, HarnessRevisionValidation(
        accepted=True,
        selected_proposal_refs=selected,
        model_candidate=compiled_candidate,
    )


def _compile_model_candidate(
    draft: HarnessModelCandidateDraft,
    *,
    context: HarnessModelCandidateContext,
) -> tuple[HarnessCompiledModelCandidate | None, str]:
    """Compile one provider hypothesis without silently changing its values."""

    domains = {domain.name: domain for domain in context.domains}
    requested = {item.name: item.value for item in draft.parameters}
    if any(name not in domains for name in requested):
        return None, "unknown_model_candidate_parameter"
    if len(requested) > context.maximum_changed_parameters:
        return None, "model_candidate_change_cap_exceeded"

    changed: list[str] = []
    parameters = {domain.name: domain.incumbent for domain in context.domains}
    for name, raw_value in requested.items():
        domain = domains[name]
        value = float(raw_value)
        if not domain.minimum <= value <= domain.maximum:
            return None, "model_candidate_out_of_bounds"
        if domain.choices and value not in domain.choices:
            return None, "model_candidate_choice_mismatch"
        if domain.value_type in {"integer", "boolean", "enum"} and not value.is_integer():
            return None, "model_candidate_type_mismatch"
        if domain.value_type == "boolean" and value not in {0.0, 1.0}:
            return None, "model_candidate_type_mismatch"
        if domain.step is not None:
            step_count = (value - domain.minimum) / domain.step
            if not math.isclose(step_count, round(step_count), abs_tol=1e-9):
                return None, "model_candidate_step_mismatch"
        if math.isclose(value, domain.incumbent, rel_tol=0.0, abs_tol=1e-12):
            continue
        parameters[name] = value
        changed.append(name)
    if not changed:
        return None, "model_candidate_noop"
    canonical = {
        "label": draft.label,
        "rationale": draft.rationale,
        "expected_effect": draft.expected_effect,
        "risk_assessment": draft.risk_assessment,
        "changed_parameters": sorted(changed),
        "parameters": {name: parameters[name] for name in sorted(parameters)},
    }
    return (
        HarnessCompiledModelCandidate(
            label=draft.label,
            rationale=draft.rationale,
            expected_effect=draft.expected_effect,
            risk_assessment=draft.risk_assessment,
            changed_parameters=tuple(sorted(changed)),
            parameters=parameters,
            candidate_sha256=_sha256(canonical),
        ),
        "accepted",
    )


def deterministic_revision_fallback(
    proposals: Sequence[HarnessProposalSummary],
    *,
    maximum_dispatch_candidates: int,
    rejection_code: str,
) -> HarnessRevisionValidation:
    """Select canonical proposal order after a failed second model turn."""

    selected = tuple(
        item.proposal_ref for item in proposals[:maximum_dispatch_candidates]
    )
    if not selected:
        return HarnessRevisionValidation(
            accepted=False,
            rejection_code="no_usable_proposals",
            fallback_used=True,
        )
    return HarnessRevisionValidation(
        accepted=True,
        selected_proposal_refs=selected,
        fallback_used=True,
    )


def plan_revision_schema(
    proposals: Sequence[HarnessProposalSummary],
    *,
    maximum_dispatch_candidates: int,
    model_candidate_context: HarnessModelCandidateContext | None = None,
) -> dict[str, object]:
    proposal_refs = [item.proposal_ref for item in proposals]
    model_candidate_schema: dict[str, object] = {"type": "null"}
    if model_candidate_context is not None:
        parameter_names = [domain.name for domain in model_candidate_context.domains]
        model_candidate_schema = {
            "type": ["object", "null"],
            "properties": {
                "label": {"type": "string", "minLength": 1, "maxLength": 64},
                "rationale": {"type": "string", "minLength": 1, "maxLength": 512},
                "expected_effect": {"type": "string", "minLength": 1, "maxLength": 512},
                "risk_assessment": {"type": "string", "minLength": 1, "maxLength": 512},
                "parameters": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": model_candidate_context.maximum_changed_parameters,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": parameter_names},
                            "value": {"type": "number"},
                        },
                        "required": ["name", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "label",
                "rationale",
                "expected_effect",
                "risk_assessment",
                "parameters",
            ],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "decision": {"type": "string", "enum": ["dispatch", "abandon"]},
            "selected_proposal_refs": {
                "type": "array",
                "maxItems": maximum_dispatch_candidates,
                "items": {"type": "string", "enum": proposal_refs},
            },
            "model_candidate": model_candidate_schema,
            "rationale": {"type": "string", "minLength": 1, "maxLength": 256},
        },
        "required": [
            "schema_version",
            "decision",
            "selected_proposal_refs",
            "model_candidate",
            "rationale",
        ],
        "additionalProperties": False,
    }


def build_plan_revision_messages(
    *,
    compiled_plan: HarnessCompiledGenerationPlan,
    proposals: Sequence[HarnessProposalSummary],
    maximum_dispatch_candidates: int,
    model_candidate_context: HarnessModelCandidateContext | None = None,
    feedback_evidence: Mapping[str, object] | None = None,
) -> tuple[str, str]:
    """Build the sole optional post-tool turn from bounded evidence."""

    if not proposals and model_candidate_context is None:
        raise ValueError("plan revision requires proposals or a candidate context")
    system = (
        "You are DroneDream's bounded simulation candidate strategist. Compare the "
        "typed tool proposals and feedback. You may select tool proposal references "
        "and optionally author one parameter hypothesis within the supplied domains. "
        "Explain its expected effect and risk. The Harness validates every value and "
        "owns budgets, seeds, simulation execution, qualification, holdout, rollback, "
        "and all authority. Your candidate consumes the same fixed candidate capacity; "
        "it cannot expand any budget or authorize hardware. Return only strict JSON."
    )
    payload = {
        "schema_version": HARNESS_PLAN_REVISION_PROMPT_VERSION,
        "compiled_plan_sha256": compiled_plan.plan_sha256,
        "maximum_dispatch_candidates": maximum_dispatch_candidates,
        "proposals": [item.model_dump(mode="json") for item in proposals],
        "feedback_evidence": dict(feedback_evidence or {}),
        "model_candidate_context": (
            model_candidate_context.model_dump(mode="json")
            if model_candidate_context is not None
            else None
        ),
    }
    return system, _canonical_json(payload)


def proposal_summary(
    *,
    proposal_ref: str,
    tool_id: HarnessToolId,
    tool_candidate_ordinal: int,
    requested_fidelity: float,
    effective_fidelity: float,
    normalized_distance_from_incumbent: float,
) -> HarnessProposalSummary:
    """Create a finite, bounded post-tool summary without raw parameter values."""

    for field_name, value in (
        ("requested_fidelity", requested_fidelity),
        ("effective_fidelity", effective_fidelity),
        ("normalized_distance_from_incumbent", normalized_distance_from_incumbent),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise ValueError(f"{field_name} must be finite")
    return HarnessProposalSummary(
        proposal_ref=proposal_ref,
        tool_id=tool_id,
        tool_candidate_ordinal=tool_candidate_ordinal,
        requested_fidelity=float(requested_fidelity),
        effective_fidelity=float(effective_fidelity),
        normalized_distance_from_incumbent=float(normalized_distance_from_incumbent),
    )


__all__ = [
    "HARNESS_BUDGET_PLAN_SCHEMA_VERSION",
    "HARNESS_BUDGET_POLICY_VERSION",
    "HARNESS_BUDGET_PROMPT_VERSION",
    "HARNESS_PLAN_REVISION_PROMPT_VERSION",
    "HARNESS_PLAN_REVISION_SCHEMA_VERSION",
    "HarnessBudgetOpportunity",
    "HarnessCompiledGenerationPlan",
    "HarnessCompiledModelCandidate",
    "HarnessCompiledToolCall",
    "HarnessGenerationPlan",
    "HarnessModelCandidateContext",
    "HarnessModelCandidateDomain",
    "HarnessPlanRevision",
    "HarnessPlanValidation",
    "HarnessProposalSummary",
    "HarnessRevisionValidation",
    "HarnessStopRecommendation",
    "HarnessStopReason",
    "HarnessToolAllocation",
    "HarnessToolBudget",
    "build_budget_opportunity",
    "build_budget_plan_messages",
    "build_plan_revision_messages",
    "compile_generation_plan",
    "deterministic_fallback_plan",
    "deterministic_revision_fallback",
    "generation_plan_schema",
    "plan_revision_schema",
    "proposal_summary",
    "validate_generation_plan",
    "validate_plan_revision",
]
