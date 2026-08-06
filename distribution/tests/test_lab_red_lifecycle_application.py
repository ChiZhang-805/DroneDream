from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLICATION_PATH = (
    ROOT
    / "distribution"
    / "editions"
    / "lab"
    / "lifecycle"
    / "red-debd064-app-only-application.v1.json"
)
BUILD_RECEIPT_PATH = (
    ROOT
    / "distribution"
    / "build-receipts"
    / "lab-preview-1.0.0-debd064-yellow-attempt6.exact-artifact.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_red_application_preserves_exact_artifact_source_separation() -> None:
    application = _load(APPLICATION_PATH)
    receipt = _load(BUILD_RECEIPT_PATH)

    assert application["state"] == "prepared-not-executed"
    assert application["sourceSeparation"]["artifactProductSourceCommit"] == (
        receipt["productSource"]["commit"]
    )
    assert application["sourceSeparation"]["preparationBaseCommit"] == (
        "e510933109b31133ccbf8a5cd4fe515ba3913b71"
    )
    assert application["sourceSeparation"]["applicationEvidenceIsArtifactSource"] is False
    assert application["sourceSeparation"]["productRuntimeSemanticsChanged"] is False
    assert application["artifact"]["sha256"] == receipt["artifact"]["sha256"]
    assert application["artifact"]["bytes"] == receipt["artifact"]["bytes"]
    assert application["artifact"]["mayBeRebuiltOrRelabeledByThisApplication"] is False


def test_red_application_limits_post_artifact_changes_to_tools_tests_and_receipt() -> None:
    application = _load(APPLICATION_PATH)

    assert application["sourceSeparation"]["allowedPostArtifactChangedPaths"] == [
        "desktop/scripts/build-windows-llvm.ps1",
        "desktop/scripts/release-build-driver.psm1",
        "desktop/scripts/verify-release-source-policy.mjs",
        "desktop/scripts/verify-updater-signing-contract.ps1",
        "distribution/build-receipts/lab-preview-1.0.0-debd064-yellow-attempt6.exact-artifact.json",
        "distribution/tests/test_shared_windows_build_contract.py",
    ]
    assert "desktop/src-tauri" in application["sourceSeparation"][
        "unchangedProductSurfaces"
    ]


def test_red_application_owns_only_the_lab_namespace() -> None:
    application = _load(APPLICATION_PATH)
    identity = application["identity"]
    owned = application["ownedMutationSurface"]

    assert identity["internalProductName"] == "DroneDream-Lab"
    assert identity["displayName"] == "DroneDream · LAB"
    assert identity["bundleIdentifier"] == "io.dronedream.desktop.lab"
    assert all("lab" in path.casefold() for path in owned["paths"])
    assert all("DroneDream-Lab" in key for key in owned["registryKeys"])
    assert owned["shortcutOwnershipRequiresExactTarget"] is True
    assert application["protectedState"]["parityRequiredAfterEveryStage"] is True


def test_red_application_has_one_shot_counts_and_no_high_risk_side_effects() -> None:
    application = _load(APPLICATION_PATH)
    counts = application["exactCounts"]

    assert counts == {
        "freshInstallerInvocations": 1,
        "overlayInstallerInvocations": 1,
        "applicationLaunches": 2,
        "uninstallerInvocations": 1,
        "oauthBoundaryChecks": 1,
        "realTokenExchanges": 0,
        "artifactBuilds": 0,
        "runtimeStarts": 0,
        "px4Starts": 0,
        "gazeboStarts": 0,
        "hardwareActions": 0,
    }
    assert application["rollback"]["stopAfterFirstFailureWithoutRetry"] is True
    assert application["protectedState"]["webView2InstallOrRepairAllowed"] is False
    assert application["protectedState"]["runtimeMutationAllowed"] is False


def test_red_application_fails_closed_without_disposable_oauth_boundary() -> None:
    application = _load(APPLICATION_PATH)
    oauth = application["oauthBoundary"]
    authorization = application["authorization"]

    assert oauth["redirectUri"] == (
        "http://127.0.0.1:49212/desktop-auth/lab/callback"
    )
    assert oauth["explicitUserGestureRequired"] is True
    assert oauth["crossEditionSessionAdoptionAllowed"] is False
    assert oauth["accountPasswordMayBeRead"] is False
    assert oauth["existingDefaultBrowserSessionMayBeUsedAutomatically"] is False
    assert oauth["providerTokenExchangeAllowed"] is False
    assert oauth["disposableBrowserOrProviderBoundaryProven"] is False
    assert authorization["executionDecision"] == "deny-before-mutation"
    assert authorization["executionBlockers"] == [
        "disposable-browser-or-provider-boundary-not-proven"
    ]


def test_red_application_keeps_zero_pack_hardware_actions_denied() -> None:
    application = _load(APPLICATION_PATH)
    safety = application["safety"]

    assert safety["validatedVehiclePackCount"] == 0
    assert safety["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert safety["requiredAuthorityLayers"] == ["native", "backend", "runtime"]
    assert safety["frontendOrWorkspaceCountsAsAuthority"] is False
