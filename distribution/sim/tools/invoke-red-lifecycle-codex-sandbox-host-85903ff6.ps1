[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedToolHead,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedLauncherSha256,

    [Parameter(Mandatory = $true)]
    [string]$ApplicationPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedApplicationSha256,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long]$ExpectedApplicationBytes,

    [ValidateSet("Plan", "StageAndRunAs")]
    [string]$Mode = "Plan"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$launcherPath = (Resolve-Path -LiteralPath $MyInvocation.MyCommand.Path).Path
$applicationFull = (Resolve-Path -LiteralPath $ApplicationPath).Path
$application = Get-Content -LiteralPath $applicationFull -Raw | ConvertFrom-Json
$expectedUserName = "CodexSandboxOffline"
$expectedUserSid = "S-1-5-21-2197768555-4123441877-442284878-1020"
$expectedUserProfile = "C:\Users\CodexSandboxOffline"
$executionOrdinal = [int]$application.executionOrdinal
if ($executionOrdinal -lt 1) {
    throw "Lifecycle application execution ordinal is invalid."
}
$expectedSharedRoot = "C:\Users\Public\Documents\DroneDream-Codex\Sim-RED\sim-red-final-85903ff6-ordinal$executionOrdinal"
$sharedRoot = [IO.Path]::GetFullPath([string]$application.ownedSurface.sharedRoot)
$sharedToolRoot = Join-Path $sharedRoot "tool"
$sharedIntakeRoot = Join-Path $sharedRoot "intake"
$sharedApplication = Join-Path $sharedToolRoot (Split-Path -Leaf $applicationFull)
$sharedGuestRunner = Join-Path $sharedToolRoot "invoke-red-lifecycle-codex-sandbox-85903ff6.ps1"
$sharedContract = Join-Path $sharedToolRoot "edition-installer-lifecycle-contract.ps1"
$sharedStaticAcceptance = Join-Path $sharedToolRoot "yellow-build-attempt-21-573e8f9-static-accepted.v1.json"
$sharedArtifact = Join-Path $sharedIntakeRoot "DroneDream-Sim-1.0.0.exe"

function Get-ExactFileRecord {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[0-9a-f]{64}$")]
        [string]$ExpectedSha256,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, [long]::MaxValue)]
        [long]$ExpectedBytes
    )

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $item = Get-Item -LiteralPath $resolved
    $sha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([long]$item.Length -ne $ExpectedBytes -or $sha256 -cne $ExpectedSha256) {
        throw "Frozen file identity drifted: $resolved"
    }
    return [ordered]@{ path = $resolved; bytes = [long]$item.Length; sha256 = $sha256 }
}

function Assert-OrdinaryDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Expected an ordinary directory: $Path"
    }
}

function Get-HostFileRecord {
    param([Parameter(Mandatory = $true)][string]$Path)

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

function Get-HostRegistryRecord {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ path = $Path; exists = $false; values = [ordered]@{} }
    }
    $properties = Get-ItemProperty -LiteralPath $Path
    $values = [ordered]@{}
    foreach ($property in @($properties.PSObject.Properties | Sort-Object Name)) {
        if ($property.Name -match '^PS') { continue }
        $values[$property.Name] = if ($null -eq $property.Value) { $null } else { [string]$property.Value }
    }
    return [ordered]@{ path = $Path; exists = $true; values = $values }
}

function Get-HostShortcutRecord {
    param([Parameter(Mandatory = $true)][string]$Path)

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

function Get-HostProtectedState {
    $displayName = "DroneDream $([char]0x00B7) SIM"
    $desktop = [Environment]::GetFolderPath("Desktop")
    $programs = [Environment]::GetFolderPath("Programs")
    $installRoot = Join-Path $env:LOCALAPPDATA "DroneDream-Sim"
    return [ordered]@{
        userName = $env:USERNAME
        userProfile = $env:USERPROFILE
        simApplication = Get-HostFileRecord -Path (Join-Path $installRoot "drone-dream-desktop.exe")
        simUninstaller = Get-HostFileRecord -Path (Join-Path $installRoot "uninstall.exe")
        simUninstallKey = Get-HostRegistryRecord -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Sim"
        simProductKey = Get-HostRegistryRecord -Path "HKCU:\Software\DroneDream\DroneDream-Sim"
        simDesktopShortcut = Get-HostShortcutRecord -Path (Join-Path $desktop "$displayName.lnk")
        simStartMenuShortcut = Get-HostShortcutRecord -Path (Join-Path $programs "$displayName.lnk")
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
    }
}

function ConvertTo-CanonicalJson {
    param([Parameter(Mandatory = $true)][object]$Value)
    return $Value | ConvertTo-Json -Depth 30 -Compress
}

$head = (& git -C $repoRoot rev-parse HEAD).Trim()
$upstream = (& git -C $repoRoot rev-parse '@{upstream}').Trim()
$dirty = @(& git -C $repoRoot status --porcelain)
if ($head -cne $ExpectedToolHead -or $upstream -cne $ExpectedToolHead -or $dirty.Count -ne 0) {
    throw "Git HEAD/upstream/clean lifecycle application identity drifted."
}

$launcher = Get-ExactFileRecord `
    -Path $launcherPath `
    -ExpectedSha256 $ExpectedLauncherSha256 `
    -ExpectedBytes ([long]$application.toolBundle.hostLauncherBytes)
$applicationRecord = Get-ExactFileRecord `
    -Path $applicationFull `
    -ExpectedSha256 $ExpectedApplicationSha256 `
    -ExpectedBytes $ExpectedApplicationBytes

if ([string]$application.editionId -cne "sim" -or
    [string]$application.state -cne "awaiting-user-present-start" -or
    [int]$application.executionOrdinal -ne $executionOrdinal -or
    [string]$application.sourceSeparation.productSourceCommit -cne "573e8f991eba703bbfd6c4b35f464fbaab78903c" -or
    [string]$application.artifact.sha256 -cne "85903ff6a5dad93224f5396096d90f2e96e71eb5e68980df7ca2691d8001ddae" -or
    [long]$application.artifact.bytes -ne 12070633 -or
    [string]$application.disposableWindowsUser.userName -cne $expectedUserName -or
    [string]$application.disposableWindowsUser.sid -cne $expectedUserSid -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath([string]$application.disposableWindowsUser.profile).TrimEnd("\"),
        [IO.Path]::GetFullPath($expectedUserProfile).TrimEnd("\"),
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    [string]$application.toolBundle.hostLauncherSha256 -cne $ExpectedLauncherSha256 -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath([string]$application.ownedSurface.sharedRoot).TrimEnd("\"),
        [IO.Path]::GetFullPath($expectedSharedRoot).TrimEnd("\"),
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Lifecycle application contract drifted."
}

$sourceFiles = [ordered]@{
    artifact = Get-ExactFileRecord `
        -Path ([string]$application.artifact.absolutePath) `
        -ExpectedSha256 ([string]$application.artifact.sha256) `
        -ExpectedBytes ([long]$application.artifact.bytes)
    guestRunner = Get-ExactFileRecord `
        -Path (Join-Path $repoRoot ([string]$application.toolBundle.guestRunnerPath)) `
        -ExpectedSha256 ([string]$application.toolBundle.guestRunnerSha256) `
        -ExpectedBytes ([long]$application.toolBundle.guestRunnerBytes)
    contract = Get-ExactFileRecord `
        -Path (Join-Path $repoRoot ([string]$application.toolBundle.contractPath)) `
        -ExpectedSha256 ([string]$application.toolBundle.contractSha256) `
        -ExpectedBytes ([long]$application.toolBundle.contractBytes)
    staticAcceptance = Get-ExactFileRecord `
        -Path (Join-Path $repoRoot ([string]$application.toolBundle.staticAcceptancePath)) `
        -ExpectedSha256 ([string]$application.toolBundle.staticAcceptanceSha256) `
        -ExpectedBytes ([long]$application.toolBundle.staticAcceptanceBytes)
}

$localUser = Get-LocalUser -Name $expectedUserName -ErrorAction Stop
if (-not $localUser.Enabled -or $localUser.SID.Value -cne $expectedUserSid) {
    throw "The disposable Windows user identity is absent, disabled, or changed."
}
$profileRegistry = "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\$expectedUserSid"
$profilePath = [string](Get-ItemProperty -LiteralPath $profileRegistry -ErrorAction Stop).ProfileImagePath
if (-not [string]::Equals(
        [IO.Path]::GetFullPath($profilePath).TrimEnd("\"),
        [IO.Path]::GetFullPath($expectedUserProfile).TrimEnd("\"),
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "The disposable Windows user profile path changed."
}
$profileHiveLoaded = Test-Path -LiteralPath "Registry::HKEY_USERS\$expectedUserSid"
$profileState = if ($profileHiveLoaded) { "loaded" } else { "unloaded-or-inaccessible" }
Assert-OrdinaryDirectory -Path "C:\Users\Public"
Assert-OrdinaryDirectory -Path "C:\Users\Public\Documents"

$conflictingLifecycleProcesses = @(
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.Name -in @("powershell.exe", "runas.exe") -and
            $_.CommandLine -match "CodexSandboxOffline" -and
            $_.CommandLine -match "(Lab-RED|Field-RED|Sim-RED)"
        } |
        Select-Object ProcessId, ParentProcessId, Name
)
if ($Mode -ceq "StageAndRunAs" -and $conflictingLifecycleProcesses.Count -ne 0) {
    throw "CodexSandboxOffline is occupied by another Edition lifecycle process; refusing concurrent staging or install."
}

if (Test-Path -LiteralPath $sharedRoot) {
    throw "The exact lifecycle shared root already exists; refusing reuse."
}

$plan = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-sim-codex-sandbox-host-plan"
    mode = $Mode
    toolEvidenceHead = $ExpectedToolHead
    launcher = $launcher
    application = $applicationRecord
    artifact = $sourceFiles.artifact
    disposableWindowsUser = [ordered]@{
        userName = $expectedUserName
        sid = $expectedUserSid
        profile = $expectedUserProfile
        profileState = $profileState
        conflictingLifecycleProcessCount = $conflictingLifecycleProcesses.Count
        enabled = $true
        passwordReadRecordedOrTransmitted = $false
    }
    ownedSurface = [ordered]@{
        sharedRoot = $sharedRoot
        sharedRootExists = $false
        canonicalCurrentUserSimInstallTouched = $false
    }
    exactCounts = [ordered]@{
        hostLauncher = if ($Mode -ceq "StageAndRunAs") { 1 } else { 0 }
        runAsInteractivePrompts = if ($Mode -ceq "StageAndRunAs") { 1 } else { 0 }
        freshInstallerInvocations = 0
        overlayInstallerInvocations = 0
        applicationLaunches = 0
        uninstallerInvocations = 0
        builds = 0
        retries = 0
        passwordReads = 0
        systemFeatureChanges = 0
    }
    executionStarted = $false
}

if ($Mode -ceq "Plan") {
    $plan | ConvertTo-Json -Depth 20
    exit 0
}

New-Item -ItemType Directory -Path $sharedToolRoot -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path $sharedIntakeRoot -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath $sourceFiles.artifact.path -Destination $sharedArtifact -ErrorAction Stop
Copy-Item -LiteralPath $sourceFiles.guestRunner.path -Destination $sharedGuestRunner -ErrorAction Stop
Copy-Item -LiteralPath $sourceFiles.contract.path -Destination $sharedContract -ErrorAction Stop
Copy-Item -LiteralPath $sourceFiles.staticAcceptance.path -Destination $sharedStaticAcceptance -ErrorAction Stop
Copy-Item -LiteralPath $applicationFull -Destination $sharedApplication -ErrorAction Stop

Get-ExactFileRecord -Path $sharedArtifact -ExpectedSha256 $sourceFiles.artifact.sha256 -ExpectedBytes $sourceFiles.artifact.bytes | Out-Null
Get-ExactFileRecord -Path $sharedGuestRunner -ExpectedSha256 $sourceFiles.guestRunner.sha256 -ExpectedBytes $sourceFiles.guestRunner.bytes | Out-Null
Get-ExactFileRecord -Path $sharedContract -ExpectedSha256 $sourceFiles.contract.sha256 -ExpectedBytes $sourceFiles.contract.bytes | Out-Null
Get-ExactFileRecord -Path $sharedStaticAcceptance -ExpectedSha256 $sourceFiles.staticAcceptance.sha256 -ExpectedBytes $sourceFiles.staticAcceptance.bytes | Out-Null
Get-ExactFileRecord -Path $sharedApplication -ExpectedSha256 $ExpectedApplicationSha256 -ExpectedBytes $ExpectedApplicationBytes | Out-Null

$hostProtectedBefore = Get-HostProtectedState
$hostEvidenceRoot = Join-Path $sharedRoot "host-evidence"
New-Item -ItemType Directory -Path $hostEvidenceRoot -ErrorAction Stop | Out-Null
$hostSnapshotPath = Join-Path $hostEvidenceRoot "canonical-current-user-protected-state-before.json"
[IO.File]::WriteAllText(
    $hostSnapshotPath,
    ($hostProtectedBefore | ConvertTo-Json -Depth 30),
    [Text.UTF8Encoding]::new($false)
)

$powerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$guestCommand = "$powerShell -NoProfile -ExecutionPolicy Bypass -File $sharedGuestRunner -ExpectedToolHead $ExpectedToolHead -ExpectedScriptSha256 $($sourceFiles.guestRunner.sha256) -ApplicationPath $sharedApplication -ExpectedApplicationSha256 $ExpectedApplicationSha256 -ExpectedApplicationBytes $ExpectedApplicationBytes -Mode Execute"
$runAsArguments = @("/profile", "/user:.\$expectedUserName", $guestCommand)
$runAsExitCode = $null
$guestReceiptPath = Join-Path $sharedRoot "execution\evidence\lifecycle-receipt.json"
try {
    & "$env:SystemRoot\System32\runas.exe" @runAsArguments
    $runAsExitCode = $LASTEXITCODE
    if ($runAsExitCode -ne 0) {
        throw "Interactive runas lifecycle process failed with exit code $runAsExitCode."
    }
    $deadline = [DateTime]::UtcNow.AddMinutes(20)
    while (-not (Test-Path -LiteralPath $guestReceiptPath -PathType Leaf) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 2
    }
    if (-not (Test-Path -LiteralPath $guestReceiptPath -PathType Leaf)) {
        throw "The disposable-user lifecycle receipt did not appear within 20 minutes."
    }
    $guestReceipt = Get-Content -LiteralPath $guestReceiptPath -Raw | ConvertFrom-Json
    if (-not [bool]$guestReceipt.success) {
        throw "The disposable-user lifecycle receipt reports failure."
    }
}
finally {
    $hostProtectedAfter = Get-HostProtectedState
    $hostParity = (ConvertTo-CanonicalJson $hostProtectedBefore) -ceq (ConvertTo-CanonicalJson $hostProtectedAfter)
    $hostReceipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-sim-codex-sandbox-host-protection-receipt"
        toolEvidenceHead = $ExpectedToolHead
        runAsExitCode = $runAsExitCode
        guestReceiptPath = $guestReceiptPath
        canonicalCurrentUserProtectedStateUnchanged = $hostParity
        passwordReadRecordedOrTransmitted = $false
        systemFeaturesChanged = $false
        protectedStateBefore = $hostProtectedBefore
        protectedStateAfter = $hostProtectedAfter
    }
    [IO.File]::WriteAllText(
        (Join-Path $hostEvidenceRoot "canonical-current-user-protection-receipt.json"),
        ($hostReceipt | ConvertTo-Json -Depth 30),
        [Text.UTF8Encoding]::new($false)
    )
    if (-not $hostParity) {
        throw "Canonical current-user Sim/Runtime state changed during disposable-user lifecycle execution."
    }
}

Write-Host "CodexSandboxOffline lifecycle command completed; inspect the shared evidence receipt before any release claim."
