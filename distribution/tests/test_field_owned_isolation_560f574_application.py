from __future__ import annotations

import json
import subprocess
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "owned-isolation-560f574-application.v1.json"
PLAN = LIFECYCLE / "owned-isolation-560f574-plan.v1.json"
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


def test_application_binds_exact_artifact_audit_and_plan() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)

    assert application["status"] == "prepared-awaiting-exact-red-start-signal"
    assert application["source"]["productCommit"] == PRODUCT
    assert application["artifact"]["bytes"] == 11_534_069
    assert application["artifact"]["sha256"] == (
        "8e2e2260704901c52b1c0b149eb4929b0e353b7ccf3d76a0fbba7031aa17ca1f"
    )
    assert application["staticAudit"]["receiptBytes"] == 8_904
    assert application["staticAudit"]["receiptSha256"] == (
        "2447677521529871e671053159515a898743d6ee82775f09e030fd5674252ceb"
    )
    assert application["staticAudit"]["staticAuditComplete"] is True
    assert application["plan"]["fileSha256"] == sha256(PLAN.read_bytes()).hexdigest()
    assert application["plan"]["bytes"] == PLAN.stat().st_size
    assert plan["artifact"]["sha256"] == application["artifact"]["sha256"]


def test_tool_bindings_are_exact_git_blobs_and_lf_bytes() -> None:
    application = _load(APPLICATION)
    for binding in application["toolBindings"]:
        blob, content = _git_blob(binding["sourceCommit"], binding["path"])
        assert blob == binding["gitBlob"]
        assert len(content) == binding["lfNormalizedBytes"]
        assert sha256(content).hexdigest() == binding["lfNormalizedSha256"]


def test_product_ui_bindings_and_shared_3d_contract_are_source_bound() -> None:
    application = _load(APPLICATION)
    for binding in application["productSourceBindings"]:
        blob, content = _git_blob(PRODUCT, binding["path"])
        assert blob == binding["gitBlob"]
        assert sha256(content).hexdigest() == binding["canonicalSha256"]

    main = _git_blob(PRODUCT, "frontend/src/field/main.tsx")[1].decode()
    field_app = _git_blob(PRODUCT, "frontend/src/field/FieldApp.tsx")[1].decode()
    scene = _git_blob(PRODUCT, "frontend/src/components/DroneLaunchScene.tsx")[1].decode()
    assert '<EditionThemeProvider edition="field">' in main
    assert "FieldSettingsDialog" in field_app
    assert "DroneLaunchScene" not in field_app
    assert "useEditionTheme" in scene
    assert "editionTheme.three" in scene
    assert application["uiContract"]["liveFieldThreeSceneExpected"] is False
    assert application["uiContract"]["sharedDroneLaunchSceneConsumesEditionThemeThree"] is True


def test_exact_counts_are_one_shot_and_all_external_authority_is_zero() -> None:
    application = _load(APPLICATION)
    counts = application["execution"]["exactCounts"]
    assert counts == {
        "visibleInstallerLanguageProbes": 2,
        "freshInstallerInvocations": 1,
        "overlayInstallerInvocations": 1,
        "applicationLaunches": 2,
        "shortcutLaunches": 1,
        "liveWebView2Inspections": 2,
        "settingsViewportInspections": 4,
        "languageTransitions": 2,
        "uninstallerInvocations": 1,
        "ownedPreferenceCleanupAttempts": 1,
        "ownedPreferenceCleanupInvocations": 1,
        "browserLaunches": 0,
        "oauthTransactions": 0,
        "accountOrTokenReads": 0,
        "artifactBuildsOrSigning": 0,
        "runtimeStartsOrMigrations": 0,
        "simulatorStarts": 0,
        "deviceOrHardwareActions": 0,
    }
    assert application["execution"]["lifecycleCountMaximum"] == 1
    assert application["execution"]["retryCountMaximum"] == 0
    assert application["execution"]["currentMessageAuthorizesExecution"] is False


def test_owned_paths_and_sim_protection_are_exact_and_fail_closed() -> None:
    application = _load(APPLICATION)
    paths = application["ownedPaths"]
    protected = application["protectedState"]

    assert paths["runRoot"].endswith("\\Field-Owned-Isolation\\560f574-attempt-1")
    assert paths["runRootMustBeAbsentAtStart"] is True
    assert paths["installRoot"] == "%LOCALAPPDATA%\\DroneDream-Field"
    assert paths["desktopShortcut"].endswith("DroneDream · FIELD.lnk")
    assert protected["simPreferenceKey"]["preparationStableJsonSha256"] == (
        "bf75c75edf429cfbf5f7aebd453768d9d6b36db82c0a0ba597b0146dbad426d5"
    )
    assert protected["simPreferenceKey"]["beforeMustMatchPreparation"] is True
    assert protected["simPreferenceKey"]["afterMustMatchBefore"] is True
    assert protected["otherEditionMutationAllowed"] is False
    assert protected["runtimeMutationAllowed"] is False
    assert protected["webView2MutationAllowed"] is False


def test_plan_is_honest_about_host_containment_and_remaining_release_gates() -> None:
    plan = _load(PLAN)
    assert plan["isolationBoundary"]["isVmGradeIsolation"] is False
    assert plan["isolationBoundary"]["sufficiencyClaim"] == (
        "bounded internal-test lifecycle validation only"
    )
    assert plan["dynamicUiContract"]["settingsViewport"] == {"width": 390, "height": 620}
    assert plan["dynamicUiContract"]["presentationOnly"] is True
    assert plan["dynamicUiContract"]["grantsHardwareAuthority"] is False
    assert plan["safety"]["validatedHardwarePackCount"] == 0
    assert plan["safety"]["hardwareDecision"] == "deny"
    assert plan["nonClaims"] == {
        "lifecycleExecuted": False,
        "lifecyclePassed": False,
        "releaseReady": False,
        "websiteReady": False,
        "websiteHandoffAllowed": False,
    }
