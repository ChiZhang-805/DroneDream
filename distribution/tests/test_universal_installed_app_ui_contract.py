from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ROOT / "desktop/scripts/verify-universal-installed-app-ui.ps1"
BROWSER = ROOT / "frontend/scripts/verify-installed-universal-ui.mjs"
OFFLINE_BROWSER = ROOT / "frontend/scripts/verify-software-ui-layout.mjs"


def test_headed_verifier_has_exact_bounded_execution_contract() -> None:
    script = POWERSHELL.read_text(encoding="utf-8-sig")
    for fragment in (
        'DroneDream-Universal-1.0.0.exe',
        '$installerCountCap = 1',
        '$appLaunchCountCap = 1',
        '$appCloseCountCap = 1',
        '$uninstallerCountCap = 1',
        '$ownedCleanupCountCap = 1',
        '@("/S", "/NS", "/L=1033")',
        'settingsOpen = $matrix.Count',
        'settingsTabActivations = $matrix.Count * 4',
        'screenshots = $matrix.Count * 2',
        'runtimeStart = 0',
        'px4 = 0',
        'gazebo = 0',
        'browser = 0',
        'auth = 0',
        'offline-layout-contract-only-not-installed-app-evidence',
        'reviewedEvidenceHead = $head',
        'presentationOnly = $true',
        'grantsHardwareAuthority = $false',
        'modeSwitchMayAuthorizeHardware = $false',
        'loopback-cdp-parent-child-read-only-existing-runtime',
        'closeOnlyThisBatchApp = $true',
        'invokeOnlyThisBatchUninstaller = $true',
        'retryAllowed = $false',
        'WEBVIEW2_USER_DATA_FOLDER',
        'webview2-profile',
        r'distribution\desktop\edition-coexistence.v1.json',
        '$expectedEditionIds = @("universal", "sim", "lab", "field", "autonomy")',
        '$otherEditionContracts',
        'otherEditions = @(',
        'Convert-CoexistenceFilePath',
        'Convert-CoexistenceRegistryPath',
        'io.dronedream.desktop.$editionId',
        'credentialVaultNamespace',
        'Invoke-IsolatedUninstallerOnce',
        'Invoke-OwnedCleanupOnce',
        'Close-ThisBatchAppOnce',
        'if (-not $Execute)',
        'Refusing to overwrite an existing installed-app execution root.',
    ):
        assert fragment in script
    assert "tauri build" not in script
    assert "cargo build" not in script
    assert "wsl.exe" not in script
    assert "Start-Px4" not in script
    assert "gz sim" not in script
    assert "OPENAI_API_KEY" not in script
    assert "SUPABASE_SERVICE_ROLE" not in script


def test_headed_verifier_protects_every_non_universal_edition_namespace() -> None:
    script = POWERSHELL.read_text(encoding="utf-8-sig")
    for edition in ("sim", "lab", "field", "autonomy"):
        assert f'"{edition}"' in script
    for protected_surface in (
        "installRoot = Get-DirectoryRecord",
        "application = Get-FileRecord",
        "uninstaller = Get-FileRecord",
        "uninstallRegistration = Get-RegistryRecord",
        "productRegistration = Get-RegistryRecord",
        "desktopShortcut = Get-ShortcutRecord",
        "startMenuShortcut = Get-ShortcutRecord",
        "webViewData = Get-DirectoryRecord",
    ):
        assert protected_surface in script
    assert "Desktop edition coexistence identities drifted." in script
    assert "Edition install root escaped the LOCALAPPDATA contract." in script
    assert "Edition registry path escaped the HKCU Software contract." in script


def test_headed_browser_observer_covers_pre_auth_without_bypassing_account_gate() -> None:
    script = BROWSER.read_text(encoding="utf-8")
    for fragment in (
        'chromium.connectOverCDP(cdpEndpoint)',
        'launcherUrl.hash = "/desktop/setup"',
        'assert.equal(edition, "universal")',
        'The pre-auth prerequisite intentionally stays on the Universal launcher.',
        'startupTheme',
        'validationSurface: authenticatedWorkspace '
        '? "authenticated-workspace" : "pre-auth-launcher"',
        'drone-dream:locale',
        'data-theme-grants-hardware-authority',
        'data-grants-hardware-authority',
        'assert.equal(theme.grantsHardwareAuthority, "false")',
        'assert.equal(scene.grantsHardwareAuthority, "false")',
        'assert.equal(await tabs.count(), 4',
        'measurement.dialogScrollHeight <= measurement.dialogClientHeight + 1',
        'measurement.panelScrollHeight <= measurement.panelClientHeight + 1',
        'await settingsButton.press("Enter")',
        'async function visibleSettingsButton(page)',
        '".app-mobile-menu-button:visible"',
        '".app-mobile-settings-entry:visible"',
        'await menuButton.click()',
        '".app-mobile-menu-panel.is-open:visible"',
        'assert.equal(await menuButton.getAttribute("aria-expanded"), "true")',
        'async function assertAuthenticatedAccountSurface(page)',
        'await workspaceModeSelector.selectOption(edition)',
        'assert.equal(await workspaceModeSelector.inputValue(), edition)',
        'prevents each case from inheriting the previous case\'s language',
        'menuPanel.locator(".app-account-button:visible")',
        'await menuPanel.waitFor({ state: "hidden", timeout: 30_000 })',
        'await closeButton.press("Enter")',
        'const emulateViewport = args.get("--emulate-viewport") === "true"',
        'await page.setViewportSize({ width: expectedWidth, height: expectedHeight })',
        'cdp-emulated-installed-webview',
    ):
        assert fragment in script
    assert "CDP must remain loopback-only" in script
    assert "must never own or terminate the app" in script
    assert "await browser.close()" not in script
    assert "window.location.assign(nextRoute)" not in script
    assert 'window.history.replaceState({}, "", "/desktop/setup")' not in script
    assert 'if (authenticatedWorkspace)' in script
    assert 'universal: "/vehicle-studio"' in script
    assert "password" not in script.lower()
    assert "token" not in script.lower()
    assert "requestId" not in script

    powershell = POWERSHELL.read_text(encoding="utf-8-sig")
    assert "$Process.Kill()" in powershell
    assert "$Process.Kill($true)" not in powershell


def test_ui_verifiers_use_the_current_universal_workspace_storage_contract() -> None:
    script = BROWSER.read_text(encoding="utf-8")
    assert 'dronedream:universal-workspace:v2' not in script
    assert 'dronedream:universal-mode:v1' not in script

    offline = OFFLINE_BROWSER.read_text(encoding="utf-8")
    assert 'dronedream:universal-workspace:v2' in offline
    assert 'testCase.edition === "universal"' in offline
    assert '"/vehicle-studio"' in offline


def test_headed_plan_matrix_is_two_sizes_two_locales_on_the_universal_launcher() -> None:
    script = POWERSHELL.read_text(encoding="utf-8-sig")
    assert '[ordered]@{ id = "minimum"; width = 390; height = 700 }' in script
    assert '[ordered]@{ id = "desktop"; width = 1440; height = 900 }' in script
    assert '@("en", "zh-CN")' in script
    assert 'presentationEdition = "universal"' in script
    assert 'authenticatedWorkspaceMatrixDeferredToOAuthReceipt = $true' in script


def test_headed_tools_parse_without_execution() -> None:
    powershell_parse = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$null=$errors=$tokens=$null; "
                f"[Management.Automation.Language.Parser]::ParseFile('{POWERSHELL}',"
                "[ref]$tokens,[ref]$errors)|Out-Null; "
                "if($errors.Count){$errors|% Message;exit 1}"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert powershell_parse.returncode == 0, powershell_parse.stderr or powershell_parse.stdout

    node_parse = subprocess.run(
        ["node", "--check", str(BROWSER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert node_parse.returncode == 0, node_parse.stderr or node_parse.stdout


def test_offline_layout_receipt_remains_exact_and_non_substitutive() -> None:
    receipt = ROOT / (
        "artifacts/test-runs/common-ui-theme-settings-4933e21-exact/"
        "software-ui-layout-receipt.json"
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload
    script = POWERSHELL.read_text(encoding="utf-8-sig")
    assert "ExpectedOfflineLayoutReceiptSha256" in script
    assert "offline-layout-contract-only-not-installed-app-evidence" in script
