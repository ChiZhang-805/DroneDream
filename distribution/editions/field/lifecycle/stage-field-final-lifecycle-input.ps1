param(
    [Parameter(Mandatory = $true)][string]$Application,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedApplicationSha256,
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-LfIdentity {
    param([Parameter(Mandatory = $true)][string]$Path)
    $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
    $bytes = [Text.Encoding]::UTF8.GetBytes($text.Replace("`r`n", "`n").Replace("`r", "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [ordered]@{
            bytes = $bytes.Length
            sha256 = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
        }
    } finally { $sha.Dispose() }
}

function Get-Identity {
    param([string]$Path, [string]$Mode)
    if ($Mode -ceq "lf-normalized") { return Get-LfIdentity -Path $Path }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Resolve-OwnedChild {
    param([string]$Base, [string]$Relative)
    if ([IO.Path]::IsPathRooted($Relative) -or $Relative.Contains("..") -or $Relative.Contains(":")) {
        throw "A staging relative path is unsafe."
    }
    $basePath = [IO.Path]::GetFullPath($Base).TrimEnd("\")
    $child = [IO.Path]::GetFullPath((Join-Path $basePath $Relative)).TrimEnd("\")
    if (-not ($child + "\").StartsWith($basePath + "\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "A staging path escaped its owned root."
    }
    return $child
}

$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$applicationHash = (Get-FileHash -LiteralPath $applicationPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($applicationHash -cne $ExpectedApplicationSha256) { throw "Application SHA-256 mismatch." }
$contract = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$adapterIdentity = Get-LfIdentity -Path $MyInvocation.MyCommand.Path
if ($contract.tools.stagingAdapter.lfNormalizedBytes -ne $adapterIdentity.bytes -or
    $contract.tools.stagingAdapter.lfNormalizedSha256 -cne $adapterIdentity.sha256) {
    throw "Application is not bound to this staging adapter."
}

$sourcePath = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd("\")
$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$allowedBase = [IO.Path]::GetFullPath("C:\Users\Public\DroneDream-Codex\Field-RED").TrimEnd("\")
if (-not ($outputPath + "\").StartsWith($allowedBase + "\", [StringComparison]::OrdinalIgnoreCase) -or
    $outputPath -cne [IO.Path]::GetFullPath($contract.isolation.stagingRoot).TrimEnd("\")) {
    throw "OutputRoot is not the frozen Field staging root."
}
if (Test-Path -LiteralPath $outputPath) { throw "Staging root already exists." }
if ($contract.attempt.stagingMaximum -ne 1 -or $contract.attempt.stagingAtFreeze -ne 0 -or
    $contract.attempt.retryMaximum -ne 0) { throw "Unsafe staging attempt contract." }

$validated = [Collections.Generic.List[object]]::new()
foreach ($input in @($contract.stagingInputs)) {
    $relative = [string]$input.relativePath
    if ($input.sourceClass -ceq "repository-relative") {
        $source = Resolve-OwnedChild -Base $sourcePath -Relative $relative
    } elseif ($input.sourceClass -ceq "exact-absolute") {
        $source = [IO.Path]::GetFullPath([string]$input.sourceAbsolutePath)
    } else { throw "Unknown staging source class." }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Staging input is missing: $relative" }
    $mode = if ($input.hashMode) { [string]$input.hashMode } else { "exact-bytes" }
    $identity = Get-Identity -Path $source -Mode $mode
    if ($identity.bytes -ne [long]$input.bytes -or $identity.sha256 -cne [string]$input.sha256) {
        throw "Staging input identity mismatch: $relative"
    }
    $validated.Add([ordered]@{ source = $source; relative = $relative; mode = $mode; identity = $identity })
}
$applicationRelative = [string]$contract.applicationSelfRelativePath
if ((Resolve-OwnedChild -Base $sourcePath -Relative $applicationRelative) -cne $applicationPath) {
    throw "Application must be staged from the exact source root."
}
$validated.Add([ordered]@{
    source = $applicationPath
    relative = $applicationRelative
    mode = "exact-bytes"
    identity = [ordered]@{ bytes = (Get-Item $applicationPath).Length; sha256 = $applicationHash }
})

if (-not $Execute) {
    [ordered]@{ result = "green-plan-only-no-write"; inputCount = $validated.Count; stagingRootCreated = $false } |
        ConvertTo-Json -Depth 5
    exit 0
}

New-Item -ItemType Directory -Path $outputPath | Out-Null
foreach ($input in $validated) {
    $destination = Resolve-OwnedChild -Base $outputPath -Relative $input.relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $input.source -Destination $destination
    $copied = Get-Identity -Path $destination -Mode $input.mode
    if ($copied.bytes -ne $input.identity.bytes -or $copied.sha256 -cne $input.identity.sha256) {
        throw "Copied staging input identity mismatch."
    }
}

[ordered]@{
    result = "staged-exact-inputs"
    stagingRoot = $outputPath
    inputCount = $validated.Count
    stagingInvocations = 1
} | ConvertTo-Json -Depth 5
