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
    LabSimFieldIntegrationError,
    validate_contract,
    verify_contract,
)


def test_lab_waits_for_exact_donors_and_owns_only_the_bidirectional_bridge() -> None:
    contract = verify_contract()

    assert contract["principles"]["reuseMatureEditionModules"] is True
    assert contract["principles"]["manualCodeCopyAllowed"] is False
    assert contract["principles"]["crossEditionHarnessOrchestrator"] is False
    assert contract["simInput"]["hardwareAuthority"] is False
    assert contract["fieldInput"]["hardwareAuthority"] == (
        "external-native-backend-runtime-quorum-only"
    )
    assert contract["join"]["sameLabJobRequired"] is True


def test_lab_integration_stays_denied_until_both_donors_and_packs_are_accepted() -> None:
    contract = verify_contract()

    assert contract["currentGate"] == {
        "validatedVehiclePackCount": 0,
        "simDonorAccepted": False,
        "fieldDonorAccepted": False,
        "hardwareExecutionDecision": "deny",
        "qualificationIssueDecision": "deny",
        "fieldHandoffDecision": "deny",
    }


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("principles", "manualCodeCopyAllowed", True),
        ("principles", "crossEditionHarnessOrchestrator", True),
        ("simInput", "hardwareAuthority", True),
        ("join", "replayDecision", "allow"),
        ("currentGate", "hardwareExecutionDecision", "allow"),
        ("currentGate", "simDonorAccepted", True),
    ],
)
def test_lab_integration_rejects_drift(section: str, key: str, value: object) -> None:
    contract = copy.deepcopy(verify_contract())
    contract[section][key] = value

    with pytest.raises(LabSimFieldIntegrationError):
        validate_contract(contract)
