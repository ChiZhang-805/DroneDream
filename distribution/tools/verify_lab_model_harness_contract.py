from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT / "distribution" / "editions" / "lab" / "model-harness-closed-loop.v1.json"
)

DENIED_HARDWARE_ACTIONS = (
    "hardware.parameter.write",
    "hardware.arm",
    "hardware.flight",
    "hardware.hitl.execute",
)
REQUIRED_AUTHORITY_LAYERS = (
    "native",
    "backend",
    "runtime",
    "validated-vehicle-pack",
    "operator-confirmation",
)
REQUIRED_PHASES = (
    "objective-and-constraints",
    "simulation-search",
    "simulation-qualification",
    "controlled-real-observation",
    "sim-real-gap-analysis",
    "real-sim-model-calibration",
    "resimulation",
    "independent-holdout",
    "qualification-and-evidence",
    "field-handoff",
)


class LabModelHarnessContractError(ValueError):
    pass


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabModelHarnessContractError(f"{label} must be an object")
    return value


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("schemaVersion") != 1
        or contract.get("kind") != "dronedream-lab-model-harness-closed-loop"
        or contract.get("editionId") != "lab"
    ):
        raise LabModelHarnessContractError("Lab Model + Harness identity drifted")

    positioning = _object(contract.get("positioning"), "positioning")
    if positioning.get("notSimpleFeatureUnion") is not True:
        raise LabModelHarnessContractError("Lab must not be described as a simple feature union")

    boundary = _object(contract.get("jobBoundary"), "jobBoundary")
    if boundary.get("sameJobRequired") is not True:
        raise LabModelHarnessContractError("the bidirectional loop must remain in one job")
    for key in (
        "crossEditionHarnessOrchestrator",
        "modelCanAuthorizeExecution",
        "workspaceSwitchInvokesModelOrHarness",
        "workspaceSwitchGrantsHardwareAuthority",
    ):
        if boundary.get(key) is not False:
            raise LabModelHarnessContractError(f"unsafe job boundary: {key}")

    roles = _object(contract.get("roles"), "roles")
    if tuple(roles.get("hardwareAuthority", ())) != REQUIRED_AUTHORITY_LAYERS:
        raise LabModelHarnessContractError("hardware authority quorum drifted")
    if "propose-next-parameter-candidate" not in roles.get("model", ()):
        raise LabModelHarnessContractError("Model proposal role is missing")
    if "enforce-independent-holdout" not in roles.get("harness", ()):
        raise LabModelHarnessContractError("Harness holdout role is missing")

    if tuple(contract.get("phases", ())) != REQUIRED_PHASES:
        raise LabModelHarnessContractError("Lab closed-loop phases drifted")

    qualification = _object(contract.get("qualification"), "qualification")
    for key in (
        "requiresIndependentHoldout",
        "requiresGapWithinTolerance",
        "requiresValidatedVehiclePack",
        "requiresNativeBackendRuntimeQuorum",
        "requiresOperatorConfirmationForHardware",
    ):
        if qualification.get(key) is not True:
            raise LabModelHarnessContractError(f"qualification gate is missing: {key}")
    for key in ("importedEvidenceGrantsAuthority", "frontendCanIssueTrustedQualification"):
        if qualification.get(key) is not False:
            raise LabModelHarnessContractError(f"unsafe qualification authority: {key}")

    safety = _object(contract.get("currentSafetyState"), "currentSafetyState")
    if safety.get("validatedVehiclePackCount") != 0:
        raise LabModelHarnessContractError("validated Vehicle Pack count must remain zero")
    if safety.get("hardwareExecutionDecision") != "deny":
        raise LabModelHarnessContractError("hardware execution must fail closed")
    if tuple(safety.get("deniedActions", ())) != DENIED_HARDWARE_ACTIONS:
        raise LabModelHarnessContractError("hardware deny action set drifted")

    receipt = _object(contract.get("receiptPolicy"), "receiptPolicy")
    for key in (
        "canonicalJsonRequired",
        "sourceHashesRequired",
        "releaseRequiresSignedQualificationReceipt",
        "releaseRequiresExactSource",
    ):
        if receipt.get(key) is not True:
            raise LabModelHarnessContractError(f"receipt requirement is missing: {key}")
    for key in ("draftReceiptTrusted", "draftReceiptGrantsHardwareAuthority"):
        if receipt.get(key) is not False:
            raise LabModelHarnessContractError(f"draft receipt overstates authority: {key}")

    presentation = _object(contract.get("presentation"), "presentation")
    if presentation.get("themeTokens") != ["#A7E84A", "#20C77A", "#087E69"]:
        raise LabModelHarnessContractError("canonical Lab theme tokens drifted")
    if (
        presentation.get("presentationOnly") is not True
        or presentation.get("grantsHardwareAuthority") is not False
    ):
        raise LabModelHarnessContractError("presentation must not grant authority")
    return contract


def verify_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return validate_contract(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    verified = verify_contract()
    print(
        json.dumps(
            {
                "editionId": verified["editionId"],
                "phaseCount": len(verified["phases"]),
                "hardwareExecutionDecision": verified["currentSafetyState"][
                    "hardwareExecutionDecision"
                ],
            },
            separators=(",", ":"),
        )
    )
