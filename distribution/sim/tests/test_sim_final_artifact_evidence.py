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
APPLICATION = (
    ROOT / "distribution" / "sim" / "lifecycle" / "red-fcabd99f-final-application.v1.json"
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


def test_final_candidate_lifecycle_application_is_single_attempt_and_fail_closed() -> None:
    application = json.loads(APPLICATION.read_text(encoding="utf-8"))
    artifact = application["artifact"]
    runner = application["runner"]
    runner_path = ROOT / runner["path"]
    static_path = ROOT / artifact["staticAcceptancePath"]
    assert artifact["sha256"] == "fcabd99fcd3add8c4a19ca429b05faafc2a6ad8f5989cf32b62549ec0ec3299e"
    assert static_path.stat().st_size == artifact["staticAcceptanceBytes"]
    assert sha256(static_path) == artifact["staticAcceptanceSha256"]
    assert runner_path.stat().st_size == runner["bytes"]
    assert sha256(runner_path) == runner["sha256"]
    assert runner["maximumExecuteInvocations"] == 1
    assert runner["automaticRetryAllowed"] is False

    counts = application["acceptanceMatrix"]["exactMaximumCounts"]
    assert counts["freshInstallerInvocations"] == 1
    assert counts["overlayInstallerInvocations"] == 1
    assert counts["applicationLaunches"] == 1
    assert counts["uninstallerInvocations"] == 1
    assert counts["pkceBoundaryChecks"] == 1
    for key in (
        "browserLoginTransactions",
        "realTokenExchanges",
        "credentialReads",
        "runtimeStarts",
        "px4Starts",
        "gazeboStarts",
        "hardwareActions",
        "artifactBuilds",
        "automaticRetries",
    ):
        assert counts[key] == 0
    assert application["protectedState"]["simPreferenceKeyValueParity"] is True
    assert application["rollback"]["manualProtectedStateDeletionAllowed"] is False
