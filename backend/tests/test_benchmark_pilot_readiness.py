from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.benchmarking.composite_inventory import CompositeExecutionVerificationReceiptV1
from app.benchmarking.contracts import canonical_sha256
from app.benchmarking.llm_arm_contracts import BENCHMARK_LLM_ARM_POLICIES_SHA256
from app.benchmarking.method_inventory import BENCHMARK_METHOD_INVENTORY_SHA256
from app.benchmarking.physical_stability_assessment import (
    PhysicalStabilityAssessmentV1,
    PhysicalStabilityScenarioAssessmentV1,
)
from app.benchmarking.pilot_readiness import (
    BenchmarkPilotGateReceiptV1,
    BenchmarkPilotReadinessObservationV1,
    assess_benchmark_pilot_readiness,
)

_SHA = "a" * 64
_SUBJECT = "1" * 40
_GATES = (
    "campaign-coordinator",
    "sealed-qualification",
    "provider-accounting",
    "statistical-preregistration",
    "composite-inventory",
    "current-exact-quality",
    "physical-stability",
    "final-scenario-freeze",
)


def _gate(
    gate_id: str,
    *,
    status: str = "passed",
    subject: str = _SUBJECT,
    evidence_sha256: str = "3" * 64,
):
    payload = {
        "schema_id": "dronedream.benchmark-pilot-gate-receipt/v1",
        "gate_id": gate_id,
        "repository_subject_commit": subject,
        "status": status,
        "contract_sha256": "2" * 64,
        "evidence_sha256": evidence_sha256,
        "receipt_file_sha256": "4" * 64,
        "issued_at_utc": datetime(2026, 8, 5, tzinfo=timezone.utc),
        "physical_trials_attempted": 60 if gate_id == "physical-stability" else 0,
        "provider_network_requests_attempted": 0,
        "current_exact": True,
    }
    binding_payload = dict(payload)
    binding_payload["issued_at_utc"] = payload["issued_at_utc"].isoformat().replace(
        "+00:00", "Z"
    )
    payload["binding_sha256"] = canonical_sha256(binding_payload)
    return BenchmarkPilotGateReceiptV1.model_validate(payload)


def _assessment(*, ready: bool = True, subject: str = _SUBJECT):
    scenarios = tuple(
        PhysicalStabilityScenarioAssessmentV1(
            scenario_id=f"scenario-{index}",
            terminal_status_counts={"completed": 10},
            completed_count=10,
            pass_count=5,
            safety_critical_failure_count=0,
            effect_applied_and_read_back_count=10,
            parameter_readback_verified_count=10,
            complete_evidence_count=10,
            rmse_median=0.5,
            rmse_normalized_mad=0.1,
            max_error_median=1.0,
            max_error_normalized_mad=0.1,
            physical_contract_passed=True,
            repeatability_passed=True,
            difficulty_signal="graded",
            final_candidate_status="eligible_for_final_freeze",
            rejection_reasons=(),
        )
        for index in range(6)
    )
    return PhysicalStabilityAssessmentV1(
        manifest_sha256="5" * 64,
        plan_sha256="6" * 64,
        repository_subject_commit=subject,
        composite_execution_inventory_sha256="7" * 64,
        terminal_status_counts={"completed": 60},
        scenarios=scenarios,
        eligible_scenario_ids=tuple(item.scenario_id for item in scenarios),
        pilot_selection_ready=ready,
        all_preregistered_candidates_eligible=True,
    )


def _composite(*, verified: bool = True):
    return CompositeExecutionVerificationReceiptV1(
        status="verified" if verified else "denied",
        compatible=verified,
        inventory_sha256="7" * 64,
        observation_sha256="8" * 64,
        compatibility_summary_sha256="9" * 64,
        verification_contract_sha256="b" * 64,
        verified_component_ids=("runtime-base", "engine-pack") if verified else (),
        reason_codes=() if verified else ("runtime-engine-mismatch",),
    )


def _observation(
    *,
    required_adapter_ids=("random_search/v1", "optimizer_portfolio/v1"),
    gates=None,
    assessment=None,
    composite=None,
):
    effective_assessment = _assessment() if assessment is None else assessment
    effective_composite = _composite() if composite is None else composite
    campaign_manifest_sha256 = "d" * 64
    final_scenario_manifest_sha256 = "c" * 64
    effective_gates = (
        tuple(
            _gate(
                gate_id,
                evidence_sha256=(
                    campaign_manifest_sha256
                    if gate_id == "campaign-coordinator"
                    else canonical_sha256(effective_composite)
                    if gate_id == "composite-inventory"
                    else canonical_sha256(effective_assessment)
                    if gate_id == "physical-stability"
                    else final_scenario_manifest_sha256
                    if gate_id == "final-scenario-freeze"
                    else "3" * 64
                ),
            )
            for gate_id in _GATES
        )
        if gates is None
        else gates
    )
    return BenchmarkPilotReadinessObservationV1(
        repository_subject_commit=_SUBJECT,
        method_inventory_sha256=BENCHMARK_METHOD_INVENTORY_SHA256,
        llm_arm_policies_sha256=BENCHMARK_LLM_ARM_POLICIES_SHA256,
        campaign_manifest_sha256=campaign_manifest_sha256,
        required_adapter_ids=required_adapter_ids,
        required_adapter_set_sha256=canonical_sha256(sorted(required_adapter_ids)),
        gate_receipts=effective_gates,
        composite_verification=effective_composite,
        physical_stability_assessment=effective_assessment,
        final_scenario_manifest_sha256=final_scenario_manifest_sha256,
        observation_adapter_receipt_sha256=_SHA,
    )


def test_ready_only_means_ready_to_request_separate_batch_approval() -> None:
    receipt = assess_benchmark_pilot_readiness(_observation())

    assert receipt.status == "ready_for_batch_approval"
    assert receipt.ready_for_provider_batch_approval is True
    assert receipt.execution_authorized is False
    assert receipt.separate_provider_batch_approval_required is True
    assert receipt.verified_gate_ids == _GATES


def test_current_registry_blocks_unimplemented_reference_and_llm_arms() -> None:
    receipt = assess_benchmark_pilot_readiness(
        _observation(required_adapter_ids=("optuna_tpe/v1", "llm_direct/v1"))
    )

    assert receipt.status == "blocked"
    assert receipt.blocked_adapter_ids == ("llm_direct/v1", "optuna_tpe/v1")
    assert "blocked-adapter:llm_direct/v1" in receipt.blocker_codes
    assert "blocked-adapter:optuna_tpe/v1" in receipt.blocker_codes


def test_non_passed_or_subject_drifted_gate_fails_closed() -> None:
    gates = tuple(
        _gate(
            gate_id,
            status="not_run" if gate_id == "physical-stability" else "passed",
            evidence_sha256=(
                canonical_sha256(_assessment())
                if gate_id == "physical-stability"
                else "d" * 64
                if gate_id == "campaign-coordinator"
                else canonical_sha256(_composite())
                if gate_id == "composite-inventory"
                else "c" * 64
                if gate_id == "final-scenario-freeze"
                else "3" * 64
            ),
        )
        for gate_id in _GATES
    )
    receipt = assess_benchmark_pilot_readiness(_observation(gates=gates))
    assert "gate-not-passed:physical-stability:not_run" in receipt.blocker_codes

    drifted = tuple(
        _gate(
            gate_id,
            subject="f" * 40 if gate_id == "current-exact-quality" else _SUBJECT,
            evidence_sha256=(
                "d" * 64
                if gate_id == "campaign-coordinator"
                else canonical_sha256(_composite())
                if gate_id == "composite-inventory"
                else canonical_sha256(_assessment())
                if gate_id == "physical-stability"
                else "c" * 64
                if gate_id == "final-scenario-freeze"
                else "3" * 64
            ),
        )
        for gate_id in _GATES
    )
    receipt = assess_benchmark_pilot_readiness(_observation(gates=drifted))
    assert "gate-subject-drift:current-exact-quality" in receipt.blocker_codes


def test_incomplete_physical_assessment_or_composite_denial_fails_closed() -> None:
    receipt = assess_benchmark_pilot_readiness(
        _observation(assessment=_assessment(ready=False), composite=_composite(verified=False))
    )
    assert "physical-stability-not-ready" in receipt.blocker_codes
    assert "composite-inventory-not-verified" in receipt.blocker_codes
    assert "composite-inventory-incompatible" in receipt.blocker_codes


def test_gate_receipt_rejects_tamper_duplicate_ids_and_nonzero_provider_use() -> None:
    payload = _gate("physical-stability").model_dump(mode="python")
    payload["physical_trials_attempted"] = 59
    with pytest.raises(ValueError, match="binding hash"):
        BenchmarkPilotGateReceiptV1.model_validate(payload)

    duplicate = tuple(_gate("campaign-coordinator") for _ in _GATES)
    with pytest.raises(ValueError, match="must be unique"):
        _observation(gates=duplicate)

    payload = _gate("physical-stability").model_dump(mode="python")
    payload["provider_network_requests_attempted"] = 1
    binding_payload = {
        key: value for key, value in payload.items() if key != "binding_sha256"
    }
    binding_payload["issued_at_utc"] = payload["issued_at_utc"].isoformat().replace(
        "+00:00", "Z"
    )
    payload["binding_sha256"] = canonical_sha256(binding_payload)
    with pytest.raises(ValueError, match="zero-provider"):
        BenchmarkPilotGateReceiptV1.model_validate(payload)


def test_cross_object_hash_mismatches_fail_closed() -> None:
    gates = list(_observation().gate_receipts)
    scenario_index = next(
        index for index, gate in enumerate(gates) if gate.gate_id == "final-scenario-freeze"
    )
    gates[scenario_index] = _gate(
        "final-scenario-freeze", evidence_sha256="e" * 64
    )
    receipt = assess_benchmark_pilot_readiness(_observation(gates=tuple(gates)))

    assert "final-scenario-manifest-receipt-mismatch" in receipt.blocker_codes
