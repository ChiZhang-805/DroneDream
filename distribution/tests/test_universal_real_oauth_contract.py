from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ROOT / "desktop/scripts/verify-universal-real-oauth.ps1"
OBSERVER = ROOT / "frontend/scripts/verify-installed-universal-oauth.mjs"
RUNTIME_INSTALLER = ROOT / "desktop/src-tauri/src/runtime_installer.rs"


def test_oauth_tool_is_source_bound_and_plan_only_by_default() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    assert "if (-not $Execute)" in text
    assert "executionAuthorized = $false" in text
    assert 'Get-GitText @("status", "--porcelain")' in text
    assert "ExpectedPlanSha256" in text
    assert "Refusing to overwrite an existing validation execution root" in text
    assert "Product source is not an ancestor" in text


def test_oauth_plan_binds_all_prior_success_gates_and_exact_caps() -> None:
    text = POWERSHELL.read_text(encoding="utf-8")
    for gate in ("LifecycleReceipt", "VisibleInstallerReceipt", "InstalledAppReceipt"):
        assert gate in text
    for exact in (
        "installerFreshSilentNoShortcut = 1",
        "appLaunch = 1",
        "runtimeStartMax = 1",
        "appClose = 1",
        "isolatedUninstaller = 1",
        "ownedCleanupMax = 1",
    ):
        assert exact in text
    assert "providerRetryCap = 0" in text
    assert "browserCredentialInputCap = 0" in text
    assert "browserPasswordStoreReadCap = 0" in text
    for exact in (
        "credentialVaultRestoreProbeMax",
        "loginButton",
        "oauthTransaction",
        "callback",
        "authorizationCodeExchange",
        "localLogout",
    ):
        assert f"{exact} = if ($runtimeDiagnosisOnly) {{ 0 }} else {{ 1 }}" in text
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


def test_attempts_are_durable_before_side_effects_and_runtime_failure_is_bounded() -> None:
    observer = OBSERVER.read_text(encoding="utf-8")
    powershell = POWERSHELL.read_text(encoding="utf-8")

    runtime_increment = observer.index("counts.runtimeStart += 1")
    runtime_checkpoint = observer.index('await persist("runtime-start-attempted")')
    runtime_click = observer.index('await primary.press("Enter")', runtime_checkpoint)
    assert runtime_increment < runtime_checkpoint < runtime_click

    oauth_increment = observer.index("counts.oauthTransaction += 1")
    oauth_checkpoint = observer.index('await persist("oauth-attempted")')
    oauth_click = observer.index('await primary.press("Enter")', oauth_checkpoint)
    assert oauth_increment < oauth_checkpoint < oauth_click

    logout_increment = observer.index("counts.localLogout += 1")
    logout_checkpoint = observer.index('await persist("local-logout-attempted")')
    logout_click = observer.index('await signOut.press("Enter")')
    assert logout_increment < logout_checkpoint < logout_click

    assert '.querySelectorAll(".alert-body code")' in observer
    for code in (
        "runtime_service_unhealthy",
        "runtime_host_connectivity",
        "runtime_health_unknown",
        "runtime_maintenance_deadline_exceeded",
        "runtime_operation_busy",
        "runtime_update_quiesce_active",
        "runtime_start_pending_timeout",
    ):
        assert code in observer

    assert "function Import-ObserverCheckpoint" in powershell
    finally_block = powershell.index("finally {", powershell.index("& node $nodeVerifier"))
    assert powershell.index("Import-ObserverCheckpoint $observerPath", finally_block) > finally_block
    assert 'rawRuntimeErrorRecorded = $false' in powershell

    app_close_increment = powershell.index("$counts.appClose++")
    app_close_checkpoint = powershell.index('Save-ExecutionCheckpoint "app-close-attempted"')
    app_close_action = powershell.index("$app.CloseMainWindow()", app_close_checkpoint)
    assert app_close_increment < app_close_checkpoint < app_close_action


def test_native_runtime_maintenance_preserves_machine_failure_code() -> None:
    text = RUNTIME_INSTALLER.read_text(encoding="utf-8")
    assert "fn runtime_maintenance_error_for_ipc" in text
    assert '.map_err(runtime_maintenance_error_for_ipc)?' in text
    assert 'format!("{}: {}", error.code, error.message)' in text
    assert "runtime_maintenance_ipc_error_preserves_bounded_machine_code" in text


def test_runtime_diagnosis_mode_is_frozen_and_cannot_consume_oauth() -> None:
    powershell = POWERSHELL.read_text(encoding="utf-8")
    observer = OBSERVER.read_text(encoding="utf-8")

    assert '[ValidateSet("oauth", "runtime-diagnosis")]' in powershell
    assert 'mode = $Mode' in powershell
    assert 'if ($frozenPlan.schemaVersion -ne 2 -or $frozenPlan.mode -cne $Mode)' in powershell
    assert 'executionAllowed = (-not $runtimeDiagnosisOnly)' in powershell
    assert 'loginButton = if ($runtimeDiagnosisOnly) { 0 } else { 1 }' in powershell
    assert 'oauthTransaction = if ($runtimeDiagnosisOnly) { 0 } else { 1 }' in powershell
    assert 'callback = if ($runtimeDiagnosisOnly) { 0 } else { 1 }' in powershell
    assert 'authorizationCodeExchange = if ($runtimeDiagnosisOnly) { 0 } else { 1 }' in powershell
    assert 'browserAction = 0' in powershell
    assert 'localLogout = if ($runtimeDiagnosisOnly) { 0 } else { 1 }' in powershell
    assert 'Runtime diagnosis attempted a forbidden browser authentication action.' in powershell

    assert 'const runtimeDiagnosisOnly = mode === "runtime-diagnosis"' in observer
    assert 'evidence.diagnosisComplete = true' in observer
    diagnosis_branch = observer.index("if (runtimeDiagnosisOnly)")
    completed = observer.index('await persist("runtime-diagnosis-completed")', diagnosis_branch)
    oauth_attempt = observer.index('await persist("oauth-attempted")', completed)
    assert completed < oauth_attempt


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
