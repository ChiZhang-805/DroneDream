param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ProductSourceCommit,

    [Parameter(Mandatory = $true)]
    [string]$CandidatePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$CargoTargetDir = (
        "$env:LOCALAPPDATA\DroneDream\codex-cache\universal-cargo-target"
    )
)

$ErrorActionPreference = "Stop"

function Invoke-GitText([string[]]$Arguments) {
    $output = (& git -C $repoRoot @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed"
    }
    return $output
}

function Get-FileSha256Lower([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Write-Utf8NoBom([string]$Path, [object]$Value) {
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        $Path,
        "$(ConvertTo-Json $Value -Depth 10)$([Environment]::NewLine)",
        $encoding
    )
}

function Assert-UnchangedFromProductSource([string]$RelativePath) {
    & git -C $repoRoot diff --quiet $ProductSourceCommit -- $RelativePath
    if ($LASTEXITCODE -ne 0) {
        throw "Finalizer input drifted from the product source: $RelativePath"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$branch = Invoke-GitText @("branch", "--show-current")
$toolHead = Invoke-GitText @("rev-parse", "--verify", "HEAD")
$sourceStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($branch -cne "codex/software" -or $sourceStatus) {
    throw "Universal candidate finalization requires clean codex/software."
}
& git -C $repoRoot cat-file -e "$ProductSourceCommit`^{commit}"
if ($LASTEXITCODE -ne 0) {
    throw "The requested Universal product source commit is unavailable."
}
& git -C $repoRoot merge-base --is-ancestor $ProductSourceCommit $toolHead
if ($LASTEXITCODE -ne 0) {
    throw "The finalizer head does not descend from the Universal product source."
}
foreach ($inputPath in @(
    "distribution/build-profiles/universal-1.0.0.v1.json",
    "desktop/src-tauri/tauri.universal.conf.json",
    "distribution/universal/release/website-exact-exe-handoff.v1.json"
)) {
    Assert-UnchangedFromProductSource $inputPath
}

$cargoTargetFull = [IO.Path]::GetFullPath($CargoTargetDir).TrimEnd('\', '/')
$candidateFull = [IO.Path]::GetFullPath($CandidatePath)
$expectedBundleDirectory = [IO.Path]::GetFullPath(
    (Join-Path $cargoTargetFull "x86_64-pc-windows-gnullvm\release\bundle\nsis")
).TrimEnd('\', '/')
if (-not $candidateFull.StartsWith(
    "$expectedBundleDirectory\",
    [StringComparison]::OrdinalIgnoreCase
) -or [IO.Path]::GetFileName($candidateFull) -cne
    "DroneDream-Universal_1.0.0_x64-setup.exe") {
    throw "The Universal candidate is outside the exact build target or has drifted identity."
}
if (-not (Test-Path -LiteralPath $candidateFull -PathType Leaf)) {
    throw "The source-bound Universal candidate is missing."
}
$candidateSignature = "${candidateFull}.sig"
$candidateChecksum = "${candidateFull}.sha256"
if (-not (Test-Path -LiteralPath $candidateSignature -PathType Leaf) -or
    -not (Test-Path -LiteralPath $candidateChecksum -PathType Leaf)) {
    throw "The Universal candidate signature or checksum is missing."
}

$failureReceiptPath = Join-Path $repoRoot (
    "artifacts\test-runs\universal-installer-postbuild-a1aeaf0-failure-receipt.json"
)
$failureReceipt = Get-Content -LiteralPath $failureReceiptPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$candidateSha = Get-FileSha256Lower $candidateFull
$candidateBytes = (Get-Item -LiteralPath $candidateFull).Length
$candidateSignatureSha = Get-FileSha256Lower $candidateSignature
$checksumClaim = (Get-Content -LiteralPath $candidateChecksum -Raw -Encoding ascii).Trim().Split(' ')[0]
if ($failureReceipt.executionSubject -cne $ProductSourceCommit -or
    $failureReceipt.buildCount -ne 1 -or
    $failureReceipt.handoff.rebuildProhibited -ne $true -or
    $failureReceipt.candidate.sha256 -cne $candidateSha -or
    $failureReceipt.candidate.bytes -ne $candidateBytes -or
    $failureReceipt.candidate.updaterSignatureSha256 -cne $candidateSignatureSha -or
    $checksumClaim -cne $candidateSha) {
    throw "The preserved Universal candidate no longer matches its failure receipt."
}

$engineManifestMatches = @()
Get-ChildItem -LiteralPath $cargoTargetFull -Recurse -Filter "engine-pack-manifest.json" `
    -File -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $document = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 |
                ConvertFrom-Json
        } catch {
            return
        }
        $digest = Get-FileSha256Lower $_.FullName
        if ($document.source.gitCommit -ceq $ProductSourceCommit -and
            $document.editionProfile.profileId -ceq "unified-sim-lab" -and
            $digest -ceq $failureReceipt.enginePack.manifestSha256 -and
            $document.packId -ceq $failureReceipt.enginePack.packId) {
            $engineManifestMatches += [pscustomobject]@{
                Path = $_.FullName
                Sha256 = $digest
                Document = $document
            }
        }
    }
if ($engineManifestMatches.Count -eq 0) {
    throw "No Engine Pack manifest matches the preserved Universal candidate receipt."
}
$engineManifest = $engineManifestMatches[0]
$enginePaths = @($engineManifest.Document.files.path)
$requiredEnginePaths = @(
    "distribution/editions/field.v1.json",
    "distribution/editions/lab.v1.json",
    "distribution/editions/sim.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/vehicle-packs/registry.v1.json"
)
if (@($requiredEnginePaths | Where-Object { $_ -notin $enginePaths }).Count -gt 0 -or
    @($enginePaths | Where-Object {
        $_ -eq "distribution/build-plans" -or
        $_.StartsWith("distribution/build-plans/", [StringComparison]::Ordinal) -or
        $_ -eq "distribution/tests" -or
        $_.StartsWith("distribution/tests/", [StringComparison]::Ordinal)
    }).Count -gt 0) {
    throw "The preserved candidate Engine Pack payload contract failed closed."
}

$allowedHandoffRoot = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream\handoffs")
).TrimEnd('\', '/')
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\', '/')
if (-not $outputRootFull.StartsWith(
    "$allowedHandoffRoot\",
    [StringComparison]::OrdinalIgnoreCase
) -or (Test-Path -LiteralPath $outputRootFull)) {
    throw "Universal handoff output must be a new directory under the owned handoff root."
}
$stagingRoot = "${outputRootFull}.staging-$([Guid]::NewGuid().ToString('N'))"
$artifactName = "DroneDream-Universal-1.0.0.exe"
$artifactPath = Join-Path $outputRootFull $artifactName
$signaturePath = "${artifactPath}.sig"
$checksumPath = "${artifactPath}.sha256"
$receiptPath = "${artifactPath}.receipt.json"
$manifestPath = Join-Path $outputRootFull "handoff-manifest.json"

try {
    New-Item -ItemType Directory -Path $stagingRoot | Out-Null
    $stagedArtifact = Join-Path $stagingRoot $artifactName
    $stagedSignature = "${stagedArtifact}.sig"
    $stagedChecksum = "${stagedArtifact}.sha256"
    $stagedReceipt = "${stagedArtifact}.receipt.json"
    $stagedManifest = Join-Path $stagingRoot "handoff-manifest.json"
    Copy-Item -LiteralPath $candidateFull -Destination $stagedArtifact
    Copy-Item -LiteralPath $candidateSignature -Destination $stagedSignature
    "$candidateSha  $artifactName" | Set-Content -Encoding ascii -LiteralPath $stagedChecksum
    $authenticode = Get-AuthenticodeSignature -LiteralPath $stagedArtifact
    $receipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-universal-candidate-handoff-receipt"
        state = "candidate-awaiting-isolated-red-lifecycle-validation"
        exactCleanProductSourceCommit = $ProductSourceCommit
        finalizerToolHead = $toolHead
        finalizerToolHeadIsProductSource = $false
        buildCount = 1
        artifact = [ordered]@{
            absolutePath = $artifactPath
            fileName = $artifactName
            version = "1.0.0"
            bytes = $candidateBytes
            sha256 = $candidateSha
            authenticodeStatus = [string]$authenticode.Status
        }
        updaterSignature = [ordered]@{
            absolutePath = $signaturePath
            bytes = (Get-Item -LiteralPath $stagedSignature).Length
            sha256 = Get-FileSha256Lower $stagedSignature
            state = "issued-by-tauri-signer"
        }
        checksum = [ordered]@{
            absolutePath = $checksumPath
            bytes = (Get-Item -LiteralPath $stagedChecksum).Length
            sha256 = Get-FileSha256Lower $stagedChecksum
        }
        enginePack = [ordered]@{
            profileCompatibilityId = "unified-sim-lab"
            payloadContractId = "dronedream-universal-engine-payload/v1"
            packId = [string]$engineManifest.Document.packId
            sourceCommit = [string]$engineManifest.Document.source.gitCommit
            manifestSha256 = [string]$engineManifest.Sha256
            fileCount = $enginePaths.Count
        }
        preservedFailureReceipt = [ordered]@{
            path = $failureReceiptPath
            sha256 = Get-FileSha256Lower $failureReceiptPath
        }
        lifecycle = [ordered]@{
            freshInstall = "pending-isolated-red-validation"
            upgrade = "pending-isolated-red-validation"
            uninstall = "pending-isolated-red-validation"
            shortcut = "pending-isolated-red-validation"
            webView2 = "pending-isolated-red-validation"
            locales = "pending-en-zh-red-validation"
        }
        releaseReady = $false
    }
    Write-Utf8NoBom $stagedReceipt $receipt
    $manifest = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-universal-candidate-handoff-manifest"
        exactCleanProductSourceCommit = $ProductSourceCommit
        finalizerToolHead = $toolHead
        buildCount = 1
        files = @(
            [ordered]@{path = $artifactPath; bytes = $candidateBytes; sha256 = $candidateSha},
            [ordered]@{path = $checksumPath; bytes = (Get-Item $stagedChecksum).Length; sha256 = Get-FileSha256Lower $stagedChecksum},
            [ordered]@{path = $signaturePath; bytes = (Get-Item $stagedSignature).Length; sha256 = Get-FileSha256Lower $stagedSignature},
            [ordered]@{path = $receiptPath; bytes = (Get-Item $stagedReceipt).Length; sha256 = Get-FileSha256Lower $stagedReceipt}
        )
        releaseReady = $false
    }
    Write-Utf8NoBom $stagedManifest $manifest
    Move-Item -LiteralPath $stagingRoot -Destination $outputRootFull
} catch {
    $stagingFull = [IO.Path]::GetFullPath($stagingRoot)
    if ($stagingFull.StartsWith(
        "$allowedHandoffRoot\",
        [StringComparison]::OrdinalIgnoreCase
    ) -and (Test-Path -LiteralPath $stagingFull)) {
        Remove-Item -LiteralPath $stagingFull -Recurse -Force
    }
    throw
}

[ordered]@{
    exactCleanProductSourceCommit = $ProductSourceCommit
    finalizerToolHead = $toolHead
    fileName = $artifactName
    bytes = $candidateBytes
    sha256 = $candidateSha
    updaterSignatureSha256 = Get-FileSha256Lower $signaturePath
    receiptPath = $receiptPath
    receiptSha256 = Get-FileSha256Lower $receiptPath
    manifestPath = $manifestPath
    manifestSha256 = Get-FileSha256Lower $manifestPath
    buildCount = 1
    releaseReady = $false
} | ConvertTo-Json -Depth 5
