param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [ValidateSet("English", "SimpChinese")]
    [string]$Language = "English",
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$InstallerProductName = "DroneDream",
    [string]$ExpectedTarget = "E:\DroneDream",
    [string]$ExpectedApplication = (Join-Path $env:LOCALAPPDATA "DroneDream"),
    [string]$RecoveryControlExecutable = "",
    [switch]$SimulateFreshInstall,
    [switch]$ValidatePathGuard
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RecoveryControlExecutable)) {
    $RecoveryControlExecutable = Join-Path $PSScriptRoot "..\src-tauri\target\x86_64-pc-windows-gnullvm\release\drone-dream-desktop.exe"
}

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class DroneDreamInstallerUi {
    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern IntPtr GetDlgItem(IntPtr hwnd, int id);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool EnumChildWindows(IntPtr hwnd, EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", EntryPoint = "SendMessageW", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessageText(IntPtr hwnd, uint message, IntPtr wParam, StringBuilder lParam);

    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

    public static string ReadText(IntPtr hwnd) {
        const uint WM_GETTEXT = 0x000D;
        const uint WM_GETTEXTLENGTH = 0x000E;
        var length = (int)SendMessage(hwnd, WM_GETTEXTLENGTH, IntPtr.Zero, IntPtr.Zero);
        if (length == 0) length = GetWindowTextLength(hwnd);
        var buffer = new StringBuilder(Math.Max(length + 1, 2));
        SendMessageText(hwnd, WM_GETTEXT, (IntPtr)buffer.Capacity, buffer);
        if (buffer.Length == 0) GetWindowText(hwnd, buffer, buffer.Capacity);
        return buffer.ToString();
    }

    public static string ReadDescendants(IntPtr root) {
        var values = new List<string>();
        EnumChildWindows(root, delegate(IntPtr hwnd, IntPtr unused) {
            if (!IsWindowVisible(hwnd)) return true;
            var value = ReadText(hwnd);
            if (!String.IsNullOrWhiteSpace(value)) values.Add(value.Trim());
            return true;
        }, IntPtr.Zero);
        return String.Join("\n", values);
    }

    public static IntPtr[] TopLevelWindows(uint processId) {
        var windows = new List<IntPtr>();
        EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner == processId && IsWindowVisible(hwnd)) windows.Add(hwnd);
            return true;
        }, IntPtr.Zero);
        return windows.ToArray();
    }

}
"@

$BM_CLICK = 0x00F5
$CB_SETCURSEL = 0x014E
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$process = $null
$registryBackups = @()
$installerLanguageRegistryPath = "HKCU:\Software\DroneDream\$InstallerProductName"
$installerLanguageValueName = "Installer Language"
$installerLanguageWasPresent = $false
$originalInstallerLanguage = $null
$zhWelcome = (-join ([char[]](27426, 36814, 20351, 29992))) + " DroneDream"
$zhInstallationComplete = -join ([char[]](23433, 35013, 23436, 25104))
$zhInstallLocation = -join ([char[]](36873, 25321, 23433, 35013, 20301, 32622))
$zhInstallContent = -join ([char[]](36873, 25321, 23433, 35013, 20869, 23481))
$zhInstallEverything = -join ([char[]](23433, 35013, 20840, 37096, 65288, 25512, 33616, 65289))
$zhAlreadyInstalled = -join ([char[]](24050, 23433, 35013))
$zhAddOrReinstall = -join ([char[]](28155, 21152, 25110, 37325, 26032, 23433, 35013, 32452, 20214))
$zhDontUninstall = -join ([char[]](19981, 21368, 36733))
$zhRuntimeDeferred = -join ([char[]](36816, 34892, 29615, 22659, 23558, 22312, 26700, 38754, 31243, 24207, 20013, 32487, 32493, 35774, 32622, 12290))

function Wait-InstallerWindow {
    param(
        [Diagnostics.Process]$Process,
        [scriptblock]$Condition,
        [int]$TimeoutSeconds = 30
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastTitle = ""
    $lastBody = ""
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            throw "Installer exited unexpectedly with code $($Process.ExitCode)"
        }
        $Process.Refresh()
        $handle = $Process.MainWindowHandle
        if ($handle -ne [IntPtr]::Zero) {
            $title = [DroneDreamInstallerUi]::ReadText($handle)
            $body = [DroneDreamInstallerUi]::ReadDescendants($handle)
            $lastTitle = $title
            $lastBody = $body
            if (& $Condition $handle $title $body) {
                return @{ Handle = $handle; Title = $title; Body = $body }
            }
        }
        Start-Sleep -Milliseconds 150
    }
    throw "Timed out waiting for the expected installer page. Last title='$lastTitle' controls='$lastBody'"
}

function Invoke-DialogButton {
    param(
        [IntPtr]$Dialog,
        [int]$ControlId
    )
    $button = [DroneDreamInstallerUi]::GetDlgItem($Dialog, $ControlId)
    if ($button -eq [IntPtr]::Zero) {
        throw "Installer dialog button $ControlId was not found"
    }
    $posted = [DroneDreamInstallerUi]::PostMessage(
        $button,
        $BM_CLICK,
        [IntPtr]::Zero,
        [IntPtr]::Zero
    )
    if (-not $posted) {
        throw "Installer dialog button $ControlId could not be activated"
    }
}

function Get-InstallerFamilyProcessIds {
    param([int]$RootProcessId)

    $ids = [Collections.Generic.HashSet[int]]::new()
    [void]$ids.Add($RootProcessId)
    $processes = @(Get-CimInstance Win32_Process)
    $found = $true
    while ($found) {
        $found = $false
        foreach ($candidate in $processes) {
            if ($ids.Contains([int]$candidate.ParentProcessId) -and $ids.Add([int]$candidate.ProcessId)) {
                $found = $true
            }
        }
    }
    return @($ids)
}

function Advance-InstallerPage {
    param(
        [Diagnostics.Process]$Process,
        [string]$CurrentPageNeedle,
        [int]$TimeoutSeconds = 120,
        [switch]$AllowProcessExit
    )
    $Process.Refresh()
    $handle = $Process.MainWindowHandle
    if ($handle -eq [IntPtr]::Zero) {
        throw "The installer window was not available while leaving '$CurrentPageNeedle'"
    }
    $body = [DroneDreamInstallerUi]::ReadDescendants($handle)
    if (-not $body.Contains($CurrentPageNeedle)) {
        return
    }
    # A single asynchronous click is intentional. The next page may run the
    # Runtime disk planner before replacing the old NSIS controls. Re-posting
    # while that work is in flight queues multiple Next clicks and can skip or
    # corrupt the page sequence after the planner returns.
    Invoke-DialogButton -Dialog $handle -ControlId 1
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            if ($AllowProcessExit) {
                return
            }
            throw "Installer exited unexpectedly with code $($Process.ExitCode)"
        }
        $Process.Refresh()
        $handle = $Process.MainWindowHandle
        if ($handle -eq [IntPtr]::Zero) {
            Start-Sleep -Milliseconds 150
            continue
        }
        $body = [DroneDreamInstallerUi]::ReadDescendants($handle)
        if (-not $body.Contains($CurrentPageNeedle)) {
            return
        }
        Start-Sleep -Milliseconds 150
    }
    throw "The installer did not advance from '$CurrentPageNeedle'. Controls='$body'"
}

function Suspend-DroneDreamRegistration {
    $keys = @(
        @{
            Key = "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\$InstallerProductName"
            ProviderPath = "Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall\$InstallerProductName"
        },
        @{
            Key = "HKCU\Software\DroneDream\$InstallerProductName"
            ProviderPath = "Registry::HKEY_CURRENT_USER\Software\DroneDream\$InstallerProductName"
        }
    )
    foreach ($entry in $keys) {
        # An absent registration is the expected fresh-install state. Use the
        # Registry provider for this check so reg.exe's normal "not found"
        # stderr cannot become a terminating NativeCommandError under Stop.
        # Export/delete still use reg.exe and remain fail-closed below.
        if (-not (Test-Path -LiteralPath $entry.ProviderPath)) {
            continue
        }
        $key = $entry.Key
        $backup = Join-Path $env:TEMP ("dronedream-installer-ui-{0}.reg" -f [Guid]::NewGuid().ToString("N"))
        & reg.exe export $key $backup /y *> $null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $backup)) {
            throw "Could not back up installer registration '$key'"
        }
        $script:registryBackups += @{ Key = $key; Backup = $backup }
        & reg.exe delete $key /f *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not suspend installer registration '$key'"
        }
    }
}

function Restore-DroneDreamRegistration {
    foreach ($entry in $script:registryBackups) {
        $restore = Start-Process -FilePath "$env:SystemRoot\System32\reg.exe" `
            -ArgumentList @("import", $entry.Backup) -PassThru -Wait -WindowStyle Hidden
        $restoreExitCode = $restore.ExitCode
        $restore.Dispose()
        if ($restoreExitCode -ne 0) {
            Write-Warning "Could not restore installer registration '$($entry.Key)'; backup retained at '$($entry.Backup)'."
            continue
        }
        Remove-Item -LiteralPath $entry.Backup -Force
    }
}

try {
    $maintenanceFlow = $false
    if ($SimulateFreshInstall) {
        Write-Host "UI verify: temporarily suspending DroneDream registration"
        Suspend-DroneDreamRegistration
    }
    $welcomeNeedle = if ($Language -eq "English") { "Welcome to DroneDream Setup" } else { $zhWelcome }
    $locationNeedle = if ($Language -eq "English") { "Choose Install Location" } else { $zhInstallLocation }
    $languageId = if ($Language -eq "English") { 1033 } else { 2052 }
    if (-not $SimulateFreshInstall -and (Test-Path -LiteralPath $installerLanguageRegistryPath)) {
        try {
            $originalInstallerLanguage = Get-ItemPropertyValue `
                -LiteralPath $installerLanguageRegistryPath `
                -Name $installerLanguageValueName
            $installerLanguageWasPresent = $true
        } catch [Management.Automation.PSArgumentException] {
            $installerLanguageWasPresent = $false
        }
        Set-ItemProperty -LiteralPath $installerLanguageRegistryPath `
            -Name $installerLanguageValueName -Value ([string]$languageId)
    }
    $installerArguments = @("/L=$languageId")
    if ($ValidatePathGuard) {
        $installerArguments += "/DRONEDREAMVALIDATEPATHONLY"
    }
    $process = Start-Process -FilePath $installerPath -ArgumentList $installerArguments -PassThru
    Write-Host "UI verify: waiting for localized entry page"
    $entryPage = Wait-InstallerWindow -Process $process -Condition {
        param($handle, $title, $body)
        [DroneDreamInstallerUi]::GetDlgItem($handle, 1002) -ne [IntPtr]::Zero -or
            $body.Contains($welcomeNeedle) -or
            $body.Contains($locationNeedle)
    }
    $languageCombo = [DroneDreamInstallerUi]::GetDlgItem($entryPage.Handle, 1002)
    if ($languageCombo -ne [IntPtr]::Zero -and
        -not $entryPage.Body.Contains($welcomeNeedle) -and
        -not $entryPage.Body.Contains($locationNeedle)) {
        $languageIndex = if ($Language -eq "English") { 0 } else { 1 }
        [void][DroneDreamInstallerUi]::SendMessage($languageCombo, $CB_SETCURSEL, [IntPtr]$languageIndex, [IntPtr]::Zero)
        Invoke-DialogButton -Dialog $entryPage.Handle -ControlId 1
        Write-Host "UI verify: waiting for welcome or location page"
        $firstPage = Wait-InstallerWindow -Process $process -Condition {
            param($handle, $title, $body)
            $body.Contains($welcomeNeedle) -or $body.Contains($locationNeedle)
        }
    } else {
        $firstPage = $entryPage
    }
    if ($firstPage.Body.Contains($welcomeNeedle)) {
        Write-Host "UI verify: advancing welcome page"
        Advance-InstallerPage -Process $process -CurrentPageNeedle $welcomeNeedle
    }
    $alreadyInstalledNeedle = if ($Language -eq "English") { "Already installed" } else { $zhAlreadyInstalled }
    Write-Host "UI verify: waiting for existing-installation or location page"
    $postWelcomePage = Wait-InstallerWindow -Process $process -Condition {
        param($handle, $title, $body)
        $body.Contains($locationNeedle) -or $body.Contains($alreadyInstalledNeedle)
    }
    if ($postWelcomePage.Body.Contains($alreadyInstalledNeedle)) {
        $maintenanceFlow = $true
        Write-Host "UI verify: validating the non-destructive in-place upgrade path"
        $pageDialog = [DroneDreamInstallerUi]::GetDlgItem($postWelcomePage.Handle, 0)
        if ($pageDialog -eq [IntPtr]::Zero) {
            throw "The existing-installation page dialog was not found"
        }
        $maintenanceOption1 = [DroneDreamInstallerUi]::GetDlgItem($pageDialog, 1201)
        $maintenanceOption2 = [DroneDreamInstallerUi]::GetDlgItem($pageDialog, 1202)
        $option1Text = [DroneDreamInstallerUi]::ReadText($maintenanceOption1)
        $option2Text = [DroneDreamInstallerUi]::ReadText($maintenanceOption2)
        $addOrReinstallNeedle = if ($Language -eq "English") { "Add or reinstall components" } else { $zhAddOrReinstall }
        $dontUninstallNeedle = if ($Language -eq "English") { "Do not uninstall" } else { $zhDontUninstall }
        if ($option2Text.Contains($dontUninstallNeedle)) {
            $safeMaintenanceOption = $maintenanceOption2
        } elseif ($option1Text.Contains($addOrReinstallNeedle)) {
            $safeMaintenanceOption = $maintenanceOption1
        } else {
            throw "No non-destructive maintenance option was found. Options='$option1Text' / '$option2Text'"
        }
        if (-not [DroneDreamInstallerUi]::PostMessage(
                $safeMaintenanceOption,
                $BM_CLICK,
                [IntPtr]::Zero,
                [IntPtr]::Zero
            )) {
            throw "The safe maintenance option could not be selected"
        }
        Advance-InstallerPage -Process $process -CurrentPageNeedle $alreadyInstalledNeedle
    }
    Write-Host "UI verify: waiting for application location page"
    $locationPage = Wait-InstallerWindow -Process $process -Condition {
        param($handle, $title, $body)
        $body.Contains($locationNeedle)
    }
    if (-not $locationPage.Body.Contains($ExpectedApplication)) {
        throw "The application page did not preserve the expected destination $ExpectedApplication. Controls='$($locationPage.Body)'"
    }
    Advance-InstallerPage -Process $process -CurrentPageNeedle $locationNeedle `
        -AllowProcessExit:$ValidatePathGuard

    if ($ValidatePathGuard) {
        $diagnosticLog = Join-Path $env:TEMP "DroneDream\installer-diagnostics.log"
        $deadline = [DateTime]::UtcNow.AddSeconds(45)
        while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
            Start-Sleep -Milliseconds 150
        }
        if (-not $process.HasExited) {
            throw "The installer path-only validation did not exit"
        }
        if (-not (Test-Path -LiteralPath $diagnosticLog)) {
            throw "The installer path-only validation did not write diagnostics"
        }
        $diagnostics = Get-Content -LiteralPath $diagnosticLog -Raw
        if ($process.ExitCode -ne 0 -or
            -not $diagnostics.Contains("path-check relation=safe") -or
            -not $diagnostics.Contains("path-validation-only success")) {
            throw "The real installer rejected the default application destination. Exit=$($process.ExitCode) diagnostics='$diagnostics'"
        }
        Write-Host "Real installer page flow verified: language=$Language app=$ExpectedApplication target=$ExpectedTarget"
        return
    }

    $runtimeNeedle = if ($Language -eq "English") { "Choose what to install" } else { $zhInstallContent }
    $fullNeedle = if ($Language -eq "English") { "Install everything (recommended)" } else { $zhInstallEverything }
    $forbiddenNeedle = if ($Language -eq "English") { $zhInstallContent } else { "Choose what to install" }
    $completionNeedle = if ($Language -eq "English") { "Installation Complete" } else { $zhInstallationComplete }
    $dismissedPlannerDialogs = @{}
    $script:DroneDreamUnexpectedPlannerDialog = ""
    Write-Host "UI verify: waiting for Runtime selection page"
    $runtimePage = Wait-InstallerWindow -Process $process -TimeoutSeconds 90 -Condition {
        param($handle, $title, $body)
        # Runtime preflight failures must render the usable app-only selection
        # page directly. A modal here recreates the first-run interruption this
        # verifier is meant to prevent. Dismiss it only so the test can inspect
        # the resulting page, then fail below with the captured text.
        foreach ($installerProcessId in Get-InstallerFamilyProcessIds -RootProcessId $process.Id) {
            foreach ($window in [DroneDreamInstallerUi]::TopLevelWindows([uint32]$installerProcessId)) {
                $windowKey = $window.ToInt64().ToString()
                if ($dismissedPlannerDialogs.ContainsKey($windowKey)) {
                    continue
                }
                $candidateBody = [DroneDreamInstallerUi]::ReadDescendants($window)
                $okButton = [DroneDreamInstallerUi]::GetDlgItem($window, 1)
                if ($okButton -ne [IntPtr]::Zero -and
                    -not $candidateBody.Contains("Nullsoft Install System") -and
                    -not [string]::IsNullOrWhiteSpace($candidateBody)) {
                    $dismissedPlannerDialogs[$windowKey] = $true
                    $script:DroneDreamUnexpectedPlannerDialog = $candidateBody
                    Invoke-DialogButton -Dialog $window -ControlId 1
                    Write-Host "UI verify: dismissed unexpected Runtime preflight dialog"
                }
            }
        }
        # NSIS updates the page header before the Runtime disk planner has
        # finished creating the page controls. Waiting for the localized
        # install-all control prevents a transient half-rendered page from
        # being mistaken for the completed Runtime selection page.
        ($body.Contains($runtimeNeedle) -and $body.Contains($fullNeedle)) -or
            ($maintenanceFlow -and $body.Contains($completionNeedle))
    }
    if ($maintenanceFlow -and $runtimePage.Body.Contains($completionNeedle)) {
        Write-Host "Interactive installer upgrade verified: language=$Language app=$ExpectedApplication"
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($script:DroneDreamUnexpectedPlannerDialog)) {
        throw "Runtime preflight opened an unexpected modal dialog: $script:DroneDreamUnexpectedPlannerDialog"
    }
    if (-not $runtimePage.Body.Contains($fullNeedle)) {
        throw "The full-install option was not rendered in $Language. Controls='$($runtimePage.Body)'"
    }
    if ($runtimePage.Body.Contains($forbiddenNeedle)) {
        throw "The $Language page contains text from the other locale"
    }
    $deferredNeedle = if ($Language -eq "English") {
        "Runtime setup will continue inside the desktop application."
    } else {
        $zhRuntimeDeferred
    }
    if (-not $runtimePage.Body.Contains($ExpectedTarget) -and
        -not $runtimePage.Body.Contains($deferredNeedle)) {
        throw "The Runtime page showed neither the verified target nor the safe desktop fallback. Controls='$($runtimePage.Body)'"
    }

    Write-Host "Interactive installer UI verified: language=$Language app=$ExpectedApplication target=$ExpectedTarget pathGuard=$ValidatePathGuard"
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
    if ($null -ne $process) {
        $process.Dispose()
    }
    Restore-DroneDreamRegistration
    if (-not $SimulateFreshInstall -and (Test-Path -LiteralPath $installerLanguageRegistryPath)) {
        if ($installerLanguageWasPresent) {
            Set-ItemProperty -LiteralPath $installerLanguageRegistryPath `
                -Name $installerLanguageValueName -Value $originalInstallerLanguage
        } else {
            Remove-ItemProperty -LiteralPath $installerLanguageRegistryPath `
                -Name $installerLanguageValueName -ErrorAction SilentlyContinue
        }
    }
    # The UI verifier intentionally stops before committing an installation.
    # NSIS has already quiesced Runtime operations by that point, so a forced
    # test-process shutdown must be followed by the same safe recovery command
    # used after an interrupted real update. This keeps automated verification
    # from leaving the next installer invocation in a false "maintenance busy"
    # state while still refusing to remove a marker owned by a live process.
    if (Test-Path -LiteralPath $RecoveryControlExecutable) {
        $recovered = $false
        for ($attempt = 0; $attempt -lt 5 -and -not $recovered; $attempt++) {
            $recovery = Start-Process -FilePath $RecoveryControlExecutable `
                -ArgumentList "--recover-runtime-quiesce" -PassThru -Wait
            $recovered = $recovery.ExitCode -eq 0
            $recovery.Dispose()
            if (-not $recovered) {
                Start-Sleep -Milliseconds 250
            }
        }
        if (-not $recovered) {
            Write-Warning "Installer UI verification could not recover the Runtime maintenance marker safely."
        }
    }
}
