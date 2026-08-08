param(
    [switch]$Build,
    [string]$OutputRoot,
    [string]$CargoTargetDir,
    [string]$ExpectedSourceCommit,
    [ValidateSet("gnullvm")]
    [string]$Toolchain = "gnullvm"
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

$sourceBranch = "codex/software-lab"
if ($ExpectedSourceCommit) {
    if ($ExpectedSourceCommit -cnotmatch "^[0-9a-f]{40}$") {
        throw "ExpectedSourceCommit must be a full lowercase Git commit."
    }
    if ($sourceCommit -cne $ExpectedSourceCommit) {
        throw "Lab preview HEAD does not match ExpectedSourceCommit."
    }
}

$checkoutBranch = Invoke-GitText @("branch", "--show-current")
if ($checkoutBranch -ceq $sourceBranch) {
    $sourceCheckoutMode = "branch"
} elseif (-not $checkoutBranch -and $ExpectedSourceCommit -and $sourceCommit -ceq $ExpectedSourceCommit) {
    $sourceCheckoutMode = "detached-exact"
} else {
    throw "Lab preview builds require codex/software-lab or a detached exact ExpectedSourceCommit."
}

$sourceStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($sourceStatus) {
    throw "Lab preview builds require an exact clean source tree."
}

$commonCoreCommit = "e374d3f8d96b1265fcdb06864208b676566e94d9"
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

if (-not $CargoTargetDir) {
    $CargoTargetDir = Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache\lab-cargo-target"
}
$cargoTargetFull = [IO.Path]::GetFullPath($CargoTargetDir)
$repositoryTargetFull = [IO.Path]::GetFullPath((Join-Path $repoRoot "desktop\src-tauri\target"))
if ($cargoTargetFull.StartsWith($repositoryTargetFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Lab preview must not write the large Cargo target back into the repository."
}

$ownedOutputBase = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache\lab-build-attempts")
).TrimEnd('\', '/')
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ownedOutputBase ("lab-preview-{0}" -f $sourceCommit.Substring(0, 7))
}
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\', '/')
if ($outputRootFull -ceq $ownedOutputBase -or
    -not $outputRootFull.StartsWith(
        $ownedOutputBase + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Lab preview OutputRoot must be a descendant of the edition-owned build-attempts root."
}
$artifactName = "DroneDream-Lab-1.0.0.exe"
$tauriOverlayPath = Join-Path $repoRoot "desktop\src-tauri\tauri.lab-preview.conf.json"
try {
    $tauriOverlay = Get-Content -LiteralPath $tauriOverlayPath -Raw -Encoding UTF8 |
        ConvertFrom-Json
} catch {
    throw "The Lab Tauri overlay must be valid UTF-8 JSON."
}
$tauriProductName = [string]$tauriOverlay.productName
if (-not $tauriProductName) {
    throw "The Lab Tauri overlay productName is missing."
}
$tauriDisplayName = [string]$tauriOverlay.app.windows[0].title
if (-not $tauriDisplayName) {
    throw "The Lab Tauri overlay display title is missing."
}
$artifactPath = Join-Path $outputRootFull $artifactName
$artifactSignaturePath = "${artifactPath}.sig"
$receiptPath = Join-Path $outputRootFull "lab-preview-receipt.json"

$corePaths = @("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")
$coreListing = (& git -C $repoRoot ls-tree -r --full-tree $commonCoreCommit -- @corePaths | Out-String)
if ($LASTEXITCODE -ne 0 -or -not $coreListing.Trim()) {
    throw "Unable to compute the Lab preview common-core hash."
}
$coreListingCanonical = $coreListing.Replace("`r`n", "`n").Replace("`r", "`n").Trim()
$commonCoreHash = Get-Sha256Text $coreListingCanonical

if (-not $Build) {
    Write-Host "Lab preview contract verified for $sourceCommit with pinned $Toolchain; no EXE was built. Pass -Build to create the updater-signed, Authenticode-unsigned internal preview."
    exit 0
}

New-Item -ItemType Directory -Force -Path $ownedOutputBase | Out-Null
if (Test-Path -LiteralPath $outputRootFull) {
    if (-not (Test-Path -LiteralPath $outputRootFull -PathType Container) -or
        @(Get-ChildItem -LiteralPath $outputRootFull -Force).Count -ne 0) {
        throw "Lab preview OutputRoot must be a new or empty owned directory."
    }
} else {
    New-Item -ItemType Directory -Path $outputRootFull | Out-Null
}
$ownedBoundaryCursor = $outputRootFull
while ($ownedBoundaryCursor.Length -gt $ownedOutputBase.Length) {
    $ownedBoundaryItem = Get-Item -LiteralPath $ownedBoundaryCursor -Force
    if (($ownedBoundaryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Lab preview OutputRoot must not traverse a junction or symbolic link."
    }
    $ownedBoundaryCursor = Split-Path -Parent $ownedBoundaryCursor
}
$ownedOutputBaseResolved = (Resolve-Path -LiteralPath $ownedOutputBase).Path.TrimEnd('\', '/')
$outputRootResolved = (Resolve-Path -LiteralPath $outputRootFull).Path.TrimEnd('\', '/')
if ($outputRootResolved -ceq $ownedOutputBaseResolved -or
    -not $outputRootResolved.StartsWith(
        $ownedOutputBaseResolved + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Resolved Lab preview OutputRoot escaped the edition-owned build-attempts root."
}
$outputRootFull = $outputRootResolved
$artifactPath = Join-Path $outputRootFull $artifactName
$artifactSignaturePath = "${artifactPath}.sig"
$receiptPath = Join-Path $outputRootFull "lab-preview-receipt.json"

if (-not $env:TAURI_SIGNING_PRIVATE_KEY_PATH -or
    -not (Test-Path -LiteralPath $env:TAURI_SIGNING_PRIVATE_KEY_PATH -PathType Leaf)) {
    throw "Lab updater signing requires the controller-approved TAURI_SIGNING_PRIVATE_KEY_PATH."
}

$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python is required for the read-only Lab toolchain readiness gate."
}
$readinessTool = Join-Path $repoRoot "distribution\tools\lab_yellow_readiness_audit.py"
$readinessJson = (
    & $python.Source $readinessTool --expected-source-commit $sourceCommit |
        Out-String
)
if ($LASTEXITCODE -ne 0) {
    throw "The Lab YELLOW readiness audit failed before the build."
}
try {
    $readiness = $readinessJson | ConvertFrom-Json
} catch {
    throw "The Lab YELLOW readiness audit returned invalid JSON."
}
if (-not $readiness.yellowBuildRequest.requestable) {
    throw "The Lab YELLOW readiness gate is closed: $($readiness.yellowBuildRequest.requestBlockers -join '; ')"
}
if ($readiness.toolchain.selectedToolchain -cne $Toolchain) {
    throw "The Lab YELLOW readiness audit did not select the required pinned $Toolchain toolchain."
}
$gnullvm = $readiness.toolchain.candidates.gnullvm
if (-not $gnullvm.strictlyPinnedReady -or $gnullvm.requiresMsvcLinkExe) {
    throw "The pinned Lab gnullvm toolchain is not ready or unexpectedly requires MSVC link.exe."
}

$env:CARGO_TARGET_DIR = $cargoTargetFull
$env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $sourceCommit
$env:DRONEDREAM_LAB_PREVIEW = "1"
$env:DRONEDREAM_DESKTOP_EDITION_ID = "lab"
$env:DRONEDREAM_EDITION_PROFILE = "unified-sim-lab"
$env:VITE_DRONEDREAM_EDITION = "lab"
$env:VITE_DRONEDREAM_SOURCE_COMMIT = $sourceCommit

if (-not $env:DRONEDREAM_OAUTH_CLIENT_ID -or
    $env:DRONEDREAM_OAUTH_CLIENT_ID -match '\s' -or
    $env:DRONEDREAM_OAUTH_CLIENT_ID -like 'unregistered-*') {
    throw "Lab browser sign-in requires its registered public DRONEDREAM_OAUTH_CLIENT_ID."
}

& (Join-Path $repoRoot "desktop\scripts\build-windows-llvm.ps1") `
    -AdditionalConfigPath $tauriOverlayPath `
    -CargoTargetDir $cargoTargetFull `
    -LlvmRoot $gnullvm.llvmRoot `
    -ExpectedProductName $tauriProductName `
    -EditionId lab `
    -PreserveBundleHistory
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$postBuildCommit = Invoke-GitText @("rev-parse", "--verify", "HEAD")
$postBuildStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($postBuildCommit -cne $sourceCommit -or $postBuildStatus) {
    throw "Lab preview source changed while building."
}

$bundleDirectory = Join-Path $cargoTargetFull "x86_64-pc-windows-gnullvm\release\bundle\nsis"
$candidatePath = Join-Path $bundleDirectory "${tauriProductName}_1.0.0_x64-setup.exe"
if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf)) {
    throw "The Lab preview build completed without a Tauri NSIS installer."
}
$candidate = Get-Item -LiteralPath $candidatePath
$candidateSignaturePath = "${candidatePath}.sig"
if (-not (Test-Path -LiteralPath $candidateSignaturePath -PathType Leaf)) {
    throw "The Lab preview build completed without the required updater signature."
}

New-Item -ItemType Directory -Force -Path $outputRootFull | Out-Null
Copy-Item -LiteralPath $candidate.FullName -Destination $artifactPath -Force
Copy-Item -LiteralPath $candidateSignaturePath -Destination $artifactSignaturePath -Force
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $artifactPath
$signature = Get-AuthenticodeSignature -LiteralPath $artifactPath

$receipt = [ordered]@{
    schemaVersion = 2
    kind = "dronedream-lab-preview-artifact-receipt"
    receiptVersion = "1.1.0"
    testOnly = $false
    editionId = "lab"
    productDisplayVersion = "1.0.0"
    sourceCommit = $sourceCommit
    branch = $sourceBranch
    commonCoreCommit = $commonCoreCommit
    commonCoreHash = $commonCoreHash
    editionManifest = New-RepoFileRef "distribution\editions\lab.v1.json"
    profile = New-RepoFileRef "distribution\build-profiles\lab-preview.v1.json"
    websiteHandoffContract = New-RepoFileRef "distribution\schemas\lab-website-exact-exe-handoff.schema.json"
    brand = [ordered]@{
        displayName = $tauriDisplayName
        canonicalDonor = New-RepoFileRef "brand\brand-editions.v1.json"
        sourceManifest = New-RepoFileRef "distribution\editions\lab\brand-source-manifest.v1.json"
        mark = New-RepoFileRef "distribution\editions\lab\assets\dronedream-lab-mark-v2.png"
        dotLockup = New-RepoFileRef "brand\generated\lab\lockup-compact.png"
        installerIcon = New-RepoFileRef "brand\generated\lab\windows\icon.ico"
        grantsHardwareAuthority = $false
    }
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
            "managed-protocol-adapters",
            "recorded-evidence-harness",
            "parameter-snapshot-rollback",
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
    artifactRoot = [ordered]@{
        representation = "relative-to-receipt-parent"
        ownership = "edition-owned-output-root"
    }
    artifact = [ordered]@{
        fileName = $artifactName
        path = $artifactName
        sha256 = Get-FileSha256Lower $artifactPath
        bytes = (Get-Item -LiteralPath $artifactPath).Length
        authenticode = [ordered]@{
            expected = "not-signed"
            observedStatus = [string]$signature.Status
        }
        tauriUpdaterSignature = [ordered]@{
            state = "issued"
            path = "${artifactName}.sig"
            sha256 = Get-FileSha256Lower $artifactSignaturePath
            keyId = "BA3FDCAF71CE2FF5"
        }
    }
}
$receiptJson = ($receipt | ConvertTo-Json -Depth 8) + "`n"
$utf8NoBom = New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText($receiptPath, $receiptJson, $utf8NoBom)
Write-Host "Wrote Authenticode-unsigned Lab preview artifact $artifactPath"
Write-Host "Wrote Lab updater signature $artifactSignaturePath"
Write-Host "Wrote Lab preview receipt $receiptPath"
