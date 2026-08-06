from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "owned-isolation-560f574-attempt5-application.v1.json"
PLAN = LIFECYCLE / "owned-isolation-560f574-attempt5-plan.v1.json"
OBSERVER = LIFECYCLE / "inspect-field-owned-installer-language.ps1"
PRODUCT = "560f574a95c8b51bbf34711bfd092d77fd3e166e"
TOOL_SOURCE = "6c3dd377af91ee6a96069d672109ae0d4e6500fa"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def git_blob(commit: str, path: str) -> tuple[str, bytes]:
    blob = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=ROOT, check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
    content = subprocess.run(
        ["git", "cat-file", "blob", blob], cwd=ROOT, check=True,
        capture_output=True,
    ).stdout
    return blob, content


def test_attempt5_binds_frozen_product_plan_and_new_root() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    assert application["source"]["productCommit"] == PRODUCT
    assert application["source"]["toolSourceCommit"] == TOOL_SOURCE
    assert application["artifact"]["bytes"] == 11_534_069
    assert application["artifact"]["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert application["ownedPaths"]["runRoot"].endswith("\\560f574-attempt-5")
    assert application["ownedPaths"]["runRootMustBeAbsentAtStart"] is True
    assert plan["ownedPaths"] == application["ownedPaths"]
    assert application["plan"]["bytes"] == PLAN.stat().st_size
    assert application["plan"]["fileSha256"] == sha256(PLAN.read_bytes()).hexdigest()


def test_attempt5_freezes_attempt1_through_attempt4() -> None:
    predecessors = load(APPLICATION)["predecessors"]
    assert [item["applicationId"] for item in predecessors] == [
        f"field-owned-isolation-560f574-attempt-{ordinal}" for ordinal in range(1, 5)
    ]
    assert [item["receiptSha256"] for item in predecessors] == [
        "3f3c5072016e73e16262da70f1558c29ca37eaf6bac6ec45a6521edec754a2e1",
        "4eda662da0ad1430f463794f38ba4725a058b4f32d9d62fde50e236fa90a9456",
        "7cc23b0ceca2bdd655b12306673500dea5cfba6b81aac61ffa48307d951e175f",
        "d5a74565b216f73adf9bc5a536969f61e830e099c89563b75035d71e4fe10598",
    ]
    assert all(item["readOnly"] is True for item in predecessors)
    assert all(item["retryAllowed"] is False for item in predecessors)


def test_attempt5_tools_bind_exact_diagnostic_tool_source() -> None:
    for binding in load(APPLICATION)["toolBindings"]:
        assert binding["sourceCommit"] == TOOL_SOURCE
        blob, content = git_blob(TOOL_SOURCE, binding["path"])
        assert blob == binding["gitBlob"]
        assert len(content) == binding["lfNormalizedBytes"]
        assert sha256(content).hexdigest() == binding["lfNormalizedSha256"]
        working = (ROOT / binding["path"]).read_text(encoding="utf-8-sig")
        assert sha256(working.replace("\r\n", "\n").encode()).hexdigest() == (
            binding["lfNormalizedSha256"]
        )


def test_attempt5_diagnostics_are_preclassification_sanitized_and_non_authoritative() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    contract = application["observerContract"]
    source = OBSERVER.read_text(encoding="utf-8-sig")
    assert contract["preclassificationSnapshotRequired"] is True
    assert contract["snapshotPersistedOnClassificationFailure"] is True
    assert contract["sameInstallerPidRequiredBeforeSnapshot"] is True
    assert contract["singleWindowRequiredBeforeSnapshot"] is True
    assert contract["sensitiveTextRedacted"] is True
    assert contract["urlsRedacted"] is True
    assert contract["nonFieldAbsolutePathsRedacted"] is True
    assert contract["diagnosticSnapshotGrantsAcceptance"] is False
    assert plan["visibleInstallerObserver"]["unknownTitleDecision"] == "deny"
    assert "Add-PreclassificationSnapshot" in source
    assert 'stage = "pending-classification"' in source
    assert "[redacted-sensitive]" in source
    assert "[redacted-path]" in source


def test_attempt5_is_unconsumed_and_hardware_remains_denied() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    execution = application["execution"]
    assert execution["applicationOrdinal"] == 5
    assert execution["lifecycleAttemptOrdinal"] == 5
    assert execution["lifecycleCountMaximum"] == 1
    assert execution["lifecycleAttemptsConsumedAtPreparation"] == 0
    assert execution["retryCountMaximum"] == 0
    assert execution["currentMessageAuthorizesExecution"] is False
    for name in (
        "browserLaunches", "oauthTransactions", "accountOrTokenReads",
        "artifactBuildsOrSigning", "runtimeStartsOrMigrations",
        "simulatorStarts", "deviceOrHardwareActions",
    ):
        assert execution["exactCounts"][name] == 0
    assert plan["safety"]["validatedHardwarePackCount"] == 0
    assert plan["safety"]["hardwareDecision"] == "deny"
    assert application["nonClaims"]["attempt5Executed"] is False
    assert application["nonClaims"]["attempt4ProvesProductIdentityDefect"] is False
