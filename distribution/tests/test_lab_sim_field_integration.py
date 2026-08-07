from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from verify_lab_sim_field_integration import (  # noqa: E402
    COMMON_CORE_COMMIT,
    FIELD_PRODUCT_SOURCE,
    FIELD_PRODUCT_TREE,
    LabSimFieldIntegrationError,
    validate_audit,
    validate_contract,
    verify_audit,
    verify_contract,
)


def test_lab_accepts_exact_field_donor_as_recorded_evidence_only() -> None:
    contract = verify_contract()
    audit = verify_audit()

    assert contract["integrationState"] == "field-donor-accepted-sim-donor-pending"
    assert contract["fieldDonor"]["productSource"] == FIELD_PRODUCT_SOURCE
    assert contract["fieldDonor"]["tree"] == FIELD_PRODUCT_TREE
    assert contract["fieldDonor"]["commonCoreCommit"] == COMMON_CORE_COMMIT
    assert contract["fieldDonor"]["fieldSourceCopiedIntoLab"] is False
    assert contract["fieldInput"]["envelopeKind"] == (
        "dronedream-field-harness-job-receipt"
    )
    assert contract["fieldInput"]["receiptHardwareAuthority"] is False
    assert audit["semanticFindings"]["fieldNoSimulationInstallerPolicyAppliedToLab"] is False
    assert audit["semanticFindings"]["labRetainsSimulationPayload"] is True


def test_lab_owns_bridge_without_forking_common_core() -> None:
    contract = verify_contract()

    assert contract["principles"]["reuseMatureEditionModules"] is True
    assert contract["principles"]["manualCodeCopyAllowed"] is False
    assert contract["principles"]["crossEditionHarnessOrchestrator"] is False
    assert contract["join"]["sameLabJobRequired"] is True


def test_metric_mismatch_requires_an_explicit_normalization_receipt() -> None:
    metrics = verify_contract()["metricCompatibility"]

    assert metrics["fieldMetrics"] != metrics["labCalibrationMetrics"]
    assert metrics["directMappingAllowed"] is False
    assert metrics["normalizationReceiptRequired"] is True
    assert metrics["missingNormalizationDecision"] == "deny"


def test_lab_stays_denied_until_sim_metrics_packs_and_quorum_are_ready() -> None:
    contract = verify_contract()

    assert contract["currentGate"] == {
        "validatedVehiclePackCount": 0,
        "simDonorAccepted": False,
        "fieldDonorAccepted": True,
        "fieldEvidenceAdapterState": "accepted-offline-recorded-evidence-only",
        "jobBindingDecision": "deny",
        "metricNormalizationDecision": "deny",
        "hardwareExecutionDecision": "deny",
        "qualificationIssueDecision": "deny",
        "fieldHandoffDecision": "deny",
    }


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("fieldDonor", "productSource", "0" * 40),
        ("fieldDonor", "fieldSourceCopiedIntoLab", True),
        ("principles", "manualCodeCopyAllowed", True),
        ("principles", "crossEditionHarnessOrchestrator", True),
        ("simInput", "hardwareAuthority", True),
        ("fieldInput", "receiptHardwareAuthority", True),
        ("metricCompatibility", "directMappingAllowed", True),
        ("metricCompatibility", "missingNormalizationDecision", "allow"),
        ("join", "replayDecision", "allow"),
        ("currentGate", "hardwareExecutionDecision", "allow"),
        ("currentGate", "simDonorAccepted", True),
        ("currentGate", "fieldDonorAccepted", False),
    ],
)
def test_lab_integration_rejects_drift(section: str, key: str, value: object) -> None:
    contract = copy.deepcopy(verify_contract())
    contract[section][key] = value

    with pytest.raises(LabSimFieldIntegrationError):
        validate_contract(contract)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("fieldDonor", "productSource", "f" * 40),
        ("semanticFindings", "hardwareValidationClaimed", True),
        ("semanticFindings", "fieldSourceCopiedIntoLab", True),
        ("semanticFindings", "fieldNoSimulationInstallerPolicyAppliedToLab", True),
        ("decision", "realToSimCalibration", "allow"),
        ("decision", "hardwareWrite", "allow"),
    ],
)
def test_field_donor_audit_rejects_unsafe_claims(
    section: str,
    key: str,
    value: object,
) -> None:
    audit = copy.deepcopy(verify_audit())
    audit[section][key] = value

    with pytest.raises(LabSimFieldIntegrationError):
        validate_audit(audit)
