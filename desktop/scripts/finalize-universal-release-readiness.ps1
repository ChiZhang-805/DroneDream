param(
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{40}$")][string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][ValidateRange(1, [long]::MaxValue)][long]$ExpectedBytes,
    [Parameter(Mandatory = $true)][string]$BuildReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedBuildReceiptSha256,
    [Parameter(Mandatory = $true)][string]$BuildManifest,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedBuildManifestSha256,
    [Parameter(Mandatory = $true)][string]$LifecycleReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedLifecycleReceiptSha256,
    [Parameter(Mandatory = $true)][string]$VisibleInstallerReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedVisibleInstallerReceiptSha256,
    [Parameter(Mandatory = $true)][string]$InstalledAppReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedInstalledAppReceiptSha256,
    [Parameter(Mandatory = $true)][string]$OAuthReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedOAuthReceiptSha256,
    [Parameter(Mandatory = $true)][string]$IconReceipt,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedIconReceiptSha256,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\', '/')
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream\handoffs")).TrimEnd('\', '/')

function Get-GitText([string[]]$Arguments) {
    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed." }
    return (($output | Out-String).Trim())
}

function Get-FileRecord([string]$Path) {
    $full = (Resolve-Path -LiteralPath $Path).Path
    $item = Get-Item -LiteralPath $full
    return [ordered]@{
        path = $full
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Read-BoundJson([string]$Path, [string]$ExpectedHash, [string]$Label) {
    $record = Get-FileRecord $Path
    if ($record.sha256 -cne $ExpectedHash) { throw "$Label hash drifted from the frozen input." }
    $document = Get-Content -LiteralPath $record.path -Raw -Encoding UTF8 | ConvertFrom-Json
    return [pscustomobject]@{ Record = $record; Document = $document }
}

function Write-JsonNoBom([string]$Path, [object]$Value) {
    $encoding = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, "$(ConvertTo-Json $Value -Depth 15)$([Environment]::NewLine)", $encoding)
}

function Assert-ArtifactIdentity([object]$Artifact, [string]$Label) {
    $path = if ($Artifact.absolutePath) { [string]$Artifact.absolutePath } else { [string]$Artifact.path }
    $sha = [string]$Artifact.sha256
    $bytes = [long]$Artifact.bytes
    if ([IO.Path]::GetFullPath($path) -cne $installerPath -or $sha -cne $ExpectedSha256 -or $bytes -ne $ExpectedBytes) {
        throw "$Label is not bound to the frozen Universal artifact."
    }
}

if (-not $outputRootFull.StartsWith("$allowedRoot\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Final readiness output must stay under the owned DroneDream handoff root."
}
if ((Split-Path -Leaf $installerPath) -cne "DroneDream-Universal-1.0.0.exe") {
    throw "Universal Website handoff filename drifted."
}
$artifact = Get-FileRecord $installerPath
if ($artifact.sha256 -cne $ExpectedSha256 -or $artifact.bytes -ne $ExpectedBytes) {
    throw "Universal artifact identity drifted."
}
$branch = Get-GitText @("branch", "--show-current")
$toolHead = Get-GitText @("rev-parse", "HEAD")
$upstream = Get-GitText @("rev-parse", "@{u}")
$status = Get-GitText @("status", "--porcelain=v1", "--untracked-files=all")
if ($branch -cne "codex/software" -or $toolHead -cne $upstream -or $status) {
    throw "Final readiness requires clean, upstream-exact codex/software."
}
& git -C $repoRoot merge-base --is-ancestor $ProductSourceCommit $toolHead
if ($LASTEXITCODE -ne 0) { throw "Finalizer tool source does not descend from the product source." }
foreach ($path in @(
    "distribution/build-profiles/universal-1.0.0.v1.json",
    "desktop/src-tauri/tauri.universal.conf.json",
    "brand/brand-editions.v1.json",
    "brand/generated/universal/windows/icon.ico"
)) {
    & git -C $repoRoot diff --quiet $ProductSourceCommit -- $path
    if ($LASTEXITCODE -ne 0) { throw "Product input drifted after the frozen build: $path" }
}

$build = Read-BoundJson $BuildReceipt $ExpectedBuildReceiptSha256 "Build receipt"
$buildManifest = Read-BoundJson $BuildManifest $ExpectedBuildManifestSha256 "Build manifest"
$lifecycle = Read-BoundJson $LifecycleReceipt $ExpectedLifecycleReceiptSha256 "Lifecycle receipt"
$visible = Read-BoundJson $VisibleInstallerReceipt $ExpectedVisibleInstallerReceiptSha256 "Visible installer receipt"
$headed = Read-BoundJson $InstalledAppReceipt $ExpectedInstalledAppReceiptSha256 "Installed-app receipt"
$oauth = Read-BoundJson $OAuthReceipt $ExpectedOAuthReceiptSha256 "OAuth receipt"
$icons = Read-BoundJson $IconReceipt $ExpectedIconReceiptSha256 "Icon receipt"

if ($build.Document.kind -cne "dronedream-universal-build-receipt" -or
    $build.Document.sourceCommit -cne $ProductSourceCommit -or $build.Document.buildCount -ne 1) {
    throw "Build receipt source or build count drifted."
}
Assert-ArtifactIdentity $build.Document.artifact "Build receipt"
if ($buildManifest.Document.sourceCommit -cne $ProductSourceCommit -or
    $buildManifest.Document.buildCount -ne 1 -or $buildManifest.Document.releaseReady -ne $false) {
    throw "Historical build manifest is not the immutable pre-validation record."
}
$checksum = Get-FileRecord ([string]$build.Document.checksum.absolutePath)
$signature = Get-FileRecord ([string]$build.Document.updaterSignature.absolutePath)
if ($checksum.sha256 -cne [string]$build.Document.checksum.sha256 -or
    $signature.sha256 -cne [string]$build.Document.updaterSignature.sha256 -or
    [string]$build.Document.updaterSignature.state -cne "issued") {
    throw "Checksum or updater signature drifted."
}
$checksumClaim = (Get-Content -LiteralPath $checksum.path -Raw -Encoding ASCII).Trim().Split(' ')[0]
if ($checksumClaim -cne $ExpectedSha256) { throw "Checksum companion does not claim the frozen EXE." }
$authenticode = Get-AuthenticodeSignature -LiteralPath $installerPath
if ([string]$authenticode.Status -cne "NotSigned") {
    throw "Universal Authenticode state drifted from the frozen internal-test fact."
}

if ($lifecycle.Document.kind -cne "dronedream-universal-installer-lifecycle-receipt" -or
    $lifecycle.Document.productSourceCommit -cne $ProductSourceCommit -or
    $lifecycle.Document.installerLifecycleReady -ne $true -or
    $lifecycle.Document.lifecycle.freshInstall -cne "pass" -or
    $lifecycle.Document.lifecycle.inPlaceSameVersionUpdate -cne "pass" -or
    $lifecycle.Document.lifecycle.uninstall -cne "pass-both-cycles" -or
    $lifecycle.Document.lifecycle.shortcut -cne "pass" -or
    $lifecycle.Document.lifecycle.webView2 -cne "pass-existing-runtime-unchanged") {
    throw "Lifecycle receipt did not prove every frozen lifecycle boundary."
}
Assert-ArtifactIdentity $lifecycle.Document.installer "Lifecycle receipt"
if ($visible.Document.kind -cne "dronedream-universal-visible-installer-ui-receipt" -or
    $visible.Document.productSourceCommit -cne $ProductSourceCommit -or
    $visible.Document.result.visibleInstallerUiReady -ne $true -or
    $visible.Document.exactCounts.installerProcesses -ne 2 -or
    $visible.Document.exactCounts.installationCommits -ne 0 -or
    @($visible.Document.cases).Count -ne 2 -or
    @($visible.Document.cases | Where-Object { $_.pathGuard -ne $true -or $_.installationCommitted -ne $false }).Count -ne 0) {
    throw "Visible EN/ZH installer receipt failed closed."
}
Assert-ArtifactIdentity $visible.Document.artifact "Visible installer receipt"
if ($headed.Document.kind -cne "dronedream-universal-installed-app-headed-receipt" -or
    $headed.Document.productSourceCommit -cne $ProductSourceCommit -or
    $headed.Document.passed -ne $true -or @($headed.Document.cases).Count -ne 4 -or
    $headed.Document.counts.settingsOpen -ne 4 -or $headed.Document.counts.settingsTabActivations -ne 16 -or
    $headed.Document.counts.screenshots -ne 8 -or $headed.Document.webView2.childCount -lt 1 -or
    $headed.Document.ownedCleanup.productRegistrationRemoved -ne $true -or
    $headed.Document.ownedCleanup.testWebViewProfileRemoved -ne $true) {
    throw "Installed-app headed receipt failed closed."
}
Assert-ArtifactIdentity $headed.Document.artifact "Installed-app receipt"
if ($oauth.Document.kind -cne "dronedream-universal-real-oauth-receipt" -or
    $oauth.Document.productSourceCommit -cne $ProductSourceCommit -or $oauth.Document.passed -ne $true -or
    $oauth.Document.counts.credentialVaultRestoreProbe -ne 1 -or $oauth.Document.counts.loginButton -ne 1 -or
    $oauth.Document.counts.oauthTransaction -ne 1 -or $oauth.Document.counts.callback -ne 1 -or
    $oauth.Document.counts.authorizationCodeExchange -ne 1 -or $oauth.Document.counts.localLogout -ne 1 -or
    $oauth.Document.counts.authenticatedUiCases -ne 16 -or $oauth.Document.counts.settingsOpen -ne 16 -or
    $oauth.Document.counts.settingsTabActivations -ne 64 -or $oauth.Document.counts.screenshots -ne 32 -or
    @($oauth.Document.authenticatedUiCases).Count -ne 16 -or -not $oauth.Document.authEvidence.subjectHash -or
    $oauth.Document.authEvidence.rawCallbackRecorded -ne $false -or $oauth.Document.authEvidence.credentialsRecorded -ne $false -or
    $oauth.Document.runtimeRestoreObserved -ne $true -or $oauth.Document.failure) {
    throw "Real OAuth/PKCE receipt failed closed."
}
Assert-ArtifactIdentity $oauth.Document.artifact "OAuth receipt"
if (($oauth.Document.protectedStateBefore | ConvertTo-Json -Depth 12 -Compress) -cne
    ($oauth.Document.protectedStateAfter | ConvertTo-Json -Depth 12 -Compress)) {
    throw "OAuth validation did not restore protected state exactly."
}
if ($icons.Document.kind -cne "dronedream-universal-icon-surfaces-receipt" -or
    $icons.Document.productSourceCommit -cne $ProductSourceCommit -or $icons.Document.passed -ne $true -or
    @($icons.Document.surfaces).Count -ne 4 -or $icons.Document.protectedShortcutParity -ne $true -or
    $icons.Document.canonicalIcon.sha256 -cne "88223fab6c2b0d493aaedab932c04d40def4da58e28f6d670adbfd745a6ca8ba" -or
    $icons.Document.counts.installer -ne 1 -or $icons.Document.counts.uninstaller -ne 1) {
    throw "Four-surface Universal icon receipt failed closed."
}
Assert-ArtifactIdentity $icons.Document.installer "Icon receipt"

$preflight = [ordered]@{
    installRootAbsent = -not (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "DroneDream-Universal"))
    uninstallKeyAbsent = -not (Test-Path -LiteralPath "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Universal")
    productKeyAbsent = -not (Test-Path -LiteralPath "HKCU:\Software\DroneDream\DroneDream-Universal")
    appProcessAbsent = @(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -eq 0
    callbackPortFree = @(Get-NetTCPConnection -State Listen -LocalPort 49210 -ErrorAction SilentlyContinue).Count -eq 0
    cdpPortFree = @(Get-NetTCPConnection -State Listen -LocalPort 49321 -ErrorAction SilentlyContinue).Count -eq 0
}
if (@($preflight.Values | Where-Object { -not $_ }).Count -ne 0) {
    throw "Final readiness preflight found owned product residue or live ports."
}

$summary = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-final-readiness-plan"
    productSourceCommit = $ProductSourceCommit
    evidenceToolHead = $toolHead
    artifact = $artifact
    buildCount = 1
    authenticodeState = "NotSigned"
    updaterSignature = $signature
    checksum = $checksum
    evidence = [ordered]@{
        buildReceipt = $build.Record
        immutableBuildManifest = $buildManifest.Record
        lifecycle = $lifecycle.Record
        visibleInstaller = $visible.Record
        installedAppHeaded = $headed.Record
        realOAuthPkce = $oauth.Record
        fourIconSurfaces = $icons.Record
        iconEvidenceBoard = $icons.Document.screenshot
    }
    boundaries = [ordered]@{
        freshInstall = "passed"
        sameVersionOverlay = "passed"
        uninstall = "passed"
        desktopAndStartMenuShortcuts = "passed"
        existingWebView2 = "passed"
        englishAndSimplifiedChineseInstaller = "passed"
        installedAppResponsiveUi = "passed"
        realBrowserPkceAndLocalLogout = "passed"
        editionCoexistenceProtectedState = "passed"
        runtimeReturnedToPreRunState = "passed"
        iconInstallerAppDesktopStartMenu = "passed"
        publicWebsiteDeployment = "not-performed-awaiting-user-command"
    }
    safety = [ordered]@{
        validatedVehiclePackCount = 0
        hardwareActionDecision = "deny"
        presentationSwitchGrantsAuthority = $false
    }
    preflight = $preflight
    releaseReady = $true
    deploymentPerformed = $false
}
if (-not $Execute) {
    $summary | ConvertTo-Json -Depth 15 | Write-Output
    exit 0
}
if (Test-Path -LiteralPath $outputRootFull) { throw "Refusing to replace an existing final readiness directory." }
$stagingRoot = "$outputRootFull.staging-$([Guid]::NewGuid().ToString('N'))"
try {
    New-Item -ItemType Directory -Path $stagingRoot | Out-Null
    $readinessPath = Join-Path $stagingRoot "universal-final-readiness-receipt.json"
    $summary.kind = "dronedream-universal-final-readiness-receipt"
    $summary.completedAt = [DateTime]::UtcNow.ToString("O")
    Write-JsonNoBom $readinessPath $summary
    $readinessRecord = Get-FileRecord $readinessPath

    $finalManifest = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-universal-final-handoff-manifest"
        exactCleanProductSourceCommit = $ProductSourceCommit
        evidenceToolHead = $toolHead
        productSourceAndEvidenceHeadAreDistinct = ($ProductSourceCommit -cne $toolHead)
        buildCount = 1
        artifact = $artifact
        checksum = $checksum
        updaterSignature = $signature
        buildReceipt = $build.Record
        readinessReceipt = $readinessRecord
        validationReceipts = @(
            $lifecycle.Record, $visible.Record, $headed.Record, $oauth.Record, $icons.Record
        )
        releaseReady = $true
        deploymentPerformed = $false
    }
    $manifestPath = Join-Path $stagingRoot "universal-final-handoff-manifest.json"
    Write-JsonNoBom $manifestPath $finalManifest
    $manifestRecord = Get-FileRecord $manifestPath

    $websiteHandoff = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-universal-website-exact-exe-handoff"
        state = "release-ready-awaiting-website-deployment-command"
        editionId = "universal"
        exactCleanProductSourceCommit = $ProductSourceCommit
        evidenceToolHead = $toolHead
        absoluteExePath = $artifact.path
        fileName = "DroneDream-Universal-1.0.0.exe"
        version = "1.0.0"
        bytes = $artifact.bytes
        sha256Lowercase = $artifact.sha256
        authenticodeState = "NotSigned"
        updaterSigPath = $signature.path
        updaterSigSha256 = $signature.sha256
        checksumPath = $checksum.path
        checksumSha256 = $checksum.sha256
        receiptPath = $readinessRecord.path.Replace($stagingRoot, $outputRootFull)
        receiptSha256 = $readinessRecord.sha256
        manifestPath = $manifestRecord.path.Replace($stagingRoot, $outputRootFull)
        manifestSha256 = $manifestRecord.sha256
        buildReceiptPath = $build.Record.path
        buildReceiptSha256 = $build.Record.sha256
        buildCount = 1
        freshInstallBoundary = "passed"
        overlayBoundary = "passed"
        uninstallBoundary = "passed"
        shortcutBoundary = "passed"
        webView2Boundary = "passed"
        localeBoundary = "passed-en-and-zh"
        editionCoexistenceBoundary = "passed-protected-state-parity"
        browserAuthBoundary = "passed-real-pkce-callback-local-logout"
        runtimeUpdateFamilyBoundary = "signed-metadata-issued-public-deployment-pending"
        iconBoundary = "passed-installer-app-desktop-start-menu"
        releaseReady = $true
        deploymentPerformed = $false
        websiteMustNotRebuildOrRename = $true
    }
    $websitePath = Join-Path $stagingRoot "website-exact-exe-handoff.final.v1.json"
    Write-JsonNoBom $websitePath $websiteHandoff
    Move-Item -LiteralPath $stagingRoot -Destination $outputRootFull
}
catch {
    if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }
    throw
}

[ordered]@{
    exactCleanProductSourceCommit = $ProductSourceCommit
    evidenceToolHead = $toolHead
    artifact = $artifact
    readinessReceipt = Get-FileRecord (Join-Path $outputRootFull "universal-final-readiness-receipt.json")
    finalManifest = Get-FileRecord (Join-Path $outputRootFull "universal-final-handoff-manifest.json")
    websiteHandoff = Get-FileRecord (Join-Path $outputRootFull "website-exact-exe-handoff.final.v1.json")
    releaseReady = $true
    deploymentPerformed = $false
} | ConvertTo-Json -Depth 8
