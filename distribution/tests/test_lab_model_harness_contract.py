from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from verify_lab_model_harness_contract import (  # noqa: E402
    LabModelHarnessContractError,
    validate_contract,
    verify_contract,
)


def test_lab_contract_defines_one_bidirectional_job_without_cross_edition_scheduler() -> None:
    contract = verify_contract()

    assert contract["positioning"]["notSimpleFeatureUnion"] is True
    assert contract["jobBoundary"] == {
        "sameJobRequired": True,
        "crossEditionHarnessOrchestrator": False,
        "modelCanAuthorizeExecution": False,
        "workspaceSwitchInvokesModelOrHarness": False,
        "workspaceSwitchGrantsHardwareAuthority": False,
    }
    assert contract["phases"][0] == "objective-and-constraints"
    assert contract["phases"][-1] == "field-handoff"
    assert "real-sim-model-calibration" in contract["phases"]
    assert "independent-holdout" in contract["phases"]


def test_lab_contract_keeps_zero_pack_hardware_actions_fail_closed() -> None:
    contract = verify_contract()

    assert contract["currentSafetyState"]["validatedVehiclePackCount"] == 0
    assert contract["currentSafetyState"]["hardwareExecutionDecision"] == "deny"
    assert contract["qualification"]["frontendCanIssueTrustedQualification"] is False
    assert contract["qualification"]["importedEvidenceGrantsAuthority"] is False


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("jobBoundary", "sameJobRequired"), False, "one job"),
        (("jobBoundary", "crossEditionHarnessOrchestrator"), True, "unsafe job boundary"),
        (("jobBoundary", "modelCanAuthorizeExecution"), True, "unsafe job boundary"),
        (("qualification", "frontendCanIssueTrustedQualification"), True, "authority"),
        (("currentSafetyState", "validatedVehiclePackCount"), 1, "must remain zero"),
        (("currentSafetyState", "hardwareExecutionDecision"), "allow", "fail closed"),
        (("presentation", "grantsHardwareAuthority"), True, "presentation"),
    ],
)
def test_lab_contract_rejects_authority_and_positioning_drift(
    path: tuple[str, str], value: object, message: str
) -> None:
    contract = copy.deepcopy(verify_contract())
    contract[path[0]][path[1]] = value

    with pytest.raises(LabModelHarnessContractError, match=message):
        validate_contract(contract)
