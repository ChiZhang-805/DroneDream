"""Offline-only execution runtime for versioned LLM/Harness benchmark arms.

This module deliberately rejects production provider clients.  It exists to
prove closed schemas, bounded 1--4 turn state machines, local-tool isolation,
deterministic adaptive triggers, and failure receipts before P3 introduces
durable real-provider accounting.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Final, Literal, NoReturn, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.adapters import BenchmarkAdapterError, search_space_from_observation
from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    BenchmarkProposalV1,
    canonical_sha256,
)
from app.benchmarking.llm_arm_contracts import (
    BENCHMARK_LLM_ARM_POLICIES_SHA256,
    BenchmarkLLMAdapterId,
    BenchmarkLLMArmPolicyV1,
    BenchmarkLLMContractError,
    BenchmarkLLMTurnRequestV1,
    BenchmarkTurnRole,
    assert_unique_turn_bindings,
    build_llm_turn_request,
    critic_response_schema,
    diagnosis_response_schema,
    parse_bounded_json_response,
    proposal_response_schema,
    react_response_schema,
    require_llm_arm_policy,
    selection_response_schema,
    tool_action_response_schema,
    validate_critic_response,
    validate_diagnosis_response,
    validate_proposal_response,
    validate_react_response,
    validate_selection_response,
    validate_tool_action_response,
)
from app.benchmarking.registry import create_benchmark_adapter

BENCHMARK_FIXTURE_RUNTIME_SCHEMA_ID: Final = "dronedream.benchmark-llm-fixture-runtime/v1"
BENCHMARK_ADAPTIVE_TRIGGER_POLICY_VERSION: Final = "benchmark-adaptive-trigger-v1"

_TRIGGER_FAMILY = {
    "trailing_stagnation": "progress",
    "tool_direction_conflict": "conflict",
    "prediction_outcome_mismatch": "mismatch",
    "domain_failure_spike": "physical_failure",
    "ood_no_transfer_memory": "ood",
    "crash_or_instability": "physical_failure",
    "timeout_or_sensor_anomaly": "physical_failure",
    "near_threshold_uncertain": "threshold",
    "hard_boundary_candidate": "boundary",
}
_TRIGGER_SEVERITY = {
    "trailing_stagnation": 1,
    "tool_direction_conflict": 1,
    "prediction_outcome_mismatch": 1,
    "domain_failure_spike": 1,
    "ood_no_transfer_memory": 1,
    "near_threshold_uncertain": 1,
    "crash_or_instability": 2,
    "timeout_or_sensor_anomaly": 2,
    "hard_boundary_candidate": 2,
}


class OfflineFixtureProvider(Protocol):
    """A deterministic local sequence provider; real network clients are rejected."""

    fixture_only: bool

    def complete(self, request: BenchmarkLLMTurnRequestV1) -> str:
        """Return one fixture JSON response without network or credential access."""


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkAdaptiveTriggerDecisionV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-adaptive-trigger-decision/v1"] = (
        "dronedream.benchmark-adaptive-trigger-decision/v1"
    )
    policy_version: Literal["benchmark-adaptive-trigger-v1"] = "benchmark-adaptive-trigger-v1"
    diagnosis_reasons: tuple[str, ...] = Field(default=(), max_length=9)
    critic_reasons: tuple[str, ...] = Field(default=(), max_length=9)
    suppressed_by_cooldown: tuple[str, ...] = Field(default=(), max_length=9)
    evidence_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    next_family_state: dict[str, tuple[int, int]] = Field(default_factory=dict)


class BenchmarkOfflineLLMExecutionV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-llm-fixture-runtime/v1"] = (
        "dronedream.benchmark-llm-fixture-runtime/v1"
    )
    fixture_only: Literal[True] = True
    adapter_id: BenchmarkLLMAdapterId
    status: Literal["proposal", "abandoned", "first_qualified_stop"]
    proposal: BenchmarkProposalV1 | None
    provider_turns_attempted: Annotated[int, Field(ge=0, le=4)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=4)]
    turn_receipts: tuple[dict[str, Any], ...] = Field(max_length=4)
    response_sha256: tuple[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], ...] = Field(
        max_length=4
    )
    trigger_decision: BenchmarkAdaptiveTriggerDecisionV1 | None = None

    @model_validator(mode="after")
    def _validate_execution(self) -> BenchmarkOfflineLLMExecutionV1:
        if self.provider_turns_succeeded > self.provider_turns_attempted:
            raise ValueError("succeeded provider turns cannot exceed attempted turns")
        if len(self.turn_receipts) != self.provider_turns_attempted:
            raise ValueError("every attempted fixture turn requires a safe receipt")
        if len(self.response_sha256) != self.provider_turns_succeeded:
            raise ValueError("every successful fixture response requires a hash")
        if (self.status == "proposal") != (self.proposal is not None):
            raise ValueError("fixture execution status and proposal disagree")
        return self


class BenchmarkLLMFixtureExecutionError(BenchmarkLLMContractError):
    """Fail-closed error containing only safe accounting, never provider text."""

    def __init__(
        self,
        code: str,
        *,
        attempted: int,
        succeeded: int,
        turn_receipts: Sequence[dict[str, Any]],
        response_sha256: Sequence[str],
    ) -> None:
        super().__init__(f"offline benchmark LLM execution failed closed: {code}")
        self.code = code
        self.safe_receipt = {
            "schema_id": "dronedream.benchmark-llm-fixture-failure/v1",
            "fixture_only": True,
            "error_code": code,
            "provider_turns_attempted": attempted,
            "provider_turns_succeeded": succeeded,
            "turn_receipts": list(turn_receipts),
            "response_sha256": list(response_sha256),
        }


@dataclass(slots=True)
class _ExecutionState:
    provider: OfflineFixtureProvider
    policy: BenchmarkLLMArmPolicyV1
    observation: BenchmarkObservationV2
    model_snapshot: str
    requests: list[BenchmarkLLMTurnRequestV1] = field(default_factory=list)
    response_hashes: list[str] = field(default_factory=list)
    succeeded: int = 0

    def fail(self, code: str) -> NoReturn:
        raise BenchmarkLLMFixtureExecutionError(
            code,
            attempted=len(self.requests),
            succeeded=self.succeeded,
            turn_receipts=[request.receipt_payload() for request in self.requests],
            response_sha256=self.response_hashes,
        )

    def call(
        self,
        *,
        turn_index: int,
        turn_role: BenchmarkTurnRole,
        response_schema: dict[str, Any],
        tool_outputs: list[dict[str, Any]] | None = None,
    ) -> object:
        try:
            request = build_llm_turn_request(
                policy=self.policy,
                observation=self.observation,
                model_snapshot=self.model_snapshot,
                turn_index=turn_index,
                turn_role=turn_role,
                response_schema=response_schema,
                tool_outputs=tool_outputs,
            )
            assert_unique_turn_bindings((*self.requests, request))
        except BenchmarkLLMContractError:
            self.fail("turn_contract_rejected")
        self.requests.append(request)
        try:
            raw_text = self.provider.complete(request)
        except Exception:  # noqa: BLE001 - provider details must not escape into evidence.
            self.fail("fixture_provider_failed")
        self.succeeded += 1
        if not isinstance(raw_text, str):
            self.fail("fixture_provider_returned_non_text")
        self.response_hashes.append(hashlib.sha256(raw_text.encode()).hexdigest())
        try:
            return parse_bounded_json_response(raw_text)
        except BenchmarkLLMContractError:
            self.fail("fixture_provider_response_invalid")


def _safe_tool_output(proposal: BenchmarkProposalV1) -> dict[str, Any]:
    return {
        "proposal_ref": proposal.candidate_ref,
        "parameters": dict(proposal.parameters),
        "proposal_reason_code": proposal.reason_code,
        "proposal_receipt_sha256": canonical_sha256(proposal.proposal_receipt),
    }


def _run_local_tools(
    tool_adapter_ids: Sequence[str],
    observation: BenchmarkObservationV2,
    *,
    already_used: set[str],
) -> list[BenchmarkProposalV1]:
    proposals: list[BenchmarkProposalV1] = []
    for adapter_id in tool_adapter_ids:
        if adapter_id in already_used:
            raise BenchmarkAdapterError("bounded LLM arm repeated a local tool in one generation")
        already_used.add(adapter_id)
        proposals.append(create_benchmark_adapter(adapter_id).propose(observation))
    return proposals


def _proposal_by_ref(
    proposals: Sequence[BenchmarkProposalV1], proposal_ref: str
) -> BenchmarkProposalV1:
    for proposal in proposals:
        if proposal.candidate_ref == proposal_ref:
            return proposal
    raise BenchmarkLLMContractError("selected proposal reference is absent")


def _finalize_proposal(
    state: _ExecutionState,
    source: BenchmarkProposalV1,
    *,
    trigger_decision: BenchmarkAdaptiveTriggerDecisionV1 | None,
) -> BenchmarkProposalV1:
    parameter_sha256 = canonical_sha256(source.parameters)
    label = state.policy.adapter_id.split("/", maxsplit=1)[0].replace("_", "-")
    turn_receipts = [request.receipt_payload() for request in state.requests]
    receipt = {
        "schema_id": "dronedream.benchmark-llm-fixture-proposal/v1",
        "fixture_only": True,
        "adapter_id": state.policy.adapter_id,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "model_snapshot": state.model_snapshot,
        "observation_sha256": canonical_sha256(state.observation),
        "parameter_sha256": parameter_sha256,
        "selected_source_proposal_ref": source.candidate_ref,
        "selected_source_proposal_sha256": canonical_sha256(source),
        "provider_turns_attempted": len(state.requests),
        "provider_turns_succeeded": state.succeeded,
        "turn_receipts": turn_receipts,
        "response_sha256": list(state.response_hashes),
        "trigger_decision_sha256": (
            canonical_sha256(trigger_decision) if trigger_decision is not None else None
        ),
    }
    return BenchmarkProposalV1(
        candidate_ref=(
            f"{label}-g{state.observation.generation_index:06d}-"
            f"d{state.observation.next_dispatch_ordinal:06d}-{parameter_sha256[:12]}"
        ),
        parameters=dict(source.parameters),
        reason_code=f"offline-fixture-{label}",
        proposal_receipt=receipt,
    )


def _direct_source_proposal(
    state: _ExecutionState,
    *,
    turn_role: Literal["direct_proposal", "llambo_proposal"],
) -> BenchmarkProposalV1:
    raw = state.call(
        turn_index=1,
        turn_role=turn_role,
        response_schema=proposal_response_schema(state.observation),
    )
    try:
        parameters = validate_proposal_response(raw, state.observation)
    except BenchmarkLLMContractError:
        state.fail("proposal_schema_rejected")
    parameter_sha256 = canonical_sha256(parameters)
    return BenchmarkProposalV1(
        candidate_ref=f"provider-proposal-{parameter_sha256[:16]}",
        parameters=parameters,
        reason_code="offline-fixture-provider-proposal",
        proposal_receipt={
            "schema_id": "dronedream.benchmark-provider-proposal-source/v1",
            "fixture_only": True,
            "parameter_sha256": parameter_sha256,
        },
    )


def _objective_losses(observation: BenchmarkObservationV2) -> list[float]:
    return [
        float(item.outcome.loss)
        for item in observation.history
        if item.outcome.role == "objective" and item.outcome.loss is not None
    ]


def _tool_direction_conflict(
    observation: BenchmarkObservationV2,
    proposals: Sequence[BenchmarkProposalV1],
) -> bool:
    if len(proposals) < 2:
        return False
    space = search_space_from_observation(observation)
    vectors = [space.to_unit_vector(proposal.parameters) for proposal in proposals]
    dimensions = max(1, len(vectors[0]))
    for left_index, left in enumerate(vectors):
        for right in vectors[left_index + 1 :]:
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))
            if distance / math.sqrt(dimensions) >= 0.5:
                return True
    return False


def _prediction_outcome_mismatch(observation: BenchmarkObservationV2) -> bool:
    for item in reversed(observation.history):
        context = item.proposal_context
        actual = item.outcome.loss
        if context is None or actual is None:
            continue
        predicted = context.optimizer_metadata.get("predicted_loss")
        if isinstance(predicted, bool) or not isinstance(predicted, int | float):
            continue
        if not math.isfinite(float(predicted)):
            continue
        return abs(float(actual) - float(predicted)) > max(0.1, abs(float(predicted)) * 0.5)
    return False


def _hard_boundary_candidate(
    observation: BenchmarkObservationV2,
    proposal: BenchmarkProposalV1,
) -> bool:
    vector = search_space_from_observation(observation).to_unit_vector(proposal.parameters)
    return any(value <= 0.02 or value >= 0.98 for value in vector)


def evaluate_benchmark_adaptive_triggers(
    observation: BenchmarkObservationV2,
    proposals: Sequence[BenchmarkProposalV1],
    selected_proposal: BenchmarkProposalV1,
    *,
    previous_family_state: Mapping[str, tuple[int, int]] | None = None,
) -> BenchmarkAdaptiveTriggerDecisionV1:
    """Evaluate deterministic, versioned T3/T4 triggers with one-generation cooldown."""

    diagnosis: list[str] = []
    critic: list[str] = []
    losses = _objective_losses(observation)
    if len(losses) >= 3 and min(losses[-3:]) >= min(losses[:-2]) - 1e-12:
        diagnosis.append("trailing_stagnation")
    if _tool_direction_conflict(observation, proposals):
        diagnosis.append("tool_direction_conflict")
    if _prediction_outcome_mismatch(observation):
        diagnosis.append("prediction_outcome_mismatch")
    recent = observation.history[-3:]
    if sum(item.screening_status in {"failed", "unsafe", "timeout"} for item in recent) >= 2:
        diagnosis.append("domain_failure_spike")
    if (
        observation.failure_semantics.get("scenario_distribution") == "ood"
        and not observation.history
    ):
        diagnosis.append("ood_no_transfer_memory")

    failure_codes = tuple((item.failure_code or "").lower() for item in recent)
    if any("crash" in code or "unstable" in code for code in failure_codes) or any(
        item.screening_status == "unsafe" for item in recent
    ):
        critic.append("crash_or_instability")
    if any("sensor" in code for code in failure_codes) or any(
        item.screening_status == "timeout" for item in recent
    ):
        critic.append("timeout_or_sensor_anomaly")
    if any(
        0.0 < violation <= 0.05
        for item in recent
        for violation in item.outcome.constraint_violations.values()
    ):
        critic.append("near_threshold_uncertain")
    if _hard_boundary_candidate(observation, selected_proposal):
        critic.append("hard_boundary_candidate")

    prior = dict(previous_family_state or {})
    suppressed: list[str] = []

    def apply_cooldown(reasons: Sequence[str]) -> tuple[str, ...]:
        accepted: list[str] = []
        for reason in reasons:
            family = _TRIGGER_FAMILY[reason]
            severity = _TRIGGER_SEVERITY[reason]
            previous = prior.get(family)
            if (
                previous is not None
                and observation.generation_index - previous[0] <= 1
                and severity <= previous[1]
            ):
                suppressed.append(reason)
                continue
            accepted.append(reason)
            prior[family] = (observation.generation_index, severity)
        return tuple(accepted)

    diagnosis_reasons = apply_cooldown(diagnosis)
    critic_reasons = apply_cooldown(critic)
    evidence = {
        "schema_id": "dronedream.benchmark-adaptive-trigger-evidence/v1",
        "generation_index": observation.generation_index,
        "history_statuses": [item.screening_status for item in recent],
        "losses_sha256": canonical_sha256(losses),
        "proposal_parameter_sha256": [canonical_sha256(item.parameters) for item in proposals],
        "selected_parameter_sha256": canonical_sha256(selected_proposal.parameters),
        "previous_family_state": {
            key: list(value) for key, value in sorted((previous_family_state or {}).items())
        },
    }
    return BenchmarkAdaptiveTriggerDecisionV1(
        diagnosis_reasons=diagnosis_reasons,
        critic_reasons=critic_reasons,
        suppressed_by_cooldown=tuple(dict.fromkeys(suppressed)),
        evidence_sha256=canonical_sha256(evidence),
        next_family_state=prior,
    )


def _result(
    state: _ExecutionState,
    proposal: BenchmarkProposalV1 | None,
    *,
    trigger_decision: BenchmarkAdaptiveTriggerDecisionV1 | None = None,
    terminal_status: Literal["abandoned", "first_qualified_stop"] = "abandoned",
) -> BenchmarkOfflineLLMExecutionV1:
    assert_unique_turn_bindings(tuple(state.requests))
    return BenchmarkOfflineLLMExecutionV1(
        adapter_id=state.policy.adapter_id,
        status="proposal" if proposal is not None else terminal_status,
        proposal=proposal,
        provider_turns_attempted=len(state.requests),
        provider_turns_succeeded=state.succeeded,
        turn_receipts=tuple(request.receipt_payload() for request in state.requests),
        response_sha256=tuple(state.response_hashes),
        trigger_decision=trigger_decision,
    )


def _execute_react(state: _ExecutionState) -> BenchmarkOfflineLLMExecutionV1:
    proposals: list[BenchmarkProposalV1] = []
    used_tools: set[str] = set()
    for turn_index in range(1, state.policy.maximum_turns_per_generation + 1):
        proposal_refs = tuple(proposal.candidate_ref for proposal in proposals)
        allow_action = turn_index < state.policy.maximum_turns_per_generation
        raw = state.call(
            turn_index=turn_index,
            turn_role="react_action",
            response_schema=react_response_schema(
                state.policy,
                proposal_refs,
                allow_action=allow_action,
            ),
            tool_outputs=[_safe_tool_output(proposal) for proposal in proposals],
        )
        try:
            decision, tools, selected = validate_react_response(
                raw,
                state.policy,
                proposal_refs,
                allow_action=allow_action,
            )
            if decision == "act":
                proposals.extend(
                    _run_local_tools(tools, state.observation, already_used=used_tools)
                )
                continue
            if decision == "abandon":
                return _result(state, None)
            if selected is None:
                state.fail("react_selected_proposal_missing")
            source = _proposal_by_ref(proposals, selected)
            return _result(state, _finalize_proposal(state, source, trigger_decision=None))
        except (BenchmarkAdapterError, BenchmarkLLMContractError):
            state.fail("react_state_rejected")
    state.fail("react_turn_cap_exhausted")


def _execute_plan_revision(
    state: _ExecutionState,
    *,
    adaptive: bool,
    previous_family_state: Mapping[str, tuple[int, int]] | None,
) -> BenchmarkOfflineLLMExecutionV1:
    raw_plan = state.call(
        turn_index=1,
        turn_role="plan",
        response_schema=tool_action_response_schema(state.policy, allow_stop=adaptive),
    )
    try:
        decision, tools = validate_tool_action_response(
            raw_plan,
            state.policy,
            allow_stop=adaptive,
        )
    except BenchmarkLLMContractError:
        state.fail("plan_schema_rejected")
    if decision == "stop":
        if not adaptive:
            state.fail("fixed_two_turn_plan_cannot_stop")
        return _result(state, None)
    try:
        proposals = _run_local_tools(tools, state.observation, already_used=set())
    except BenchmarkAdapterError:
        state.fail("local_tool_failed")
    proposal_refs = tuple(proposal.candidate_ref for proposal in proposals)
    tool_outputs = [_safe_tool_output(proposal) for proposal in proposals]
    raw_revision = state.call(
        turn_index=2,
        turn_role="revision",
        response_schema=selection_response_schema(proposal_refs),
        tool_outputs=tool_outputs,
    )
    try:
        selected_ref = validate_selection_response(raw_revision, proposal_refs)
    except BenchmarkLLMContractError:
        state.fail("revision_schema_rejected")
    if selected_ref is None:
        return _result(state, None)
    try:
        selected = _proposal_by_ref(proposals, selected_ref)
    except BenchmarkLLMContractError:
        state.fail("revision_selected_unknown_proposal")
    if not adaptive:
        return _result(state, _finalize_proposal(state, selected, trigger_decision=None))

    trigger = evaluate_benchmark_adaptive_triggers(
        state.observation,
        proposals,
        selected,
        previous_family_state=previous_family_state,
    )
    if trigger.diagnosis_reasons:
        diagnosis_context = [
            *tool_outputs,
            {"review_trigger_reasons": list(trigger.diagnosis_reasons)},
        ]
        raw_diagnosis = state.call(
            turn_index=3,
            turn_role="diagnosis",
            response_schema=diagnosis_response_schema(proposal_refs),
            tool_outputs=diagnosis_context,
        )
        try:
            selected_ref = validate_diagnosis_response(
                raw_diagnosis,
                proposal_refs,
                selected.candidate_ref,
            )
        except BenchmarkLLMContractError:
            state.fail("diagnosis_schema_rejected")
        if selected_ref is None:
            return _result(state, None, trigger_decision=trigger)
        try:
            selected = _proposal_by_ref(proposals, selected_ref)
        except BenchmarkLLMContractError:
            state.fail("diagnosis_selected_unknown_proposal")
    if trigger.critic_reasons:
        critic_context = [
            *_safe_tool_output_list(proposals),
            {
                "review_trigger_reasons": list(trigger.critic_reasons),
                "selected_proposal_ref": selected.candidate_ref,
            },
        ]
        raw_critic = state.call(
            turn_index=4,
            turn_role="critic",
            response_schema=critic_response_schema(selected.candidate_ref),
            tool_outputs=critic_context,
        )
        try:
            approved = validate_critic_response(raw_critic, selected.candidate_ref)
        except BenchmarkLLMContractError:
            state.fail("critic_schema_rejected")
        if not approved:
            return _result(state, None, trigger_decision=trigger)
    return _result(
        state,
        _finalize_proposal(state, selected, trigger_decision=trigger),
        trigger_decision=trigger,
    )


def _safe_tool_output_list(proposals: Sequence[BenchmarkProposalV1]) -> list[dict[str, Any]]:
    return [_safe_tool_output(proposal) for proposal in proposals]


def execute_offline_llm_arm(
    adapter_id: str,
    observation: BenchmarkObservationV2,
    *,
    provider: OfflineFixtureProvider,
    model_snapshot: str = "offline-sequence-fixture-v1",
    previous_family_state: Mapping[str, tuple[int, int]] | None = None,
    first_qualified_frozen: bool = False,
) -> BenchmarkOfflineLLMExecutionV1:
    """Execute one LLM arm without credentials, network, database, or simulator I/O."""

    if getattr(provider, "fixture_only", None) is not True:
        raise BenchmarkLLMFixtureExecutionError(
            "provider_is_not_offline_fixture",
            attempted=0,
            succeeded=0,
            turn_receipts=(),
            response_sha256=(),
        )
    policy = require_llm_arm_policy(adapter_id)
    state = _ExecutionState(
        provider=provider,
        policy=policy,
        observation=observation,
        model_snapshot=model_snapshot,
    )
    if first_qualified_frozen:
        return _result(state, None, terminal_status="first_qualified_stop")
    if policy.adapter_id == "llm_direct/v1":
        source = _direct_source_proposal(state, turn_role="direct_proposal")
        return _result(state, _finalize_proposal(state, source, trigger_decision=None))
    if policy.adapter_id == "llambo_uav/v1":
        source = _direct_source_proposal(state, turn_role="llambo_proposal")
        return _result(state, _finalize_proposal(state, source, trigger_decision=None))
    if policy.adapter_id == "llm_react/v1":
        return _execute_react(state)
    return _execute_plan_revision(
        state,
        adaptive=policy.adapter_id == "dronedream_adaptive_1_4/v1",
        previous_family_state=previous_family_state,
    )


__all__ = [
    "BENCHMARK_ADAPTIVE_TRIGGER_POLICY_VERSION",
    "BENCHMARK_FIXTURE_RUNTIME_SCHEMA_ID",
    "BenchmarkAdaptiveTriggerDecisionV1",
    "BenchmarkLLMFixtureExecutionError",
    "BenchmarkOfflineLLMExecutionV1",
    "OfflineFixtureProvider",
    "evaluate_benchmark_adaptive_triggers",
    "execute_offline_llm_arm",
]
