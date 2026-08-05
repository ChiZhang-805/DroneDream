param(
    [switch]$Build,
    [string]$OutputRoot,
    [string]$CargoTargetDir
)

$ErrorActionPreference = "Stop"

function Invoke-GitText([string[]]$Arguments) {
    $output = (& git -C $repoRoot @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed"
    }
    return $output
}

function Get-Sha256Text([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceCommit = Invoke-GitText @("rev-parse", "--verify", "HEAD")
if ($sourceCommit -cnotmatch "^[0-9a-f]{40}$") {
    throw "Unable to freeze an exact Lab preview source commit."
}

$branch = Invoke-GitText @("branch", "--show-current")
if ($branch -cne "codex/software-lab") {
    throw "Lab preview builds must run from codex/software-lab."
}

$sourceStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($sourceStatus) {
    throw "Lab preview builds require an exact clean source tree."
}

$commonCoreCommit = Invoke-GitText @("rev-parse", "--verify", "origin/codex/software")
if ($commonCoreCommit -cnotmatch "^[0-9a-f]{40}$") {
    throw "Unable to freeze the observed Universal/Core commit."
}

& git -C $repoRoot merge-base --is-ancestor $commonCoreCommit HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Lab preview source must descend from the observed Universal/Core baseline."
}

if ($env:TAURI_SIGNING_PRIVATE_KEY_PATH -or $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD) {
    throw "Lab preview is unsigned; clear Tauri signing secret environment variables before building."
}

if (-not $CargoTargetDir) {
    $CargoTargetDir = Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache\lab-cargo-target"
}
$cargoTargetFull = [IO.Path]::GetFullPath($CargoTargetDir)
$repositoryTargetFull = [IO.Path]::GetFullPath((Join-Path $repoRoot "desktop\src-tauri\target"))
if ($cargoTargetFull.StartsWith($repositoryTargetFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Lab preview must not write the large Cargo target back into the repository."
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot ("artifacts\test-runs\lab-preview-{0}" -f $sourceCommit.Substring(0, 7))
}
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot)
$artifactName = "DroneDream-Lab-1.0.0.exe"
$artifactPath = Join-Path $outputRootFull $artifactName
$receiptPath = Join-Path $outputRootFull "lab-preview-receipt.json"

$corePaths = @("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")
$coreListing = (& git -C $repoRoot ls-tree -r --full-tree $commonCoreCommit -- @corePaths | Out-String)
if ($LASTEXITCODE -ne 0 -or -not $coreListing.Trim()) {
    throw "Unable to compute the Lab preview common-core hash."
}
$commonCoreHash = Get-Sha256Text $coreListing

if (-not $Build) {
    Write-Host "Lab preview contract verified for $sourceCommit; no EXE was built. Pass -Build to create the unsigned internal preview."
    exit 0
}

$env:CARGO_TARGET_DIR = $cargoTargetFull
$env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $sourceCommit
$env:DRONEDREAM_LAB_PREVIEW = "1"

& npm.cmd --prefix (Join-Path $repoRoot "desktop") run build -- `
    --config src-tauri/tauri.lab-preview.conf.json
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$postBuildCommit = Invoke-GitText @("rev-parse", "--verify", "HEAD")
$postBuildStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($postBuildCommit -cne $sourceCommit -or $postBuildStatus) {
    throw "Lab preview source changed while building."
}

$bundleDirectory = Join-Path $repoRoot "desktop\src-tauri\target\release\bundle\nsis"
$candidate = Get-ChildItem -LiteralPath $bundleDirectory -File -Filter "*.exe" |
    Where-Object { $_.Name -match "^DroneDream Lab_1\.0\.0_.*setup\.exe$" } |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if (-not $candidate) {
    throw "The Lab preview build completed without a Tauri NSIS installer."
}

New-Item -ItemType Directory -Force -Path $outputRootFull | Out-Null
Copy-Item -LiteralPath $candidate.FullName -Destination $artifactPath -Force
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $artifactPath
$signature = Get-AuthenticodeSignature -LiteralPath $artifactPath

$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-lab-preview-build-receipt"
    editionId = "lab"
    productDisplayVersion = "1.0.0"
    sourceCommit = $sourceCommit
    branch = $branch
    commonCoreCommit = $commonCoreCommit
    commonCoreHash = $commonCoreHash
    artifact = [ordered]@{
        fileName = $artifactName
        path = $artifactPath
        sha256 = $hash.Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $artifactPath).Length
        authenticode = [ordered]@{
            expected = "not-signed"
            observedStatus = [string]$signature.Status
        }
        tauriUpdaterSignature = "not-issued"
    }
    safety = [ordered]@{
        validatedVehiclePackCount = 0
        hardwareActionsFailClosed = $true
        requiredDecisionLayers = @("native", "backend", "runtime")
    }
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $receiptPath
Write-Host "Wrote unsigned Lab preview artifact $artifactPath"
Write-Host "Wrote Lab preview receipt $receiptPath"
