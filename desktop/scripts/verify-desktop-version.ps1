param(
    [string]$ReleaseTag
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$tauriConfig = Get-Content -LiteralPath (Join-Path $repoRoot "desktop\src-tauri\tauri.conf.json") -Raw |
    ConvertFrom-Json
$package = Get-Content -LiteralPath (Join-Path $repoRoot "desktop\package.json") -Raw |
    ConvertFrom-Json

# Windows PowerShell 5.1 cannot ConvertFrom-Json an npm lockfile's required
# empty-string package key, so read its top-level identity with a narrowly
# anchored expression.
$packageLockMatch = [regex]::Match(
    (Get-Content -LiteralPath (Join-Path $repoRoot "desktop\package-lock.json") -Raw),
    '^\s*\{\s*"name"\s*:\s*"drone-dream-desktop"\s*,\s*"version"\s*:\s*"([^"]+)"',
    [Text.RegularExpressions.RegexOptions]::Singleline
)
if (-not $packageLockMatch.Success) {
    throw "Desktop package-lock version was not found."
}

$cargoManifestMatch = [regex]::Match(
    (Get-Content -LiteralPath (Join-Path $repoRoot "desktop\src-tauri\Cargo.toml") -Raw),
    '(?ms)^\[package\]\s*.*?^version\s*=\s*"([^"]+)"\s*$'
)
if (-not $cargoManifestMatch.Success) {
    throw "Desktop Cargo package version was not found."
}
$cargoLockMatch = [regex]::Match(
    (Get-Content -LiteralPath (Join-Path $repoRoot "desktop\src-tauri\Cargo.lock") -Raw),
    '(?ms)^\[\[package\]\]\s*^name\s*=\s*"drone-dream-desktop"\s*^version\s*=\s*"([^"]+)"\s*$'
)
if (-not $cargoLockMatch.Success) {
    throw "Desktop Cargo.lock package version was not found."
}

$versions = [ordered]@{
    "tauri.conf.json" = [string]$tauriConfig.version
    "package.json" = [string]$package.version
    "package-lock.json" = $packageLockMatch.Groups[1].Value
    "Cargo.toml" = $cargoManifestMatch.Groups[1].Value
    "Cargo.lock" = $cargoLockMatch.Groups[1].Value
}
$expected = $versions["tauri.conf.json"]
if ($expected -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Desktop version is not a supported semantic version: $expected"
}
$mismatches = @($versions.GetEnumerator() | Where-Object { $_.Value -cne $expected })
if ($mismatches.Count -gt 0) {
    $details = ($versions.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ", "
    throw "Desktop versions disagree: $details"
}

# The launcher exposes the installed desktop build to beta testers. Keep both
# localized labels tied to the signed/bundled version instead of allowing a
# stale marketing string to survive a package bump.
$i18nPath = Join-Path $repoRoot "frontend\src\i18n\I18nProvider.tsx"
$i18n = Get-Content -LiteralPath $i18nPath -Raw -Encoding UTF8
$previewMatches = [regex]::Matches(
    $i18n,
    '"app\.previewVersion"\s*:\s*"DroneDream\s+([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)\s+[^"]+"'
)
if ($previewMatches.Count -ne 2) {
    throw "Expected exactly two localized DroneDream desktop preview labels."
}
$previewMismatches = @($previewMatches | Where-Object { $_.Groups[1].Value -cne $expected })
if ($previewMismatches.Count -ne 0) {
    $previewVersions = @($previewMatches | ForEach-Object { $_.Groups[1].Value }) -join ", "
    throw "Localized desktop preview labels disagree with $expected`: $previewVersions"
}

if ($ReleaseTag -and $ReleaseTag -cne "desktop-v$expected") {
    throw "Release tag $ReleaseTag does not match desktop version $expected."
}

Write-Host "Desktop versions verified: $expected"
