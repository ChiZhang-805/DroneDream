from __future__ import annotations

import json
import subprocess
import textwrap
from hashlib import sha256
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
RUNNER_PATH = APPLICATION_PATH.with_name("run-lab-app-only-lifecycle.ps1")
INSPECTOR_PATH = APPLICATION_PATH.with_name("inspect-lab-live-webview2.mjs")
FAILURE_RECEIPT_PATH = (
    ROOT
    / "distribution"
    / "build-receipts"
    / "lab-debd064-red-segment-a1-failure.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _lf_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return sha256(content.encode()).hexdigest()


def test_red_application_preserves_exact_artifact_source_separation() -> None:
    application = _load(APPLICATION_PATH)
    receipt = _load(BUILD_RECEIPT_PATH)

    assert application["state"] == (
        "segment-a2-prepared-not-authorized-segment-b-blocked"
    )
    assert application["sourceSeparation"]["artifactProductSourceCommit"] == (
        receipt["productSource"]["commit"]
    )
    assert application["sourceSeparation"]["preparationBaseCommit"] == (
        "0d1184723c0ed807c6fb1abf98f408c1a66d43c0"
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
    segment_a = application["segments"]["a"]
    counts = segment_a["exactCounts"]

    assert counts == {
        "freshInstallerInvocations": 1,
        "overlayInstallerInvocations": 1,
        "applicationLaunches": 2,
        "uninstallerInvocations": 1,
        "ownedPreferenceKeyCleanupInvocations": 1,
        "liveWebView2Inspections": 2,
        "languageTransitions": 2,
        "browserLaunches": 0,
        "oauthBoundaryChecks": 0,
        "accountReads": 0,
        "tokenReadsOrExchanges": 0,
        "artifactBuilds": 0,
        "runtimeStarts": 0,
        "px4Starts": 0,
        "gazeboStarts": 0,
        "hardwareActions": 0,
    }
    assert segment_a["browserLaunchAllowed"] is False
    assert segment_a["oauthAllowed"] is False
    assert segment_a["accountOrTokenAccessAllowed"] is False
    assert application["rollback"]["stopAfterFirstFailureWithoutRetry"] is True
    assert application["protectedState"]["webView2InstallOrRepairAllowed"] is False
    assert application["protectedState"]["runtimeMutationAllowed"] is False


def test_red_application_splits_oauth_without_blocking_app_only_lifecycle() -> None:
    application = _load(APPLICATION_PATH)
    oauth = application["oauthBoundary"]
    authorization = application["authorization"]
    segment_b = application["segments"]["b"]

    assert oauth["redirectUri"] == (
        "http://127.0.0.1:49212/desktop-auth/lab/callback"
    )
    assert oauth["explicitUserGestureRequired"] is True
    assert oauth["crossEditionSessionAdoptionAllowed"] is False
    assert oauth["accountPasswordMayBeRead"] is False
    assert oauth["existingDefaultBrowserSessionMayBeUsedAutomatically"] is False
    assert oauth["providerTokenExchangeAllowed"] is False
    assert oauth["disposableBrowserOrProviderBoundaryProven"] is False
    assert authorization["segmentAExecutionDecision"] == (
        "prepared-awaiting-new-exact-red-authorization"
    )
    assert authorization["segmentAExecutionBlockers"] == [
        "new-exact-red-authorization-not-recorded"
    ]
    assert authorization["segmentBExecutionDecision"] == (
        "deny-before-real-auth-boundary"
    )
    assert authorization["segmentBExecutionBlockers"] == [
        "disposable-browser-or-provider-boundary-not-proven"
    ]
    assert authorization["segmentBMayBlockSegmentA"] is False
    assert segment_b["blocksSegmentA"] is False
    assert all(
        count == 0
        for count in segment_b["exactCountsBeforeSeparateAuthorization"].values()
    )


def test_red_application_keeps_zero_pack_hardware_actions_denied() -> None:
    application = _load(APPLICATION_PATH)
    safety = application["safety"]

    assert safety["validatedVehiclePackCount"] == 0
    assert safety["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert safety["requiredAuthorityLayers"] == ["native", "backend", "runtime"]
    assert safety["frontendOrWorkspaceCountsAsAuthority"] is False


def test_segment_a_runner_binds_exact_artifact_and_owned_namespaces() -> None:
    application = _load(APPLICATION_PATH)
    runner = RUNNER_PATH.read_text(encoding="utf-8-sig")

    assert _lf_sha256(RUNNER_PATH) == application["executionTools"]["runner"][
        "lfNormalizedSha256"
    ]

    for fragment in (
        '"debd0647c5883ffe5c9c52037d35a6b567d9fd62"',
        '"DroneDream-Lab"',
        '"io.dronedream.desktop.lab"',
        '"prepared-awaiting-new-exact-red-authorization"',
        '"deny-before-real-auth-boundary"',
        'Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S")',
        'Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S", "/UPDATE")',
        'Invoke-ProcessOnce -Executable $uninstaller -Arguments @("/S")',
        "Assert-ProtectedParity",
        "Assert-OwnedProductPreferenceValues",
        "Assert-AndRemoveOwnedProductPreferenceKey",
        "Remove-OwnedAppData",
        "segment-a-failed-no-retry",
    ):
        assert fragment in runner

    for forbidden in (
        "Start-Process -FilePath $env:ComSpec",
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "wsl.exe",
        "PX4",
        "Gazebo",
    ):
        assert forbidden not in runner


def test_live_webview2_inspector_switches_language_without_auth_or_browser() -> None:
    application = _load(APPLICATION_PATH)
    inspector = INSPECTOR_PATH.read_text(encoding="utf-8")

    assert _lf_sha256(INSPECTOR_PATH) == application["executionTools"][
        "liveWebView2Inspector"
    ]["lfNormalizedSha256"]

    for fragment in (
        "chromium.connectOverCDP(endpoint)",
        '.app-shell[data-brand-edition="lab"]',
        '.launcher-language-options button',
        'img.brand-lockup[data-brand-edition="lab"]',
        "forbiddenAuthRequestCount: 0",
        "browserLaunchCount: 0",
        "oauthBoundaryCheckCount: 0",
        "tokenReadOrExchangeCount: 0",
    ):
        assert fragment in inspector
    assert "page.goto(" not in inspector
    assert "page.getByRole(\"button\", { name: /sign in/i" not in inspector


def test_first_segment_a_attempt_is_frozen_failed_without_retry() -> None:
    receipt = _load(FAILURE_RECEIPT_PATH)

    assert receipt["result"] == "failed-no-retry"
    assert receipt["productSource"]["commit"] == (
        "debd0647c5883ffe5c9c52037d35a6b567d9fd62"
    )
    assert receipt["artifact"]["sha256"] == (
        "b5969f2f287cf729450618e6d3a8232f426b1ac4cbe5c3662904d31bab215a48"
    )
    assert receipt["failure"]["classification"] == (
        "edition-lifecycle-validator-policy-mismatch"
    )
    assert receipt["failure"]["artifactInvalidatedByThisFailure"] is False
    assert receipt["rollback"]["ownedProductKeyAbsentAfterCleanup"] is True
    assert receipt["rollback"][
        "protectedOtherEditionsRuntimeAndWebView2Parity"
    ] is True
    assert receipt["oauthSegmentB"]["state"] == "fail-closed-not-executed"
    assert receipt["retry"] == {
        "performed": False,
        "authorized": False,
        "requiresNewExactApplicationAndSeparateReport": True,
    }
    assert receipt["releaseReady"] is False
    assert receipt["websiteHandoffReady"] is False


def test_a2_binds_a1_and_limits_owned_preference_cleanup() -> None:
    application = _load(APPLICATION_PATH)
    a1 = application["a1Evidence"]
    cleanup = application["rollback"]["ownedProductPreferenceCleanup"]

    assert a1 == {
        "attemptId": "debd064-segment-a-red1-20260806T143000Z",
        "result": "failed-no-retry",
        "functionalStagesPassed": True,
        "failureClassification": "edition-lifecycle-validator-policy-mismatch",
        "receiptPath": (
            "distribution/build-receipts/"
            "lab-debd064-red-segment-a1-failure.json"
        ),
        "receiptSha256": (
            "a2617487a629a8850abc979a6ca75e99fc95f1558b8b221fa55bda82b7ec6cd7"
        ),
        "externalReceiptSha256": (
            "1626d92d04d2235fe897bd289877960c2ec4365d70eaffbc4b4c80110ff5a2f2"
        ),
        "rollbackRestoredFreshState": True,
        "retryPerformed": False,
    }
    assert cleanup["allowed"] is True
    assert cleanup["maximumInvocations"] == 1
    assert cleanup["exactRegistryKey"] == (
        "HKCU/Software/DroneDream/DroneDream-Lab"
    )
    assert cleanup["exactValueNames"] == [
        "(default)",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeOperationProtocol",
    ]
    assert cleanup["exactValues"] == {
        "(default)": "%LOCALAPPDATA%/DroneDream-Lab",
        "DroneDreamRuntimeDrive": "",
        "DroneDreamRuntimeInstallMode": "install-app-only",
        "DroneDreamRuntimeOperationProtocol": "2",
    }
    assert cleanup["extraValueDecision"] == "deny"
    assert cleanup["missingValueDecision"] == "deny"
    assert cleanup["otherEditionKeyDecision"] == "deny"
    assert cleanup["sharedParentDeletionAllowed"] is False


def test_a2_owned_preference_value_validator_denies_drift() -> None:
    runner = str(RUNNER_PATH).replace("'", "''")
    script = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null
        $errors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile(
          '{runner}', [ref]$tokens, [ref]$errors
        )
        if ($errors.Count -ne 0) {{ throw 'runner AST failed' }}
        $function = $ast.Find({{
          param($node)
          $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Assert-OwnedProductPreferenceValues'
        }}, $true)
        if ($null -eq $function) {{ throw 'validator function missing' }}
        Invoke-Expression $function.Extent.Text
        $root = 'C:\\Users\\fixture\\AppData\\Local\\DroneDream-Lab'
        $good = [ordered]@{{
          '(default)' = $root
          DroneDreamRuntimeDrive = ''
          DroneDreamRuntimeInstallMode = 'install-app-only'
          DroneDreamRuntimeOperationProtocol = '2'
        }}
        Assert-OwnedProductPreferenceValues -Values $good -ExpectedInstallRoot $root
        $cases = @(
          [ordered]@{{
            '(default)' = $root
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-app-only'
          }},
          [ordered]@{{
            '(default)' = $root
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-app-only'
            DroneDreamRuntimeOperationProtocol = '2'
            Unexpected = 'deny'
          }},
          [ordered]@{{
            '(default)' = 'C:\\Users\\fixture\\AppData\\Local\\DroneDream-Field'
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-app-only'
            DroneDreamRuntimeOperationProtocol = '2'
          }},
          [ordered]@{{
            '(default)' = $root
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-all'
            DroneDreamRuntimeOperationProtocol = '2'
          }},
          [ordered]@{{
            '(default)' = $root
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-app-only'
            DroneDreamRuntimeOperationProtocol = '3'
          }}
        )
        foreach ($case in $cases) {{
          $denied = $false
          try {{
            Assert-OwnedProductPreferenceValues -Values $case -ExpectedInstallRoot $root
          }} catch {{
            $denied = $true
          }}
          if (-not $denied) {{ throw 'drift fixture was accepted' }}
        }}
        Write-Output 'owned-preference-fixtures-passed'
        """
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "owned-preference-fixtures-passed" in result.stdout
