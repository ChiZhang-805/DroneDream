from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "proposals"
    / "universal-auth-coexistence-binding-fix-v1.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_proposal_records_the_exact_universal_auth_binding_conflict() -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    conflict = proposal["conflict"]
    identity = ROOT / conflict["identityContractPath"]
    auth = ROOT / conflict["authContractPath"]
    auth_document = json.loads(auth.read_text(encoding="utf-8"))

    assert _sha256(identity) == conflict["identityContractActualSha256"]
    assert _sha256(auth) == conflict["authContractSha256"]
    assert (
        auth_document["identityBinding"]["contractSha256"]
        == conflict["authBoundIdentitySha256"]
    )
    assert conflict["identityContractActualSha256"] != conflict["authBoundIdentitySha256"]
    assert conflict["fieldRuntimeProfileRequired"] == "field-lightweight"


def test_proposal_keeps_field_fail_closed_without_forking_common_auth() -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    boundary = proposal["fieldBoundary"]
    assert boundary == {
        "sharedPathPatchedOnField": False,
        "releaseBuildAllowed": False,
        "installAllowed": False,
        "providerUseAllowed": False,
        "hardwareAllowed": False,
        "validatedHardwarePackCount": 0,
        "resumeCondition": (
            "consume an exact clean Universal product commit whose auth binding "
            "matches the field-lightweight coexistence contract"
        ),
    }
