from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "distribution/editions/lab/sim-field-integration.v1.json"
SYNC_PATH = ROOT / "distribution/editions/lab/field-2f8fa285-capability-sync.v1.json"
HISTORICAL_AUDIT_PATH = (
    ROOT / "distribution/editions/lab/field-45e897fa-evidence-bridge-audit.v1.json"
)
SIM_PRODUCT_SOURCE = "ef70567fe4c34f261fc9f16defb6e98e95f337dc"
SIM_PRODUCT_TREE = "c102508870dcc98e534e1f4e51696bfed77ff18b"
SIM_MODEL_HARNESS_SOURCE = "38731d530fdf3bfed6dde43167856f9c6b4a5d67"
FIELD_PRODUCT_SOURCE = "2f8fa28564dab7b1ff264c853705535373cb9068"
FIELD_PRODUCT_TREE = "afb7b4db584bf71e03d2f0b707b8b992e96bc7e7"
FIELD_AUTH_SOURCE = "1129b561a187edf9ddb3214f3e8c993be31f281b"
COMMON_CORE_COMMIT = "e374d3f8d96b1265fcdb06864208b676566e94d9"


class LabSimFieldIntegrationError(ValueError):
    pass


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabSimFieldIntegrationError(f"{label} must be an object")
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        return _mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabSimFieldIntegrationError(f"cannot read {path}: {exc}") from exc


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("schemaVersion") != 1
        or contract.get("kind") != "dronedream-lab-sim-field-integration"
        or contract.get("editionId") != "lab"
        or contract.get("integrationState") != "sim-and-field-capabilities-integrated"
    ):
        raise LabSimFieldIntegrationError("Lab integration identity drifted")

    sim = _mapping(contract.get("simDonor"), "simDonor")
    if (
        sim.get("productSource") != SIM_PRODUCT_SOURCE
        or sim.get("tree") != SIM_PRODUCT_TREE
        or sim.get("modelHarnessFeatureSource") != SIM_MODEL_HARNESS_SOURCE
        or sim.get("integrationMode") != "path-limited-semantic-forward-sync"
        or sim.get("standaloneSimShellCopiedIntoLab") is not False
        or sim.get("sharedCoreForkCreated") is not False
    ):
        raise LabSimFieldIntegrationError("SIM donor binding drifted")

    field = _mapping(contract.get("fieldDonor"), "fieldDonor")
    if (
        field.get("productSource") != FIELD_PRODUCT_SOURCE
        or field.get("tree") != FIELD_PRODUCT_TREE
        or field.get("authWireContractSource") != FIELD_AUTH_SOURCE
        or field.get("commonCoreCommit") != COMMON_CORE_COMMIT
        or field.get("integrationMode") != "path-limited-semantic-forward-sync"
        or field.get("fieldStandaloneShellCopiedIntoLab") is not False
        or field.get("fieldNoSimulationInstallerPolicyAppliedToLab") is not False
        or field.get("sharedCoreForkCreated") is not False
        or field.get("syncReceipt") != SYNC_PATH.relative_to(ROOT).as_posix()
    ):
        raise LabSimFieldIntegrationError("FIELD donor binding drifted")

    principles = _mapping(contract.get("principles"), "principles")
    for key in (
        "reuseMatureEditionModules",
        "pathLimitedForwardSyncRequired",
        "exactDonorCommitRequired",
        "labOwnsBidirectionalCalibration",
    ):
        if principles.get(key) is not True:
            raise LabSimFieldIntegrationError(f"integration requirement missing: {key}")
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
        sim_input.get("donorState") != "accepted-exact-product-source"
        or sim_input.get("productSource") != SIM_PRODUCT_SOURCE
        or sim_input.get("hardwareAuthority") is not False
        or field_input.get("receiptHardwareAuthority") is not False
        or field_input.get("liveHardwareAuthority")
        != "external-native-backend-runtime-quorum-only"
    ):
        raise LabSimFieldIntegrationError("evidence authority boundary drifted")

    metrics = _mapping(contract.get("metricCompatibility"), "metricCompatibility")
    if (
        metrics.get("directMappingAllowed") is not False
        or metrics.get("normalizationReceiptRequired") is not True
        or metrics.get("missingNormalizationDecision") != "deny"
    ):
        raise LabSimFieldIntegrationError("metric normalization drifted")

    join = _mapping(contract.get("join"), "join")
    if join.get("sameLabJobRequired") is not True:
        raise LabSimFieldIntegrationError("SIM and FIELD evidence must share one Lab job")
    for key in (
        "mismatchDecision",
        "unboundEvidenceDecision",
        "replayDecision",
        "crossJobEvidenceDecision",
    ):
        if join.get(key) != "deny":
            raise LabSimFieldIntegrationError(f"join must deny {key}")

    gate = _mapping(contract.get("currentGate"), "currentGate")
    if (
        gate.get("validatedVehiclePackCount") != 0
        or gate.get("simDonorAccepted") is not True
        or gate.get("fieldDonorAccepted") is not True
        or gate.get("jobBindingDecision") != "conditional-exact-match"
        or gate.get("metricNormalizationDecision") != "explicit-receipt-required"
        or gate.get("hardwareExecutionDecision") != "deny"
        or gate.get("qualificationIssueDecision") != "deny"
        or gate.get("fieldHandoffDecision") != "draft-only"
    ):
        raise LabSimFieldIntegrationError("current integration gate drifted")
    return contract


def validate_sync(sync: dict[str, Any]) -> dict[str, Any]:
    donor = _mapping(sync.get("donor"), "sync.donor")
    adaptation = _mapping(sync.get("labAdaptations"), "sync.labAdaptations")
    if (
        sync.get("schemaVersion") != 1
        or sync.get("kind") != "dronedream-lab-field-capability-donor-sync"
        or sync.get("editionId") != "lab"
        or donor.get("productSource") != FIELD_PRODUCT_SOURCE
        or donor.get("tree") != FIELD_PRODUCT_TREE
        or donor.get("authWireContractSource") != FIELD_AUTH_SOURCE
        or adaptation.get("compiledEditionId") != "lab"
        or adaptation.get("runtimeProfile") != "unified-sim-lab"
        or adaptation.get("fieldInstallerPolicyIncluded") is not False
        or adaptation.get("fieldBrandIncluded") is not False
        or adaptation.get("labSimulationPayloadRetained") is not True
        or adaptation.get("hardwareAuthority") is not False
        or adaptation.get("validatedVehiclePackCount") != 0
    ):
        raise LabSimFieldIntegrationError("FIELD sync receipt drifted")
    for entry in sync.get("exactContractAssets", []):
        item = _mapping(entry, "exactContractAsset")
        path = ROOT / str(item.get("path"))
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256")
        ):
            raise LabSimFieldIntegrationError(f"exact donor asset drifted: {path}")
    return sync


def verify_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return validate_contract(_load(path))


def verify_sync(path: Path = SYNC_PATH) -> dict[str, Any]:
    return validate_sync(_load(path))


def verify_audit(path: Path = HISTORICAL_AUDIT_PATH) -> dict[str, Any]:
    audit = _load(path)
    if audit.get("kind") != "dronedream-lab-field-donor-audit":
        raise LabSimFieldIntegrationError("historical Field audit identity drifted")
    return audit


if __name__ == "__main__":
    contract = verify_contract()
    verify_sync()
    print(json.dumps({"state": contract["integrationState"], **contract["currentGate"]}))
