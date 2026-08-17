param(
    [string]$ReleaseTag,
    [ValidateSet("universal", "sim", "lab", "field")]
    [string]$ValidationEditionId = "universal",
    [string]$GitHubOutputPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$version = [string](
    Get-Content -LiteralPath (Join-Path $repoRoot "desktop\src-tauri\tauri.conf.json") `
        -Raw -Encoding UTF8 |
        ConvertFrom-Json
).version
$familyPath = Join-Path $repoRoot "distribution\desktop\edition-runtime-update-families.v1.json"
$families = Get-Content -LiteralPath $familyPath -Raw -Encoding UTF8 | ConvertFrom-Json

$isRelease = -not [string]::IsNullOrWhiteSpace($ReleaseTag)
if ($isRelease) {
    $match = [regex]::Match(
        $ReleaseTag,
        '^desktop-(universal|sim|lab|field)-v([0-9]+\.[0-9]+\.[0-9]+)-build-([1-9][0-9]*)$',
        [Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if (-not $match.Success) {
        throw "Desktop release tag must identify one edition, version, and positive build number."
    }
    $editionId = $match.Groups[1].Value
    $tagVersion = $match.Groups[2].Value
    $buildNumber = [UInt64]$match.Groups[3].Value
    if ($tagVersion -cne $version) {
        throw "Desktop release tag version $tagVersion does not match product version $version."
    }
} else {
    # Pull requests exercise one real edition without acquiring release
    # authority or publishing into any updater channel.
    $editionId = $ValidationEditionId
    $buildNumberText = (& git -C $repoRoot rev-list --count HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $buildNumberText -notmatch '^[1-9][0-9]*$') {
        throw "Unable to resolve the validation build number."
    }
    $buildNumber = [UInt64]$buildNumberText
}

$matches = @($families.editions | Where-Object { $_.editionId -ceq $editionId })
if ($matches.Count -ne 1) {
    throw "Desktop edition must resolve to exactly one updater family."
}
$family = $matches[0]
$configRelativePath = "desktop/src-tauri/tauri.$editionId.conf.json"
$configPath = Join-Path $repoRoot $configRelativePath.Replace('/', '\')
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json

$expectedBundleName = "$($family.installerProductName)_${version}_x64-setup.exe"
$expectedPublicName = "$($family.installerProductName)-${version}.exe"
$expectedMetadataName = "latest-${editionId}.json"
$expectedChannelTag = "desktop-${editionId}-channel"
$expectedReleasePrefix = "desktop-${editionId}-v${version}-build-"
if ([string]$config.productName -cne [string]$family.installerProductName -or
    [string]$family.tauriBundleInstallerFileName -cne $expectedBundleName -or
    [string]$family.publicArtifactFileName -cne $expectedPublicName -or
    [string]$family.updaterMetadataFileName -cne $expectedMetadataName -or
    [string]$family.updaterChannelTag -cne $expectedChannelTag -or
    [string]$family.updaterReleaseTagPrefix -cne $expectedReleasePrefix) {
    throw "Desktop edition release identity drifted from the updater-family contract."
}

if ($isRelease) {
    $expectedTag = "$expectedReleasePrefix$buildNumber"
    if ($ReleaseTag -cne $expectedTag) {
        throw "Desktop release tag $ReleaseTag does not match $expectedTag."
    }
    $actualBuildNumber = (& git -C $repoRoot rev-list --count HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualBuildNumber -cne [string]$buildNumber) {
        throw "Desktop release build number must equal the tagged source commit count."
    }
}

$payload = [ordered]@{
    schemaVersion = 1
    isRelease = $isRelease
    editionId = $editionId
    runtimeProfileId = [string]$family.runtimeProfileId
    productName = [string]$family.installerProductName
    version = $version
    buildNumber = [string]$buildNumber
    configPath = $configRelativePath
    windowTitle = [string]$config.app.windows[0].title
    bundleInstallerFileName = [string]$family.tauriBundleInstallerFileName
    publicArtifactFileName = [string]$family.publicArtifactFileName
    metadataFileName = [string]$family.updaterMetadataFileName
    channelTag = [string]$family.updaterChannelTag
    releaseTag = if ($isRelease) { $ReleaseTag } else { "" }
}

if ($GitHubOutputPath) {
    $outputLines = @(
        "is_release=$($payload.isRelease.ToString().ToLowerInvariant())",
        "edition_id=$($payload.editionId)",
        "runtime_profile_id=$($payload.runtimeProfileId)",
        "product_name=$($payload.productName)",
        "version=$($payload.version)",
        "build_number=$($payload.buildNumber)",
        "config_path=$($payload.configPath)",
        "window_title=$($payload.windowTitle)",
        "bundle_installer=$($payload.bundleInstallerFileName)",
        "public_installer=$($payload.publicArtifactFileName)",
        "metadata_file=$($payload.metadataFileName)",
        "channel_tag=$($payload.channelTag)",
        "release_tag=$($payload.releaseTag)"
    )
    $outputLines | Out-File -FilePath $GitHubOutputPath -Encoding utf8 -Append
}

[pscustomobject]$payload
