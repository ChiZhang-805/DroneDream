$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$sourceRoot = "C:\Users\zju20\ddfedc7"
$runRoot = "C:\Users\zju20\.codex\visualizations\2026\08\05\019fd0e2-71cc-7742-bfab-612510f37c39\field-yellow-build-edc7aa1-frontend-dist-replacement"
$outputRoot = Join-Path $runRoot "artifact"
$cargoTarget = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\field-cargo-target\edc7aa1"
$expectedHead = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
$expectedEvidenceHead = "6219e731ebe70dbb1e550de9156437f30bf1e648"
$preflightReceipt = Join-Path $runRoot "preflight-receipt.json"
$expectedPreflightSha256 = "c6a9f35b96f39783e5150906a20254477ea59f63266d11b2e340f4a49668b092"
$configPath = Join-Path $runRoot "tauri-yellow-authorized.json"
$expectedOverlaySha256 = "dfbfddb4dc50f856f97f3f33112a9e62f0c1359a93afbfe950970e802961d586"
$stdoutPath = Join-Path $runRoot "build.stdout.log"
$stderrPath = Join-Path $runRoot "build.stderr.log"
$processReceiptPath = Join-Path $runRoot "build-process.json"
$failureReceiptPath = Join-Path $runRoot "build-failure-receipt.json"
$updaterKeyPath = "C:\Users\zju20\.tauri\dronedream-updater.key"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Get-Sha256Lower([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

Assert-Contract ((Get-Sha256Lower $preflightReceipt) -ceq $expectedPreflightSha256) `
    "Approved preflight receipt changed."
Assert-Contract ((Get-Sha256Lower $configPath) -ceq $expectedOverlaySha256) `
    "Approved Tauri authorization overlay changed."
$head = (& git -C $sourceRoot rev-parse HEAD).Trim()
$status = (& git -C $sourceRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
$remoteHead = (& git -C $sourceRoot rev-parse refs/remotes/origin/codex/software-field).Trim()
Assert-Contract ($head -ceq $expectedHead -and -not $status) `
    "Approved Field source is no longer exact and clean."
Assert-Contract ($remoteHead -ceq $expectedEvidenceHead) `
    "Approved Field upstream evidence head changed."
Assert-Contract (-not (Test-Path -LiteralPath $outputRoot)) `
    "Approved external OutputRoot is no longer empty."
Assert-Contract (-not (Test-Path -LiteralPath $cargoTarget)) `
    "Approved source-specific Cargo target is no longer empty."
Assert-Contract (Test-Path -LiteralPath $updaterKeyPath -PathType Leaf) `
    "Approved updater key path is unavailable."

$env:CARGO_NET_OFFLINE = "true"
$env:npm_config_offline = "true"
$env:CARGO_BUILD_JOBS = "2"
$env:DRONEDREAM_DESKTOP_EDITION_ID = "field"
$env:DRONEDREAM_EDITION_PROFILE = "field-lightweight"
$env:VITE_DRONEDREAM_EDITION = "field"
$env:DRONEDREAM_OAUTH_CLIENT_ID = "3140bbe2-5f0e-4699-8a9b-295d4030f853"
$env:TAURI_SIGNING_PRIVATE_KEY_PATH = $updaterKeyPath
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
$env:HTTP_PROXY = "http://127.0.0.1:9"
$env:HTTPS_PROXY = "http://127.0.0.1:9"
$env:ALL_PROXY = "http://127.0.0.1:9"
$env:NO_PROXY = ""
Remove-Item Env:TAURI_SIGNING_PRIVATE_KEY -ErrorAction SilentlyContinue
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:GOOGLE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY -ErrorAction SilentlyContinue

$candidateRoot = Join-Path $cargoTarget "x86_64-pc-windows-gnullvm\release\bundle\nsis"
$candidate = Join-Path $candidateRoot "DroneDream-Field_1.0.0_x64-setup.exe"
$candidateSignature = "$candidate.sig"
$candidateChecksum = "$candidate.sha256"
$candidateMetadata = Join-Path $candidateRoot "latest-field.json"
$frozenArtifact = Join-Path $outputRoot "DroneDream-Field-1.0.0.exe"
$frozenSignature = "$frozenArtifact.sig"
$frozenChecksum = "$frozenArtifact.sha256"
$frozenMetadata = Join-Path $outputRoot "latest-field.json"

$started = [DateTime]::UtcNow
$exitCode = 1
$exceptionText = $null
try {
    & (Join-Path $sourceRoot "desktop\scripts\build-windows-llvm.ps1") `
        -AdditionalConfigPath $configPath `
        -CargoTargetDir $cargoTarget `
        -ExpectedProductName "DroneDream-Field" `
        -EditionId field `
        -PreserveBundleHistory `
        1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE
} catch {
    $exceptionText = $_.Exception.Message
    ($_ | Out-String) | Add-Content -Encoding UTF8 -LiteralPath $stderrPath
    $exitCode = 1
}
$finished = [DateTime]::UtcNow

$candidateRecords = [ordered]@{}
foreach ($entry in ([ordered]@{
    installer = $candidate
    updaterSignature = $candidateSignature
    checksum = $candidateChecksum
    updaterMetadata = $candidateMetadata
}).GetEnumerator()) {
    $exists = Test-Path -LiteralPath $entry.Value -PathType Leaf
    $candidateRecords[$entry.Key] = [ordered]@{
        path = $entry.Value
        exists = $exists
        bytes = if ($exists) { (Get-Item -LiteralPath $entry.Value).Length } else { $null }
        sha256 = if ($exists) { Get-Sha256Lower $entry.Value } else { $null }
    }
}

$frozenRecords = [ordered]@{}
if ($candidateRecords.installer.exists) {
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
    Copy-Item -LiteralPath $candidate -Destination $frozenArtifact
    if ($candidateRecords.updaterSignature.exists) {
        Copy-Item -LiteralPath $candidateSignature -Destination $frozenSignature
    }
    if ($candidateRecords.updaterMetadata.exists) {
        Copy-Item -LiteralPath $candidateMetadata -Destination $frozenMetadata
    }
    $artifactSha = Get-Sha256Lower $frozenArtifact
    "$artifactSha  DroneDream-Field-1.0.0.exe" |
        Set-Content -Encoding ascii -LiteralPath $frozenChecksum
    foreach ($entry in ([ordered]@{
        installer = $frozenArtifact
        updaterSignature = $frozenSignature
        checksum = $frozenChecksum
        updaterMetadata = $frozenMetadata
    }).GetEnumerator()) {
        $exists = Test-Path -LiteralPath $entry.Value -PathType Leaf
        $frozenRecords[$entry.Key] = [ordered]@{
            path = $entry.Value
            exists = $exists
            bytes = if ($exists) { (Get-Item -LiteralPath $entry.Value).Length } else { $null }
            sha256 = if ($exists) { Get-Sha256Lower $entry.Value } else { $null }
        }
    }
}

$processReceipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-replacement-yellow-build-process"
    sourceCommit = $expectedHead
    upstreamEvidenceCommit = $expectedEvidenceHead
    startedAt = $started.ToString("o")
    finishedAt = $finished.ToString("o")
    durationSeconds = [Math]::Round(($finished - $started).TotalSeconds, 3)
    exitCode = $exitCode
    exception = $exceptionText
    cargoBuildCountMaximum = 1
    nsisInvocationMaximum = 1
    cargoBuildJobs = 2
    stdoutPath = $stdoutPath
    stderrPath = $stderrPath
    cargoTarget = $cargoTarget
    externalOutputRoot = $outputRoot
    candidate = $candidateRecords
    frozen = $frozenRecords
}
[IO.File]::WriteAllText(
    $processReceiptPath,
    (($processReceipt | ConvertTo-Json -Depth 10) + "`n"),
    [Text.UTF8Encoding]::new($false)
)

if ($exitCode -ne 0) {
    $failureReceipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-field-replacement-yellow-build-failure-receipt"
        sourceCommit = $expectedHead
        processReceiptPath = $processReceiptPath
        processReceiptSha256 = Get-Sha256Lower $processReceiptPath
        candidate = $candidateRecords
        frozen = $frozenRecords
        retryAllowed = $false
        releaseReady = $false
    }
    [IO.File]::WriteAllText(
        $failureReceiptPath,
        (($failureReceipt | ConvertTo-Json -Depth 10) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}
exit $exitCode
