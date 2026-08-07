from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "distribution/editions/lab/sim-field-integration.v1.json"


class LabSimFieldIntegrationError(ValueError):
    pass


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabSimFieldIntegrationError(f"{label} must be an object")
    return value


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("schemaVersion") != 1
        or contract.get("kind") != "dronedream-lab-sim-field-integration"
        or contract.get("editionId") != "lab"
        or contract.get("integrationState") != "awaiting-exact-sim-and-field-donors"
    ):
        raise LabSimFieldIntegrationError("Lab integration identity drifted")

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
    if sim_input.get("hardwareAuthority") is not False:
        raise LabSimFieldIntegrationError("SIM input must not grant hardware authority")
    if field_input.get("hardwareAuthority") != "external-native-backend-runtime-quorum-only":
        raise LabSimFieldIntegrationError("FIELD authority boundary drifted")
    for binding in (
        "commonCoreCommit",
        "vehiclePackId",
        "controllerIdentity",
        "firmwareIdentity",
    ):
        if binding not in sim_input.get("requiredBindings", ()):
            raise LabSimFieldIntegrationError(f"SIM binding is missing: {binding}")
        if binding not in field_input.get("requiredBindings", ()):
            raise LabSimFieldIntegrationError(f"FIELD binding is missing: {binding}")

    join = _mapping(contract.get("join"), "join")
    if join.get("sameLabJobRequired") is not True:
        raise LabSimFieldIntegrationError("SIM and FIELD evidence must join in one Lab job")
    for key in (
        "mismatchDecision",
        "unboundEvidenceDecision",
        "replayDecision",
        "crossJobEvidenceDecision",
    ):
        if join.get(key) != "deny":
            raise LabSimFieldIntegrationError(f"join must fail closed: {key}")

    outputs = contract.get("labOwnedOutputs")
    if not isinstance(outputs, list) or len(outputs) != 6 or len(set(outputs)) != len(outputs):
        raise LabSimFieldIntegrationError("Lab-owned output contract drifted")
    if not all(isinstance(item, str) and item.startswith("dronedream-lab-") for item in outputs):
        raise LabSimFieldIntegrationError("Lab output escaped the edition namespace")

    gate = _mapping(contract.get("currentGate"), "currentGate")
    if gate != {
        "validatedVehiclePackCount": 0,
        "simDonorAccepted": False,
        "fieldDonorAccepted": False,
        "hardwareExecutionDecision": "deny",
        "qualificationIssueDecision": "deny",
        "fieldHandoffDecision": "deny",
    }:
        raise LabSimFieldIntegrationError("current integration gate must remain denied")
    return contract


def verify_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return validate_contract(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    contract = verify_contract()
    print(json.dumps({"state": contract["integrationState"], **contract["currentGate"]}))
