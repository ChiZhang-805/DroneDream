[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedToolHead,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedScriptSha256,

    [Parameter(Mandatory = $true)]
    [string]$ApplicationPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedApplicationSha256,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long]$ExpectedApplicationBytes,

    [ValidateSet("Plan", "Execute")]
    [string]$Mode = "Plan"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
. (Join-Path $repoRoot "desktop\scripts\edition-installer-lifecycle-contract.ps1")
$productSource = "79a718dae55c274cf4803a57129e5789012dca03"
$artifact = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-ordinal15-79a718d\bundle\DroneDream-Sim-1.0.0.exe"
$expectedArtifactSha256 = "fcabd99fcd3add8c4a19ca429b05faafc2a6ad8f5989cf32b62549ec0ec3299e"
$expectedArtifactBytes = 11944855
$staticAcceptance = Join-Path $repoRoot "distribution\sim\desktop\yellow-build-attempt-15-79a718d-static-accepted.v1.json"
$runId = "sim-red-final-fcabd99f-ordinal5"
$runRoot = Join-Path $env:LOCALAPPDATA "DroneDream-Codex\Sim-RED\$runId"
$evidenceRoot = Join-Path $runRoot "evidence"
$tempRoot = Join-Path $runRoot "temp"
$receiptPath = Join-Path $evidenceRoot "lifecycle-receipt.json"

$productName = "DroneDream-Sim"
$centeredDot = [char]0x00B7
$displayName = "DroneDream $centeredDot SIM"
$bundleId = "io.dronedream.sim"
$installRoot = Join-Path $env:LOCALAPPDATA $productName
$application = Join-Path $installRoot "drone-dream-desktop.exe"
$uninstaller = Join-Path $installRoot "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$desktopShortcut = Join-Path $desktop "$displayName.lnk"
$startMenuShortcut = Join-Path $programs "$displayName.lnk"
$internalDesktopShortcut = Join-Path $desktop "$productName.lnk"
$internalStartMenuShortcut = Join-Path $programs "$productName.lnk"
$roamingAppData = Join-Path $env:APPDATA $bundleId
$localAppData = Join-Path $env:LOCALAPPDATA $bundleId

$events = [Collections.Generic.List[object]]::new()
$installerInvocationCount = 0
$freshInstallerInvocationCount = 0
$overlayInstallerInvocationCount = 0
$applicationLaunchCount = 0
$uninstallerInvocationCount = 0
$pkceBoundaryCheckCount = 0
$installerLanguagePreferenceWriteCount = 0
$installerLanguagePreferenceCleanupWriteCount = 0
$rollbackExecuted = $false
$installedStateCreated = $false
$success = $false
$appProcess = $null
$originalTemp = $env:TEMP
$originalTmp = $env:TMP

function Get-FileRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; exists = $false; bytes = $null; sha256 = $null }
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $item.FullName
        exists = $true
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-DirectoryRecord {
    param(
        [string]$Path,
        [switch]$FingerprintFiles
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return [ordered]@{
            path = $Path
            exists = $false
            lastWriteTimeUtc = $null
            fileCount = $null
            totalBytes = $null
            inventorySha256 = $null
        }
    }
    $item = Get-Item -LiteralPath $Path
    $record = [ordered]@{
        path = $item.FullName
        exists = $true
        lastWriteTimeUtc = $item.LastWriteTimeUtc.ToString("O")
        fileCount = $null
        totalBytes = $null
        inventorySha256 = $null
    }
    if ($FingerprintFiles) {
        $rows = @(
            Get-ChildItem -LiteralPath $Path -Recurse -File -ErrorAction Stop |
                Sort-Object FullName |
                ForEach-Object {
                    $relative = $_.FullName.Substring($item.FullName.Length).TrimStart("\")
                    "$relative|$($_.Length)|$($_.LastWriteTimeUtc.ToString('O'))|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
                }
        )
        $payload = [Text.Encoding]::UTF8.GetBytes(($rows -join "`n"))
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $record.fileCount = $rows.Count
            $record.totalBytes = [long](@(Get-ChildItem -LiteralPath $Path -Recurse -File | Measure-Object Length -Sum).Sum)
            $record.inventorySha256 = ([BitConverter]::ToString($sha.ComputeHash($payload))).Replace("-", "").ToLowerInvariant()
        }
        finally {
            $sha.Dispose()
        }
    }
    return $record
}

function Get-RegistryRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ path = $Path; exists = $false; values = [ordered]@{} }
    }
    $properties = Get-ItemProperty -LiteralPath $Path
    $values = [ordered]@{}
    foreach ($property in @($properties.PSObject.Properties | Sort-Object Name)) {
        if ($property.Name -match '^PS') { continue }
        $values[$property.Name] = if ($null -eq $property.Value) {
            $null
        } else {
            [string]$property.Value
        }
    }
    return [ordered]@{ path = $Path; exists = $true; values = $values }
}

function Get-SimPreferenceCoreRecord {
    $record = Get-RegistryRecord -Path $productKey
    if (-not $record.exists) { return $record }
    $coreValues = [ordered]@{}
    foreach ($name in @(
        "(default)",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeOperationProtocol"
    )) {
        if ($record.values.Contains($name)) {
            $coreValues[$name] = $record.values[$name]
        }
    }
    return [ordered]@{ path = $record.path; exists = $true; values = $coreValues }
}

function Set-OwnedInstallerLanguage {
    param(
        [ValidateSet("1033", "2052")]
        [string]$Language,
        [string]$Stage
    )
    $core = Get-SimPreferenceCoreRecord
    $expectedCore = [ordered]@{
        path = $productKeyBefore.path
        exists = $productKeyBefore.exists
        values = [ordered]@{}
    }
    foreach ($name in @(
        "(default)",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeOperationProtocol"
    )) {
        if ($productKeyBefore.values.Contains($name)) {
            $expectedCore.values[$name] = $productKeyBefore.values[$name]
        }
    }
    if ((ConvertTo-CanonicalJson $core) -cne (ConvertTo-CanonicalJson $expectedCore)) {
        throw "$Stage cannot write the language preference because the Sim preference core drifted."
    }
    New-ItemProperty `
        -LiteralPath $productKey `
        -Name "Installer Language" `
        -Value $Language `
        -PropertyType String `
        -Force | Out-Null
    $script:installerLanguagePreferenceWriteCount++
    $events.Add([ordered]@{
        stage = $Stage
        path = $productKey
        valueName = "Installer Language"
        value = $Language
        ownedWrite = $true
    })
}

function Remove-OwnedInstallerLanguage {
    param([string]$Stage)
    if (-not $productKeyBefore.exists -or $productKeyBefore.values.Contains("Installer Language")) {
        throw "$Stage cannot remove a language preference that was not absent in the baseline."
    }
    $currentProduct = Get-RegistryRecord -Path $productKey
    $core = Get-SimPreferenceCoreRecord
    $expectedCore = [ordered]@{
        path = $productKeyBefore.path
        exists = $true
        values = [ordered]@{}
    }
    foreach ($name in @(
        "(default)",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeOperationProtocol"
    )) {
        if ($productKeyBefore.values.Contains($name)) {
            $expectedCore.values[$name] = $productKeyBefore.values[$name]
        }
    }
    if ((ConvertTo-CanonicalJson $core) -cne (ConvertTo-CanonicalJson $expectedCore)) {
        throw "$Stage cannot remove the language preference because the Sim preference core drifted."
    }
    if (-not $currentProduct.values.Contains("Installer Language")) { return }
    if ([string]$currentProduct.values["Installer Language"] -notin @("1033", "2052")) {
        throw "$Stage found a non-runner-owned language preference."
    }
    Remove-ItemProperty -LiteralPath $productKey -Name "Installer Language"
    $script:installerLanguagePreferenceCleanupWriteCount++
    $events.Add([ordered]@{
        stage = $Stage
        path = $productKey
        valueName = "Installer Language"
        ownedCleanupWrite = $true
    })
}

function Get-ShortcutRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{
            path = $Path
            exists = $false
            bytes = $null
            sha256 = $null
            target = $null
            iconLocation = $null
        }
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        $item = Get-Item -LiteralPath $Path
        return [ordered]@{
            path = $item.FullName
            exists = $true
            bytes = [long]$item.Length
            sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            target = $shortcut.TargetPath
            iconLocation = $shortcut.IconLocation
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}

function Get-WebView2Record {
    $appGuid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    foreach ($key in @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$appGuid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$appGuid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$appGuid"
    )) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $properties = Get-ItemProperty -LiteralPath $key
        $version = [string]$properties.pv
        $location = [string]$properties.location
        $candidates = @(
            (Join-Path $location "msedgewebview2.exe"),
            (Join-Path $location "$version\msedgewebview2.exe"),
            (Join-Path $location "Application\$version\msedgewebview2.exe")
        )
        $executable = $candidates | Where-Object {
            Test-Path -LiteralPath $_ -PathType Leaf
        } | Select-Object -First 1
        if ($version -and $version -ne "0.0.0.0" -and $executable) {
            return [ordered]@{
                registryPath = $key
                version = $version
                location = $location
                executable = (Resolve-Path -LiteralPath $executable).Path
                executableSha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    throw "A usable WebView2 Runtime was not found."
}

function Get-WslRuntimeState {
    $listing = ((& wsl.exe --list --verbose 2>$null) | Out-String) -replace "`0", ""
    $line = @($listing -split "`r?`n" | Where-Object { $_ -match 'DroneDreamRuntime' })
    if ($line.Count -ne 1) { return "not-found" }
    if ($line[0] -match 'Stopped') { return "Stopped" }
    if ($line[0] -match 'Running') { return "Running" }
    return "unknown"
}

function Get-ProtectedState {
    $legacyRoot = Join-Path $env:LOCALAPPDATA "DroneDream"
    $registryNames = @("DroneDream", "DroneDream-Universal", "DroneDream-Lab", "DroneDream-Field")
    $shortcutNames = @(
        "DroneDream",
        "DroneDream-Universal",
        "DroneDream-Lab",
        "DroneDream-Field",
        "DroneDream $centeredDot LAB",
        "DroneDream $centeredDot FIELD"
    )
    return [ordered]@{
        simProductRegistration = Get-SimPreferenceCoreRecord
        legacy = [ordered]@{
            root = Get-DirectoryRecord -Path $legacyRoot
            application = Get-FileRecord -Path (Join-Path $legacyRoot "drone-dream-desktop.exe")
            uninstaller = Get-FileRecord -Path (Join-Path $legacyRoot "uninstall.exe")
        }
        editionInstallRoots = @(
            "DroneDream-Universal", "DroneDream-Lab", "DroneDream-Field" |
                ForEach-Object { Get-DirectoryRecord -Path (Join-Path $env:LOCALAPPDATA $_) }
        )
        editionAppData = @(
            "io.dronedream.desktop.universal",
            "io.dronedream.desktop.lab",
            "io.dronedream.desktop.field",
            "io.dronedream.desktop.sim" |
                ForEach-Object {
                    Get-DirectoryRecord -Path (Join-Path $env:LOCALAPPDATA $_) -FingerprintFiles
                }
        )
        uninstallKeys = @(
            $registryNames | ForEach-Object {
                Get-RegistryRecord -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$_"
            }
        )
        productKeys = @(
            $registryNames | ForEach-Object {
                Get-RegistryRecord -Path "HKCU:\Software\DroneDream\$_"
            }
        )
        desktopShortcuts = @(
            $shortcutNames | ForEach-Object {
                Get-ShortcutRecord -Path (Join-Path $desktop "$_.lnk")
            }
        )
        startMenuShortcuts = @(
            $shortcutNames | ForEach-Object {
                Get-ShortcutRecord -Path (Join-Path $programs "$_.lnk")
            }
        )
        runtimeRoots = @(
            Get-DirectoryRecord -Path "C:\DroneDream"
            Get-DirectoryRecord -Path "Z:\DroneDream"
        )
        runtimeWslState = Get-WslRuntimeState
        webView2 = Get-WebView2Record
    }
}

function ConvertTo-CanonicalJson {
    param([object]$Value)
    return $Value | ConvertTo-Json -Depth 30 -Compress
}

function Assert-ProtectedStateUnchanged {
    param(
        [object]$Before,
        [string]$Stage
    )
    $after = Get-ProtectedState
    if ((ConvertTo-CanonicalJson $Before) -cne (ConvertTo-CanonicalJson $after)) {
        throw "Protected legacy/edition/Runtime/WebView2 state changed during '$Stage'."
    }
    $events.Add([ordered]@{ stage = $Stage; protectedStateParity = $true })
}

function Wait-ForPathState {
    param(
        [string]$Path,
        [bool]$ShouldExist,
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if ((Test-Path -LiteralPath $Path) -eq $ShouldExist) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for exists=$ShouldExist at $Path"
}

function Invoke-CheckedProcess {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Stage
    )
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) {
            throw "$Stage exited with code $($process.ExitCode)."
        }
        $events.Add([ordered]@{
            stage = $Stage
            processExitCode = $process.ExitCode
            arguments = $Arguments
        })
    }
    finally {
        $process.Dispose()
    }
}

function Assert-ShortcutTarget {
    param(
        [string]$Path,
        [string]$ExpectedTarget,
        [string]$Stage
    )
    $record = Get-ShortcutRecord -Path $Path
    if (-not $record.exists -or
        [IO.Path]::GetFullPath([string]$record.target) -cne [IO.Path]::GetFullPath($ExpectedTarget)) {
        throw "$Stage shortcut target drifted: $Path"
    }
    return $record
}

function Assert-SimInstalled {
    param([string]$Stage)
    foreach ($required in @(
        $application,
        $uninstaller,
        (Join-Path $installRoot "licenses\DroneDream-LICENSE.txt"),
        (Join-Path $installRoot "licenses\THIRD_PARTY_NOTICES.md"),
        (Join-Path $installRoot "licenses\Valkey-COPYING.txt"),
        (Join-Path $installRoot "icons\DroneDream.ico"),
        (Join-Path $installRoot "WebView2Loader.dll")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "$Stage missing installed payload: $required"
        }
    }
    $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($application)
    if ($version.ProductVersion -notmatch '^1\.0\.0(?:\.0)?$') {
        throw "$Stage product version drifted: $($version.ProductVersion)"
    }
    $registration = Get-ItemProperty -LiteralPath $uninstallKey
    $expectedRegistration = [ordered]@{
        DisplayName = $displayName
        DisplayVersion = "1.0.0"
        InstallLocation = $installRoot
        MainBinaryName = "drone-dream-desktop.exe"
    }
    $actualRegistration = [ordered]@{
        DisplayName = [string]$registration.DisplayName
        DisplayVersion = [string]$registration.DisplayVersion
        InstallLocation = ([string]$registration.InstallLocation).Trim('"')
        MainBinaryName = [string]$registration.MainBinaryName
    }
    $registrationComparison = Compare-DroneDreamUninstallRegistration `
        -Expected $expectedRegistration `
        -Actual $actualRegistration
    $events.Add([ordered]@{
        stage = "$Stage-uninstall-registration"
        comparison = $registrationComparison
    })
    if (-not $registrationComparison.passed) {
        throw "$Stage uninstall registration drifted: $($registrationComparison.mismatches -join ', ')."
    }
    $product = Get-ItemProperty -LiteralPath $productKey
    if ([string]$product.DroneDreamRuntimeInstallMode -cne "install-app-only" -or
        -not [string]::IsNullOrEmpty([string]$product.DroneDreamRuntimeDrive) -or
        [int]$product.DroneDreamRuntimeOperationProtocol -ne 2) {
        throw "$Stage runtime mode is not app-only protocol 2."
    }
    if (Test-Path -LiteralPath $internalDesktopShortcut -PathType Leaf) {
        throw "$Stage created an internal-name desktop shortcut."
    }
    if (Test-Path -LiteralPath $internalStartMenuShortcut -PathType Leaf) {
        throw "$Stage created an internal-name Start Menu shortcut."
    }
    $desktopRecord = Assert-ShortcutTarget -Path $desktopShortcut -ExpectedTarget $application -Stage $Stage
    $startRecord = Assert-ShortcutTarget -Path $startMenuShortcut -ExpectedTarget $application -Stage $Stage
    if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "$Stage unexpectedly left the application running."
    }
    $events.Add([ordered]@{
        stage = "$Stage-installed-contract"
        registration = $registrationComparison
        applicationSha256 = (Get-FileHash -LiteralPath $application -Algorithm SHA256).Hash.ToLowerInvariant()
        desktopShortcut = $desktopRecord
        startMenuShortcut = $startRecord
        appOnly = $true
        runtimeProfileId = "sim-only"
        artifactAppUserModelId = $bundleId
    })
}

function Copy-InstallerDiagnostic {
    param([string]$Name)
    $source = Join-Path $tempRoot "DroneDream\installer-diagnostics.log"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Installer diagnostic was not created for $Name."
    }
    $destination = Join-Path $evidenceRoot "$Name-installer-diagnostics.log"
    Copy-Item -LiteralPath $source -Destination $destination
    return [ordered]@{
        path = $destination
        bytes = (Get-Item -LiteralPath $destination).Length
        sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Invoke-PkceBoundaryCheck {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 49211)
    try {
        $listener.Start()
        $endpoint = [Net.IPEndPoint]$listener.LocalEndpoint
        if ($endpoint.Address.ToString() -ne "127.0.0.1" -or $endpoint.Port -ne 49211) {
            throw "PKCE listener bound outside the exact Sim callback boundary."
        }
        $script:pkceBoundaryCheckCount++
        $events.Add([ordered]@{
            stage = "pkce-boundary"
            address = $endpoint.Address.ToString()
            port = $endpoint.Port
            browserOpened = $false
            callbackRequestSent = $false
            credentialRead = $false
            tokenExchangeAttempted = $false
        })
    }
    finally {
        $listener.Stop()
    }
}

function Invoke-SingleApplicationLaunch {
    $webViewBefore = @(Get-Process -Name "msedgewebview2" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $script:appProcess = Start-Process -FilePath $application -PassThru
    $script:applicationLaunchCount++
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $windowTitle = ""
    $webViewProcesses = @()
    do {
        Start-Sleep -Milliseconds 500
        $script:appProcess.Refresh()
        if ($script:appProcess.HasExited) {
            throw "The Sim application exited before live WebView2 acceptance."
        }
        $windowTitle = $script:appProcess.MainWindowTitle
        $webViewProcesses = @(
            Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" |
                Where-Object {
                    $_.ProcessId -notin $webViewBefore -and
                    ($_.CommandLine -match 'io\.dronedream\.sim' -or
                     $_.CommandLine -match [regex]::Escape($installRoot))
                }
        )
        if ($webViewProcesses.Count -gt 0 -and $windowTitle) { break }
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($webViewProcesses.Count -eq 0) {
        throw "No live WebView2 process was bound to the Sim app-data namespace."
    }
    if ($windowTitle -cne $displayName) {
        throw "Live application title drifted: '$windowTitle'."
    }
    Invoke-PkceBoundaryCheck
    if (@(Get-NetTCPConnection -LocalPort 49210,49211,49212,49213 -State Listen -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "A desktop auth listener remained active without an authorized browser transaction."
    }
    $events.Add([ordered]@{
        stage = "single-live-application-launch"
        processId = $script:appProcess.Id
        windowTitle = $windowTitle
        webViewProcessCount = $webViewProcesses.Count
        webViewUserDataNamespace = $bundleId
        browserAuthStarted = $false
        realTokenExchangeAttempted = $false
    })
    $closeMode = "close-main-window"
    [void]$script:appProcess.CloseMainWindow()
    if (-not $script:appProcess.WaitForExit(12000)) {
        $closeMode = "stop-exact-launched-pid"
        Stop-Process -Id $script:appProcess.Id -Force
        $script:appProcess.WaitForExit(10000)
    }
    $events.Add([ordered]@{ stage = "single-live-application-close"; mode = $closeMode })
    $script:appProcess.Dispose()
    $script:appProcess = $null
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $remaining = @(
            Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" |
                Where-Object {
                    $_.CommandLine -match 'io\.dronedream\.sim' -or
                    $_.CommandLine -match [regex]::Escape($installRoot)
                }
        )
        if ($remaining.Count -eq 0) { return }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Sim WebView2 processes remained after closing the exact launched app."
}

function Invoke-OwnedUninstaller {
    param([string]$Stage)
    if ($script:uninstallerInvocationCount -ge 1) {
        throw "The single authorized uninstaller invocation was already consumed."
    }
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw "$Stage cannot find the owned Sim uninstaller."
    }
    $registered = Get-ItemProperty -LiteralPath $uninstallKey
    if (([string]$registered.InstallLocation).Trim('"') -cne $installRoot -or
        ([string]$registered.UninstallString).Trim('"') -cne $uninstaller) {
        throw "$Stage uninstaller ownership proof failed."
    }
    $script:uninstallerInvocationCount++
    Invoke-CheckedProcess -Executable $uninstaller -Arguments @("/S", "/L=2052") -Stage $Stage
    Wait-ForPathState -Path $installRoot -ShouldExist $false
}

function Assert-SimRemoved {
    param([string]$Stage)
    foreach ($path in @(
        $installRoot,
        $uninstallKey,
        $desktopShortcut,
        $startMenuShortcut,
        $internalDesktopShortcut,
        $internalStartMenuShortcut
    )) {
        if (Test-Path -LiteralPath $path) {
            throw "$Stage left owned Sim state behind: $path"
        }
    }
    $productAfter = Get-RegistryRecord -Path $productKey
    if ((ConvertTo-CanonicalJson $productKeyBefore) -cne (ConvertTo-CanonicalJson $productAfter)) {
        throw "$Stage changed the pre-existing Sim preference registration."
    }
    $retainedAppData = @(
        foreach ($path in @($roamingAppData, $localAppData)) {
            if (Test-Path -LiteralPath $path -PathType Container) {
                Get-DirectoryRecord -Path $path -FingerprintFiles
            }
        }
    )
    $events.Add([ordered]@{
        stage = "$Stage-owned-residue"
        installRootAbsent = $true
        uninstallRegistrationAbsent = $true
        preExistingPreferenceRegistrationPreserved = $true
        shortcutsAbsent = $true
        retainedAppData = $retainedAppData
        appDataPolicy = "diagnostics-and-user-state-may-be-preserved"
    })
}

$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-sim-final-candidate-lifecycle-execution"
    editionId = "sim"
    productSourceCommit = $productSource
    toolEvidenceHead = $ExpectedToolHead
    executionOrdinal = 5
    runId = $runId
    runRoot = $runRoot
    artifact = [ordered]@{
        path = $artifact
        bytes = $expectedArtifactBytes
        sha256 = $expectedArtifactSha256
    }
    application = [ordered]@{
        path = $ApplicationPath
        bytes = $ExpectedApplicationBytes
        sha256 = $ExpectedApplicationSha256
    }
    runner = [ordered]@{
        path = $MyInvocation.MyCommand.Path
        sha256 = $ExpectedScriptSha256
    }
    executionAuthorized = $Mode -ceq "Execute"
    exactCounts = [ordered]@{
        freshInstallerInvocations = 0
        overlayInstallerInvocations = 0
        applicationLaunches = 0
        uninstallerInvocations = 0
        pkceBoundaryChecks = 0
        builds = 0
        tokenExchanges = 0
        runtimeStarts = 0
        px4Starts = 0
        gazeboStarts = 0
        hardwareActions = 0
    }
    lifecycle = [ordered]@{
        freshEn = "not-run"
        overlayZhPath = "not-run"
        shortcut = "not-run"
        liveWebView2 = "not-run"
        pkceBoundary = "not-run"
        uninstall = "not-run"
        protectedParity = "not-run"
    }
    events = @()
    releaseReady = $false
    websiteHandoffReady = $false
}

try {
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    $upstream = (& git -C $repoRoot rev-parse '@{upstream}').Trim()
    $dirty = @(& git -C $repoRoot status --porcelain)
    if ($head -cne $ExpectedToolHead -or $upstream -cne $ExpectedToolHead -or $dirty.Count -ne 0) {
        throw "Git HEAD/upstream/clean preflight drifted."
    }
    $runnerPath = (Resolve-Path -LiteralPath $MyInvocation.MyCommand.Path).Path
    $applicationFull = (Resolve-Path -LiteralPath $ApplicationPath).Path
    if (-not $applicationFull.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        (Get-FileHash -LiteralPath $runnerPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedScriptSha256 -or
        (Get-FileHash -LiteralPath $applicationFull -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedApplicationSha256 -or
        (Get-Item -LiteralPath $applicationFull).Length -ne $ExpectedApplicationBytes) {
        throw "Lifecycle runner or application identity drifted."
    }
    $static = Get-Content -LiteralPath $staticAcceptance -Raw | ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expectedArtifactSha256 -or
        (Get-Item -LiteralPath $artifact).Length -ne $expectedArtifactBytes -or
        [string]$static.sourceSeparation.productSourceCommit -cne $productSource -or
        [string]$static.artifact.sha256 -cne $expectedArtifactSha256 -or
        [long]$static.artifact.bytes -ne $expectedArtifactBytes -or
        [bool]$static.lifecycle.validated) {
        throw "Artifact or static acceptance identity drifted."
    }
    if ($Mode -ceq "Execute" -and (Test-Path -LiteralPath $runRoot)) {
        throw "Owned run root already exists; refusing to reuse it."
    }
    foreach ($path in @(
        $installRoot,
        $uninstallKey,
        $desktopShortcut,
        $startMenuShortcut,
        $internalDesktopShortcut,
        $internalStartMenuShortcut
    )) {
        if (Test-Path -LiteralPath $path) {
            throw "Fresh Sim precondition failed: $path"
        }
    }
    if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "A DroneDream desktop process is already running."
    }
    if (@(Get-NetTCPConnection -LocalPort 49211 -State Listen -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "Sim callback port 49211 is already in use."
    }
    if ($Mode -ceq "Execute" -and @(
        Get-Process -Name "cargo", "rustc", "makensis", "gazebo", "px4" -ErrorAction SilentlyContinue
    ).Count -ne 0) {
        throw "A heavy build or simulation process is active."
    }
    if ((Get-WslRuntimeState) -cne "Stopped") {
        throw "DroneDreamRuntime must remain stopped."
    }
    $productKeyBefore = Get-RegistryRecord -Path $productKey
    if ($productKeyBefore.values.Contains("Installer Language")) {
        throw "The exact lifecycle baseline must not contain a pre-existing Installer Language value."
    }
    $protectedBefore = Get-ProtectedState
    $simAppDataBefore = @(
        Get-DirectoryRecord -Path $roamingAppData -FingerprintFiles
        Get-DirectoryRecord -Path $localAppData -FingerprintFiles
    )
    $receipt.preflight = [ordered]@{
        head = $head
        upstream = $upstream
        clean = $true
        artifactRehash = "pass"
        simInstallRootAbsent = $true
        simUninstallKeyAbsent = $true
        simPreferenceKeyPresentAndProtected = $productKeyBefore.exists
        callbackPort49211Free = $true
        runtimeState = "Stopped"
        protectedStateCaptured = $true
        simAppDataPolicy = "existing-user-state-is-not-a-fresh-install-blocker-and-must-not-be-manually-deleted"
        simAppDataBefore = $simAppDataBefore
    }
    if ($Mode -ceq "Plan") {
        $receipt.lifecycle.freshEn = "plan-only"
        $receipt.lifecycle.overlayZhPath = "plan-only"
        $receipt.lifecycle.shortcut = "plan-only"
        $receipt.lifecycle.liveWebView2 = "plan-only"
        $receipt.lifecycle.pkceBoundary = "plan-only"
        $receipt.lifecycle.uninstall = "plan-only"
        $receipt.lifecycle.protectedParity = "plan-only"
        $success = $true
        $receipt.planOnly = $true
    }
    else {
    New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $env:TEMP = $tempRoot
    $env:TMP = $tempRoot
    $receipt.protectedStateBefore = $protectedBefore
    $receipt.startedAt = [DateTime]::UtcNow.ToString("O")

    Set-OwnedInstallerLanguage -Language "1033" -Stage "fresh-en-language-preference"
    $installerInvocationCount++
    $freshInstallerInvocationCount++
    Invoke-CheckedProcess -Executable $artifact -Arguments @("/S", "/L=1033") -Stage "fresh-en-app-only"
    $installedStateCreated = $true
    Wait-ForPathState -Path $installRoot -ShouldExist $true
    Assert-SimInstalled -Stage "fresh-en-app-only"
    $freshDiagnostic = Copy-InstallerDiagnostic -Name "fresh-en"
    if (-not ((Get-Content -LiteralPath $freshDiagnostic.path -Raw) -match 'installer-init language=1033')) {
        throw "Fresh installer did not execute the English language path."
    }
    Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "fresh-en-app-only"
    $receipt.lifecycle.freshEn = "pass"
    $receipt.lifecycle.shortcut = "pass-created-owned-display-shortcuts"
    $receipt.freshDiagnostic = $freshDiagnostic

    Set-OwnedInstallerLanguage -Language "2052" -Stage "overlay-zh-language-preference"
    $installerInvocationCount++
    $overlayInstallerInvocationCount++
    Invoke-CheckedProcess -Executable $artifact -Arguments @("/S", "/UPDATE", "/L=2052") -Stage "overlay-zh-path"
    Assert-SimInstalled -Stage "overlay-zh-path"
    $overlayDiagnostic = Copy-InstallerDiagnostic -Name "overlay-zh"
    if (-not ((Get-Content -LiteralPath $overlayDiagnostic.path -Raw) -match 'installer-init language=2052')) {
        throw "Overlay installer did not execute the Simplified Chinese language path."
    }
    Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "overlay-zh-path"
    $receipt.lifecycle.overlayZhPath = "pass"
    $receipt.overlayDiagnostic = $overlayDiagnostic

    Invoke-SingleApplicationLaunch
    if ((Get-WslRuntimeState) -cne "Stopped") {
        throw "The Sim application launch changed DroneDreamRuntime state."
    }
    Assert-SimInstalled -Stage "post-live-launch"
    Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "post-live-launch"
    $receipt.lifecycle.liveWebView2 = "pass"
    $receipt.lifecycle.pkceBoundary = "pass-49211-exclusive-bind-no-browser-no-callback"

    Invoke-OwnedUninstaller -Stage "final-zh-uninstall"
    Remove-OwnedInstallerLanguage -Stage "final-zh-language-preference-cleanup"
    Assert-SimRemoved -Stage "final-zh-uninstall"
    Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "final-zh-uninstall"
    $installedStateCreated = $false
    $receipt.lifecycle.uninstall = "pass"
    $receipt.lifecycle.protectedParity = "pass-after-every-phase"
    $receipt.releaseReady = $true
    $receipt.websiteHandoffReady = $true
    $success = $true
    }
}
catch {
    $receipt.failure = [ordered]@{
        type = $_.Exception.GetType().FullName
        message = $_.Exception.Message
    }
    if ($appProcess -and -not $appProcess.HasExited) {
        try { Stop-Process -Id $appProcess.Id -Force } catch {}
    }
    if ($installedStateCreated -and
        $uninstallerInvocationCount -eq 0 -and
        (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        try {
            Invoke-OwnedUninstaller -Stage "failure-recovery-owned-uninstaller"
            $rollbackExecuted = $true
            Assert-SimRemoved -Stage "failure-recovery-owned-uninstaller"
            Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "failure-recovery-owned-uninstaller"
            $receipt.failureRecovery = "owned-sim-uninstaller-succeeded"
        }
        catch {
            $receipt.failureRecovery = "owned-sim-uninstaller-failed-manual-attention-required"
            $receipt.failureRecoveryError = $_.Exception.Message
        }
    }
}
finally {
    $env:TEMP = $originalTemp
    $env:TMP = $originalTmp
    if (-not $success -and $productKeyBefore -and $productKeyBefore.exists -and
        $installerLanguagePreferenceCleanupWriteCount -eq 0) {
        try {
            Remove-OwnedInstallerLanguage -Stage "failure-language-preference-cleanup"
            if ($installerLanguagePreferenceCleanupWriteCount -eq 1) {
                $receipt.failurePreferenceRecovery = "removed-exact-runner-owned-language-value"
            }
        }
        catch {
            $receipt.failurePreferenceRecovery = "failed-to-remove-runner-owned-language-value"
            $receipt.failurePreferenceRecoveryError = $_.Exception.Message
        }
    }
    $receipt.exactCounts = [ordered]@{
        freshInstallerInvocations = $freshInstallerInvocationCount
        overlayInstallerInvocations = $overlayInstallerInvocationCount
        applicationLaunches = $applicationLaunchCount
        uninstallerInvocations = $uninstallerInvocationCount
        pkceBoundaryChecks = $pkceBoundaryCheckCount
        installerLanguagePreferenceWrites = $installerLanguagePreferenceWriteCount
        installerLanguagePreferenceCleanupWrites = $installerLanguagePreferenceCleanupWriteCount
        builds = 0
        tokenExchanges = 0
        runtimeStarts = 0
        px4Starts = 0
        gazeboStarts = 0
        hardwareActions = 0
    }
    $receipt.events = @($events)
    $receipt.rollbackExecuted = $rollbackExecuted
    $receipt.success = $success
    $receipt.completedAt = [DateTime]::UtcNow.ToString("O")
    if (Test-Path -LiteralPath $evidenceRoot -PathType Container) {
        [IO.File]::WriteAllText(
            $receiptPath,
            ($receipt | ConvertTo-Json -Depth 40),
            [Text.UTF8Encoding]::new($false)
        )
    }
}

if (-not $success) {
    $failureMessage = if ($receipt.failure) { [string]$receipt.failure.message } else { "unknown" }
    throw "Sim RED lifecycle failed: $failureMessage; evidence is frozen at $receiptPath"
}

if ($Mode -ceq "Execute") {
    Write-Host "Sim RED lifecycle passed: $receiptPath"
}
else {
    $receipt | ConvertTo-Json -Depth 40
}
