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

    $editionPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    [void]$editionPaths.Add('downloads/editions.json')
    [void]$editionPaths.Add('downloads/edition-artifacts.json')
    foreach ($edition in @($snapshots.global.BuildManifest.editionArtifacts.entries)) {
        foreach ($file in @($edition.files)) {
            $editionFileName = [string]$file.fileName
            if ($editionFileName -notmatch '^[A-Za-z0-9._-]+$') {
                throw "The edition build manifest contains an unsafe filename."
            }
            [void]$editionPaths.Add("downloads/$editionFileName")
        }
    }

    $verifiedPaths = @()
    $verifiedReleaseMetadata = @{}
    foreach ($line in Get-Content `
        -LiteralPath $snapshots.global.IntegrityManifestPath -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw "The public SHA256SUMS contains an invalid entry."
        }
        $expectedHash = $Matches[1]
        $relativePath = $Matches[2]
        if (-not $editionPaths.Contains($relativePath) -and
            $relativePath -notmatch (
                '^(?:index|site|404)\.html$|' +
                '^(?:assets|console/assets)/.+\.(?:js|css)$|' +
                '^console/index\.html$|' +
                '^downloads/latest\.json$'
            )) {
            continue
        }
        foreach ($originName in $originUris.Keys) {
            $downloadPath = Join-Path $temporaryRoot (
                "$originName-" + [Guid]::NewGuid().ToString('N')
            )
            $downloadTimeout = if ($editionPaths.Contains($relativePath)) { 120 } else { 30 }
            Invoke-WebRequest `
                -Uri "$($snapshots[$originName].BaseUri)/$relativePath" `
                -UseBasicParsing -OutFile $downloadPath -TimeoutSec $downloadTimeout
            $actualHash = (Get-FileHash -LiteralPath $downloadPath `
                -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -cne $expectedHash) {
                throw "$originName differs from the shared artifact: $relativePath"
            }
            if ($relativePath -ceq 'downloads/latest.json') {
                $metadata = Get-Content -LiteralPath $downloadPath `
                    -Raw -Encoding UTF8 | ConvertFrom-Json
                $release = $snapshots[$originName].BuildManifest.release
                $releaseTag = [string]$release.releaseTag
                $fileName = [string]$release.fileName
                $expectedDownloadUrl =
                    "https://github.com/ChiZhang-805/DroneDream/releases/download/" +
                    "$releaseTag/$fileName"
                if ([string]$metadata.version -cne [string]$release.version -or
                    [string]$metadata.fileName -cne $fileName -or
                    ([string]$metadata.sha256).ToLowerInvariant() -cne
                        ([string]$release.sha256).ToLowerInvariant() -or
                    [long]$metadata.sizeBytes -ne [long]$release.sizeBytes -or
                    [string]$metadata.publishedAt -cne
                        [string]$release.publishedAt -or
                    [string]$metadata.downloadUrl -cne $expectedDownloadUrl -or
                    [string]$metadata.checksumUrl -cne
                        "$expectedDownloadUrl.sha256") {
                    throw "$originName downloads/latest.json does not match the shared release metadata."
                }
                $verifiedReleaseMetadata[$originName] = $metadata
            }
        }
        $verifiedPaths += $relativePath
    }
    if ($verifiedPaths.Count -lt 5 -or
        'downloads/latest.json' -notin $verifiedPaths -or
        $verifiedReleaseMetadata.Count -ne $originUris.Count) {
        throw "Parity verification did not cover enough HTML, JavaScript, CSS, and release metadata files."
    }
    $missingEditionPaths = @(
        $editionPaths | Where-Object { $_ -notin $verifiedPaths }
    )
    if ($missingEditionPaths.Count -ne 0) {
        throw "Parity verification missed edition artifact paths: $($missingEditionPaths -join ', ')"
    }

    $sourceCommit = [string]$snapshots.global.BuildManifest.sourceCommit
    Write-Host "Global and mirror manifests are identical."
    Write-Host "Source commit: $sourceCommit"
    Write-Host "Verified $($verifiedPaths.Count) shared-artifact files on both origins, including edition downloads."
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
