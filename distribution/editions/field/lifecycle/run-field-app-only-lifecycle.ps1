param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedInstallerSha256,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long]$ExpectedInstallerBytes,
    [Parameter(Mandatory = $true)]
    [string]$Application,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedApplicationSha256,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$productSource = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
$productName = "DroneDream-Field"
$displayName = "DroneDream $([char]0x00B7) FIELD"
$mainBinaryName = "drone-dream-desktop.exe"
$bundleId = "io.dronedream.desktop.field"
$installRoot = Join-Path $env:LOCALAPPDATA $productName
$appBinary = Join-Path $installRoot $mainBinaryName
$uninstaller = Join-Path $installRoot "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$sharedProductParent = "HKCU:\Software\DroneDream"
$protectedSimProductKey = "HKCU:\Software\DroneDream\DroneDream-Sim"
$expectedProtectedSimSha256 = "ef59eb8105ccef5db3c0ba45a933ee8bbf582255d498104b2928b9f5ef8eab8d"
$roamingAppData = Join-Path $env:APPDATA $bundleId
$localAppData = Join-Path $env:LOCALAPPDATA $bundleId
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$displayName.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$displayName.lnk"
$inspector = Join-Path $PSScriptRoot "inspect-field-live-webview2.mjs"

$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$allowedOutputBase = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream-Codex\Field-RED")
).TrimEnd("\")
if (-not ($outputPath + "\").StartsWith(
    $allowedOutputBase + "\",
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "OutputRoot must be a fresh child of the Field RED owned base."
}
if (Test-Path -LiteralPath $outputPath) {
    throw "OutputRoot already exists; refusing to reuse lifecycle evidence."
}

$installerItem = Get-Item -LiteralPath $installerPath
$installerSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$applicationSha256 = (Get-FileHash -LiteralPath $applicationPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($installerItem.Length -ne $ExpectedInstallerBytes -or $installerSha256 -cne $ExpectedInstallerSha256) {
    throw "The exact frozen Field installer identity does not match the application."
}
if ($applicationSha256 -cne $ExpectedApplicationSha256) {
    throw "The exact RED application SHA-256 does not match."
}
$applicationContract = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($applicationContract.artifact.sha256 -cne $ExpectedInstallerSha256 -or
    $applicationContract.artifact.bytes -ne $ExpectedInstallerBytes -or
    $applicationContract.sourceSeparation.artifactProductSourceCommit -cne $productSource) {
    throw "The RED application is not bound to the exact frozen Field artifact."
}
if ($applicationContract.authorization.segmentAExecutionDecision -cne
    "prepared-awaiting-new-exact-red-authorization") {
    throw "Segment A2 is not in its exact prepared state."
}
if ($applicationContract.authorization.segmentBExecutionDecision -cne
    "deny-before-real-auth-boundary") {
    throw "Segment B must remain fail-closed."
}

$counters = [ordered]@{
    freshInstallerInvocations = 0
    overlayInstallerInvocations = 0
    applicationLaunches = 0
    shortcutLaunches = 0
    uninstallerInvocations = 0
    ownedPreferenceKeyCleanupAttempts = 0
    ownedPreferenceKeyCleanupInvocations = 0
    liveWebView2Inspections = 0
    languageTransitions = 0
    browserLaunches = 0
    oauthBoundaryChecks = 0
    accountReads = 0
    tokenReadsOrExchanges = 0
    artifactBuilds = 0
    runtimeStarts = 0
    px4Starts = 0
    gazeboStarts = 0
    deviceEnumerationInvocations = 0
    serialUsbWrites = 0
    parameterWrites = 0
    armCommands = 0
    flightCommands = 0
    hardwareActions = 0
}
$events = [Collections.Generic.List[object]]::new()
$appProcess = $null
$freshInstalled = $false
$ownedPreferenceCleanupAttempted = $false
$result = "not-executed"
$failure = $null

function Get-PathRecord {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    return [ordered]@{
        path = $Path
        exists = ($null -ne $item)
        isDirectory = if ($null -ne $item) { [bool]$item.PSIsContainer } else { $null }
        length = if ($null -ne $item -and -not $item.PSIsContainer) { [long]$item.Length } else { $null }
        lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
    }
}

function Get-RegistryRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ path = $Path; exists = $false; values = [ordered]@{} }
    }
    $item = Get-ItemProperty -LiteralPath $Path
    $values = [ordered]@{}
    foreach ($name in @("DisplayName", "DisplayVersion", "InstallLocation", "MainBinaryName")) {
        $value = $item.$name
        $values[$name] = if ($null -eq $value) { $null } else { [string]$value }
    }
    return [ordered]@{ path = $Path; exists = $true; values = $values }
}

function Get-ShortcutRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; exists = $false; target = $null; iconLocation = $null }
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        return [ordered]@{
            path = $Path
            exists = $true
            target = $shortcut.TargetPath
            iconLocation = $shortcut.IconLocation
        }
    } finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}

function Get-WebView2Record {
    $guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $keys = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid"
    )
    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $properties = Get-ItemProperty -LiteralPath $key
        $version = [string]$properties.pv
        $location = [string]$properties.location
        if ($version -and $version -ne "0.0.0.0") {
            return [ordered]@{ registryPath = $key; version = $version; location = $location }
        }
    }
    throw "A usable WebView2 Runtime is required; repair is forbidden in Segment A."
}

function Get-ProtectedState {
    $otherRoots = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab") |
        ForEach-Object { Get-PathRecord -Path (Join-Path $env:LOCALAPPDATA $_) }
    $otherKeys = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab") |
        ForEach-Object {
            Get-RegistryRecord -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$_"
        }
    $runtimeRoots = @(
        Get-PathRecord -Path "C:\DroneDream"
        Get-PathRecord -Path "Z:\DroneDream"
    )
    return [ordered]@{
        otherEditionRoots = @($otherRoots)
        otherEditionUninstallKeys = @($otherKeys)
        runtimeRoots = $runtimeRoots
        webView2 = Get-WebView2Record
    }
}

function ConvertTo-StableJson {
    param([object]$Value)
    return $Value | ConvertTo-Json -Depth 20 -Compress
}

function Assert-ProtectedParity {
    param([object]$Before, [string]$Stage)
    $after = Get-ProtectedState
    if ((ConvertTo-StableJson $Before) -cne (ConvertTo-StableJson $after)) {
        throw "Protected other-Edition, Runtime, or WebView2 state changed during $Stage."
    }
    $events.Add([ordered]@{ stage = $Stage; protectedStateParity = $true })
}

function Assert-FreshPreconditions {
    foreach ($path in @($installRoot, $roamingAppData, $localAppData, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Fresh precondition failed: $path exists." }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Fresh precondition failed: $key exists." }
    }
    foreach ($protectedKey in @($sharedProductParent, $protectedSimProductKey)) {
        if (-not (Test-Path -LiteralPath $protectedKey)) {
            throw "Protected registry precondition failed: $protectedKey is missing."
        }
    }
    $listeners = @(Get-NetTCPConnection -LocalPort 49213 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 0) { throw "Field OAuth callback port 49213 is already listening." }
    $processes = @(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue)
    if ($processes.Count -ne 0) { throw "A DroneDream desktop process is already running." }
    Get-WebView2Record | Out-Null
}

function Invoke-ProcessOnce {
    param([string]$Executable, [string[]]$Arguments, [string]$Stage)
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) { throw "$Stage exited with code $($process.ExitCode)." }
        $events.Add([ordered]@{ stage = $Stage; processExitCode = $process.ExitCode })
    } finally {
        $process.Dispose()
    }
}

function Assert-FieldInstalled {
    param([string]$Stage)
    foreach ($path in @($appBinary, $uninstaller)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "$Stage missing $path." }
    }
    $registration = Get-RegistryRecord -Path $uninstallKey
    if (-not $registration.exists -or $registration.values.DisplayName -cne $displayName -or
        $registration.values.DisplayVersion -cne "1.0.0" -or
        $registration.values.MainBinaryName -cne $mainBinaryName -or
        $registration.values.InstallLocation.Trim('"') -cne $installRoot) {
        throw "$Stage produced an invalid Field uninstall registration."
    }
    foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
        $shortcut = Get-ShortcutRecord -Path $shortcutPath
        if (-not $shortcut.exists -or $shortcut.target -cne $appBinary) {
            throw "$Stage produced an invalid Field shortcut: $shortcutPath"
        }
    }
    $events.Add([ordered]@{ stage = $Stage; fieldIdentityAccepted = $true })
}

function Get-FreeLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port } finally { $listener.Stop() }
}

function Stop-OwnedFieldProcess {
    if ($null -eq $script:appProcess) { return }
    try {
        if (-not $script:appProcess.HasExited) {
            $script:appProcess.CloseMainWindow() | Out-Null
            if (-not $script:appProcess.WaitForExit(5000)) {
                Stop-Process -Id $script:appProcess.Id -Force
                $script:appProcess.WaitForExit(5000) | Out-Null
            }
        }
    } finally {
        $script:appProcess.Dispose()
        $script:appProcess = $null
    }
    Start-Sleep -Seconds 2
    if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "The owned Field desktop process did not stop."
    }
}

function Invoke-LiveInspection {
    param(
        [string]$Phase,
        [string]$LaunchPath,
        [bool]$IsShortcutLaunch = $false
    )
    $port = Get-FreeLoopbackPort
    $oldArguments = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
    try {
        $script:appProcess = Start-Process -FilePath $LaunchPath -PassThru
        $counters.applicationLaunches++
        if ($IsShortcutLaunch) { $counters.shortcutLaunches++ }
        $endpoint = "http://127.0.0.1:$port"
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            try {
                Invoke-WebRequest -Uri "$endpoint/json/version" -UseBasicParsing -TimeoutSec 2 | Out-Null
                break
            } catch {
                if ($script:appProcess.HasExited) { throw "Field exited before WebView2 inspection." }
                Start-Sleep -Milliseconds 300
            }
        } while ([DateTime]::UtcNow -lt $deadline)
        if ([DateTime]::UtcNow -ge $deadline) { throw "Timed out waiting for live Field WebView2." }

        $inspectionPath = Join-Path $outputPath "$Phase-live-webview2.json"
        $stdoutPath = Join-Path $outputPath "$Phase-live-webview2.stdout.log"
        $stderrPath = Join-Path $outputPath "$Phase-live-webview2.stderr.log"
        $node = Start-Process -FilePath "node.exe" -ArgumentList @(
            $inspector, $endpoint, $Phase, $inspectionPath
        ) -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -Wait -WindowStyle Hidden
        try {
            if ($node.ExitCode -ne 0) {
                throw "The $Phase live WebView2 inspection failed with exit code $($node.ExitCode)."
            }
        } finally {
            $node.Dispose()
        }
        $inspection = Get-Content -LiteralPath $inspectionPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $inspection.passed -or $inspection.forbiddenAuthRequestCount -ne 0 -or
            $inspection.authStorageKeyCount -ne 0 -or $inspection.browserLaunchCount -ne 0) {
            throw "The $Phase live WebView2 inspection violated Segment A."
        }
        $counters.liveWebView2Inspections++
        $counters.languageTransitions += [int]$inspection.languageTransitionCount
        $events.Add([ordered]@{
            stage = "$Phase-live-webview2"
            processId = $script:appProcess.Id
            inspectionPath = $inspectionPath
            initialLocale = $inspection.initialLocale
            finalLocale = $inspection.finalLocale
            webView2PageUrl = $inspection.pageUrl
            brandNaturalWidth = $inspection.brand.naturalWidth
            brandNaturalHeight = $inspection.brand.naturalHeight
            forbiddenAuthRequestCount = 0
        })
    } finally {
        if ($null -eq $oldArguments) {
            Remove-Item Env:\WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
        } else {
            $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $oldArguments
        }
        Stop-OwnedFieldProcess
    }
}

function Remove-OwnedAppData {
    foreach ($path in @($roamingAppData, $localAppData)) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $path).Path).TrimEnd("\")
        $expected = [IO.Path]::GetFullPath($path).TrimEnd("\")
        if ($resolved -cne $expected -or
            -not ($resolved + "\").StartsWith(
                [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd("\") + "\",
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "Owned Field app-data cleanup escaped its exact namespace."
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

function Assert-OwnedProductPreferenceValues {
    param(
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$Values,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedInstallRoot
    )
    $actualNames = @($Values.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    $expectedNames = @(
        "(default)",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeOperationProtocol"
    ) | Sort-Object
    if (($actualNames -join "`n") -cne ($expectedNames -join "`n")) {
        throw "The Field product preference residue contains missing or unexpected values."
    }
    if ([string]$Values["(default)"] -cne $ExpectedInstallRoot -or
        [string]$Values["DroneDreamRuntimeInstallMode"] -cne "install-app-only" -or
        [string]$Values["DroneDreamRuntimeDrive"] -cne "" -or
        [string]$Values["DroneDreamRuntimeOperationProtocol"] -cne "2") {
        throw "The Field product preference residue values do not match this exact app-only install."
    }
}

function Assert-AndRemoveOwnedProductPreferenceKey {
    if ($script:ownedPreferenceCleanupAttempted) {
        throw "The exact Field product preference cleanup may be attempted only once."
    }
    $script:ownedPreferenceCleanupAttempted = $true
    $counters.ownedPreferenceKeyCleanupAttempts++
    if (-not (Test-Path -LiteralPath $productKey)) {
        throw "The exact Field product preference residue was not present after silent uninstall."
    }
    $properties = Get-ItemProperty -LiteralPath $productKey
    $values = [ordered]@{}
    foreach ($property in $properties.PSObject.Properties) {
        if ($property.Name -match '^PS') { continue }
        $values[$property.Name] = $property.Value
    }
    Assert-OwnedProductPreferenceValues -Values $values -ExpectedInstallRoot $installRoot
    Remove-Item -LiteralPath $productKey -Recurse -Force
    if (Test-Path -LiteralPath $productKey) {
        throw "The exact owned Field product preference key was not removed."
    }
    if (-not (Test-Path -LiteralPath $sharedProductParent)) {
        throw "The shared DroneDream registry parent was removed unexpectedly."
    }
    $counters.ownedPreferenceKeyCleanupInvocations++
    $events.Add([ordered]@{
        stage = "owned-product-preference-cleanup"
        path = $productKey
        exactValueNames = @(
            "(default)",
            "DroneDreamRuntimeDrive",
            "DroneDreamRuntimeInstallMode",
            "DroneDreamRuntimeOperationProtocol"
        )
        exactValuesAccepted = $true
        sharedParentPreserved = $true
    })
}

function Export-ProtectedSimProductKey {
    param([string]$Destination)
    if (-not (Test-Path -LiteralPath $protectedSimProductKey)) {
        throw "The protected Sim product preference key is missing."
    }
    & reg.exe export "HKCU\Software\DroneDream\DroneDream-Sim" $Destination /y | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        throw "Failed to export the protected Sim product preference key."
    }
    $item = Get-Item -LiteralPath $Destination
    return [ordered]@{
        path = $Destination
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Assert-FieldUninstalled {
    foreach ($path in @($installRoot, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Field uninstall residue remains: $path" }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Field uninstall registry residue remains: $key" }
    }
}

$protectedBefore = $null
$protectedSimExportBefore = $null
$protectedSimExportAfter = $null
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
try {
    Assert-FreshPreconditions
    $protectedBefore = Get-ProtectedState
    if (-not $Execute) {
        $result = "green-preflight-passed-not-executed"
        return
    }

    New-Item -ItemType Directory -Path $outputPath | Out-Null
    $tempPath = Join-Path $outputPath "temp"
    New-Item -ItemType Directory -Path $tempPath | Out-Null
    $env:TEMP = $tempPath
    $env:TMP = $tempPath

    $protectedSimExportBefore = Export-ProtectedSimProductKey -Destination (
        Join-Path $outputPath "protected-sim-product-key-before.reg"
    )
    if ($protectedSimExportBefore.sha256 -cne $expectedProtectedSimSha256) {
        throw "The protected Sim product preference key changed before Field execution."
    }

    $counters.freshInstallerInvocations++
    Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S") -Stage "fresh-install"
    $freshInstalled = $true
    Assert-FieldInstalled -Stage "fresh-install"
    Assert-ProtectedParity -Before $protectedBefore -Stage "fresh-install"

    Invoke-LiveInspection -Phase "fresh" -LaunchPath $appBinary
    Assert-ProtectedParity -Before $protectedBefore -Stage "fresh-live-webview2"

    $counters.overlayInstallerInvocations++
    Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S", "/UPDATE") -Stage "overlay-install"
    Assert-FieldInstalled -Stage "overlay-install"
    Assert-ProtectedParity -Before $protectedBefore -Stage "overlay-install"

    if (-not (Test-Path -LiteralPath $desktopShortcut -PathType Leaf)) {
        throw "The exact Field desktop shortcut is missing before shortcut launch."
    }
    Invoke-LiveInspection -Phase "overlay" -LaunchPath $desktopShortcut -IsShortcutLaunch $true
    Assert-ProtectedParity -Before $protectedBefore -Stage "overlay-live-webview2"

    $counters.uninstallerInvocations++
    Invoke-ProcessOnce -Executable $uninstaller -Arguments @("/S") -Stage "uninstall"
    Assert-AndRemoveOwnedProductPreferenceKey
    Remove-OwnedAppData
    Assert-FieldUninstalled
    Assert-ProtectedParity -Before $protectedBefore -Stage "uninstall-and-owned-cleanup"

    $protectedSimExportAfter = Export-ProtectedSimProductKey -Destination (
        Join-Path $outputPath "protected-sim-product-key-after.reg"
    )
    if ($protectedSimExportAfter.bytes -ne $protectedSimExportBefore.bytes -or
        $protectedSimExportAfter.sha256 -cne $protectedSimExportBefore.sha256) {
        throw "The protected Sim product preference key changed during Field execution."
    }

    $expectedCounts = $applicationContract.segments.a.exactCounts
    foreach ($name in $counters.Keys) {
        if ([int]$counters[$name] -ne [int]$expectedCounts.$name) {
            throw "Segment A count mismatch for $name."
        }
    }
    $result = "segment-a-passed"
} catch {
    $failure = $_.Exception.Message
    $result = "segment-a-failed-no-retry"
    try { Stop-OwnedFieldProcess } catch { $events.Add([ordered]@{ stage = "rollback-stop"; error = $_.Exception.Message }) }
    if ($freshInstalled -and (Test-Path -LiteralPath $uninstaller -PathType Leaf) -and
        $counters.uninstallerInvocations -eq 0) {
        try {
            $counters.uninstallerInvocations++
            Invoke-ProcessOnce -Executable $uninstaller -Arguments @("/S") -Stage "failure-rollback-uninstall"
        } catch {
            $events.Add([ordered]@{ stage = "failure-rollback-uninstall"; error = $_.Exception.Message })
        }
    }
    if ((Test-Path -LiteralPath $productKey) -and -not $script:ownedPreferenceCleanupAttempted) {
        try {
            Assert-AndRemoveOwnedProductPreferenceKey
        } catch {
            $events.Add([ordered]@{ stage = "failure-owned-preference-cleanup"; error = $_.Exception.Message })
        }
    }
    try { Remove-OwnedAppData } catch { $events.Add([ordered]@{ stage = "failure-owned-cleanup"; error = $_.Exception.Message }) }
} finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    if (-not (Test-Path -LiteralPath $outputPath)) {
        New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
    }
    $receipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-field-red-segment-a-lifecycle-receipt"
        result = $result
        productSourceCommit = $productSource
        evidenceHeadAtExecution = (git rev-parse HEAD).Trim()
        artifact = [ordered]@{
            path = $installerPath
            bytes = [long]$installerItem.Length
            sha256 = $installerSha256
        }
        application = [ordered]@{ path = $applicationPath; sha256 = $applicationSha256 }
        ownedIdentity = [ordered]@{
            productName = $productName
            displayName = $displayName
            bundleId = $bundleId
            installRoot = $installRoot
            uninstallKey = $uninstallKey
            productKey = $productKey
            desktopShortcut = $desktopShortcut
            startMenuShortcut = $startMenuShortcut
        }
        counters = $counters
        events = @($events)
        protectedStateBefore = $protectedBefore
        protectedStateAfter = if ($null -ne $protectedBefore) { Get-ProtectedState } else { $null }
        protectedSimProductKey = [ordered]@{
            registryPath = $protectedSimProductKey
            expectedSha256 = $expectedProtectedSimSha256
            before = $protectedSimExportBefore
            after = $protectedSimExportAfter
        }
        finalOwnedState = [ordered]@{
            installRoot = Get-PathRecord -Path $installRoot
            roamingAppData = Get-PathRecord -Path $roamingAppData
            localAppData = Get-PathRecord -Path $localAppData
            uninstallRegistration = Get-RegistryRecord -Path $uninstallKey
            productRegistration = Get-RegistryRecord -Path $productKey
            desktopShortcut = Get-ShortcutRecord -Path $desktopShortcut
            startMenuShortcut = Get-ShortcutRecord -Path $startMenuShortcut
        }
        oauth = [ordered]@{
            browserLaunches = 0
            oauthBoundaryChecks = 0
            accountReads = 0
            tokenReadsOrExchanges = 0
            segmentBState = "fail-closed-not-executed"
        }
        failure = $failure
        releaseReady = $false
        websiteHandoffReady = $false
    }
    $receiptPath = Join-Path $outputPath "field-red-segment-a-lifecycle-receipt.json"
    $receipt | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Output $receiptPath
}

if ($result -eq "segment-a-failed-no-retry") { exit 1 }
