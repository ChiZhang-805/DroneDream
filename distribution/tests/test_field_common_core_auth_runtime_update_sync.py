from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECEIPT = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "receipts"
    / "common-core-auth-runtime-update-sync-v1.json"
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_receipt_binds_exact_product_donors_and_common_profile_dependencies() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["kind"] == "dronedream-field-common-core-auth-runtime-update-sync-receipt"
    product_source = receipt["productSource"]["commit"]
    assert _git("merge-base", "--is-ancestor", product_source, "HEAD") == ""
    for donor in receipt["canonicalProductDonors"]:
        assert _git("merge-base", "--is-ancestor", donor["integrationCommit"], "HEAD") == ""

    dependency = receipt["commonProfileDependencySync"]
    assert dependency["pathCount"] == len(dependency["paths"]) == 18
    assert dependency["benchmarkPathsConsumed"] is False
    for path in dependency["paths"]:
        assert _git("rev-parse", f'{dependency["canonicalCommit"]}:{path}') == _git(
            "rev-parse", f"{product_source}:{path}"
        )

    union = receipt["sharedDonorUnionAudit"]
    paths = _git("diff", "--name-only", union["baseCommit"], union["tipCommit"]).splitlines()
    assert len(paths) == union["pathCount"] == 38
    for path in paths:
        assert _git("rev-parse", f'{union["tipCommit"]}:{path}') == _git(
            "rev-parse", f"{product_source}:{path}"
        )


def test_receipt_binds_field_namespaces_brand_and_unresolved_auth_blocker() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    field = receipt["fieldBindings"]
    assert field["runtimeProfileId"] == "field-lightweight"
    assert field["compiledEditionId"] == "field"
    assert field["authClientId"] == "dronedream-desktop-field"
    assert field["updaterMetadataFilename"] == "latest-field.json"
    assert _sha256(field["tauriOverlayPath"]) == field["tauriOverlaySha256"]
    assert _sha256(field["fieldAuthControlPath"]) == field["fieldAuthControlSha256"]

    brand = receipt["canonicalBrand"]
    assert _sha256("brand/generated/brand-assets.v1.json") == brand["manifestSha256"]
    assert _sha256("brand/source/approved/field-large-label-lockup.png") == brand[
        "fieldLargeLockupSha256"
    ]
    assert _sha256("brand/generated/field/windows/icon.ico") == brand[
        "fieldWindowsIconSha256"
    ]

    blocker = receipt["universalAuthBindingBlocker"]
    assert blocker["cleared"] is False
    assert blocker["coexistenceActualSha256"] != blocker["authBoundCoexistenceSha256"]
    assert _sha256(blocker["proposalPath"]) == blocker["proposalSha256"]


def test_receipt_keeps_zero_pack_hardware_and_release_gates_closed() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["safety"] == {
        "validatedHardwarePackCount": 0,
        "frontendIsAuthority": False,
        "buildAllowed": False,
        "installAllowed": False,
        "providerUseAllowed": False,
        "deviceEnumerationAllowed": False,
        "hardwareActionsAllowed": False,
        "simulationAllowed": False,
        "releaseBranchAllowed": False,
        "websiteHandoffAllowed": False,
    }
    assert receipt["frozenArtifact"]["status"] == "superseded-unsigned-preview"
    assert receipt["frozenArtifact"]["releaseReady"] is False
    assert receipt["frozenArtifact"]["websiteReady"] is False
    for evidence_commit in receipt["excludedEvidenceCommits"]:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", evidence_commit, "HEAD"],
            check=False,
        )
        assert completed.returncode != 0
