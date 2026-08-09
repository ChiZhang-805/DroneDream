param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedInstallerSha256,
    [Parameter(Mandatory = $true)][ValidateRange(1, [long]::MaxValue)][long]$ExpectedInstallerBytes,
    [Parameter(Mandatory = $true)][string]$Application,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedApplicationSha256,
    [Parameter(Mandatory = $true)][string]$Plan,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedPlanSha256,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Add-Type -AssemblyName System.Drawing

function Get-LfIdentity {
    param([string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    $bytes = [Text.Encoding]::UTF8.GetBytes($text.Replace("`r`n", "`n").Replace("`r", "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [ordered]@{
            bytes = $bytes.Length
            sha256 = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
        }
    } finally { $sha.Dispose() }
}

function Get-FileRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [ordered]@{ exists = $false } }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        exists = $true
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-PathRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [ordered]@{ exists = $false } }
    $item = Get-Item -LiteralPath $Path -Force
    return [ordered]@{
        exists = $true
        fullName = $item.FullName
        attributes = [string]$item.Attributes
        reparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    }
}

function Get-RegistryRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [ordered]@{ exists = $false } }
    $properties = Get-ItemProperty -LiteralPath $Path
    $values = [ordered]@{}
    foreach ($property in $properties.PSObject.Properties) {
        if ($property.Name -notmatch '^PS') { $values[$property.Name] = $property.Value }
    }
    return [ordered]@{ exists = $true; values = $values }
}

function Get-ShortcutRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [ordered]@{ exists = $false } }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
    return [ordered]@{
        exists = $true
        target = [IO.Path]::GetFullPath($shortcut.TargetPath)
        iconLocation = [string]$shortcut.IconLocation
        file = Get-FileRecord -Path $Path
    }
}

function Get-IconPixelSha256 {
    param([string]$ExecutablePath, [string]$EvidencePath)
    $icon = [Drawing.Icon]::ExtractAssociatedIcon($ExecutablePath)
    if ($null -eq $icon) { throw "No embedded Windows icon was found in $ExecutablePath." }
    try {
        $sourceBitmap = $icon.ToBitmap()
        try {
            $bitmap = [Drawing.Bitmap]::new(32, 32, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
            try {
                $graphics = [Drawing.Graphics]::FromImage($bitmap)
                try {
                    $graphics.Clear([Drawing.Color]::Transparent)
                    $graphics.DrawImage($sourceBitmap, 0, 0, 32, 32)
                } finally { $graphics.Dispose() }
                $bitmap.Save($EvidencePath, [Drawing.Imaging.ImageFormat]::Png)
                $bytes = [Collections.Generic.List[byte]]::new(4096)
                for ($y = 0; $y -lt 32; $y++) {
                    for ($x = 0; $x -lt 32; $x++) {
                        $pixel = $bitmap.GetPixel($x, $y)
                        $bytes.Add($pixel.A); $bytes.Add($pixel.R); $bytes.Add($pixel.G); $bytes.Add($pixel.B)
                    }
                }
                $sha = [Security.Cryptography.SHA256]::Create()
                try {
                    return ([BitConverter]::ToString($sha.ComputeHash($bytes.ToArray()))).Replace("-", "").ToLowerInvariant()
                } finally { $sha.Dispose() }
            } finally { $bitmap.Dispose() }
        } finally { $sourceBitmap.Dispose() }
    } finally { $icon.Dispose() }
}

function Get-WebView2Record {
    $guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $paths = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid"
    )
    foreach ($path in $paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $record = Get-ItemProperty -LiteralPath $path
        if ($record.pv -and $record.pv -ne "0.0.0.0") {
            return [ordered]@{ path = $path; version = [string]$record.pv; location = [string]$record.location }
        }
    }
    throw "A usable existing WebView2 Runtime is required; installation or repair is forbidden."
}

function ConvertTo-StableJson { param([object]$Value) return ($Value | ConvertTo-Json -Depth 20 -Compress) }

$expectedUser = "CodexSandboxOffline"
$expectedSid = "S-1-5-21-2197768555-4123441877-442284878-1020"
$expectedProfile = "C:\Users\CodexSandboxOffline"
$actualUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$actualProfile = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd("\")
if ($env:USERNAME -cne $expectedUser -or $actualUser.User.Value -cne $expectedSid -or
    $actualProfile -cne $expectedProfile) {
    throw "Execution is restricted to the exact CodexSandboxOffline account, SID, and profile."
}
$profileItem = Get-Item -LiteralPath $actualProfile -Force
if ($profileItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw "The disposable provider profile must not be a reparse point."
}
if ([IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd("\") -cne "$expectedProfile\AppData\Local" -or
    [IO.Path]::GetFullPath($env:APPDATA).TrimEnd("\") -cne "$expectedProfile\AppData\Roaming") {
    throw "Provider AppData namespaces do not match the frozen profile."
}

$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$installer = Get-FileRecord -Path $installerPath
$applicationHash = (Get-FileHash -LiteralPath $applicationPath -Algorithm SHA256).Hash.ToLowerInvariant()
$planHash = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($installer.bytes -ne $ExpectedInstallerBytes -or $installer.sha256 -cne $ExpectedInstallerSha256 -or
    $applicationHash -cne $ExpectedApplicationSha256 -or $planHash -cne $ExpectedPlanSha256) {
    throw "Frozen lifecycle input identity mismatch."
}
$contract = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$planContract = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
$adapterIdentity = Get-LfIdentity -Path $MyInvocation.MyCommand.Path
$inspectorPath = Join-Path $PSScriptRoot "inspect-field-owned-launcher.mjs"
$inspectorIdentity = Get-LfIdentity -Path $inspectorPath
if ($contract.tools.runner.lfNormalizedSha256 -cne $adapterIdentity.sha256 -or
    $contract.tools.runner.lfNormalizedBytes -ne $adapterIdentity.bytes -or
    $contract.tools.launcherInspector.lfNormalizedSha256 -cne $inspectorIdentity.sha256 -or
    $contract.tools.launcherInspector.lfNormalizedBytes -ne $inspectorIdentity.bytes) {
    throw "Application is not bound to the exact runner and launcher inspector."
}
if ($contract.provider.accountName -cne $expectedUser -or $contract.provider.sid -cne $expectedSid -or
    [IO.Path]::GetFullPath($contract.provider.profileRoot).TrimEnd("\") -cne $expectedProfile -or
    $contract.provider.passwordReadRecordedOrPassedAllowed -ne $false) {
    throw "Disposable provider contract mismatch."
}
$expectedCounterNames = @($contract.counts.PSObject.Properties.Name | Sort-Object)
$planCounterNames = @($planContract.counts.PSObject.Properties.Name | Sort-Object)
if (($expectedCounterNames -join "`n") -cne ($planCounterNames -join "`n")) {
    throw "Application and plan count schemas differ."
}

$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$allowedBase = "$expectedProfile\AppData\Local\DroneDream-Codex\Field-RED"
if (-not ($outputPath + "\").StartsWith($allowedBase + "\", [StringComparison]::OrdinalIgnoreCase) -or
    $outputPath -cne [IO.Path]::GetFullPath($contract.isolation.runRoot).TrimEnd("\")) {
    throw "OutputRoot is outside the exact provider-owned Field RED root."
}
if (Test-Path -LiteralPath $outputPath) { throw "Lifecycle run root already exists." }
if ($contract.attempt.ordinal -ne 1 -or $contract.attempt.maximum -ne 1 -or
    $contract.attempt.executionsAtFreeze -ne 0 -or $contract.attempt.retryMaximum -ne 0) {
    throw "One-shot lifecycle attempt contract mismatch."
}

$productName = "DroneDream-Field"
$displayName = "DroneDream $([char]0x00B7) FIELD"
$mainBinaryName = "drone-dream-desktop.exe"
$bundleId = "io.dronedream.desktop.field"
$installRoot = Join-Path $env:LOCALAPPDATA $productName
$appBinary = Join-Path $installRoot $mainBinaryName
$uninstaller = Join-Path $installRoot "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$roamingAppData = Join-Path $env:APPDATA $bundleId
$localAppData = Join-Path $env:LOCALAPPDATA $bundleId
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$displayName.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$displayName.lnk"

function Get-ProtectedState {
    return [ordered]@{
        otherRoots = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab") |
            ForEach-Object { Get-PathRecord (Join-Path $env:LOCALAPPDATA $_) }
        otherUninstallKeys = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab") |
            ForEach-Object { Get-RegistryRecord "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$_" }
        webView2 = Get-WebView2Record
    }
}

function Assert-ProtectedParity { param([object]$Before, [string]$Stage)
    if ((ConvertTo-StableJson $Before) -cne (ConvertTo-StableJson (Get-ProtectedState))) {
        throw "Protected provider state changed during $Stage."
    }
}

function Assert-Fresh {
    foreach ($path in @($installRoot, $roamingAppData, $localAppData, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Fresh precondition failed: $path" }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Fresh registry precondition failed: $key" }
    }
    if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "A DroneDream desktop process is already running in the provider session."
    }
    Get-WebView2Record | Out-Null
}

function Invoke-ProcessOnce { param([string]$File, [string[]]$Arguments, [string]$Stage)
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try { if ($process.ExitCode -ne 0) { throw "$Stage exited with code $($process.ExitCode)." } }
    finally { $process.Dispose() }
}

function Assert-Installed {
    if (-not (Test-Path $appBinary -PathType Leaf) -or -not (Test-Path $uninstaller -PathType Leaf)) {
        throw "Installed Field binaries are missing."
    }
    $installedBinary = Get-FileRecord $appBinary
    if ($installedBinary.bytes -ne [long]$contract.artifact.installedMainBinary.bytes -or
        $installedBinary.sha256 -cne [string]$contract.artifact.installedMainBinary.sha256) {
        throw "Installed Field main binary differs from the source-bound payload."
    }
    $registration = Get-RegistryRecord $uninstallKey
    if (-not $registration.exists -or $registration.values.DisplayName -cne $displayName -or
        $registration.values.DisplayVersion -cne "1.0.0" -or
        $registration.values.InstallLocation.Trim('"') -cne $installRoot) {
        throw "Field uninstall registration is invalid."
    }
    foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
        $shortcut = Get-ShortcutRecord $shortcutPath
        if (-not $shortcut.exists -or $shortcut.target -cne $appBinary) {
            throw "Field shortcut identity is invalid."
        }
    }
}

function Assert-IconSurfaces {
    $canonicalPath = Join-Path $PSScriptRoot "..\..\..\..\brand\generated\field\windows\32x32.png"
    $canonicalPath = (Resolve-Path $canonicalPath).Path
    $canonicalPixelEvidence = Join-Path $outputPath "canonical-field-icon-32.png"
    Copy-Item $canonicalPath $canonicalPixelEvidence
    $canonicalBitmap = [Drawing.Bitmap]::new($canonicalPath)
    try {
        if ($canonicalBitmap.Width -ne 32 -or $canonicalBitmap.Height -ne 32) {
            throw "Canonical Field render source is not 32x32."
        }
        $bytes = [Collections.Generic.List[byte]]::new(4096)
        for ($y = 0; $y -lt 32; $y++) {
            for ($x = 0; $x -lt 32; $x++) {
                $pixel = $canonicalBitmap.GetPixel($x, $y)
                $bytes.Add($pixel.A); $bytes.Add($pixel.R); $bytes.Add($pixel.G); $bytes.Add($pixel.B)
            }
        }
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $canonicalPixelSha = ([BitConverter]::ToString($sha.ComputeHash($bytes.ToArray()))).Replace("-", "").ToLowerInvariant() }
        finally { $sha.Dispose() }
    } finally { $canonicalBitmap.Dispose() }

    $surfaces = [ordered]@{
        installer = $installerPath
        installedExe = $appBinary
        desktopShortcut = (Get-ShortcutRecord $desktopShortcut).target
        startMenuShortcut = (Get-ShortcutRecord $startMenuShortcut).target
    }
    foreach ($surface in $surfaces.Keys) {
        $pixelSha = Get-IconPixelSha256 $surfaces[$surface] (Join-Path $outputPath "$surface-icon-32.png")
        if ($pixelSha -cne $canonicalPixelSha) { throw "$surface icon pixels differ from canonical FIELD." }
    }
    return [ordered]@{ canonicalPixelSha256 = $canonicalPixelSha; surfaces = $surfaces }
}

function Get-FreePort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start(); try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port } finally { $listener.Stop() }
}

$script:appProcess = $null
function Stop-OwnedApp {
    if ($null -eq $script:appProcess) { return }
    try {
        if (-not $script:appProcess.HasExited) {
            $script:appProcess.CloseMainWindow() | Out-Null
            if (-not $script:appProcess.WaitForExit(5000)) { Stop-Process $script:appProcess.Id -Force }
        }
    } finally { $script:appProcess.Dispose(); $script:appProcess = $null }
}

function Invoke-LauncherInspection { param([string]$Phase, [string]$LaunchPath)
    $port = Get-FreePort
    $old = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
    try {
        $script:appProcess = Start-Process -FilePath $LaunchPath -PassThru
        $endpoint = "http://127.0.0.1:$port"
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            try { Invoke-WebRequest "$endpoint/json/version" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
            catch { if ($script:appProcess.HasExited) { throw "Field exited before inspection." }; Start-Sleep -Milliseconds 300 }
        } while ([DateTime]::UtcNow -lt $deadline)
        if ([DateTime]::UtcNow -ge $deadline) { throw "Timed out waiting for Field WebView2." }
        $out = Join-Path $outputPath "$Phase-launcher.json"
        $node = Start-Process node.exe -ArgumentList @($inspectorPath, $endpoint, $Phase, $out) `
            -WorkingDirectory $contract.inspection.playwrightWorkingDirectory -PassThru -Wait -WindowStyle Hidden
        try { if ($node.ExitCode -ne 0) { throw "$Phase launcher inspection failed." } } finally { $node.Dispose() }
        $inspection = Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $inspection.passed -or $inspection.authButtonClicked -or $inspection.fieldAppEntered -or
            -not $inspection.live3dObserved -or $inspection.forbiddenRequestCount -ne 0) {
            throw "$Phase launcher violated the frozen no-auth boundary."
        }
        return $inspection
    } finally {
        if ($null -eq $old) { Remove-Item Env:\WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue }
        else { $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $old }
        Stop-OwnedApp
    }
}

function Remove-OwnedResidue {
    if (Test-Path $productKey) {
        $values = Get-RegistryRecord $productKey
        if (-not $values.exists -or [string]$values.values.'(default)' -cne $installRoot) {
            throw "Refusing to remove an unrecognized Field preference key."
        }
        Remove-Item $productKey -Recurse -Force
    }
    foreach ($path in @($roamingAppData, $localAppData)) {
        if (-not (Test-Path $path)) { continue }
        $resolved = (Resolve-Path $path).Path.TrimEnd("\")
        if (-not ($resolved + "\").StartsWith($expectedProfile + "\", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Owned cleanup escaped provider profile."
        }
        Remove-Item $resolved -Recurse -Force
    }
}

$counters = [ordered]@{
    freshInstallerInvocations = 0; overlayInstallerInvocations = 0; applicationLaunches = 0
    applicationCloses = 0; launcherInspections = 0; languageTransitions = 0
    threeDChecks = 0; authorityFalseChecks = 0; iconSurfaceChecks = 0
    settingsLiveChecks = 0; uninstallerInvocations = 0; ownedCleanupInvocations = 0
    browserLaunches = 0; oauthTransactions = 0; accountReads = 0; tokenReads = 0
    runtimeActions = 0; px4Actions = 0; gazeboActions = 0; hardwareActions = 0
    builds = 0; uploadsOrDeployments = 0
}
$events = [Collections.Generic.List[object]]::new()
$result = "green-plan-only-not-executed"
$failure = $null
$freshInstalled = $false
$protectedBefore = $null

if (-not $Execute) {
    [ordered]@{ result = $result; provider = $expectedUser; runRootCreated = $false; counters = $counters } |
        ConvertTo-Json -Depth 5
    exit 0
}

try {
    Assert-Fresh
    $protectedBefore = Get-ProtectedState
    New-Item -ItemType Directory -Path $outputPath | Out-Null
    $env:TEMP = New-Item -ItemType Directory -Path (Join-Path $outputPath "temp") | Select-Object -ExpandProperty FullName
    $env:TMP = $env:TEMP

    $counters.freshInstallerInvocations++
    Invoke-ProcessOnce $installerPath @("/S", "/LANG=1033") "fresh-install-en"
    $freshInstalled = $true
    Assert-Installed
    Assert-ProtectedParity $protectedBefore "fresh-install"
    $iconEvidence = Assert-IconSurfaces
    $counters.iconSurfaceChecks += 4
    $counters.applicationLaunches++
    $freshInspection = Invoke-LauncherInspection "fresh" $appBinary
    $counters.applicationCloses++; $counters.launcherInspections++; $counters.languageTransitions++
    $counters.threeDChecks++; $counters.authorityFalseChecks++

    $counters.overlayInstallerInvocations++
    Invoke-ProcessOnce $installerPath @("/S", "/UPDATE", "/LANG=2052") "overlay-install-zh"
    Assert-Installed
    Assert-ProtectedParity $protectedBefore "overlay-install"
    $counters.applicationLaunches++
    $overlayInspection = Invoke-LauncherInspection "overlay" $desktopShortcut
    $counters.applicationCloses++; $counters.launcherInspections++; $counters.languageTransitions++
    $counters.threeDChecks++; $counters.authorityFalseChecks++

    $counters.uninstallerInvocations++
    Invoke-ProcessOnce $uninstaller @("/S") "uninstall"
    $counters.ownedCleanupInvocations++
    Remove-OwnedResidue
    foreach ($path in @($installRoot, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path $path) { throw "Field lifecycle residue remains: $path" }
    }
    if ((Test-Path $uninstallKey) -or (Test-Path $productKey)) { throw "Field registry residue remains." }
    Assert-ProtectedParity $protectedBefore "uninstall-cleanup"
    foreach ($name in $counters.Keys) {
        if ([int]$counters[$name] -ne [int]$contract.counts.$name) {
            throw "Lifecycle count mismatch for $name."
        }
    }
    $result = "segment-a-lifecycle-passed-settings-live-deferred-by-auth-boundary"
} catch {
    $failure = $_.Exception.Message
    $result = "failed-frozen-no-retry"
    try { Stop-OwnedApp } catch {}
    if ($freshInstalled -and (Test-Path $uninstaller) -and $counters.uninstallerInvocations -eq 0) {
        try { $counters.uninstallerInvocations++; Invoke-ProcessOnce $uninstaller @("/S") "rollback-uninstall" } catch {}
    }
    if ($counters.ownedCleanupInvocations -eq 0) { try { $counters.ownedCleanupInvocations++; Remove-OwnedResidue } catch {} }
} finally {
    if (-not (Test-Path $outputPath)) { New-Item -ItemType Directory -Path $outputPath -Force | Out-Null }
    [ordered]@{
        schemaVersion = 1
        kind = "dronedream-field-disposable-user-lifecycle-receipt"
        result = $result
        productSourceCommit = $contract.productSource.commit
        provider = [ordered]@{ user = $env:USERNAME; sid = $actualUser.User.Value; profile = $actualProfile }
        artifact = [ordered]@{ path = $installerPath; bytes = $installer.bytes; sha256 = $installer.sha256 }
        applicationSha256 = $applicationHash
        planSha256 = $planHash
        counters = $counters
        events = @($events)
        protectedBefore = $protectedBefore
        protectedAfter = if ($null -ne $protectedBefore) { Get-ProtectedState } else { $null }
        liveSettings = [ordered]@{
            executed = $false
            reason = "The exact production Field app requires a real Field OAuth session before FieldApp mounts; OAuth/account/token actions are forbidden in this segment."
            staticEvidenceBound = $true
        }
        failure = $failure
        releaseReady = $false
    } | ConvertTo-Json -Depth 30 | Set-Content (Join-Path $outputPath "lifecycle-receipt.json") -Encoding UTF8
}

if ($result -eq "failed-frozen-no-retry") { exit 1 }
