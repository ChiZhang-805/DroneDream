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
    / "yellow-build-attempt-21-573e8f9-static-accepted.v1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_attempt_21_static_acceptance_is_exact_and_not_release_ready() -> None:
    record = load_record()
    source = record["sourceSeparation"]
    tree = subprocess.run(
        ["git", "show", "-s", "--format=%T", source["productSourceCommit"]],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert source["productSourceCommit"] == (
        "573e8f991eba703bbfd6c4b35f464fbaab78903c"
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
    assert artifact["checksumContentExact"] is True

    attempt = record["attempt"]
    for key in (
        "launcherInvocations",
        "preflightInvocations",
        "prepareInvocations",
        "executeInvocations",
        "snapshotInvocations",
        "buildInvocations",
        "frontendBuilds",
        "tauriBuilds",
        "cargoBuilds",
        "nsisBuilds",
        "artifactBuilds",
    ):
        assert attempt[key] == 1
    assert attempt["npmCiInvocations"] == 4
    assert attempt["retryCount"] == 0
    assert attempt["outerLauncherExitCode"] == 1
    assert attempt["actualBuildState"] == "complete"

    payload = record["payload"]
    assert payload["enginePackProfileId"] == "sim-only"
    assert payload["editionManifestPaths"] == ["distribution/editions/sim.v1.json"]
    assert payload["runtimeExecutableCount"] == 0
    assert payload["validatedVehiclePackCount"] == 0
    assert payload["forbiddenFindingCount"] == 0
    assert payload["hardwarePayloadAllowed"] is False
    assert payload["contractPassed"] is True

    brand = record["brandAndInstaller"]
    assert brand["installerIcoSha256"] == (
        "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c"
    )
    assert brand["installerAndAppEmbeddedIconPixelsMatchCanonical32Frame"] is True
    assert brand["shortcutIconStaticSource"] == "$INSTDIR\\${MAINBINARYNAME}.exe"
    assert brand["shortcutLegacySharedIcoReferenceCount"] == 0
    assert brand["actualShortcutAndUninstallerIconObservationPendingLifecycle"] is True
    assert brand["displayNameCenteredDotCodePoint"] == 183

    assert record["lifecycle"]["validated"] is False
    assert record["nonClaims"]["releaseReady"] is False
    assert record["nonClaims"]["websiteDeployed"] is False


def test_attempt_21_frozen_external_bytes_rehash_when_present() -> None:
    record = load_record()
    artifact = record["artifact"]
    artifact_path = Path(artifact["absolutePath"])
    if artifact_path.exists():
        assert artifact_path.stat().st_size == artifact["bytes"]
        assert sha256(artifact_path) == artifact["sha256"]
        sidecar = artifact_path.with_suffix(artifact_path.suffix + ".sha256")
        assert sidecar.stat().st_size == artifact["checksumSidecarBytes"]
        assert sha256(sidecar) == artifact["checksumSidecarSha256"]
        assert sidecar.read_text(encoding="ascii").strip() == (
            f'{artifact["sha256"]}  {artifact["fileName"]}'
        )

    signature = Path(record["updater"]["signaturePath"])
    if signature.exists():
        assert signature.stat().st_size == record["updater"]["signatureBytes"]
        assert sha256(signature) == record["updater"]["signatureSha256"]

    evidence_root = Path(record["evidence"]["root"]) / "receipt"
    for name, key in (
        ("attempt-lock.json", "attemptLockSha256"),
        ("yellow-build-receipt.json", "buildReceiptSha256"),
        ("build-transcript.log", "buildTranscriptSha256"),
        ("offline-cache-snapshot.json", "cacheSnapshotReceiptSha256"),
        ("dependency-preparation-core.json", "dependencyPreparationCoreSha256"),
        ("dependency-preparation-receipt.json", "dependencyPreparationReceiptSha256"),
    ):
        path = evidence_root / name
        if path.exists():
            assert sha256(path) == record["evidence"][key]

    for path_key, hash_key in (
        ("installerEmbeddedIconEvidencePath", "installerEmbeddedIconEvidenceSha256"),
        ("appEmbeddedIconEvidencePath", "appEmbeddedIconEvidenceSha256"),
        ("canonicalIco32FrameEvidencePath", "canonicalIco32FrameEvidenceSha256"),
    ):
        path = Path(record["brandAndInstaller"][path_key])
        if path.exists():
            assert sha256(path) == record["brandAndInstaller"][hash_key]


def test_attempt_21_exit_reconciliation_and_correction_are_bound() -> None:
    record = load_record()
    evidence = record["evidence"]
    reconciliation = ROOT / evidence["exitReconciliationPath"]
    assert reconciliation.stat().st_size == evidence["exitReconciliationBytes"]
    assert sha256(reconciliation) == evidence["exitReconciliationSha256"]
    document = json.loads(reconciliation.read_text(encoding="utf-8"))
    assert document["attempt"]["retryCount"] == 0
    assert document["boundedCleanup"]["junctionDeleteInvocations"] == 2
    assert document["boundedCleanup"]["recursiveDeleteInvocations"] == 0
    assert document["boundedCleanup"]["targetDirectoriesDeleted"] is False
    assert document["correction"]["historicalEntryModified"] is False
