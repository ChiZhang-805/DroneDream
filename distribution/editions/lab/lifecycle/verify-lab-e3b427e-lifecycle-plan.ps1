[CmdletBinding()]
param(
    [string]$Plan,
    [string]$Installer,
    [string]$TargetReceipt,
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedPlanSha256,
    [switch]$SnapshotOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-TextSha256 {
    param([string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString(
            $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))
        ).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-PathRecord {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) {
        return [ordered]@{
            path = $Path
            exists = $false
            type = $null
            length = $null
            lastWriteUtc = $null
        }
    }
    return [ordered]@{
        path = $Path
        exists = $true
        type = if ($item.PSIsContainer) { "directory" } else { "file" }
        length = if ($item.PSIsContainer) { $null } else { [long]$item.Length }
        lastWriteUtc = $item.LastWriteTimeUtc.ToString("O")
    }
}

function Get-RegistryFingerprint {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{
            path = $Path
            exists = $false
            valueCount = 0
            sha256 = $null
        }
    }
    $key = Get-Item -LiteralPath $Path
    $records = @()
    foreach ($name in @($key.GetValueNames() | Sort-Object)) {
        $value = $key.GetValue(
            $name,
            $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        $records += [ordered]@{
            name = $name
            kind = [string]$key.GetValueKind($name)
            value = if ($value -is [array]) { @($value) } else { $value }
        }
    }
    $canonical = $records | ConvertTo-Json -Depth 8 -Compress
    return [ordered]@{
        path = $Path
        exists = $true
        valueCount = $records.Count
        sha256 = Get-TextSha256 $canonical
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
        return [ordered]@{
            registryPath = $key
            version = [string]$properties.pv
            locationPresent = -not [string]::IsNullOrWhiteSpace(
                [string]$properties.location
            )
        }
    }
    return $null
}

function Get-ObservedState {
    $local = $env:LOCALAPPDATA
    $roaming = $env:APPDATA
    $desktop = [Environment]::GetFolderPath("Desktop")
    $programs = [Environment]::GetFolderPath("Programs")
    $labPaths = @(
        (Join-Path $local "DroneDream-Lab"),
        (Join-Path $roaming "io.dronedream.desktop.lab"),
        (Join-Path $local "io.dronedream.desktop.lab"),
        (Join-Path $desktop "DroneDream $([char]0x00B7) LAB.lnk"),
        (Join-Path $programs "DroneDream $([char]0x00B7) LAB.lnk")
    )
    $labKeys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Lab",
        "HKCU:\Software\DroneDream\DroneDream-Lab"
    )
    $protectedPaths = @()
    $protectedKeys = @()
    foreach ($edition in @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Field")) {
        $protectedPaths += Get-PathRecord (Join-Path $local $edition)
        $protectedKeys += Get-RegistryFingerprint (
            "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$edition"
        )
        $protectedKeys += Get-RegistryFingerprint (
            "HKCU:\Software\DroneDream\$edition"
        )
    }
    $protectedPaths += Get-PathRecord "C:\DroneDream"
    $protectedPaths += Get-PathRecord "Z:\DroneDream"
    foreach ($name in @(
        "DroneDream.lnk",
        "DroneDream $([char]0x00B7) SIM.lnk",
        "DroneDream $([char]0x00B7) FIELD.lnk"
    )) {
        $protectedPaths += Get-PathRecord (Join-Path $desktop $name)
        $protectedPaths += Get-PathRecord (Join-Path $programs $name)
    }
    return [ordered]@{
        labOwnedFreshPaths = @($labPaths | ForEach-Object { Get-PathRecord $_ })
        labOwnedFreshKeys = @($labKeys | ForEach-Object { Get-RegistryFingerprint $_ })
        protectedPaths = $protectedPaths
        protectedRegistryKeys = $protectedKeys
        webView2 = Get-WebView2Record
        droneDreamProcessCount = @(
            Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue
        ).Count
        oauthPort49212ListenerCount = @(
            Get-NetTCPConnection -LocalPort 49212 -State Listen -ErrorAction SilentlyContinue
        ).Count
    }
}

$observed = Get-ObservedState
$observedCanonical = $observed | ConvertTo-Json -Depth 16 -Compress
$observedHash = Get-TextSha256 $observedCanonical
if ($SnapshotOnly) {
    [ordered]@{
        schemaVersion = 1
        kind = "dronedream-lab-lifecycle-read-only-snapshot"
        observedState = $observed
        observedStateSha256 = $observedHash
        sideEffects = [ordered]@{
            installerRun = $false
            applicationLaunched = $false
            runtimeStarted = $false
            browserLaunched = $false
            providerCalled = $false
            registryOrFilesystemMutation = $false
        }
    } | ConvertTo-Json -Depth 18
    exit 0
}

foreach ($required in @($Plan, $Installer, $TargetReceipt, $ExpectedPlanSha256)) {
    if ([string]::IsNullOrWhiteSpace($required)) {
        throw "Plan verification requires exact plan, installer, target receipt, and plan SHA-256."
    }
}
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$targetReceiptPath = (Resolve-Path -LiteralPath $TargetReceipt).Path
if ((Get-FileSha256 $planPath) -cne $ExpectedPlanSha256) {
    throw "The lifecycle plan SHA-256 does not match."
}
$contract = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
$target = Get-Content -LiteralPath $targetReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($contract.state -cne "green-plan-frozen-no-execute" -or
    $contract.authorization.executionAuthorized -ne $false -or
    $target.state -cne "target-only-no-execution-evidence") {
    throw "The lifecycle plan or target receipt is not in its NO-EXECUTE state."
}
if ((Get-Item -LiteralPath $installerPath).Length -ne $contract.artifact.bytes -or
    (Get-FileSha256 $installerPath) -cne $contract.artifact.sha256) {
    throw "The exact Lab lifecycle artifact identity does not match."
}
if ((Get-FileSha256 $targetReceiptPath) -cne $contract.targetReceipt.sha256) {
    throw "The lifecycle target receipt contract hash does not match."
}
if ($observedHash -cne $contract.protectedState.observedStateSha256) {
    throw "Protected state drifted after plan freeze."
}
if (@($observed.labOwnedFreshPaths | Where-Object { $_.exists }).Count -ne 0 -or
    @($observed.labOwnedFreshKeys | Where-Object { $_.exists }).Count -ne 0) {
    throw "The Lab owned namespace is not fresh."
}
if ($null -eq $observed.webView2 -or -not $observed.webView2.version -or
    $observed.droneDreamProcessCount -ne 0 -or
    $observed.oauthPort49212ListenerCount -ne 0) {
    throw "The app-only lifecycle provider preconditions are unavailable."
}
$ownedBase = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream-Codex\Lab-RED")
).TrimEnd("\")
$runRoot = [IO.Path]::GetFullPath($contract.ownedIsolation.runRoot).TrimEnd("\")
if (-not ($runRoot + "\").StartsWith(
    $ownedBase + "\",
    [StringComparison]::OrdinalIgnoreCase
) -or (Test-Path -LiteralPath $runRoot)) {
    throw "The planned RED run root is not a fresh owned child."
}

[ordered]@{
    schemaVersion = 1
    kind = "dronedream-lab-lifecycle-plan-readiness"
    planPath = $planPath
    planSha256 = $ExpectedPlanSha256
    artifactSha256 = Get-FileSha256 $installerPath
    targetReceiptSha256 = Get-FileSha256 $targetReceiptPath
    observedStateSha256 = $observedHash
    planReady = $true
    readyForExactRedRequest = [bool]$contract.redReadiness.exactRedRequestable
    requestBlockers = @($contract.redReadiness.blockers)
    executionAuthorized = $false
    executionPerformed = $false
    sideEffects = [ordered]@{
        installerRun = $false
        applicationLaunched = $false
        runtimeStarted = $false
        browserLaunched = $false
        providerCalled = $false
        registryOrFilesystemMutation = $false
    }
} | ConvertTo-Json -Depth 8
