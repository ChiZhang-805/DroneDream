param(
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
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedEvidenceHead,
    [switch]$PlanOnly,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
if ($PlanOnly -eq $Execute) {
    throw "Select exactly one of -PlanOnly or -Execute."
}

$productSource = "560f574a95c8b51bbf34711bfd092d77fd3e166e"
$productTree = "0e4535535b7ee339faeaa704069a46bcfe1c350d"
$productName = "DroneDream-Field"
$displayName = "DroneDream $([char]0x00B7) FIELD"
$bundleId = "io.dronedream.desktop.field"
$mainBinaryName = "drone-dream-desktop.exe"
$installRoot = Join-Path $env:LOCALAPPDATA $productName
$appBinary = Join-Path $installRoot $mainBinaryName
$uninstaller = Join-Path $installRoot "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$sharedProductParent = "HKCU:\Software\DroneDream"
$roamingAppData = Join-Path $env:APPDATA $bundleId
$localAppData = Join-Path $env:LOCALAPPDATA $bundleId
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$displayName.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$displayName.lnk"
$allowedOutputBase = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream-Codex\Field-Owned-Isolation")
).TrimEnd("\")

function Get-LfSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false)).Replace("`r`n", "`n")
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function ConvertTo-StableJson {
    param([Parameter(Mandatory = $true)][object]$Value)
    return $Value | ConvertTo-Json -Depth 30 -Compress
}

function Get-ObjectSha256 {
    param([Parameter(Mandatory = $true)][object]$Value)
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-StableJson $Value))
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $hash.Dispose() }
}

$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$planPath = (Resolve-Path -LiteralPath $Plan).Path
$applicationSha256 = (Get-FileHash -LiteralPath $applicationPath -Algorithm SHA256).Hash.ToLowerInvariant()
$planSha256 = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($applicationSha256 -cne $ExpectedApplicationSha256) { throw "Application SHA-256 mismatch." }
if ($planSha256 -cne $ExpectedPlanSha256) { throw "Plan SHA-256 mismatch." }
$applicationContract = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$planContract = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ($applicationContract.kind -cne "dronedream-field-owned-isolation-lifecycle-application" -or
    $applicationContract.status -cne "prepared-awaiting-exact-red-start-signal" -or
    $applicationContract.source.productCommit -cne $productSource -or
    $applicationContract.source.productTree -cne $productTree -or
    $applicationContract.execution.currentMessageAuthorizesExecution -ne $false -or
    $applicationContract.execution.lifecycleCountMaximum -ne 1 -or
    $applicationContract.execution.retryCountMaximum -ne 0 -or
    $applicationContract.plan.fileSha256 -cne $planSha256) {
    throw "Application contract binding or authorization drifted."
}
if ($planContract.kind -cne "dronedream-field-owned-isolation-lifecycle-plan" -or
    $planContract.source.productCommit -cne $productSource -or
    $planContract.artifact.sha256 -cne $applicationContract.artifact.sha256 -or
    $planContract.ownedPaths.runRoot -cne $applicationContract.ownedPaths.runRoot) {
    throw "Plan and application are not bound to the same lifecycle."
}

$toolRoot = Split-Path -Parent $applicationPath
foreach ($binding in $applicationContract.toolBindings) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $toolRoot $binding.relativeToLifecycleDirectory))
    if (-not ($candidate + "\").StartsWith($toolRoot.TrimEnd("\") + "\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Tool binding escaped the Field lifecycle directory."
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Bound lifecycle tool is missing." }
    if ((Get-LfSha256 -Path $candidate) -cne $binding.lfNormalizedSha256) {
        throw "Bound lifecycle tool content drifted: $($binding.path)"
    }
}

$head = (git rev-parse HEAD).Trim()
$upstream = (git rev-parse origin/codex/software-field).Trim()
if ($head -cne $ExpectedEvidenceHead -or $upstream -cne $ExpectedEvidenceHead) {
    throw "Evidence HEAD/upstream does not match the exact start binding."
}
$status = @(git status --porcelain --untracked-files=all)
if ($status.Count -ne 0) { throw "Evidence worktree must be clean." }

if ($PlanOnly) {
    [ordered]@{
        schemaVersion = 1
        decision = "pass-plan-only-no-host-lifecycle-read-or-write"
        productSource = $productSource
        evidenceHead = $head
        applicationSha256 = $applicationSha256
        planSha256 = $planSha256
        lifecycleAttemptsConsumed = 0
        artifactRead = $false
        registryRead = $false
        processRead = $false
        outputRootCreated = $false
        installerStarted = $false
        applicationStarted = $false
        webView2Attached = $false
    } | ConvertTo-Json -Depth 10
    exit 0
}

$installerPath = $applicationContract.artifact.path
$auditReceiptPath = $applicationContract.staticAudit.receiptPath
$outputPath = [IO.Path]::GetFullPath($applicationContract.ownedPaths.runRoot).TrimEnd("\")
if (-not ($outputPath + "\").StartsWith($allowedOutputBase + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Lifecycle run root escaped the exact Field-owned base."
}
if (Test-Path -LiteralPath $outputPath) { throw "Lifecycle run root already exists; no retry is allowed." }
foreach ($binding in @(
    [ordered]@{ path = $installerPath; bytes = $applicationContract.artifact.bytes; sha256 = $applicationContract.artifact.sha256 },
    [ordered]@{ path = $auditReceiptPath; bytes = $applicationContract.staticAudit.receiptBytes; sha256 = $applicationContract.staticAudit.receiptSha256 }
)) {
    $item = Get-Item -LiteralPath $binding.path
    $sha = (Get-FileHash -LiteralPath $binding.path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($item.Length -ne $binding.bytes -or $sha -cne $binding.sha256) {
        throw "Frozen artifact or audit receipt identity mismatch."
    }
}

function Get-RegistryRecord {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [ordered]@{ path = $Path; exists = $false; values = @{} } }
    $properties = Get-ItemProperty -LiteralPath $Path
    $values = [ordered]@{}
    foreach ($property in $properties.PSObject.Properties | Sort-Object Name) {
        if ($property.Name -notmatch '^PS') { $values[$property.Name] = [string]$property.Value }
    }
    return [ordered]@{ path = $Path; exists = $true; values = $values }
}

function Get-PathRecord {
    param([Parameter(Mandatory = $true)][string]$Path)
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    if ($null -eq $item) { return [ordered]@{ path = $Path; exists = $false } }
    $record = [ordered]@{ path = $Path; exists = $true; directory = [bool]$item.PSIsContainer; lastWriteUtc = $item.LastWriteTimeUtc.ToString("O") }
    if (-not $item.PSIsContainer) {
        $record.bytes = [long]$item.Length
        $record.sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $record
}

function Get-ProtectedState {
    $otherProducts = @("DroneDream", "DroneDream-Universal", "DroneDream-Sim", "DroneDream-Lab")
    return [ordered]@{
        installRoots = @($otherProducts | ForEach-Object { Get-PathRecord (Join-Path $env:LOCALAPPDATA $_) })
        uninstallKeys = @($otherProducts | ForEach-Object { Get-RegistryRecord "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$_" })
        preferenceKeys = @($otherProducts | ForEach-Object { Get-RegistryRecord "HKCU:\Software\DroneDream\$_" })
        desktopShortcuts = @($otherProducts | ForEach-Object {
            $name = if ($_ -eq "DroneDream") { "DroneDream.lnk" } else { "$($_.Replace('DroneDream-', 'DroneDream ' + [char]0x00B7 + ' ')).lnk" }
            Get-PathRecord (Join-Path ([Environment]::GetFolderPath("Desktop")) $name)
        })
        startMenuShortcuts = @($otherProducts | ForEach-Object {
            $name = if ($_ -eq "DroneDream") { "DroneDream.lnk" } else { "$($_.Replace('DroneDream-', 'DroneDream ' + [char]0x00B7 + ' ')).lnk" }
            Get-PathRecord (Join-Path ([Environment]::GetFolderPath("Programs")) $name)
        })
        runtimeRoots = @(Get-PathRecord "C:\DroneDream"; Get-PathRecord "Z:\DroneDream")
        sharedProductParentExists = Test-Path -LiteralPath $sharedProductParent
        webView2 = @(
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        ) | ForEach-Object { Get-RegistryRecord $_ }
    }
}

function Assert-FreshFieldState {
    foreach ($path in @($installRoot, $roamingAppData, $localAppData, $desktopShortcut, $startMenuShortcut)) {
        if (Test-Path -LiteralPath $path) { throw "Fresh Field path already exists: $path" }
    }
    foreach ($key in @($uninstallKey, $productKey)) {
        if (Test-Path -LiteralPath $key) { throw "Fresh Field registry key already exists: $key" }
    }
}

function Assert-InstalledFieldIdentity {
    foreach ($path in @($appBinary, $uninstaller, $desktopShortcut, $startMenuShortcut)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Installed Field identity missing: $path" }
    }
    $registration = Get-RegistryRecord $uninstallKey
    if (-not $registration.exists -or $registration.values.DisplayName -cne $displayName -or
        $registration.values.DisplayVersion -cne "1.0.0" -or
        $registration.values.InstallLocation.Trim('"') -cne $installRoot -or
        $registration.values.MainBinaryName -cne $mainBinaryName) {
        throw "Field uninstall registration drifted."
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        foreach ($path in @($desktopShortcut, $startMenuShortcut)) {
            if ($shell.CreateShortcut($path).TargetPath -cne $appBinary) { throw "Field shortcut target drifted." }
        }
    } finally { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
}

function Invoke-ProcessOnce {
    param([string]$Executable, [string[]]$Arguments, [string]$Stage)
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try { if ($process.ExitCode -ne 0) { throw "$Stage exited with code $($process.ExitCode)." } }
    finally { $process.Dispose() }
}

function Get-FreeLoopbackPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    try { return ([Net.IPEndPoint]$listener.LocalEndpoint).Port } finally { $listener.Stop() }
}

$appProcess = $null
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
    } finally { $script:appProcess.Dispose(); $script:appProcess = $null }
}

function Invoke-LiveInspection {
    param([string]$Phase, [string]$LaunchPath, [bool]$ShortcutLaunch)
    $port = Get-FreeLoopbackPort
    $prior = $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=$port"
    try {
        $script:appProcess = Start-Process -FilePath $LaunchPath -PassThru
        $script:counters.applicationLaunches++
        if ($ShortcutLaunch) { $script:counters.shortcutLaunches++ }
        $endpoint = "http://127.0.0.1:$port"
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            try { Invoke-WebRequest -Uri "$endpoint/json/version" -UseBasicParsing -TimeoutSec 2 | Out-Null; break }
            catch { if ($script:appProcess.HasExited) { throw "Field exited before WebView2 inspection." }; Start-Sleep -Milliseconds 300 }
        } while ([DateTime]::UtcNow -lt $deadline)
        if ([DateTime]::UtcNow -ge $deadline) { throw "Timed out waiting for Field WebView2." }
        $resultPath = Join-Path $outputPath "$Phase-webview2.json"
        $stdout = Join-Path $outputPath "$Phase-webview2.stdout.log"
        $stderr = Join-Path $outputPath "$Phase-webview2.stderr.log"
        $inspector = Join-Path $PSScriptRoot "inspect-field-owned-webview2.mjs"
        $node = Start-Process -FilePath "node.exe" -ArgumentList @($inspector, $endpoint, $Phase, $resultPath) -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -Wait -WindowStyle Hidden
        try { if ($node.ExitCode -ne 0) { throw "$Phase WebView2 inspection failed." } } finally { $node.Dispose() }
        $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $result.passed -or $result.forbiddenRequestCount -ne 0) { throw "$Phase WebView2 contract failed." }
        $script:counters.liveWebView2Inspections++
        $script:counters.settingsViewportInspections += $result.settingsInspections.Count
        $script:counters.languageTransitions += $result.languageTransitionCount
    } finally {
        if ($null -eq $prior) { Remove-Item Env:\WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue } else { $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = $prior }
        Stop-OwnedFieldProcess
    }
}

function Assert-AndRemoveOwnedPreferenceKey {
    if ($script:ownedPreferenceCleanupAttempted) { throw "Field preference cleanup is limited to one attempt." }
    $script:ownedPreferenceCleanupAttempted = $true
    $script:counters.ownedPreferenceCleanupAttempts++
    $record = Get-RegistryRecord $productKey
    $expected = [ordered]@{
        "(default)" = $installRoot
        DroneDreamRuntimeDrive = ""
        DroneDreamRuntimeInstallMode = "install-app-only"
        DroneDreamRuntimeOperationProtocol = "2"
    }
    if (-not $record.exists -or (ConvertTo-StableJson $record.values) -cne (ConvertTo-StableJson $expected)) {
        throw "Field preference key does not contain the four exact allowed values."
    }
    Remove-Item -LiteralPath $productKey -Recurse -Force
    if (Test-Path -LiteralPath $productKey -or -not (Test-Path -LiteralPath $sharedProductParent)) {
        throw "Exact Field preference cleanup failed or touched the shared parent."
    }
    $script:counters.ownedPreferenceCleanupInvocations++
}

function Remove-OwnedFieldAppData {
    $profileRoot = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd("\") + "\"
    foreach ($path in @($roamingAppData, $localAppData)) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $path).Path).TrimEnd("\")
        $expected = [IO.Path]::GetFullPath($path).TrimEnd("\")
        if ($resolved -cne $expected -or -not ($resolved + "\").StartsWith($profileRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Field app-data cleanup escaped its exact owned namespace."
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

$counters = [ordered]@{
    visibleInstallerLanguageProbes = 0
    freshInstallerInvocations = 0
    overlayInstallerInvocations = 0
    applicationLaunches = 0
    shortcutLaunches = 0
    liveWebView2Inspections = 0
    settingsViewportInspections = 0
    languageTransitions = 0
    uninstallerInvocations = 0
    ownedPreferenceCleanupAttempts = 0
    ownedPreferenceCleanupInvocations = 0
    browserLaunches = 0
    oauthTransactions = 0
    accountOrTokenReads = 0
    artifactBuildsOrSigning = 0
    runtimeStartsOrMigrations = 0
    simulatorStarts = 0
    deviceOrHardwareActions = 0
}
$freshInstalled = $false
$ownedPreferenceCleanupAttempted = $false
$protectedBefore = $null
$protectedAfter = $null
$failure = $null
$result = "not-started"
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
try {
    Assert-FreshFieldState
    if (@(Get-Process -Name $mainBinaryName.Replace(".exe", "") -ErrorAction SilentlyContinue).Count -ne 0) { throw "A DroneDream desktop process is already running." }
    if (@(Get-NetTCPConnection -LocalPort 49213 -State Listen -ErrorAction SilentlyContinue).Count -ne 0) { throw "Field OAuth callback port is in use." }
    $protectedBefore = Get-ProtectedState
    $protectedBeforeSha256 = Get-ObjectSha256 $protectedBefore

    New-Item -ItemType Directory -Path $outputPath | Out-Null
    $tempPath = Join-Path $outputPath "temp"
    New-Item -ItemType Directory -Path $tempPath | Out-Null
    $env:TEMP = $tempPath
    $env:TMP = $tempPath

    $languageInspector = Join-Path $PSScriptRoot "inspect-field-owned-installer-language.ps1"
    foreach ($probe in @(
        [ordered]@{ id = "1033"; locale = "en" },
        [ordered]@{ id = "2052"; locale = "zh-CN" }
    )) {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $languageInspector -Installer $installerPath -ExpectedInstallerSha256 $applicationContract.artifact.sha256 -LanguageId $probe.id -ExpectedLocale $probe.locale -OutputRoot $outputPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Visible installer language probe failed for $($probe.locale)." }
        $counters.visibleInstallerLanguageProbes++
        Assert-FreshFieldState
    }

    $counters.freshInstallerInvocations++
    Invoke-ProcessOnce $installerPath @("/S") "fresh-install"
    $freshInstalled = $true
    Assert-InstalledFieldIdentity
    if ((Get-ObjectSha256 (Get-ProtectedState)) -cne $protectedBeforeSha256) { throw "Protected state changed after fresh install." }
    Invoke-LiveInspection "fresh" $appBinary $false
    if ((Get-ObjectSha256 (Get-ProtectedState)) -cne $protectedBeforeSha256) { throw "Protected state changed after fresh app inspection." }

    $counters.overlayInstallerInvocations++
    Invoke-ProcessOnce $installerPath @("/S", "/UPDATE") "same-version-overlay"
    Assert-InstalledFieldIdentity
    if ((Get-ObjectSha256 (Get-ProtectedState)) -cne $protectedBeforeSha256) { throw "Protected state changed after overlay." }
    Invoke-LiveInspection "overlay" $desktopShortcut $true
    if ((Get-ObjectSha256 (Get-ProtectedState)) -cne $protectedBeforeSha256) { throw "Protected state changed after overlay app inspection." }

    $counters.uninstallerInvocations++
    Invoke-ProcessOnce $uninstaller @("/S") "uninstall"
    Assert-AndRemoveOwnedPreferenceKey
    Remove-OwnedFieldAppData
    Assert-FreshFieldState
    $protectedAfter = Get-ProtectedState
    if ((Get-ObjectSha256 $protectedAfter) -cne $protectedBeforeSha256) { throw "Protected state changed after uninstall and owned cleanup." }

    foreach ($name in $counters.Keys) {
        if ([int]$counters[$name] -ne [int]$applicationContract.execution.exactCounts.$name) { throw "Lifecycle count mismatch: $name" }
    }
    $result = "passed"
} catch {
    $failure = $_.Exception.Message
    $result = "failed-frozen-no-retry"
    try { Stop-OwnedFieldProcess } catch {}
    if ($freshInstalled -and (Test-Path -LiteralPath $uninstaller -PathType Leaf) -and $counters.uninstallerInvocations -eq 0) {
        try { $counters.uninstallerInvocations++; Invoke-ProcessOnce $uninstaller @("/S") "rollback-uninstall" } catch {}
    }
    if ((Test-Path -LiteralPath $productKey) -and -not $ownedPreferenceCleanupAttempted) {
        try { Assert-AndRemoveOwnedPreferenceKey } catch {}
    }
    try { Remove-OwnedFieldAppData } catch {}
} finally {
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    if (Test-Path -LiteralPath $outputPath -PathType Container) {
        $receipt = [ordered]@{
            schemaVersion = 1
            kind = "dronedream-field-owned-isolation-lifecycle-receipt"
            result = $result
            productSource = $productSource
            evidenceHead = $head
            artifact = $applicationContract.artifact
            staticAudit = $applicationContract.staticAudit
            applicationSha256 = $applicationSha256
            planSha256 = $planSha256
            counters = $counters
            protectedStateBefore = $protectedBefore
            protectedStateAfter = if ($null -ne $protectedAfter) { $protectedAfter } else { Get-ProtectedState }
            failure = $failure
            releaseReady = $false
            websiteReady = $false
        }
        $receipt | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $outputPath "lifecycle-receipt.json") -Encoding UTF8
    }
}

if ($result -ne "passed") { exit 1 }
