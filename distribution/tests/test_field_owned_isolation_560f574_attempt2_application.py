from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "owned-isolation-560f574-attempt2-application.v1.json"
PLAN = LIFECYCLE / "owned-isolation-560f574-attempt2-plan.v1.json"
DIAGNOSIS = LIFECYCLE / "attempt1-visible-installer-observer-diagnosis.v1.json"
PRODUCT = "560f574a95c8b51bbf34711bfd092d77fd3e166e"


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


def test_attempt2_binds_new_root_old_failure_and_same_frozen_artifact() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)

    assert application["source"]["productCommit"] == PRODUCT
    assert application["artifact"]["bytes"] == 11_534_069
    assert application["artifact"]["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert application["predecessor"]["receiptSha256"] == (
        "3f3c5072016e73e16262da70f1558c29ca37eaf6bac6ec45a6521edec754a2e1"
    )
    assert application["predecessor"]["retryAllowed"] is False
    assert application["ownedPaths"]["runRoot"].endswith("\\560f574-attempt-2")
    assert "attempt-1" not in application["ownedPaths"]["runRoot"]
    assert plan["predecessor"]["readOnly"] is True
    assert application["plan"]["bytes"] == PLAN.stat().st_size
    assert application["plan"]["fileSha256"] == sha256(PLAN.read_bytes()).hexdigest()


def test_attempt2_tools_bind_exact_current_git_blobs() -> None:
    application = _load(APPLICATION)
    for binding in application["toolBindings"]:
        blob, content = _git_blob(binding["sourceCommit"], binding["path"])
        assert blob == binding["gitBlob"]
        assert len(content) == binding["lfNormalizedBytes"]
        assert sha256(content).hexdigest() == binding["lfNormalizedSha256"]


def test_attempt2_remains_historical_after_observer_tool_moves_forward() -> None:
    application = _load(APPLICATION)
    assert {binding["sourceCommit"] for binding in application["toolBindings"]} == {
        "7586d971176e0e6ecae096aa9a545f8749503819"
    }
    assert application["execution"]["retryCountMaximum"] == 0
    assert application["nonClaims"]["attempt2Executed"] is False


def test_attempt2_observer_contract_matches_diagnosis() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    diagnosis = _load(DIAGNOSIS)
    contract = application["observerContract"]

    assert contract["genericLanguageSelectorTitle"] == "Installer Language"
    assert contract["genericLanguageSelectorMayOmitProductIdentity"] is True
    assert contract["sameInstallerPidAfterSelectionRequired"] is True
    assert contract["singleVisibleOwnedWindowRequired"] is True
    assert contract["canonicalDisplayName"] == "DroneDream · FIELD"
    assert contract["canonicalInstallRoot"] == "%LOCALAPPDATA%\\DroneDream-Field"
    assert contract["maximumNonInstallNextInvocationsPerProbe"] == 2
    assert contract["installActionAllowedDuringProbe"] is False
    assert plan["visibleInstallerObserver"]["languageOrder"] == [
        {"locale": "en", "languageId": "1033", "comboIndex": 0},
        {"locale": "zh-CN", "languageId": "2052", "comboIndex": 1},
    ]
    assert diagnosis["remediationContract"]["postSelection"][
        "canonicalDisplayName"
    ] == contract["canonicalDisplayName"]


def test_attempt2_counts_and_authority_remain_fail_closed() -> None:
    application = _load(APPLICATION)
    counts = application["execution"]["exactCounts"]

    assert application["execution"]["applicationOrdinal"] == 2
    assert application["execution"]["lifecycleAttemptOrdinal"] == 2
    assert application["execution"]["lifecycleCountMaximum"] == 1
    assert application["execution"]["retryCountMaximum"] == 0
    assert application["execution"]["currentMessageAuthorizesExecution"] is False
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
    assert application["nonClaims"]["attempt2Executed"] is False
    assert application["nonClaims"]["releaseReady"] is False
    assert application["nonClaims"]["websiteReady"] is False
