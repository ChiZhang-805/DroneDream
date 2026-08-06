param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedSha256,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long]$ExpectedBytes,
    [Parameter(Mandatory = $true)]
    [string]$OfflineLayoutReceipt,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedOfflineLayoutReceiptSha256,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [ValidateRange(49152, 65535)]
    [int]$CdpPort = 49320,
    [ValidatePattern("^$|^[0-9a-f]{64}$")]
    [string]$ExpectedPlanSha256 = "",
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "edition-installer-lifecycle-contract.ps1")

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$offlineLayoutPath = (Resolve-Path -LiteralPath $OfflineLayoutReceipt).Path
$outputRootPath = [IO.Path]::GetFullPath($OutputRoot)
$validationRoot = Join-Path (Split-Path -Parent $installerPath) "validation"
$planPath = Join-Path $outputRootPath "universal-installed-app-headed-plan.json"
$executionRoot = Join-Path $outputRootPath "universal-installed-app-headed-red1"
$receiptPath = Join-Path $executionRoot "receipt.json"
$screenshotRoot = Join-Path $executionRoot "screenshots"
$caseReceiptRoot = Join-Path $executionRoot "cases"
$webViewProfileRoot = Join-Path $executionRoot "webview2-profile"
$nodeVerifier = Join-Path $repoRoot "frontend\scripts\verify-installed-universal-ui.mjs"
$installDirectory = Join-Path $env:LOCALAPPDATA "DroneDream-Universal"
$applicationPath = Join-Path $installDirectory "drone-dream-desktop.exe"
$uninstallerPath = Join-Path $installDirectory "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Universal"
$productKey = "HKCU:\Software\DroneDream\DroneDream-Universal"
$baseInstallDirectory = Join-Path $env:LOCALAPPDATA "DroneDream"
$baseUninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream"
$baseProductKey = "HKCU:\Software\DroneDream\DroneDream"
$installerCountCap = 1
$appLaunchCountCap = 1
$appCloseCountCap = 1
$uninstallerCountCap = 1
$ownedCleanupCountCap = 1
$matrix = @(
    foreach ($viewport in @(
        [ordered]@{ id = "minimum"; width = 390; height = 700 },
        [ordered]@{ id = "desktop"; width = 1440; height = 900 }
    )) {
        foreach ($locale in @("en", "zh-CN")) {
            foreach ($edition in @("universal", "sim", "lab", "field")) {
                [ordered]@{
                    id = "$($viewport.id)-$($locale.Replace('-',''))-$edition"
                    width = $viewport.width
                    height = $viewport.height
                    locale = $locale
                    presentationEdition = $edition
                }
            }
        }
    }
)

function Get-GitText {
    param([string[]]$Arguments)
    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed." }
    return (($output | Out-String).Trim())
}

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

function Get-RegistryRecord {
    param([string]$Path, [string[]]$Names)
    $values = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ path = $Path; exists = $false; values = $values }
    }
    $properties = Get-ItemProperty -LiteralPath $Path
    foreach ($name in $Names) {
        $value = $properties.$name
        $values[$name] = if ($null -eq $value) { $null } else { [string]$value }
    }
    return [ordered]@{ path = $Path; exists = $true; values = $values }
}

function Get-DirectoryRecord {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    return [ordered]@{
        path = $Path
        exists = ($null -ne $item)
        lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
    }
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
        $executable = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        if ($version -and $version -ne "0.0.0.0" -and $executable) {
            return [ordered]@{
                registryPath = $key
                version = $version
                executable = (Resolve-Path -LiteralPath $executable).Path
                executableSha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    throw "A usable existing WebView2 Runtime was not found; this verifier never installs or repairs it."
}

function Get-ProtectedState {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $programs = [Environment]::GetFolderPath("Programs")
    return [ordered]@{
        baseApplication = Get-FileRecord -Path (Join-Path $baseInstallDirectory "drone-dream-desktop.exe")
        baseUninstaller = Get-FileRecord -Path (Join-Path $baseInstallDirectory "uninstall.exe")
        baseUninstallRegistration = Get-RegistryRecord -Path $baseUninstallKey -Names @(
            "DisplayName", "DisplayVersion", "InstallLocation", "UninstallString", "MainBinaryName"
        )
        baseProductRegistration = Get-RegistryRecord -Path $baseProductKey -Names @(
            "DroneDreamRuntimeInstallMode", "DroneDreamRuntimeDrive", "DroneDreamRuntimeOperationProtocol"
        )
        baseDesktopShortcut = Get-ShortcutRecord -Path (Join-Path $desktop "DroneDream.lnk")
        baseStartMenuShortcut = Get-ShortcutRecord -Path (Join-Path $programs "DroneDream.lnk")
        runtimeRoots = @(
            Get-PSDrive -PSProvider FileSystem | ForEach-Object {
                $candidate = Join-Path $_.Root "DroneDream"
                $item = Get-Item -LiteralPath $candidate -ErrorAction SilentlyContinue
                [ordered]@{
                    path = $candidate
                    exists = ($null -ne $item)
                    lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
                }
            }
        )
        existingUniversalWebViewData = Get-DirectoryRecord -Path (
            Join-Path $env:LOCALAPPDATA "io.dronedream.desktop.universal"
        )
        webView2 = Get-WebView2Record
    }
}

function ConvertTo-CanonicalJson {
    param([object]$Value)
    return $Value | ConvertTo-Json -Depth 30 -Compress
}

function Assert-ProtectedStateUnchanged {
    param([object]$Before, [string]$Stage)
    $after = Get-ProtectedState
    if ((ConvertTo-CanonicalJson $Before) -cne (ConvertTo-CanonicalJson $after)) {
        throw "Protected existing DroneDream, Runtime, shortcuts, registry, or WebView2 changed during '$Stage'."
    }
}

function Write-AtomicJson {
    param([string]$Path, [object]$Value, [switch]$RefuseExisting)
    if ($RefuseExisting -and (Test-Path -LiteralPath $Path)) {
        throw "Refusing to overwrite frozen JSON: $Path"
    }
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }
    $temporary = "$Path.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 40), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Invoke-CheckedProcess {
    param([string]$Executable, [string[]]$Arguments, [string]$Stage)
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) { throw "$Stage exited with code $($process.ExitCode)." }
    }
    finally { $process.Dispose() }
}

function Invoke-IsolatedUninstallerOnce {
    param([string]$Stage)
    if ($script:uninstallerConsumed) { throw "The isolated uninstaller cap was already consumed." }
    $script:uninstallerConsumed = $true
    $script:counts.isolatedUninstaller++
    Invoke-CheckedProcess -Executable $uninstallerPath -Arguments @("/S", "/L=1033") -Stage $Stage
}

function Wait-ForCondition {
    param([scriptblock]$Condition, [string]$Failure, [int]$TimeoutSeconds = 45)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw $Failure
}

function Get-DescendantProcesses {
    param([int]$RootProcessId)
    $all = @(Get-CimInstance Win32_Process)
    $pending = [Collections.Generic.Queue[int]]::new()
    $pending.Enqueue($RootProcessId)
    $ids = [Collections.Generic.HashSet[int]]::new()
    while ($pending.Count -gt 0) {
        $parent = $pending.Dequeue()
        foreach ($child in @($all | Where-Object { [int]$_.ParentProcessId -eq $parent })) {
            $id = [int]$child.ProcessId
            if ($ids.Add($id)) { $pending.Enqueue($id) }
        }
    }
    return @($all | Where-Object { $ids.Contains([int]$_.ProcessId) })
}

function Ensure-WindowInterop {
    if ("DroneDreamInstalledUiWindow" -as [type]) { return }
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class DroneDreamInstalledUiWindow {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
"@
}

function Set-AppClientSize {
    param([Diagnostics.Process]$Process, [int]$Width, [int]$Height)
    Ensure-WindowInterop
    Wait-ForCondition -TimeoutSeconds 30 -Failure "Installed app did not expose a main window." -Condition {
        $Process.Refresh()
        return $Process.MainWindowHandle -ne [IntPtr]::Zero
    }
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        $window = [DroneDreamInstalledUiWindow+RECT]::new()
        $client = [DroneDreamInstalledUiWindow+RECT]::new()
        if (-not [DroneDreamInstalledUiWindow]::GetWindowRect($Process.MainWindowHandle, [ref]$window) -or
            -not [DroneDreamInstalledUiWindow]::GetClientRect($Process.MainWindowHandle, [ref]$client)) {
            throw "Cannot measure the installed app window."
        }
        $clientWidth = $client.Right - $client.Left
        $clientHeight = $client.Bottom - $client.Top
        if ([Math]::Abs($clientWidth - $Width) -le 2 -and [Math]::Abs($clientHeight - $Height) -le 2) { return }
        $borderWidth = ($window.Right - $window.Left) - $clientWidth
        $borderHeight = ($window.Bottom - $window.Top) - $clientHeight
        $flags = 0x0002 -bor 0x0004 -bor 0x0010
        if (-not [DroneDreamInstalledUiWindow]::SetWindowPos(
            $Process.MainWindowHandle, [IntPtr]::Zero, 0, 0,
            $Width + $borderWidth, $Height + $borderHeight, $flags
        )) { throw "Cannot resize the installed app window." }
        Start-Sleep -Milliseconds 400
    }
    throw "Installed app client size did not converge to ${Width}x${Height}."
}

function Remove-TestCreatedProductRegistration {
    if (-not (Test-Path -LiteralPath $productKey)) { return $false }
    $properties = Get-ItemProperty -LiteralPath $productKey
    $values = [ordered]@{ "(default)" = [string](Get-Item -LiteralPath $productKey).GetValue("") }
    foreach ($property in @($properties.PSObject.Properties | Sort-Object Name)) {
        if ($property.Name -notmatch '^PS' -and $property.Name -ne '(default)') {
            $values[$property.Name] = $property.Value
        }
    }
    [void](Get-DroneDreamProductRegistrationDisposition `
        -Values $values `
        -ExpectedInstallDirectory $installDirectory `
        -PreflightProductKeyAbsent $true)
    Remove-Item -LiteralPath $productKey -Force
    return $true
}

function Invoke-OwnedCleanupOnce {
    if ($script:cleanupConsumed) { throw "The owned cleanup cap was already consumed." }
    $script:cleanupConsumed = $true
    $script:counts.ownedCleanup++
    $result = [ordered]@{
        productRegistrationRemoved = $false
        testWebViewProfileRemoved = $false
    }
    if (Test-Path -LiteralPath $productKey) {
        $result.productRegistrationRemoved = Remove-TestCreatedProductRegistration
    }
    if (Test-Path -LiteralPath $webViewProfileRoot) {
        $resolvedProfile = [IO.Path]::GetFullPath($webViewProfileRoot)
        $resolvedExecution = [IO.Path]::GetFullPath($executionRoot).TrimEnd('\') + '\'
        if (-not $resolvedProfile.StartsWith($resolvedExecution, [StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedProfile) -cne "webview2-profile") {
            throw "Refusing cleanup outside the exact owned headed-validation profile."
        }
        Remove-Item -LiteralPath $resolvedProfile -Recurse -Force
        $result.testWebViewProfileRemoved = $true
    }
    return $result
}

function Close-ThisBatchAppOnce {
    param([Diagnostics.Process]$Process, [bool]$FailIfNotRunning)
    if ($script:appCloseConsumed) { throw "The installed-app close cap was already consumed." }
    $Process.Refresh()
    if ($Process.HasExited) {
        if ($FailIfNotRunning) { throw "Installed app exited before its single planned close." }
        return $false
    }
    $script:appCloseConsumed = $true
    $script:counts.appClose++
    if (-not $Process.CloseMainWindow() -or -not $Process.WaitForExit(15000)) {
        if (-not $Process.HasExited) {
            $Process.Kill($true)
            $Process.WaitForExit()
        }
        throw "Installed app required forced recovery after its single close operation."
    }
    return $true
}

$actualSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$actualBytes = [long](Get-Item -LiteralPath $installerPath).Length
$actualLayoutSha256 = (Get-FileHash -LiteralPath $offlineLayoutPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Split-Path -Leaf $installerPath) -cne "DroneDream-Universal-1.0.0.exe" -or
    $actualSha256 -cne $ExpectedSha256 -or $actualBytes -ne $ExpectedBytes) {
    throw "Installer identity does not match the frozen Universal artifact."
}
if ($actualLayoutSha256 -cne $ExpectedOfflineLayoutReceiptSha256) {
    throw "Offline layout receipt drifted."
}
if (-not (Test-Path -LiteralPath $nodeVerifier -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $repoRoot "frontend\node_modules\playwright") -PathType Container)) {
    throw "The tracked installed-app verifier or pinned Playwright dependency is unavailable."
}
$validationRootFull = [IO.Path]::GetFullPath($validationRoot).TrimEnd('\') + '\'
if (-not $outputRootPath.StartsWith($validationRootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot must remain inside the frozen artifact validation directory."
}
$head = Get-GitText @("rev-parse", "HEAD")
$upstream = Get-GitText @("rev-parse", "@{upstream}")
if ($head -cne $upstream -or -not [string]::IsNullOrWhiteSpace((Get-GitText @("status", "--porcelain")))) {
    throw "Installed-app verification requires a clean exact upstream tool source."
}
[void](Get-GitText @("cat-file", "-e", "$ProductSourceCommit^{commit}"))
& git -C $repoRoot merge-base --is-ancestor $ProductSourceCommit $head | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Product source is not an ancestor of the verification tool source."
}
if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
    throw "DroneDream is running; this verifier never adopts or terminates a pre-existing app."
}
if ((Test-Path -LiteralPath $installDirectory) -or (Test-Path -LiteralPath $uninstallKey) -or
    (Test-Path -LiteralPath $productKey)) {
    throw "Universal owned install state already exists; refusing to overwrite or clean it."
}
if (@(Get-NetTCPConnection -State Listen -LocalPort $CdpPort -ErrorAction SilentlyContinue).Count -ne 0) {
    throw "Loopback CDP port $CdpPort is already in use."
}
$protectedBefore = Get-ProtectedState
$toolFiles = [ordered]@{
    powershell = Get-FileRecord -Path $PSCommandPath
    browser = Get-FileRecord -Path $nodeVerifier
}
$plan = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-installed-app-headed-plan"
    productSourceCommit = $ProductSourceCommit
    toolSourceCommit = $head
    reviewedEvidenceHead = $head
    artifact = [ordered]@{
        absolutePath = $installerPath
        fileName = "DroneDream-Universal-1.0.0.exe"
        version = "1.0.0"
        bytes = $actualBytes
        sha256 = $actualSha256
    }
    tools = $toolFiles
    offlineEvidence = [ordered]@{
        absolutePath = $offlineLayoutPath
        sha256 = $actualLayoutSha256
        role = "offline-layout-contract-only-not-installed-app-evidence"
    }
    resourceClass = if ($Execute) { "RED" } else { "GREEN" }
    exactCounts = [ordered]@{
        installerFreshSilentNoShortcut = 1
        appLaunch = 1
        appClose = 1
        isolatedUninstaller = 1
        ownedCleanupMax = 1
        settingsOpen = $matrix.Count
        settingsTabActivations = $matrix.Count * 4
        screenshots = $matrix.Count * 2
        runtimeStart = 0
        px4 = 0
        gazebo = 0
        browser = 0
        auth = 0
    }
    targets = [ordered]@{
        installRoot = $installDirectory
        application = $applicationPath
        uninstaller = $uninstallerPath
        plan = $planPath
        executionReceipt = $receiptPath
        screenshots = $screenshotRoot
        caseReceipts = $caseReceiptRoot
        isolatedWebViewProfile = $webViewProfileRoot
    }
    webView2 = [ordered]@{
        observation = "loopback-cdp-parent-child-read-only-existing-runtime"
        cdpEndpoint = "http://127.0.0.1:$CdpPort"
        preflight = $protectedBefore.webView2
        installOrRepairAllowed = $false
    }
    presentationMatrix = $matrix
    authority = [ordered]@{
        presentationOnly = $true
        grantsHardwareAuthority = $false
        modeSwitchMayAuthorizeHardware = $false
    }
    failurePolicy = [ordered]@{
        closeOnlyThisBatchApp = $true
        invokeOnlyThisBatchUninstaller = $true
        restoreAndCompareProtectedState = $true
        retryAllowed = $false
    }
    executionAuthorized = [bool]$Execute
}

if (-not $Execute) {
    Write-AtomicJson -Path $planPath -Value $plan -RefuseExisting
    Write-Host "Installed-app headed plan frozen; no installer, app, Runtime, browser, auth, PX4, or Gazebo action ran."
    exit 0
}

if ([string]::IsNullOrWhiteSpace($ExpectedPlanSha256) -or -not (Test-Path -LiteralPath $planPath -PathType Leaf)) {
    throw "Execute requires the separately frozen plan and its exact SHA256."
}
if ((Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedPlanSha256) {
    throw "Frozen installed-app plan drifted."
}
$frozenPlan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
if ($frozenPlan.productSourceCommit -cne $ProductSourceCommit -or
    $frozenPlan.toolSourceCommit -cne $head -or
    $frozenPlan.artifact.sha256 -cne $actualSha256 -or
    [long]$frozenPlan.artifact.bytes -ne $actualBytes -or
    $frozenPlan.offlineEvidence.sha256 -cne $actualLayoutSha256 -or
    $frozenPlan.targets.installRoot -cne $installDirectory -or
    $frozenPlan.targets.application -cne $applicationPath -or
    $frozenPlan.targets.executionReceipt -cne $receiptPath -or
    $frozenPlan.targets.isolatedWebViewProfile -cne $webViewProfileRoot -or
    [int]$frozenPlan.exactCounts.settingsOpen -ne $matrix.Count -or
    [bool]$frozenPlan.authority.grantsHardwareAuthority) {
    throw "Frozen installed-app plan does not match this exact execution context."
}
if (Test-Path -LiteralPath $executionRoot) {
    throw "Refusing to overwrite an existing installed-app execution root."
}

$counts = [ordered]@{
    installerFreshSilentNoShortcut = 0
    appLaunch = 0
    appClose = 0
    isolatedUninstaller = 0
    ownedCleanup = 0
    settingsOpen = 0
    settingsTabActivations = 0
    screenshots = 0
}
$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-installed-app-headed-receipt"
    planSha256 = $ExpectedPlanSha256
    productSourceCommit = $ProductSourceCommit
    toolSourceCommit = $head
    artifact = $plan.artifact
    startedAt = [DateTime]::UtcNow.ToString("O")
    passed = $false
    counts = $counts
    cases = @()
}
$appProcess = $null
$installedByRun = $false
$script:uninstallerConsumed = $false
$script:cleanupConsumed = $false
$script:appCloseConsumed = $false
$script:counts = $counts

try {
    New-Item -ItemType Directory -Path $executionRoot | Out-Null
    $counts.installerFreshSilentNoShortcut++
    Invoke-CheckedProcess -Executable $installerPath -Arguments @("/S", "/NS", "/L=1033") -Stage "fresh-silent-no-shortcut"
    $installedByRun = $true
    Wait-ForCondition -Failure "Installed Universal application did not appear." -Condition {
        (Test-Path -LiteralPath $applicationPath -PathType Leaf) -and
        (Test-Path -LiteralPath $uninstallerPath -PathType Leaf)
    }

    $previousBrowserArguments = [Environment]::GetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "Process")
    $previousUserDataFolder = [Environment]::GetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", "Process")
    try {
        [Environment]::SetEnvironmentVariable(
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$CdpPort",
            "Process"
        )
        [Environment]::SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", $webViewProfileRoot, "Process")
        $counts.appLaunch++
        $appProcess = Start-Process -FilePath $applicationPath -PassThru
    }
    finally {
        [Environment]::SetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", $previousBrowserArguments, "Process")
        [Environment]::SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", $previousUserDataFolder, "Process")
    }

    Wait-ForCondition -TimeoutSeconds 45 -Failure "Installed app did not open loopback WebView2 CDP." -Condition {
        @(Get-NetTCPConnection -State Listen -LocalPort $CdpPort -ErrorAction SilentlyContinue).Count -eq 1
    }
    $webViewChildren = @(Get-DescendantProcesses -RootProcessId $appProcess.Id | Where-Object { $_.Name -ieq "msedgewebview2.exe" })
    if ($webViewChildren.Count -eq 0) { throw "No WebView2 child process belongs to the installed app." }
    $receipt.webView2 = [ordered]@{
        parentProcessId = $appProcess.Id
        childCount = $webViewChildren.Count
        childProcesses = @($webViewChildren | ForEach-Object {
            [ordered]@{ processId = [int]$_.ProcessId; parentProcessId = [int]$_.ParentProcessId; executablePath = [string]$_.ExecutablePath }
        })
        existingRuntimeBefore = $protectedBefore.webView2
    }

    foreach ($case in $matrix) {
        Set-AppClientSize -Process $appProcess -Width $case.width -Height $case.height
        $caseReceipt = Join-Path $caseReceiptRoot "$($case.id).json"
        $arguments = @(
            $nodeVerifier,
            "--cdp-endpoint=http://127.0.0.1:$CdpPort",
            "--output=$caseReceipt",
            "--screenshot-root=$screenshotRoot",
            "--case-id=$($case.id)",
            "--locale=$($case.locale)",
            "--edition=$($case.presentationEdition)",
            "--width=$($case.width)",
            "--height=$($case.height)"
        )
        & node @arguments
        if ($LASTEXITCODE -ne 0) { throw "Installed-app browser verifier failed for $($case.id)." }
        $caseResult = Get-Content -LiteralPath $caseReceipt -Raw | ConvertFrom-Json
        $counts.settingsOpen += [int]$caseResult.settingsOpenCount
        $counts.settingsTabActivations += [int]$caseResult.settingsTabActivationCount
        $counts.screenshots += 2
        $receipt.cases += [ordered]@{
            id = $case.id
            receiptPath = $caseReceipt
            receiptSha256 = (Get-FileHash -LiteralPath $caseReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    if ($counts.settingsOpen -ne $matrix.Count -or
        $counts.settingsTabActivations -ne $matrix.Count * 4 -or
        $counts.screenshots -ne $matrix.Count * 2) {
        throw "Installed-app UI observation counts drifted from the frozen plan."
    }

    [void](Close-ThisBatchAppOnce -Process $appProcess -FailIfNotRunning $true)
    $appProcess.Dispose()
    $appProcess = $null

    Invoke-IsolatedUninstallerOnce -Stage "isolated-uninstall"
    $installedByRun = $false
    Wait-ForCondition -Failure "Universal install root remained after its isolated uninstaller." -Condition {
        -not (Test-Path -LiteralPath $installDirectory)
    }
    $receipt.ownedCleanup = Invoke-OwnedCleanupOnce
    Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "successful-headed-app-validation"
    if ($counts.installerFreshSilentNoShortcut -ne $installerCountCap -or
        $counts.appLaunch -ne $appLaunchCountCap -or
        $counts.appClose -ne $appCloseCountCap -or
        $counts.isolatedUninstaller -ne $uninstallerCountCap -or
        $counts.ownedCleanup -ne $ownedCleanupCountCap) {
        throw "Installed-app process counts drifted from the exact bounded plan."
    }
    $receipt.passed = $true
}
catch {
    $receipt.failure = [ordered]@{ type = $_.Exception.GetType().FullName; message = $_.Exception.Message }
    throw
}
finally {
    if ($null -ne $appProcess) {
        try {
            if (-not $script:appCloseConsumed) {
                [void](Close-ThisBatchAppOnce -Process $appProcess -FailIfNotRunning $false)
            }
        }
        catch { $receipt.appCloseRecoveryError = $_.Exception.Message }
        finally { $appProcess.Dispose() }
    }
    if ($installedByRun -and -not $script:uninstallerConsumed -and (Test-Path -LiteralPath $uninstallerPath -PathType Leaf)) {
        try {
            Invoke-IsolatedUninstallerOnce -Stage "failure-recovery-isolated-uninstall"
            $receipt.failureRecoveryUninstaller = "succeeded"
        }
        catch {
            $receipt.failureRecoveryUninstaller = "failed-manual-attention-required"
            $receipt.failureRecoveryUninstallerError = $_.Exception.Message
        }
    }
    if (-not $script:cleanupConsumed -and ((Test-Path -LiteralPath $productKey) -or
        (Test-Path -LiteralPath $webViewProfileRoot))) {
        try {
            $receipt.ownedCleanup = Invoke-OwnedCleanupOnce
        }
        catch { $receipt.ownedCleanupError = $_.Exception.Message }
    }
    try { Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "final-headed-app-validation" }
    catch { $receipt.protectedStateError = $_.Exception.Message }
    $receipt.completedAt = [DateTime]::UtcNow.ToString("O")
    $receipt.counts = $counts
    Write-AtomicJson -Path $receiptPath -Value $receipt
}

Write-Host "Universal installed-app headed UI matrix passed; Runtime, browser auth, PX4, and Gazebo were not started."
