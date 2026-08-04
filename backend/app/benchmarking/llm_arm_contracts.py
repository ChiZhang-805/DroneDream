"""Closed, provider-neutral contracts for fair LLM benchmark arms.

This module is deliberately pure: it does not open a network connection, read a
JobSecret, access the database, or run a simulator.  Every LLM arm receives the
same identity-neutral observation payload; only its preregistered cognitive
policy and prompt role may differ.
"""

from __future__ import annotations

import json
import math
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.adapters import search_space_from_observation
from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    Sha256Hex,
    canonical_json_bytes,
    canonical_sha256,
)

BenchmarkLLMAdapterId = Literal[
    "llm_direct/v1",
    "llm_react/v1",
    "llambo_uav/v1",
    "dronedream_fixed_two_turn/v1",
    "dronedream_adaptive_1_4/v1",
]
BenchmarkTurnRole = Literal[
    "direct_proposal",
    "react_action",
    "llambo_proposal",
    "plan",
    "revision",
    "diagnosis",
    "critic",
]
BenchmarkToolMode = Literal["none", "bounded_react", "plan_then_revision"]
BenchmarkProviderInterventionId = Literal[
    "single_turn_proposal/v1",
    "bounded_tool_loop/v1",
    "uav_llm_bo_proposal/v1",
    "fixed_plan_revision/v1",
    "adaptive_plan_revision_review/v1",
]

BENCHMARK_LLM_POLICY_SCHEMA_ID: Final = "dronedream.benchmark-llm-arm-policy/v1"
BENCHMARK_LLM_TURN_SCHEMA_ID: Final = "dronedream.benchmark-llm-turn-request/v1"
BENCHMARK_LLM_PROMPT_VERSION: Final = "benchmark-fair-observation-v1"
BENCHMARK_LLM_MAX_PROMPT_BYTES: Final = 32_768
BENCHMARK_LLM_MAX_RESPONSE_BYTES: Final = 8_192
BENCHMARK_LLM_MAX_TURNS_PER_GENERATION: Final = 4
BENCHMARK_LOCAL_TOOL_ADAPTERS: Final = (
    "random_search/v1",
    "seeded_halton/v1",
    "repo_constrained_mobo/v1",
    "optimizer_portfolio/v1",
)


class BenchmarkLLMContractError(ValueError):
    """A turn would violate the frozen provider-neutral benchmark contract."""


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkLLMArmPolicyV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-llm-arm-policy/v1"] = (
        "dronedream.benchmark-llm-arm-policy/v1"
    )
    adapter_id: BenchmarkLLMAdapterId
    provider_intervention_id: BenchmarkProviderInterventionId
    prompt_version: Literal["benchmark-fair-observation-v1"] = "benchmark-fair-observation-v1"
    minimum_turns_per_generation: Annotated[int, Field(ge=1, le=4)]
    maximum_turns_per_generation: Annotated[int, Field(ge=1, le=4)]
    allowed_turn_roles: tuple[BenchmarkTurnRole, ...] = Field(min_length=1, max_length=7)
    tool_mode: BenchmarkToolMode
    allowed_tool_adapter_ids: tuple[str, ...] = Field(default=(), max_length=8)
    provider_retry_cap: Literal[0] = 0
    maximum_prompt_utf8_bytes: Literal[32768] = BENCHMARK_LLM_MAX_PROMPT_BYTES
    maximum_response_utf8_bytes: Literal[8192] = BENCHMARK_LLM_MAX_RESPONSE_BYTES

    @model_validator(mode="after")
    def _validate_policy(self) -> BenchmarkLLMArmPolicyV1:
        if self.minimum_turns_per_generation > self.maximum_turns_per_generation:
            raise ValueError("minimum turns cannot exceed maximum turns")
        if len(set(self.allowed_turn_roles)) != len(self.allowed_turn_roles):
            raise ValueError("turn roles must be unique")
        if self.maximum_turns_per_generation > BENCHMARK_LLM_MAX_TURNS_PER_GENERATION:
            raise ValueError("per-generation turn cap exceeds the product absolute limit")
        if self.tool_mode == "none" and self.allowed_tool_adapter_ids:
            raise ValueError("tool-free arms cannot declare local tools")
        if self.tool_mode != "none":
            if not self.allowed_tool_adapter_ids:
                raise ValueError("tool-using arms require a non-empty allowlist")
            if not set(self.allowed_tool_adapter_ids).issubset(BENCHMARK_LOCAL_TOOL_ADAPTERS):
                raise ValueError("LLM benchmark arm declared an unreviewed local tool")
        return self


class BenchmarkLLMTurnRequestV1(_FrozenStrict):
    """In-memory request plus immutable hashes; raw text must not enter receipts."""

    schema_id: Literal["dronedream.benchmark-llm-turn-request/v1"] = (
        "dronedream.benchmark-llm-turn-request/v1"
    )
    adapter_id: BenchmarkLLMAdapterId
    generation_index: Annotated[int, Field(ge=0)]
    turn_index: Annotated[int, Field(ge=1, le=4)]
    turn_role: BenchmarkTurnRole
    model_snapshot: Annotated[str, Field(min_length=1, max_length=255)]
    system: Annotated[str, Field(min_length=1, max_length=16_384)]
    user: Annotated[str, Field(min_length=1, max_length=32_768)]
    response_schema: dict[str, Any]
    prompt_sha256: Sha256Hex
    evidence_sha256: Sha256Hex
    response_schema_sha256: Sha256Hex
    tool_outputs_sha256: Sha256Hex
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_hashes_and_size(self) -> BenchmarkLLMTurnRequestV1:
        prompt_bytes = f"{self.system}\n{self.user}".encode()
        if len(prompt_bytes) > BENCHMARK_LLM_MAX_PROMPT_BYTES:
            raise ValueError("benchmark LLM prompt exceeds 32768 UTF-8 bytes")
        if canonical_sha256({"system": self.system, "user": self.user}) != self.prompt_sha256:
            raise ValueError("benchmark LLM prompt hash does not match raw request text")
        if canonical_sha256(self.response_schema) != self.response_schema_sha256:
            raise ValueError("benchmark LLM response schema hash does not match")
        binding = {
            "adapter_id": self.adapter_id,
            "evidence_sha256": self.evidence_sha256,
            "generation_index": self.generation_index,
            "model_snapshot": self.model_snapshot,
            "prompt_sha256": self.prompt_sha256,
            "response_schema_sha256": self.response_schema_sha256,
            "tool_outputs_sha256": self.tool_outputs_sha256,
            "turn_index": self.turn_index,
            "turn_role": self.turn_role,
        }
        if canonical_sha256(binding) != self.binding_sha256:
            raise ValueError("benchmark LLM turn binding hash does not match")
        return self

    def receipt_payload(self) -> dict[str, Any]:
        """Return persistence-safe provenance without prompts or provider request IDs."""

        return {
            "schema_id": "dronedream.benchmark-llm-turn-binding/v1",
            "adapter_id": self.adapter_id,
            "generation_index": self.generation_index,
            "turn_index": self.turn_index,
            "turn_role": self.turn_role,
            "model_snapshot": self.model_snapshot,
            "prompt_sha256": self.prompt_sha256,
            "evidence_sha256": self.evidence_sha256,
            "response_schema_sha256": self.response_schema_sha256,
            "tool_outputs_sha256": self.tool_outputs_sha256,
            "binding_sha256": self.binding_sha256,
        }


def _policy(
    adapter_id: BenchmarkLLMAdapterId,
    *,
    provider_intervention_id: BenchmarkProviderInterventionId,
    minimum_turns: int,
    maximum_turns: int,
    roles: tuple[BenchmarkTurnRole, ...],
    tool_mode: BenchmarkToolMode,
) -> BenchmarkLLMArmPolicyV1:
    return BenchmarkLLMArmPolicyV1(
        adapter_id=adapter_id,
        provider_intervention_id=provider_intervention_id,
        minimum_turns_per_generation=minimum_turns,
        maximum_turns_per_generation=maximum_turns,
        allowed_turn_roles=roles,
        tool_mode=tool_mode,
        allowed_tool_adapter_ids=(() if tool_mode == "none" else BENCHMARK_LOCAL_TOOL_ADAPTERS),
    )


_POLICIES = (
    _policy(
        "llm_direct/v1",
        provider_intervention_id="single_turn_proposal/v1",
        minimum_turns=1,
        maximum_turns=1,
        roles=("direct_proposal",),
        tool_mode="none",
    ),
    _policy(
        "llm_react/v1",
        provider_intervention_id="bounded_tool_loop/v1",
        minimum_turns=1,
        maximum_turns=4,
        roles=("react_action",),
        tool_mode="bounded_react",
    ),
    _policy(
        "llambo_uav/v1",
        provider_intervention_id="uav_llm_bo_proposal/v1",
        minimum_turns=1,
        maximum_turns=1,
        roles=("llambo_proposal",),
        tool_mode="none",
    ),
    _policy(
        "dronedream_fixed_two_turn/v1",
        provider_intervention_id="fixed_plan_revision/v1",
        minimum_turns=2,
        maximum_turns=2,
        roles=("plan", "revision"),
        tool_mode="plan_then_revision",
    ),
    _policy(
        "dronedream_adaptive_1_4/v1",
        provider_intervention_id="adaptive_plan_revision_review/v1",
        minimum_turns=1,
        maximum_turns=4,
        roles=("plan", "revision", "diagnosis", "critic"),
        tool_mode="plan_then_revision",
    ),
)

_POLICIES_BY_ID: dict[str, BenchmarkLLMArmPolicyV1] = {item.adapter_id: item for item in _POLICIES}
BENCHMARK_LLM_ARM_POLICIES = MappingProxyType(_POLICIES_BY_ID)
if len(BENCHMARK_LLM_ARM_POLICIES) != len(_POLICIES):
    raise RuntimeError("duplicate adapter_id in benchmark LLM arm policies")

BENCHMARK_LLM_ARM_POLICIES_SHA256: Final = canonical_sha256(
    [
        BENCHMARK_LLM_ARM_POLICIES[adapter_id].model_dump(mode="json")
        for adapter_id in sorted(BENCHMARK_LLM_ARM_POLICIES)
    ]
)


def require_llm_arm_policy(adapter_id: str) -> BenchmarkLLMArmPolicyV1:
    try:
        return BENCHMARK_LLM_ARM_POLICIES[adapter_id]
    except KeyError as exc:
        raise BenchmarkLLMContractError(f"unknown benchmark LLM arm: {adapter_id}") from exc


def fair_provider_evidence(observation: BenchmarkObservationV2) -> dict[str, Any]:
    """Return the exact shared provider view, excluding arm/run identity bias."""

    payload = observation.model_dump(mode="json", exclude_none=False)
    for key in ("benchmark_arm_id", "campaign_id", "run_id"):
        payload.pop(key, None)
    payload["provider_view_schema_id"] = "dronedream.benchmark-provider-view/v1"
    payload["qualification_holdout_visible"] = False
    return payload


def proposal_response_schema(observation: BenchmarkObservationV2) -> dict[str, Any]:
    search_space = search_space_from_observation(observation)
    properties: dict[str, Any] = {}
    for domain in search_space.domains:
        item: dict[str, Any] = {
            "type": "number" if domain.value_type == "float" else "integer",
            "minimum": domain.minimum,
            "maximum": domain.maximum,
        }
        if domain.choices:
            item["enum"] = list(domain.choices)
        properties[domain.name] = item
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "decision", "parameters"],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "decision": {"type": "string", "enum": ["propose"]},
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": [domain.name for domain in search_space.domains],
                "properties": properties,
            },
        },
    }


def tool_action_response_schema(policy: BenchmarkLLMArmPolicyV1) -> dict[str, Any]:
    if policy.tool_mode == "none":
        raise BenchmarkLLMContractError("tool-free arms cannot request an action schema")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "decision", "tool_adapter_ids"],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "decision": {"type": "string", "enum": ["act", "stop"]},
            "tool_adapter_ids": {
                "type": "array",
                "items": {"type": "string", "enum": list(policy.allowed_tool_adapter_ids)},
                "uniqueItems": True,
                "maxItems": 2,
            },
        },
    }


def selection_response_schema(proposal_refs: tuple[str, ...]) -> dict[str, Any]:
    if not proposal_refs or len(set(proposal_refs)) != len(proposal_refs):
        raise BenchmarkLLMContractError("selection schema requires unique proposal references")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "decision", "selected_proposal_ref"],
        "properties": {
            "schema_version": {"type": "string", "enum": ["1.0"]},
            "decision": {"type": "string", "enum": ["dispatch", "abandon"]},
            "selected_proposal_ref": {
                "anyOf": [
                    {"type": "string", "enum": list(proposal_refs)},
                    {"type": "null"},
                ]
            },
        },
    }


def _canonical_json_text(value: BaseModel | dict[str, Any] | list[Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def build_llm_turn_request(
    *,
    policy: BenchmarkLLMArmPolicyV1,
    observation: BenchmarkObservationV2,
    model_snapshot: str,
    turn_index: int,
    turn_role: BenchmarkTurnRole,
    response_schema: dict[str, Any],
    tool_outputs: list[dict[str, Any]] | None = None,
) -> BenchmarkLLMTurnRequestV1:
    if turn_role not in policy.allowed_turn_roles:
        raise BenchmarkLLMContractError(
            f"turn role {turn_role} is not allowed for {policy.adapter_id}"
        )
    if turn_index > policy.maximum_turns_per_generation:
        raise BenchmarkLLMContractError("benchmark arm exceeded its per-generation turn cap")
    expected_role = (
        policy.allowed_turn_roles[0]
        if policy.tool_mode == "bounded_react"
        else policy.allowed_turn_roles[turn_index - 1]
    )
    if turn_role != expected_role:
        raise BenchmarkLLMContractError(
            f"turn {turn_index} must use role {expected_role} for {policy.adapter_id}"
        )
    evidence = fair_provider_evidence(observation)
    bounded_tool_outputs = tool_outputs or []
    system = (
        "You are a bounded DroneDream benchmark decision component. "
        "Use only the supplied frozen observation and allowlisted local-tool outputs. "
        "PX4 remains the high-rate controller. Qualification holdout outcomes, credentials, "
        "raw chat, filesystem, shell, network tools, and hidden prompts are unavailable. "
        "Return only JSON matching the closed response schema."
    )
    user_payload = {
        "schema_id": "dronedream.benchmark-llm-turn-input/v1",
        "prompt_version": policy.prompt_version,
        "arm_intervention": policy.provider_intervention_id,
        "turn_index": turn_index,
        "turn_role": turn_role,
        "observation": evidence,
        "allowlisted_tool_adapter_ids": list(policy.allowed_tool_adapter_ids),
        "tool_outputs": bounded_tool_outputs,
        "response_schema_sha256": canonical_sha256(response_schema),
    }
    user = _canonical_json_text(user_payload)
    prompt_sha256 = canonical_sha256({"system": system, "user": user})
    evidence_sha256 = canonical_sha256(evidence)
    response_schema_sha256 = canonical_sha256(response_schema)
    tool_outputs_sha256 = canonical_sha256(bounded_tool_outputs)
    binding = {
        "adapter_id": policy.adapter_id,
        "evidence_sha256": evidence_sha256,
        "generation_index": observation.generation_index,
        "model_snapshot": model_snapshot,
        "prompt_sha256": prompt_sha256,
        "response_schema_sha256": response_schema_sha256,
        "tool_outputs_sha256": tool_outputs_sha256,
        "turn_index": turn_index,
        "turn_role": turn_role,
    }
    try:
        return BenchmarkLLMTurnRequestV1(
            adapter_id=policy.adapter_id,
            generation_index=observation.generation_index,
            turn_index=turn_index,
            turn_role=turn_role,
            model_snapshot=model_snapshot,
            system=system,
            user=user,
            response_schema=response_schema,
            prompt_sha256=prompt_sha256,
            evidence_sha256=evidence_sha256,
            response_schema_sha256=response_schema_sha256,
            tool_outputs_sha256=tool_outputs_sha256,
            binding_sha256=canonical_sha256(binding),
        )
    except ValueError as exc:
        raise BenchmarkLLMContractError(str(exc)) from exc


def validate_proposal_response(
    raw: object,
    observation: BenchmarkObservationV2,
) -> dict[str, float]:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "decision",
        "parameters",
    }:
        raise BenchmarkLLMContractError("proposal response does not match the closed schema")
    if raw.get("schema_version") != "1.0" or raw.get("decision") != "propose":
        raise BenchmarkLLMContractError("proposal response has an invalid version or decision")
    parameters = raw.get("parameters")
    if not isinstance(parameters, dict):
        raise BenchmarkLLMContractError("proposal parameters must be an object")
    search_space = search_space_from_observation(observation)
    expected = {domain.name for domain in search_space.domains}
    if set(parameters) != expected:
        raise BenchmarkLLMContractError("proposal parameter names differ from the frozen domain")
    numeric: dict[str, float] = {}
    for name, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise BenchmarkLLMContractError(f"proposal parameter {name} is not numeric")
        number = float(value)
        if not math.isfinite(number):
            raise BenchmarkLLMContractError(f"proposal parameter {name} is not finite")
        numeric[name] = number
    try:
        projected = search_space.project(numeric)
    except ValueError as exc:
        raise BenchmarkLLMContractError(str(exc)) from exc
    if any(
        not math.isclose(projected[name], numeric[name], rel_tol=0.0, abs_tol=1e-12)
        for name in expected
    ):
        raise BenchmarkLLMContractError("proposal violates the frozen parameter domain")
    return projected


def validate_tool_action_response(
    raw: object,
    policy: BenchmarkLLMArmPolicyV1,
) -> tuple[Literal["act", "stop"], tuple[str, ...]]:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "decision",
        "tool_adapter_ids",
    }:
        raise BenchmarkLLMContractError("tool action does not match the closed schema")
    decision = raw.get("decision")
    tools = raw.get("tool_adapter_ids")
    if raw.get("schema_version") != "1.0" or decision not in {"act", "stop"}:
        raise BenchmarkLLMContractError("tool action has an invalid version or decision")
    if not isinstance(tools, list) or any(not isinstance(item, str) for item in tools):
        raise BenchmarkLLMContractError("tool_adapter_ids must be a string array")
    selected = tuple(tools)
    if len(selected) != len(set(selected)) or len(selected) > 2:
        raise BenchmarkLLMContractError("tool action contains duplicate or excessive tools")
    if not set(selected).issubset(policy.allowed_tool_adapter_ids):
        raise BenchmarkLLMContractError("tool action selected an unreviewed tool")
    if decision == "act" and not selected:
        raise BenchmarkLLMContractError("act requires at least one tool")
    if decision == "stop" and selected:
        raise BenchmarkLLMContractError("stop cannot select tools")
    return decision, selected


def validate_selection_response(
    raw: object,
    proposal_refs: tuple[str, ...],
) -> str | None:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "decision",
        "selected_proposal_ref",
    }:
        raise BenchmarkLLMContractError("selection response does not match the closed schema")
    decision = raw.get("decision")
    selected = raw.get("selected_proposal_ref")
    if raw.get("schema_version") != "1.0" or decision not in {"dispatch", "abandon"}:
        raise BenchmarkLLMContractError("selection has an invalid version or decision")
    if decision == "abandon":
        if selected is not None:
            raise BenchmarkLLMContractError("abandon cannot select a proposal")
        return None
    if not isinstance(selected, str) or selected not in proposal_refs:
        raise BenchmarkLLMContractError("dispatch selected an unknown proposal reference")
    return selected


def assert_unique_turn_bindings(requests: tuple[BenchmarkLLMTurnRequestV1, ...]) -> None:
    bindings = [request.binding_sha256 for request in requests]
    if len(bindings) != len(set(bindings)):
        raise BenchmarkLLMContractError("duplicate benchmark LLM turn binding would double-charge")


def parse_bounded_json_response(raw_text: str) -> object:
    payload = raw_text.encode("utf-8")
    if len(payload) > BENCHMARK_LLM_MAX_RESPONSE_BYTES:
        raise BenchmarkLLMContractError("benchmark LLM response exceeds 8192 UTF-8 bytes")
    try:
        return json.loads(raw_text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise BenchmarkLLMContractError("benchmark LLM response is not finite JSON") from exc


def _reject_json_constant(value: str) -> None:
    raise ValueError(value)


__all__ = [
    "BENCHMARK_LLM_ARM_POLICIES",
    "BENCHMARK_LLM_ARM_POLICIES_SHA256",
    "BENCHMARK_LLM_MAX_PROMPT_BYTES",
    "BENCHMARK_LLM_MAX_RESPONSE_BYTES",
    "BENCHMARK_LLM_MAX_TURNS_PER_GENERATION",
    "BENCHMARK_LOCAL_TOOL_ADAPTERS",
    "BenchmarkLLMArmPolicyV1",
    "BenchmarkLLMContractError",
    "BenchmarkLLMTurnRequestV1",
    "assert_unique_turn_bindings",
    "build_llm_turn_request",
    "fair_provider_evidence",
    "parse_bounded_json_response",
    "proposal_response_schema",
    "require_llm_arm_policy",
    "selection_response_schema",
    "tool_action_response_schema",
    "validate_proposal_response",
    "validate_selection_response",
    "validate_tool_action_response",
]
