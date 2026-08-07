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
APPLICATION_2 = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-final-application-2.v1.json"
)
ATTEMPT_1_FAILURE = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-execution-attempt-1-failed.v1.json"
)
APPLICATION_3 = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-final-application-3.v1.json"
)
ATTEMPT_2_FAILURE = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-execution-attempt-2-failed.v1.json"
)
APPLICATION_4 = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-final-application-4.v1.json"
)
ATTEMPT_3_ABORT = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-execution-attempt-3-aborted.v1.json"
)
APPLICATION_5 = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-final-application-5.v1.json"
)
ATTEMPT_4_FAILURE = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "red-fcabd99f-execution-attempt-4-failed.v1.json"
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


def test_second_lifecycle_application_repairs_only_runner_unicode_and_uses_new_root() -> None:
    first = json.loads(APPLICATION.read_text(encoding="utf-8"))
    second = json.loads(APPLICATION_2.read_text(encoding="utf-8"))
    failure = json.loads(ATTEMPT_1_FAILURE.read_text(encoding="utf-8"))
    assert second["artifact"] == first["artifact"]
    assert second["ownedSurface"]["runRoot"] != first["ownedSurface"]["runRoot"]
    assert second["runner"]["path"].endswith("invoke-red-lifecycle-fcabd99f-2.ps1")
    runner = ROOT / second["runner"]["path"]
    assert runner.stat().st_size == second["runner"]["bytes"]
    assert sha256(runner) == second["runner"]["sha256"]
    runner_text = runner.read_text(encoding="utf-8-sig")
    assert "[char]0x00B7" in runner_text
    assert "\u00b7" not in runner_text
    assert failure["failure"]["productDefectObserved"] is False
    assert failure["rollback"]["protectedStateParity"] is True
    assert second["priorAttempt"]["externalReceiptSha256"] == failure["externalReceipt"]["sha256"]
    assert second["priorAttempt"]["sameRunRootReuseAllowed"] is False


def test_third_lifecycle_application_selects_locales_through_owned_preference() -> None:
    second = json.loads(APPLICATION_2.read_text(encoding="utf-8"))
    third = json.loads(APPLICATION_3.read_text(encoding="utf-8"))
    failure = json.loads(ATTEMPT_2_FAILURE.read_text(encoding="utf-8"))
    assert third["artifact"] == second["artifact"]
    assert third["ownedSurface"]["runRoot"] != second["ownedSurface"]["runRoot"]
    runner = ROOT / third["runner"]["path"]
    assert runner.stat().st_size == third["runner"]["bytes"]
    assert sha256(runner) == third["runner"]["sha256"]
    runner_text = runner.read_text(encoding="utf-8-sig")
    assert 'Set-OwnedInstallerLanguage -Language "1033"' in runner_text
    assert 'Set-OwnedInstallerLanguage -Language "2052"' in runner_text
    assert 'ValidateSet("1033", "2052")' in runner_text
    counts = third["acceptanceMatrix"]["exactMaximumCounts"]
    assert counts["installerLanguagePreferenceWrites"] == 2
    assert counts["failureLanguagePreferenceCleanupWrites"] == 1
    assert failure["failure"]["observedLanguage"] == 2052
    assert failure["rollback"]["protectedStateParity"] is True
    assert third["priorAttempt"]["externalReceiptSha256"] == failure["externalReceipt"]["sha256"]


def test_fourth_lifecycle_application_replaces_zero_mutation_transport_abort() -> None:
    third = json.loads(APPLICATION_3.read_text(encoding="utf-8"))
    fourth = json.loads(APPLICATION_4.read_text(encoding="utf-8"))
    aborted = json.loads(ATTEMPT_3_ABORT.read_text(encoding="utf-8"))
    assert fourth["artifact"] == third["artifact"]
    assert fourth["ownedSurface"]["runRoot"] != third["ownedSurface"]["runRoot"]
    runner = ROOT / fourth["runner"]["path"]
    assert runner.stat().st_size == fourth["runner"]["bytes"]
    assert sha256(runner) == fourth["runner"]["sha256"]
    runner_text = runner.read_text(encoding="utf-8-sig")
    assert "sim-red-final-fcabd99f-ordinal4" in runner_text
    assert "executionOrdinal = 4" in runner_text
    assert aborted["execution"]["commandTransportExitCode"] == 124
    assert aborted["execution"]["freshInstallerInvocations"] == 0
    assert aborted["verifiedAfterAbort"]["ownedRunRootAbsent"] is True
    assert aborted["verifiedAfterAbort"]["installRootAbsent"] is True
    assert aborted["verifiedAfterAbort"]["uninstallKeyAbsent"] is True
    assert fourth["priorAttempt"]["lifecycleMutationCount"] == 0
    assert fourth["priorAttempt"]["sameRunRootReuseAllowed"] is False


def test_fifth_lifecycle_application_restores_runner_owned_locale_before_parity() -> None:
    fourth = json.loads(APPLICATION_4.read_text(encoding="utf-8"))
    fifth = json.loads(APPLICATION_5.read_text(encoding="utf-8"))
    failure = json.loads(ATTEMPT_4_FAILURE.read_text(encoding="utf-8"))
    assert fifth["artifact"] == fourth["artifact"]
    assert fifth["ownedSurface"]["runRoot"] != fourth["ownedSurface"]["runRoot"]
    runner = ROOT / fifth["runner"]["path"]
    assert runner.stat().st_size == fifth["runner"]["bytes"]
    assert sha256(runner) == fifth["runner"]["sha256"]
    runner_text = runner.read_text(encoding="utf-8-sig")
    cleanup = runner_text.index(
        'Remove-OwnedInstallerLanguage -Stage "final-zh-language-preference-cleanup"'
    )
    parity = runner_text.index('Assert-SimRemoved -Stage "final-zh-uninstall"')
    assert cleanup < parity
    assert "executionOrdinal = 5" in runner_text
    assert "existing-user-state-is-not-a-fresh-install-blocker" in runner_text
    precondition_end = runner_text.index('throw "Fresh Sim precondition failed: $path"')
    precondition_start = runner_text.rindex("foreach ($path in @(", 0, precondition_end)
    fresh_precondition = runner_text[precondition_start:precondition_end]
    assert "$roamingAppData" not in fresh_precondition
    assert "$localAppData" not in fresh_precondition
    assert fifth["acceptanceMatrix"]["exactMaximumCounts"][
        "installerLanguagePreferenceCleanupWrites"
    ] == 1
    assert failure["verifiedBeforeFailure"]["liveWebView2"] == "pass"
    assert failure["postFailureState"]["preExistingPreferenceCorePreserved"] is True
    assert fifth["priorAttempt"]["externalReceiptSha256"] == failure["externalReceipt"][
        "sha256"
    ]
