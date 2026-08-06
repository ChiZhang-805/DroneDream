param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDirectory,
    [string]$Repository = "ChiZhang-805/DroneDream",
    [ValidatePattern("^[A-Za-z0-9.-]+$")]
    [string]$InstallerProductName = "DroneDream",
    [string]$SourceCommit,
    [UInt64]$BuildNumber
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
$installerName = "${InstallerProductName}_${version}_x64-setup.exe"
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

$tag = "desktop-v$version"
$downloadUrl = "https://github.com/$Repository/releases/download/$tag/$installerName"
$manifest = [ordered]@{
    version = $version
    notes = @(
        "DroneDream $version for Windows x64."
        "build-number: $BuildNumber"
        "source-commit: $SourceCommit"
    ) -join "`n"
    pub_date = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    platforms = [ordered]@{
        "windows-x86_64" = [ordered]@{
            signature = $signature
            url = $downloadUrl
        }
    }
}

$manifestPath = Join-Path $bundleDirectoryFull "latest.json"
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    $manifestPath,
    "$(($manifest | ConvertTo-Json -Depth 6))$([Environment]::NewLine)",
    $utf8WithoutBom
)

$roundTrip = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($roundTrip.version -cne $version -or
    $roundTrip.notes -cne $manifest.notes -or
    $roundTrip.platforms.'windows-x86_64'.url -cne $downloadUrl -or
    $roundTrip.platforms.'windows-x86_64'.signature -cne $signature) {
    throw "Generated updater manifest did not survive round-trip validation."
}

Write-Host "Wrote Tauri updater manifest to $manifestPath"
