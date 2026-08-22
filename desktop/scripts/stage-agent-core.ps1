param(
    [string]$AgentCoreRepository,
    [ValidateSet("x86_64-pc-windows-msvc", "x86_64-pc-windows-gnullvm")]
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
if ([string]::IsNullOrWhiteSpace($AgentCoreRepository)) {
    $AgentCoreRepository = [Environment]::GetEnvironmentVariable(
        "DRONEDREAM_AGENT_CORE_REPOSITORY",
        "Process"
    )
}
if ([string]::IsNullOrWhiteSpace($AgentCoreRepository)) {
    $documents = [Environment]::GetFolderPath([Environment+SpecialFolder]::MyDocuments)
    $AgentCoreRepository = Join-Path $documents "Codex\DroneDream-Flight-Agent-Core"
}
$coreRoot = [IO.Path]::GetFullPath($AgentCoreRepository)
if (-not (Test-Path -LiteralPath $coreRoot -PathType Container)) {
    throw "The private DroneDream AGENT Core repository is unavailable: $coreRoot"
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
    (Join-Path $sourceResources "official-plugins\index.json"),
    (Join-Path $sourceResources "default-assets\index.json"),
    (Join-Path $sourceResources "default-assets\school-map.zip"),
    (Join-Path $sourceResources "default-assets\my-drone.zip"),
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
foreach ($name in @("runtime", "official-plugins", "default-assets")) {
    Copy-Item -LiteralPath (Join-Path $sourceResources $name) -Destination $targetResourceRoot -Recurse
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
    stagedAt = [DateTimeOffset]::UtcNow.ToString("o")
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (
    Join-Path $targetResourceRoot "agent-core-stage.json"
) -Encoding UTF8

Write-Host "Staged AGENT Core $coreCommit for $TargetTriple"
