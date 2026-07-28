$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$frontendRoot = Join-Path $repositoryRoot "frontend"
$deploymentTargetsPath = Join-Path $repositoryRoot "website\deployment-targets.json"
$releaseConfigPath = Join-Path $repositoryRoot "website\pages-release.json"
$tauriConfigPath = Join-Path $repositoryRoot "desktop\src-tauri\tauri.conf.json"
$codeSigningPolicyPath = Join-Path $repositoryRoot "CODE_SIGNING_POLICY.md"
$release = Get-Content -LiteralPath $releaseConfigPath -Raw | ConvertFrom-Json
$deploymentTargets = Get-Content -LiteralPath $deploymentTargetsPath -Raw |
    ConvertFrom-Json
$tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
$codeSigningPolicy = Get-Content -LiteralPath $codeSigningPolicyPath -Raw

$version = [string]$release.version
$fileName = [string]$release.fileName
$releaseTag = [string]$release.releaseTag
$sha256 = ([string]$release.sha256).ToLowerInvariant()
$sizeBytes = [long]$release.sizeBytes
$publishedAt = [string]$release.publishedAt
$expectedFileName = "DroneDream_${version}_x64-setup.exe"
$globalTarget = $deploymentTargets.global
$mirrorTarget = $deploymentTargets.mirror

if ($null -eq $globalTarget -or $null -eq $mirrorTarget) {
    throw "Deployment targets must define global and mirror."
}
if ([string]$globalTarget.platform -cne "github-pages" -or
    [string]$globalTarget.publicHost -cne "getdronedream.com" -or
    [string]$globalTarget.publicBaseUri -cne "https://getdronedream.com/" -or
    [string]$mirrorTarget.platform -cne "baota" -or
    [string]$mirrorTarget.publicHost -cne "47.93.180.216" -or
    [string]$mirrorTarget.publicBaseUri -cne "http://47.93.180.216/" -or
    [string]$mirrorTarget.vhostMode -cne "install" -or
    [string]$globalTarget.artifactDirectory -cne
        [string]$mirrorTarget.artifactDirectory) {
    throw "Deployment targets do not match the approved global-site and bare-IP mirror topology."
}

if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid Pages release version: $version" }
if ($version -ne [string]$tauriConfig.version) { throw "Pages release version must match the desktop version." }
if ($fileName -ne $expectedFileName) { throw "Pages release file name must be $expectedFileName" }
if ($releaseTag -notmatch '^[A-Za-z0-9._-]+$') { throw "Invalid GitHub release tag: $releaseTag" }
if ($sha256 -notmatch '^[a-f0-9]{64}$') { throw "Invalid SHA-256 in $releaseConfigPath" }
if ($sizeBytes -le 0) { throw "Pages release size must be positive." }
foreach ($attribution in @(
    "SignPath.io",
    "SignPath Foundation"
)) {
    if ($codeSigningPolicy.IndexOf($attribution, [StringComparison]::Ordinal) -lt 0) {
        throw "The code signing policy is missing required attribution: $attribution"
    }
}
$parsedDate = [DateTime]::MinValue
if (-not [DateTime]::TryParseExact(
    $publishedAt,
    'yyyy-MM-dd',
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::None,
    [ref]$parsedDate
)) { throw "Invalid Pages release date: $publishedAt" }

$assetBaseUrl = "https://github.com/ChiZhang-805/DroneDream/releases/download/$releaseTag"
$metadata = [ordered]@{
    version = $version
    fileName = $fileName
    downloadUrl = "$assetBaseUrl/$fileName"
    checksumUrl = "$assetBaseUrl/$fileName.sha256"
    sha256 = $sha256
    sizeBytes = $sizeBytes
    publishedAt = $publishedAt
}

$sourceCommit = ([string]$env:GITHUB_SHA).Trim()
if ([string]::IsNullOrWhiteSpace($sourceCommit)) {
    Push-Location $repositoryRoot
    try {
        $sourceCommit = (& git rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to resolve the source commit for the website artifact."
        }
    } finally {
        Pop-Location
    }
}
if ($sourceCommit -notmatch '^[0-9a-f]{40}$') {
    throw "The website artifact source commit is invalid."
}

$npmCommand = if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { "npm.cmd" } else { "npm" }
$previousReleaseJson = $env:DRONEDREAM_RELEASE_JSON
try {
    $env:DRONEDREAM_RELEASE_JSON = $metadata | ConvertTo-Json -Compress
    & $npmCommand --prefix $frontendRoot run site:build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $npmCommand --prefix $frontendRoot run console:build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    if ($null -eq $previousReleaseJson) {
        Remove-Item Env:\DRONEDREAM_RELEASE_JSON -ErrorAction SilentlyContinue
    } else {
        $env:DRONEDREAM_RELEASE_JSON = $previousReleaseJson
    }
}

$outputDirectory = Join-Path $frontendRoot "site-dist"
$assetDirectory = Join-Path $outputDirectory "assets"
$siteHtml = Join-Path $outputDirectory "site.html"
if (-not (Test-Path -LiteralPath $siteHtml -PathType Leaf)) {
    throw "The site build completed without producing $siteHtml"
}
$consoleHtml = Join-Path $outputDirectory "console\index.html"
if (-not (Test-Path -LiteralPath $consoleHtml -PathType Leaf)) {
    throw "The console build completed without producing $consoleHtml"
}

$builtJavaScript = @(
    Get-ChildItem -LiteralPath $assetDirectory -Filter "*.js" -File |
        ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }
) -join "`n"
foreach ($marker in @(
    $fileName,
    $sha256,
    $publishedAt,
    "CODE_SIGNING_POLICY.md",
    "PRIVACY.md"
)) {
    if ($builtJavaScript.IndexOf([string]$marker, [StringComparison]::Ordinal) -lt 0) {
        throw "The Pages build did not embed required marker: $marker"
    }
}

Copy-Item -LiteralPath $siteHtml -Destination (Join-Path $outputDirectory "index.html") -Force
Copy-Item -LiteralPath $siteHtml -Destination (Join-Path $outputDirectory "404.html") -Force
$downloadsDirectory = Join-Path $outputDirectory "downloads"
New-Item -ItemType Directory -Force -Path $downloadsDirectory | Out-Null

$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
$metadataJson = $metadata | ConvertTo-Json
[IO.File]::WriteAllText(
    (Join-Path $downloadsDirectory "latest.json"),
    "$metadataJson$([Environment]::NewLine)",
    $utf8WithoutBom
)
$cnamePath = Join-Path $outputDirectory "CNAME"
$customDomain = [string]$globalTarget.publicHost
[IO.File]::WriteAllText(
    $cnamePath,
    "$customDomain$([Environment]::NewLine)",
    $utf8WithoutBom
)
[IO.File]::WriteAllText((Join-Path $outputDirectory ".nojekyll"), "", $utf8WithoutBom)

$buildManifest = [ordered]@{
    schemaVersion = 1
    artifactKind = "dronedream-shared-static-site"
    sourceCommit = $sourceCommit
    release = [ordered]@{
        version = $version
        releaseTag = $releaseTag
        fileName = $fileName
        sha256 = $sha256
        sizeBytes = $sizeBytes
        publishedAt = $publishedAt
    }
    origins = [ordered]@{
        global = [string]$globalTarget.publicBaseUri
        mirror = [string]$mirrorTarget.publicBaseUri
    }
}
[IO.File]::WriteAllText(
    (Join-Path $outputDirectory "build-manifest.json"),
    "$($buildManifest | ConvertTo-Json -Depth 4)$([Environment]::NewLine)",
    $utf8WithoutBom
)

$integrityManifestPath = Join-Path $outputDirectory "SHA256SUMS"
Remove-Item -LiteralPath $integrityManifestPath -Force -ErrorAction SilentlyContinue
$integrityLines = Get-ChildItem -LiteralPath $outputDirectory -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = $_.FullName.Substring($outputDirectory.Length + 1).
            Replace('\', '/')
        $fileHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).
            Hash.ToLowerInvariant()
        "$fileHash  $relativePath"
    }
[IO.File]::WriteAllText(
    $integrityManifestPath,
    "$($integrityLines -join [Environment]::NewLine)$([Environment]::NewLine)",
    $utf8WithoutBom
)

Write-Host "GitHub Pages site built at $outputDirectory"
Write-Host "Shared artifact source commit: $sourceCommit"
Write-Host "Integrity manifest: $integrityManifestPath"
Write-Host "Release asset: $($metadata.downloadUrl)"
Write-Host "SHA-256: $sha256"
Write-Host "Custom domain: $customDomain"
