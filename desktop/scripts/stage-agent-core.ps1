param(
    [string]$AgentCoreRepository,
    [ValidateSet("x86_64-pc-windows-msvc", "x86_64-pc-windows-gnullvm")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Copy-VerifiedManifestFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$TargetRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [long]$ExpectedBytes = -1
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        [IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "AGENT Core manifest contains an unsafe relative path: $RelativePath"
    }
    if ($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "AGENT Core manifest contains an invalid SHA-256: $RelativePath"
    }
    $sourceRootFull = [IO.Path]::GetFullPath($SourceRoot)
    $targetRootFull = [IO.Path]::GetFullPath($TargetRoot)
    $normalized = $RelativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $source = [IO.Path]::GetFullPath((Join-Path $sourceRootFull $normalized))
    $sourcePrefix = $sourceRootFull.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $source.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "AGENT Core manifest file is unavailable: $RelativePath"
    }
    $sourceItem = Get-Item -LiteralPath $source -Force
    if ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "AGENT Core manifest file must not be a reparse point: $RelativePath"
    }
    if ($ExpectedBytes -ge 0 -and $sourceItem.Length -ne $ExpectedBytes) {
        throw "AGENT Core manifest byte count does not match: $RelativePath"
    }
    $sourceSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
    if ($sourceSha256 -cne $ExpectedSha256) {
        throw "AGENT Core manifest SHA-256 does not match: $RelativePath"
    }

    $destination = [IO.Path]::GetFullPath((Join-Path $targetRootFull $normalized))
    $targetPrefix = $targetRootFull.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $destination.StartsWith($targetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stage outside the selected AGENT Core resource tree: $RelativePath"
    }
    $destinationParent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
    $stagedSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
    if ($stagedSha256 -cne $ExpectedSha256) {
        throw "Staged AGENT Core file failed post-copy verification: $RelativePath"
    }
}

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
if ([string]::IsNullOrWhiteSpace($AgentCoreRepository)) {
    $AgentCoreRepository = [Environment]::GetEnvironmentVariable(
        "DRONEDREAM_AGENT_CORE_REPOSITORY",
        "Process"
    )
}
if ([string]::IsNullOrWhiteSpace($AgentCoreRepository)) {
    throw (
        "The current private AGENT Core repository must be supplied with " +
        "-AgentCoreRepository or DRONEDREAM_AGENT_CORE_REPOSITORY. " +
        "Implicit checkout fallbacks are not allowed."
    )
}
$coreRoot = [IO.Path]::GetFullPath($AgentCoreRepository)
if (-not (Test-Path -LiteralPath $coreRoot -PathType Container)) {
    throw "The private DroneDream AGENT Core repository is unavailable: $coreRoot"
}
$embeddedCoreRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "autonomy-core"))
if ($coreRoot.TrimEnd('\', '/') -ieq $embeddedCoreRoot.TrimEnd('\', '/')) {
    throw (
        "The retired embedded autonomy-core snapshot is not a release input. " +
        "Stage the explicitly selected private AGENT Core repository instead."
    )
}

$coreCommit = (& git -C $coreRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $coreCommit -notmatch '^[0-9a-f]{40}$') {
    throw "The AGENT Core source commit could not be resolved."
}
$coreStatus = (& git -C $coreRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $coreStatus) {
    throw "The AGENT Core sidecar must be staged from one clean source commit."
}

$sourceRoot = Join-Path $coreRoot "app\desktop\src-tauri"
$sourceBinaryRoot = Join-Path $sourceRoot "binaries"
$sourceTriple = "x86_64-pc-windows-msvc"
$coreBinary = Join-Path $sourceBinaryRoot "dronedream-autonomy-core-$sourceTriple.exe"
$isolatorBinary = Join-Path $sourceBinaryRoot "dronedream-plugin-isolator-$sourceTriple.exe"
$sourceResources = Join-Path $sourceRoot "resources"
$required = @(
    $coreBinary,
    $isolatorBinary,
    (Join-Path $sourceResources "runtime\runtime-manifest.json"),
    (Join-Path $sourceResources "runtime\local-policy\catalog.json"),
    (Join-Path $sourceResources "official-plugins\index.json"),
    (Join-Path $sourceResources "default-assets\index.json"),
    (Join-Path $sourceResources "default-assets\school-map.ddpkg"),
    (Join-Path $sourceResources "default-assets\my-drone.ddpkg")
)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "The AGENT Core package is incomplete: $path"
    }
}

$targetBinaryRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "desktop\src-tauri\binaries"))
$targetResourceRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot "desktop\src-tauri\agent-core-resources"))
$allowedParent = [IO.Path]::GetFullPath((Join-Path $repoRoot "desktop\src-tauri"))
$allowedPrefix = $allowedParent.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
foreach ($target in @($targetBinaryRoot, $targetResourceRoot)) {
    if (-not $target.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stage outside desktop/src-tauri: $target"
    }
    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to replace an unsafe AGENT Core staging path: $target"
        }
        $nestedReparse = @(Get-ChildItem -LiteralPath $target -Force -Recurse | Where-Object {
            $_.Attributes -band [IO.FileAttributes]::ReparsePoint
        })
        if ($nestedReparse.Count -ne 0) {
            throw "Refusing to replace an AGENT Core staging tree containing reparse points: $target"
        }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    New-Item -ItemType Directory -Path $target | Out-Null
}

$stagedCoreName = "dronedream-autonomy-core-$TargetTriple.exe"
$stagedIsolatorName = "dronedream-plugin-isolator-$TargetTriple.exe"
Copy-Item -LiteralPath $coreBinary -Destination (Join-Path $targetBinaryRoot $stagedCoreName)
Copy-Item -LiteralPath $isolatorBinary -Destination (Join-Path $targetBinaryRoot $stagedIsolatorName)
Copy-Item -LiteralPath $isolatorBinary -Destination (Join-Path $targetResourceRoot "dronedream-plugin-isolator.exe")

$runtimeSource = Join-Path $sourceResources "runtime"
$runtimeTarget = Join-Path $targetResourceRoot "runtime"
$runtimeManifestPath = Join-Path $runtimeSource "runtime-manifest.json"
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
$runtimeEntries = @($runtimeManifest.files)
if (-not $runtimeManifest.files -or $runtimeEntries.Count -eq 0) {
    throw "The AGENT Core Runtime manifest contains no files."
}
$runtimePaths = @($runtimeEntries | ForEach-Object { [string]$_.path })
if ($runtimePaths -cnotcontains "local-policy/catalog.json") {
    throw "The AGENT Core Runtime manifest omits its local expert catalog."
}
if (@($runtimePaths | Where-Object {
    $_ -match '(^|/)__pycache__(/|$)' -or $_ -match '\.pyc$'
}).Count -ne 0) {
    throw "The AGENT Core Runtime manifest contains a Python cache."
}
$localPolicyCatalogPath = Join-Path $runtimeSource "local-policy\catalog.json"
$localPolicyCatalog = Get-Content -LiteralPath $localPolicyCatalogPath -Raw | ConvertFrom-Json
$localPolicyEntries = @($localPolicyCatalog.entries)
if ($localPolicyCatalog.schema_version -cne "dronedream.local-policy-runtime-catalog.v2" -or
    $localPolicyCatalog.deployment_scope -cnotin @("simulation-only", "production-qualified") -or
    $localPolicyEntries.Count -ne 1) {
    throw "The AGENT Core local expert catalog is not the current single-package contract."
}
$localPolicyReceiptKind = [string]$localPolicyEntries[0].receipt.kind
if (($localPolicyCatalog.deployment_scope -ceq "simulation-only" -and
        $localPolicyReceiptKind -cne "simulation-admission") -or
    ($localPolicyCatalog.deployment_scope -ceq "production-qualified" -and
        $localPolicyReceiptKind -cne "qualification")) {
    throw "The AGENT Core local expert catalog scope and receipt kind disagree."
}
New-Item -ItemType Directory -Path $runtimeTarget -Force | Out-Null
Copy-Item -LiteralPath $runtimeManifestPath -Destination (Join-Path $runtimeTarget "runtime-manifest.json")
foreach ($file in $runtimeEntries) {
    Copy-VerifiedManifestFile `
        -SourceRoot $runtimeSource `
        -TargetRoot $runtimeTarget `
        -RelativePath ([string]$file.path) `
        -ExpectedSha256 ([string]$file.sha256) `
        -ExpectedBytes ([long]$file.bytes)
}

$pluginSource = Join-Path $sourceResources "official-plugins"
$pluginTarget = Join-Path $targetResourceRoot "official-plugins"
$pluginIndexPath = Join-Path $pluginSource "index.json"
$pluginIndex = Get-Content -LiteralPath $pluginIndexPath -Raw | ConvertFrom-Json
if (-not $pluginIndex.plugins -or @($pluginIndex.plugins).Count -eq 0) {
    throw "The AGENT Core official plug-in index contains no packages."
}
New-Item -ItemType Directory -Path $pluginTarget -Force | Out-Null
Copy-Item -LiteralPath $pluginIndexPath -Destination (Join-Path $pluginTarget "index.json")
foreach ($plugin in @($pluginIndex.plugins)) {
    Copy-VerifiedManifestFile `
        -SourceRoot $pluginSource `
        -TargetRoot $pluginTarget `
        -RelativePath ([string]$plugin.file) `
        -ExpectedSha256 ([string]$plugin.sha256)
}

$assetSource = Join-Path $sourceResources "default-assets"
$assetTarget = Join-Path $targetResourceRoot "default-assets"
$assetIndexPath = Join-Path $assetSource "index.json"
$assetIndex = Get-Content -LiteralPath $assetIndexPath -Raw | ConvertFrom-Json
$assetPackages = @($assetIndex.qualified_pair.packages)
if ($assetPackages.Count -ne 2 -or
    @($assetPackages | Where-Object { $_.kind -eq "map" }).Count -ne 1 -or
    @($assetPackages | Where-Object { $_.kind -eq "vehicle" }).Count -ne 1) {
    throw "The AGENT Core default-asset index must contain one map and one vehicle package."
}
New-Item -ItemType Directory -Path $assetTarget -Force | Out-Null
Copy-Item -LiteralPath $assetIndexPath -Destination (Join-Path $assetTarget "index.json")
foreach ($asset in $assetPackages) {
    if ([IO.Path]::GetExtension([string]$asset.file) -cne ".ddpkg") {
        throw "The AGENT Core default-asset index may reference only current DDPKG packages."
    }
    Copy-VerifiedManifestFile `
        -SourceRoot $assetSource `
        -TargetRoot $assetTarget `
        -RelativePath ([string]$asset.file) `
        -ExpectedSha256 ([string]$asset.sha256)
}

$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-agent-core-stage"
    publicSourceCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
    agentCoreSourceCommit = $coreCommit
    targetTriple = $TargetTriple
    files = @(
        [ordered]@{
            name = $stagedCoreName
            bytes = (Get-Item -LiteralPath $coreBinary).Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $coreBinary).Hash.ToLowerInvariant()
        },
        [ordered]@{
            name = $stagedIsolatorName
            bytes = (Get-Item -LiteralPath $isolatorBinary).Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $isolatorBinary).Hash.ToLowerInvariant()
        }
    )
    resourceIndexSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (
        Join-Path $sourceResources "official-plugins\index.json"
    )).Hash.ToLowerInvariant()
    defaultAssetIndexSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (
        Join-Path $sourceResources "default-assets\index.json"
    )).Hash.ToLowerInvariant()
    localPolicyCatalogSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (
        Join-Path $sourceResources "runtime\local-policy\catalog.json"
    )).Hash.ToLowerInvariant()
    stagedAt = [DateTimeOffset]::UtcNow.ToString("o")
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (
    Join-Path $targetResourceRoot "agent-core-stage.json"
) -Encoding UTF8

Write-Host "Staged AGENT Core $coreCommit for $TargetTriple"
