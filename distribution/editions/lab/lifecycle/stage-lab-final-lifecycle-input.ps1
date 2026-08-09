param(
    [Parameter(Mandatory = $true)]
    [string]$Application,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedApplicationSha256,
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Get-SafeFullPath {
    param(
        [Parameter(Mandatory = $true)][string]$Base,
        [Parameter(Mandatory = $true)][string]$Relative
    )

    if ([IO.Path]::IsPathRooted($Relative) -or
        $Relative.Contains("..") -or
        $Relative.StartsWith("\\") -or
        $Relative.Contains(":")) {
        throw "Staging paths must be simple relative paths without traversal."
    }
    $basePath = [IO.Path]::GetFullPath($Base).TrimEnd("\")
    $fullPath = [IO.Path]::GetFullPath((Join-Path $basePath $Relative)).TrimEnd("\")
    if (-not ($fullPath + "\").StartsWith(
        $basePath + "\",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "A staging path escaped its owned root."
    }
    return $fullPath
}

function Get-InputIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$HashMode
    )

    if ($HashMode -ceq "exact-bytes") {
        $item = Get-Item -LiteralPath $Path
        return [ordered]@{
            bytes = $item.Length
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    if ($HashMode -ceq "lf-normalized") {
        $text = [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false))
        $normalized = $text.Replace("`r`n", "`n").Replace("`r", "`n")
        $bytes = [Text.Encoding]::UTF8.GetBytes($normalized)
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            return [ordered]@{
                bytes = $bytes.Length
                sha256 = ([BitConverter]::ToString(
                    $sha.ComputeHash($bytes)
                )).Replace("-", "").ToLowerInvariant()
            }
        } finally {
            $sha.Dispose()
        }
    }
    throw "Unknown lifecycle staging hash mode."
}

$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$applicationSha256 = (Get-FileHash -LiteralPath $applicationPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($applicationSha256 -cne $ExpectedApplicationSha256) {
    throw "The lifecycle application SHA-256 does not match."
}
$applicationObject = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$stagingAdapterIdentity = Get-InputIdentity `
    -Path $MyInvocation.MyCommand.Path `
    -HashMode "lf-normalized"
if ($applicationObject.executionTools.stagingAdapter.lfNormalizedBytes -ne
        $stagingAdapterIdentity.bytes -or
    $applicationObject.executionTools.stagingAdapter.lfNormalizedSha256 -cne
        $stagingAdapterIdentity.sha256) {
    throw "The lifecycle application is not bound to this staging adapter."
}

$sourcePath = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd("\")
$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$allowedBase = [IO.Path]::GetFullPath("C:\Users\Public\DroneDream-Codex\Lab-RED").TrimEnd("\")
if (-not ($outputPath + "\").StartsWith(
    $allowedBase + "\",
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "OutputRoot must be a fresh child of the public Lab RED staging base."
}
if ($outputPath -cne [IO.Path]::GetFullPath(
    $applicationObject.ownedIsolation.stagingRoot
).TrimEnd("\")) {
    throw "OutputRoot does not match the frozen lifecycle application."
}
if (Test-Path -LiteralPath $outputPath) {
    throw "OutputRoot already exists; refusing to reuse lifecycle staging."
}
if ($applicationObject.ownedIsolation.staging.maximumInvocations -ne 1 -or
    $applicationObject.ownedIsolation.staging.invocationsAtFreeze -ne 0 -or
    $applicationObject.ownedIsolation.staging.automaticRetryMaximum -ne 0 -or
    $applicationObject.ownedIsolation.staging.additionalInputsAllowed -ne $false) {
    throw "The one-shot staging contract is missing or unsafe."
}

$validatedInputs = @()
foreach ($inputFile in @($applicationObject.ownedIsolation.staging.inputs)) {
    $relativePath = [string]$inputFile.relativePath
    if ($inputFile.sourceClass -ceq "repository-relative") {
        $sourceFile = Get-SafeFullPath -Base $sourcePath -Relative $relativePath
    } elseif ($inputFile.sourceClass -ceq "exact-absolute-artifact") {
        $absoluteSource = [string]$inputFile.sourceAbsolutePath
        if (-not [IO.Path]::IsPathRooted($absoluteSource) -or
            $absoluteSource.StartsWith("\\") -or
            $relativePath -cne "artifact/DroneDream-Lab-1.0.0.exe") {
            throw "The frozen artifact staging source is not a safe local absolute path."
        }
        $sourceFile = [IO.Path]::GetFullPath($absoluteSource)
    } else {
        throw "Unknown lifecycle staging input source class."
    }
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
        throw "A required lifecycle staging input is missing."
    }
    $hashMode = if ([string]::IsNullOrWhiteSpace([string]$inputFile.hashMode)) {
        "exact-bytes"
    } else {
        [string]$inputFile.hashMode
    }
    $identity = Get-InputIdentity -Path $sourceFile -HashMode $hashMode
    if ($identity.bytes -ne [long]$inputFile.bytes -or
        $identity.sha256 -cne [string]$inputFile.sha256) {
        throw "A lifecycle staging input does not match its frozen bytes and SHA-256."
    }
    $validatedInputs += [ordered]@{
        relativePath = $relativePath
        sourcePath = $sourceFile
        hashMode = $hashMode
        bytes = $identity.bytes
        sha256 = $identity.sha256
    }
}
$applicationRelativePath = [string](
    $applicationObject.ownedIsolation.staging.applicationSelfRelativePath
)
if ($applicationRelativePath -cne
    "distribution/editions/lab/lifecycle/final-ba6dc119-app-only-application.v1.json") {
    throw "The lifecycle application staging destination is not canonical."
}
$expectedApplicationSource = Get-SafeFullPath `
    -Base $sourcePath `
    -Relative $applicationRelativePath
if ($expectedApplicationSource -cne $applicationPath) {
    throw "The lifecycle application must be staged from the exact source root."
}
$validatedInputs += [ordered]@{
    relativePath = $applicationRelativePath
    sourcePath = $applicationPath
    hashMode = "exact-bytes"
    bytes = (Get-Item -LiteralPath $applicationPath).Length
    sha256 = $applicationSha256
}

if (-not $Execute) {
    [ordered]@{
        result = "green-plan-only-staging-preflight-passed-no-copy"
        applicationSha256 = $applicationSha256
        outputRoot = $outputPath
        outputRootCreated = $false
        validatedInputCount = $validatedInputs.Count
        stagingInvocations = 0
    } | ConvertTo-Json -Depth 5
    exit 0
}

New-Item -ItemType Directory -Path $outputPath | Out-Null
foreach ($inputFile in $validatedInputs) {
    $destination = Get-SafeFullPath -Base $outputPath -Relative $inputFile.relativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $inputFile.sourcePath -Destination $destination
    $copiedIdentity = Get-InputIdentity `
        -Path $destination `
        -HashMode $inputFile.hashMode
    if ($copiedIdentity.bytes -ne $inputFile.bytes -or
        $copiedIdentity.sha256 -cne $inputFile.sha256) {
        throw "A copied lifecycle staging input failed exact-byte verification."
    }
}

[ordered]@{
    result = "staging-inputs-copied-and-verified"
    applicationSha256 = $applicationSha256
    outputRoot = $outputPath
    outputRootCreated = $true
    validatedInputCount = $validatedInputs.Count
    stagingInvocations = 1
} | ConvertTo-Json -Depth 5
