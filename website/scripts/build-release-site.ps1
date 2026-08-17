param(
    [ValidateSet("universal", "sim", "lab", "field")]
    [string]$EditionId = "universal",
    [UInt64]$BuildNumber = 0
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$frontendRoot = Join-Path $repositoryRoot "frontend"
$tauriConfigPath = Join-Path $repositoryRoot "desktop\src-tauri\tauri.conf.json"
$familyContractPath = Join-Path $repositoryRoot `
    "distribution\desktop\edition-runtime-update-families.v1.json"
$tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
$familyContract = Get-Content -LiteralPath $familyContractPath -Raw | ConvertFrom-Json
$version = [string]$tauriConfig.version
$family = @($familyContract.editions | Where-Object { $_.editionId -ceq $EditionId })
if ($family.Count -ne 1) {
    throw "The desktop release contract must contain exactly one $EditionId edition."
}
$family = $family[0]
if ([string]$familyContract.productDisplayVersion -cne $version) {
    throw "The desktop family contract version does not match the Tauri version."
}
if ($BuildNumber -eq 0) {
    $resolvedBuildNumber = (& git rev-list --count HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedBuildNumber -notmatch '^[1-9]\d*$') {
        throw "Unable to derive a positive desktop build number from Git."
    }
    $BuildNumber = [UInt64]$resolvedBuildNumber
}

$bundleDirectory = Join-Path $repositoryRoot `
    "desktop\src-tauri\target\release\bundle\nsis"
$bundleInstallerName = [string]$family.tauriBundleInstallerFileName
$installerName = [string]$family.publicArtifactFileName
$installerPath = Join-Path $bundleDirectory $bundleInstallerName
$sourceChecksumPath = "$installerPath.sha256"

if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Build the versioned desktop installer first. Missing: $installerPath"
}
$calculatedHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if (Test-Path -LiteralPath $sourceChecksumPath -PathType Leaf) {
    $checksumLine = (Get-Content -LiteralPath $sourceChecksumPath -Raw).Trim()
    if ($checksumLine -notmatch "^$calculatedHash\s+$([regex]::Escape($bundleInstallerName))$") {
        throw "The optional bundle checksum file does not match the current EXE."
    }
}

$installer = Get-Item -LiteralPath $installerPath
$metadata = [ordered]@{
    edition = $EditionId
    buildNumber = $BuildNumber
    version = $version
    fileName = $installerName
    downloadUrl = "/downloads/$installerName"
    checksumUrl = "/downloads/$installerName.sha256"
    sha256 = $calculatedHash
    sizeBytes = $installer.Length
    publishedAt = $installer.LastWriteTime.ToString("yyyy-MM-dd")
}

$previousReleaseJson = $env:DRONEDREAM_RELEASE_JSON
$siteBuildExitCode = 1
try {
    $env:DRONEDREAM_RELEASE_JSON = $metadata | ConvertTo-Json -Compress
    & npm.cmd --prefix $frontendRoot run site:build
    $siteBuildExitCode = $LASTEXITCODE
    if ($siteBuildExitCode -eq 0) {
        & npm.cmd --prefix $frontendRoot run console:build
        $siteBuildExitCode = $LASTEXITCODE
    }
} finally {
    if ($null -eq $previousReleaseJson) {
        Remove-Item Env:\DRONEDREAM_RELEASE_JSON -ErrorAction SilentlyContinue
    } else {
        $env:DRONEDREAM_RELEASE_JSON = $previousReleaseJson
    }
}
if ($siteBuildExitCode -ne 0) {
    exit $siteBuildExitCode
}

$outputDirectory = Join-Path $frontendRoot "site-dist"
$assetDirectory = Join-Path $outputDirectory "assets"
$builtJavaScript = @(
    Get-ChildItem -LiteralPath $assetDirectory -Filter "*.js" -File |
        ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }
) -join "`n"
foreach ($marker in @($installerName, $calculatedHash, $metadata.publishedAt)) {
    if ($builtJavaScript.IndexOf([string]$marker, [StringComparison]::Ordinal) -lt 0) {
        throw "The website build did not embed release metadata marker: $marker"
    }
}

$downloadsDirectory = Join-Path $outputDirectory "downloads"
New-Item -ItemType Directory -Force -Path $downloadsDirectory | Out-Null

Copy-Item -LiteralPath $installerPath -Destination (Join-Path $downloadsDirectory $installerName) -Force
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    (Join-Path $downloadsDirectory "$installerName.sha256"),
    "$calculatedHash  $installerName$([Environment]::NewLine)",
    $utf8WithoutBom
)

# Keep the generated download directory unambiguous for local QA and server
# uploads. Prune only versioned DroneDream installer artifacts, only inside the
# exact generated downloads directory, and only after the current pair exists.
$downloadsDirectoryFull = [IO.Path]::GetFullPath($downloadsDirectory).TrimEnd('\', '/')
$expectedDownloadsRoot = [IO.Path]::GetFullPath(
    (Join-Path $frontendRoot "site-dist\downloads")
).TrimEnd('\', '/')
if (-not $downloadsDirectoryFull.Equals($expectedDownloadsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to prune website downloads outside the generated site directory."
}
$currentDownloadArtifacts = @(
    [IO.Path]::GetFullPath((Join-Path $downloadsDirectoryFull $installerName)),
    [IO.Path]::GetFullPath((Join-Path $downloadsDirectoryFull "$installerName.sha256"))
)
Get-ChildItem -LiteralPath $downloadsDirectoryFull -File |
    Where-Object {
        $_.Name -match '^DroneDream(?:_|-).+\.exe(?:\.sha256)?$' -and
        $_.FullName -notin $currentDownloadArtifacts
    } |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Host "Removed stale website download $($_.Name)"
    }

$siteHtml = Join-Path $outputDirectory "site.html"
if (-not (Test-Path -LiteralPath $siteHtml -PathType Leaf)) {
    throw "The site build completed without producing $siteHtml"
}
$consoleHtml = Join-Path $outputDirectory "console\index.html"
if (-not (Test-Path -LiteralPath $consoleHtml -PathType Leaf)) {
    throw "The console build completed without producing $consoleHtml"
}
$organizationHtml = Join-Path $outputDirectory "organization\index.html"
if (-not (Test-Path -LiteralPath $organizationHtml -PathType Leaf)) {
    throw "The site build completed without producing the organization management route."
}
Copy-Item -LiteralPath $siteHtml -Destination (Join-Path $outputDirectory "index.html") -Force

$metadataPath = Join-Path $downloadsDirectory "latest.json"
$metadataJson = $metadata | ConvertTo-Json
[System.IO.File]::WriteAllText($metadataPath, "$metadataJson$([Environment]::NewLine)", $utf8WithoutBom)

# Publish an integrity manifest for the complete static release, not just the
# installer. The server-side deployment verifies this before switching the
# live symlink, so a partial upload can never become the active website.
$manifestPath = Join-Path $outputDirectory "SHA256SUMS"
Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
$manifestLines = @(
    Get-ChildItem -LiteralPath $outputDirectory -Recurse -File |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = $_.FullName.Substring($outputDirectory.Length).
                TrimStart([char[]]@([char]92, [char]47)).Replace('\', '/')
            $fileHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).
                Hash.ToLowerInvariant()
            "$fileHash  $relativePath"
        }
)
[System.IO.File]::WriteAllText(
    $manifestPath,
    "$($manifestLines -join "`n")`n",
    $utf8WithoutBom
)

Write-Host "DroneDream website release built at $outputDirectory"
Write-Host "Release: $EditionId $version build $BuildNumber ($($installer.Length) bytes)"
Write-Host "SHA-256: $calculatedHash"
Write-Host "Integrity manifest: $($manifestLines.Count) files"
