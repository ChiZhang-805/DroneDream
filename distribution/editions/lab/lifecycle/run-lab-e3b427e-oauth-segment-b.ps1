[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$ExpectedInstallerSha256,
    [Parameter(Mandatory = $true)][long]$ExpectedInstallerBytes,
    [Parameter(Mandatory = $true)][string]$Application,
    [Parameter(Mandatory = $true)][string]$ExpectedApplicationSha256,
    [Parameter(Mandatory = $true)][string]$Plan,
    [Parameter(Mandatory = $true)][string]$ExpectedPlanSha256,
    [Parameter(Mandatory = $true)][ValidateSet("RuntimePrerequisite", "OAuthTransaction")][string]$Phase,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$RuntimePrerequisiteReceipt,
    [string]$ExpectedRuntimePrerequisiteReceiptSha256,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$productSource = "e3b427e9d1d6209495d629c399a1962913f2d00c"
$artifactSha256 = "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
$displayName = "DroneDream $([char]0x00B7) LAB"
$productName = "DroneDream-Lab"
$bundleId = "io.dronedream.desktop.lab"
$mainBinaryName = "drone-dream-desktop.exe"
$installRoot = Join-Path $env:LOCALAPPDATA $productName
$appBinary = Join-Path $installRoot $mainBinaryName
$uninstaller = Join-Path $installRoot "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$roamingAppData = Join-Path $env:APPDATA $bundleId
$localAppData = Join-Path $env:LOCALAPPDATA $bundleId
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$displayName.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$displayName.lnk"
$inspector = Join-Path $PSScriptRoot "inspect-lab-e3b427e-oauth-segment-b.mjs"

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-ExactFile([string]$Path, [string]$ExpectedSha256, [string]$Label) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "$Label is not a file." }
    if ((Get-Sha256 $resolved) -cne $ExpectedSha256) { throw "$Label SHA-256 mismatch." }
    return $resolved
}

function Get-RegistryRecord([string]$Path) {
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

function Get-PathRecord([string]$Path) {
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    return [ordered]@{
        path = $Path
        exists = ($null -ne $item)
        length = if ($null -ne $item -and -not $item.PSIsContainer) { [long]$item.Length } else { $null }
        lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
    }
}

function Get-ShortcutRecord([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; exists = $false; target = $null }
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        return [ordered]@{ path = $Path; exists = $true; target = $shortcut.TargetPath }
    } finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}

function Get-ProtectedState {
    $names = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Field")
    $shortcutNames = @("DroneDream", "DroneDream $([char]0x00B7) SIM", "DroneDream $([char]0x00B7) FIELD")
    return [ordered]@{
        roots = @($names | ForEach-Object { Get-PathRecord (Join-Path $env:LOCALAPPDATA $_) })
        uninstallKeys = @($names | ForEach-Object { Get-RegistryRecord "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$_" })
        productKeys = @($names | ForEach-Object { Get-RegistryRecord "HKCU:\Software\DroneDream\$_" })
        shortcuts = @($shortcutNames | ForEach-Object {
            Get-ShortcutRecord (Join-Path ([Environment]::GetFolderPath("Desktop")) "$_.lnk")
            Get-ShortcutRecord (Join-Path ([Environment]::GetFolderPath("Programs")) "$_.lnk")
        })
        runtimeRoots = @((Get-PathRecord "C:\DroneDream"), (Get-PathRecord "Z:\DroneDream"))
        webView2 = Get-RegistryRecord "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    }
}

function Get-StableJson([object]$Value) {
    return $Value | ConvertTo-Json -Depth 20 -Compress
}

function Assert-ProtectedParity([object]$Before, [string]$Stage) {
    if ((Get-StableJson $Before) -cne (Get-StableJson (Get-ProtectedState))) {
        throw "Protected other-Edition, Runtime, or WebView2 state changed during $Stage."
    }
}

function Assert-PortFree {
    if (@(Get-NetTCPConnection -LocalPort 49212 -State Listen -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "Lab callback port 49212 is already listening."
    }
}

function Assert-NoDesktopProcess {
    if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
        throw "A DroneDream desktop process is already running."
    }
}

function Assert-LabAbsent {
    foreach ($path in @($installRoot, $roamingAppData, $localAppData, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Lab owned path exists: $path" }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Lab owned registry key exists: $key" }
    }
}

function Assert-LabInstalled {
    foreach ($path in @($appBinary, $uninstaller, $desktopShortcut, $startMenuShortcut)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Lab install is incomplete: $path" }
    }
    $registration = Get-RegistryRecord $uninstallKey
    if (-not $registration.exists -or $registration.values.DisplayName -cne $displayName -or
        $registration.values.DisplayVersion -cne "1.0.0" -or
        $registration.values.MainBinaryName -cne $mainBinaryName -or
        $registration.values.InstallLocation.Trim('"') -cne $installRoot) {
        throw "Lab uninstall registration is invalid."
    }
    foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
        if ((Get-ShortcutRecord $shortcutPath).target -cne $appBinary) {
            throw "Lab shortcut target mismatch: $shortcutPath"
        }
    }
}

function Invoke-ProcessOnce([string]$Executable, [string[]]$Arguments, [string]$Stage) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) { throw "$Stage exited with code $($process.ExitCode)." }
    } finally {
        $process.Dispose()
    }
}

function Get-FreeLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port } finally { $listener.Stop() }
}

function Stop-OwnedApp([Diagnostics.Process]$Process) {
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            $Process.CloseMainWindow() | Out-Null
            if (-not $Process.WaitForExit(5000)) {
                Stop-Process -Id $Process.Id -Force
                $Process.WaitForExit(5000) | Out-Null
            }
        }
    } finally {
        $Process.Dispose()
    }
    Start-Sleep -Seconds 2
    Assert-NoDesktopProcess
}

function Invoke-Inspector([string]$InspectorPhase, [string]$ReceiptPath) {
    $port = Get-FreeLoopbackPort
    $previous = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
    $process = $null
    try {
        $process = Start-Process -FilePath $appBinary -PassThru
        $endpoint = "http://127.0.0.1:$port"
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            try {
                Invoke-WebRequest -Uri "$endpoint/json/version" -UseBasicParsing -TimeoutSec 2 | Out-Null
                break
            } catch {
                if ($process.HasExited) { throw "Lab exited before WebView2 inspection." }
                Start-Sleep -Milliseconds 300
            }
        } while ([DateTime]::UtcNow -lt $deadline)
        if ([DateTime]::UtcNow -ge $deadline) { throw "Timed out waiting for Lab WebView2." }
        & node.exe $inspector $endpoint $InspectorPhase $ReceiptPath
        if ($LASTEXITCODE -ne 0) { throw "$InspectorPhase failed closed." }
        $inspection = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $inspection.passed -or $inspection.editionId -cne "lab") {
            throw "$InspectorPhase receipt was not accepted."
        }
        return $inspection
    } finally {
        try { Stop-OwnedApp $process } finally { $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $previous }
    }
}

function Remove-OwnedPreferenceKey {
    if (-not (Test-Path -LiteralPath $productKey)) { return }
    $record = Get-RegistryRecord $productKey
    $expectedNames = @("(default)", "DroneDreamRuntimeDrive", "DroneDreamRuntimeInstallMode", "DroneDreamRuntimeOperationProtocol")
    $actualNames = @($record.values.Keys | Sort-Object)
    if (($actualNames -join "`n") -cne (($expectedNames | Sort-Object) -join "`n")) {
        throw "Lab preference key contains unexpected values."
    }
    if ([string]$record.values."(default)" -cne $installRoot -or
        [string]$record.values.DroneDreamRuntimeDrive -cne "" -or
        [string]$record.values.DroneDreamRuntimeInstallMode -cne "install-app-only" -or
        [int]$record.values.DroneDreamRuntimeOperationProtocol -ne 2) {
        throw "Lab preference values are not exact."
    }
    Remove-Item -LiteralPath $productKey -Force
}

function Invoke-OwnedRollback([bool]$TryVaultCleanup, [string]$EvidenceRoot) {
    if ($TryVaultCleanup -and (Test-Path -LiteralPath $appBinary -PathType Leaf)) {
        try { Invoke-Inspector "vault-cleanup" (Join-Path $EvidenceRoot "failure-vault-cleanup.json") | Out-Null } catch {}
    }
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        Invoke-ProcessOnce $uninstaller @("/S") "rollback-uninstall"
    }
    Remove-OwnedPreferenceKey
}

$installerPath = Resolve-ExactFile $Installer $ExpectedInstallerSha256 "installer"
if ((Get-Item -LiteralPath $installerPath).Length -ne $ExpectedInstallerBytes -or
    $ExpectedInstallerBytes -ne 12081900 -or $ExpectedInstallerSha256 -cne $artifactSha256) {
    throw "The exact Lab artifact binding drifted."
}
$applicationPath = Resolve-ExactFile $Application $ExpectedApplicationSha256 "application"
$planPath = Resolve-ExactFile $Plan $ExpectedPlanSha256 "plan"
$applicationContract = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$planContract = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($applicationContract.productSourceCommit -cne $productSource -or
    $planContract.productSourceCommit -cne $productSource -or
    $applicationContract.publicOAuth.clientId -cne "0b9e7a8d-2c90-4b76-8842-511363f555bd" -or
    $applicationContract.publicOAuth.redirectUri -cne "http://127.0.0.1:49212/desktop-auth/lab/callback") {
    throw "The Lab product or public OAuth identity binding drifted."
}

$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$allowedBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream-Codex\Lab-RED")).TrimEnd("\")
if (-not ($outputPath + "\").StartsWith($allowedBase + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot escaped the Lab RED owned base."
}
$expectedRoot = if ($Phase -ceq "RuntimePrerequisite") { $planContract.ownedRoots.b0 } else { $planContract.ownedRoots.b1 }
if ([IO.Path]::GetFullPath($expectedRoot).TrimEnd("\") -cne $outputPath) {
    throw "OutputRoot does not match the exact phase-owned root."
}
if (Test-Path -LiteralPath $outputPath) { throw "OutputRoot must not exist before this invocation." }
Assert-PortFree
Assert-NoDesktopProcess

if ($Phase -ceq "RuntimePrerequisite") {
    Assert-LabAbsent
} else {
    Assert-LabInstalled
    if (-not $RuntimePrerequisiteReceipt -or -not $ExpectedRuntimePrerequisiteReceiptSha256) {
        throw "B1 requires an exact accepted B0 receipt path and SHA-256."
    }
    $b0Path = Resolve-ExactFile $RuntimePrerequisiteReceipt $ExpectedRuntimePrerequisiteReceiptSha256 "B0 receipt"
    $b0 = Get-Content -LiteralPath $b0Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($b0.result -cne "runtime-prerequisite-passed" -or $b0.productSourceCommit -cne $productSource -or
        $b0.artifactSha256 -cne $artifactSha256 -or -not $b0.labInstallRetainedForB1) {
        throw "The B0 receipt is not eligible for B1."
    }
}

if (-not $Execute) {
    [ordered]@{
        result = "green-plan-only-preflight-passed-no-execute"
        phase = $Phase
        productSourceCommit = $productSource
        artifactSha256 = $artifactSha256
        outputRootAbsent = $true
        listener49212Count = 0
        installerApplicationBrowserOAuthProviderRuntimeInvocations = 0
    } | ConvertTo-Json -Depth 5
    exit 0
}

if ((git status --porcelain).Count -ne 0) { throw "RED execution requires a clean worktree." }
New-Item -ItemType Directory -Path $outputPath | Out-Null
$protectedBefore = Get-ProtectedState
$result = "failed-no-retry"
$failureCode = $null
try {
    if ($Phase -ceq "RuntimePrerequisite") {
        Invoke-ProcessOnce $installerPath @("/S") "b0-fresh-install"
        Assert-LabInstalled
        Assert-ProtectedParity $protectedBefore "b0-install"
        $inspection = Invoke-Inspector "runtime-prerequisite" (Join-Path $outputPath "runtime-prerequisite-inspection.json")
        Assert-ProtectedParity $protectedBefore "b0-runtime-readiness-inspection"
        $result = "runtime-prerequisite-passed"
        $receipt = [ordered]@{
            schemaVersion = 1
            kind = "dronedream-lab-oauth-b0-runtime-prerequisite-receipt"
            result = $result
            productSourceCommit = $productSource
            artifactSha256 = $artifactSha256
            applicationSha256 = $ExpectedApplicationSha256
            planSha256 = $ExpectedPlanSha256
            runtimeReadinessPercent = $inspection.runtimeReadinessPercent
            explicitLoginActionEnabled = $inspection.explicitLoginActionEnabled
            browserOauthProviderAccountTokenRuntimeMutationCounts = 0
            protectedStateParity = $true
            labInstallRetainedForB1 = $true
            automaticRetryCount = 0
            b1Authorized = $false
        }
    } else {
        $inspection = Invoke-Inspector "oauth-transaction" (Join-Path $outputPath "oauth-transaction-inspection.json")
        Assert-ProtectedParity $protectedBefore "b1-oauth-transaction"
        Invoke-ProcessOnce $uninstaller @("/S") "b1-uninstall"
        Remove-OwnedPreferenceKey
        Assert-LabAbsent
        Assert-ProtectedParity $protectedBefore "b1-cleanup"
        Assert-PortFree
        $result = "oauth-transaction-passed-and-local-session-cleared"
        $receipt = [ordered]@{
            schemaVersion = 1
            kind = "dronedream-lab-oauth-b1-transaction-receipt"
            result = $result
            productSourceCommit = $productSource
            artifactSha256 = $artifactSha256
            applicationSha256 = $ExpectedApplicationSha256
            planSha256 = $ExpectedPlanSha256
            b0ReceiptSha256 = $ExpectedRuntimePrerequisiteReceiptSha256
            explicitLoginGestures = $inspection.explicitLoginGestures
            browserLaunchMaximum = $inspection.browserLaunchMaximum
            oauthTransactionMaximum = $inspection.oauthTransactionMaximum
            accountIdentityPersisted = $false
            localLogoutCompleted = $inspection.localLogoutCompleted
            rawSensitiveEvidencePersisted = $false
            protectedStateParity = $true
            labOwnedStateAbsent = $true
            automaticRetryCount = 0
        }
    }
    $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $outputPath "lab-oauth-segment-b-receipt.json") -Encoding UTF8
} catch {
    $failureCode = if ($Phase -ceq "RuntimePrerequisite") { "b0-failed" } else { "b1-failed" }
    try { Invoke-OwnedRollback ($Phase -ceq "OAuthTransaction") $outputPath } catch {}
    $failureReceipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-lab-oauth-segment-b-failure-receipt"
        result = "failed-no-retry"
        phase = $Phase
        failureCode = $failureCode
        rawErrorOrSensitiveValuePersisted = $false
        automaticRetryCount = 0
        sameCommandMayBeRunAgain = $false
    }
    $failureReceipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputPath "lab-oauth-segment-b-receipt.json") -Encoding UTF8
    throw "Lab OAuth Segment B $Phase failed closed; evidence was frozen and rollback was attempted."
}
