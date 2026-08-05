"""Durable, fail-closed execution boundary for the direct LLM benchmark arm.

This module deliberately stops short of registering the arm as executable.  It
proves the production-shaped boundary with fake transports: campaign/run/source
provenance is revalidated, one logical turn and one actual request are committed
before provider I/O, and no retry or compatibility fallback is permitted.
Credentials remain an implementation detail of the injected transport and are
never accepted by these contracts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated, Any, Literal, NoReturn, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
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
    require_llm_arm_policy,
    validate_proposal_response,
)
from app.benchmarking.provider_execution_contract import (
    BENCHMARK_DIRECT_RESERVATION_REASON,
    BENCHMARK_PROVIDER_BASE_URLS,
    BenchmarkProviderExecutionConfigV1,
    direct_provider_run_capacity,
)
from app.benchmarking.provider_usage_reconciliation import (
    BenchmarkProviderUsageBlocked,
    reconcile_direct_provider_run_usage,
    validate_provider_run_reservation,
)
from app.orchestration.cognitive_budget import (
    begin_benchmark_direct_turn,
    cancel_cognitive_turn_if_job_terminal,
    finish_cognitive_turn,
    resolve_source_commit,
)
from app.orchestration.provider_request_accounting import (
    BoundProviderRequestAccountant,
    ProviderUsage,
    provider_request_counts_for_turn,
)

BENCHMARK_DIRECT_PROPOSAL_RECEIPT_SCHEMA_ID = (
    "dronedream.benchmark-direct-proposal/v1"
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
        request: BenchmarkLLMTurnRequestV1,
        config: BenchmarkProviderExecutionConfigV1,
    ) -> BenchmarkProviderTransportResult: ...


class BenchmarkDurableDirectExecutionV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-durable-direct-execution/v1"] = (
        "dronedream.benchmark-durable-direct-execution/v1"
    )
    status: Literal["proposal", "first_qualified_stop"]
    proposal: BenchmarkProposalV1 | None
    provider_turns_attempted: Annotated[int, Field(ge=0, le=1)]
    provider_turns_succeeded: Annotated[int, Field(ge=0, le=1)]
    provider_requests_attempted: Annotated[int, Field(ge=0, le=1)]
    provider_requests_succeeded: Annotated[int, Field(ge=0, le=1)]
    safe_receipt: dict[str, Any]

    @model_validator(mode="after")
    def _validate_result(self) -> BenchmarkDurableDirectExecutionV1:
        if self.status == "proposal":
            if self.proposal is None or self.provider_turns_succeeded != 1:
                raise ValueError("proposal result requires one successful durable turn")
        elif self.proposal is not None or any(
            (
                self.provider_turns_attempted,
                self.provider_turns_succeeded,
                self.provider_requests_attempted,
                self.provider_requests_succeeded,
            )
        ):
            raise ValueError("first-qualified stop must consume zero provider work")
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
        inventory = CompositeExecutionInventoryV1.model_validate(
            campaign.composite_inventory_json
        )
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
        if item.benchmark_arm_id == arm.benchmark_arm_id
        and item.arm_version == arm.arm_version
    ]
    if len(matching_arms) != 1 or matching_arms[0] != arm_manifest:
        _blocked("benchmark_arm_campaign_mismatch", "Arm differs from the campaign manifest.")
    if (
        not arm_manifest.execution_enabled
        or arm_manifest.proposal_adapter_id != "llm_direct/v1"
        or arm.proposal_adapter_id != "llm_direct/v1"
        or arm_manifest.provider_contract_sha256 != BENCHMARK_LLM_ARM_POLICIES_SHA256
    ):
        _blocked("benchmark_direct_contract_mismatch", "Arm is not the frozen direct LLM contract.")
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
    if provider.maximum_generations != job.max_iterations or (
        job.provider_turn_cap != provider.maximum_generations
        or job.provider_request_cap != provider.maximum_generations
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
                "name": "benchmark_direct_proposal",
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
    required = direct_provider_run_capacity(context.provider)
    if any(
        int(getattr(reservation, field)) != amount
        for field, amount in required.model_dump().items()
    ):
        _blocked(
            "benchmark_provider_budget_drift",
            "Reserved provider budget differs from the frozen run capacity.",
        )


def execute_durable_direct_arm(
    db: Session,
    job: models.Job,
    observation: BenchmarkObservationV2,
    *,
    transport: BenchmarkDirectTransport,
) -> BenchmarkDurableDirectExecutionV1:
    """Execute exactly one direct proposal after durable attempts are committed."""

    context = _load_context(db, job, observation)
    policy = require_llm_arm_policy("llm_direct/v1")
    if job.first_qualified_candidate_id is not None:
        return BenchmarkDurableDirectExecutionV1(
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
        turn_role="direct_proposal",
        response_schema=proposal_response_schema(observation),
    )
    body = _request_body(request, context.provider, context.binding.provider_seed)
    _require_prereserved_budget(db, context, body)
    attempt = begin_benchmark_direct_turn(
        db,
        job,
        generation_index=observation.generation_index,
        turn_role="direct_proposal",
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
        result = transport.complete(request, context.provider)
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
            error_code="benchmark_direct_response_invalid",
        )
        raise BenchmarkDurableLLMBlocked(
            "benchmark_direct_response_invalid",
            "Provider response failed the frozen direct-proposal schema.",
        ) from exc
    status = finish_cognitive_turn(db, job, attempt, status="succeeded", response=parameters)
    if status != "succeeded":
        _blocked("benchmark_source_drift", "Source changed before cognitive finalization.")
    request_counts = provider_request_counts_for_turn(
        db,
        cognitive_turn_receipt_id=attempt.receipt_id,
    )
    try:
        usage_reconciliation = reconcile_direct_provider_run_usage(db, context.binding.id)
    except BenchmarkProviderUsageBlocked as exc:
        raise BenchmarkDurableLLMBlocked(exc.code, str(exc)) from exc
    if usage_reconciliation.status != "complete":
        _blocked(
            "benchmark_provider_usage_incomplete",
            "Provider usage cannot be reconciled completely against the reservation.",
        )
    parameter_sha256 = canonical_sha256(parameters)
    safe_receipt = {
        "schema_id": BENCHMARK_DIRECT_PROPOSAL_RECEIPT_SCHEMA_ID,
        "campaign_id": context.campaign.id,
        "run_binding_id": context.binding.id,
        "arm_manifest_sha256": context.arm.manifest_sha256,
        "composite_inventory_sha256": context.campaign.composite_inventory_sha256,
        "source_commit": context.source_commit,
        "llm_policy_registry_sha256": BENCHMARK_LLM_ARM_POLICIES_SHA256,
        "turn_binding_sha256": request.binding_sha256,
        "parameter_sha256": parameter_sha256,
        "provider_turns_attempted": 1,
        "provider_turns_succeeded": 1,
        "provider_requests_attempted": request_counts[0],
        "provider_requests_succeeded": request_counts[1],
        "provider_usage_reconciliation_sha256": canonical_sha256(usage_reconciliation),
        "retry_cap": 0,
    }
    proposal = BenchmarkProposalV1(
        candidate_ref=(
            f"llm-direct-g{observation.generation_index:06d}-"
            f"d{observation.next_dispatch_ordinal:06d}-{parameter_sha256[:12]}"
        ),
        parameters=parameters,
        reason_code="benchmark-llm-direct",
        proposal_receipt=safe_receipt,
    )
    return BenchmarkDurableDirectExecutionV1(
        status="proposal",
        proposal=proposal,
        provider_turns_attempted=1,
        provider_turns_succeeded=1,
        provider_requests_attempted=request_counts[0],
        provider_requests_succeeded=request_counts[1],
        safe_receipt=safe_receipt,
    )


__all__ = [
    "BENCHMARK_DIRECT_RESERVATION_REASON",
    "BENCHMARK_PROVIDER_BASE_URLS",
    "BenchmarkDirectTransport",
    "BenchmarkDurableDirectExecutionV1",
    "BenchmarkDurableLLMBlocked",
    "BenchmarkProviderExecutionConfigV1",
    "BenchmarkProviderTransportResult",
    "execute_durable_direct_arm",
]
