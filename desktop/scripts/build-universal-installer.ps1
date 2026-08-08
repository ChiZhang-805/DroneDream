param(
    [switch]$Build,
    [string]$ExpectedSourceCommit,
    [string]$OutputRoot,
    [string]$CargoTargetDir,
    [string]$LlvmRoot
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

function Get-StringSha256Lower([string]$Value) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString(
            $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
        )).Replace("-", "").ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function New-RepoFileRef([string]$RelativePath) {
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Universal build input is missing: $RelativePath"
    }
    return [ordered]@{
        path = $RelativePath.Replace('\', '/')
        sha256 = Get-FileSha256Lower $path
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceCommit = Invoke-GitText @("rev-parse", "--verify", "HEAD")
if ($sourceCommit -cnotmatch "^[0-9a-f]{40}$") {
    throw "Unable to freeze an exact Universal source commit."
}
if ($ExpectedSourceCommit -and $ExpectedSourceCommit -cnotmatch "^[0-9a-f]{40}$") {
    throw "ExpectedSourceCommit must be a full lowercase Git SHA."
}
if ($ExpectedSourceCommit -and $ExpectedSourceCommit -cne $sourceCommit) {
    throw "Universal HEAD does not match ExpectedSourceCommit."
}
if ($Build -and -not $ExpectedSourceCommit) {
    throw "Universal builds require an explicit -ExpectedSourceCommit pin."
}
$branch = Invoke-GitText @("branch", "--show-current")
if ($branch -cne "codex/software") {
    throw "Universal builds must run from codex/software."
}
$sourceStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($sourceStatus) {
    throw "Universal builds require an exact clean source tree."
}

$profilePath = Join-Path $repoRoot "distribution\build-profiles\universal-1.0.0.v1.json"
$overlayPath = Join-Path $repoRoot "desktop\src-tauri\tauri.universal.conf.json"
$coexistencePath = Join-Path $repoRoot "distribution\desktop\edition-coexistence.v1.json"
$browserAuthPath = Join-Path $repoRoot "distribution\desktop\edition-browser-auth.v1.json"
$runtimeFamiliesPath = Join-Path $repoRoot "distribution\desktop\edition-runtime-update-families.v1.json"
$profile = Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8 | ConvertFrom-Json
$overlay = Get-Content -LiteralPath $overlayPath -Raw -Encoding UTF8 | ConvertFrom-Json
$coexistence = Get-Content -LiteralPath $coexistencePath -Raw -Encoding UTF8 | ConvertFrom-Json
$browserAuth = Get-Content -LiteralPath $browserAuthPath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeFamilies = Get-Content -LiteralPath $runtimeFamiliesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sharedUi = $profile.sharedUiContract
$vehicleStudio = $profile.universalExclusiveCapabilities.vehicleStudio
if ($profile.artifactFileName -cne "DroneDream-Universal-1.0.0.exe" -or
    $overlay.productName -cne "DroneDream-Universal" -or
    $profile.enginePackProfile -cne "unified-sim-lab" -or
    $profile.desktopContracts.coexistence -cne "distribution/desktop/edition-coexistence.v1.json" -or
    $profile.desktopContracts.browserAuth -cne "distribution/desktop/edition-browser-auth.v1.json" -or
    $profile.desktopContracts.runtimeAndUpdaterFamilies -cne "distribution/desktop/edition-runtime-update-families.v1.json" -or
    $profile.releaseGates.installerLifecycleReceiptRequired -ne $true -or
    $profile.releaseGates.exactEditionBrowserAuthReceiptRequired -ne $true -or
    $profile.releaseGates.crossEditionSessionReuseAllowed -ne $false -or
    $profile.releaseGates.releaseReadyBeforeBothReceipts -ne $false -or
    $profile.brand.presentationOnly -ne $true -or
    $profile.brand.grantsHardwareAuthority -ne $false -or
    $sharedUi.contractId -cne "dronedream-shared-edition-ui/v1" -or
    $sharedUi.donorCommit -cnotmatch "^[0-9a-f]{40}$" -or
    $sharedUi.visualEvidence.subjectCommit -cnotmatch "^[0-9a-f]{40}$" -or
    $sharedUi.visualEvidence.caseCount -ne 6 -or
    $sharedUi.visualEvidence.runtimePanelHeadedValidationStatus -cne "pending-exact-desktop-runtime-red-validation" -or
    $sharedUi.minimumDesktopViewport.width -ne 390 -or
    $sharedUi.minimumDesktopViewport.height -ne 700 -or
    $sharedUi.minimumDesktopViewport.scalePercent -ne 100 -or
    $sharedUi.settingsDialogVerticalOverflowAllowed -ne $false -or
    $sharedUi.activeSettingsPanelVerticalOverflowAllowed -ne $false -or
    $sharedUi.presentationOnly -ne $true -or
    $sharedUi.grantsHardwareAuthority -ne $false -or
    $sharedUi.fieldLightweightEntryIntegrationStatus -cne "integrated-in-universal" -or
    $profile.capabilityAuthority.frontendCanAuthorize -ne $false -or
    $profile.capabilityAuthority.hardwareActionDecision -cne "deny") {
    throw "Universal build identity or safety policy drifted."
}
Invoke-GitText @("merge-base", "--is-ancestor", [string]$sharedUi.donorCommit, $sourceCommit) | Out-Null
Invoke-GitText @("merge-base", "--is-ancestor", [string]$sharedUi.visualEvidence.subjectCommit, $sourceCommit) | Out-Null
$sharedUiSourceRefs = @()
foreach ($expectedRef in @($sharedUi.sourceFiles)) {
    if ($expectedRef.path -cnotmatch "^frontend/src/" -or
        $expectedRef.sha256 -cnotmatch "^[0-9a-f]{64}$") {
        throw "Universal shared UI source binding is malformed."
    }
    $actualRef = New-RepoFileRef ([string]$expectedRef.path)
    if ($actualRef.sha256 -cne [string]$expectedRef.sha256) {
        throw "Universal shared UI source binding drifted: $($expectedRef.path)"
    }
    $sharedUiSourceRefs += $actualRef
}
if ($sharedUiSourceRefs.Count -ne 7) {
    throw "Universal shared UI contract must bind exactly seven source files."
}
$sharedUiEvidenceRef = New-RepoFileRef ([string]$sharedUi.visualEvidence.path)
if ($sharedUiEvidenceRef.sha256 -cne [string]$sharedUi.visualEvidence.sha256) {
    throw "Universal shared UI visual evidence hash drifted."
}
$sharedUiEvidence = Get-Content -LiteralPath (Join-Path $repoRoot $sharedUiEvidenceRef.path) `
    -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sharedUiEvidence.subject_commit -cne [string]$sharedUi.visualEvidence.subjectCommit -or
    $sharedUiEvidence.subject_dirty -ne $false -or
    $sharedUiEvidence.status -cne "pass" -or
    @($sharedUiEvidence.cases).Count -ne [int]$sharedUi.visualEvidence.caseCount -or
    @($sharedUiEvidence.cases | Where-Object { $_.status -cne "pass" }).Count -ne 0) {
    throw "Universal shared UI visual evidence is not an exact clean passing donor receipt."
}
foreach ($case in @($sharedUiEvidence.cases)) {
    foreach ($measurement in @($case.settings.panelMeasurements)) {
        if ($measurement.dialogScrollHeight -gt $measurement.dialogClientHeight -or
            $measurement.panelScrollHeight -gt $measurement.panelClientHeight -or
            $measurement.grantsHardwareAuthority -cne "false") {
            throw "Universal shared UI visual evidence violates the no-overflow or authority contract."
        }
    }
}
$vehicleStudioTargets = @($vehicleStudio.shareTargets)
if ($vehicleStudio.ownerEdition -cne "universal" -or
    $vehicleStudio.productSourceCommit -cnotmatch "^[0-9a-f]{40}$" -or
    $vehicleStudio.contract -cne "distribution/universal/vehicle-studio.v1.json" -or
    $vehicleStudio.schema -cne "distribution/schemas/vehicle-pack-draft-envelope.schema.json" -or
    $vehicleStudio.transport -cne "file-based-draft-envelope" -or
    ($vehicleStudioTargets -join ",") -cne "sim,lab,field" -or
    $vehicleStudio.automaticReceiverInstallation -ne $false -or
    $vehicleStudio.modelHarnessStartsOnExchange -ne $false -or
    $vehicleStudio.grantsSimulationExecution -ne $false -or
    $vehicleStudio.grantsHardwareAuthority -ne $false) {
    throw "Universal Vehicle Studio identity or safety policy drifted."
}
Invoke-GitText @("merge-base", "--is-ancestor", [string]$vehicleStudio.productSourceCommit, $sourceCommit) | Out-Null
$vehicleStudioSourceRefs = @()
foreach ($expectedRef in @($vehicleStudio.sourceFiles)) {
    if ($expectedRef.path -cnotmatch "^(frontend/src/|distribution/(schemas|universal)/)" -or
        $expectedRef.sha256 -cnotmatch "^[0-9a-f]{64}$") {
        throw "Universal Vehicle Studio source binding is malformed."
    }
    $actualRef = New-RepoFileRef ([string]$expectedRef.path)
    if ($actualRef.sha256 -cne [string]$expectedRef.sha256) {
        throw "Universal Vehicle Studio source binding drifted: $($expectedRef.path)"
    }
    $vehicleStudioSourceRefs += $actualRef
}
if ($vehicleStudioSourceRefs.Count -ne 10) {
    throw "Universal Vehicle Studio contract must bind exactly ten source files."
}
$coexistenceMatches = @($coexistence.editions | Where-Object { $_.editionId -ceq "universal" })
$browserAuthMatches = @($browserAuth.editions | Where-Object { $_.editionId -ceq "universal" })
$runtimeFamilyMatches = @($runtimeFamilies.editions | Where-Object { $_.editionId -ceq "universal" })
if ($coexistence.kind -cne "dronedream-desktop-edition-coexistence" -or
    $browserAuth.kind -cne "dronedream-desktop-edition-browser-auth" -or
    $runtimeFamilies.kind -cne "dronedream-desktop-runtime-update-families" -or
    $coexistenceMatches.Count -ne 1 -or
    $browserAuthMatches.Count -ne 1 -or
    $runtimeFamilyMatches.Count -ne 1) {
    throw "Universal desktop identity registries are invalid or ambiguous."
}
$coexistenceIdentity = $coexistenceMatches[0]
$browserAuthIdentity = $browserAuthMatches[0]
$runtimeFamilyIdentity = $runtimeFamilyMatches[0]
$coexistenceSha256 = Get-FileSha256Lower $coexistencePath
if ($browserAuth.identityBinding.contractSha256 -cne $coexistenceSha256 -or
    $browserAuthIdentity.authClientId -cne $coexistenceIdentity.authClientId -or
    $browserAuthIdentity.authClientId -cne $profile.desktopContracts.authClientId -or
    $browserAuthIdentity.bundleIdentifier -cne $profile.desktopContracts.bundleIdentifier -or
    $browserAuthIdentity.credentialVaultNamespace -cne $profile.desktopContracts.credentialVaultNamespace -or
    $runtimeFamilyIdentity.runtimeProfileId -cne $profile.enginePackProfile -or
    $runtimeFamilyIdentity.updaterMetadataFileName -cne $profile.desktopContracts.updaterMetadataFileName) {
    throw "Universal coexistence, browser-auth, Runtime, or updater identity drifted."
}
$expectedAppAuthClientId = [string]$browserAuthIdentity.authClientId

if (-not $CargoTargetDir) {
    $CargoTargetDir = Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache\universal-cargo-target"
}
$cargoTargetFull = [IO.Path]::GetFullPath($CargoTargetDir)
$repositoryTargetFull = [IO.Path]::GetFullPath((Join-Path $repoRoot "desktop\src-tauri\target"))
if ($cargoTargetFull.StartsWith($repositoryTargetFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Universal builds must not write the large Cargo target into the repository."
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $env:LOCALAPPDATA (
        "DroneDream\handoffs\universal-1.0.0-{0}" -f $sourceCommit.Substring(0, 7)
    )
}
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot)
$artifactName = "DroneDream-Universal-1.0.0.exe"
$artifactPath = Join-Path $outputRootFull $artifactName
$checksumPath = "${artifactPath}.sha256"
$signaturePath = "${artifactPath}.sig"
$releaseMetadataDirectory = Join-Path $outputRootFull "release-metadata"
$updaterMetadataPath = Join-Path $releaseMetadataDirectory "latest-universal.json"
$buildReceiptPath = "${artifactPath}.receipt.json"
$manifestPath = Join-Path $outputRootFull "handoff-manifest.json"

if (-not $Build) {
    [ordered]@{
        sourceCommit = $sourceCommit
        expectedSourceCommit = if ($ExpectedSourceCommit) { $ExpectedSourceCommit } else { $null }
        explicitSourcePinRequiredForBuild = $true
        branch = $branch
        artifactFileName = $artifactName
        profile = New-RepoFileRef "distribution\build-profiles\universal-1.0.0.v1.json"
        overlay = New-RepoFileRef "desktop\src-tauri\tauri.universal.conf.json"
        websiteHandoff = New-RepoFileRef "distribution\universal\release\website-exact-exe-handoff.v1.json"
        desktopContracts = [ordered]@{
            coexistence = New-RepoFileRef "distribution\desktop\edition-coexistence.v1.json"
            browserAuth = New-RepoFileRef "distribution\desktop\edition-browser-auth.v1.json"
            runtimeAndUpdaterFamilies = New-RepoFileRef "distribution\desktop\edition-runtime-update-families.v1.json"
        }
        sharedUi = [ordered]@{
            contractId = [string]$sharedUi.contractId
            donorCommit = [string]$sharedUi.donorCommit
            visualEvidenceSubjectCommit = [string]$sharedUi.visualEvidence.subjectCommit
            sourceFiles = $sharedUiSourceRefs
            visualEvidence = $sharedUiEvidenceRef
            minimumDesktopViewport = $sharedUi.minimumDesktopViewport
            settingsDialogVerticalOverflowAllowed = $false
            activeSettingsPanelVerticalOverflowAllowed = $false
            runtimePanelHeadedValidationStatus = [string]$sharedUi.visualEvidence.runtimePanelHeadedValidationStatus
            fieldLightweightEntryIntegrationStatus = [string]$sharedUi.fieldLightweightEntryIntegrationStatus
            presentationOnly = $true
            grantsHardwareAuthority = $false
        }
        vehicleStudio = [ordered]@{
            productSourceCommit = [string]$vehicleStudio.productSourceCommit
            contract = New-RepoFileRef ([string]$vehicleStudio.contract)
            schema = New-RepoFileRef ([string]$vehicleStudio.schema)
            sourceFiles = $vehicleStudioSourceRefs
            shareTargets = $vehicleStudioTargets
            automaticReceiverInstallation = $false
            modelHarnessStartsOnExchange = $false
            grantsSimulationExecution = $false
            grantsHardwareAuthority = $false
        }
        appAuthClientId = $expectedAppAuthClientId
        providerOAuthClientId = "external-registered-public-config-required"
        enginePackProfile = "unified-sim-lab"
        enginePackPayloadContract = "dronedream-universal-engine-payload/v1"
        workspaceModes = @("universal", "sim", "lab", "field")
        presentationSwitchGrantsAuthority = $false
        validatedVehiclePackCount = 0
        hardwareActionDecision = "deny"
        releaseGates = [ordered]@{
            installerLifecycleReceiptRequired = $true
            exactEditionBrowserAuthReceiptRequired = $true
            releaseReadyBeforeBothReceipts = $false
        }
        buildInvoked = $false
    } | ConvertTo-Json -Depth 6
    exit 0
}

if (-not $env:TAURI_SIGNING_PRIVATE_KEY_PATH -or
    -not (Test-Path -LiteralPath $env:TAURI_SIGNING_PRIVATE_KEY_PATH -PathType Leaf)) {
    throw "Universal updater signing requires TAURI_SIGNING_PRIVATE_KEY_PATH."
}
if (-not $env:DRONEDREAM_OAUTH_CLIENT_ID -or
    $env:DRONEDREAM_OAUTH_CLIENT_ID -match '\s' -or
    $env:DRONEDREAM_OAUTH_CLIENT_ID -like 'unregistered-*') {
    throw "Universal browser sign-in requires its registered public DRONEDREAM_OAUTH_CLIENT_ID."
}
$providerOAuthClientIdSha256 = Get-StringSha256Lower $env:DRONEDREAM_OAUTH_CLIENT_ID
if (Test-Path -LiteralPath $outputRootFull) {
    throw "Refusing to replace an existing Universal handoff directory: $outputRootFull"
}

$env:CARGO_TARGET_DIR = $cargoTargetFull
$env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $sourceCommit
$env:DRONEDREAM_EDITION_PROFILE = "unified-sim-lab"
$env:DRONEDREAM_DESKTOP_EDITION_ID = "universal"
$env:VITE_DRONEDREAM_EDITION = "universal"

if ($LlvmRoot) {
    & (Join-Path $repoRoot "desktop\scripts\build-windows-llvm.ps1") `
        -AdditionalConfigPath $overlayPath `
        -CargoTargetDir $cargoTargetFull `
        -LlvmRoot $LlvmRoot `
        -ExpectedProductName ([string]$overlay.productName) `
        -EditionId "universal" `
        -PreserveBundleHistory
} else {
    & (Join-Path $repoRoot "desktop\scripts\build-windows-llvm.ps1") `
        -AdditionalConfigPath $overlayPath `
        -CargoTargetDir $cargoTargetFull `
        -ExpectedProductName ([string]$overlay.productName) `
        -EditionId "universal" `
        -PreserveBundleHistory
}
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$postBuildCommit = Invoke-GitText @("rev-parse", "--verify", "HEAD")
$postBuildStatus = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($postBuildCommit -cne $sourceCommit -or $postBuildStatus) {
    throw "Universal source changed while building."
}

$bundleDirectory = Join-Path $cargoTargetFull "x86_64-pc-windows-gnullvm\release\bundle\nsis"
$candidatePath = Join-Path $bundleDirectory "DroneDream-Universal_1.0.0_x64-setup.exe"
$candidateSignaturePath = "${candidatePath}.sig"
$candidateUpdaterMetadataPath = Join-Path $bundleDirectory "latest-universal.json"
if (-not (Test-Path -LiteralPath $candidatePath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $candidateSignaturePath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $candidateUpdaterMetadataPath -PathType Leaf)) {
    throw "Universal build completed without its NSIS, signature, and updater metadata family."
}
$candidateUpdaterMetadata = Get-Content -LiteralPath $candidateUpdaterMetadataPath -Raw `
    -Encoding UTF8 | ConvertFrom-Json
if ($candidateUpdaterMetadata.version -cne "1.0.0" -or
    $candidateUpdaterMetadata.notes -cnotmatch '(?m)^edition-id: universal$' -or
    $candidateUpdaterMetadata.notes -cnotmatch "(?m)^source-commit: $sourceCommit`$" -or
    $candidateUpdaterMetadata.platforms.'windows-x86_64'.url -cnotmatch (
        '^https://github\.com/ChiZhang-805/DroneDream/releases/download/' +
        'desktop-universal-v1\.0\.0-build-[1-9][0-9]*/' +
        'DroneDream-Universal-1\.0\.0\.exe$'
    )) {
    throw "Universal updater metadata is not bound to the exact edition/source/URL family."
}

$engineManifestCandidates = @(Get-ChildItem -LiteralPath $cargoTargetFull -Recurse `
    -Filter "engine-pack-manifest.json" -File -ErrorAction SilentlyContinue)
$matchingEngineManifests = @()
foreach ($candidate in $engineManifestCandidates) {
    try {
        $document = Get-Content -LiteralPath $candidate.FullName -Raw -Encoding UTF8 |
            ConvertFrom-Json
    } catch {
        continue
    }
    if ($document.source.gitCommit -ceq $sourceCommit -and
        $document.editionProfile.profileId -ceq "unified-sim-lab") {
        $matchingEngineManifests += [pscustomobject]@{
            Path = $candidate.FullName
            Sha256 = Get-FileSha256Lower $candidate.FullName
            Document = $document
        }
    }
}
if ($matchingEngineManifests.Count -eq 0) {
    throw "The Universal build did not leave a source-bound Engine Pack manifest."
}
$engineManifestDigests = @($matchingEngineManifests.Sha256 | Sort-Object -Unique)
if ($engineManifestDigests.Count -ne 1) {
    throw "Multiple incompatible Universal Engine Pack manifests were produced."
}
$engineManifestMatch = $matchingEngineManifests[0]
$enginePayloadPaths = @($engineManifestMatch.Document.files.path)
$requiredEnginePayloadPaths = @(
    "distribution/editions/field.v1.json",
    "distribution/editions/lab.v1.json",
    "distribution/editions/sim.v1.json",
    "distribution/desktop/edition-coexistence.v1.json",
    "distribution/desktop/edition-browser-auth.v1.json",
    "distribution/desktop/edition-runtime-update-families.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/vehicle-packs/registry.v1.json"
)
$missingEnginePayloadPaths = @($requiredEnginePayloadPaths | Where-Object {
    $_ -notin $enginePayloadPaths
})
$forbiddenEnginePayloadPaths = @($enginePayloadPaths | Where-Object {
    $_ -eq "distribution/build-planning" -or
    $_.StartsWith("distribution/build-planning/", [StringComparison]::Ordinal) -or
    $_ -eq "distribution/build-plans" -or
    $_.StartsWith("distribution/build-plans/", [StringComparison]::Ordinal) -or
    $_ -eq "distribution/tests" -or
    $_.StartsWith("distribution/tests/", [StringComparison]::Ordinal)
})
if ($missingEnginePayloadPaths.Count -gt 0 -or $forbiddenEnginePayloadPaths.Count -gt 0) {
    throw "The Universal Engine Pack payload contract failed closed."
}

New-Item -ItemType Directory -Path $outputRootFull | Out-Null
New-Item -ItemType Directory -Path $releaseMetadataDirectory | Out-Null
Copy-Item -LiteralPath $candidatePath -Destination $artifactPath
Copy-Item -LiteralPath $candidateSignaturePath -Destination $signaturePath
Copy-Item -LiteralPath $candidateUpdaterMetadataPath -Destination $updaterMetadataPath
$artifactSha = Get-FileSha256Lower $artifactPath
"$artifactSha  $artifactName" | Set-Content -Encoding ascii -LiteralPath $checksumPath
$authenticode = Get-AuthenticodeSignature -LiteralPath $artifactPath

$buildReceipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-build-receipt"
    sourceCommit = $sourceCommit
    branch = $branch
    buildCount = 1
    productDisplayVersion = "1.0.0"
    artifact = [ordered]@{
        fileName = $artifactName
        absolutePath = $artifactPath
        bytes = (Get-Item -LiteralPath $artifactPath).Length
        sha256 = $artifactSha
        authenticodeStatus = [string]$authenticode.Status
    }
    checksum = [ordered]@{
        absolutePath = $checksumPath
        bytes = (Get-Item -LiteralPath $checksumPath).Length
        sha256 = Get-FileSha256Lower $checksumPath
    }
    updaterSignature = [ordered]@{
        absolutePath = $signaturePath
        bytes = (Get-Item -LiteralPath $signaturePath).Length
        sha256 = Get-FileSha256Lower $signaturePath
        state = "issued"
    }
    updaterMetadata = [ordered]@{
        absolutePath = $updaterMetadataPath
        bytes = (Get-Item -LiteralPath $updaterMetadataPath).Length
        sha256 = Get-FileSha256Lower $updaterMetadataPath
        channel = "desktop-universal-channel"
        fileName = "latest-universal.json"
    }
    profile = New-RepoFileRef "distribution\build-profiles\universal-1.0.0.v1.json"
    overlay = New-RepoFileRef "desktop\src-tauri\tauri.universal.conf.json"
    brand = New-RepoFileRef "brand\brand-editions.v1.json"
    sharedUi = [ordered]@{
        contractId = [string]$sharedUi.contractId
        donorCommit = [string]$sharedUi.donorCommit
        visualEvidenceSubjectCommit = [string]$sharedUi.visualEvidence.subjectCommit
        sourceFiles = $sharedUiSourceRefs
        visualEvidence = $sharedUiEvidenceRef
        minimumDesktopViewport = $sharedUi.minimumDesktopViewport
        settingsDialogVerticalOverflowAllowed = $false
        activeSettingsPanelVerticalOverflowAllowed = $false
        runtimePanelHeadedValidationStatus = [string]$sharedUi.visualEvidence.runtimePanelHeadedValidationStatus
        fieldLightweightEntryIntegrationStatus = [string]$sharedUi.fieldLightweightEntryIntegrationStatus
        presentationOnly = $true
        grantsHardwareAuthority = $false
    }
    vehicleStudio = [ordered]@{
        productSourceCommit = [string]$vehicleStudio.productSourceCommit
        contract = New-RepoFileRef ([string]$vehicleStudio.contract)
        schema = New-RepoFileRef ([string]$vehicleStudio.schema)
        sourceFiles = $vehicleStudioSourceRefs
        shareTargets = $vehicleStudioTargets
        automaticReceiverInstallation = $false
        modelHarnessStartsOnExchange = $false
        grantsSimulationExecution = $false
        grantsHardwareAuthority = $false
    }
    desktopContracts = [ordered]@{
        coexistence = New-RepoFileRef "distribution\desktop\edition-coexistence.v1.json"
        browserAuth = New-RepoFileRef "distribution\desktop\edition-browser-auth.v1.json"
        runtimeAndUpdaterFamilies = New-RepoFileRef "distribution\desktop\edition-runtime-update-families.v1.json"
        appAuthClientId = $expectedAppAuthClientId
        providerOAuthClientIdSha256 = $providerOAuthClientIdSha256
        browserAuthStatus = "pending-exact-headed-roundtrip-validation"
        crossEditionSessionReuseAllowed = $false
    }
    enginePack = [ordered]@{
        profileCompatibilityId = [string]$engineManifestMatch.Document.editionProfile.profileId
        payloadContractId = "dronedream-universal-engine-payload/v1"
        packId = [string]$engineManifestMatch.Document.packId
        sourceCommit = [string]$engineManifestMatch.Document.source.gitCommit
        manifestPath = [string]$engineManifestMatch.Path
        manifestSha256 = [string]$engineManifestMatch.Sha256
        fileCount = $enginePayloadPaths.Count
        requiredEditionContractsPresent = $true
        buildPlanningPayloadExcluded = $true
    }
    modeSwitch = [ordered]@{
        modes = @("universal", "sim", "lab", "field")
        presentationOnly = $true
        grantsHardwareAuthority = $false
    }
    safety = [ordered]@{
        validatedVehiclePackCount = 0
        hardwareActionDecision = "deny"
        requiredDecisionLayers = @("native", "backend", "runtime")
    }
    lifecycle = [ordered]@{
        freshInstall = "pending-isolated-red-validation"
        overlay = "pending-isolated-red-validation"
        uninstall = "pending-isolated-red-validation"
        shortcut = "pending-isolated-red-validation"
        webView2 = "pending-isolated-red-validation"
        locales = "pending-en-zh-red-validation"
        browserAuth = "pending-exact-headed-roundtrip-validation"
    }
    releaseGates = [ordered]@{
        installerLifecycleReceiptRequired = $true
        exactEditionBrowserAuthReceiptRequired = $true
        releaseReadyBeforeBothReceipts = $false
    }
    releaseReady = $false
}
$buildReceipt | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $buildReceiptPath

$manifest = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-handoff-manifest"
    sourceCommit = $sourceCommit
    buildCount = 1
    state = "built-awaiting-isolated-lifecycle-validation"
    files = @(
        [ordered]@{ path = $artifactPath; sha256 = $artifactSha; bytes = (Get-Item $artifactPath).Length },
        [ordered]@{ path = $checksumPath; sha256 = Get-FileSha256Lower $checksumPath; bytes = (Get-Item $checksumPath).Length },
        [ordered]@{ path = $signaturePath; sha256 = Get-FileSha256Lower $signaturePath; bytes = (Get-Item $signaturePath).Length },
        [ordered]@{ path = $buildReceiptPath; sha256 = Get-FileSha256Lower $buildReceiptPath; bytes = (Get-Item $buildReceiptPath).Length }
    )
    releaseMetadata = [ordered]@{
        path = $updaterMetadataPath
        sha256 = Get-FileSha256Lower $updaterMetadataPath
        bytes = (Get-Item $updaterMetadataPath).Length
        publishedWithWebsiteFiles = $false
    }
    releaseReady = $false
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath $manifestPath
Write-Host "Wrote source-bound Universal installer candidate to $artifactPath"
Write-Host "Lifecycle validation remains pending; this build is not release-ready."
