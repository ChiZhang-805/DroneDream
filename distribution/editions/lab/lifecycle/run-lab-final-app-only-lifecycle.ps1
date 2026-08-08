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
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedProductSourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$Application,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedApplicationSha256,
    [Parameter(Mandatory = $true)]
    [string]$Plan,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedPlanSha256,
    [Parameter(Mandatory = $true)]
    [string]$TargetReceipt,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedTargetReceiptSha256,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-LfNormalizedSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    $normalized = $text.Replace("`r`n", "`n").Replace("`r", "`n")
    $bytes = [Text.Encoding]::UTF8.GetBytes($normalized)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

$productSource = $ExpectedProductSourceCommit
$productName = "DroneDream-Lab"
$displayName = "DroneDream $([char]0x00B7) LAB"
$mainBinaryName = "drone-dream-desktop.exe"
$bundleId = "io.dronedream.desktop.lab"
$installRoot = Join-Path $env:LOCALAPPDATA $productName
$appBinary = Join-Path $installRoot $mainBinaryName
$uninstaller = Join-Path $installRoot "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$roamingAppData = Join-Path $env:APPDATA $bundleId
$localAppData = Join-Path $env:LOCALAPPDATA $bundleId
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$displayName.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$displayName.lnk"
$inspector = Join-Path $PSScriptRoot "inspect-lab-e3b427e-live-webview2.mjs"
$requestDiagnosticsClassifier = Join-Path $PSScriptRoot "lab-request-origin-diagnostics.mjs"
$adapterPath = $MyInvocation.MyCommand.Path

$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$targetReceiptPath = (Resolve-Path -LiteralPath $TargetReceipt).Path
$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$allowedOutputBase = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream-Codex\Lab-RED")
).TrimEnd("\")
if (-not ($outputPath + "\").StartsWith(
    $allowedOutputBase + "\",
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "OutputRoot must be a fresh child of the Lab RED owned base."
}
if (Test-Path -LiteralPath $outputPath) {
    throw "OutputRoot already exists; refusing to reuse lifecycle evidence."
}

$installerItem = Get-Item -LiteralPath $installerPath
$installerSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$applicationSha256 = (Get-FileHash -LiteralPath $applicationPath -Algorithm SHA256).Hash.ToLowerInvariant()
$planSha256 = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
$targetReceiptSha256 = (
    Get-FileHash -LiteralPath $targetReceiptPath -Algorithm SHA256
).Hash.ToLowerInvariant()
$adapterSha256 = Get-LfNormalizedSha256 -Path $adapterPath
$inspectorSha256 = Get-LfNormalizedSha256 -Path $inspector
$requestDiagnosticsClassifierSha256 = Get-LfNormalizedSha256 -Path $requestDiagnosticsClassifier
if ($installerItem.Length -ne $ExpectedInstallerBytes -or $installerSha256 -cne $ExpectedInstallerSha256) {
    throw "The exact frozen Lab installer identity does not match the application."
}
if ($applicationSha256 -cne $ExpectedApplicationSha256) {
    throw "The exact RED application SHA-256 does not match."
}
if ($planSha256 -cne $ExpectedPlanSha256 -or
    $targetReceiptSha256 -cne $ExpectedTargetReceiptSha256) {
    throw "The exact RED plan or target receipt SHA-256 does not match."
}
$applicationContract = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$planContract = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
$targetReceiptContract = Get-Content `
    -LiteralPath $targetReceiptPath `
    -Raw `
    -Encoding UTF8 | ConvertFrom-Json
if ($applicationContract.artifact.sha256 -cne $ExpectedInstallerSha256 -or
    $applicationContract.artifact.bytes -ne $ExpectedInstallerBytes -or
    $applicationContract.sourceSeparation.artifactProductSourceCommit -cne $productSource -or
    $applicationContract.plan.sha256 -cne $planSha256 -or
    $applicationContract.targetReceipt.sha256 -cne $targetReceiptSha256 -or
    $planContract.artifact.sha256 -cne $ExpectedInstallerSha256 -or
    $targetReceiptContract.artifact.sha256 -cne $ExpectedInstallerSha256) {
    throw "The RED application is not bound to the exact frozen Lab artifact."
}
if ($applicationContract.executionTools.adapter.lfNormalizedSha256 -cne $adapterSha256 -or
    $applicationContract.executionTools.liveInspector.lfNormalizedSha256 -cne $inspectorSha256 -or
    $applicationContract.executionTools.requestDiagnosticsClassifier.lfNormalizedSha256 -cne
        $requestDiagnosticsClassifierSha256) {
    throw "The RED application is not bound to the exact lifecycle diagnostics tools."
}
if ($applicationContract.authorization.segmentAExecutionDecision -cne
    "prepared-awaiting-new-exact-red-authorization") {
    throw "Segment A is not in its exact prepared state."
}
if ($applicationContract.authorization.segmentBExecutionDecision -cne
    "deny-before-real-auth-boundary") {
    throw "Segment B must remain fail-closed."
}
if ($applicationContract.attempt.maximumExecutionInvocations -ne 1 -or
    $applicationContract.attempt.automaticRetryMaximum -ne 0 -or
    $applicationContract.ownedIsolation.runRootMustBeAbsentBeforeExecution -ne $true -or
    $applicationContract.ownedIsolation.runId -cne (Split-Path -Leaf $outputPath) -or
    [IO.Path]::GetFullPath($applicationContract.ownedIsolation.runRoot).TrimEnd("\") -cne
        $outputPath) {
    throw "The one-shot lifecycle attempt or owned output root binding does not match."
}

$counters = [ordered]@{
    freshInstallerInvocations = 0
    overlayInstallerInvocations = 0
    applicationLaunches = 0
    applicationCloses = 0
    uninstallerInvocations = 0
    ownedPreferenceKeyCleanupInvocations = 0
    liveWebView2Inspections = 0
    languageTransitions = 0
    languageSurfaceAssertions = 0
    settingsSingleScreenChecks = 0
    labThemeChecks = 0
    authorityFalseChecks = 0
    shortcutIdentityChecks = 0
    protectedStateSnapshots = 0
    protectedStateParityChecks = 0
    browserLaunches = 0
    oauthBoundaryChecks = 0
    providerTokenExchanges = 0
    accountReads = 0
    artifactBuilds = 0
    runtimeStartsOrMigrations = 0
    px4Starts = 0
    gazeboStarts = 0
    hardwareActions = 0
    uploadsOrDeployments = 0
}
$expectedCountNames = @($counters.Keys | Sort-Object)
foreach ($contractCounts in @(
    $applicationContract.segments.a.exactCounts,
    $planContract.exactCounts,
    $targetReceiptContract.requiredExactCounts
)) {
    $contractNames = @($contractCounts.PSObject.Properties.Name | Sort-Object)
    if (($contractNames -join "`n") -cne ($expectedCountNames -join "`n")) {
        throw "The RED count contract has missing or unexpected fields."
    }
    foreach ($name in $expectedCountNames) {
        if ([int]$contractCounts.$name -ne [int]$applicationContract.segments.a.exactCounts.$name) {
            throw "The RED plan, target receipt, and application count contracts disagree for $name."
        }
    }
}
if ($applicationContract.safety.validatedVehiclePackCount -ne 0 -or
    $applicationContract.safety.hardwareWriteArmHitlFlightDecision -cne "deny" -or
    $applicationContract.safety.frontendSettingsThemeOrWorkspaceCountsAsAuthority -ne $false -or
    $planContract.safety.validatedVehiclePackCount -ne 0 -or
    $planContract.safety.hardwareWriteArmHitlFlightDecision -cne "deny" -or
    $targetReceiptContract.requiredOutcome.validatedVehiclePackCount -ne 0 -or
    $targetReceiptContract.requiredOutcome.hardwareWriteArmHitlFlightDecision -cne "deny") {
    throw "The exact zero-pack hardware deny contract is not intact."
}
$events = [Collections.Generic.List[object]]::new()
$appProcess = $null
$freshInstalled = $false
$result = "not-executed"
$failure = $null

function Get-DirectoryContentDigest {
    param([string]$Path)
    $records = [Collections.Generic.List[string]]::new()
    foreach ($file in @(Get-ChildItem -LiteralPath $Path -File -Recurse | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($Path.TrimEnd("\").Length + 1).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $records.Add("$relative|$($file.Length)|$hash")
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($records -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-PathRecord {
    param([string]$Path, [bool]$HashDirectoryContents = $false)
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    return [ordered]@{
        path = $Path
        exists = ($null -ne $item)
        isDirectory = if ($null -ne $item) { [bool]$item.PSIsContainer } else { $null }
        length = if ($null -ne $item -and -not $item.PSIsContainer) { [long]$item.Length } else { $null }
        lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
        contentSha256 = if ($null -ne $item -and $item.PSIsContainer -and $HashDirectoryContents) {
            Get-DirectoryContentDigest -Path $item.FullName
        } elseif ($null -ne $item -and -not $item.PSIsContainer) {
            (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        } else { $null }
    }
}

function Get-RegistryRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ path = $Path; exists = $false; values = [ordered]@{} }
    }
    $item = Get-ItemProperty -LiteralPath $Path
    $values = [ordered]@{}
    foreach ($property in @($item.PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' } | Sort-Object Name)) {
        $values[$property.Name] = $property.Value
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
            arguments = $shortcut.Arguments
            workingDirectory = $shortcut.WorkingDirectory
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
    $otherRoots = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Field") |
        ForEach-Object { Get-PathRecord -Path (Join-Path $env:LOCALAPPDATA $_) -HashDirectoryContents $true }
    $otherKeys = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Field") |
        ForEach-Object {
            Get-RegistryRecord -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$_"
        }
    $otherProductKeys = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Field") |
        ForEach-Object { Get-RegistryRecord -Path "HKCU:\Software\DroneDream\$_" }
    $protectedDisplayNames = @(
        "DroneDream",
        "DroneDream $([char]0x00B7) SIM",
        "DroneDream $([char]0x00B7) FIELD"
    )
    $protectedShortcuts = foreach ($name in $protectedDisplayNames) {
        Get-ShortcutRecord -Path (Join-Path ([Environment]::GetFolderPath("Desktop")) "$name.lnk")
        Get-ShortcutRecord -Path (Join-Path ([Environment]::GetFolderPath("Programs")) "$name.lnk")
    }
    $runtimeRoots = @(
        Get-PathRecord -Path "C:\DroneDream"
        Get-PathRecord -Path "Z:\DroneDream"
    )
    return [ordered]@{
        otherEditionRoots = @($otherRoots)
        otherEditionUninstallKeys = @($otherKeys)
        otherEditionProductKeys = @($otherProductKeys)
        otherEditionShortcuts = @($protectedShortcuts)
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
    $counters.protectedStateSnapshots++
    $counters.protectedStateParityChecks++
    $events.Add([ordered]@{ stage = $Stage; protectedStateParity = $true })
}

function Assert-FreshPreconditions {
    foreach ($path in @($installRoot, $roamingAppData, $localAppData, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Fresh precondition failed: $path exists." }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Fresh precondition failed: $key exists." }
    }
    $listeners = @(Get-NetTCPConnection -LocalPort 49212 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -ne 0) { throw "Lab OAuth callback port 49212 is already listening." }
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

function Assert-LabInstalled {
    param([string]$Stage)
    foreach ($path in @($appBinary, $uninstaller)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "$Stage missing $path." }
    }
    $registration = Get-RegistryRecord -Path $uninstallKey
    if (-not $registration.exists -or $registration.values.DisplayName -cne $displayName -or
        $registration.values.DisplayVersion -cne "1.0.0" -or
        $registration.values.MainBinaryName -cne $mainBinaryName -or
        $registration.values.InstallLocation.Trim('"') -cne $installRoot) {
        throw "$Stage produced an invalid Lab uninstall registration."
    }
    foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
        $shortcut = Get-ShortcutRecord -Path $shortcutPath
        if (-not $shortcut.exists -or $shortcut.target -cne $appBinary) {
            throw "$Stage produced an invalid Lab shortcut: $shortcutPath"
        }
    }
    $counters.shortcutIdentityChecks++
    $events.Add([ordered]@{ stage = $Stage; labIdentityAccepted = $true })
}

function Get-FreeLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port } finally { $listener.Stop() }
}

function Stop-OwnedLabProcess {
    if ($null -eq $script:appProcess) { return }
    $exitedBeforePlannedClose = $script:appProcess.HasExited
    try {
        if (-not $exitedBeforePlannedClose) {
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
    if ($exitedBeforePlannedClose) {
        throw "The owned Lab desktop process exited before the planned close."
    }
    Start-Sleep -Seconds 2
    if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "The owned Lab desktop process did not stop."
    }
    $counters.applicationCloses++
}

function Invoke-LiveInspection {
    param([string]$Phase)
    $port = Get-FreeLoopbackPort
    $oldArguments = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
    try {
        $script:appProcess = Start-Process -FilePath $appBinary -PassThru
        $counters.applicationLaunches++
        $endpoint = "http://127.0.0.1:$port"
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            try {
                Invoke-WebRequest -Uri "$endpoint/json/version" -UseBasicParsing -TimeoutSec 2 | Out-Null
                break
            } catch {
                if ($script:appProcess.HasExited) { throw "Lab exited before WebView2 inspection." }
                Start-Sleep -Milliseconds 300
            }
        } while ([DateTime]::UtcNow -lt $deadline)
        if ([DateTime]::UtcNow -ge $deadline) { throw "Timed out waiting for live Lab WebView2." }

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
            $inspection.forbiddenProviderRequestCount -ne 0 -or
            $inspection.authStorageKeyCount -ne 0 -or $inspection.browserLaunchCount -ne 0 -or
            $inspection.oauthBoundaryCheckCount -ne 0 -or $inspection.accountReadCount -ne 0 -or
            $inspection.providerTokenExchangeCount -ne 0 -or
            $inspection.languageTransitionCount -ne 1 -or
            $inspection.languageSurfaceAssertionCount -ne 2 -or
            -not $inspection.settings.singleScreenNoVerticalScroll -or
            -not $inspection.settings.presentationOnly -or
            $inspection.settings.grantsHardwareAuthority -ne $false -or
            ($inspection.theme.gradientStops -join ",") -cne "#A7E84A,#20C77A,#087E69" -or
            -not $inspection.threeD.rendered -or -not $inspection.threeD.responded -or
            $inspection.threeD.grantsHardwareAuthority -ne $false -or
            -not $inspection.webView2.existingRuntimeReadOnly) {
            throw "The $Phase live WebView2 inspection violated Segment A."
        }
        $counters.liveWebView2Inspections++
        $counters.languageTransitions += [int]$inspection.languageTransitionCount
        $counters.languageSurfaceAssertions += [int]$inspection.languageSurfaceAssertionCount
        $counters.settingsSingleScreenChecks++
        $counters.labThemeChecks++
        $counters.authorityFalseChecks++
        $events.Add([ordered]@{
            stage = "$Phase-live-webview2"
            processId = $script:appProcess.Id
            inspectionPath = $inspectionPath
            initialLocale = $inspection.initialLocale
            finalLocale = $inspection.finalLocale
            webView2PageLocation = $inspection.pageLocation
            requestDiagnosticsPath = $inspection.requestDiagnosticsPath
            brandNaturalWidth = $inspection.brand.naturalWidth
            brandNaturalHeight = $inspection.brand.naturalHeight
            forbiddenAuthRequestCount = 0
            forbiddenProviderRequestCount = 0
            settingsSingleScreenNoVerticalScroll = $true
            labThemeAndThreeDResponsive = $true
            presentationOnly = $true
            grantsHardwareAuthority = $false
        })
    } finally {
        if ($null -eq $oldArguments) {
            Remove-Item Env:\WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
        } else {
            $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $oldArguments
        }
        Stop-OwnedLabProcess
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
            throw "Owned Lab app-data cleanup escaped its exact namespace."
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
        throw "The Lab product preference residue contains missing or unexpected values."
    }
    if ([string]$Values["(default)"] -cne $ExpectedInstallRoot -or
        [string]$Values["DroneDreamRuntimeInstallMode"] -cne "install-app-only" -or
        [string]$Values["DroneDreamRuntimeDrive"] -cne "" -or
        [string]$Values["DroneDreamRuntimeOperationProtocol"] -cne "2") {
        throw "The Lab product preference residue values do not match this exact app-only install."
    }
}

function Assert-AndRemoveOwnedProductPreferenceKey {
    if (-not (Test-Path -LiteralPath $productKey)) {
        throw "The exact Lab product preference residue was not present after silent uninstall."
    }
    $properties = Get-ItemProperty -LiteralPath $productKey
    $values = [ordered]@{}
    foreach ($property in $properties.PSObject.Properties) {
        if ($property.Name -match '^PS') { continue }
        $values[$property.Name] = $property.Value
    }
    Assert-OwnedProductPreferenceValues -Values $values -ExpectedInstallRoot $installRoot
    $expectedNames = @(
        "(default)",
        "DroneDreamRuntimeDrive",
        "DroneDreamRuntimeInstallMode",
        "DroneDreamRuntimeOperationProtocol"
    ) | Sort-Object
    Remove-Item -LiteralPath $productKey -Recurse -Force
    if (Test-Path -LiteralPath $productKey) {
        throw "The exact owned Lab product preference key was not removed."
    }
    if (-not (Test-Path -LiteralPath "HKCU:\Software\DroneDream")) {
        throw "The shared DroneDream registry parent was removed unexpectedly."
    }
    $counters.ownedPreferenceKeyCleanupInvocations++
    $events.Add([ordered]@{
        stage = "owned-product-preference-cleanup"
        path = $productKey
        exactValueNames = $expectedNames
        exactValuesAccepted = $true
        sharedParentPreserved = $true
    })
}

function Assert-LabUninstalled {
    foreach ($path in @($installRoot, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Lab uninstall residue remains: $path" }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Lab uninstall registry residue remains: $key" }
    }
    $counters.shortcutIdentityChecks++
}

$protectedBefore = $null
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
Assert-FreshPreconditions
if (-not $Execute) {
    $result = "green-plan-only-preflight-passed-no-execute"
    [ordered]@{
        result = $result
        productSourceCommit = $productSource
        artifactSha256 = $installerSha256
        applicationSha256 = $applicationSha256
        planSha256 = $planSha256
        targetReceiptSha256 = $targetReceiptSha256
        adapterSha256 = $adapterSha256
        liveInspectorSha256 = $inspectorSha256
        requestDiagnosticsClassifierSha256 = $requestDiagnosticsClassifierSha256
        outputRootCreated = $false
        executionAuthorized = $false
    } | ConvertTo-Json -Depth 5
    exit 0
}
$protectedBefore = Get-ProtectedState
$counters.protectedStateSnapshots++
try {

    New-Item -ItemType Directory -Path $outputPath | Out-Null
    $tempPath = Join-Path $outputPath "temp"
    New-Item -ItemType Directory -Path $tempPath | Out-Null
    $env:TEMP = $tempPath
    $env:TMP = $tempPath

    $counters.freshInstallerInvocations++
    Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S") -Stage "fresh-install"
    $freshInstalled = $true
    Assert-LabInstalled -Stage "fresh-install"
    Assert-ProtectedParity -Before $protectedBefore -Stage "fresh-install"

    Invoke-LiveInspection -Phase "fresh"

    $counters.overlayInstallerInvocations++
    Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S", "/UPDATE") -Stage "overlay-install"
    Assert-LabInstalled -Stage "overlay-install"
    Assert-ProtectedParity -Before $protectedBefore -Stage "overlay-install"

    Invoke-LiveInspection -Phase "overlay"
    Assert-ProtectedParity -Before $protectedBefore -Stage "overlay-live-webview2"

    $counters.uninstallerInvocations++
    Invoke-ProcessOnce -Executable $uninstaller -Arguments @("/S") -Stage "uninstall"
    Assert-AndRemoveOwnedProductPreferenceKey
    Remove-OwnedAppData
    Assert-LabUninstalled
    Assert-ProtectedParity -Before $protectedBefore -Stage "uninstall-and-owned-cleanup"

    $expectedCounts = $applicationContract.segments.a.exactCounts
    foreach ($name in $counters.Keys) {
        if ([int]$counters[$name] -ne [int]$expectedCounts.$name) {
            throw "Segment A count mismatch for $name."
        }
    }
    $result = "segment-a-app-only-passed"
} catch {
    $failure = $_.Exception.Message
    $result = "segment-a-failed-no-retry"
    try { Stop-OwnedLabProcess } catch { $events.Add([ordered]@{ stage = "rollback-stop"; error = $_.Exception.Message }) }
    if ($freshInstalled -and (Test-Path -LiteralPath $uninstaller -PathType Leaf) -and
        $counters.uninstallerInvocations -eq 0) {
        try {
            $counters.uninstallerInvocations++
            Invoke-ProcessOnce -Executable $uninstaller -Arguments @("/S") -Stage "failure-rollback-uninstall"
        } catch {
            $events.Add([ordered]@{ stage = "failure-rollback-uninstall"; error = $_.Exception.Message })
        }
    }
    if (Test-Path -LiteralPath $productKey) {
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
    if (-not (Test-Path -LiteralPath $outputPath)) { throw "Execution evidence root is missing." }
    $receipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-lab-red-segment-a-lifecycle-receipt"
        result = $result
        productSourceCommit = $productSource
        evidenceHeadAtExecution = (git rev-parse HEAD).Trim()
        artifact = [ordered]@{
            path = $installerPath
            bytes = [long]$installerItem.Length
            sha256 = $installerSha256
        }
        application = [ordered]@{ path = $applicationPath; sha256 = $applicationSha256 }
        plan = [ordered]@{ path = $planPath; sha256 = $planSha256 }
        targetReceipt = [ordered]@{ path = $targetReceiptPath; sha256 = $targetReceiptSha256 }
        executionTools = [ordered]@{
            adapter = [ordered]@{ path = $adapterPath; sha256 = $adapterSha256 }
            liveInspector = [ordered]@{ path = $inspector; sha256 = $inspectorSha256 }
            requestDiagnosticsClassifier = [ordered]@{
                path = $requestDiagnosticsClassifier
                sha256 = $requestDiagnosticsClassifierSha256
            }
        }
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
            providerTokenExchanges = 0
            segmentBState = "fail-closed-not-executed"
        }
        failure = $failure
        releaseReady = $false
        websiteHandoffReady = $false
    }
    $receiptPath = Join-Path $outputPath "lab-red-segment-a-lifecycle-receipt.json"
    $receipt | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Output $receiptPath
}

if ($result -eq "segment-a-failed-no-retry") { exit 1 }


