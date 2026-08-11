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
    FIELD_PRODUCT_SOURCE,
    SIM_PRODUCT_SOURCE,
    LabSimFieldIntegrationError,
    validate_contract,
    validate_sync,
    verify_contract,
    verify_sync,
)


def test_exact_sim_and_field_donors_are_integrated_without_standalone_shells() -> None:
    contract = verify_contract()
    sync = verify_sync()

    assert contract["integrationState"] == "sim-and-field-capabilities-integrated"
    assert contract["simDonor"]["productSource"] == SIM_PRODUCT_SOURCE
    assert contract["fieldDonor"]["productSource"] == FIELD_PRODUCT_SOURCE
    assert contract["simDonor"]["standaloneSimShellCopiedIntoLab"] is False
    assert contract["fieldDonor"]["fieldStandaloneShellCopiedIntoLab"] is False
    assert sync["labAdaptations"]["fieldInstallerPolicyIncluded"] is False
    assert sync["labAdaptations"]["labSimulationPayloadRetained"] is True


def test_lab_owns_bidirectional_bridge_and_keeps_authority_denied() -> None:
    contract = verify_contract()
    gate = contract["currentGate"]

    assert contract["principles"]["labOwnsBidirectionalCalibration"] is True
    assert contract["join"]["sameLabJobRequired"] is True
    assert contract["metricCompatibility"]["normalizationReceiptRequired"] is True
    assert gate["validatedVehiclePackCount"] == 0
    assert gate["hardwareExecutionDecision"] == "deny"
    assert gate["qualificationIssueDecision"] == "deny"
    assert gate["fieldHandoffDecision"] == "draft-only"


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("simDonor", "productSource", "0" * 40),
        ("fieldDonor", "productSource", "0" * 40),
        ("fieldDonor", "fieldNoSimulationInstallerPolicyAppliedToLab", True),
        ("principles", "copyOrForkCommonCore", True),
        ("principles", "crossEditionHarnessOrchestrator", True),
        ("metricCompatibility", "directMappingAllowed", True),
        ("join", "replayDecision", "allow"),
        ("currentGate", "validatedVehiclePackCount", 1),
        ("currentGate", "hardwareExecutionDecision", "allow"),
        ("currentGate", "qualificationIssueDecision", "allow"),
    ],
)
def test_integration_contract_fails_closed(section: str, key: str, value: object) -> None:
    contract = copy.deepcopy(verify_contract())
    contract[section][key] = value
    with pytest.raises(LabSimFieldIntegrationError):
        validate_contract(contract)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("compiledEditionId", "field"),
        ("fieldBrandIncluded", True),
        ("fieldInstallerPolicyIncluded", True),
        ("labSimulationPayloadRetained", False),
        ("hardwareAuthority", True),
        ("validatedVehiclePackCount", 1),
    ],
)
def test_field_sync_adaptation_fails_closed(key: str, value: object) -> None:
    sync = copy.deepcopy(verify_sync())
    sync["labAdaptations"][key] = value
    with pytest.raises(LabSimFieldIntegrationError):
        validate_sync(sync)
