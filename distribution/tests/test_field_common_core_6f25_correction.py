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
    / "common-core-6f25-donor-correction-v1.json"
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


def test_corrected_auth_and_runtime_mode_paths_are_exact_to_6f25() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    common = receipt["commonCore"]
    assert _git("rev-parse", f'{common["commit"]}^{{tree}}') == common["tree"]
    records = [receipt["authCorrection"], *receipt["runtimeModeAtomicReview"]["paths"]]
    for record in records:
        path = record["path"]
        assert _git("rev-parse", f'{common["commit"]}:{path}') == record["gitBlob"]
        assert _git("rev-parse", f"HEAD:{path}") == record["gitBlob"]
        assert _sha256(path) == record["sha256"]


def test_auth_binding_matches_current_coexistence_bytes() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    auth = json.loads(
        (ROOT / receipt["authCorrection"]["path"]).read_text(encoding="utf-8")
    )
    coexistence_sha = _sha256("distribution/desktop/edition-coexistence.v1.json")
    assert auth["identityBinding"]["contractSha256"] == coexistence_sha
    assert coexistence_sha == receipt["authCorrection"]["identityBindingSha256"]
    assert receipt["releaseState"]["authCommonCoreBlockerCleared"] is True


def test_correction_preserves_field_safety_and_historical_evidence() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert _git(
        "merge-base", "--is-ancestor", receipt["productSource"]["commit"], "HEAD"
    ) == ""
    assert receipt["runtimeModeAtomicReview"]["pathCount"] == 3
    assert receipt["runtimeModeAtomicReview"]["changedPathCount"] == 0
    assert receipt["historicalEvidence"]["preserved"] is True
    assert (ROOT / receipt["historicalEvidence"]["supersededProposalPath"]).is_file()
    assert receipt["fieldBindings"]["runtimeProfileId"] == "field-lightweight"
    assert receipt["fieldBindings"]["validatedHardwarePackCount"] == 0
    assert not any(receipt["safety"].values())
    assert receipt["releaseState"]["releaseReady"] is False
    assert receipt["releaseState"]["websiteReady"] is False
