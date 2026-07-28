[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$Commit,

    [string]$Destination = "",

    [ValidateRange(0, [long]::MaxValue)]
    [long]$RunId = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $repositoryRoot "work\website-artifacts\$Commit"
}
$destinationFullPath = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destinationFullPath) {
    if (@(Get-ChildItem -LiteralPath $destinationFullPath -Force).Count -ne 0) {
        throw "Artifact destination must be empty: $destinationFullPath"
    }
} else {
    New-Item -ItemType Directory -Path $destinationFullPath -Force | Out-Null
}

$ghPath = (Get-Command gh.exe -ErrorAction Stop).Source
if ($RunId -eq 0) {
    $runsJson = & $ghPath api --method GET `
        'repos/ChiZhang-805/DroneDream/actions/workflows/pages.yml/runs' `
        -f "head_sha=$Commit" -f 'status=success' -f 'per_page=20'
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to query successful Pages workflow runs."
    }
    $runs = ($runsJson | ConvertFrom-Json).workflow_runs
    $matchingRun = @(
        $runs | Where-Object {
            [string]$_.head_sha -ceq $Commit -and
            [string]$_.conclusion -ceq 'success'
        } | Sort-Object run_number -Descending
    ) | Select-Object -First 1
    if ($null -eq $matchingRun) {
        throw "No successful Pages workflow run exists for commit $Commit."
    }
    $RunId = [long]$matchingRun.id
}

$artifactName = "dronedream-site-$Commit"
& $ghPath run download $RunId --repo ChiZhang-805/DroneDream `
    --name $artifactName --dir $destinationFullPath
if ($LASTEXITCODE -ne 0) {
    throw "Unable to download artifact $artifactName from workflow run $RunId."
}

$buildManifestPath = Join-Path $destinationFullPath 'build-manifest.json'
$integrityManifestPath = Join-Path $destinationFullPath 'SHA256SUMS'
if (-not (Test-Path -LiteralPath $buildManifestPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $integrityManifestPath -PathType Leaf)) {
    throw "The downloaded workflow artifact is missing its manifests."
}
$buildManifest = Get-Content -LiteralPath $buildManifestPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ([string]$buildManifest.artifactKind -cne
        'dronedream-shared-static-site' -or
    [string]$buildManifest.sourceCommit -cne $Commit) {
    throw "The downloaded artifact does not identify commit $Commit."
}

$artifactRoot = $destinationFullPath.TrimEnd('\', '/')
$artifactPrefix = "$artifactRoot$([IO.Path]::DirectorySeparatorChar)"
$entryCount = 0
foreach ($line in Get-Content -LiteralPath $integrityManifestPath -Encoding UTF8) {
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
        throw "SHA256SUMS contains an invalid entry."
    }
    $expectedHash = $Matches[1]
    $relativePath = $Matches[2]
    if ([IO.Path]::IsPathRooted($relativePath) -or
        $relativePath.Contains('\') -or
        $relativePath -match '(^|/)\.\.(/|$)') {
        throw "SHA256SUMS contains an unsafe path: $relativePath"
    }
    $artifactPath = [IO.Path]::GetFullPath(
        (Join-Path $artifactRoot ($relativePath.Replace('/', '\')))
    )
    if (-not $artifactPath.StartsWith(
            $artifactPrefix,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
        throw "SHA256SUMS references an invalid artifact path: $relativePath"
    }
    $actualHash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).
        Hash.ToLowerInvariant()
    if ($actualHash -cne $expectedHash) {
        throw "Downloaded artifact hash mismatch: $relativePath"
    }
    $entryCount++
}
if ($entryCount -eq 0) {
    throw "The downloaded artifact integrity manifest is empty."
}

Write-Host "Downloaded and verified $artifactName from workflow run $RunId."
Write-Host "Artifact directory: $destinationFullPath"
Write-Output $destinationFullPath
