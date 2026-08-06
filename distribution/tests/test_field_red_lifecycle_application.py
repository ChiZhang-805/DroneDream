from __future__ import annotations

import json
import subprocess
import textwrap
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "red-edc7aa1-app-only-application.v1.json"
RUNNER = LIFECYCLE / "run-field-app-only-lifecycle.ps1"
INSPECTOR = LIFECYCLE / "inspect-field-live-webview2.mjs"
PREPARATION_RECEIPT = (
    LIFECYCLE / "red-edc7aa1-green-preparation-receipt.v1.json"
)


def _load() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _lf_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return sha256(content.encode()).hexdigest()


def test_application_binds_the_exact_frozen_field_artifact() -> None:
    application = _load()

    assert application["state"] == "prepared-not-authorized"
    assert application["sourceSeparation"]["artifactProductSourceCommit"] == (
        "edc7aa124e058fda3bb143dc66cd7c208a601cef"
    )
    assert application["artifact"]["filename"] == "DroneDream-Field-1.0.0.exe"
    assert application["artifact"]["bytes"] == 11_535_000
    assert application["artifact"]["sha256"] == (
        "b87a020df957aeca7b179779a2400a2dfeb0fc2d43e655aa5bf8969db7c46dbd"
    )
    assert application["artifact"]["buildReceipt"]["sha256"] == (
        "f399fc6805e959f6acca434016a29f6348b689a43132007e5dcd02f9644e7e31"
    )
    assert application["artifact"]["authenticodeState"] == "NotSigned"


def test_application_owns_only_field_paths_and_one_fresh_output() -> None:
    application = _load()
    identity = application["identity"]
    tools = application["executionTools"]

    assert identity["displayName"] == "DroneDream · FIELD"
    assert identity["bundleId"] == "io.dronedream.desktop.field"
    assert identity["installRoot"] == "%LOCALAPPDATA%\\DroneDream-Field"
    assert all(
        "field" in identity[name].casefold()
        for name in (
            "installRoot",
            "uninstallKey",
            "productPreferenceKey",
            "roamingData",
            "localData",
            "desktopShortcut",
            "startMenuShortcut",
        )
    )
    assert tools["requestedOwnedOutputRoot"].endswith(
        "\\Field-RED\\edc7aa1-segment-a-attempt-1"
    )
    assert tools["outputRootMustNotExistBeforeStart"] is True


def test_segment_a_has_exact_one_shot_counts_and_zero_hardware() -> None:
    application = _load()
    counts = application["segments"]["a"]["exactCounts"]

    assert counts["freshInstallerInvocations"] == 1
    assert counts["overlayInstallerInvocations"] == 1
    assert counts["applicationLaunches"] == 2
    assert counts["shortcutLaunches"] == 1
    assert counts["uninstallerInvocations"] == 1
    assert counts["ownedPreferenceKeyCleanupAttempts"] == 1
    assert counts["ownedPreferenceKeyCleanupInvocations"] == 1
    assert counts["liveWebView2Inspections"] == 2
    assert counts["languageTransitions"] == 2
    for name in (
        "browserLaunches",
        "oauthBoundaryChecks",
        "accountReads",
        "tokenReadsOrExchanges",
        "artifactBuilds",
        "runtimeStarts",
        "px4Starts",
        "gazeboStarts",
        "deviceEnumerationInvocations",
        "serialUsbWrites",
        "parameterWrites",
        "armCommands",
        "flightCommands",
        "hardwareActions",
    ):
        assert counts[name] == 0


def test_field_preference_cleanup_is_exact_once_and_fail_closed() -> None:
    application = _load()
    cleanup = application["ownedPreferenceCleanup"]

    assert cleanup["allowedKey"].endswith("\\DroneDream-Field")
    assert cleanup["allowedExactValues"] == {
        "(default)": "%LOCALAPPDATA%\\DroneDream-Field",
        "DroneDreamRuntimeDrive": "",
        "DroneDreamRuntimeInstallMode": "install-app-only",
        "DroneDreamRuntimeOperationProtocol": "2",
    }
    assert cleanup["maximumCleanupAttempts"] == 1
    assert cleanup["maximumSuccessfulCleanupInvocations"] == 1
    for decision in (
        "missingValueDecision",
        "extraValueDecision",
        "valueDriftDecision",
        "otherEditionKeyDecision",
        "sharedParentDeletionDecision",
    ):
        assert cleanup[decision] == "deny"


def test_protected_sim_key_requires_byte_exact_before_after_parity() -> None:
    application = _load()
    protected = application["protectedState"]
    expected = "ef59eb8105ccef5db3c0ba45a933ee8bbf582255d498104b2928b9f5ef8eab8d"

    assert protected["simProductPreferenceKey"].endswith("\\DroneDream-Sim")
    assert protected["simExportBefore"] == {
        "path": (
            "C:\\Users\\zju20\\AppData\\Local\\DroneDream-Codex\\"
            "Field-RED-Applications\\edc7aa1-green-prep-20260806T153502Z\\"
            "protected-sim-product-key-before.reg"
        ),
        "bytes": 572,
        "sha256": expected,
    }
    assert protected["requiredSimExportAfter"]["sha256"] == expected
    assert protected["requiredSimExportAfter"]["state"].startswith("require-")
    assert protected["otherEditionMutationAllowed"] is False
    assert protected["sharedParentDeletionAllowed"] is False


def test_real_oauth_is_a_separate_blocked_segment() -> None:
    application = _load()
    oauth = application["segments"]["b"]
    authorization = application["authorization"]

    assert oauth["state"] == "blocked-not-part-of-segment-a"
    assert oauth["callback"] == (
        "http://127.0.0.1:49213/desktop-auth/field/callback"
    )
    assert oauth["credentialNamespace"] == "DroneDream/Auth/field/v1"
    assert oauth["explicitFieldTransactionRequired"] is True
    assert oauth["otherEditionSessionReuseAllowed"] is False
    assert authorization["segmentAExecutionDecision"] == (
        "prepared-awaiting-new-exact-red-authorization"
    )
    assert authorization["segmentBExecutionDecision"] == (
        "deny-before-real-auth-boundary"
    )
    assert authorization["currentMessageAuthorizesExecution"] is False


def test_tools_match_application_hashes_and_static_boundaries() -> None:
    application = _load()
    runner = RUNNER.read_text(encoding="utf-8-sig")
    inspector = INSPECTOR.read_text(encoding="utf-8")

    assert _lf_sha256(RUNNER) == application["executionTools"]["runner"][
        "lfNormalizedSha256"
    ]
    assert _lf_sha256(INSPECTOR) == application["executionTools"][
        "liveWebView2Inspector"
    ]["lfNormalizedSha256"]
    for fragment in (
        '"DroneDream-Field"',
        '"io.dronedream.desktop.field"',
        "$protectedSimProductKey",
        "$expectedProtectedSimSha256",
        "$script:ownedPreferenceCleanupAttempted",
        "Export-ProtectedSimProductKey",
        '-LaunchPath $desktopShortcut -IsShortcutLaunch $true',
        "segment-a-failed-no-retry",
        '@("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab")',
    ):
        assert fragment in runner
    field_in_protected_set = (
        '@("DroneDream", "DroneDream-Universal", "DroneDream-Sim", '
        '"DroneDream-Field")'
    )
    assert field_in_protected_set not in runner
    for forbidden in (
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "wsl.exe",
        "PX4",
        "Gazebo",
    ):
        assert forbidden not in runner
    assert '.app-shell[data-brand-edition="field"]' in inspector
    assert "brand.naturalWidth !== 2581" in inspector
    assert "safety.validatedCount !== \"0\"" in inspector
    assert "page.goto(" not in inspector


def test_preference_value_validator_accepts_only_the_exact_field_fixture() -> None:
    runner = str(RUNNER).replace("'", "''")
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
        $root = 'C:\\Users\\fixture\\AppData\\Local\\DroneDream-Field'
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
            '(default)' = 'C:\\Users\\fixture\\AppData\\Local\\DroneDream-Sim'
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-app-only'
            DroneDreamRuntimeOperationProtocol = '2'
          }},
          [ordered]@{{
            '(default)' = $root
            DroneDreamRuntimeDrive = ''
            DroneDreamRuntimeInstallMode = 'install-all'
            DroneDreamRuntimeOperationProtocol = '2'
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
        Write-Output 'field-owned-preference-fixtures-passed'
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
    assert "field-owned-preference-fixtures-passed" in result.stdout


def test_green_receipt_is_honest_about_the_dynamic_start_blocker() -> None:
    application = _load()
    receipt = json.loads(PREPARATION_RECEIPT.read_text(encoding="utf-8"))

    assert receipt["decision"] == "prepared-conditional-deny-execution"
    assert receipt["application"]["sha256"] == _sha256(APPLICATION)
    assert receipt["tools"]["runner"]["lfNormalizedSha256"] == _lf_sha256(
        RUNNER
    )
    assert receipt["tools"]["liveWebView2Inspector"][
        "lfNormalizedSha256"
    ] == _lf_sha256(INSPECTOR)
    assert receipt["dynamicStartGate"]["droneDreamDesktopProcessCount"] == 1
    assert receipt["dynamicStartGate"]["protectedProcessPath"].endswith(
        "\\DroneDream-Universal\\drone-dream-desktop.exe"
    )
    assert receipt["authorization"]["redStartSignalRecorded"] is False
    assert receipt["authorization"]["segmentAExecutionAllowed"] is False
    assert receipt["protectedSimProductKey"]["requiredAfter"]["observed"] is False
    assert application["nonClaims"]["lifecyclePassed"] is False
