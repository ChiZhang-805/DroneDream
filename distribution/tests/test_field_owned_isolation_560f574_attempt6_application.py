from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "owned-isolation-560f574-attempt6-application.v1.json"
PLAN = LIFECYCLE / "owned-isolation-560f574-attempt6-plan.v1.json"
OBSERVER = LIFECYCLE / "inspect-field-owned-installer-language.ps1"
PRODUCT = "560f574a95c8b51bbf34711bfd092d77fd3e166e"
TOOL_SOURCE = "59a38447288bb4520e89d0aed99de497c43187cd"


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


def test_attempt6_binds_product_plan_and_fresh_root() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    assert application["source"]["productCommit"] == PRODUCT
    assert application["source"]["toolSourceCommit"] == TOOL_SOURCE
    assert application["artifact"]["bytes"] == 11_534_069
    assert application["artifact"]["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert application["ownedPaths"]["runRoot"].endswith("\\560f574-attempt-6")
    assert plan["ownedPaths"] == application["ownedPaths"]
    assert application["plan"]["bytes"] == PLAN.stat().st_size
    assert application["plan"]["fileSha256"] == sha256(PLAN.read_bytes()).hexdigest()


def test_attempt6_freezes_attempt1_through_attempt5() -> None:
    predecessors = load(APPLICATION)["predecessors"]
    assert [item["applicationId"] for item in predecessors] == [
        f"field-owned-isolation-560f574-attempt-{ordinal}" for ordinal in range(1, 6)
    ]
    assert predecessors[-1]["receiptSha256"] == (
        "e0fba209e6f59c31a4938c7382dbf84c12bfa7ce0dd91fd05d6ae4b6098950ed"
    )
    assert predecessors[-1]["observerSha256"] == (
        "f9f4bdaeef4aa40a0112bff16d64f0702d359d9d739883a32f5047247a17f61a"
    )
    assert all(item["readOnly"] is True for item in predecessors)
    assert all(item["retryAllowed"] is False for item in predecessors)


def test_attempt6_tools_bind_exact_loading_tool_source() -> None:
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


def test_attempt6_loading_progress_only_continues_bounded_polling() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    contract = application["observerContract"]
    source = OBSERVER.read_text(encoding="utf-8-sig")
    assert contract["loadingProgressPercentMinimum"] == 0
    assert contract["loadingProgressPercentMaximum"] == 100
    assert contract["loadingProgressExactControlCount"] == 3
    assert contract["loadingProgressInteractiveControlsAllowed"] is False
    assert contract["loadingProgressDecision"] == "continue-bounded-polling"
    assert contract["loadingProgressAcceptedAsBranded"] is False
    assert contract["loadingProgressClickAllowed"] is False
    loading = plan["visibleInstallerObserver"]["loadingProgress"]
    assert loading["allowedControlTypes"] == ["ControlType.Text", "ControlType.Image"]
    assert plan["visibleInstallerObserver"]["unknownTitleDecision"] == "deny"
    assert 'return "loading-progress"' in source
    assert '$welcomeStage -cne "loading-progress"' in source


def test_attempt6_is_unconsumed_and_hardware_denied() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    execution = application["execution"]
    assert execution["applicationOrdinal"] == 6
    assert execution["lifecycleAttemptOrdinal"] == 6
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
    assert application["nonClaims"]["attempt6Executed"] is False
    assert application["nonClaims"]["loadingProgressGrantsAcceptance"] is False
