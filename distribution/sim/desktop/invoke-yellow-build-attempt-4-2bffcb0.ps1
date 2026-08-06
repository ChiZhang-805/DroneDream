[CmdletBinding()]
param(
    [ValidateSet("Plan", "Preflight", "Execute")]
    [string]$Mode = "Plan"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProductSource = "2bffcb0d26d080107144441f1c356f45dc4320ec"
$ProductTree = "3ed74a2299fe3b9e6ad83763b05fcf17952b0cfc"
$ApplicationName = "yellow-build-attempt-4-2bffcb0-application.v1.json"
$EvidenceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$ApplicationPath = Join-Path $PSScriptRoot $ApplicationName
$RunRoot = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-ordinal4-2bffcb0"
$SourceRoot = Join-Path $RunRoot "source"
$BundleRoot = Join-Path $RunRoot "bundle"
$ReceiptRoot = Join-Path $RunRoot "receipt"
$CargoTargetDir = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\sim-cargo-target"
$GeneratedInstaller = Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle\nsis\DroneDream-Sim_1.0.0_x64-setup.exe"
$GeneratedSignature = "$GeneratedInstaller.sig"
$FixedArtifact = Join-Path $BundleRoot "DroneDream-Sim-1.0.0.exe"
$FixedSignature = "$FixedArtifact.sig"
$FixedChecksum = "$FixedArtifact.sha256"
$BuildReceipt = Join-Path $ReceiptRoot "yellow-build-receipt.json"
$BuildLog = Join-Path $ReceiptRoot "build-transcript.log"
$AttemptLock = Join-Path $ReceiptRoot "attempt-lock.json"
$FrozenArtifact = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-20260806T120129Z-f24eb3a\bundle\DroneDream-Sim-1.0.0.exe"
$FrozenArtifactSha256 = "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece"
$SimRegistryPath = "Registry::HKEY_CURRENT_USER\Software\DroneDream\DroneDream-Sim"
$UpdaterKeyPath = "C:\Users\zju20\.tauri\dronedream-updater.key"
$OAuthClientId = "0c2ad943-a0cb-4a2f-9eda-eba44b7f58df"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-GitText {
    param([string[]]$Arguments)
    $output = (& git -C $EvidenceRoot @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: git -C <evidence-root> $($Arguments -join ' ')"
    }
    return $output
}

function Get-Sha256Lower {
    param([string]$LiteralPath)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Get-ResourceSnapshot {
    $computer = Get-CimInstance Win32_OperatingSystem
    $totalBytes = [double]$computer.TotalVisibleMemorySize * 1KB
    $freeBytes = [double]$computer.FreePhysicalMemory * 1KB
    $usedPercent = [Math]::Round((1 - ($freeBytes / $totalBytes)) * 100, 1)
    $heavy = @(
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -match '^(cargo|rustc|tauri|makensis|px4|gazebo)$' } |
            ForEach-Object { "$($_.ProcessName):$($_.Id)" }
    )
    $processor = Get-CimInstance Win32_Processor
    $cpuPercent = [Math]::Round((
        @($processor | ForEach-Object { [double]$_.LoadPercentage }) |
            Measure-Object -Average
    ).Average, 1)
    $diskC = Get-PSDrive -Name C
    $diskZ = Get-PSDrive -Name Z -ErrorAction SilentlyContinue
    return [ordered]@{
        memoryUsedPercent = $usedPercent
        memoryFreeBytes = [UInt64]$freeBytes
        cpuUsedPercent = $cpuPercent
        cFreeBytes = [UInt64]$diskC.Free
        zFreeBytes = if ($diskZ) { [UInt64]$diskZ.Free } else { 0 }
        heavyProcesses = $heavy
    }
}

function Get-PlanDocument {
    return [ordered]@{
        schemaVersion = 1
        mode = $Mode
        productSourceCommit = $ProductSource
        productSourceTree = $ProductTree
        checkout = [ordered]@{
            strategy = "git-worktree-add-detach-exact-commit"
            evidenceRoot = $EvidenceRoot
            sourceRoot = $SourceRoot
            sourceRootCreated = $false
            sourceMustBeClean = $true
        }
        ownedPaths = [ordered]@{
            runRoot = $RunRoot
            bundleRoot = $BundleRoot
            receiptRoot = $ReceiptRoot
            cargoTargetDir = $CargoTargetDir
            fixedArtifact = $FixedArtifact
            fixedSignature = $FixedSignature
            fixedChecksum = $FixedChecksum
            buildReceipt = $BuildReceipt
            buildLog = $BuildLog
        }
        invocationMaximums = [ordered]@{
            entryScript = 1
            frontend = 1
            tauri = 1
            cargo = 1
            nsis = 1
            retry = 0
        }
        environment = [ordered]@{
            inheritedWithoutPrinting = @(
                "VITE_SUPABASE_URL",
                "VITE_SUPABASE_PUBLISHABLE_KEY"
            )
            fixedPublicValues = @(
                "DRONEDREAM_DESKTOP_EDITION_ID=sim",
                "DRONEDREAM_EDITION_PROFILE=sim-only",
                "VITE_DRONEDREAM_EDITION=sim",
                "CARGO_BUILD_JOBS=2",
                "DRONEDREAM_OAUTH_CLIENT_ID=<approved-public-client-id>"
            )
            secretValuesPrinted = $false
        }
        protectedReadOnly = [ordered]@{
            frozenArtifact = $FrozenArtifact
            frozenArtifactSha256 = $FrozenArtifactSha256
            simRegistryPath = "HKCU/Software/DroneDream/DroneDream-Sim"
            cleanupAllowed = $false
        }
        mutationsPlanned = ($Mode -ceq "Execute")
    }
}

function Invoke-ReadOnlyPreflight {
    Assert-True (Test-Path -LiteralPath $ApplicationPath -PathType Leaf) "Application file is missing."
    $application = Get-Content -LiteralPath $ApplicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($application.sourceSeparation.productSourceCommit -ceq $ProductSource) "Application source commit drifted."
    Assert-True ($application.sourceSeparation.productSourceTree -ceq $ProductTree) "Application source tree drifted."

    $head = Invoke-GitText @("rev-parse", "HEAD")
    $status = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
    Assert-True (-not $status) "Evidence worktree must be clean."
    Assert-True ((Invoke-GitText @("rev-parse", $ProductSource)) -ceq $ProductSource) "Product source object is unavailable."
    Assert-True ((Invoke-GitText @("rev-parse", "$ProductSource`^{tree}")) -ceq $ProductTree) "Product source tree drifted."
    Assert-True (-not (Test-Path -LiteralPath $RunRoot)) "Owned run root already exists; retry is forbidden."
    Assert-True (-not (Test-Path -LiteralPath $SourceRoot)) "Detached source root already exists."

    $entryScript = $application.executionPlan.entryScript
    Assert-True ((Get-Item -LiteralPath $PSCommandPath).Length -eq $entryScript.bytes) "Entry script byte count drifted."
    Assert-True ((Get-Sha256Lower $PSCommandPath) -ceq $entryScript.sha256) "Entry script SHA-256 drifted."

    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$env:VITE_SUPABASE_URL)) "Approved public VITE_SUPABASE_URL is not injected."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$env:VITE_SUPABASE_PUBLISHABLE_KEY)) "Approved public VITE_SUPABASE_PUBLISHABLE_KEY is not injected."
    Assert-True (Test-Path -LiteralPath $UpdaterKeyPath -PathType Leaf) "Approved updater key path is unavailable."
    Assert-True (Test-Path -LiteralPath $FrozenArtifact -PathType Leaf) "Frozen historical artifact is missing."
    Assert-True ((Get-Sha256Lower $FrozenArtifact) -ceq $FrozenArtifactSha256) "Frozen historical artifact bytes drifted."

    $env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $ProductSource
    $env:DRONEDREAM_DESKTOP_EDITION_ID = "sim"
    $env:DRONEDREAM_OAUTH_CLIENT_ID = $OAuthClientId
    & node.exe (Join-Path $EvidenceRoot "desktop\scripts\verify-browser-auth-config.mjs") | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Public browser-auth configuration preflight failed."
    }

    $resources = Get-ResourceSnapshot
    Assert-True ($resources.memoryUsedPercent -lt 80) "Memory used is at or above 80 percent."
    Assert-True ($resources.memoryFreeBytes -ge 3GB) "Free memory is below 3 GiB."
    Assert-True ($resources.cFreeBytes -ge 10GB) "C drive free space is below 10 GiB."
    Assert-True ($resources.zFreeBytes -ge 5GB) "Z drive free space is below 5 GiB."
    Assert-True ($resources.heavyProcesses.Count -eq 0) "A heavy build or simulator process is already running."

    return [ordered]@{
        status = "pass"
        evidenceHead = $head
        productSourceCommit = $ProductSource
        productSourceTree = $ProductTree
        runRootAbsent = $true
        sourceRootAbsent = $true
        frozenArtifactSha256 = $FrozenArtifactSha256
        frozenArtifactReadOnly = $true
        simRegistryPresent = (Test-Path -LiteralPath $SimRegistryPath)
        simRegistryReadOnly = $true
        publicSupabaseVariablesPresent = $true
        publicSupabaseValuesRecorded = $false
        updaterKeyPresent = $true
        updaterKeyRead = $false
        resources = $resources
    }
}

function Write-JsonFile {
    param([object]$Document, [string]$LiteralPath)
    $Document | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $LiteralPath -Encoding UTF8
}

function Invoke-ExactBuild {
    $preflight = Invoke-ReadOnlyPreflight
    New-Item -ItemType Directory -Path $RunRoot | Out-Null
    New-Item -ItemType Directory -Path $BundleRoot, $ReceiptRoot | Out-Null
    Write-JsonFile ([ordered]@{
        productSourceCommit = $ProductSource
        globalAuthorizedCommandOrdinal = 4
        sourceApplicationPreflightOrdinal = 2
        priorSourceBuildInvocationCount = 0
        sourceBuildInvocationOrdinal = 1
        sourceBuildInvocationMaximum = 1
        retryAllowed = $false
        createdAtUtc = [DateTime]::UtcNow.ToString("o")
    }) $AttemptLock

    $startedAt = [DateTime]::UtcNow
    $frozenArtifactBefore = Get-Sha256Lower $FrozenArtifact
    $registryPresentBefore = Test-Path -LiteralPath $SimRegistryPath
    $buildDriverInvocations = 0
    $transcriptStarted = $false
    try {
        & git -C $EvidenceRoot worktree add --detach $SourceRoot $ProductSource
        if ($LASTEXITCODE -ne 0) {
            throw "Detached exact-source worktree creation failed."
        }
        $sourceHead = (& git -C $SourceRoot rev-parse HEAD).Trim()
        $sourceTree = (& git -C $SourceRoot rev-parse "HEAD^{tree}").Trim()
        $sourceStatus = (& git -C $SourceRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
        Assert-True ($sourceHead -ceq $ProductSource) "Detached source HEAD drifted."
        Assert-True ($sourceTree -ceq $ProductTree) "Detached source tree drifted."
        Assert-True (-not $sourceStatus) "Detached source is not clean."

        $env:DRONEDREAM_DESKTOP_EDITION_ID = "sim"
        $env:DRONEDREAM_EDITION_PROFILE = "sim-only"
        $env:VITE_DRONEDREAM_EDITION = "sim"
        $env:CARGO_BUILD_JOBS = "2"
        $env:CARGO_TARGET_DIR = $CargoTargetDir
        $env:DRONEDREAM_OAUTH_CLIENT_ID = $OAuthClientId
        $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $UpdaterKeyPath
        $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""

        Start-Transcript -LiteralPath $BuildLog -Force | Out-Null
        $transcriptStarted = $true
        $buildDriverInvocations = 1
        & (Join-Path $SourceRoot "desktop\scripts\build-windows-llvm.ps1") `
            -AdditionalConfigPath (Join-Path $SourceRoot "distribution\sim\desktop\tauri.sim.conf.json") `
            -CargoTargetDir $CargoTargetDir `
            -ExpectedProductName "DroneDream-Sim" `
            -EditionId "sim" `
            -PreserveBundleHistory

        Assert-True (Test-Path -LiteralPath $GeneratedInstaller -PathType Leaf) "Generated installer is missing."
        Assert-True (Test-Path -LiteralPath $GeneratedSignature -PathType Leaf) "Generated updater signature is missing."
        Assert-True ((Get-Item -LiteralPath $GeneratedInstaller).LastWriteTimeUtc -ge $startedAt.AddSeconds(-2)) "Generated installer was not refreshed by this attempt."
        Copy-Item -LiteralPath $GeneratedInstaller -Destination $FixedArtifact
        Copy-Item -LiteralPath $GeneratedSignature -Destination $FixedSignature
        $artifactSha256 = Get-Sha256Lower $FixedArtifact
        "$artifactSha256  DroneDream-Sim-1.0.0.exe" | Set-Content -LiteralPath $FixedChecksum -Encoding ASCII

        Assert-True ((Get-Sha256Lower $FrozenArtifact) -ceq $frozenArtifactBefore) "Frozen historical artifact was mutated."
        Assert-True ((Test-Path -LiteralPath $SimRegistryPath) -eq $registryPresentBefore) "Historical Sim registry presence changed."
        Write-JsonFile ([ordered]@{
            status = "success"
            productSourceCommit = $ProductSource
            productSourceTree = $ProductTree
            startedAtUtc = $startedAt.ToString("o")
            completedAtUtc = [DateTime]::UtcNow.ToString("o")
            invocationCounts = [ordered]@{
                buildDriver = $buildDriverInvocations
                frontendMaximum = 1
                tauriMaximum = 1
                cargoMaximum = 1
                nsisMaximum = 1
                retry = 0
            }
            artifact = [ordered]@{
                path = $FixedArtifact
                bytes = (Get-Item -LiteralPath $FixedArtifact).Length
                sha256 = $artifactSha256
                signaturePath = $FixedSignature
                signatureSha256 = Get-Sha256Lower $FixedSignature
            }
            protectedState = [ordered]@{
                frozenArtifactSha256Before = $frozenArtifactBefore
                frozenArtifactSha256After = Get-Sha256Lower $FrozenArtifact
                simRegistryPresentBefore = $registryPresentBefore
                simRegistryPresentAfter = Test-Path -LiteralPath $SimRegistryPath
                cleanupExecuted = $false
            }
            publicSupabaseValuesRecorded = $false
            updaterKeyReadOrCopied = $false
            preflight = $preflight
        }) $BuildReceipt
    } catch {
        if ($transcriptStarted) {
            Stop-Transcript | Out-Null
            $transcriptStarted = $false
        }
        Write-JsonFile ([ordered]@{
            status = "failed-frozen-no-retry"
            productSourceCommit = $ProductSource
            startedAtUtc = $startedAt.ToString("o")
            failedAtUtc = [DateTime]::UtcNow.ToString("o")
            failureType = $_.Exception.GetType().FullName
            failureMessage = $_.Exception.Message
            buildDriverInvocations = $buildDriverInvocations
            retryAllowed = $false
            runRootPreserved = $true
            publicSupabaseValuesRecorded = $false
            updaterKeyReadOrCopied = $false
        }) $BuildReceipt
        throw
    } finally {
        if ($transcriptStarted) {
            Stop-Transcript | Out-Null
        }
    }
}

switch ($Mode) {
    "Plan" {
        Get-PlanDocument | ConvertTo-Json -Depth 10
    }
    "Preflight" {
        Invoke-ReadOnlyPreflight | ConvertTo-Json -Depth 10
    }
    "Execute" {
        Invoke-ExactBuild
    }
}
