param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{40}$")][string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][ValidateRange(1, [long]::MaxValue)][long]$ExpectedBytes,
    [Parameter(Mandatory = $true)][string]$LifecycleReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedLifecycleReceiptSha256,
    [Parameter(Mandatory = $true)][string]$VisibleInstallerReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedVisibleInstallerReceiptSha256,
    [string]$InstalledAppReceipt = "",
    [ValidatePattern("^$|^[0-9a-f]{64}$")][string]$ExpectedInstalledAppReceiptSha256 = "",
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [ValidateSet("oauth", "runtime-diagnosis")][string]$Mode = "oauth",
    [ValidateRange(49152, 65535)][int]$CdpPort = 49321,
    [ValidatePattern("^$|^[0-9a-f]{64}$")][string]$ExpectedPlanSha256 = "",
    [switch]$RunAuthenticatedUiMatrix,
    [switch]$AllowBrowserConsentAction,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$lifecyclePath = (Resolve-Path -LiteralPath $LifecycleReceipt).Path
$visibleInstallerPath = (Resolve-Path -LiteralPath $VisibleInstallerReceipt).Path
$installedAppPath = if ($InstalledAppReceipt) { (Resolve-Path -LiteralPath $InstalledAppReceipt).Path } else { $null }
$outputRootPath = [IO.Path]::GetFullPath($OutputRoot)
$validationRoot = Join-Path (Split-Path -Parent $installerPath) "validation"
$runtimeDiagnosisOnly = $Mode -ceq "runtime-diagnosis"
$planPath = Join-Path $outputRootPath $(if ($runtimeDiagnosisOnly) { "universal-runtime-diagnosis-plan.json" } else { "universal-real-oauth-plan.json" })
$executionRoot = Join-Path $outputRootPath $(if ($runtimeDiagnosisOnly) { "universal-runtime-diagnosis-red1" } else { "universal-real-oauth-red1" })
$receiptPath = Join-Path $executionRoot "receipt.json"
$observerPath = Join-Path $executionRoot "app-observation.json"
$postAuthSignalPath = Join-Path $executionRoot "post-auth-ui.signal"
$uiCaseRoot = Join-Path $executionRoot "authenticated-ui-cases"
$uiScreenshotRoot = Join-Path $executionRoot "authenticated-ui-screenshots"
$webViewProfileRoot = Join-Path $executionRoot "webview2-profile"
$nodeVerifier = Join-Path $repoRoot "frontend\scripts\verify-installed-universal-oauth.mjs"
$uiVerifier = Join-Path $repoRoot "frontend\scripts\verify-installed-universal-ui.mjs"
$browserConsentVerifier = Join-Path $PSScriptRoot "confirm-universal-browser-consent.ps1"
$installDirectory = Join-Path $env:LOCALAPPDATA "DroneDream-Universal"
$applicationPath = Join-Path $installDirectory "drone-dream-desktop.exe"
$uninstallerPath = Join-Path $installDirectory "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Universal"
$productKey = "HKCU:\Software\DroneDream\DroneDream-Universal"
$auditRoot = Join-Path $env:LOCALAPPDATA "io.dronedream.desktop.universal\audit\browser-auth"
$redirectUri = "http://127.0.0.1:49210/desktop-auth/universal/callback"
$uiMatrix = @(
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

function Get-GitText([string[]]$Arguments) {
    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed." }
    return (($output | Out-String).Trim())
}

function Get-FileRecord([string]$Path) {
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

function Get-DirectoryRecord([string]$Path) {
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    return [ordered]@{
        path = $Path
        exists = ($null -ne $item)
        lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
    }
}

function Write-AtomicJson([string]$Path, $Value) {
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporary = "$Path.tmp-$PID"
    try {
        $json = $Value | ConvertTo-Json -Depth 30
        [IO.File]::WriteAllText($temporary, "$json`n", [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
}

function Write-AtomicText([string]$Path, [string]$Value) {
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $temporary = "$Path.tmp-$PID"
    try {
        [IO.File]::WriteAllText($temporary, "$Value`n", [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
}

function Get-BytesSha256Lower([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (([BitConverter]::ToString($sha.ComputeHash($Bytes))) -replace "-", "").ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Import-ObserverCheckpoint([string]$Path, $Counts, $Receipt) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $observation = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($observation.schemaVersion -ne 2 -or $observation.kind -cne "dronedream-installed-universal-oauth-observation") {
        throw "Installed-app OAuth observer checkpoint has an unknown contract."
    }
    $expectedCountKeys = @("localLogout", "loginButton", "oauthTransaction", "runtimeStart")
    $actualCountKeys = @($observation.counts.PSObject.Properties.Name | Sort-Object)
    if (($actualCountKeys -join "|") -cne (($expectedCountKeys | Sort-Object) -join "|")) {
        throw "Installed-app OAuth observer checkpoint has unknown count fields."
    }
    foreach ($key in $expectedCountKeys) {
        $value = $observation.counts.$key
        if ($value -isnot [int] -and $value -isnot [long]) {
            throw "Installed-app OAuth observer count $key is not an integer."
        }
        if ([long]$value -lt 0 -or [long]$value -gt 1) {
            throw "Installed-app OAuth observer count $key exceeds its frozen cap."
        }
        $Counts[$key] = [int]$value
    }
    $allowedStages = @("initialized", "connected", "runtime-start-attempted", "runtime-ready", "runtime-already-ready", "runtime-start-failed", "runtime-diagnosis-completed", "oauth-attempted", "authenticated-ui-ready", "local-logout-attempted", "completed")
    if ($observation.stage -notin $allowedStages) { throw "Installed-app OAuth observer checkpoint has an unknown stage." }
    $allowedRuntimeFailures = @($null, "runtime_service_unhealthy", "runtime_host_connectivity", "runtime_health_unknown", "runtime_maintenance_deadline_exceeded", "runtime_operation_busy", "runtime_update_quiesce_active", "runtime_not_installed", "runtime_error_unclassified", "runtime_start_pending_timeout")
    if ($observation.runtimeFailureCode -notin $allowedRuntimeFailures) {
        throw "Installed-app OAuth observer checkpoint has an unknown Runtime failure code."
    }
    $Receipt["runtimeDiagnosis"] = [ordered]@{
        stage = [string]$observation.stage
        runtimeReadyObserved = [bool]$observation.runtimeReadyObserved
        runtimeActionSettled = [bool]$observation.runtimeActionSettled
        runtimeFailureCode = $observation.runtimeFailureCode
        observerCheckpointSha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        rawRuntimeErrorRecorded = $false
    }
    return $observation
}

function Get-WslInventory {
    $raw = (& wsl.exe --list --verbose 2>$null | Out-String) -replace "`0", ""
    $rows = @()
    foreach ($line in ($raw -split "`r?`n")) {
        if ($line -match '^\s*\*?\s*(?<name>\S.*?)\s{2,}(?<state>Running|Stopped)\s{2,}(?<version>\d+)\s*$') {
            $rows += [ordered]@{ name = $Matches.name.Trim(); state = $Matches.state; version = [int]$Matches.version }
        }
    }
    return @($rows | Sort-Object name)
}

function Get-PortRecord([int]$Port) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    return [ordered]@{ port = $Port; listenerCount = $listeners.Count }
}

function Get-AuditRecords {
    $records = @()
    if (-not (Test-Path -LiteralPath $auditRoot -PathType Container)) { return $records }
    foreach ($file in @(Get-ChildItem -LiteralPath $auditRoot -File -Filter "*.jsonl" | Sort-Object FullName)) {
        $lineNumber = 0
        foreach ($line in [IO.File]::ReadLines($file.FullName)) {
            $lineNumber++
            if (-not $line.Trim()) { continue }
            $value = $line | ConvertFrom-Json
            $keys = @($value.PSObject.Properties.Name | Sort-Object)
            $allowed = @("attemptIdHash","authClientId","brokerOrigin","callbackTransport","completedAt","contractVersion","editionId","failureCode","issuedAt","kind","receiptVersion","result","stateHash","subjectHash") | Sort-Object
            if (($keys -join "|") -cne ($allowed -join "|")) { throw "Browser-auth audit contains non-allowlisted fields." }
            $encoded = [Text.Encoding]::UTF8.GetBytes($line)
            $records += [ordered]@{
                file = $file.FullName
                line = $lineNumber
                lineSha256 = Get-BytesSha256Lower $encoded
                value = $value
            }
        }
    }
    return $records
}

function Get-ProtectedState {
    $baseInstall = Join-Path $env:LOCALAPPDATA "DroneDream"
    return [ordered]@{
        baseApplication = Get-FileRecord (Join-Path $baseInstall "drone-dream-desktop.exe")
        baseUninstaller = Get-FileRecord (Join-Path $baseInstall "uninstall.exe")
        wslInventory = @(Get-WslInventory)
        simStorage = Get-DirectoryRecord (Join-Path $env:LOCALAPPDATA "io.dronedream.desktop.sim")
        labStorage = Get-DirectoryRecord (Join-Path $env:LOCALAPPDATA "io.dronedream.desktop.lab")
        fieldStorage = Get-DirectoryRecord (Join-Path $env:LOCALAPPDATA "io.dronedream.desktop.field")
    }
}

function Assert-ProtectedStateUnchanged($Before, [string]$Stage) {
    $after = Get-ProtectedState
    $beforeJson = $Before | ConvertTo-Json -Depth 20 -Compress
    $afterJson = $after | ConvertTo-Json -Depth 20 -Compress
    if ($beforeJson -cne $afterJson) { throw "$Stage changed the base app, Runtime identity/state, or another Edition storage namespace." }
    return $after
}

function Get-ResourceRecord {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    $heavy = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match 'cargo|rustc|tauri|makensis|px4|gz'
    } | Select-Object ProcessName, Id)
    return [ordered]@{
        memoryFreeGiB = [Math]::Round(([double]$os.FreePhysicalMemory * 1KB / 1GB), 2)
        memoryUsedPercent = [Math]::Round((1 - ([double]$os.FreePhysicalMemory / [double]$os.TotalVisibleMemorySize)) * 100, 1)
        cpuLoadPercent = [Math]::Round([double]$cpu, 1)
        cFreeGiB = [Math]::Round((Get-PSDrive C).Free / 1GB, 2)
        zFreeGiB = [Math]::Round((Get-PSDrive Z).Free / 1GB, 2)
        heavyProcesses = $heavy
    }
}

function Assert-Receipt([string]$Path, [string]$ExpectedSha, [scriptblock]$Predicate, [string]$Label) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $ExpectedSha) { throw "$Label receipt SHA drifted." }
    $document = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if (-not (& $Predicate $document)) { throw "$Label receipt did not prove its frozen success gate." }
    return [ordered]@{ path = $Path; bytes = (Get-Item -LiteralPath $Path).Length; sha256 = $actual }
}

function Invoke-Checked([string]$FilePath, [string[]]$Arguments, [string]$Stage) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "$Stage failed with exit code $($process.ExitCode)." }
}

function Wait-Until([scriptblock]$Condition, [int]$TimeoutSeconds, [string]$Failure) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw $Failure
}

$head = Get-GitText @("rev-parse", "HEAD")
$upstream = Get-GitText @("rev-parse", "@{u}")
if ($head -cne $upstream -or (Get-GitText @("status", "--porcelain"))) {
    throw "Universal OAuth verifier requires an exact clean upstream tool source."
}
& git -C $repoRoot merge-base --is-ancestor $ProductSourceCommit $head
if ($LASTEXITCODE -ne 0) { throw "Product source is not an ancestor of the verifier source." }

$artifact = Get-FileRecord $installerPath
if ($artifact.bytes -ne $ExpectedBytes -or $artifact.sha256 -cne $ExpectedSha256) { throw "Frozen Universal artifact drifted." }
$lifecycle = Assert-Receipt $lifecyclePath $ExpectedLifecycleReceiptSha256 { param($d) $d.productSourceCommit -ceq $ProductSourceCommit -and $d.installerLifecycleReady -eq $true } "Lifecycle"
$visible = Assert-Receipt $visibleInstallerPath $ExpectedVisibleInstallerReceiptSha256 { param($d) $d.productSourceCommit -ceq $ProductSourceCommit -and $d.result.visibleInstallerUiReady -eq $true } "Visible installer"
$headed = $null
if ($RunAuthenticatedUiMatrix) {
    if ($runtimeDiagnosisOnly) { throw "Authenticated UI matrix is unavailable in Runtime diagnosis mode." }
    if ($InstalledAppReceipt -or $ExpectedInstalledAppReceiptSha256) {
        throw "Authenticated UI matrix replaces, rather than combines with, a pre-auth installed-app success gate."
    }
}
else {
    if (-not $installedAppPath -or -not $ExpectedInstalledAppReceiptSha256) {
        throw "OAuth-only validation requires a prior successful installed-app receipt."
    }
    $headed = Assert-Receipt $installedAppPath $ExpectedInstalledAppReceiptSha256 { param($d) $d.productSourceCommit -ceq $ProductSourceCommit -and $d.passed -eq $true } "Installed app"
}

if (-not (Test-Path -LiteralPath $nodeVerifier -PathType Leaf)) { throw "Installed-app OAuth observer is missing." }
if ($RunAuthenticatedUiMatrix -and -not (Test-Path -LiteralPath $uiVerifier -PathType Leaf)) { throw "Authenticated installed-app UI observer is missing." }
if ($AllowBrowserConsentAction -and -not (Test-Path -LiteralPath $browserConsentVerifier -PathType Leaf)) { throw "Bounded browser consent helper is missing." }
if (-not $outputRootPath.StartsWith(([IO.Path]::GetFullPath($validationRoot) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) { throw "OutputRoot must be a new owned child of the artifact validation directory." }
if ((Get-PortRecord 49210).listenerCount -ne 0 -or (Get-PortRecord $CdpPort).listenerCount -ne 0) { throw "OAuth callback or CDP port is already occupied." }
if ((Test-Path -LiteralPath $installDirectory) -or (Test-Path -LiteralPath $uninstallKey) -or (Test-Path -LiteralPath $productKey)) { throw "Universal test identity is not isolated before planning." }

$runtimeInventory = @(Get-WslInventory)
$runtime = @($runtimeInventory | Where-Object { $_.name -ceq "DroneDreamRuntime" })
$runtimeRequired = $true
if ($runtime.Count -ne 1) { throw "The existing DroneDreamRuntime WSL distribution is unavailable; this plan cannot install or register one." }
$plan = [ordered]@{
    schemaVersion = 2
    kind = if ($runtimeDiagnosisOnly) { "dronedream-universal-runtime-diagnosis-plan" } else { "dronedream-universal-real-oauth-plan" }
    mode = $Mode
    runAuthenticatedUiMatrix = [bool]$RunAuthenticatedUiMatrix
    allowBrowserConsentAction = [bool]$AllowBrowserConsentAction
    resourceClass = "RED"
    executionAuthorized = $false
    productSourceCommit = $ProductSourceCommit
    toolSourceCommit = $head
    artifact = $artifact
    successfulPrerequisites = [ordered]@{ lifecycle = $lifecycle; visibleInstaller = $visible; installedAppHeaded = $headed }
    targets = [ordered]@{
        installRoot = $installDirectory
        application = $applicationPath
        isolatedWebViewProfile = $webViewProfileRoot
        plan = $planPath
        executionReceipt = $receiptPath
        appObservation = $observerPath
        postAuthUiSignal = if ($RunAuthenticatedUiMatrix) { $postAuthSignalPath } else { $null }
        authenticatedUiCases = if ($RunAuthenticatedUiMatrix) { $uiCaseRoot } else { $null }
        authenticatedUiScreenshots = if ($RunAuthenticatedUiMatrix) { $uiScreenshotRoot } else { $null }
    }
    auth = [ordered]@{
        executionAllowed = (-not $runtimeDiagnosisOnly)
        editionId = "universal"
        authClientId = "dronedream-desktop-universal"
        protocolVersion = "desktop-browser-auth-pkce-v1"
        callback = [ordered]@{ uri = $redirectUri; port = 49210; listenerCount = 0 }
        existingBrowserCookieMayBeUsed = $true
        browserCredentialInputCap = 0
        browserPasswordStoreReadCap = 0
        nonCredentialAccountOrConsentActionCap = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        providerRetryCap = 0
        rawCallbackLoggingAllowed = $false
        tokenCookiePasswordPersistenceAllowed = $false
    }
    runtime = [ordered]@{
        requiredBeforeLogin = $runtimeRequired
        reason = "DesktopSetup localChecksReady requires the installed Runtime, health/readback, Runtime access, and session API to be ready before browser sign-in is exposed."
        inventory = $runtimeInventory
        droneDreamRuntimePresent = ($runtime.Count -eq 1)
        startExistingRuntimeCap = 1
        installUpgradeMigrationRepairConfigurationCap = 0
        runtimeBaseReplacementCap = 0
        wslRegisterUnregisterCap = 0
        px4GazeboSitlHitlCap = 0
        restorePreRunState = $true
    }
    exactCounts = [ordered]@{
        installerFreshSilentNoShortcut = 1
        appLaunch = 1
        runtimeStartMax = 1
        diagnosisSettlementMax = 1
        credentialVaultRestoreProbeMax = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        loginButton = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        oauthTransaction = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        callback = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        authorizationCodeExchange = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        browserAction = if ($AllowBrowserConsentAction) { 1 } else { 0 }
        localLogout = if ($runtimeDiagnosisOnly) { 0 } else { 1 }
        appClose = 1
        isolatedUninstaller = 1
        ownedCleanupMax = 1
        authenticatedUiCases = if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count } else { 0 }
        settingsOpen = if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count } else { 0 }
        settingsTabActivations = if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count * 4 } else { 0 }
        screenshots = if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count * 2 } else { 0 }
    }
    portsAtPlan = @((Get-PortRecord 49210), (Get-PortRecord $CdpPort))
    resourcesAtPlan = Get-ResourceRecord
    authenticatedUiMatrix = if ($RunAuthenticatedUiMatrix) { $uiMatrix } else { @() }
    protectedStateAtPlan = Get-ProtectedState
    failurePolicy = [ordered]@{
        retryCap = 0
        stopBeforeAnyCredentialInput = $true
        stopOnInstallOrMigrationSurface = $true
        stopOnUnexpectedBrowserOrCallback = $true
        browserAuthenticationForbidden = $runtimeDiagnosisOnly
        rawRuntimeErrorPersistenceAllowed = $false
        rollbackWithOwnUninstallerOnly = $true
        preserveFailureEvidence = $true
    }
}

if (-not $Execute) {
    if (Test-Path -LiteralPath $outputRootPath) { throw "Refusing to overwrite an existing validation plan root." }
    Write-AtomicJson $planPath $plan
    Write-Host "Universal $Mode plan frozen; no installer, app, Runtime, browser, auth, PX4, or Gazebo action ran."
    exit 0
}

if (-not $ExpectedPlanSha256) { throw "Execute requires ExpectedPlanSha256." }
$actualPlanSha = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPlanSha -cne $ExpectedPlanSha256) { throw "Frozen validation plan SHA drifted." }
$frozenPlan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
if ($frozenPlan.schemaVersion -ne 2 -or $frozenPlan.mode -cne $Mode -or
    [bool]$frozenPlan.runAuthenticatedUiMatrix -ne [bool]$RunAuthenticatedUiMatrix -or
    [bool]$frozenPlan.allowBrowserConsentAction -ne [bool]$AllowBrowserConsentAction) {
    throw "Frozen validation plan mode drifted."
}
if (Test-Path -LiteralPath $executionRoot) { throw "Refusing to overwrite an existing validation execution root." }

$counts = [ordered]@{ installerFreshSilentNoShortcut = 0; appLaunch = 0; runtimeStart = 0; diagnosisSettlement = 0; credentialVaultRestoreProbe = 0; loginButton = 0; oauthTransaction = 0; callback = 0; authorizationCodeExchange = 0; browserAction = 0; localLogout = 0; authenticatedUiCases = 0; settingsOpen = 0; settingsTabActivations = 0; screenshots = 0; appClose = 0; isolatedUninstaller = 0; ownedCleanup = 0 }
$receipt = [ordered]@{ schemaVersion = 2; kind = if ($runtimeDiagnosisOnly) { "dronedream-universal-runtime-diagnosis-receipt" } else { "dronedream-universal-real-oauth-receipt" }; mode = $Mode; planSha256 = $ExpectedPlanSha256; productSourceCommit = $ProductSourceCommit; toolSourceCommit = $head; artifact = $artifact; startedAt = [DateTime]::UtcNow.ToString("O"); passed = $false; counts = $counts }
$app = $null
$oauthObserverProcess = $null
$installed = $false
$uninstalled = $false
$cleaned = $false
$auditBefore = @(Get-AuditRecords)
$protectedBefore = Get-ProtectedState
function Save-ExecutionCheckpoint([string]$Stage) {
    $receipt["stage"] = $Stage
    $receipt["updatedAt"] = [DateTime]::UtcNow.ToString("O")
    $receipt["counts"] = $counts
    Write-AtomicJson $receiptPath $receipt
}
try {
    New-Item -ItemType Directory -Path $executionRoot | Out-Null
    $counts.installerFreshSilentNoShortcut++
    Save-ExecutionCheckpoint "installer-attempted"
    Invoke-Checked $installerPath @("/S", "/NS", "/L=1033") "Universal isolated install"
    $installed = $true
    Wait-Until { (Test-Path -LiteralPath $applicationPath -PathType Leaf) -and (Test-Path -LiteralPath $uninstallerPath -PathType Leaf) } 30 "Universal application did not install."

    $oldArgs = [Environment]::GetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "Process")
    $oldProfile = [Environment]::GetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", "Process")
    try {
        [Environment]::SetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$CdpPort", "Process")
        [Environment]::SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", $webViewProfileRoot, "Process")
        $counts.appLaunch++
        Save-ExecutionCheckpoint "app-launch-attempted"
        $app = Start-Process -FilePath $applicationPath -PassThru
    }
    finally {
        [Environment]::SetEnvironmentVariable("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", $oldArgs, "Process")
        [Environment]::SetEnvironmentVariable("WEBVIEW2_USER_DATA_FOLDER", $oldProfile, "Process")
    }
    Wait-Until { (Get-PortRecord $CdpPort).listenerCount -eq 1 } 45 "Installed app did not open loopback CDP."
    $observerArguments = @(
        $nodeVerifier,
        "--cdp-endpoint=http://127.0.0.1:$CdpPort",
        "--output=$observerPath",
        "--runtime-ready-timeout-ms=300000",
        "--oauth-timeout-ms=600000",
        "--mode=$Mode"
    )
    if ($RunAuthenticatedUiMatrix) {
        $observerArguments += "--post-auth-hold-signal=$postAuthSignalPath"
        $oauthObserverProcess = Start-Process -FilePath (Get-Command node).Source -ArgumentList $observerArguments -PassThru -NoNewWindow
        $browserConsentAttempted = $false
        Wait-Until {
            $oauthObserverProcess.Refresh()
            if ($oauthObserverProcess.HasExited) { return $true }
            if (-not (Test-Path -LiteralPath $observerPath -PathType Leaf)) { return $false }
            try { $checkpoint = Get-Content -LiteralPath $observerPath -Raw | ConvertFrom-Json }
            catch { return $false }
            if ($AllowBrowserConsentAction -and -not $browserConsentAttempted -and $checkpoint.stage -ceq "oauth-attempted") {
                $browserConsentAttempted = $true
                $counts.browserAction++
                Save-ExecutionCheckpoint "browser-consent-attempted"
                $consentReceipt = Join-Path $executionRoot "browser-consent.json"
                & $browserConsentVerifier -OutputReceipt $consentReceipt -TimeoutSeconds 90 -Execute
                if ($LASTEXITCODE -ne 0) { throw "Bounded browser consent action failed." }
            }
            return ($checkpoint.stage -ceq "authenticated-ui-ready")
        } 900 "Installed-app OAuth observer did not expose an authenticated UI hold."
        $oauthObserverProcess.Refresh()
        if ($oauthObserverProcess.HasExited) {
            $null = Import-ObserverCheckpoint $observerPath $counts $receipt
            throw "Installed-app OAuth observer exited before authenticated UI validation."
        }

        $receipt["authenticatedUiCases"] = @()
        foreach ($case in $uiMatrix) {
            $caseReceiptPath = Join-Path $uiCaseRoot "$($case.id).json"
            & node $uiVerifier `
                "--cdp-endpoint=http://127.0.0.1:$CdpPort" `
                "--output=$caseReceiptPath" `
                "--screenshot-root=$uiScreenshotRoot" `
                "--case-id=$($case.id)" `
                "--locale=$($case.locale)" `
                "--edition=$($case.presentationEdition)" `
                "--width=$($case.width)" `
                "--height=$($case.height)" `
                "--emulate-viewport=true"
            if ($LASTEXITCODE -ne 0) { throw "Authenticated installed-app UI case $($case.id) failed." }
            $caseReceipt = Get-Content -LiteralPath $caseReceiptPath -Raw | ConvertFrom-Json
            if ($caseReceipt.kind -cne "dronedream-installed-universal-ui-case-receipt" -or
                $caseReceipt.caseId -cne $case.id -or
                $caseReceipt.locale -cne $case.locale -or
                $caseReceipt.presentationEdition -cne $case.presentationEdition -or
                -not $caseReceipt.presentationOnly -or $caseReceipt.grantsHardwareAuthority -or
                $caseReceipt.settingsOpenCount -ne 1 -or $caseReceipt.settingsTabActivationCount -ne 4 -or
                @($caseReceipt.screenshots.PSObject.Properties).Count -ne 2) {
                throw "Authenticated installed-app UI case $($case.id) produced an invalid receipt."
            }
            $counts.authenticatedUiCases++
            $counts.settingsOpen++
            $counts.settingsTabActivations += 4
            $counts.screenshots += 2
            $receipt.authenticatedUiCases += [ordered]@{
                caseId = $case.id
                receipt = Get-FileRecord $caseReceiptPath
                sceneScreenshotSha256 = $caseReceipt.screenshots.scene.sha256
                settingsScreenshotSha256 = $caseReceipt.screenshots.settings.sha256
            }
            Save-ExecutionCheckpoint "authenticated-ui-case-$($case.id)-completed"
        }
        Write-AtomicText $postAuthSignalPath "complete"
        Wait-Until { $oauthObserverProcess.Refresh(); $oauthObserverProcess.HasExited } 60 "Installed-app OAuth observer did not settle after authenticated UI validation."
        if ($oauthObserverProcess.ExitCode -ne 0) { throw "Installed-app OAuth observer failed after authenticated UI validation." }
        $oauthObserverProcess.Dispose(); $oauthObserverProcess = $null
    }
    else {
        & node @observerArguments
        if ($LASTEXITCODE -ne 0) { throw "Installed-app $Mode observer failed before its bounded outcome." }
    }
    $observation = Import-ObserverCheckpoint $observerPath $counts $receipt
    if ($runtimeDiagnosisOnly) {
        if (-not $observation.passed -or -not $observation.diagnosisComplete) { throw "Runtime observer did not produce one bounded diagnosis." }
        $counts.diagnosisSettlement = 1
        if ($counts.loginButton -ne 0 -or $counts.oauthTransaction -ne 0 -or $counts.callback -ne 0 -or $counts.authorizationCodeExchange -ne 0 -or $counts.browserAction -ne 0 -or $counts.localLogout -ne 0) {
            throw "Runtime diagnosis attempted a forbidden browser authentication action."
        }
        $receipt.runtimeEvidence = [ordered]@{
            runtimeReadyObserved = [bool]$observation.runtimeReadyObserved
            runtimeActionSettled = [bool]$observation.runtimeActionSettled
            runtimeFailureCode = $observation.runtimeFailureCode
            rawRuntimeErrorRecorded = $false
            credentialsRecorded = $false
        }
    }
    elseif (-not $observation.passed -or -not $observation.callbackSessionObserved -or -not $observation.localLogoutObserved) { throw "OAuth observer did not prove callback session and local logout." }

    if (-not $runtimeDiagnosisOnly) {
        $auditAfter = @(Get-AuditRecords)
        $oldHashes = @{}; foreach ($entry in $auditBefore) { $oldHashes[$entry.lineSha256] = $true }
        $newAudit = @($auditAfter | Where-Object { -not $oldHashes.ContainsKey($_.lineSha256) })
        $vaultProbe = @($newAudit | Where-Object { $_.value.result -ceq "no_saved_session" -and $_.value.callbackTransport -ceq "credential-vault" })
        $authorized = @($newAudit | Where-Object { $_.value.result -ceq "authorized" -and $_.value.callbackTransport -ceq "loopback-http" })
        $logout = @($newAudit | Where-Object { $_.value.result -ceq "local_logout" -and $_.value.callbackTransport -ceq "native-command" })
        if ($vaultProbe.Count -ne 1 -or $authorized.Count -ne 1 -or $logout.Count -ne 1) { throw "Native audit did not prove one empty-vault probe, authorized callback, and local logout." }
        $counts.credentialVaultRestoreProbe = 1
        if (-not $authorized[0].value.subjectHash) { throw "Authorized callback omitted the non-sensitive subject hash." }
        $counts.callback = 1
        $counts.authorizationCodeExchange = 1
        $receipt.authEvidence = [ordered]@{
            subjectHash = $authorized[0].value.subjectHash
            attemptIdHash = $authorized[0].value.attemptIdHash
            stateHash = $authorized[0].value.stateHash
            authorizedReceiptLineSha256 = $authorized[0].lineSha256
            logoutReceiptLineSha256 = $logout[0].lineSha256
            rawCallbackRecorded = $false
            credentialsRecorded = $false
        }
    }

    if ($app.HasExited) { throw "App exited before the bounded close action." }
    $counts.appClose++
    Save-ExecutionCheckpoint "app-close-attempted"
    $app.CloseMainWindow() | Out-Null
    Wait-Until { $app.HasExited } 15 "App did not close."
    $app.Dispose(); $app = $null
    $counts.isolatedUninstaller++
    Save-ExecutionCheckpoint "uninstaller-attempted"
    Invoke-Checked $uninstallerPath @("/S", "_?=$installDirectory") "Universal isolated uninstall"
    $uninstalled = $true
    Wait-Until { -not (Test-Path -LiteralPath $installDirectory) } 30 "Universal install root remained after uninstall."
    if ((Test-Path -LiteralPath $productKey) -or (Test-Path -LiteralPath $webViewProfileRoot)) {
        $counts.ownedCleanup++
        Save-ExecutionCheckpoint "owned-cleanup-attempted"
        if (Test-Path -LiteralPath $productKey) { Remove-Item -LiteralPath $productKey -Recurse -Force }
        if (Test-Path -LiteralPath $webViewProfileRoot) { Remove-Item -LiteralPath $webViewProfileRoot -Recurse -Force }
    }
    $cleaned = $true
    Wait-Until {
        ((Get-WslInventory | ConvertTo-Json -Depth 10 -Compress) -ceq ($protectedBefore.wslInventory | ConvertTo-Json -Depth 10 -Compress))
    } 60 "Existing Runtime did not return to its pre-run state after the app closed."
    $receipt.protectedStateAfter = Assert-ProtectedStateUnchanged $protectedBefore "Successful Universal OAuth validation"
    if ($counts.installerFreshSilentNoShortcut -ne 1 -or
        $counts.appLaunch -ne 1 -or
        $counts.runtimeStart -gt 1 -or
        $counts.diagnosisSettlement -gt 1 -or
        $counts.credentialVaultRestoreProbe -ne $(if ($runtimeDiagnosisOnly) { 0 } else { 1 }) -or
        $counts.loginButton -ne $(if ($runtimeDiagnosisOnly) { 0 } else { 1 }) -or
        $counts.oauthTransaction -ne $(if ($runtimeDiagnosisOnly) { 0 } else { 1 }) -or
        $counts.callback -ne $(if ($runtimeDiagnosisOnly) { 0 } else { 1 }) -or
        $counts.authorizationCodeExchange -ne $(if ($runtimeDiagnosisOnly) { 0 } else { 1 }) -or
        $counts.browserAction -ne $(if ($AllowBrowserConsentAction) { 1 } else { 0 }) -or
        $counts.localLogout -ne $(if ($runtimeDiagnosisOnly) { 0 } else { 1 }) -or
        $counts.authenticatedUiCases -ne $(if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count } else { 0 }) -or
        $counts.settingsOpen -ne $(if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count } else { 0 }) -or
        $counts.settingsTabActivations -ne $(if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count * 4 } else { 0 }) -or
        $counts.screenshots -ne $(if ($RunAuthenticatedUiMatrix) { $uiMatrix.Count * 2 } else { 0 }) -or
        $counts.appClose -ne 1 -or
        $counts.isolatedUninstaller -ne 1 -or
        $counts.ownedCleanup -gt 1) {
        throw "Universal OAuth execution counts drifted from the frozen bounded plan."
    }
    $receipt.passed = $true
}
catch {
    $receipt.failure = [ordered]@{ type = $_.Exception.GetType().FullName; message = $_.Exception.Message }
    throw
}
finally {
    if ($null -ne $oauthObserverProcess) {
        try {
            $oauthObserverProcess.Refresh()
            if (-not $oauthObserverProcess.HasExited) {
                if (-not (Test-Path -LiteralPath $postAuthSignalPath -PathType Leaf)) {
                    Write-AtomicText $postAuthSignalPath "abort"
                }
                try { Wait-Until { $oauthObserverProcess.Refresh(); $oauthObserverProcess.HasExited } 45 "OAuth observer did not settle after an authenticated UI abort." }
                catch {
                    $receipt["oauthObserverRecoveryError"] = $_.Exception.Message
                    Stop-Process -Id $oauthObserverProcess.Id -Force -ErrorAction SilentlyContinue
                    Wait-Until { $oauthObserverProcess.Refresh(); $oauthObserverProcess.HasExited } 10 "OAuth observer process remained after bounded recovery."
                }
            }
        }
        catch { $receipt["oauthObserverRecoveryError"] = $_.Exception.Message }
        finally { $oauthObserverProcess.Dispose(); $oauthObserverProcess = $null }
    }
    try { $null = Import-ObserverCheckpoint $observerPath $counts $receipt }
    catch { $receipt["observerCheckpointError"] = $_.Exception.Message }
    if ($null -ne $app) {
        try {
            if (-not $app.HasExited -and $counts.appClose -eq 0) {
                $counts.appClose++
                Save-ExecutionCheckpoint "app-close-recovery-attempted"
                $app.CloseMainWindow() | Out-Null
                Wait-Until { $app.HasExited } 15 "App recovery close failed."
            }
        }
        catch { $receipt.appCloseRecoveryError = $_.Exception.Message }
        $app.Dispose()
    }
    if ($installed -and -not $uninstalled -and (Test-Path -LiteralPath $uninstallerPath -PathType Leaf)) {
        try { $counts.isolatedUninstaller++; Save-ExecutionCheckpoint "uninstaller-recovery-attempted"; Invoke-Checked $uninstallerPath @("/S", "_?=$installDirectory") "Universal failure recovery uninstall"; $uninstalled = $true } catch { $receipt.uninstallRecoveryError = $_.Exception.Message }
    }
    if (-not $cleaned -and ((Test-Path -LiteralPath $productKey) -or (Test-Path -LiteralPath $webViewProfileRoot))) {
        try { $counts.ownedCleanup++; Save-ExecutionCheckpoint "owned-cleanup-recovery-attempted"; if (Test-Path -LiteralPath $productKey) { Remove-Item -LiteralPath $productKey -Recurse -Force }; if (Test-Path -LiteralPath $webViewProfileRoot) { Remove-Item -LiteralPath $webViewProfileRoot -Recurse -Force }; $cleaned = $true } catch { $receipt.ownedCleanupError = $_.Exception.Message }
    }
    $receipt.counts = $counts
    $receipt.protectedStateBefore = $protectedBefore
    if (-not $receipt.protectedStateAfter) {
        try { $receipt.protectedStateAfter = Assert-ProtectedStateUnchanged $protectedBefore "Final Universal OAuth validation" }
        catch { $receipt.protectedStateError = $_.Exception.Message; $receipt.protectedStateAfter = Get-ProtectedState }
    }
    $receipt.completedAt = [DateTime]::UtcNow.ToString("O")
    Write-AtomicJson $receiptPath $receipt
}

if ($runtimeDiagnosisOnly) {
    Write-Host "Universal Runtime diagnosis completed without browser authentication; no credentials or raw Runtime errors were recorded."
}
else {
    Write-Host "Universal real browser PKCE roundtrip passed with local-only logout; no credentials were read or recorded."
}
