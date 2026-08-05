"""Durable, fail-closed execution boundaries for provider benchmark arms.

Campaign/run/source provenance is revalidated, logical turns and actual requests
are committed before provider I/O, and no retry or compatibility fallback is
permitted. Credentials remain an implementation detail of the injected transport
and are never accepted by these contracts.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Literal, NoReturn, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.benchmarking.adapters import BenchmarkAdapterError
from app.benchmarking.contracts import (
    BenchmarkArmManifestV1,
    BenchmarkCampaignManifestV1,
    BenchmarkObservationV2,
    BenchmarkProposalV1,
    BenchmarkRunBindingRequestV1,
    CompositeExecutionInventoryV1,
    canonical_json_bytes,
    canonical_sha256,
)
from app.benchmarking.coordinator import run_binding_sha256
from app.benchmarking.llm_arm_contracts import (
    BENCHMARK_LLM_ARM_POLICIES_SHA256,
    BenchmarkLLMContractError,
    BenchmarkLLMTurnRequestV1,
    build_llm_turn_request,
    parse_bounded_json_response,
    proposal_response_schema,
    react_response_schema,
    require_llm_arm_policy,
    selection_response_schema,
    tool_action_response_schema,
    validate_proposal_response,
    validate_react_response,
    validate_selection_response,
    validate_tool_action_response,
)
from app.benchmarking.provider_execution_contract import (
    BENCHMARK_DIRECT_RESERVATION_REASON,
    BENCHMARK_PROVIDER_BASE_URLS,
    BenchmarkProviderExecutionConfigV1,
    BenchmarkProviderRequestEnvelope,
    provider_run_capacity,
)
from app.benchmarking.provider_usage_reconciliation import (
    BenchmarkProviderUsageBlocked,
    reconcile_provider_run_usage,
    validate_provider_run_reservation,
)
from app.benchmarking.registry import create_benchmark_adapter
from app.orchestration.cognitive_budget import (
    CognitiveTurnAttempt,
    begin_benchmark_llm_turn,
    cancel_cognitive_turn_if_job_terminal,
    finish_cognitive_turn,
    resolve_source_commit,
)
from app.orchestration.provider_request_accounting import (
    BoundProviderRequestAccountant,
    ProviderUsage,
    provider_request_counts_for_turn,
)

BENCHMARK_DIRECT_PROPOSAL_RECEIPT_SCHEMA_ID = "dronedream.benchmark-direct-proposal/v1"
BENCHMARK_DIRECT_PROPOSAL_HANDOFF_SCHEMA_ID = "dronedream.benchmark-direct-proposal-handoff/v1"
BENCHMARK_LLAMBO_PROPOSAL_RECEIPT_SCHEMA_ID = "dronedream.benchmark-llambo-uav-proposal/v1"
BENCHMARK_LLAMBO_PROPOSAL_HANDOFF_SCHEMA_ID = "dronedream.benchmark-llambo-uav-proposal-handoff/v1"
BENCHMARK_REACT_CHECKPOINT_SCHEMA_ID = "dronedream.benchmark-llm-react-checkpoint/v1"
BENCHMARK_REACT_PROPOSAL_RECEIPT_SCHEMA_ID = "dronedream.benchmark-llm-react-proposal/v1"
BENCHMARK_PLAN_REVISION_CHECKPOINT_SCHEMA_ID = (
    "dronedream.benchmark-llm-plan-revision-checkpoint/v1"
)
BENCHMARK_FIXED_TWO_TURN_PROPOSAL_RECEIPT_SCHEMA_ID = (
    "dronedream.benchmark-fixed-two-turn-proposal/v1"
)


class BenchmarkDurableLLMBlocked(RuntimeError):
    """The durable arm was denied without leaking provider or prompt details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


@dataclass(frozen=True)
class BenchmarkProviderTransportResult:
    response_text: str
    usage: ProviderUsage
    latency_ms: int


class BenchmarkDirectTransport(Protocol):
    """Credential-owning transport; credentials never cross this interface."""

    def complete(
        self,
        request: BenchmarkProviderRequestEnvelope,
        config: BenchmarkProviderExecutionConfigV1,
    ) -> BenchmarkProviderTransportResult: ...


BenchmarkDirectTransportFactory = Callable[
    [BenchmarkProviderExecutionConfigV1], BenchmarkDirectTransport
]


class BenchmarkDurableDirectExecutionV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-durable-direct-execution/v1"] = (
        "dronedream.benchmark-durable-direct-execution/v1"
    )
    status: Literal["proposal", "proposal_recovered", "first_qualified_stop"]
    proposal: BenchmarkProposalV1 | None
    provider_turns_attempted: Annotated[int, Field(ge=0, le=1)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=1)]
    provider_requests_attempted: Annotated[int, Field(ge=0, le=1)]
    provider_requests_succeeded: Annotated[int, Field(ge=0, le=1)]
    recovered_from_handoff: bool = False
    safe_receipt: dict[str, Any]

    @model_validator(mode="after")
    def _validate_result(self) -> BenchmarkDurableDirectExecutionV1:
        if self.status in {"proposal", "proposal_recovered"}:
            if self.proposal is None or self.provider_turns_succeeded != 1:
                raise ValueError("proposal result requires one successful durable turn")
            if self.recovered_from_handoff != (self.status == "proposal_recovered"):
                raise ValueError("proposal recovery status and flag disagree")
        elif self.proposal is not None or any(
            (
                self.provider_turns_attempted,
                self.provider_turns_succeeded,
                self.provider_requests_attempted,
                self.provider_requests_succeeded,
            )
        ):
            raise ValueError("first-qualified stop must consume zero provider work")
        elif self.recovered_from_handoff:
            raise ValueError("first-qualified stop cannot be a recovered proposal")
        return self


class BenchmarkDurableLLAMBOExecutionV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-durable-llambo-uav-execution/v1"] = (
        "dronedream.benchmark-durable-llambo-uav-execution/v1"
    )
    status: Literal["proposal", "proposal_recovered", "first_qualified_stop"]
    proposal: BenchmarkProposalV1 | None
    provider_turns_attempted: Annotated[int, Field(ge=0, le=1)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=1)]
    provider_requests_attempted: Annotated[int, Field(ge=0, le=1)]
    provider_requests_succeeded: Annotated[int, Field(ge=0, le=1)]
    recovered_from_handoff: bool = False
    safe_receipt: dict[str, Any]

    @model_validator(mode="after")
    def _validate_result(self) -> BenchmarkDurableLLAMBOExecutionV1:
        if self.status in {"proposal", "proposal_recovered"}:
            if self.proposal is None or self.provider_turns_succeeded != 1:
                raise ValueError("LLAMBO proposal result requires one successful durable turn")
            if self.recovered_from_handoff != (self.status == "proposal_recovered"):
                raise ValueError("LLAMBO proposal recovery status and flag disagree")
        elif self.proposal is not None or any(
            (
                self.provider_turns_attempted,
                self.provider_turns_succeeded,
                self.provider_requests_attempted,
                self.provider_requests_succeeded,
            )
        ):
            raise ValueError("first-qualified stop must consume zero provider work")
        elif self.recovered_from_handoff:
            raise ValueError("first-qualified stop cannot be a recovered proposal")
        return self


class BenchmarkDurableReactExecutionV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-durable-react-execution/v1"] = (
        "dronedream.benchmark-durable-react-execution/v1"
    )
    status: Literal[
        "proposal",
        "proposal_recovered",
        "abandoned",
        "abandoned_recovered",
        "first_qualified_stop",
    ]
    proposal: BenchmarkProposalV1 | None
    provider_turns_attempted: Annotated[int, Field(ge=0, le=4)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=4)]
    provider_requests_attempted: Annotated[int, Field(ge=0, le=4)]
    provider_requests_succeeded: Annotated[int, Field(ge=0, le=4)]
    recovered_from_checkpoint: bool = False
    safe_receipt: dict[str, Any]

    @model_validator(mode="after")
    def _validate_result(self) -> BenchmarkDurableReactExecutionV1:
        if self.provider_turns_succeeded > self.provider_turns_attempted:
            raise ValueError("successful turns cannot exceed attempted turns")
        if self.provider_requests_succeeded > self.provider_requests_attempted:
            raise ValueError("successful requests cannot exceed attempted requests")
        if self.provider_requests_attempted != self.provider_turns_attempted:
            raise ValueError("bounded ReAct permits exactly one request per attempted turn")
        if self.status.startswith("proposal") != (self.proposal is not None):
            raise ValueError("ReAct proposal status and payload disagree")
        if self.status == "first_qualified_stop" and any(
            (
                self.provider_turns_attempted,
                self.provider_turns_succeeded,
                self.provider_requests_attempted,
                self.provider_requests_succeeded,
            )
        ):
            raise ValueError("first-qualified stop must consume zero provider work")
        if self.recovered_from_checkpoint != self.status.endswith("_recovered"):
            raise ValueError("ReAct recovery status and flag disagree")
        return self


class BenchmarkDurableFixedTwoTurnExecutionV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-durable-fixed-two-turn-execution/v1"] = (
        "dronedream.benchmark-durable-fixed-two-turn-execution/v1"
    )
    status: Literal[
        "proposal",
        "proposal_recovered",
        "abandoned",
        "abandoned_recovered",
        "first_qualified_stop",
    ]
    proposal: BenchmarkProposalV1 | None
    provider_turns_attempted: Annotated[int, Field(ge=0, le=2)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=2)]
    provider_requests_attempted: Annotated[int, Field(ge=0, le=2)]
    provider_requests_succeeded: Annotated[int, Field(ge=0, le=2)]
    recovered_from_checkpoint: bool = False
    safe_receipt: dict[str, Any]

    @model_validator(mode="after")
    def _validate_result(self) -> BenchmarkDurableFixedTwoTurnExecutionV1:
        if self.provider_turns_succeeded > self.provider_turns_attempted:
            raise ValueError("successful turns cannot exceed attempted turns")
        if self.provider_requests_succeeded > self.provider_requests_attempted:
            raise ValueError("successful requests cannot exceed attempted requests")
        if self.provider_requests_attempted != self.provider_turns_attempted:
            raise ValueError("fixed two-turn permits one request per attempted turn")
        if self.status == "first_qualified_stop":
            if self.proposal is not None or any(
                (
                    self.provider_turns_attempted,
                    self.provider_turns_succeeded,
                    self.provider_requests_attempted,
                    self.provider_requests_succeeded,
                )
            ):
                raise ValueError("first-qualified stop must consume zero provider work")
        elif self.provider_turns_attempted != 2 or self.provider_turns_succeeded != 2:
            raise ValueError("fixed plan/revision completion requires exactly two successful turns")
        if self.status.startswith("proposal") != (self.proposal is not None):
            raise ValueError("fixed two-turn proposal status and payload disagree")
        if self.recovered_from_checkpoint != self.status.endswith("_recovered"):
            raise ValueError("fixed two-turn recovery status and flag disagree")
        return self


def _usage_is_complete(value: object) -> bool:
    if not isinstance(value, ProviderUsage):
        return False
    input_tokens = value.input_tokens
    output_tokens = value.output_tokens
    total_tokens = value.total_tokens
    if input_tokens is None or output_tokens is None or total_tokens is None:
        return False
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item < 0
        for item in (input_tokens, output_tokens, total_tokens)
    ):
        return False
    return total_tokens >= input_tokens + output_tokens


@dataclass(frozen=True)
class _BoundDirectContext:
    binding: models.BenchmarkCampaignRunBinding
    arm: models.BenchmarkArm
    campaign: models.BenchmarkCampaign
    inventory: CompositeExecutionInventoryV1
    provider: BenchmarkProviderExecutionConfigV1
    source_commit: str


def _blocked(code: str, message: str) -> NoReturn:
    raise BenchmarkDurableLLMBlocked(code, message)


def _validate_run_binding(
    binding: models.BenchmarkCampaignRunBinding,
    arm: models.BenchmarkArm,
) -> None:
    scenario_suite_sha256 = binding.scenario_suite_sha256
    qualification_contract_sha256 = binding.qualification_contract_sha256
    if (
        binding.qualification_policy_version is None
        or scenario_suite_sha256 is None
        or qualification_contract_sha256 is None
    ):
        _blocked("benchmark_qualification_binding_missing", "Run qualification is not sealed.")
    request = BenchmarkRunBindingRequestV1(
        run_key=binding.run_key,
        job_id=binding.job_id,
        benchmark_arm_id=arm.benchmark_arm_id,
        arm_version=arm.arm_version,
        algorithm_seed=binding.algorithm_seed,
        simulator_seed_block=binding.simulator_seed_block,
        provider_randomness_policy=binding.provider_randomness_policy,  # type: ignore[arg-type]
        provider_seed=binding.provider_seed,
    )
    expected = run_binding_sha256(
        request,
        scenario_suite_sha256=scenario_suite_sha256,
        qualification_contract_sha256=qualification_contract_sha256,
    )
    if expected != binding.binding_sha256:
        _blocked("benchmark_run_binding_drift", "Run binding hash no longer matches its fields.")


def _load_context(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    expected_adapter_id: Literal[
        "llm_direct/v1",
        "llm_react/v1",
        "llambo_uav/v1",
        "dronedream_fixed_two_turn/v1",
    ] = ("llm_direct/v1"),
) -> _BoundDirectContext:
    binding = db.scalar(
        select(models.BenchmarkCampaignRunBinding).where(
            models.BenchmarkCampaignRunBinding.job_id == job.id
        )
    )
    if binding is None:
        _blocked("benchmark_run_binding_missing", "Job lacks an immutable benchmark run binding.")
    arm = db.get(models.BenchmarkArm, binding.benchmark_arm_id)
    campaign = db.get(models.BenchmarkCampaign, binding.campaign_id)
    batch_binding = db.get(models.BenchmarkCampaignBatchBinding, binding.batch_binding_id)
    if arm is None or campaign is None or batch_binding is None:
        _blocked("benchmark_binding_graph_incomplete", "Benchmark binding graph is incomplete.")
    if (
        campaign.status != "ACTIVE"
        or arm.campaign_id != campaign.id
        or batch_binding.campaign_id != campaign.id
        or binding.campaign_id != campaign.id
    ):
        _blocked("benchmark_campaign_inactive", "Benchmark campaign is inactive or mismatched.")
    if job.user_id is None or job.user_id != campaign.user_id:
        _blocked("benchmark_owner_mismatch", "Job and campaign owner identities differ.")
    if not arm.execution_enabled or arm.arm_family != "llm_harness":
        _blocked("benchmark_arm_execution_disabled", "Benchmark LLM arm is not execution-enabled.")

    try:
        arm_manifest = BenchmarkArmManifestV1.model_validate(arm.manifest_json)
        campaign_manifest = BenchmarkCampaignManifestV1.model_validate_json(
            canonical_json_bytes(campaign.manifest_json)
        )
        inventory = CompositeExecutionInventoryV1.model_validate(campaign.composite_inventory_json)
    except ValueError as exc:
        raise BenchmarkDurableLLMBlocked(
            "benchmark_manifest_invalid",
            "Benchmark manifest cannot be validated by the current schema.",
        ) from exc
    if canonical_sha256(arm_manifest) != arm.manifest_sha256:
        _blocked("benchmark_arm_manifest_drift", "Arm manifest hash no longer matches.")
    if canonical_sha256(campaign_manifest) != campaign.manifest_sha256:
        _blocked("benchmark_campaign_manifest_drift", "Campaign manifest hash no longer matches.")
    if canonical_sha256(inventory) != campaign.composite_inventory_sha256:
        _blocked("benchmark_inventory_drift", "Composite inventory hash no longer matches.")
    if campaign_manifest.composite_execution_inventory != inventory:
        _blocked("benchmark_inventory_manifest_mismatch", "Campaign inventory copies disagree.")
    matching_arms = [
        item
        for item in campaign_manifest.arms
        if item.benchmark_arm_id == arm.benchmark_arm_id and item.arm_version == arm.arm_version
    ]
    if len(matching_arms) != 1 or matching_arms[0] != arm_manifest:
        _blocked("benchmark_arm_campaign_mismatch", "Arm differs from the campaign manifest.")
    if (
        not arm_manifest.execution_enabled
        or arm_manifest.proposal_adapter_id != expected_adapter_id
        or arm.proposal_adapter_id != expected_adapter_id
        or arm_manifest.provider_contract_sha256 != BENCHMARK_LLM_ARM_POLICIES_SHA256
    ):
        _blocked("benchmark_llm_contract_mismatch", "Arm is not the frozen LLM contract.")
    provider_payload = arm_manifest.intervention.get("provider_execution")
    if not isinstance(provider_payload, dict):
        _blocked(
            "benchmark_provider_contract_invalid",
            "Provider execution contract is missing or invalid.",
        )
    try:
        provider = BenchmarkProviderExecutionConfigV1.model_validate_json(
            canonical_json_bytes(provider_payload)
        )
    except ValueError as exc:
        raise BenchmarkDurableLLMBlocked(
            "benchmark_provider_contract_invalid",
            "Provider execution contract is missing or invalid.",
        ) from exc
    if provider.model_matrix_sha256 != inventory.model_matrix_sha256:
        _blocked("benchmark_model_matrix_drift", "Provider model matrix differs from inventory.")
    if job.llm_access_mode != "byok":
        _blocked(
            "benchmark_provider_access_mode_drift",
            "Formal direct-arm execution requires the Job's frozen BYOK access mode.",
        )
    if job.llm_provider != provider.provider:
        _blocked(
            "benchmark_provider_identity_drift",
            "Job provider identity differs from the arm manifest.",
        )
    job_base_url = job.llm_base_url
    if job_base_url is None and job.llm_provider == "openai":
        # The legacy OpenAI request shape persists ``None`` for the SDK's exact
        # default origin.  Resolve that semantic default before comparing it
        # with the explicit, credential-free arm contract.
        job_base_url = BENCHMARK_PROVIDER_BASE_URLS["openai"]
    if job_base_url != provider.base_url:
        _blocked(
            "benchmark_provider_endpoint_drift",
            "Job provider endpoint differs from the arm manifest.",
        )
    if provider.model_snapshot != job.openai_model:
        _blocked("benchmark_model_snapshot_drift", "Job model differs from arm manifest.")
    policy = require_llm_arm_policy(expected_adapter_id)
    total_turn_cap = provider.maximum_generations * policy.maximum_turns_per_generation
    if provider.maximum_generations != job.max_iterations or (
        job.provider_turn_cap != total_turn_cap
        or job.provider_request_cap != total_turn_cap
        or job.provider_max_retries != 0
    ):
        _blocked(
            "benchmark_provider_budget_drift",
            "Job provider caps differ from the arm contract.",
        )
    if binding.provider_randomness_policy != provider.randomness_policy:
        _blocked(
            "benchmark_randomness_policy_drift",
            "Run and provider randomness policies differ.",
        )
    if provider.randomness_policy == "fixed_seed" and binding.provider_seed is None:
        _blocked("benchmark_provider_seed_missing", "Fixed-seed execution lacks a provider seed.")
    if provider.randomness_policy == "provider_managed" and binding.provider_seed is not None:
        _blocked(
            "benchmark_provider_seed_unexpected",
            "Provider-managed randomness cannot add a seed.",
        )
    _validate_run_binding(binding, arm)

    if (
        observation.campaign_id != campaign.id
        or observation.run_id != binding.id
        or observation.benchmark_arm_id != arm.benchmark_arm_id
        or observation.algorithm_seed != binding.algorithm_seed
        or observation.simulator_seed_block_id != binding.simulator_seed_block
        or observation.generation_index != job.current_generation + 1
        or observation.next_dispatch_ordinal != job.next_candidate_dispatch_ordinal
    ):
        _blocked(
            "benchmark_observation_binding_drift",
            "Observation differs from run or Job state.",
        )
    source_commit = resolve_source_commit()
    if inventory.engine_pack.source_commit != source_commit:
        _blocked("benchmark_engine_source_drift", "Active Engine Pack differs from inventory.")
    return _BoundDirectContext(
        binding=binding,
        arm=arm,
        campaign=campaign,
        inventory=inventory,
        provider=provider,
        source_commit=source_commit,
    )


def _request_body(
    request: BenchmarkLLMTurnRequestV1,
    config: BenchmarkProviderExecutionConfigV1,
    provider_seed: int | None,
) -> dict[str, Any]:
    schema_name = f"benchmark_{request.adapter_id.replace('/', '_')}_t{request.turn_index}"
    body: dict[str, Any] = {
        "model": config.model_snapshot,
        "messages": [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ],
        "temperature": config.temperature,
        "top_p": config.top_p,
        "max_tokens": config.maximum_output_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": request.response_schema,
            },
        },
    }
    if provider_seed is not None:
        body["seed"] = provider_seed
    return body


def _require_prereserved_budget(
    db: Session,
    context: _BoundDirectContext,
    request_body: dict[str, Any],
) -> None:
    reservation = db.scalar(
        select(models.BenchmarkBudgetReservation).where(
            models.BenchmarkBudgetReservation.campaign_id == context.campaign.id,
            models.BenchmarkBudgetReservation.reservation_key
            == f"provider-run/{context.binding.id}",
        )
    )
    if reservation is None or reservation.reason != BENCHMARK_DIRECT_RESERVATION_REASON:
        _blocked("benchmark_provider_budget_unreserved", "Run provider budget is not reserved.")
    try:
        validate_provider_run_reservation(
            reservation,
            campaign_id=context.campaign.id,
            run_binding_id=context.binding.id,
        )
    except BenchmarkProviderUsageBlocked as exc:
        raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
    request_bytes = len(canonical_json_bytes(request_body))
    if request_bytes > context.provider.maximum_request_utf8_bytes:
        _blocked(
            "benchmark_provider_request_too_large",
            "Serialized provider request exceeds the frozen per-turn byte cap.",
        )
    policy = require_llm_arm_policy(context.arm.proposal_adapter_id)
    required = provider_run_capacity(
        context.provider,
        maximum_turns_per_generation=policy.maximum_turns_per_generation,
    )
    if any(
        int(getattr(reservation, field)) != amount
        for field, amount in required.model_dump().items()
    ):
        _blocked(
            "benchmark_provider_budget_drift",
            "Reserved provider budget differs from the frozen run capacity.",
        )


def _recover_single_turn_proposal_handoff(
    db: Session,
    job: models.Job,
    context: _BoundDirectContext,
    observation: BenchmarkObservationV2,
    request: BenchmarkLLMTurnRequestV1,
    *,
    adapter_id: Literal["llm_direct/v1", "llambo_uav/v1"],
) -> BenchmarkDurableDirectExecutionV1 | BenchmarkDurableLLAMBOExecutionV1 | None:
    """Recover one validated proposal without replaying provider I/O."""

    is_direct = adapter_id == "llm_direct/v1"
    error_namespace = "direct" if is_direct else "llambo"
    handoff_schema = (
        BENCHMARK_DIRECT_PROPOSAL_HANDOFF_SCHEMA_ID
        if is_direct
        else BENCHMARK_LLAMBO_PROPOSAL_HANDOFF_SCHEMA_ID
    )
    receipt_schema = (
        BENCHMARK_DIRECT_PROPOSAL_RECEIPT_SCHEMA_ID
        if is_direct
        else BENCHMARK_LLAMBO_PROPOSAL_RECEIPT_SCHEMA_ID
    )
    candidate_prefix = "llm-direct" if is_direct else "llambo-uav"
    reason_code = "benchmark-llm-direct" if is_direct else "benchmark-llambo-uav"
    result_type = (
        BenchmarkDurableDirectExecutionV1 if is_direct else BenchmarkDurableLLAMBOExecutionV1
    )
    turn = db.scalar(
        select(models.HarnessCognitiveTurnReceipt).where(
            models.HarnessCognitiveTurnReceipt.job_id == job.id,
            models.HarnessCognitiveTurnReceipt.generation_index == observation.generation_index,
            models.HarnessCognitiveTurnReceipt.turn_index == 1,
        )
    )
    if turn is None:
        return None
    handoff: models.BenchmarkDirectProposalHandoff | models.BenchmarkLLAMBOProposalHandoff | None
    if is_direct:
        handoff = db.scalar(
            select(models.BenchmarkDirectProposalHandoff).where(
                models.BenchmarkDirectProposalHandoff.job_id == job.id,
                models.BenchmarkDirectProposalHandoff.generation_index
                == observation.generation_index,
            )
        )
    else:
        handoff = db.scalar(
            select(models.BenchmarkLLAMBOProposalHandoff).where(
                models.BenchmarkLLAMBOProposalHandoff.job_id == job.id,
                models.BenchmarkLLAMBOProposalHandoff.generation_index
                == observation.generation_index,
            )
        )
    if handoff is None:
        # The ordinary begin path preserves the existing pending/consumed
        # classification.  In neither case may provider I/O be replayed.
        return None
    outcome = turn.outcome
    if outcome is None or outcome.status != "succeeded":
        _blocked(
            f"benchmark_{error_namespace}_handoff_outcome_mismatch",
            "Single-turn proposal handoff is not paired with a successful turn.",
        )
    observation_sha256 = canonical_sha256(observation)
    if (
        handoff.handoff_schema != handoff_schema
        or handoff.job_id != job.id
        or handoff.run_binding_id != context.binding.id
        or handoff.cognitive_turn_receipt_id != turn.id
        or handoff.generation_index != observation.generation_index
        or handoff.dispatch_ordinal != observation.next_dispatch_ordinal
        or handoff.source_commit != context.source_commit
        or handoff.observation_sha256 != observation_sha256
        or handoff.turn_binding_sha256 != request.binding_sha256
        or turn.source_commit != context.source_commit
        or turn.model_snapshot != request.model_snapshot
        or turn.prompt_sha256 != request.prompt_sha256
        or turn.evidence_sha256 != request.evidence_sha256
        or turn.schema_sha256 != request.response_schema_sha256
        or turn.tool_outputs_sha256 != request.tool_outputs_sha256
        or canonical_sha256(handoff.parameters_json) != handoff.parameter_sha256
        or canonical_sha256(handoff.proposal_receipt_json) != handoff.proposal_receipt_sha256
        or outcome.response_sha256 != handoff.parameter_sha256
    ):
        _blocked(
            f"benchmark_{error_namespace}_handoff_drift",
            "Recovered single-turn proposal no longer matches its frozen provenance.",
        )
    receipt = handoff.proposal_receipt_json
    expected_candidate_ref = (
        f"{candidate_prefix}-g{observation.generation_index:06d}-"
        f"d{observation.next_dispatch_ordinal:06d}-{handoff.parameter_sha256[:12]}"
    )
    if (
        receipt.get("schema_id") != receipt_schema
        or receipt.get("campaign_id") != context.campaign.id
        or receipt.get("run_binding_id") != context.binding.id
        or receipt.get("arm_manifest_sha256") != context.arm.manifest_sha256
        or receipt.get("composite_inventory_sha256") != context.campaign.composite_inventory_sha256
        or receipt.get("source_commit") != context.source_commit
        or receipt.get("llm_policy_registry_sha256") != BENCHMARK_LLM_ARM_POLICIES_SHA256
        or receipt.get("turn_binding_sha256") != request.binding_sha256
        or receipt.get("observation_sha256") != observation_sha256
        or receipt.get("parameter_sha256") != handoff.parameter_sha256
        or receipt.get("provider_turns_attempted") != 1
        or receipt.get("provider_turns_succeeded") != 1
        or receipt.get("provider_requests_attempted") != 1
        or receipt.get("provider_requests_succeeded") != 1
        or receipt.get("retry_cap") != 0
        or handoff.candidate_ref != expected_candidate_ref
        or handoff.reason_code != reason_code
        or (
            not is_direct
            and receipt.get("adaptation_policy_sha256")
            != canonical_sha256(require_llm_arm_policy("llambo_uav/v1"))
        )
    ):
        _blocked(
            f"benchmark_{error_namespace}_handoff_receipt_drift",
            "Recovered single-turn proposal receipt fields disagree with provenance.",
        )
    usage_sha256 = receipt.get("provider_usage_reconciliation_sha256")
    if (
        not isinstance(usage_sha256, str)
        or len(usage_sha256) != 64
        or any(character not in "0123456789abcdef" for character in usage_sha256)
    ):
        _blocked(
            f"benchmark_{error_namespace}_handoff_receipt_drift",
            "Recovered single-turn proposal receipt lacks a usage reconciliation hash.",
        )
    try:
        parameters = validate_proposal_response(
            {
                "schema_version": "1.0",
                "decision": "propose",
                "parameters": handoff.parameters_json,
            },
            observation,
        )
        proposal = BenchmarkProposalV1(
            candidate_ref=handoff.candidate_ref,
            parameters=parameters,
            reason_code=handoff.reason_code,
            proposal_receipt=handoff.proposal_receipt_json,
        )
    except (BenchmarkLLMContractError, ValueError) as exc:
        raise BenchmarkDurableLLMBlocked(
            f"benchmark_{error_namespace}_handoff_invalid",
            "Recovered single-turn proposal fails the current frozen schema.",
        ) from exc
    request_counts = provider_request_counts_for_turn(
        db,
        cognitive_turn_receipt_id=turn.id,
    )
    if request_counts != (1, 1):
        _blocked(
            f"benchmark_{error_namespace}_handoff_request_mismatch",
            "Recovered single-turn proposal does not bind one successful request.",
        )
    return result_type(
        status="proposal_recovered",
        proposal=proposal,
        provider_turns_attempted=1,
        provider_turns_succeeded=1,
        provider_requests_attempted=1,
        provider_requests_succeeded=1,
        recovered_from_handoff=True,
        safe_receipt=handoff.proposal_receipt_json,
    )


def _execute_durable_single_turn_arm(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    adapter_id: Literal["llm_direct/v1", "llambo_uav/v1"],
    transport: BenchmarkDirectTransport | None = None,
    transport_factory: BenchmarkDirectTransportFactory | None = None,
) -> BenchmarkDurableDirectExecutionV1 | BenchmarkDurableLLAMBOExecutionV1:
    """Execute one frozen single-turn provider arm with durable accounting."""

    is_direct = adapter_id == "llm_direct/v1"
    turn_role: Literal["direct_proposal", "llambo_proposal"] = (
        "direct_proposal" if is_direct else "llambo_proposal"
    )
    error_namespace = "direct" if is_direct else "llambo"
    candidate_prefix = "llm-direct" if is_direct else "llambo-uav"
    reason_code = "benchmark-llm-direct" if is_direct else "benchmark-llambo-uav"
    receipt_schema = (
        BENCHMARK_DIRECT_PROPOSAL_RECEIPT_SCHEMA_ID
        if is_direct
        else BENCHMARK_LLAMBO_PROPOSAL_RECEIPT_SCHEMA_ID
    )
    handoff_schema = (
        BENCHMARK_DIRECT_PROPOSAL_HANDOFF_SCHEMA_ID
        if is_direct
        else BENCHMARK_LLAMBO_PROPOSAL_HANDOFF_SCHEMA_ID
    )
    result_type = (
        BenchmarkDurableDirectExecutionV1 if is_direct else BenchmarkDurableLLAMBOExecutionV1
    )
    context = _load_context(db, job, observation, expected_adapter_id=adapter_id)
    policy = require_llm_arm_policy(adapter_id)
    if job.first_qualified_candidate_id is not None:
        return result_type(
            status="first_qualified_stop",
            proposal=None,
            provider_turns_attempted=0,
            provider_turns_succeeded=0,
            provider_requests_attempted=0,
            provider_requests_succeeded=0,
            safe_receipt={
                "schema_id": "dronedream.benchmark-first-qualified-stop/v1",
                "campaign_id": context.campaign.id,
                "run_binding_id": context.binding.id,
                "source_commit": context.source_commit,
            },
        )
    request = build_llm_turn_request(
        policy=policy,
        observation=observation,
        model_snapshot=context.provider.model_snapshot,
        turn_index=1,
        turn_role=turn_role,
        response_schema=proposal_response_schema(observation),
    )
    body = _request_body(request, context.provider, context.binding.provider_seed)
    _require_prereserved_budget(db, context, body)
    recovered = _recover_single_turn_proposal_handoff(
        db,
        job,
        context,
        observation,
        request,
        adapter_id=adapter_id,
    )
    if recovered is not None:
        return recovered
    if (transport is None) == (transport_factory is None):
        _blocked(
            "benchmark_provider_transport_binding_invalid",
            "Single-turn execution requires exactly one transport binding.",
        )
    if transport is None:
        try:
            transport = transport_factory(context.provider)  # type: ignore[misc]
        except BenchmarkDurableLLMBlocked:
            raise
        except Exception as exc:  # noqa: BLE001 - credential details remain private.
            raise BenchmarkDurableLLMBlocked(
                "benchmark_provider_credential_unavailable",
                "The Job-bound provider credential is unavailable.",
            ) from exc
    request_envelope = BenchmarkProviderRequestEnvelope.from_request_body(body)
    attempt = begin_benchmark_llm_turn(
        db,
        job,
        generation_index=observation.generation_index,
        turn_index=1,
        turn_role=turn_role,
        adapter_id=adapter_id,
        maximum_turns_per_generation=1,
        model_snapshot=request.model_snapshot,
        prompt_sha256=request.prompt_sha256,
        evidence_sha256=request.evidence_sha256,
        schema_sha256=request.response_schema_sha256,
        tool_outputs_sha256=request.tool_outputs_sha256,
    )
    accountant = BoundProviderRequestAccountant(
        db,
        job,
        cognitive_turn_receipt_id=attempt.receipt_id,
        provider=context.provider.provider,
        region=context.provider.region,
    )
    network_attempt = accountant.begin(
        request_kind="primary",
        model_snapshot=request.model_snapshot,
        api_surface=context.provider.api_surface,
        base_url=context.provider.base_url,
        temperature=context.provider.temperature,
        top_p=context.provider.top_p,
        provider_seed=context.binding.provider_seed,
        response_schema_sha256=request.response_schema_sha256,
        prompt_sha256=request.prompt_sha256,
        request_body=body,
        price_snapshot=context.provider.price_snapshot,
    )
    started = time.monotonic()
    try:
        result = transport.complete(request_envelope, context.provider)
    except Exception as exc:  # noqa: BLE001 - transport details must not enter evidence.
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        accountant.fail(
            network_attempt,
            latency_ms=latency_ms,
            error_code="benchmark_provider_transport_failed",
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_provider_transport_failed",
        )
        raise BenchmarkDurableLLMBlocked(
            "benchmark_provider_transport_failed",
            "Provider transport failed; this attempted turn cannot be replayed.",
        ) from exc
    if (
        not isinstance(result, BenchmarkProviderTransportResult)
        or not isinstance(result.response_text, str)
        or isinstance(result.latency_ms, bool)
        or not isinstance(result.latency_ms, int)
        or result.latency_ms < 0
    ):
        accountant.fail(
            network_attempt,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            error_code="benchmark_transport_result_invalid",
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_transport_result_invalid",
        )
        _blocked("benchmark_transport_result_invalid", "Transport returned an invalid result.")
    if not _usage_is_complete(result.usage):
        accountant.succeed(
            network_attempt,
            response_content=result.response_text,
            usage=ProviderUsage(),
            latency_ms=result.latency_ms,
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_provider_usage_incomplete",
        )
        _blocked(
            "benchmark_provider_usage_incomplete",
            "Provider response omitted complete token usage required by the formal contract.",
        )
    accountant.succeed(
        network_attempt,
        response_content=result.response_text,
        usage=result.usage,
        latency_ms=result.latency_ms,
    )
    if len(result.response_text.encode("utf-8")) > context.provider.maximum_response_utf8_bytes:
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            error_code="benchmark_provider_response_too_large",
        )
        _blocked(
            "benchmark_provider_response_too_large",
            "Provider response exceeds the frozen per-turn byte cap.",
        )
    terminal_status = cancel_cognitive_turn_if_job_terminal(db, job, attempt)
    if terminal_status is not None:
        _blocked(
            "benchmark_job_terminal_during_provider",
            "Job became terminal during provider I/O.",
        )
    try:
        raw = parse_bounded_json_response(result.response_text)
        parameters = validate_proposal_response(raw, observation)
    except BenchmarkLLMContractError as exc:
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            error_code=f"benchmark_{error_namespace}_response_invalid",
        )
        raise BenchmarkDurableLLMBlocked(
            f"benchmark_{error_namespace}_response_invalid",
            "Provider response failed the frozen single-turn proposal schema.",
        ) from exc
    request_counts = provider_request_counts_for_turn(
        db,
        cognitive_turn_receipt_id=attempt.receipt_id,
    )
    status = finish_cognitive_turn(
        db,
        job,
        attempt,
        status="succeeded",
        response=parameters,
        commit=False,
    )
    if status != "succeeded":
        db.commit()
        db.refresh(job)
        _blocked("benchmark_source_drift", "Source changed before cognitive finalization.")
    try:
        usage_reconciliation = reconcile_provider_run_usage(db, context.binding.id)
    except BenchmarkProviderUsageBlocked as exc:
        db.rollback()
        db.refresh(job)
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code=exc.code,
        )
        raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
    if usage_reconciliation.status != "complete":
        db.rollback()
        db.refresh(job)
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_provider_usage_incomplete",
        )
        _blocked(
            "benchmark_provider_usage_incomplete",
            "Provider usage cannot be reconciled completely against the reservation.",
        )
    parameter_sha256 = canonical_sha256(parameters)
    observation_sha256 = canonical_sha256(observation)
    safe_receipt = {
        "schema_id": receipt_schema,
        "campaign_id": context.campaign.id,
        "run_binding_id": context.binding.id,
        "arm_manifest_sha256": context.arm.manifest_sha256,
        "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
        "source_commit": context.source_commit,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "turn_binding_sha256": request.binding_sha256,
        "observation_sha256": observation_sha256,
        "parameter_sha256": parameter_sha256,
        "provider_turns_attempted": 1,
        "provider_turns_succeeded": 1,
        "provider_requests_attempted": request_counts[0],
        "provider_requests_succeeded": request_counts[1],
        "provider_usage_reconciliation_sha256": canonical_sha256(usage_reconciliation),
        "retry_cap": 0,
    }
    if not is_direct:
        safe_receipt["adaptation_policy_sha256"] = canonical_sha256(policy)
    candidate_ref = (
        f"{candidate_prefix}-g{observation.generation_index:06d}-"
        f"d{observation.next_dispatch_ordinal:06d}-{parameter_sha256[:12]}"
    )
    proposal = BenchmarkProposalV1(
        candidate_ref=candidate_ref,
        parameters=parameters,
        reason_code=reason_code,
        proposal_receipt=safe_receipt,
    )
    handoff_type = (
        models.BenchmarkDirectProposalHandoff
        if is_direct
        else models.BenchmarkLLAMBOProposalHandoff
    )
    db.add(
        handoff_type(
            job_id=job.id,
            run_binding_id=context.binding.id,
            cognitive_turn_receipt_id=attempt.receipt_id,
            handoff_schema=handoff_schema,
            generation_index=observation.generation_index,
            dispatch_ordinal=observation.next_dispatch_ordinal,
            source_commit=context.source_commit,
            observation_sha256=observation_sha256,
            turn_binding_sha256=request.binding_sha256,
            candidate_ref=candidate_ref,
            reason_code=reason_code,
            parameters_json=parameters,
            parameter_sha256=parameter_sha256,
            proposal_receipt_json=safe_receipt,
            proposal_receipt_sha256=canonical_sha256(safe_receipt),
        )
    )
    db.commit()
    db.refresh(job)
    return result_type(
        status="proposal",
        proposal=proposal,
        provider_turns_attempted=1,
        provider_turns_succeeded=1,
        provider_requests_attempted=request_counts[0],
        provider_requests_succeeded=request_counts[1],
        safe_receipt=safe_receipt,
    )


def execute_durable_direct_arm(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    transport: BenchmarkDirectTransport | None = None,
    transport_factory: BenchmarkDirectTransportFactory | None = None,
) -> BenchmarkDurableDirectExecutionV1:
    """Execute the preregistered one-turn direct proposal arm."""

    result = _execute_durable_single_turn_arm(
        db,
        job,
        observation,
        adapter_id="llm_direct/v1",
        transport=transport,
        transport_factory=transport_factory,
    )
    if not isinstance(result, BenchmarkDurableDirectExecutionV1):  # pragma: no cover
        raise RuntimeError("direct runtime returned the wrong result contract")
    return result


def execute_durable_llambo_arm(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    transport: BenchmarkDirectTransport | None = None,
    transport_factory: BenchmarkDirectTransportFactory | None = None,
) -> BenchmarkDurableLLAMBOExecutionV1:
    """Execute the one-turn noisy constrained UAV LLAMBO adaptation."""

    result = _execute_durable_single_turn_arm(
        db,
        job,
        observation,
        adapter_id="llambo_uav/v1",
        transport=transport,
        transport_factory=transport_factory,
    )
    if not isinstance(result, BenchmarkDurableLLAMBOExecutionV1):  # pragma: no cover
        raise RuntimeError("LLAMBO runtime returned the wrong result contract")
    return result


def _safe_react_proposal_record(proposal: BenchmarkProposalV1) -> dict[str, Any]:
    return proposal.model_dump(mode="json")


def _react_proposals_from_state(value: object) -> list[BenchmarkProposalV1]:
    if not isinstance(value, list):
        _blocked("benchmark_react_checkpoint_invalid", "ReAct proposal state is not a list.")
    try:
        proposals = [BenchmarkProposalV1.model_validate(item) for item in value]
    except ValueError as exc:
        raise BenchmarkDurableLLMBlocked(
            "benchmark_react_checkpoint_invalid",
            "ReAct proposal state fails the frozen proposal schema.",
        ) from exc
    refs = [proposal.candidate_ref for proposal in proposals]
    if len(refs) != len(set(refs)):
        _blocked("benchmark_react_checkpoint_invalid", "ReAct proposal references are duplicated.")
    return proposals


def _run_react_local_tools(
    tool_adapter_ids: Sequence[str],
    observation: BenchmarkObservationV2,
    *,
    already_used: set[str],
) -> list[BenchmarkProposalV1]:
    proposals: list[BenchmarkProposalV1] = []
    for adapter_id in tool_adapter_ids:
        if adapter_id in already_used:
            raise BenchmarkAdapterError("bounded ReAct repeated a local tool in one generation")
        already_used.add(adapter_id)
        proposals.append(create_benchmark_adapter(adapter_id).propose(observation))
    return proposals


def _proposal_by_ref(
    proposals: Sequence[BenchmarkProposalV1], proposal_ref: str
) -> BenchmarkProposalV1:
    for proposal in proposals:
        if proposal.candidate_ref == proposal_ref:
            return proposal
    raise BenchmarkLLMContractError("selected ReAct proposal reference is absent")


def _react_terminal_receipt(
    *,
    context: _BoundDirectContext,
    observation: BenchmarkObservationV2,
    selected: BenchmarkProposalV1 | None,
    turn_bindings: Sequence[str],
    usage_reconciliation_sha256: str,
) -> tuple[BenchmarkProposalV1 | None, dict[str, Any]]:
    observation_sha256 = canonical_sha256(observation)
    common = {
        "campaign_id": context.campaign.id,
        "run_binding_id": context.binding.id,
        "arm_manifest_sha256": context.arm.manifest_sha256,
        "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
        "source_commit": context.source_commit,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "observation_sha256": observation_sha256,
        "turn_binding_sha256": list(turn_bindings),
        "provider_turns_attempted": len(turn_bindings),
        "provider_turns_succeeded": len(turn_bindings),
        "provider_requests_attempted": len(turn_bindings),
        "provider_requests_succeeded": len(turn_bindings),
        "provider_usage_reconciliation_sha256": usage_reconciliation_sha256,
        "retry_cap": 0,
    }
    if selected is None:
        return None, {
            "schema_id": "dronedream.benchmark-llm-react-abandon/v1",
            **common,
        }
    parameter_sha256 = canonical_sha256(selected.parameters)
    safe_receipt = {
        "schema_id": BENCHMARK_REACT_PROPOSAL_RECEIPT_SCHEMA_ID,
        **common,
        "selected_local_proposal_ref": selected.candidate_ref,
        "selected_local_proposal_receipt_sha256": canonical_sha256(selected.proposal_receipt),
        "parameter_sha256": parameter_sha256,
    }
    candidate_ref = (
        f"llm-react-g{observation.generation_index:06d}-"
        f"d{observation.next_dispatch_ordinal:06d}-{parameter_sha256[:12]}"
    )
    return (
        BenchmarkProposalV1(
            candidate_ref=candidate_ref,
            parameters=dict(selected.parameters),
            reason_code="benchmark-llm-react",
            proposal_receipt=safe_receipt,
        ),
        safe_receipt,
    )


def _call_durable_provider_turn(
    db: Session,
    job: models.Job,
    context: _BoundDirectContext,
    request: BenchmarkLLMTurnRequestV1,
    body: dict[str, Any],
    transport: BenchmarkDirectTransport,
    *,
    adapter_id: Literal["llm_react/v1", "dronedream_fixed_two_turn/v1"],
    turn_role: Literal["react_action", "plan", "revision"],
    maximum_turns_per_generation: int,
    error_namespace: str,
) -> tuple[object, CognitiveTurnAttempt]:
    attempt = begin_benchmark_llm_turn(
        db,
        job,
        generation_index=request.generation_index,
        turn_index=request.turn_index,
        turn_role=turn_role,
        adapter_id=adapter_id,
        maximum_turns_per_generation=maximum_turns_per_generation,
        model_snapshot=request.model_snapshot,
        prompt_sha256=request.prompt_sha256,
        evidence_sha256=request.evidence_sha256,
        schema_sha256=request.response_schema_sha256,
        tool_outputs_sha256=request.tool_outputs_sha256,
    )
    accountant = BoundProviderRequestAccountant(
        db,
        job,
        cognitive_turn_receipt_id=attempt.receipt_id,
        provider=context.provider.provider,
        region=context.provider.region,
    )
    network_attempt = accountant.begin(
        request_kind="primary",
        model_snapshot=request.model_snapshot,
        api_surface=context.provider.api_surface,
        base_url=context.provider.base_url,
        temperature=context.provider.temperature,
        top_p=context.provider.top_p,
        provider_seed=context.binding.provider_seed,
        response_schema_sha256=request.response_schema_sha256,
        prompt_sha256=request.prompt_sha256,
        request_body=body,
        price_snapshot=context.provider.price_snapshot,
    )
    started = time.monotonic()
    try:
        result = transport.complete(
            BenchmarkProviderRequestEnvelope.from_request_body(body),
            context.provider,
        )
    except Exception as exc:  # noqa: BLE001 - provider details remain private.
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        accountant.fail(
            network_attempt,
            latency_ms=latency_ms,
            error_code="benchmark_provider_transport_failed",
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_provider_transport_failed",
        )
        raise BenchmarkDurableLLMBlocked(
            "benchmark_provider_transport_failed",
            f"Provider transport failed; this attempted {error_namespace} turn cannot be replayed.",
        ) from exc
    if (
        not isinstance(result, BenchmarkProviderTransportResult)
        or not isinstance(result.response_text, str)
        or isinstance(result.latency_ms, bool)
        or not isinstance(result.latency_ms, int)
        or result.latency_ms < 0
    ):
        accountant.fail(
            network_attempt,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            error_code="benchmark_transport_result_invalid",
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_transport_result_invalid",
        )
        _blocked("benchmark_transport_result_invalid", "Transport returned an invalid result.")
    if not _usage_is_complete(result.usage):
        accountant.succeed(
            network_attempt,
            response_content=result.response_text,
            usage=ProviderUsage(),
            latency_ms=result.latency_ms,
        )
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="provider_failed",
            error_code="benchmark_provider_usage_incomplete",
        )
        _blocked(
            "benchmark_provider_usage_incomplete",
            "Provider response omitted complete token usage required by the formal contract.",
        )
    accountant.succeed(
        network_attempt,
        response_content=result.response_text,
        usage=result.usage,
        latency_ms=result.latency_ms,
    )
    if len(result.response_text.encode("utf-8")) > context.provider.maximum_response_utf8_bytes:
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            error_code="benchmark_provider_response_too_large",
        )
        _blocked(
            "benchmark_provider_response_too_large",
            "Provider response exceeds the frozen per-turn byte cap.",
        )
    terminal_status = cancel_cognitive_turn_if_job_terminal(db, job, attempt)
    if terminal_status is not None:
        _blocked(
            "benchmark_job_terminal_during_provider",
            "Job became terminal during provider I/O.",
        )
    try:
        raw = parse_bounded_json_response(result.response_text)
    except BenchmarkLLMContractError as exc:
        finish_cognitive_turn(
            db,
            job,
            attempt,
            status="invalid_schema",
            error_code=f"benchmark_{error_namespace}_response_invalid",
        )
        raise BenchmarkDurableLLMBlocked(
            f"benchmark_{error_namespace}_response_invalid",
            f"Provider response failed the bounded {error_namespace} JSON contract.",
        ) from exc
    return raw, attempt


def _recover_react_checkpoint(
    db: Session,
    job: models.Job,
    context: _BoundDirectContext,
    observation: BenchmarkObservationV2,
    request: BenchmarkLLMTurnRequestV1,
    *,
    proposals_before: Sequence[BenchmarkProposalV1],
    used_tools_before: Sequence[str],
    prior_state_sha256: str | None,
    turn_bindings: Sequence[str],
    allow_action: bool,
) -> (
    tuple[
        Literal["act", "dispatch", "abandon"],
        list[BenchmarkProposalV1],
        list[str],
        BenchmarkProposalV1 | None,
        dict[str, Any],
        str,
    ]
    | None
):
    checkpoint = db.scalar(
        select(models.BenchmarkLLMReactCheckpoint).where(
            models.BenchmarkLLMReactCheckpoint.job_id == job.id,
            models.BenchmarkLLMReactCheckpoint.generation_index == observation.generation_index,
            models.BenchmarkLLMReactCheckpoint.turn_index == request.turn_index,
        )
    )
    if checkpoint is None:
        return None
    turn = db.get(models.HarnessCognitiveTurnReceipt, checkpoint.cognitive_turn_receipt_id)
    state = checkpoint.state_json
    observation_sha256 = canonical_sha256(observation)
    if (
        turn is None
        or turn.outcome is None
        or turn.outcome.status != "succeeded"
        or checkpoint.checkpoint_schema != BENCHMARK_REACT_CHECKPOINT_SCHEMA_ID
        or checkpoint.adapter_id != "llm_react/v1"
        or checkpoint.job_id != job.id
        or checkpoint.run_binding_id != context.binding.id
        or checkpoint.generation_index != observation.generation_index
        or checkpoint.turn_index != request.turn_index
        or checkpoint.source_commit != context.source_commit
        or checkpoint.observation_sha256 != observation_sha256
        or checkpoint.turn_binding_sha256 != request.binding_sha256
        or canonical_sha256(state) != checkpoint.state_sha256
        or turn.source_commit != context.source_commit
        or turn.turn_role != "react_action"
        or turn.model_snapshot != request.model_snapshot
        or turn.prompt_sha256 != request.prompt_sha256
        or turn.evidence_sha256 != request.evidence_sha256
        or turn.schema_sha256 != request.response_schema_sha256
        or turn.tool_outputs_sha256 != request.tool_outputs_sha256
    ):
        _blocked("benchmark_react_checkpoint_drift", "Recovered ReAct checkpoint drifted.")
    if (
        not isinstance(state, dict)
        or state.get("schema_id") != BENCHMARK_REACT_CHECKPOINT_SCHEMA_ID
    ):
        _blocked("benchmark_react_checkpoint_invalid", "Recovered ReAct state is invalid.")
    if set(state) != {
        "schema_id",
        "campaign_id",
        "run_binding_id",
        "arm_manifest_sha256",
        "composite_inventory_sha256",
        "source_commit",
        "llm_policy_registry_sha256",
        "observation_sha256",
        "generation_index",
        "turn_index",
        "turn_binding_sha256",
        "prior_state_sha256",
        "decision",
        "validated_response",
        "used_tool_adapter_ids",
        "proposals",
        "selected_proposal_ref",
        "final_proposal",
        "terminal_receipt",
    }:
        _blocked("benchmark_react_checkpoint_invalid", "Recovered ReAct state is not closed.")
    expected_base = {
        "campaign_id": context.campaign.id,
        "run_binding_id": context.binding.id,
        "arm_manifest_sha256": context.arm.manifest_sha256,
        "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
        "source_commit": context.source_commit,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "observation_sha256": observation_sha256,
        "generation_index": observation.generation_index,
        "turn_index": request.turn_index,
        "turn_binding_sha256": request.binding_sha256,
        "prior_state_sha256": prior_state_sha256,
    }
    if any(state.get(key) != value for key, value in expected_base.items()):
        _blocked("benchmark_react_checkpoint_drift", "Recovered ReAct context fields drifted.")
    validated_response = state.get("validated_response")
    try:
        decision, tools, selected_ref = validate_react_response(
            validated_response,
            require_llm_arm_policy("llm_react/v1"),
            tuple(proposal.candidate_ref for proposal in proposals_before),
            allow_action=allow_action,
        )
    except BenchmarkLLMContractError as exc:
        raise BenchmarkDurableLLMBlocked(
            "benchmark_react_checkpoint_invalid",
            "Recovered ReAct decision fails the current schema.",
        ) from exc
    if not isinstance(validated_response, (dict, list)):
        _blocked("benchmark_react_checkpoint_drift", "Recovered ReAct response is malformed.")
    if turn.outcome.response_sha256 != canonical_sha256(validated_response):
        _blocked("benchmark_react_checkpoint_drift", "Recovered ReAct response hash drifted.")
    proposals_after = list(proposals_before)
    used_after = list(used_tools_before)
    if decision == "act":
        try:
            proposals_after.extend(
                _run_react_local_tools(
                    tools,
                    observation,
                    already_used=set(used_after),
                )
            )
        except BenchmarkAdapterError as exc:
            raise BenchmarkDurableLLMBlocked(
                "benchmark_react_checkpoint_invalid",
                "Recovered ReAct tool state cannot be reproduced.",
            ) from exc
        used_after.extend(tools)
    stored_proposals = _react_proposals_from_state(state.get("proposals"))
    if (
        [_safe_react_proposal_record(item) for item in proposals_after]
        != [_safe_react_proposal_record(item) for item in stored_proposals]
        or state.get("used_tool_adapter_ids") != used_after
        or state.get("decision") != decision
        or checkpoint.decision != decision
        or state.get("selected_proposal_ref") != selected_ref
        or provider_request_counts_for_turn(
            db,
            cognitive_turn_receipt_id=turn.id,
        )
        != (1, 1)
    ):
        _blocked("benchmark_react_checkpoint_drift", "Recovered ReAct state is inconsistent.")
    proposal: BenchmarkProposalV1 | None = None
    safe_receipt: dict[str, Any] = {}
    if decision == "act":
        if state.get("terminal_receipt") != {} or state.get("final_proposal") is not None:
            _blocked("benchmark_react_checkpoint_drift", "Nonterminal ReAct state drifted.")
    else:
        try:
            usage = reconcile_provider_run_usage(db, context.binding.id)
        except BenchmarkProviderUsageBlocked as exc:
            raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
        if usage.status != "complete":
            _blocked(
                "benchmark_provider_usage_incomplete",
                "Recovered ReAct usage cannot be reconciled completely.",
            )
        selected = (
            _proposal_by_ref(stored_proposals, selected_ref)
            if decision == "dispatch" and selected_ref is not None
            else None
        )
        expected_proposal, expected_receipt = _react_terminal_receipt(
            context=context,
            observation=observation,
            selected=selected,
            turn_bindings=turn_bindings,
            usage_reconciliation_sha256=canonical_sha256(usage),
        )
        if state.get("terminal_receipt") != expected_receipt or state.get("final_proposal") != (
            None if expected_proposal is None else expected_proposal.model_dump(mode="json")
        ):
            _blocked("benchmark_react_checkpoint_drift", "Recovered terminal state drifted.")
        proposal = expected_proposal
        safe_receipt = expected_receipt
    return (
        decision,
        stored_proposals,
        used_after,
        proposal,
        safe_receipt,
        checkpoint.state_sha256,
    )


def execute_durable_react_arm(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    transport: BenchmarkDirectTransport | None = None,
    transport_factory: BenchmarkDirectTransportFactory | None = None,
) -> BenchmarkDurableReactExecutionV1:
    """Execute or recover one preregistered bounded ReAct generation."""

    context = _load_context(
        db,
        job,
        observation,
        expected_adapter_id="llm_react/v1",
    )
    policy = require_llm_arm_policy("llm_react/v1")
    if job.first_qualified_candidate_id is not None:
        return BenchmarkDurableReactExecutionV1(
            status="first_qualified_stop",
            proposal=None,
            provider_turns_attempted=0,
            provider_turns_succeeded=0,
            provider_requests_attempted=0,
            provider_requests_succeeded=0,
            safe_receipt={
                "schema_id": "dronedream.benchmark-first-qualified-stop/v1",
                "campaign_id": context.campaign.id,
                "run_binding_id": context.binding.id,
                "source_commit": context.source_commit,
            },
        )
    if (transport is None) == (transport_factory is None):
        _blocked(
            "benchmark_provider_transport_binding_invalid",
            "ReAct execution requires exactly one transport binding.",
        )
    proposals: list[BenchmarkProposalV1] = []
    used_tools: list[str] = []
    prior_state_sha256: str | None = None
    turn_bindings: list[str] = []
    any_recovered = False
    for turn_index in range(1, policy.maximum_turns_per_generation + 1):
        allow_action = turn_index < policy.maximum_turns_per_generation
        response_schema = react_response_schema(
            policy,
            tuple(proposal.candidate_ref for proposal in proposals),
            allow_action=allow_action,
        )
        request = build_llm_turn_request(
            policy=policy,
            observation=observation,
            model_snapshot=context.provider.model_snapshot,
            turn_index=turn_index,
            turn_role="react_action",
            response_schema=response_schema,
            tool_outputs=[
                {
                    "proposal_ref": proposal.candidate_ref,
                    "parameters": dict(proposal.parameters),
                    "proposal_reason_code": proposal.reason_code,
                    "proposal_receipt_sha256": canonical_sha256(proposal.proposal_receipt),
                }
                for proposal in proposals
            ],
        )
        turn_bindings.append(request.binding_sha256)
        recovered = _recover_react_checkpoint(
            db,
            job,
            context,
            observation,
            request,
            proposals_before=proposals,
            used_tools_before=used_tools,
            prior_state_sha256=prior_state_sha256,
            turn_bindings=turn_bindings,
            allow_action=allow_action,
        )
        if recovered is not None:
            any_recovered = True
            (
                decision,
                proposals,
                used_tools,
                recovered_proposal,
                safe_receipt,
                prior_state_sha256,
            ) = recovered
            if decision == "act":
                continue
            attempted = turn_index
            return BenchmarkDurableReactExecutionV1(
                status=("proposal_recovered" if decision == "dispatch" else "abandoned_recovered"),
                proposal=recovered_proposal,
                provider_turns_attempted=attempted,
                provider_turns_succeeded=attempted,
                provider_requests_attempted=attempted,
                provider_requests_succeeded=attempted,
                recovered_from_checkpoint=True,
                safe_receipt=safe_receipt,
            )
        body = _request_body(request, context.provider, context.binding.provider_seed)
        _require_prereserved_budget(db, context, body)
        if transport is None:
            try:
                transport = transport_factory(context.provider)  # type: ignore[misc]
            except BenchmarkDurableLLMBlocked:
                raise
            except Exception as exc:  # noqa: BLE001 - credentials remain private.
                raise BenchmarkDurableLLMBlocked(
                    "benchmark_provider_credential_unavailable",
                    "The Job-bound provider credential is unavailable.",
                ) from exc
        raw, attempt = _call_durable_provider_turn(
            db,
            job,
            context,
            request,
            body,
            transport,
            adapter_id="llm_react/v1",
            turn_role="react_action",
            maximum_turns_per_generation=policy.maximum_turns_per_generation,
            error_namespace="react",
        )
        proposal_refs = tuple(proposal.candidate_ref for proposal in proposals)
        try:
            decision, tools, selected_ref = validate_react_response(
                raw,
                policy,
                proposal_refs,
                allow_action=allow_action,
            )
            if decision == "act":
                new_proposals = _run_react_local_tools(
                    tools,
                    observation,
                    already_used=set(used_tools),
                )
                proposals.extend(new_proposals)
                used_tools.extend(tools)
        except (BenchmarkAdapterError, BenchmarkLLMContractError) as exc:
            finish_cognitive_turn(
                db,
                job,
                attempt,
                status="invalid_schema",
                error_code="benchmark_react_state_rejected",
            )
            raise BenchmarkDurableLLMBlocked(
                "benchmark_react_state_rejected",
                "Provider ReAct decision or local-tool state failed closed.",
            ) from exc
        validated_response = {
            "schema_version": "1.0",
            "decision": decision,
            "tool_adapter_ids": list(tools),
            "selected_proposal_ref": selected_ref,
        }
        status = finish_cognitive_turn(
            db,
            job,
            attempt,
            status="succeeded",
            response=validated_response,
            commit=False,
        )
        if status != "succeeded":
            db.commit()
            db.refresh(job)
            _blocked("benchmark_source_drift", "Source changed before ReAct finalization.")
        proposal: BenchmarkProposalV1 | None = None
        terminal_receipt: dict[str, Any] = {}
        if decision in {"dispatch", "abandon"}:
            try:
                usage = reconcile_provider_run_usage(db, context.binding.id)
            except BenchmarkProviderUsageBlocked as exc:
                db.rollback()
                db.refresh(job)
                finish_cognitive_turn(
                    db,
                    job,
                    attempt,
                    status="provider_failed",
                    error_code=exc.code,
                )
                raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
            if usage.status != "complete":
                db.rollback()
                db.refresh(job)
                finish_cognitive_turn(
                    db,
                    job,
                    attempt,
                    status="provider_failed",
                    error_code="benchmark_provider_usage_incomplete",
                )
                _blocked(
                    "benchmark_provider_usage_incomplete",
                    "Provider usage cannot be reconciled against the frozen reservation.",
                )
            selected = (
                _proposal_by_ref(proposals, selected_ref)
                if decision == "dispatch" and selected_ref is not None
                else None
            )
            proposal, terminal_receipt = _react_terminal_receipt(
                context=context,
                observation=observation,
                selected=selected,
                turn_bindings=turn_bindings,
                usage_reconciliation_sha256=canonical_sha256(usage),
            )
        state = {
            "schema_id": BENCHMARK_REACT_CHECKPOINT_SCHEMA_ID,
            "campaign_id": context.campaign.id,
            "run_binding_id": context.binding.id,
            "arm_manifest_sha256": context.arm.manifest_sha256,
            "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
            "source_commit": context.source_commit,
            "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
            "observation_sha256": canonical_sha256(observation),
            "generation_index": observation.generation_index,
            "turn_index": turn_index,
            "turn_binding_sha256": request.binding_sha256,
            "prior_state_sha256": prior_state_sha256,
            "decision": decision,
            "validated_response": validated_response,
            "used_tool_adapter_ids": list(used_tools),
            "proposals": [_safe_react_proposal_record(item) for item in proposals],
            "selected_proposal_ref": selected_ref,
            "final_proposal": None if proposal is None else proposal.model_dump(mode="json"),
            "terminal_receipt": terminal_receipt,
        }
        state_sha256 = canonical_sha256(state)
        db.add(
            models.BenchmarkLLMReactCheckpoint(
                job_id=job.id,
                run_binding_id=context.binding.id,
                cognitive_turn_receipt_id=attempt.receipt_id,
                checkpoint_schema=BENCHMARK_REACT_CHECKPOINT_SCHEMA_ID,
                adapter_id="llm_react/v1",
                generation_index=observation.generation_index,
                turn_index=turn_index,
                source_commit=context.source_commit,
                observation_sha256=canonical_sha256(observation),
                turn_binding_sha256=request.binding_sha256,
                decision=decision,
                state_json=state,
                state_sha256=state_sha256,
            )
        )
        db.commit()
        db.refresh(job)
        prior_state_sha256 = state_sha256
        if decision == "act":
            continue
        attempted = turn_index
        return BenchmarkDurableReactExecutionV1(
            status=(
                "proposal_recovered"
                if decision == "dispatch" and any_recovered
                else "abandoned_recovered"
                if decision == "abandon" and any_recovered
                else "proposal"
                if decision == "dispatch"
                else "abandoned"
            ),
            proposal=proposal,
            provider_turns_attempted=attempted,
            provider_turns_succeeded=attempted,
            provider_requests_attempted=attempted,
            provider_requests_succeeded=attempted,
            recovered_from_checkpoint=any_recovered,
            safe_receipt=terminal_receipt,
        )
    _blocked("benchmark_react_turn_cap_exhausted", "Bounded ReAct exhausted its turn cap.")


def _fixed_terminal_receipt(
    *,
    context: _BoundDirectContext,
    observation: BenchmarkObservationV2,
    selected: BenchmarkProposalV1 | None,
    turn_bindings: Sequence[str],
    usage_reconciliation_sha256: str,
) -> tuple[BenchmarkProposalV1 | None, dict[str, Any]]:
    observation_sha256 = canonical_sha256(observation)
    common = {
        "campaign_id": context.campaign.id,
        "run_binding_id": context.binding.id,
        "arm_manifest_sha256": context.arm.manifest_sha256,
        "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
        "source_commit": context.source_commit,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "observation_sha256": observation_sha256,
        "turn_binding_sha256": list(turn_bindings),
        "provider_turns_attempted": 2,
        "provider_turns_succeeded": 2,
        "provider_requests_attempted": 2,
        "provider_requests_succeeded": 2,
        "provider_usage_reconciliation_sha256": usage_reconciliation_sha256,
        "retry_cap": 0,
    }
    if selected is None:
        return None, {
            "schema_id": "dronedream.benchmark-fixed-two-turn-abandon/v1",
            **common,
        }
    parameter_sha256 = canonical_sha256(selected.parameters)
    safe_receipt = {
        "schema_id": BENCHMARK_FIXED_TWO_TURN_PROPOSAL_RECEIPT_SCHEMA_ID,
        **common,
        "selected_local_proposal_ref": selected.candidate_ref,
        "selected_local_proposal_receipt_sha256": canonical_sha256(selected.proposal_receipt),
        "parameter_sha256": parameter_sha256,
    }
    candidate_ref = (
        f"dronedream-fixed-two-turn-g{observation.generation_index:06d}-"
        f"d{observation.next_dispatch_ordinal:06d}-{parameter_sha256[:12]}"
    )
    return (
        BenchmarkProposalV1(
            candidate_ref=candidate_ref,
            parameters=dict(selected.parameters),
            reason_code="benchmark-dronedream-fixed-two-turn",
            proposal_receipt=safe_receipt,
        ),
        safe_receipt,
    )


def _recover_fixed_checkpoint(
    db: Session,
    job: models.Job,
    context: _BoundDirectContext,
    observation: BenchmarkObservationV2,
    request: BenchmarkLLMTurnRequestV1,
    *,
    proposals_before: Sequence[BenchmarkProposalV1],
    used_tools_before: Sequence[str],
    prior_state_sha256: str | None,
    turn_bindings: Sequence[str],
) -> (
    tuple[
        Literal["act", "dispatch", "abandon"],
        list[BenchmarkProposalV1],
        list[str],
        BenchmarkProposalV1 | None,
        dict[str, Any],
        str,
    ]
    | None
):
    checkpoint = db.scalar(
        select(models.BenchmarkLLMPlanRevisionCheckpoint).where(
            models.BenchmarkLLMPlanRevisionCheckpoint.job_id == job.id,
            models.BenchmarkLLMPlanRevisionCheckpoint.generation_index
            == observation.generation_index,
            models.BenchmarkLLMPlanRevisionCheckpoint.turn_index == request.turn_index,
        )
    )
    if checkpoint is None:
        return None
    turn = db.get(models.HarnessCognitiveTurnReceipt, checkpoint.cognitive_turn_receipt_id)
    state = checkpoint.state_json
    expected_role = "plan" if request.turn_index == 1 else "revision"
    observation_sha256 = canonical_sha256(observation)
    if (
        turn is None
        or turn.outcome is None
        or turn.outcome.status != "succeeded"
        or checkpoint.checkpoint_schema != BENCHMARK_PLAN_REVISION_CHECKPOINT_SCHEMA_ID
        or checkpoint.adapter_id != "dronedream_fixed_two_turn/v1"
        or checkpoint.job_id != job.id
        or checkpoint.run_binding_id != context.binding.id
        or checkpoint.generation_index != observation.generation_index
        or checkpoint.turn_index != request.turn_index
        or checkpoint.turn_role != expected_role
        or checkpoint.source_commit != context.source_commit
        or checkpoint.observation_sha256 != observation_sha256
        or checkpoint.turn_binding_sha256 != request.binding_sha256
        or canonical_sha256(state) != checkpoint.state_sha256
        or turn.source_commit != context.source_commit
        or turn.turn_role != expected_role
        or turn.model_snapshot != request.model_snapshot
        or turn.prompt_sha256 != request.prompt_sha256
        or turn.evidence_sha256 != request.evidence_sha256
        or turn.schema_sha256 != request.response_schema_sha256
        or turn.tool_outputs_sha256 != request.tool_outputs_sha256
    ):
        _blocked("benchmark_fixed_checkpoint_drift", "Recovered fixed-turn checkpoint drifted.")
    if (
        not isinstance(state, dict)
        or state.get("schema_id") != BENCHMARK_PLAN_REVISION_CHECKPOINT_SCHEMA_ID
    ):
        _blocked("benchmark_fixed_checkpoint_invalid", "Recovered fixed-turn state is invalid.")
    if set(state) != {
        "schema_id",
        "campaign_id",
        "run_binding_id",
        "arm_manifest_sha256",
        "composite_inventory_sha256",
        "source_commit",
        "llm_policy_registry_sha256",
        "observation_sha256",
        "generation_index",
        "turn_index",
        "turn_role",
        "turn_binding_sha256",
        "prior_state_sha256",
        "decision",
        "validated_response",
        "used_tool_adapter_ids",
        "proposals",
        "selected_proposal_ref",
        "final_proposal",
        "terminal_receipt",
    }:
        _blocked("benchmark_fixed_checkpoint_invalid", "Recovered fixed-turn state is not closed.")
    expected_base = {
        "campaign_id": context.campaign.id,
        "run_binding_id": context.binding.id,
        "arm_manifest_sha256": context.arm.manifest_sha256,
        "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
        "source_commit": context.source_commit,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "observation_sha256": observation_sha256,
        "generation_index": observation.generation_index,
        "turn_index": request.turn_index,
        "turn_role": expected_role,
        "turn_binding_sha256": request.binding_sha256,
        "prior_state_sha256": prior_state_sha256,
    }
    if any(state.get(key) != value for key, value in expected_base.items()):
        _blocked("benchmark_fixed_checkpoint_drift", "Recovered fixed-turn context drifted.")
    validated_response = state.get("validated_response")
    if not isinstance(validated_response, dict):
        _blocked("benchmark_fixed_checkpoint_invalid", "Recovered response is not an object.")
    if turn.outcome.response_sha256 != canonical_sha256(validated_response):
        _blocked("benchmark_fixed_checkpoint_drift", "Recovered response hash drifted.")
    if provider_request_counts_for_turn(db, cognitive_turn_receipt_id=turn.id) != (1, 1):
        _blocked("benchmark_fixed_checkpoint_drift", "Recovered turn request count drifted.")
    policy = require_llm_arm_policy("dronedream_fixed_two_turn/v1")
    if request.turn_index == 1:
        try:
            plan_decision, tools = validate_tool_action_response(
                validated_response, policy, allow_stop=False
            )
            proposals_after = _run_react_local_tools(
                tools, observation, already_used=set(used_tools_before)
            )
        except (BenchmarkAdapterError, BenchmarkLLMContractError) as exc:
            raise BenchmarkDurableLLMBlocked(
                "benchmark_fixed_checkpoint_invalid",
                "Recovered fixed plan fails its frozen schema or local-tool contract.",
            ) from exc
        stored_proposals = _react_proposals_from_state(state.get("proposals"))
        if (
            plan_decision != "act"
            or checkpoint.decision != "act"
            or state.get("decision") != "act"
            or state.get("used_tool_adapter_ids") != list(tools)
            or [_safe_react_proposal_record(item) for item in proposals_after]
            != [_safe_react_proposal_record(item) for item in stored_proposals]
            or state.get("selected_proposal_ref") is not None
            or state.get("final_proposal") is not None
            or state.get("terminal_receipt") != {}
        ):
            _blocked("benchmark_fixed_checkpoint_drift", "Recovered fixed plan is inconsistent.")
        return "act", stored_proposals, list(tools), None, {}, checkpoint.state_sha256

    stored_proposals = _react_proposals_from_state(state.get("proposals"))
    proposal_refs = tuple(proposal.candidate_ref for proposal in proposals_before)
    try:
        selected_ref = validate_selection_response(validated_response, proposal_refs)
    except BenchmarkLLMContractError as exc:
        raise BenchmarkDurableLLMBlocked(
            "benchmark_fixed_checkpoint_invalid",
            "Recovered fixed revision fails its frozen selection schema.",
        ) from exc
    revision_decision: Literal["dispatch", "abandon"] = (
        "dispatch" if selected_ref is not None else "abandon"
    )
    if (
        checkpoint.decision != revision_decision
        or state.get("decision") != revision_decision
        or state.get("used_tool_adapter_ids") != list(used_tools_before)
        or [_safe_react_proposal_record(item) for item in stored_proposals]
        != [_safe_react_proposal_record(item) for item in proposals_before]
        or state.get("selected_proposal_ref") != selected_ref
    ):
        _blocked("benchmark_fixed_checkpoint_drift", "Recovered fixed revision is inconsistent.")
    try:
        usage = reconcile_provider_run_usage(db, context.binding.id)
    except BenchmarkProviderUsageBlocked as exc:
        raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
    if usage.status != "complete":
        _blocked(
            "benchmark_provider_usage_incomplete",
            "Recovered fixed-turn usage cannot be reconciled completely.",
        )
    selected = (
        _proposal_by_ref(proposals_before, selected_ref) if selected_ref is not None else None
    )
    proposal, receipt = _fixed_terminal_receipt(
        context=context,
        observation=observation,
        selected=selected,
        turn_bindings=turn_bindings,
        usage_reconciliation_sha256=canonical_sha256(usage),
    )
    if state.get("terminal_receipt") != receipt or state.get("final_proposal") != (
        None if proposal is None else proposal.model_dump(mode="json")
    ):
        _blocked("benchmark_fixed_checkpoint_drift", "Recovered fixed terminal state drifted.")
    return (
        revision_decision,
        stored_proposals,
        list(used_tools_before),
        proposal,
        receipt,
        checkpoint.state_sha256,
    )


def execute_durable_fixed_two_turn_arm(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    transport: BenchmarkDirectTransport | None = None,
    transport_factory: BenchmarkDirectTransportFactory | None = None,
) -> BenchmarkDurableFixedTwoTurnExecutionV1:
    """Execute or recover one fixed plan -> local tools -> revision generation."""

    context = _load_context(
        db,
        job,
        observation,
        expected_adapter_id="dronedream_fixed_two_turn/v1",
    )
    policy = require_llm_arm_policy("dronedream_fixed_two_turn/v1")
    if job.first_qualified_candidate_id is not None:
        return BenchmarkDurableFixedTwoTurnExecutionV1(
            status="first_qualified_stop",
            proposal=None,
            provider_turns_attempted=0,
            provider_turns_succeeded=0,
            provider_requests_attempted=0,
            provider_requests_succeeded=0,
            safe_receipt={
                "schema_id": "dronedream.benchmark-first-qualified-stop/v1",
                "campaign_id": context.campaign.id,
                "run_binding_id": context.binding.id,
                "source_commit": context.source_commit,
            },
        )
    if (transport is None) == (transport_factory is None):
        _blocked(
            "benchmark_provider_transport_binding_invalid",
            "Fixed plan/revision execution requires exactly one transport binding.",
        )

    proposals: list[BenchmarkProposalV1] = []
    used_tools: list[str] = []
    prior_state_sha256: str | None = None
    turn_bindings: list[str] = []
    any_recovered = False
    fixed_turns: tuple[
        tuple[int, Literal["plan", "revision"]],
        tuple[int, Literal["plan", "revision"]],
    ] = ((1, "plan"), (2, "revision"))
    for turn_index, turn_role in fixed_turns:
        response_schema = (
            tool_action_response_schema(policy, allow_stop=False)
            if turn_index == 1
            else selection_response_schema(tuple(proposal.candidate_ref for proposal in proposals))
        )
        request = build_llm_turn_request(
            policy=policy,
            observation=observation,
            model_snapshot=context.provider.model_snapshot,
            turn_index=turn_index,
            turn_role=turn_role,
            response_schema=response_schema,
            tool_outputs=(
                []
                if turn_index == 1
                else [
                    {
                        "proposal_ref": proposal.candidate_ref,
                        "parameters": dict(proposal.parameters),
                        "proposal_reason_code": proposal.reason_code,
                        "proposal_receipt_sha256": canonical_sha256(proposal.proposal_receipt),
                    }
                    for proposal in proposals
                ]
            ),
        )
        turn_bindings.append(request.binding_sha256)
        recovered = _recover_fixed_checkpoint(
            db,
            job,
            context,
            observation,
            request,
            proposals_before=proposals,
            used_tools_before=used_tools,
            prior_state_sha256=prior_state_sha256,
            turn_bindings=turn_bindings,
        )
        if recovered is not None:
            any_recovered = True
            (
                recovered_decision,
                proposals,
                used_tools,
                recovered_proposal,
                safe_receipt,
                prior_state_sha256,
            ) = recovered
            if recovered_decision == "act":
                continue
            return BenchmarkDurableFixedTwoTurnExecutionV1(
                status=(
                    "proposal_recovered"
                    if recovered_decision == "dispatch"
                    else "abandoned_recovered"
                ),
                proposal=recovered_proposal,
                provider_turns_attempted=2,
                provider_turns_succeeded=2,
                provider_requests_attempted=2,
                provider_requests_succeeded=2,
                recovered_from_checkpoint=True,
                safe_receipt=safe_receipt,
            )

        body = _request_body(request, context.provider, context.binding.provider_seed)
        _require_prereserved_budget(db, context, body)
        if transport is None:
            try:
                transport = transport_factory(context.provider)  # type: ignore[misc]
            except BenchmarkDurableLLMBlocked:
                raise
            except Exception as exc:  # noqa: BLE001 - credentials remain private.
                raise BenchmarkDurableLLMBlocked(
                    "benchmark_provider_credential_unavailable",
                    "The Job-bound provider credential is unavailable.",
                ) from exc
        raw, attempt = _call_durable_provider_turn(
            db,
            job,
            context,
            request,
            body,
            transport,
            adapter_id="dronedream_fixed_two_turn/v1",
            turn_role=turn_role,
            maximum_turns_per_generation=2,
            error_namespace="fixed_two_turn",
        )
        try:
            if turn_index == 1:
                plan_decision, tools = validate_tool_action_response(raw, policy, allow_stop=False)
                proposals = _run_react_local_tools(tools, observation, already_used=set(used_tools))
                used_tools = list(tools)
                selected_ref = None
                decision: Literal["act", "dispatch", "abandon"] = "act"
                validated_response: dict[str, Any] = {
                    "schema_version": "1.0",
                    "decision": plan_decision,
                    "tool_adapter_ids": list(tools),
                }
            else:
                selected_ref = validate_selection_response(
                    raw, tuple(proposal.candidate_ref for proposal in proposals)
                )
                decision = "dispatch" if selected_ref is not None else "abandon"
                validated_response = {
                    "schema_version": "1.0",
                    "decision": decision,
                    "selected_proposal_ref": selected_ref,
                }
        except (BenchmarkAdapterError, BenchmarkLLMContractError) as exc:
            finish_cognitive_turn(
                db,
                job,
                attempt,
                status="invalid_schema",
                error_code="benchmark_fixed_two_turn_state_rejected",
            )
            raise BenchmarkDurableLLMBlocked(
                "benchmark_fixed_two_turn_state_rejected",
                "Fixed plan/revision decision or local-tool state failed closed.",
            ) from exc
        status = finish_cognitive_turn(
            db,
            job,
            attempt,
            status="succeeded",
            response=validated_response,
            commit=False,
        )
        if status != "succeeded":
            db.commit()
            db.refresh(job)
            _blocked("benchmark_source_drift", "Source changed before fixed-turn finalization.")
        proposal: BenchmarkProposalV1 | None = None
        terminal_receipt: dict[str, Any] = {}
        if turn_index == 2:
            try:
                usage = reconcile_provider_run_usage(db, context.binding.id)
            except BenchmarkProviderUsageBlocked as exc:
                db.rollback()
                db.refresh(job)
                finish_cognitive_turn(
                    db,
                    job,
                    attempt,
                    status="provider_failed",
                    error_code=exc.code,
                )
                raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
            if usage.status != "complete":
                db.rollback()
                db.refresh(job)
                finish_cognitive_turn(
                    db,
                    job,
                    attempt,
                    status="provider_failed",
                    error_code="benchmark_provider_usage_incomplete",
                )
                _blocked(
                    "benchmark_provider_usage_incomplete",
                    "Provider usage cannot be reconciled against the frozen reservation.",
                )
            selected = (
                _proposal_by_ref(proposals, selected_ref) if selected_ref is not None else None
            )
            proposal, terminal_receipt = _fixed_terminal_receipt(
                context=context,
                observation=observation,
                selected=selected,
                turn_bindings=turn_bindings,
                usage_reconciliation_sha256=canonical_sha256(usage),
            )
        state = {
            "schema_id": BENCHMARK_PLAN_REVISION_CHECKPOINT_SCHEMA_ID,
            "campaign_id": context.campaign.id,
            "run_binding_id": context.binding.id,
            "arm_manifest_sha256": context.arm.manifest_sha256,
            "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
            "source_commit": context.source_commit,
            "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
            "observation_sha256": canonical_sha256(observation),
            "generation_index": observation.generation_index,
            "turn_index": turn_index,
            "turn_role": turn_role,
            "turn_binding_sha256": request.binding_sha256,
            "prior_state_sha256": prior_state_sha256,
            "decision": decision,
            "validated_response": validated_response,
            "used_tool_adapter_ids": list(used_tools),
            "proposals": [_safe_react_proposal_record(item) for item in proposals],
            "selected_proposal_ref": selected_ref,
            "final_proposal": None if proposal is None else proposal.model_dump(mode="json"),
            "terminal_receipt": terminal_receipt,
        }
        state_sha256 = canonical_sha256(state)
        db.add(
            models.BenchmarkLLMPlanRevisionCheckpoint(
                job_id=job.id,
                run_binding_id=context.binding.id,
                cognitive_turn_receipt_id=attempt.receipt_id,
                checkpoint_schema=BENCHMARK_PLAN_REVISION_CHECKPOINT_SCHEMA_ID,
                adapter_id="dronedream_fixed_two_turn/v1",
                generation_index=observation.generation_index,
                turn_index=turn_index,
                turn_role=turn_role,
                source_commit=context.source_commit,
                observation_sha256=canonical_sha256(observation),
                turn_binding_sha256=request.binding_sha256,
                decision=decision,
                state_json=state,
                state_sha256=state_sha256,
            )
        )
        db.commit()
        db.refresh(job)
        prior_state_sha256 = state_sha256
        if turn_index == 1:
            continue
        return BenchmarkDurableFixedTwoTurnExecutionV1(
            status=(
                "proposal_recovered"
                if decision == "dispatch" and any_recovered
                else "abandoned_recovered"
                if decision == "abandon" and any_recovered
                else "proposal"
                if decision == "dispatch"
                else "abandoned"
            ),
            proposal=proposal,
            provider_turns_attempted=2,
            provider_turns_succeeded=2,
            provider_requests_attempted=2,
            provider_requests_succeeded=2,
            recovered_from_checkpoint=any_recovered,
            safe_receipt=terminal_receipt,
        )
    _blocked("benchmark_fixed_turn_sequence_incomplete", "Fixed two-turn sequence is incomplete.")


__all__ = [
    "BENCHMARK_DIRECT_RESERVATION_REASON",
    "BENCHMARK_PROVIDER_BASE_URLS",
    "BenchmarkDirectTransport",
    "BenchmarkDirectTransportFactory",
    "BenchmarkDurableDirectExecutionV1",
    "BenchmarkDurableFixedTwoTurnExecutionV1",
    "BenchmarkDurableLLAMBOExecutionV1",
    "BenchmarkDurableReactExecutionV1",
    "BenchmarkDurableLLMBlocked",
    "BenchmarkProviderExecutionConfigV1",
    "BenchmarkProviderTransportResult",
    "execute_durable_direct_arm",
    "execute_durable_fixed_two_turn_arm",
    "execute_durable_llambo_arm",
    "execute_durable_react_arm",
]
