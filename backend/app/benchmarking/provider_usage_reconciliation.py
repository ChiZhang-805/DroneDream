"""Reconcile actual provider work without double counting reserved capacity."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal, NoReturn

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.benchmarking.contracts import (
    BenchmarkArmManifestV1,
    BenchmarkBudgetReservationRequestV1,
    BenchmarkCampaignManifestV1,
    BenchmarkProviderAttemptCountsV1,
    BenchmarkProviderRunUsageReconciliationV1,
    BenchmarkResourceVectorV1,
    BenchmarkRunBindingRequestV1,
    BenchmarkUsageDeltaV1,
    CompositeExecutionInventoryV1,
    canonical_sha256,
)
from app.benchmarking.coordinator import run_binding_sha256
from app.benchmarking.llm_arm_contracts import require_llm_arm_policy
from app.benchmarking.provider_execution_contract import (
    BENCHMARK_DIRECT_RESERVATION_REASON,
)


class BenchmarkProviderUsageBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _blocked(code: str, message: str) -> NoReturn:
    raise BenchmarkProviderUsageBlocked(code, message)


def _iso8601(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resource_vector(record: models.BenchmarkBudgetReservation) -> BenchmarkResourceVectorV1:
    return BenchmarkResourceVectorV1(
        jobs=record.jobs,
        trials=record.trials,
        logical_turns=record.logical_turns,
        network_requests=record.network_requests,
        input_utf8_bytes=record.input_utf8_bytes,
        output_utf8_bytes=record.output_utf8_bytes,
        provider_tokens=record.provider_tokens,
        provider_cost_microusd=record.provider_cost_microusd,
        wall_time_seconds=record.wall_time_seconds,
        disk_bytes=record.disk_bytes,
    )


def validate_provider_run_reservation(
    reservation: models.BenchmarkBudgetReservation,
    *,
    campaign_id: str,
    run_binding_id: str,
) -> BenchmarkResourceVectorV1:
    if (
        reservation.campaign_id != campaign_id
        or reservation.reservation_key != f"provider-run/{run_binding_id}"
        or reservation.reason != BENCHMARK_DIRECT_RESERVATION_REASON
    ):
        _blocked(
            "benchmark_provider_reservation_binding_drift",
            "Provider reservation is not bound to this campaign run.",
        )
    capacity = _resource_vector(reservation)
    try:
        usage = BenchmarkUsageDeltaV1.model_validate(capacity.model_dump())
        expected_sha256 = canonical_sha256(
            BenchmarkBudgetReservationRequestV1(
                reservation_key=reservation.reservation_key,
                lease_generation=reservation.lease_generation,
                reason=reservation.reason,
                usage=usage,
            )
        )
    except ValidationError as exc:
        raise BenchmarkProviderUsageBlocked(
            "benchmark_provider_reservation_invalid",
            "Provider reservation no longer satisfies the frozen schema.",
        ) from exc
    if expected_sha256 != reservation.reservation_sha256:
        _blocked(
            "benchmark_provider_reservation_hash_drift",
            "Provider reservation hash no longer matches its immutable fields.",
        )
    return capacity


def _validate_run_graph(
    run: models.BenchmarkCampaignRunBinding,
) -> tuple[
    models.BenchmarkCampaign,
    models.BenchmarkArm,
    CompositeExecutionInventoryV1,
    str,
    dict[str, Any],
]:
    campaign = run.campaign
    arm = run.arm
    if (
        run.job_id != run.job.id
        or run.campaign_id != campaign.id
        or arm.campaign_id != campaign.id
        or run.batch_binding.campaign_id != campaign.id
        or run.job.user_id != campaign.user_id
    ):
        _blocked(
            "benchmark_provider_run_graph_drift",
            "Provider run binding graph is inconsistent.",
        )
    if arm.proposal_adapter_id not in {"llm_direct/v1", "llm_react/v1"}:
        _blocked(
            "benchmark_provider_reconciliation_arm_unsupported",
            "This reconciliation contract does not support the bound provider arm.",
        )
    try:
        arm_manifest = BenchmarkArmManifestV1.model_validate(arm.manifest_json)
        campaign_manifest = BenchmarkCampaignManifestV1.model_validate(campaign.manifest_json)
        inventory = CompositeExecutionInventoryV1.model_validate(campaign.composite_inventory_json)
    except ValidationError as exc:
        raise BenchmarkProviderUsageBlocked(
            "benchmark_provider_reconciliation_manifest_invalid",
            "Campaign provider provenance does not satisfy the current schema.",
        ) from exc
    if canonical_sha256(arm_manifest) != arm.manifest_sha256:
        _blocked("benchmark_arm_manifest_drift", "Arm manifest hash no longer matches.")
    if canonical_sha256(campaign_manifest) != campaign.manifest_sha256:
        _blocked(
            "benchmark_campaign_manifest_drift",
            "Campaign manifest hash no longer matches.",
        )
    if canonical_sha256(inventory) != campaign.composite_inventory_sha256:
        _blocked("benchmark_inventory_drift", "Composite inventory hash no longer matches.")
    if campaign_manifest.composite_execution_inventory != inventory:
        _blocked(
            "benchmark_inventory_manifest_mismatch",
            "Campaign inventory copies disagree.",
        )
    matching_arms = [
        item
        for item in campaign_manifest.arms
        if item.benchmark_arm_id == arm.benchmark_arm_id and item.arm_version == arm.arm_version
    ]
    if len(matching_arms) != 1 or matching_arms[0] != arm_manifest:
        _blocked(
            "benchmark_arm_campaign_mismatch",
            "Run arm differs from the frozen campaign manifest.",
        )
    if (
        arm_manifest.proposal_adapter_id != arm.proposal_adapter_id
        or arm_manifest.benchmark_arm_id != arm.benchmark_arm_id
        or arm_manifest.arm_version != arm.arm_version
    ):
        _blocked("benchmark_llm_contract_mismatch", "Run arm differs from its manifest.")
    scenario_sha256 = run.scenario_suite_sha256
    qualification_sha256 = run.qualification_contract_sha256
    if scenario_sha256 is None or qualification_sha256 is None:
        _blocked("benchmark_qualification_binding_missing", "Run qualification is not sealed.")
    request = BenchmarkRunBindingRequestV1(
        run_key=run.run_key,
        job_id=run.job_id,
        benchmark_arm_id=arm.benchmark_arm_id,
        arm_version=arm.arm_version,
        algorithm_seed=run.algorithm_seed,
        simulator_seed_block=run.simulator_seed_block,
        provider_randomness_policy=run.provider_randomness_policy,  # type: ignore[arg-type]
        provider_seed=run.provider_seed,
    )
    if (
        run_binding_sha256(
            request,
            scenario_suite_sha256=scenario_sha256,
            qualification_contract_sha256=qualification_sha256,
        )
        != run.binding_sha256
    ):
        _blocked("benchmark_run_binding_drift", "Run binding hash no longer matches.")
    source_commit = inventory.engine_pack.source_commit
    if source_commit is None:
        _blocked(
            "benchmark_provider_source_missing",
            "Engine Pack source is required for provider reconciliation.",
        )
    provider_payload = arm_manifest.intervention.get("provider_execution")
    if (
        not isinstance(provider_payload, dict)
        or provider_payload.get("model_snapshot") != run.job.openai_model
    ):
        _blocked("benchmark_provider_contract_invalid", "Provider model binding is invalid.")
    return campaign, arm, inventory, source_commit, provider_payload


def _turn_ledger_item(turn: models.HarnessCognitiveTurnReceipt) -> dict[str, Any]:
    outcome = turn.outcome
    return {
        "generation_index": turn.generation_index,
        "turn_index": turn.turn_index,
        "turn_role": turn.turn_role,
        "trigger_policy_version": turn.trigger_policy_version,
        "trigger_reasons": turn.trigger_reasons_json,
        "source_commit": turn.source_commit,
        "model_snapshot": turn.model_snapshot,
        "prompt_sha256": turn.prompt_sha256,
        "evidence_sha256": turn.evidence_sha256,
        "schema_sha256": turn.schema_sha256,
        "tool_outputs_sha256": turn.tool_outputs_sha256,
        "attempted_at": _iso8601(turn.attempted_at),
        "outcome": None
        if outcome is None
        else {
            "status": outcome.status,
            "response_sha256": outcome.response_sha256,
            "error_code": outcome.error_code,
            "completed_at": _iso8601(outcome.completed_at),
        },
    }


def _request_ledger_item(request: models.ProviderNetworkRequestReceipt) -> dict[str, Any]:
    turn = request.turn_receipt
    outcome = request.outcome
    return {
        "generation_index": turn.generation_index,
        "turn_index": turn.turn_index,
        "request_index": request.request_index,
        "request_kind": request.request_kind,
        "retry_policy_version": request.retry_policy_version,
        "provider": request.provider,
        "model_snapshot": request.model_snapshot,
        "api_surface": request.api_surface,
        "base_url_sha256": request.base_url_sha256,
        "region": request.region,
        "temperature": request.temperature,
        "top_p": request.top_p,
        "provider_seed": request.provider_seed,
        "response_schema_sha256": request.response_schema_sha256,
        "prompt_sha256": request.prompt_sha256,
        "tool_outputs_sha256": request.tool_outputs_sha256,
        "request_body_sha256": request.request_body_sha256,
        "input_utf8_bytes": request.input_utf8_bytes,
        "price_snapshot_sha256": request.price_snapshot_sha256,
        "attempted_at": _iso8601(request.attempted_at),
        "outcome": None
        if outcome is None
        else {
            "status": outcome.status,
            "response_sha256": outcome.response_sha256,
            "output_utf8_bytes": outcome.output_utf8_bytes,
            "input_tokens": outcome.input_tokens,
            "output_tokens": outcome.output_tokens,
            "total_tokens": outcome.total_tokens,
            "provider_cost_microusd": outcome.provider_cost_microusd,
            "latency_ms": outcome.latency_ms,
            "error_code": outcome.error_code,
            "completed_at": _iso8601(outcome.completed_at),
        },
    }


def _attempt_counts(statuses: list[str | None]) -> BenchmarkProviderAttemptCountsV1:
    return BenchmarkProviderAttemptCountsV1(
        attempted=len(statuses),
        succeeded=sum(status == "succeeded" for status in statuses),
        failed=sum(status not in {None, "succeeded", "indeterminate"} for status in statuses),
        indeterminate=sum(status in {None, "indeterminate"} for status in statuses),
    )


def reconcile_provider_run_usage(
    db: Session,
    run_binding_id: str,
) -> BenchmarkProviderRunUsageReconciliationV1:
    """Recompute one run's actual work from immutable attempt/outcome ledgers."""

    run = db.get(models.BenchmarkCampaignRunBinding, run_binding_id)
    if run is None:
        _blocked("benchmark_run_binding_missing", "Benchmark run binding is missing.")
    campaign, arm, inventory, source_commit, provider_payload = _validate_run_graph(run)
    reservation = db.scalar(
        select(models.BenchmarkBudgetReservation).where(
            models.BenchmarkBudgetReservation.campaign_id == campaign.id,
            models.BenchmarkBudgetReservation.reservation_key == f"provider-run/{run.id}",
        )
    )
    if reservation is None:
        _blocked("benchmark_provider_budget_unreserved", "Run provider budget is not reserved.")
    capacity = validate_provider_run_reservation(
        reservation,
        campaign_id=campaign.id,
        run_binding_id=run.id,
    )
    turns = list(
        db.scalars(
            select(models.HarnessCognitiveTurnReceipt)
            .where(models.HarnessCognitiveTurnReceipt.job_id == run.job_id)
            .order_by(
                models.HarnessCognitiveTurnReceipt.generation_index,
                models.HarnessCognitiveTurnReceipt.turn_index,
            )
        )
    )
    policy = require_llm_arm_policy(arm.proposal_adapter_id)
    expected_role = (
        "direct_proposal" if arm.proposal_adapter_id == "llm_direct/v1" else "react_action"
    )
    expected_trigger = (
        "benchmark-llm-direct-v1"
        if arm.proposal_adapter_id == "llm_direct/v1"
        else "benchmark-llm-react-v1"
    )
    expected_reason = (
        ["preregistered-direct-turn"]
        if arm.proposal_adapter_id == "llm_direct/v1"
        else ["bounded-react-turn"]
    )
    if any(
        turn.turn_role != expected_role
        or not 1 <= turn.turn_index <= policy.maximum_turns_per_generation
        or turn.trigger_policy_version != expected_trigger
        or turn.trigger_reasons_json != expected_reason
        or turn.source_commit != source_commit
        or turn.model_snapshot != run.job.openai_model
        for turn in turns
    ):
        _blocked(
            "benchmark_provider_turn_contract_drift",
            "Cognitive ledger contains work outside the bound LLM arm contract.",
        )
    requests = list(
        db.scalars(
            select(models.ProviderNetworkRequestReceipt)
            .join(models.HarnessCognitiveTurnReceipt)
            .where(models.HarnessCognitiveTurnReceipt.job_id == run.job_id)
            .order_by(
                models.HarnessCognitiveTurnReceipt.generation_index,
                models.HarnessCognitiveTurnReceipt.turn_index,
                models.ProviderNetworkRequestReceipt.request_index,
            )
        )
    )
    expected_provider = provider_payload.get("provider")
    expected_api_surface = provider_payload.get("api_surface", "chat_completions")
    expected_base_url = provider_payload.get("base_url")
    expected_temperature = provider_payload.get("temperature")
    expected_top_p = provider_payload.get("top_p")
    expected_price = provider_payload.get("price_snapshot")
    if not isinstance(expected_price, dict):
        _blocked(
            "benchmark_provider_contract_invalid",
            "Provider price snapshot is missing from the arm contract.",
        )
    expected_price_sha256 = canonical_sha256(expected_price)
    if any(
        request.request_index != 1
        or request.request_kind != "primary"
        or request.retry_policy_version != "explicit-network-attempts-v1"
        or request.provider != expected_provider
        or request.model_snapshot != run.job.openai_model
        or request.api_surface != expected_api_surface
        or request.base_url_normalized != expected_base_url
        or request.temperature != expected_temperature
        or request.top_p != expected_top_p
        or request.provider_seed != run.provider_seed
        or request.price_snapshot_sha256 != expected_price_sha256
        for request in requests
    ):
        _blocked(
            "benchmark_provider_request_contract_drift",
            "Network ledger contains retries, fallbacks, or model drift.",
        )

    turn_statuses = [turn.outcome.status if turn.outcome is not None else None for turn in turns]
    request_statuses = [
        request.outcome.status if request.outcome is not None else None for request in requests
    ]
    cognitive_counts = _attempt_counts(turn_statuses)
    network_counts = _attempt_counts(request_statuses)
    incomplete_usage = 0
    output_bytes = 0
    provider_tokens = 0
    provider_cost = 0
    latency_ms = 0
    for request in requests:
        outcome = request.outcome
        if outcome is None:
            incomplete_usage += 1
            continue
        output_bytes += outcome.output_utf8_bytes
        latency_ms += outcome.latency_ms
        if (
            outcome.status != "succeeded"
            or outcome.input_tokens is None
            or outcome.output_tokens is None
            or outcome.total_tokens is None
            or outcome.provider_cost_microusd is None
        ):
            incomplete_usage += 1
        provider_tokens += outcome.total_tokens or 0
        provider_cost += outcome.provider_cost_microusd or 0
    observed = BenchmarkResourceVectorV1(
        logical_turns=len(turns),
        network_requests=len(requests),
        input_utf8_bytes=sum(request.input_utf8_bytes for request in requests),
        output_utf8_bytes=output_bytes,
        provider_tokens=provider_tokens,
        provider_cost_microusd=provider_cost,
        wall_time_seconds=math.ceil(latency_ms / 1000),
    )
    status: Literal["complete", "usage_incomplete", "indeterminate"] = (
        "indeterminate"
        if cognitive_counts.indeterminate or network_counts.indeterminate
        else "usage_incomplete"
        if incomplete_usage
        else "complete"
    )
    try:
        return BenchmarkProviderRunUsageReconciliationV1(
            status=status,
            campaign_id=campaign.id,
            run_binding_id=run.id,
            job_id=run.job_id,
            benchmark_arm_id=arm.benchmark_arm_id,
            source_commit=source_commit,
            composite_inventory_sha256=campaign.composite_inventory_sha256,
            reservation_id=reservation.id,
            reservation_sha256=reservation.reservation_sha256,
            reserved_capacity=capacity,
            actual_observed=observed,
            cognitive_turns=cognitive_counts,
            network_requests=network_counts,
            requests_with_incomplete_usage=incomplete_usage,
            cognitive_ledger_sha256=canonical_sha256([_turn_ledger_item(turn) for turn in turns]),
            network_ledger_sha256=canonical_sha256(
                [_request_ledger_item(request) for request in requests]
            ),
        )
    except ValidationError as exc:
        raise BenchmarkProviderUsageBlocked(
            "benchmark_provider_usage_exceeds_reservation",
            "Actual provider work exceeds or conflicts with preregistered capacity.",
        ) from exc


def reconcile_direct_provider_run_usage(
    db: Session,
    run_binding_id: str,
) -> BenchmarkProviderRunUsageReconciliationV1:
    """Backward-compatible direct-arm entry point."""

    run = db.get(models.BenchmarkCampaignRunBinding, run_binding_id)
    if run is None or run.arm.proposal_adapter_id != "llm_direct/v1":
        _blocked(
            "benchmark_provider_reconciliation_arm_unsupported",
            "The direct reconciliation entry point requires llm_direct/v1.",
        )
    return reconcile_provider_run_usage(db, run_binding_id)


__all__ = [
    "BENCHMARK_DIRECT_RESERVATION_REASON",
    "BenchmarkProviderUsageBlocked",
    "reconcile_direct_provider_run_usage",
    "reconcile_provider_run_usage",
    "validate_provider_run_reservation",
]
