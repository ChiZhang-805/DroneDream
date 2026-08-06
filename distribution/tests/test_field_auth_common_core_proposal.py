from __future__ import annotations

import hashlib
import json
import subprocess
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


def _git_sha256(commit: str, path: str) -> str:
    content = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(content).hexdigest()


def test_proposal_records_the_exact_universal_auth_binding_conflict() -> None:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    conflict = proposal["conflict"]
    identity = ROOT / conflict["identityContractPath"]
    observed_head = proposal["observedUniversalHead"]
    auth_bytes = subprocess.run(
        ["git", "-C", str(ROOT), "show", f'{observed_head}:{conflict["authContractPath"]}'],
        check=True,
        capture_output=True,
    ).stdout
    auth_document = json.loads(auth_bytes.decode("utf-8"))

    assert _sha256(identity) == conflict["identityContractActualSha256"]
    assert _git_sha256(observed_head, conflict["authContractPath"]) == conflict[
        "authContractSha256"
    ]
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
