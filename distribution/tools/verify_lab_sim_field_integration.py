from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "distribution/editions/lab/sim-field-integration.v1.json"
AUDIT_PATH = (
    ROOT
    / "distribution/editions/lab/field-45e897fa-evidence-bridge-audit.v1.json"
)
FIELD_PRODUCT_SOURCE = "45e897faca6b48773f0a49d2f4d74ec67ae967fe"
FIELD_PRODUCT_TREE = "bd513282437004fde4464a33b498c5e98a01e5f3"
COMMON_CORE_COMMIT = "e374d3f8d96b1265fcdb06864208b676566e94d9"
FIELD_SURFACES = [
    {
        "path": "distribution/editions/field.v1.json",
        "bytes": 2936,
        "sha256": "cbd2c3a10843601469f91ef7d097c72459becaa6e60c387e39b721e76680bd08",
    },
    {
        "path": "distribution/editions/field/field-tuning-contract.v1.json",
        "bytes": 1988,
        "sha256": "141a29cc9425c3857ddcf477e41d168184095adc9c7031deb16ef474b40f8815",
    },
    {
        "path": "frontend/src/field/tuning.ts",
        "bytes": 4988,
        "sha256": "c95e1d80b76f5f1c9a92965394839610c3043df901c8764802159dc6e3abfcb7",
    },
    {
        "path": "desktop/src-tauri/src/field_harness.rs",
        "bytes": 29049,
        "sha256": "5154c102c68a7c20e8c1d0d7744e90973f903d4fa8fd347a1371fb4da570264e",
    },
]


class LabSimFieldIntegrationError(ValueError):
    pass


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabSimFieldIntegrationError(f"{label} must be an object")
    return value


def _require_denied(mapping: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
    for key in keys:
        if mapping.get(key) != "deny":
            raise LabSimFieldIntegrationError(f"{label} must fail closed: {key}")


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("schemaVersion") != 1
        or contract.get("kind") != "dronedream-lab-sim-field-integration"
        or contract.get("editionId") != "lab"
        or contract.get("integrationState")
        != "field-donor-accepted-sim-donor-pending"
    ):
        raise LabSimFieldIntegrationError("Lab integration identity drifted")

    donor = _mapping(contract.get("fieldDonor"), "fieldDonor")
    if donor != {
        "branch": "codex/software-field",
        "productSource": FIELD_PRODUCT_SOURCE,
        "tree": FIELD_PRODUCT_TREE,
        "commonCoreCommit": COMMON_CORE_COMMIT,
        "originExactAtHandoff": True,
        "integrationMode": "semantic-receipt-adapter",
        "fieldSourceCopiedIntoLab": False,
        "acceptedSurfaces": FIELD_SURFACES,
    }:
        raise LabSimFieldIntegrationError("Field donor identity or audited surfaces drifted")

    principles = _mapping(contract.get("principles"), "principles")
    for key in (
        "reuseMatureEditionModules",
        "pathLimitedForwardSyncRequired",
        "exactDonorCommitRequired",
        "labOwnsBidirectionalCalibration",
    ):
        if principles.get(key) is not True:
            raise LabSimFieldIntegrationError(f"integration requirement is missing: {key}")
    for key in (
        "copyOrForkCommonCore",
        "manualCodeCopyAllowed",
        "evidenceCommitMayBeProductSource",
        "crossEditionHarnessOrchestrator",
    ):
        if principles.get(key) is not False:
            raise LabSimFieldIntegrationError(f"unsafe integration policy: {key}")

    sim_input = _mapping(contract.get("simInput"), "simInput")
    field_input = _mapping(contract.get("fieldInput"), "fieldInput")
    if (
        sim_input.get("donorState") != "awaiting-exact-product-source"
        or sim_input.get("hardwareAuthority") is not False
    ):
        raise LabSimFieldIntegrationError("SIM donor or authority gate drifted")
    if (
        field_input.get("envelopeKind")
        != "dronedream-field-harness-job-receipt"
        or field_input.get("executionDomain")
        != "real-device-recorded-evidence"
        or field_input.get("executionMode")
        != "offline-evidence-replay-no-device-io"
        or field_input.get("receiptHardwareAuthority") is not False
        or field_input.get("liveHardwareAuthority")
        != "external-native-backend-runtime-quorum-only"
    ):
        raise LabSimFieldIntegrationError("FIELD receipt boundary drifted")
    for binding in (
        "sourceCommit",
        "enginePackId",
        "requestSha256",
        "observationSha256",
        "snapshotSha256",
        "vehiclePackId",
        "controllerId",
        "firmwareVersion",
        "selectedCandidateSha256",
        "holdoutTrialId",
        "receiptSha256",
    ):
        if binding not in field_input.get("requiredBindings", ()):
            raise LabSimFieldIntegrationError(f"FIELD binding is missing: {binding}")

    metrics = _mapping(contract.get("metricCompatibility"), "metricCompatibility")
    if (
        metrics.get("fieldMetrics")
        != [
            "trackingError",
            "overshootPercent",
            "controlEffort",
            "constraintViolations",
            "emergencyInterventions",
        ]
        or metrics.get("labCalibrationMetrics")
        != ["trackingRmseM", "maxErrorM", "energyWh", "overshootCount"]
        or metrics.get("directMappingAllowed") is not False
        or metrics.get("normalizationReceiptRequired") is not True
        or metrics.get("missingNormalizationDecision") != "deny"
    ):
        raise LabSimFieldIntegrationError("cross-domain metric normalization drifted")

    join = _mapping(contract.get("join"), "join")
    if join.get("sameLabJobRequired") is not True:
        raise LabSimFieldIntegrationError("SIM and FIELD evidence must join in one Lab job")
    _require_denied(
        join,
        (
            "mismatchDecision",
            "unboundEvidenceDecision",
            "replayDecision",
            "crossJobEvidenceDecision",
        ),
        "join",
    )

    outputs = contract.get("labOwnedOutputs")
    if not isinstance(outputs, list) or len(outputs) != 6 or len(set(outputs)) != len(outputs):
        raise LabSimFieldIntegrationError("Lab-owned output contract drifted")
    if not all(isinstance(item, str) and item.startswith("dronedream-lab-") for item in outputs):
        raise LabSimFieldIntegrationError("Lab output escaped the edition namespace")

    gate = _mapping(contract.get("currentGate"), "currentGate")
    if gate != {
        "validatedVehiclePackCount": 0,
        "simDonorAccepted": False,
        "fieldDonorAccepted": True,
        "fieldEvidenceAdapterState": "accepted-offline-recorded-evidence-only",
        "jobBindingDecision": "deny",
        "metricNormalizationDecision": "deny",
        "hardwareExecutionDecision": "deny",
        "qualificationIssueDecision": "deny",
        "fieldHandoffDecision": "deny",
    }:
        raise LabSimFieldIntegrationError("current integration gate must remain denied")
    return contract


def validate_audit(audit: dict[str, Any]) -> dict[str, Any]:
    if (
        audit.get("schemaVersion") != 1
        or audit.get("kind") != "dronedream-lab-field-donor-audit"
        or audit.get("editionId") != "lab"
        or audit.get("auditMode") != "read-only-path-level"
    ):
        raise LabSimFieldIntegrationError("Field donor audit identity drifted")
    donor = _mapping(audit.get("fieldDonor"), "audit.fieldDonor")
    if donor != {
        "branch": "codex/software-field",
        "productSource": FIELD_PRODUCT_SOURCE,
        "tree": FIELD_PRODUCT_TREE,
        "commonCoreCommit": COMMON_CORE_COMMIT,
        "originExactAtHandoff": True,
    }:
        raise LabSimFieldIntegrationError("Field donor audit source drifted")
    findings = _mapping(audit.get("semanticFindings"), "semanticFindings")
    if (
        findings.get("acceptedReceiptKind")
        != "dronedream-field-harness-job-receipt"
        or findings.get("recordedEvidenceOnly") is not True
        or findings.get("hardwareValidationClaimed") is not False
        or findings.get("fieldSourceCopiedIntoLab") is not False
        or findings.get("fieldNoSimulationInstallerPolicyAppliedToLab") is not False
        or findings.get("labRetainsSimulationPayload") is not True
    ):
        raise LabSimFieldIntegrationError("Field semantic audit drifted")
    _require_denied(
        _mapping(audit.get("decision"), "decision"),
        (
            "simToRealCalibration",
            "realToSimCalibration",
            "qualificationIssue",
            "hardwareWrite",
            "unlock",
            "arm",
            "flight",
        ),
        "audit decision",
    )
    return audit


def verify_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return validate_contract(json.loads(path.read_text(encoding="utf-8")))


def verify_audit(path: Path = AUDIT_PATH) -> dict[str, Any]:
    return validate_audit(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    contract = verify_contract()
    verify_audit()
    print(json.dumps({"state": contract["integrationState"], **contract["currentGate"]}))
