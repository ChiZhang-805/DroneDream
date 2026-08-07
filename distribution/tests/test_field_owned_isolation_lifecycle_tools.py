from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
RUNNER = LIFECYCLE / "run-field-owned-isolation-lifecycle.ps1"
INSTALLER_INSPECTOR = LIFECYCLE / "inspect-field-owned-installer-language.ps1"
WEBVIEW_INSPECTOR = LIFECYCLE / "inspect-field-owned-webview2.mjs"
LAUNCHER_INSPECTOR = LIFECYCLE / "inspect-field-owned-launcher.mjs"


def _parse_powershell(path: Path) -> None:
    escaped = str(path).replace("'", "''")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$tokens=$null;$errors=$null;"
                f"[Management.Automation.Language.Parser]::ParseFile('{escaped}',"
                "[ref]$tokens,[ref]$errors)|Out-Null;"
                "if($errors.Count){$errors|ForEach-Object{$_.Message};exit 1}"
            ),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_lifecycle_powershell_tools_parse() -> None:
    _parse_powershell(RUNNER)
    _parse_powershell(INSTALLER_INSPECTOR)


def test_webview_inspector_is_valid_javascript() -> None:
    for inspector in (WEBVIEW_INSPECTOR, LAUNCHER_INSPECTOR):
        result = subprocess.run(
            ["node.exe", "--check", str(inspector)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr


def test_plan_only_branch_precedes_all_host_lifecycle_reads_and_writes() -> None:
    source = RUNNER.read_text(encoding="utf-8-sig")
    plan_only = source.index("if ($PlanOnly) {")
    dynamic_artifact = source.index("$installerPath = $applicationContract.artifact.path")
    output_absence = source.index("Test-Path -LiteralPath $outputPath")
    registry_function = source.index("function Get-RegistryRecord")
    process_read = source.index("Get-Process -Name")
    output_create = source.index("New-Item -ItemType Directory -Path $outputPath")

    assert plan_only < dynamic_artifact
    assert plan_only < output_absence
    assert plan_only < registry_function
    assert plan_only < process_read
    assert plan_only < output_create
    for required_false in (
        "artifactRead = $false",
        "registryRead = $false",
        "processRead = $false",
        "outputRootCreated = $false",
        "installerStarted = $false",
        "applicationStarted = $false",
        "webView2Attached = $false",
    ):
        assert required_false in source


def test_runner_freezes_field_identity_counts_and_fail_closed_boundaries() -> None:
    source = RUNNER.read_text(encoding="utf-8-sig")
    for fragment in (
        '"560f574a95c8b51bbf34711bfd092d77fd3e166e"',
        '"DroneDream-Field"',
        '"io.dronedream.desktop.field"',
        "Field-Owned-Isolation",
        '"1033"; locale = "en"',
        '"2052"; locale = "zh-CN"',
        '@("/S") "fresh-install"',
        '@("/S", "/UPDATE") "same-version-overlay"',
        'Invoke-LiveInspection "overlay" $desktopShortcut $true',
        '"install-app-only"',
        '"failed-frozen-no-retry"',
        "Assert-UsableWebView2",
        "preparationStableJsonSha256",
        '"DroneDream $([char]0x00B7) SIM.lnk"',
        '"DroneDream $([char]0x00B7) LAB.lnk"',
    ):
        assert fragment in source
    for forbidden in (
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "wsl.exe",
        "PX4",
        "Gazebo",
        "Start-Service",
    ):
        assert forbidden not in source


def test_visible_installer_probe_has_bounded_navigation_but_never_installs() -> None:
    source = INSTALLER_INSPECTOR.read_text(encoding="utf-8-sig")
    assert 'Start-Process -FilePath $installerPath -ArgumentList "/LANG=$LanguageId"' in source
    assert "installActionInvoked = $false" in source
    assert "CloseMainWindow()" in source
    assert "Select-ExactLanguage" in source
    assert "boundedNextInvocations = 2" in source
    assert 'throw "Observer refuses to invoke an Install action."' in source
    assert 'Invoke-ProcessOnce' not in source


def test_webview_inspector_covers_field_ui_without_browser_or_provider_navigation() -> None:
    source = WEBVIEW_INSPECTOR.read_text(encoding="utf-8")
    for fragment in (
        "width: 390, height: 620",
        'data-settings-consumer="field-lightweight"',
        '"--dd-brand-start": "#ffc247"',
        '"--dd-brand-middle": "#ff754b"',
        '"--dd-brand-end": "#d746a5"',
        'presentationOnly !== "true"',
        'grantsHardwareAuthority !== "false"',
        "dialogClientHeight !== metrics.dialogScrollHeight",
        "panelClientHeight !== metrics.panelScrollHeight",
        "live3dRequired: false",
        "shared3dSourceBindingRequired: true",
        "forbiddenNetwork.length !== 0",
    ):
        assert fragment in source
    assert "page.goto(" not in source
    assert "launchPersistentContext" not in source


def test_launcher_inspector_covers_the_installed_3d_auth_boundary() -> None:
    source = LAUNCHER_INSPECTOR.read_text(encoding="utf-8")
    for fragment in (
        "width: 390, height: 620",
        '.field-launcher[data-authority="false"]',
        'aria-valuenow="100"',
        'canvas.drone-launch-canvas',
        'data-flight-state") === "starflight"',
        '"--dd-brand-start": "#ffc247"',
        '"--dd-brand-middle": "#ff754b"',
        '"--dd-brand-end": "#d746a5"',
        'authButtonClicked: false',
        'fieldAppEntered: false',
        'stage: "preclassification"',
        'forbiddenNetwork.length !== 0',
        'live3dInteractionObserved: true',
    ):
        assert fragment in source
    assert "page.goto(" not in source
    assert ".click();\n  const finalLocale" in source
