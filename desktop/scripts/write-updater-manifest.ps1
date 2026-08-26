param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDirectory,
    [string]$Repository = "ChiZhang-805/DroneDream",
    [Parameter(Mandatory = $true)]
    [ValidateSet("universal", "sim", "lab", "field", "autonomy")]
    [string]$EditionId,
    [string]$SourceCommit,
    [UInt64]$BuildNumber,
    [string]$CombinedReleaseTag,
    [ValidateSet("recommended", "required")]
    [string]$UpdatePolicy = "recommended"
)

$ErrorActionPreference = "Stop"

$bundleDirectoryFull = [IO.Path]::GetFullPath($BundleDirectory)
if (-not (Test-Path -LiteralPath $bundleDirectoryFull -PathType Container)) {
    throw "Updater bundle directory does not exist: $bundleDirectoryFull"
}

$tauriConfig = Get-Content -LiteralPath (
    Join-Path $PSScriptRoot "..\src-tauri\tauri.conf.json"
) -Raw | ConvertFrom-Json
$version = [string]$tauriConfig.version
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$familyContractPath = Join-Path $repoRoot (
    "distribution\desktop\edition-runtime-update-families.v1.json"
)
$familyContract = Get-Content -LiteralPath $familyContractPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ($familyContract.kind -cne "dronedream-desktop-runtime-update-families" -or
    $familyContract.contractVersion -cne "1.0.0" -or
    $familyContract.productDisplayVersion -cne $version) {
    throw "Desktop Runtime/update family contract is incompatible with this build."
}
$families = @($familyContract.editions | Where-Object { $_.editionId -ceq $EditionId })
if ($families.Count -ne 1) {
    throw "Desktop edition must resolve to exactly one updater family."
}
$family = $families[0]
if (-not $SourceCommit) {
    $SourceCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Unable to resolve updater source commit." }
}
if ($SourceCommit -cnotmatch '^[0-9a-f]{40}$') {
    throw "Updater source commit must be a full lowercase Git SHA."
}
if ($BuildNumber -eq 0) {
    $rawBuildNumber = (& git -C $repoRoot rev-list --count $SourceCommit).Trim()
    if ($LASTEXITCODE -ne 0 -or $rawBuildNumber -notmatch '^[1-9][0-9]*$') {
        throw "Unable to resolve a positive updater build number."
    }
    $BuildNumber = [UInt64]$rawBuildNumber
}
$installerName = [string]$family.tauriBundleInstallerFileName
$publicArtifactName = [string]$family.publicArtifactFileName
$metadataFileName = [string]$family.updaterMetadataFileName
$channelTag = [string]$family.updaterChannelTag
$releaseTagPrefix = [string]$family.updaterReleaseTagPrefix
$installerProductName = [string]$family.installerProductName
if ($installerName -cne "$($family.installerProductName)_${version}_x64-setup.exe" -or
    $metadataFileName -cne "latest-${EditionId}.json" -or
    $channelTag -cne "desktop-${EditionId}-channel" -or
    $releaseTagPrefix -cne "desktop-${EditionId}-v${version}-build-" -or
    $publicArtifactName -cne "${installerProductName}-${version}.exe") {
    throw "Desktop updater family filenames or tags drifted."
}
$installerPath = Join-Path $bundleDirectoryFull $installerName
$signaturePath = "$installerPath.sig"

if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Updater installer is missing: $installerPath"
}
if (-not (Test-Path -LiteralPath $signaturePath -PathType Leaf)) {
    throw "Updater signature is missing: $signaturePath"
}

$signature = (Get-Content -LiteralPath $signaturePath -Raw -Encoding UTF8).Trim()
if ([string]::IsNullOrWhiteSpace($signature)) {
    throw "Updater signature is empty: $signaturePath"
}
$installerSize = (Get-Item -LiteralPath $installerPath).Length
if ($installerSize -le 0) {
    throw "Updater installer is empty: $installerPath"
}

$tag = "${releaseTagPrefix}${BuildNumber}"
$downloadAssetName = $publicArtifactName
if (-not [string]::IsNullOrWhiteSpace($CombinedReleaseTag)) {
    $expectedCombinedReleaseTag = "five-edition-v${version}-build-${BuildNumber}"
    if ($CombinedReleaseTag -cne $expectedCombinedReleaseTag) {
        throw "Combined release tag must equal $expectedCombinedReleaseTag."
    }
    $tag = $CombinedReleaseTag
    $downloadAssetName = $installerName
}
$downloadUrl = "https://github.com/$Repository/releases/download/$tag/$downloadAssetName"
$manifest = [ordered]@{
    version = $version
    updatePolicy = $UpdatePolicy
    notes = @(
        "$($family.installerProductName) $version for Windows x64."
        "edition-id: $EditionId"
        "build-number: $BuildNumber"
        "source-commit: $SourceCommit"
        "update-policy: $UpdatePolicy"
    ) -join "`n"
    pub_date = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    platforms = [ordered]@{
        "windows-x86_64" = [ordered]@{
            signature = $signature
            url = $downloadUrl
            size = [UInt64]$installerSize
        }
    }
}

$manifestPath = Join-Path $bundleDirectoryFull $metadataFileName
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    $manifestPath,
    "$(($manifest | ConvertTo-Json -Depth 6))$([Environment]::NewLine)",
    $utf8WithoutBom
)

$roundTrip = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($roundTrip.version -cne $version -or
    $roundTrip.updatePolicy -cne $UpdatePolicy -or
    $roundTrip.notes -cne $manifest.notes -or
    $roundTrip.platforms.'windows-x86_64'.url -cne $downloadUrl -or
    $roundTrip.platforms.'windows-x86_64'.signature -cne $signature -or
    [UInt64]$roundTrip.platforms.'windows-x86_64'.size -ne [UInt64]$installerSize) {
    throw "Generated updater manifest did not survive round-trip validation."
}

Write-Host "Wrote Tauri updater manifest to $manifestPath"
