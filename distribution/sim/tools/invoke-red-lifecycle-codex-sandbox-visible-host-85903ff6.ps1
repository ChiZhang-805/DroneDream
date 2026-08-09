[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedToolHead,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedLauncherSha256,

    [Parameter(Mandatory = $true)]
    [string]$ApplicationPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedApplicationSha256,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long]$ExpectedApplicationBytes,

    [Parameter(Mandatory = $true)]
    [string]$TranscriptPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$hostLauncher = Join-Path $PSScriptRoot "invoke-red-lifecycle-codex-sandbox-host-85903ff6.ps1"
$transcriptFull = [IO.Path]::GetFullPath($TranscriptPath)
$allowedTranscriptRoot = "C:\Users\Public\Documents\DroneDream-Codex\Sim-RED\host-launcher-evidence"
$allowedPrefix = $allowedTranscriptRoot.TrimEnd("\") + "\"
if (-not $transcriptFull.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Visible host transcript escaped its exact evidence root."
}
if (Test-Path -LiteralPath $transcriptFull) {
    throw "Visible host transcript already exists; retry is forbidden."
}
if (-not (Test-Path -LiteralPath $allowedTranscriptRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $allowedTranscriptRoot -ErrorAction Stop | Out-Null
}
$rootItem = Get-Item -LiteralPath $allowedTranscriptRoot -Force
if (-not $rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Visible host transcript root is not an ordinary directory."
}

$started = $false
try {
    Start-Transcript -LiteralPath $transcriptFull -NoClobber -ErrorAction Stop | Out-Null
    $started = $true
    Write-Host "Press ENTER once to confirm this visible console can receive keyboard input."
    $readyKey = [Console]::ReadKey($true)
    if ($readyKey.Key -ne [ConsoleKey]::Enter) {
        throw "Visible host readiness gate accepts only ENTER."
    }
    Write-Host "Console input confirmed. Starting exact DroneDream SIM lifecycle host."
    Write-Host "Password input remains inside Windows runas and is never read by this wrapper."
    & $hostLauncher `
        -ExpectedToolHead $ExpectedToolHead `
        -ExpectedLauncherSha256 $ExpectedLauncherSha256 `
        -ApplicationPath $ApplicationPath `
        -ExpectedApplicationSha256 $ExpectedApplicationSha256 `
        -ExpectedApplicationBytes $ExpectedApplicationBytes `
        -Mode StageAndRunAs
}
catch {
    Write-Error -ErrorRecord $_
    exit 1
}
finally {
    if ($started) {
        Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
    }
}
