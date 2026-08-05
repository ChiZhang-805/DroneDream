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

function Get-FileSha256Lower([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function New-RepoFileRef([string]$RelativePath) {
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Lab receipt input is missing: $RelativePath"
    }
    return [ordered]@{
        path = $RelativePath.Replace('\', '/')
        sha256 = Get-FileSha256Lower $path
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

$commonCoreCommit = "2aec69e88ee8844cff759a025f109e5b938d18c0"
$excludedPreviewEvidenceCommit = "e097b9ea057468bf1602ad1f1c4c5c5e88a65571"
Invoke-GitText @("cat-file", "-e", "$commonCoreCommit^{commit}") | Out-Null
Invoke-GitText @("cat-file", "-e", "$excludedPreviewEvidenceCommit^{commit}") | Out-Null
if ($commonCoreCommit -cnotmatch "^[0-9a-f]{40}$") {
    throw "Unable to freeze the Universal/Core product source commit."
}
if ($commonCoreCommit -ceq $excludedPreviewEvidenceCommit) {
    throw "Lab preview common-core product source must not use the Sim preview evidence commit."
}

& git -C $repoRoot merge-base --is-ancestor $commonCoreCommit HEAD
if ($LASTEXITCODE -ne 0) {
    throw "Lab preview source must descend from the Universal/Core product source baseline."
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
    kind = "dronedream-lab-preview-artifact-receipt"
    receiptVersion = "1.0.0"
    testOnly = $false
    editionId = "lab"
    productDisplayVersion = "1.0.0"
    sourceCommit = $sourceCommit
    branch = $branch
    commonCoreCommit = $commonCoreCommit
    commonCoreHash = $commonCoreHash
    editionManifest = New-RepoFileRef "distribution\editions\lab.v1.json"
    profile = New-RepoFileRef "distribution\build-profiles\lab-preview.v1.json"
    workspaces = [ordered]@{
        simulation = [ordered]@{
            workspaceId = "simulation"
            authority = "ui-workflow-only"
            allowedActions = @(
                "qualification.simulation.issue",
                "simulation.execute",
                "simulation.parameter.write",
                "simulation.vehicle.arm"
            )
            deniedHardwareActions = @(
                "hardware.parameter.write",
                "hardware.arm",
                "hardware.flight",
                "hardware.hitl.execute"
            )
        }
        hardwareLab = [ordered]@{
            workspaceId = "hardware-lab"
            authority = "ui-workflow-only"
            allowedActions = @(
                "hardware.discover",
                "hardware.parameter.read",
                "hardware.preflight.execute",
                "hardware.emergency-stop"
            )
            deniedHardwareActions = @(
                "hardware.parameter.write",
                "hardware.arm",
                "hardware.flight",
                "hardware.hitl.execute"
            )
        }
    }
    moduleGraph = [ordered]@{
        simulationPayload = @(
            "runtime-simulation",
            "simulator-gazebo-harmonic",
            "simulator-px4-sitl",
            "vehicle-pack-sim"
        )
        gatedHardwareAdapter = @(
            "hardware-bridge",
            "vehicle-pack-hardware",
            "vehicle-pack-validation"
        )
        vehiclePack = New-RepoFileRef "distribution\vehicle-packs\holybro-s500-v2-pixhawk6c.v1.json"
        controllerModel = "Pixhawk 6C"
        firmwareFamily = "px4"
        qualificationReceiptRequired = $true
    }
    payload = New-RepoFileRef "desktop\src-tauri\tauri.lab-preview.conf.json"
    licenseNotice = New-RepoFileRef "runtime\THIRD_PARTY_NOTICES.md"
    rollback = [ordered]@{
        policy = "previous-verified-promotion"
        targetArtifactSha256 = $null
        targetPromotionId = $null
    }
    upgrade = [ordered]@{
        requiresSameCommonCore = $true
        requiresManifestMatch = $true
        requiresRollback = $true
    }
    safety = [ordered]@{
        validatedVehiclePackCount = 0
        uiSwitchCountsAsAuthority = $false
        hardwareActionDecision = "deny"
        requiredDecisionLayers = @("native", "backend", "runtime")
    }
    artifact = [ordered]@{
        fileName = $artifactName
        path = $artifactPath.Replace($repoRoot, "").TrimStart('\', '/').Replace('\', '/')
        sha256 = Get-FileSha256Lower $artifactPath
        bytes = (Get-Item -LiteralPath $artifactPath).Length
        authenticode = [ordered]@{
            expected = "not-signed"
            observedStatus = [string]$signature.Status
        }
        tauriUpdaterSignature = "not-issued"
    }
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $receiptPath
Write-Host "Wrote unsigned Lab preview artifact $artifactPath"
Write-Host "Wrote Lab preview receipt $receiptPath"
