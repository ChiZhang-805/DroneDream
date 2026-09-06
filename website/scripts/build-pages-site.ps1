$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$frontendRoot = Join-Path $repositoryRoot "frontend"
$releaseConfigPath = Join-Path $repositoryRoot "website\pages-release.json"
$tauriConfigPath = Join-Path $repositoryRoot "desktop\src-tauri\tauri.conf.json"
$codeSigningPolicyPath = Join-Path $repositoryRoot "CODE_SIGNING_POLICY.md"
$release = Get-Content -LiteralPath $releaseConfigPath -Raw | ConvertFrom-Json
$tauriConfig = Get-Content -LiteralPath $tauriConfigPath -Raw | ConvertFrom-Json
$codeSigningPolicy = Get-Content -LiteralPath $codeSigningPolicyPath -Raw

$version = [string]$release.version
$fileName = [string]$release.fileName
$releaseTag = [string]$release.releaseTag
$sha256 = ([string]$release.sha256).ToLowerInvariant()
$sizeBytes = [long]$release.sizeBytes
$publishedAt = [string]$release.publishedAt
$hasEdition = $null -ne $release.PSObject.Properties['edition']
$hasBuildNumber = $null -ne $release.PSObject.Properties['buildNumber']
$edition = if ($hasEdition) { [string]$release.edition } else { "" }
$buildNumber = if ($hasBuildNumber) { [long]$release.buildNumber } else { 0 }
$editionProducts = @{
    universal = "DroneDream-Universal"
    sim = "DroneDream-Sim"
    lab = "DroneDream-Lab"
    field = "DroneDream-Field"
    autonomy = "DroneDream-Agent"
}

if ($hasEdition -xor $hasBuildNumber) {
    throw "Pages edition release metadata must include both edition and buildNumber."
}
if ($hasEdition) {
    if (-not $editionProducts.ContainsKey($edition)) {
        throw "Unsupported Pages release edition: $edition"
    }
    if ($buildNumber -le 0) { throw "Pages release buildNumber must be positive." }
    $expectedFileName = "$($editionProducts[$edition])_${version}_x64-setup.exe"
    $expectedReleaseTag = "five-edition-v$version-build-$buildNumber"
} else {
    $expectedFileName = "DroneDream_${version}_x64-setup.exe"
    $expectedReleaseTag = $null
}

if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid Pages release version: $version" }
if ($version -ne [string]$tauriConfig.version) { throw "Pages release version must match the desktop version." }
if ($fileName -ne $expectedFileName) { throw "Pages release file name must be $expectedFileName" }
if ($releaseTag -notmatch '^[A-Za-z0-9._-]+$') { throw "Invalid GitHub release tag: $releaseTag" }
if ($hasEdition -and $releaseTag -cne $expectedReleaseTag) {
    throw "Pages release tag must be $expectedReleaseTag"
}
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
if ($hasEdition) {
    $metadata["edition"] = $edition
    $metadata["buildNumber"] = $buildNumber
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
$consoleRoutes = @(
    "assistant",
    "dashboard",
    "jobs\new",
    "history",
    "scenarios",
    "autonomy",
    "autonomy\aircraft",
    "autonomy\maps",
    "autonomy\live",
    "autonomy\plugins",
    "autonomy\plugins\harness",
    "admin",
    "compare",
    "desktop\setup",
    "lab",
    "lab\hardware",
    "field",
    "sim"
)
foreach ($route in $consoleRoutes) {
    $routeDirectory = Join-Path (Join-Path $outputDirectory "console") $route
    New-Item -ItemType Directory -Force -Path $routeDirectory | Out-Null
    $routeHtml = Join-Path $routeDirectory "index.html"
    Copy-Item -LiteralPath $consoleHtml -Destination $routeHtml -Force
    if (-not (Test-Path -LiteralPath $routeHtml -PathType Leaf)) {
        throw "The Pages build failed to produce the console route entry: $route"
    }
}
$productHtml = Join-Path $outputDirectory "product\index.html"
if (-not (Test-Path -LiteralPath $productHtml -PathType Leaf)) {
    throw "The site build completed without producing the three-edition product route."
}
$organizationHtml = Join-Path $outputDirectory "organization\index.html"
if (-not (Test-Path -LiteralPath $organizationHtml -PathType Leaf)) {
    throw "The site build completed without producing the organization management route."
}
$editionAvailabilityJson = Join-Path $outputDirectory "downloads\editions.json"
if (-not (Test-Path -LiteralPath $editionAvailabilityJson -PathType Leaf)) {
    throw "The site build completed without producing edition download availability metadata."
}
$oauthConsentHtml = Join-Path $outputDirectory "oauth\consent\index.html"
if (-not (Test-Path -LiteralPath $oauthConsentHtml -PathType Leaf)) {
    throw "The site build completed without producing the desktop OAuth consent route."
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
$customDomain = ([string]$env:DRONEDREAM_CUSTOM_DOMAIN).Trim().TrimEnd(".")
if ([string]::IsNullOrWhiteSpace($customDomain)) {
    Remove-Item -LiteralPath $cnamePath -Force -ErrorAction SilentlyContinue
} else {
    if (
        $customDomain.Length -gt 253 -or
        $customDomain -notmatch '^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$'
    ) {
        throw "DRONEDREAM_CUSTOM_DOMAIN is not a valid DNS hostname."
    }
    [IO.File]::WriteAllText(
        $cnamePath,
        "$customDomain$([Environment]::NewLine)",
        $utf8WithoutBom
    )
}
[IO.File]::WriteAllText((Join-Path $outputDirectory ".nojekyll"), "", $utf8WithoutBom)

Write-Host "GitHub Pages site built at $outputDirectory"
Write-Host "Release asset: $($metadata.downloadUrl)"
Write-Host "SHA-256: $sha256"
if ([string]::IsNullOrWhiteSpace($customDomain)) {
    Write-Host "Custom domain: disabled (GitHub Pages URL remains canonical)"
} else {
    Write-Host "Custom domain: $customDomain"
}
