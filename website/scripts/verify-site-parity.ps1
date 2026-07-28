[CmdletBinding()]
param(
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedCommit = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$targetConfigPath = Join-Path $repositoryRoot 'website\deployment-targets.json'
$targets = Get-Content -LiteralPath $targetConfigPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$originUris = [ordered]@{
    global = [string]$targets.global.publicBaseUri
    mirror = [string]$targets.mirror.publicBaseUri
}
if ($originUris.global -cne 'https://getdronedream.com/' -or
    $originUris.mirror -cne 'http://47.93.180.216/') {
    throw "Deployment targets do not match the approved parity origins."
}

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) `
    ("DroneDream-parity-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null

try {
    $snapshots = @{}
    foreach ($originName in $originUris.Keys) {
        $originDirectory = Join-Path $temporaryRoot $originName
        New-Item -ItemType Directory -Path $originDirectory | Out-Null
        $baseUri = $originUris[$originName].TrimEnd('/')
        $buildManifestPath = Join-Path $originDirectory 'build-manifest.json'
        $integrityManifestPath = Join-Path $originDirectory 'SHA256SUMS'
        Invoke-WebRequest -Uri "$baseUri/build-manifest.json" `
            -UseBasicParsing -OutFile $buildManifestPath -TimeoutSec 30
        Invoke-WebRequest -Uri "$baseUri/SHA256SUMS" `
            -UseBasicParsing -OutFile $integrityManifestPath -TimeoutSec 30

        $buildManifest = Get-Content -LiteralPath $buildManifestPath `
            -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$buildManifest.artifactKind -cne
                'dronedream-shared-static-site' -or
            [string]$buildManifest.sourceCommit -notmatch '^[0-9a-f]{40}$' -or
            ($ExpectedCommit -and
                [string]$buildManifest.sourceCommit -cne $ExpectedCommit)) {
            throw "$originName does not expose the expected shared build manifest."
        }
        $snapshots[$originName] = [pscustomobject]@{
            BaseUri = $baseUri
            BuildManifest = $buildManifest
            BuildManifestPath = $buildManifestPath
            IntegrityManifestPath = $integrityManifestPath
        }
    }

    $globalBuildHash = (Get-FileHash `
        -LiteralPath $snapshots.global.BuildManifestPath -Algorithm SHA256).
        Hash.ToLowerInvariant()
    $mirrorBuildHash = (Get-FileHash `
        -LiteralPath $snapshots.mirror.BuildManifestPath -Algorithm SHA256).
        Hash.ToLowerInvariant()
    $globalIntegrityHash = (Get-FileHash `
        -LiteralPath $snapshots.global.IntegrityManifestPath -Algorithm SHA256).
        Hash.ToLowerInvariant()
    $mirrorIntegrityHash = (Get-FileHash `
        -LiteralPath $snapshots.mirror.IntegrityManifestPath -Algorithm SHA256).
        Hash.ToLowerInvariant()
    if ($globalBuildHash -cne $mirrorBuildHash -or
        $globalIntegrityHash -cne $mirrorIntegrityHash) {
        throw "The global site and mirror do not expose identical build and integrity manifests."
    }

    $verifiedPaths = @()
    foreach ($line in Get-Content `
        -LiteralPath $snapshots.global.IntegrityManifestPath -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw "The public SHA256SUMS contains an invalid entry."
        }
        $expectedHash = $Matches[1]
        $relativePath = $Matches[2]
        if ($relativePath -notmatch (
                '^(?:index|site|404)\.html$|' +
                '^(?:assets|console/assets)/.+\.(?:js|css)$|' +
                '^console/index\.html$'
            )) {
            continue
        }
        foreach ($originName in $originUris.Keys) {
            $downloadPath = Join-Path $temporaryRoot (
                "$originName-" + [Guid]::NewGuid().ToString('N')
            )
            Invoke-WebRequest `
                -Uri "$($snapshots[$originName].BaseUri)/$relativePath" `
                -UseBasicParsing -OutFile $downloadPath -TimeoutSec 30
            $actualHash = (Get-FileHash -LiteralPath $downloadPath `
                -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -cne $expectedHash) {
                throw "$originName differs from the shared artifact: $relativePath"
            }
        }
        $verifiedPaths += $relativePath
    }
    if ($verifiedPaths.Count -lt 4) {
        throw "Parity verification covered too few HTML, JavaScript, and CSS files."
    }

    $sourceCommit = [string]$snapshots.global.BuildManifest.sourceCommit
    Write-Host "Global and mirror manifests are identical."
    Write-Host "Source commit: $sourceCommit"
    Write-Host "Verified $($verifiedPaths.Count) HTML, JavaScript, and CSS files on both origins."
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
