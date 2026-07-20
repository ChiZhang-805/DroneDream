param(
    [Parameter(Mandatory = $true)]
    [string]$BundleDirectory,
    [string]$Repository = "ChiZhang-805/DroneDream"
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
$installerName = "DroneDream_${version}_x64-setup.exe"
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
    notes = "DroneDream $version for Windows x64."
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
    $roundTrip.platforms.'windows-x86_64'.url -cne $downloadUrl -or
    $roundTrip.platforms.'windows-x86_64'.signature -cne $signature) {
    throw "Generated updater manifest did not survive round-trip validation."
}

Write-Host "Wrote Tauri updater manifest to $manifestPath"
