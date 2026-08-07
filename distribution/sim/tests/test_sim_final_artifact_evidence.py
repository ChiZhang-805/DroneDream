from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECORD = (
    ROOT
    / "distribution"
    / "sim"
    / "desktop"
    / "yellow-build-attempt-15-79a718d-static-accepted.v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_final_candidate_static_acceptance_is_exact_and_not_promoted() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    source = record["sourceSeparation"]
    assert source["productSourceCommit"] == "79a718dae55c274cf4803a57129e5789012dca03"
    tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", source["productSourceCommit"]],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tree == source["productSourceTree"]
    assert source["evidenceIsProductSource"] is False

    profile = ROOT / record["buildProfile"]["path"]
    assert profile.stat().st_size == record["buildProfile"]["bytes"]
    assert sha256(profile) == record["buildProfile"]["sha256"]

    artifact = record["artifact"]
    assert artifact["fileName"] == "DroneDream-Sim-1.0.0.exe"
    assert artifact["productName"] == "DroneDream · SIM"
    assert artifact["version"] == "1.0.0"
    assert artifact["authenticodeState"] == "NotSigned"
    assert artifact["peCertificateTableOffset"] == 0
    assert artifact["peCertificateTableSize"] == 0

    payload = record["payload"]
    assert payload["enginePackProfileId"] == "sim-only"
    assert payload["editionManifestPaths"] == ["distribution/editions/sim.v1.json"]
    assert payload["validatedVehiclePackCount"] == 0
    assert payload["runtimeBaseEmbedded"] is False
    assert payload["forbiddenFindingCount"] == 0
    assert payload["hardwarePayloadAllowed"] is False
    assert payload["contractPassed"] is True

    autonomy = record["modelHarness"]
    assert autonomy["normalModelTurnsPerGeneration"] == 2
    assert autonomy["maximumModelTurnsPerGeneration"] == 4
    assert autonomy["harnessOwnsBudgetsValidationExecutionQualificationHoldoutRollback"] is True
    assert autonomy["candidateClassification"] == "simulation-hypothesis-not-hardware-approved"
    assert autonomy["hardwareAuthorityGranted"] is False
    assert autonomy["realModelProviderInvokedDuringAcceptance"] is False

    assert record["attempt"]["artifactBuilds"] == 1
    assert record["attempt"]["retryCount"] == 0
    assert record["lifecycle"]["validated"] is False
    assert record["nonClaims"]["releaseReady"] is False
    assert record["nonClaims"]["websiteDeployed"] is False


def test_mounted_final_candidate_rehashes_when_present() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    paths = [
        (record["artifact"]["absolutePath"], record["artifact"], "bytes", "sha256"),
        (
            record["updater"]["signaturePath"],
            record["updater"],
            "signatureBytes",
            "signatureSha256",
        ),
    ]
    for raw_path, expected, bytes_key, sha_key in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        assert path.is_file()
        assert path.stat().st_size == expected[bytes_key]
        assert sha256(path) == expected[sha_key]

    for path_key, sha_key in (
        ("buildReceiptPath", "buildReceiptSha256"),
        ("artifactManifestPath", "artifactManifestSha256"),
        ("payloadAuditPath", "payloadAuditSha256"),
        ("outerExitReconciliationPath", "outerExitReconciliationSha256"),
    ):
        path = Path(record["evidence"][path_key])
        if path.exists():
            assert path.is_file()
            assert sha256(path) == record["evidence"][sha_key]
