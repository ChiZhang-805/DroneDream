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
    / "yellow-build-attempt-17-4c0021b-static-accepted.v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_centered_brand_candidate_is_exact_and_static_only() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    source = record["sourceSeparation"]
    tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", source["productSourceCommit"]],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert source["productSourceCommit"] == (
        "4c0021b28161a9fa2210e6deab0edab2e4f8372d"
    )
    assert tree == source["productSourceTree"]
    assert source["evidenceIsProductSource"] is False

    artifact = record["artifact"]
    assert artifact["fileName"] == "DroneDream-Sim-1.0.0.exe"
    assert artifact["productName"] == "DroneDream · SIM"
    assert artifact["version"] == "1.0.0"
    assert artifact["authenticodeState"] == "NotSigned"
    assert artifact["peCertificateTableOffset"] == 0
    assert artifact["peCertificateTableSize"] == 0

    attempt = record["attempt"]
    assert attempt["buildInvocations"] == 1
    assert attempt["artifactBuilds"] == 1
    assert attempt["retryCount"] == 0
    assert attempt["outerLauncherExitCode"] == 1
    assert attempt["actualBuildState"] == "complete"

    payload = record["payload"]
    assert payload["enginePackProfileId"] == "sim-only"
    assert payload["editionManifestPaths"] == ["distribution/editions/sim.v1.json"]
    assert payload["runtimeExecutableCount"] == 0
    assert payload["validatedVehiclePackCount"] == 0
    assert payload["hardwarePayloadAllowed"] is False
    assert payload["contractPassed"] is True

    brand = record["brandAndInstaller"]
    assert brand["centeredSeparatorAssetSha256"] == (
        "f3dd34d3e1a546e4299370d6cbe21d9f03b07a5910dcae061a322ba6c548fd6e"
    )
    assert brand["separatorGapLeftPx"] == brand["separatorGapRightPx"] == 53
    assert brand["separatorTolerancePx"] == 0
    assert brand["displayNameCenteredDotCodePoint"] == 183

    assert record["updater"]["payloadSignatureVerification"] == (
        "pass-ed25519-over-blake2b-512"
    )
    assert record["lifecycle"]["validated"] is False
    assert record["nonClaims"]["releaseReady"] is False
    assert record["nonClaims"]["websiteDeployed"] is False


def test_centered_brand_candidate_and_external_evidence_rehash_when_present() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    artifact = Path(record["artifact"]["absolutePath"])
    signature = Path(record["updater"]["signaturePath"])
    if artifact.exists():
        assert artifact.stat().st_size == record["artifact"]["bytes"]
        assert sha256(artifact) == record["artifact"]["sha256"]
    if signature.exists():
        assert signature.stat().st_size == record["updater"]["signatureBytes"]
        assert sha256(signature) == record["updater"]["signatureSha256"]

    evidence_root = Path(record["evidence"]["root"]) / "receipt"
    for name, key in (
        ("yellow-build-receipt.json", "buildReceiptSha256"),
        ("artifact-manifest.json", "artifactManifestSha256"),
        ("payload-audit.json", "payloadAuditSha256"),
        ("outer-exit-reconciliation.json", "outerExitReconciliationSha256"),
        ("updater-signature-verification.json", "updaterSignatureVerificationSha256"),
        ("build-transcript.log", "buildTranscriptSha256"),
    ):
        path = evidence_root / name
        if path.exists():
            assert sha256(path) == record["evidence"][key]
