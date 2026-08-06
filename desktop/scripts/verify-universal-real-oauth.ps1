param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{40}$")][string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][ValidateRange(1, [long]::MaxValue)][long]$ExpectedBytes,
    [Parameter(Mandatory = $true)][string]$LifecycleReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedLifecycleReceiptSha256,
    [Parameter(Mandatory = $true)][string]$VisibleInstallerReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedVisibleInstallerReceiptSha256,
    [Parameter(Mandatory = $true)][string]$InstalledAppReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedInstalledAppReceiptSha256,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [ValidateRange(49152, 65535)][int]$CdpPort = 49321,
    [ValidatePattern("^$|^[0-9a-f]{64}$")][string]$ExpectedPlanSha256 = "",
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$lifecyclePath = (Resolve-Path -LiteralPath $LifecycleReceipt).Path
$visibleInstallerPath = (Resolve-Path -LiteralPath $VisibleInstallerReceipt).Path
$installedAppPath = (Resolve-Path -LiteralPath $InstalledAppReceipt).Path
$outputRootPath = [IO.Path]::GetFullPath($OutputRoot)
$validationRoot = Join-Path (Split-Path -Parent $installerPath) "validation"
$planPath = Join-Path $outputRootPath "universal-real-oauth-plan.json"
$executionRoot = Join-Path $outputRootPath "universal-real-oauth-red1"
$receiptPath = Join-Path $executionRoot "receipt.json"
$observerPath = Join-Path $executionRoot "app-observation.json"
$webViewProfileRoot = Join-Path $executionRoot "webview2-profile"
$nodeVerifier = Join-Path $repoRoot "frontend\scripts\verify-installed-universal-oauth.mjs"
$installDirectory = Join-Path $env:LOCALAPPDATA "DroneDream-Universal"
$applicationPath = Join-Path $installDirectory "drone-dream-desktop.exe"
$uninstallerPath = Join-Path $installDirectory "uninstall.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Universal"
$productKey = "HKCU:\Software\DroneDream\DroneDream-Universal"
$auditRoot = Join-Path $env:LOCALAPPDATA "io.dronedream.desktop.universal\audit\browser-auth"
$redirectUri = "http://127.0.0.1:49210/desktop-auth/universal/callback"

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
    $allowedStages = @("initialized", "connected", "runtime-start-attempted", "runtime-ready", "runtime-already-ready", "runtime-start-failed", "oauth-attempted", "local-logout-attempted", "completed")
    if ($observation.stage -notin $allowedStages) { throw "Installed-app OAuth observer checkpoint has an unknown stage." }
    $allowedRuntimeFailures = @($null, "runtime_service_unhealthy", "runtime_host_connectivity", "runtime_health_unknown", "runtime_operation_busy", "runtime_update_quiesce_active", "runtime_not_installed", "runtime_error_unclassified", "runtime_start_pending_timeout")
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
                lineSha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($encoded)).ToLowerInvariant()
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
$headed = Assert-Receipt $installedAppPath $ExpectedInstalledAppReceiptSha256 { param($d) $d.productSourceCommit -ceq $ProductSourceCommit -and $d.passed -eq $true } "Installed app"

if (-not (Test-Path -LiteralPath $nodeVerifier -PathType Leaf)) { throw "Installed-app OAuth observer is missing." }
if (-not $outputRootPath.StartsWith(([IO.Path]::GetFullPath($validationRoot) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) { throw "OutputRoot must be a new owned child of the artifact validation directory." }
if ((Get-PortRecord 49210).listenerCount -ne 0 -or (Get-PortRecord $CdpPort).listenerCount -ne 0) { throw "OAuth callback or CDP port is already occupied." }
if ((Test-Path -LiteralPath $installDirectory) -or (Test-Path -LiteralPath $uninstallKey) -or (Test-Path -LiteralPath $productKey)) { throw "Universal test identity is not isolated before planning." }

$runtimeInventory = @(Get-WslInventory)
$runtime = @($runtimeInventory | Where-Object { $_.name -ceq "DroneDreamRuntime" })
$runtimeRequired = $true
if ($runtime.Count -ne 1) { throw "The existing DroneDreamRuntime WSL distribution is unavailable; this plan cannot install or register one." }
$plan = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-real-oauth-plan"
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
    }
    auth = [ordered]@{
        editionId = "universal"
        authClientId = "dronedream-desktop-universal"
        protocolVersion = "desktop-browser-auth-pkce-v1"
        callback = [ordered]@{ uri = $redirectUri; port = 49210; listenerCount = 0 }
        existingBrowserCookieMayBeUsed = $true
        browserCredentialInputCap = 0
        browserPasswordStoreReadCap = 0
        nonCredentialAccountOrConsentActionCap = 1
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
        credentialVaultRestoreProbeMax = 1
        loginButton = 1
        oauthTransaction = 1
        callback = 1
        authorizationCodeExchange = 1
        localLogout = 1
        appClose = 1
        isolatedUninstaller = 1
        ownedCleanupMax = 1
    }
    portsAtPlan = @((Get-PortRecord 49210), (Get-PortRecord $CdpPort))
    resourcesAtPlan = Get-ResourceRecord
    protectedStateAtPlan = Get-ProtectedState
    failurePolicy = [ordered]@{
        retryCap = 0
        stopBeforeAnyCredentialInput = $true
        stopOnInstallOrMigrationSurface = $true
        stopOnUnexpectedBrowserOrCallback = $true
        rollbackWithOwnUninstallerOnly = $true
        preserveFailureEvidence = $true
    }
}

if (-not $Execute) {
    if (Test-Path -LiteralPath $outputRootPath) { throw "Refusing to overwrite an existing OAuth plan root." }
    Write-AtomicJson $planPath $plan
    Write-Host "Universal real OAuth plan frozen; no installer, app, Runtime, browser, auth, PX4, or Gazebo action ran."
    exit 0
}

if (-not $ExpectedPlanSha256) { throw "Execute requires ExpectedPlanSha256." }
$actualPlanSha = (Get-FileHash -LiteralPath $planPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPlanSha -cne $ExpectedPlanSha256) { throw "Frozen OAuth plan SHA drifted." }
if (Test-Path -LiteralPath $executionRoot) { throw "Refusing to overwrite an existing OAuth execution root." }

$counts = [ordered]@{ installerFreshSilentNoShortcut = 0; appLaunch = 0; runtimeStart = 0; credentialVaultRestoreProbe = 0; loginButton = 0; oauthTransaction = 0; callback = 0; authorizationCodeExchange = 0; localLogout = 0; appClose = 0; isolatedUninstaller = 0; ownedCleanup = 0 }
$receipt = [ordered]@{ schemaVersion = 1; kind = "dronedream-universal-real-oauth-receipt"; planSha256 = $ExpectedPlanSha256; productSourceCommit = $ProductSourceCommit; toolSourceCommit = $head; artifact = $artifact; startedAt = [DateTime]::UtcNow.ToString("O"); passed = $false; counts = $counts }
$app = $null
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
    & node $nodeVerifier "--cdp-endpoint=http://127.0.0.1:$CdpPort" "--output=$observerPath" "--runtime-ready-timeout-ms=300000" "--oauth-timeout-ms=600000"
    if ($LASTEXITCODE -ne 0) { throw "Installed-app OAuth observer failed or stopped before authorization." }
    $observation = Import-ObserverCheckpoint $observerPath $counts $receipt
    if (-not $observation.passed -or -not $observation.callbackSessionObserved -or -not $observation.localLogoutObserved) { throw "OAuth observer did not prove callback session and local logout." }

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
        $counts.credentialVaultRestoreProbe -ne 1 -or
        $counts.loginButton -ne 1 -or
        $counts.oauthTransaction -ne 1 -or
        $counts.callback -ne 1 -or
        $counts.authorizationCodeExchange -ne 1 -or
        $counts.localLogout -ne 1 -or
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

Write-Host "Universal real browser PKCE roundtrip passed with local-only logout; no credentials were read or recorded."
