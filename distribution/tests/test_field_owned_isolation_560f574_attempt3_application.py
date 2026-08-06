from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "owned-isolation-560f574-attempt3-application.v1.json"
PLAN = LIFECYCLE / "owned-isolation-560f574-attempt3-plan.v1.json"
OBSERVER = LIFECYCLE / "inspect-field-owned-installer-language.ps1"
PRODUCT = "560f574a95c8b51bbf34711bfd092d77fd3e166e"
TOOL_SOURCE = "e58c9739521d52fbb2f58a36b201adf6003c74d2"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob(commit: str, path: str) -> tuple[str, bytes]:
    blob = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    content = subprocess.run(
        ["git", "cat-file", "blob", blob],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return blob, content


def test_attempt3_binds_frozen_product_artifact_and_new_root() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)

    assert application["source"]["productCommit"] == PRODUCT
    assert application["source"]["toolSourceCommit"] == TOOL_SOURCE
    assert application["artifact"]["bytes"] == 11_534_069
    assert application["artifact"]["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert application["ownedPaths"]["runRoot"].endswith("\\560f574-attempt-3")
    assert application["ownedPaths"]["runRootMustBeAbsentAtStart"] is True
    assert plan["ownedPaths"] == application["ownedPaths"]
    assert application["plan"]["bytes"] == PLAN.stat().st_size
    assert application["plan"]["fileSha256"] == sha256(PLAN.read_bytes()).hexdigest()


def test_attempt3_freezes_both_failed_predecessors_without_retry() -> None:
    application = _load(APPLICATION)
    predecessors = application["predecessors"]

    assert [item["applicationId"] for item in predecessors] == [
        "field-owned-isolation-560f574-attempt-1",
        "field-owned-isolation-560f574-attempt-2",
    ]
    assert [item["receiptSha256"] for item in predecessors] == [
        "3f3c5072016e73e16262da70f1558c29ca37eaf6bac6ec45a6521edec754a2e1",
        "4eda662da0ad1430f463794f38ba4725a058b4f32d9d62fde50e236fa90a9456",
    ]
    assert all(item["readOnly"] is True for item in predecessors)
    assert all(item["retryAllowed"] is False for item in predecessors)


def test_attempt3_tools_bind_exact_tool_source_blobs() -> None:
    application = _load(APPLICATION)
    assert {binding["sourceCommit"] for binding in application["toolBindings"]} == {
        TOOL_SOURCE
    }
    for binding in application["toolBindings"]:
        blob, content = _git_blob(binding["sourceCommit"], binding["path"])
        assert blob == binding["gitBlob"]
        assert len(content) == binding["lfNormalizedBytes"]
        assert sha256(content).hexdigest() == binding["lfNormalizedSha256"]
        working = (ROOT / binding["path"]).read_text(encoding="utf-8-sig")
        assert sha256(working.replace("\r\n", "\n").encode()).hexdigest() == (
            binding["lfNormalizedSha256"]
        )


def test_attempt3_observer_contract_keeps_ownership_and_identity_fail_closed() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    contract = application["observerContract"]
    observer = OBSERVER.read_text(encoding="utf-8-sig")

    assert contract["initialExcludedTitle"] is None
    assert contract["postSelectionExcludedTitle"] == "Installer Language"
    assert contract["sameInstallerPidAfterSelectionRequired"] is True
    assert contract["singleVisibleOwnedWindowRequired"] is True
    assert contract["canonicalDisplayName"] == "DroneDream · FIELD"
    assert contract["canonicalInstallRoot"] == "%LOCALAPPDATA%\\DroneDream-Field"
    assert contract["installActionAllowedDuringProbe"] is False
    assert plan["visibleInstallerObserver"]["foreignPidDecision"] == "deny"
    assert plan["visibleInstallerObserver"]["extraOwnedWindowDecision"] == "deny"
    assert plan["visibleInstallerObserver"]["unknownTitleDecision"] == "deny"
    assert "[AllowNull()][AllowEmptyString()][string]$DifferentFromTitle" in observer
    assert "[string]::IsNullOrEmpty($DifferentFromTitle)" in observer


def test_attempt3_counts_and_authority_remain_unconsumed_and_fail_closed() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    execution = application["execution"]
    counts = execution["exactCounts"]

    assert execution["applicationOrdinal"] == 3
    assert execution["lifecycleAttemptOrdinal"] == 3
    assert execution["lifecycleCountMaximum"] == 1
    assert execution["lifecycleAttemptsConsumedAtPreparation"] == 0
    assert execution["retryCountMaximum"] == 0
    assert execution["currentMessageAuthorizesExecution"] is False
    assert counts["visibleInstallerLanguageProbes"] == 2
    assert counts["freshInstallerInvocations"] == 1
    assert counts["overlayInstallerInvocations"] == 1
    assert counts["applicationLaunches"] == 2
    assert counts["uninstallerInvocations"] == 1
    for name in (
        "browserLaunches",
        "oauthTransactions",
        "accountOrTokenReads",
        "artifactBuildsOrSigning",
        "runtimeStartsOrMigrations",
        "simulatorStarts",
        "deviceOrHardwareActions",
    ):
        assert counts[name] == 0
    assert plan["safety"]["validatedHardwarePackCount"] == 0
    assert plan["safety"]["hardwareDecision"] == "deny"
    assert plan["safety"]["frontendIsAuthority"] is False
    assert application["nonClaims"]["attempt3Executed"] is False
    assert application["nonClaims"]["releaseReady"] is False
    assert application["nonClaims"]["websiteReady"] is False
