from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ROOT / "desktop/scripts/verify-universal-real-oauth.ps1"
OBSERVER = ROOT / "frontend/scripts/verify-installed-universal-oauth.mjs"
INSTALLED_UI = ROOT / "frontend/scripts/verify-installed-universal-ui.mjs"
EXIT_CONFIRMATION = ROOT / "frontend/scripts/confirm-installed-universal-exit.mjs"
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
    for gate in ("LifecycleReceipt", "VisibleInstallerReceipt"):
        assert gate in text
    assert "OAuth-only validation requires a prior successful installed-app receipt." in text
    assert "Authenticated UI matrix replaces, rather than combines with" in text
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


def test_authenticated_ui_matrix_runs_only_inside_the_authenticated_session() -> None:
    powershell = POWERSHELL.read_text(encoding="utf-8")
    observer = OBSERVER.read_text(encoding="utf-8")

    assert "[switch]$RunAuthenticatedUiMatrix" in powershell
    assert 'Authenticated UI matrix is unavailable in Runtime diagnosis mode.' in powershell
    for exact_count in (
        "authenticatedUiCases = if ($RunAuthenticatedUiMatrix)",
        "languageSelections = if ($RunAuthenticatedUiMatrix)",
        "settingsOpen = if ($RunAuthenticatedUiMatrix)",
        "settingsTabActivations = if ($RunAuthenticatedUiMatrix)",
        "screenshots = if ($RunAuthenticatedUiMatrix)",
    ):
        assert exact_count in powershell
    assert '@("en", "zh-CN")' in powershell
    assert '@("universal", "sim", "lab", "field")' in powershell
    assert '"--emulate-viewport=true"' in powershell
    assert '"--authenticated-workspace=true"' in powershell
    assert 'validationSurface -cne "authenticated-workspace"' in powershell
    assert "languageSelectionCount -ne 1" in powershell
    assert "workspaceScreenshotSha256" in powershell
    assert 'Start-Process -FilePath (Get-Command node).Source' in powershell
    assert 'stage -ceq "authenticated-ui-ready"' in powershell
    assert 'Write-AtomicText $postAuthSignalPath "complete"' in powershell
    assert 'Write-AtomicText $postAuthSignalPath "abort"' in powershell
    helper_call = powershell.index("& $browserConsentVerifier")
    callback_recheck = powershell.index(
        'checkpointAfterConsent.stage -ceq "authenticated-ui-ready"', helper_call
    )
    helper_failure = powershell.index(
        'throw "Bounded browser consent action failed before authentication completed."',
        callback_recheck,
    )
    assert helper_call < callback_recheck < helper_failure
    assert 'process.exit' not in powershell

    ready = observer.index('await persist("authenticated-ui-ready")')
    signal = observer.index("await waitForPostAuthUiSignal()", ready)
    logout = observer.index('await persist("local-logout-attempted")', signal)
    assert ready < signal < logout
    assert 'decision === "complete" || decision === "abort"' in observer
    assert 'Post-auth UI observation failed closed' in observer


def test_authenticated_observer_settlement_uses_the_durable_terminal_checkpoint() -> None:
    powershell = POWERSHELL.read_text(encoding="utf-8")
    settlement = powershell.index(
        'Wait-Until { $oauthObserverProcess.Refresh(); $oauthObserverProcess.HasExited } 60'
    )
    checkpoint = powershell.index(
        'Import-ObserverCheckpoint $observerPath $counts $receipt', settlement
    )
    terminal = powershell.index(
        '[string]$settledObservation.terminalState -cne "passed"', checkpoint
    )
    dispose = powershell.index(
        '$oauthObserverProcess.Dispose(); $oauthObserverProcess = $null', terminal
    )
    assert settlement < checkpoint < terminal < dispose
    assert '$oauthObserverProcess.ExitCode -ne 0' not in powershell


def test_authenticated_app_close_handles_the_existing_exit_guard_once() -> None:
    powershell = POWERSHELL.read_text(encoding="utf-8")
    helper = EXIT_CONFIRMATION.read_text(encoding="utf-8")
    assert "exitGuardConfirmationMax = 1" in powershell
    assert "$counts.exitGuardConfirmation++" in powershell
    assert 'Save-ExecutionCheckpoint "exit-guard-confirmation-attempted"' in powershell
    assert '"--cdp-endpoint=http://127.0.0.1:$CdpPort"' in powershell
    assert "App did not close after its bounded exit contract." in powershell
    assert '.locator(".app-exit-dialog")' in helper
    assert '.locator(".app-exit-confirm")' in helper
    assert "receipt.confirmationClicks += 1" in helper
    assert "await browser.close" not in helper
    for forbidden in ("access_token", "refresh_token", "password", "cookie", "requestId"):
        assert forbidden not in helper


def test_owned_uninstaller_residue_cleanup_is_exact_and_fail_closed() -> None:
    powershell = POWERSHELL.read_text(encoding="utf-8")
    assert "function Remove-ExactOwnedUninstallerResidue" in powershell
    assert "$entries.Count -ne 1" in powershell
    assert "$entries[0].FullName -cne $uninstallerPath" in powershell
    assert "[long]$actual.bytes -ne [long]$ExpectedUninstaller.bytes" in powershell
    assert "[string]$actual.sha256 -cne [string]$ExpectedUninstaller.sha256" in powershell
    assert "[IO.File]::Delete($uninstallerPath)" in powershell
    assert "[IO.Directory]::Delete($installDirectory)" in powershell
    assert "Remove-Item -LiteralPath $installDirectory -Recurse" not in powershell
    assert "-and $counts.ownedCleanup -eq 0 -and" in powershell


def test_authenticated_ui_observer_switches_real_universal_workspaces() -> None:
    observer = INSTALLED_UI.read_text(encoding="utf-8")
    assert (
        'const authenticatedWorkspace = args.get("--authenticated-workspace") === "true"'
        in observer
    )
    for route in (
        'universal: "/vehicle-studio"',
        'sim: "/assistant"',
        'lab: "/lab"',
        'field: "/field"',
    ):
        assert route in observer
    for surface in (
        'universal: ".vehicle-studio-page"',
        'sim: ".experiment-assistant-page"',
        'lab: ".lab-page"',
        'field: ".field-app"',
    ):
        assert surface in observer
    assert 'page.locator(".universal-mode-switch select").first()' in observer
    assert "await workspaceModeSelector.selectOption(edition)" in observer
    assert "assert.equal(await workspaceModeSelector.inputValue(), edition)" in observer
    assert "async function assertAuthenticatedAccountSurface(page)" in observer
    assert 'menuPanel.locator(".app-account-button:visible")' in observer
    assert 'data-theme-grants-hardware-authority' in observer
    assert (
        'validationSurface: authenticatedWorkspace '
        '? "authenticated-workspace" : "pre-auth-launcher"'
        in observer
    )
    assert 'languageSelectionCount: 1' in observer


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
    assert 'runtimeRestoreObserved"] = $true' in text
    assert 'runtimeRestoreError"] = "runtime_prestate_restore_timeout"' in text
    restore_wait = text.rindex("Wait-Until {")
    final_state = text.rindex("Assert-ProtectedStateUnchanged")
    assert restore_wait < final_state


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


def test_installed_observer_uses_the_packaged_hash_router_after_callback() -> None:
    text = OBSERVER.read_text(encoding="utf-8")
    assert 'window.location.hash === "#/assistant"' in text
    assert "window.location.hash.slice(1)" in text
    assert 'window.location.pathname === "/assistant"' not in text


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
    finally_block = powershell.index("finally {", powershell.index("$observerArguments = @("))
    assert (
        powershell.index("Import-ObserverCheckpoint $observerPath", finally_block)
        > finally_block
    )
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
    assert (
        "[bool]$frozenPlan.runAuthenticatedUiMatrix -ne "
        "[bool]$RunAuthenticatedUiMatrix"
    ) in powershell
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
