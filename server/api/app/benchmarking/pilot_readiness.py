"""Fail-closed readiness assessment before a benchmark provider pilot.

This module does not discover files, contact a provider, start a simulator, or
authorize execution.  Trusted adapters must supply exact, source-bound gate
receipts.  A successful assessment only means that the caller may prepare a
separate, explicitly approved provider-batch request.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.composite_inventory import (
    CompositeExecutionVerificationReceiptV1,
)
from app.benchmarking.contracts import GitCommit, Identifier, Sha256Hex, canonical_sha256
from app.benchmarking.llm_arm_contracts import BENCHMARK_LLM_ARM_POLICIES_SHA256
from app.benchmarking.method_inventory import (
    BENCHMARK_METHOD_INVENTORY,
    BENCHMARK_METHOD_INVENTORY_SHA256,
)
from app.benchmarking.physical_stability import PHYSICAL_STABILITY_PROTOCOL_SHA256
from app.benchmarking.physical_stability_assessment import PhysicalStabilityAssessmentV1

BENCHMARK_PILOT_READINESS_SCHEMA_ID: Final = "dronedream.benchmark-pilot-readiness/v1"
BENCHMARK_PILOT_READINESS_POLICY_VERSION: Final = "pilot-readiness-fail-closed-v1"

PilotGateId = Literal[
    "campaign-coordinator",
    "sealed-qualification",
    "provider-accounting",
    "statistical-preregistration",
    "composite-inventory",
    "current-exact-quality",
    "physical-stability",
    "final-scenario-freeze",
]
PilotGateStatus = Literal["passed", "failed", "not_run", "indeterminate"]
PilotBlockerCode = Annotated[
    str,
    Field(pattern=r"^[a-z0-9][a-z0-9._/:-]{0,191}$"),
]

_REQUIRED_GATE_IDS: Final[tuple[PilotGateId, ...]] = (
    "campaign-coordinator",
    "sealed-qualification",
    "provider-accounting",
    "statistical-preregistration",
    "composite-inventory",
    "current-exact-quality",
    "physical-stability",
    "final-scenario-freeze",
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkPilotGateReceiptV1(_StrictFrozen):
    """One current-exact, sanitized prerequisite receipt."""

    schema_id: Literal["dronedream.benchmark-pilot-gate-receipt/v1"] = (
        "dronedream.benchmark-pilot-gate-receipt/v1"
    )
    gate_id: PilotGateId
    repository_subject_commit: GitCommit
    status: PilotGateStatus
    contract_sha256: Sha256Hex
    evidence_sha256: Sha256Hex
    receipt_file_sha256: Sha256Hex
    issued_at_utc: datetime
    physical_trials_attempted: Annotated[int, Field(ge=0)] = 0
    provider_network_requests_attempted: Annotated[int, Field(ge=0)] = 0
    current_exact: Literal[True] = True
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> BenchmarkPilotGateReceiptV1:
        if self.issued_at_utc.tzinfo is None:
            raise ValueError("pilot gate receipt timestamp must be timezone-aware")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_sha256(payload) != self.binding_sha256:
            raise ValueError("pilot gate receipt binding hash does not match")
        if self.gate_id == "physical-stability":
            if self.provider_network_requests_attempted != 0:
                raise ValueError("physical stability gate must remain zero-provider")
            if self.status == "passed" and self.physical_trials_attempted != 60:
                raise ValueError("passed physical stability gate requires exactly 60 trials")
        elif self.physical_trials_attempted != 0:
            raise ValueError("only the physical stability gate may report physical trials")
        return self


class BenchmarkPilotReadinessObservationV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-pilot-readiness-observation/v1"] = (
        "dronedream.benchmark-pilot-readiness-observation/v1"
    )
    repository_subject_commit: GitCommit
    protocol_sha256: Literal[
        "734bb6b42ec25ffc92bd9f15bb6fa27bc3482b4ce0841ce9aa3b080eafb8caee"
    ] = PHYSICAL_STABILITY_PROTOCOL_SHA256
    method_inventory_sha256: Sha256Hex
    llm_arm_policies_sha256: Sha256Hex
    campaign_manifest_sha256: Sha256Hex
    required_adapter_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=32)
    required_adapter_set_sha256: Sha256Hex
    gate_receipts: tuple[BenchmarkPilotGateReceiptV1, ...] = Field(
        min_length=len(_REQUIRED_GATE_IDS),
        max_length=len(_REQUIRED_GATE_IDS),
    )
    composite_verification: CompositeExecutionVerificationReceiptV1
    physical_stability_assessment: PhysicalStabilityAssessmentV1
    final_scenario_manifest_sha256: Sha256Hex
    observation_adapter_receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_unique_bindings(self) -> BenchmarkPilotReadinessObservationV1:
        if len(self.required_adapter_ids) != len(set(self.required_adapter_ids)):
            raise ValueError("required benchmark adapter ids must be unique")
        if canonical_sha256(sorted(self.required_adapter_ids)) != self.required_adapter_set_sha256:
            raise ValueError("required benchmark adapter set hash does not match")
        gate_ids = tuple(receipt.gate_id for receipt in self.gate_receipts)
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("pilot gate receipt ids must be unique")
        return self


class BenchmarkPilotReadinessReceiptV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-pilot-readiness/v1"] = (
        BENCHMARK_PILOT_READINESS_SCHEMA_ID
    )
    policy_version: Literal["pilot-readiness-fail-closed-v1"] = (
        BENCHMARK_PILOT_READINESS_POLICY_VERSION
    )
    status: Literal["ready_for_batch_approval", "blocked"]
    ready_for_provider_batch_approval: bool
    execution_authorized: Literal[False] = False
    separate_provider_batch_approval_required: Literal[True] = True
    repository_subject_commit: GitCommit
    observation_sha256: Sha256Hex
    method_inventory_sha256: Sha256Hex
    llm_arm_policies_sha256: Sha256Hex
    verified_gate_ids: tuple[PilotGateId, ...]
    blocked_adapter_ids: tuple[Identifier, ...]
    blocker_codes: tuple[PilotBlockerCode, ...]

    @model_validator(mode="after")
    def _validate_status(self) -> BenchmarkPilotReadinessReceiptV1:
        if self.status == "ready_for_batch_approval":
            if not self.ready_for_provider_batch_approval:
                raise ValueError("ready status requires the readiness flag")
            if self.blocked_adapter_ids or self.blocker_codes:
                raise ValueError("ready status cannot retain blockers")
            if self.verified_gate_ids != _REQUIRED_GATE_IDS:
                raise ValueError("ready status requires every prerequisite gate")
        elif self.ready_for_provider_batch_approval:
            raise ValueError("blocked status cannot set the readiness flag")
        return self


def _append_reason(reasons: list[str], code: str, condition: bool) -> None:
    if condition and code not in reasons:
        reasons.append(code)


def assess_benchmark_pilot_readiness(
    observation: BenchmarkPilotReadinessObservationV1,
) -> BenchmarkPilotReadinessReceiptV1:
    """Assess prerequisites without authorizing a provider or simulator run."""

    reasons: list[str] = []
    _append_reason(
        reasons,
        "method-inventory-hash-mismatch",
        observation.method_inventory_sha256 != BENCHMARK_METHOD_INVENTORY_SHA256,
    )
    _append_reason(
        reasons,
        "llm-policy-hash-mismatch",
        observation.llm_arm_policies_sha256 != BENCHMARK_LLM_ARM_POLICIES_SHA256,
    )

    unknown_adapters = sorted(
        set(observation.required_adapter_ids) - set(BENCHMARK_METHOD_INVENTORY)
    )
    blocked_adapters = sorted(
        adapter_id
        for adapter_id in observation.required_adapter_ids
        if adapter_id in BENCHMARK_METHOD_INVENTORY
        and BENCHMARK_METHOD_INVENTORY[adapter_id].execution_readiness != "ready"
    )
    for adapter_id in unknown_adapters:
        reasons.append(f"unregistered-adapter:{adapter_id}")
    for adapter_id in blocked_adapters:
        reasons.append(f"blocked-adapter:{adapter_id}")

    receipts = {receipt.gate_id: receipt for receipt in observation.gate_receipts}
    verified_gate_ids: list[PilotGateId] = []
    for gate_id in _REQUIRED_GATE_IDS:
        receipt = receipts.get(gate_id)
        if receipt is None:
            reasons.append(f"missing-gate:{gate_id}")
            continue
        if receipt.repository_subject_commit != observation.repository_subject_commit:
            reasons.append(f"gate-subject-drift:{gate_id}")
            continue
        if receipt.status != "passed":
            reasons.append(f"gate-not-passed:{gate_id}:{receipt.status}")
            continue
        verified_gate_ids.append(gate_id)

    campaign_gate = receipts.get("campaign-coordinator")
    _append_reason(
        reasons,
        "campaign-manifest-receipt-mismatch",
        campaign_gate is None
        or campaign_gate.evidence_sha256 != observation.campaign_manifest_sha256,
    )

    composite = observation.composite_verification
    _append_reason(reasons, "composite-inventory-not-verified", composite.status != "verified")
    _append_reason(reasons, "composite-inventory-incompatible", not composite.compatible)
    _append_reason(
        reasons,
        "composite-inventory-receipt-authorized-execution",
        composite.execution_authorized is not False,
    )
    composite_gate = receipts.get("composite-inventory")
    _append_reason(
        reasons,
        "composite-inventory-gate-evidence-mismatch",
        composite_gate is None
        or composite_gate.evidence_sha256 != canonical_sha256(composite),
    )

    assessment = observation.physical_stability_assessment
    _append_reason(
        reasons,
        "physical-stability-subject-drift",
        assessment.repository_subject_commit != observation.repository_subject_commit,
    )
    _append_reason(reasons, "physical-stability-trials-incomplete", assessment.trial_count != 60)
    _append_reason(
        reasons,
        "physical-stability-provider-use-detected",
        assessment.provider_network_requests_attempted != 0
        or assessment.provider_logical_turns_attempted != 0,
    )
    _append_reason(reasons, "physical-stability-not-ready", not assessment.pilot_selection_ready)
    _append_reason(
        reasons,
        "physical-stability-comparative-leakage",
        assessment.comparative_arm_outcomes_observed is not False,
    )
    _append_reason(
        reasons,
        "physical-stability-composite-mismatch",
        assessment.composite_execution_inventory_sha256 != composite.inventory_sha256,
    )
    physical_gate = receipts.get("physical-stability")
    _append_reason(
        reasons,
        "physical-stability-gate-evidence-mismatch",
        physical_gate is None
        or physical_gate.evidence_sha256 != canonical_sha256(assessment),
    )
    scenario_gate = receipts.get("final-scenario-freeze")
    _append_reason(
        reasons,
        "final-scenario-manifest-receipt-mismatch",
        scenario_gate is None
        or scenario_gate.evidence_sha256
        != observation.final_scenario_manifest_sha256,
    )

    ready = not reasons
    return BenchmarkPilotReadinessReceiptV1(
        status="ready_for_batch_approval" if ready else "blocked",
        ready_for_provider_batch_approval=ready,
        repository_subject_commit=observation.repository_subject_commit,
        observation_sha256=canonical_sha256(observation),
        method_inventory_sha256=observation.method_inventory_sha256,
        llm_arm_policies_sha256=observation.llm_arm_policies_sha256,
        verified_gate_ids=tuple(verified_gate_ids),
        blocked_adapter_ids=tuple([*unknown_adapters, *blocked_adapters]),
        blocker_codes=tuple(reasons),
    )


__all__ = [
    "BENCHMARK_PILOT_READINESS_POLICY_VERSION",
    "BENCHMARK_PILOT_READINESS_SCHEMA_ID",
    "BenchmarkPilotGateReceiptV1",
    "BenchmarkPilotReadinessObservationV1",
    "BenchmarkPilotReadinessReceiptV1",
    "assess_benchmark_pilot_readiness",
]
