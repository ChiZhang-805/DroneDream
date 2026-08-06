from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "owned-isolation-560f574-attempt7-application.v1.json"
PLAN = LIFECYCLE / "owned-isolation-560f574-attempt7-plan.v1.json"
OBSERVER = LIFECYCLE / "inspect-field-owned-installer-language.ps1"
PRODUCT = "560f574a95c8b51bbf34711bfd092d77fd3e166e"
TOOL_SOURCE = "79b85045771938cdf43f6a669b63eb36b52f99e9"


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


def test_attempt7_binds_product_plan_and_fresh_root() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    assert application["source"]["productCommit"] == PRODUCT
    assert application["source"]["toolSourceCommit"] == TOOL_SOURCE
    assert application["artifact"]["bytes"] == 11_534_069
    assert application["artifact"]["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert application["ownedPaths"]["runRoot"].endswith("\\560f574-attempt-7")
    assert plan["ownedPaths"] == application["ownedPaths"]
    assert application["plan"]["bytes"] == PLAN.stat().st_size
    assert application["plan"]["fileSha256"] == sha256(PLAN.read_bytes()).hexdigest()


def test_attempt7_freezes_attempt1_through_attempt6() -> None:
    predecessors = load(APPLICATION)["predecessors"]
    assert [item["applicationId"] for item in predecessors] == [
        f"field-owned-isolation-560f574-attempt-{ordinal}" for ordinal in range(1, 7)
    ]
    assert predecessors[-1]["receiptSha256"] == (
        "1f5be585fee0e60f7096fbb85f18260483b3c5dcb99bec121fa0d9e8beb0a0d4"
    )
    assert predecessors[-1]["observerSha256"] == (
        "102d14df24025f3cf4f1853aac5f9d69e51445299aeff3a70dc4d90e7159a6ac"
    )
    assert all(item["readOnly"] is True for item in predecessors)
    assert all(item["retryAllowed"] is False for item in predecessors)


def test_attempt7_tools_bind_exact_shared_wait_source() -> None:
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


def test_attempt7_reuses_loading_wait_before_and_after_selector() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    contract = application["observerContract"]
    source = OBSERVER.read_text(encoding="utf-8-sig")
    assert contract["sharedLoadingWaitFunction"] == "Wait-ExpectedStageAfterLoading"
    assert contract["absoluteDeadlineRequired"] is True
    assert contract["preSelectorExpectedStage"] == "language-selector"
    assert contract["postSelectorExpectedStage"] == "branded"
    assert contract["loadingDecision"] == "continue-only"
    assert contract["loadingClickAllowed"] is False
    assert contract["loadingAccepted"] is False
    assert contract["firstNonLoadingMustEqualExpectedStage"] is True
    shared = plan["visibleInstallerObserver"]["sharedLoadingWait"]
    assert shared["timeoutDecision"] == "deny"
    assert source.count("Wait-ExpectedStageAfterLoading -Process $process") == 2
    assert "Timed out waiting for $ExpectedStage" in source


def test_attempt7_is_unconsumed_and_hardware_denied() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    execution = application["execution"]
    assert execution["applicationOrdinal"] == 7
    assert execution["lifecycleAttemptOrdinal"] == 7
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
    assert application["nonClaims"]["attempt7Executed"] is False
