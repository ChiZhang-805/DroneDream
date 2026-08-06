from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ROOT / "desktop/scripts/verify-universal-real-oauth.ps1"
OBSERVER = ROOT / "frontend/scripts/verify-installed-universal-oauth.mjs"


def test_oauth_tool_is_source_bound_and_plan_only_by_default() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    assert "if (-not $Execute)" in text
    assert "executionAuthorized = $false" in text
    assert 'Get-GitText @("status", "--porcelain")' in text
    assert "ExpectedPlanSha256" in text
    assert "Refusing to overwrite an existing OAuth execution root" in text
    assert "Product source is not an ancestor" in text


def test_oauth_plan_binds_all_prior_success_gates_and_exact_caps() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    for gate in ("LifecycleReceipt", "VisibleInstallerReceipt", "InstalledAppReceipt"):
        assert gate in text
    for exact in (
        "installerFreshSilentNoShortcut = 1",
        "appLaunch = 1",
        "runtimeStartMax = 1",
        "credentialVaultRestoreProbeMax = 1",
        "loginButton = 1",
        "oauthTransaction = 1",
        "callback = 1",
        "authorizationCodeExchange = 1",
        "localLogout = 1",
        "appClose = 1",
        "isolatedUninstaller = 1",
        "ownedCleanupMax = 1",
    ):
        assert exact in text
    assert "providerRetryCap = 0" in text
    assert "browserCredentialInputCap = 0" in text
    assert "browserPasswordStoreReadCap = 0" in text
    assert "Universal OAuth execution counts drifted from the frozen bounded plan" in text


def test_runtime_prerequisite_is_existing_start_only_and_physics_stays_off() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    assert "requiredBeforeLogin = $runtimeRequired" in text
    assert "startExistingRuntimeCap = 1" in text
    assert "installUpgradeMigrationRepairConfigurationCap = 0" in text
    assert "runtimeBaseReplacementCap = 0" in text
    assert "wslRegisterUnregisterCap = 0" in text
    assert "px4GazeboSitlHitlCap = 0" in text
    assert "restorePreRunState = $true" in text
    assert "Assert-ProtectedStateUnchanged" in text
    assert "Successful Universal OAuth validation" in text


def test_observer_is_bounded_and_never_owns_or_logs_the_external_browser() -> None:
    text = OBSERVER.read_text(encoding="utf-8")
    assert 'chromium.connectOverCDP(cdpEndpoint)' in text
    assert "browser.close()" in text
    assert "await browser.close" not in text
    assert 'counts.runtimeStart, 1' in text
    assert "counts.loginButton += 1" in text
    assert "counts.oauthTransaction += 1" in text
    assert "counts.localLogout += 1" in text
    for forbidden in ("access_token", "refresh_token", "password", "cookie", "requestId"):
        assert forbidden not in text


def test_receipt_uses_allowlisted_native_audit_hashes_and_local_logout() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    assert "Browser-auth audit contains non-allowlisted fields" in text
    assert 'result -ceq "authorized"' in text
    assert 'result -ceq "no_saved_session"' in text
    assert 'callbackTransport -ceq "loopback-http"' in text
    assert 'result -ceq "local_logout"' in text
    assert 'callbackTransport -ceq "native-command"' in text
    assert "subjectHash" in text
    assert "rawCallbackRecorded = $false" in text
    assert "credentialsRecorded = $false" in text
    assert "authorization code" not in text.lower()


def test_failure_policy_uses_only_edition_owned_cleanup_and_zero_retry() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    assert 'Join-Path $env:LOCALAPPDATA "DroneDream-Universal"' in text
    assert '"HKCU:\\Software\\DroneDream\\DroneDream-Universal"' in text
    assert "rollbackWithOwnUninstallerOnly = $true" in text
    assert "preserveFailureEvidence = $true" in text
    assert "retryCap = 0" in text
    assert "Remove-Item -LiteralPath $productKey" in text
    assert "Remove-Item -LiteralPath $webViewProfileRoot" in text
    assert "Remove-Item -LiteralPath $auditRoot" not in text
