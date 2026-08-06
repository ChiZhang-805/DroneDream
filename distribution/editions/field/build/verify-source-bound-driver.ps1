param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $true)]
    [string]$SourceCommit,

    [Parameter(Mandatory = $true)]
    [string]$RelativePath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedGitBlob,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedCanonicalSha256
)

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-GitText([string[]]$Arguments) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git.exe"
    $quoted = @("-C", (Quote-ProcessArgument $script:resolvedRepo))
    $quoted += @($Arguments | ForEach-Object { Quote-ProcessArgument $_ })
    $startInfo.Arguments = $quoted -join " "
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Git command failed ($($process.ExitCode)): $($stderr.Trim())"
    }
    return $stdout.Trim()
}

function Get-GitBlobSha256([string]$Blob) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git.exe"
    $startInfo.Arguments = @(
        "-C",
        (Quote-ProcessArgument $script:resolvedRepo),
        "cat-file",
        "blob",
        (Quote-ProcessArgument $Blob)
    ) -join " "
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($process.StandardOutput.BaseStream)
    } finally {
        $sha256.Dispose()
    }
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Unable to read canonical Git blob bytes: $($stderr.Trim())"
    }
    return ([BitConverter]::ToString($digest) -replace "-", "").ToLowerInvariant()
}

Assert-Contract (Test-Path -PathType Container -LiteralPath $RepoRoot) `
    "Source repository does not exist."
$script:resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
Assert-Contract ($SourceCommit -cmatch '^[0-9a-f]{40}$') `
    "Source commit must be an exact lowercase 40-character object ID."
Assert-Contract ($ExpectedGitBlob -cmatch '^[0-9a-f]{40}$') `
    "Expected Git blob must be an exact lowercase 40-character object ID."
Assert-Contract ($ExpectedCanonicalSha256 -cmatch '^[0-9a-f]{64}$') `
    "Expected canonical SHA-256 must be lowercase hexadecimal."

$normalizedPath = $RelativePath.Replace("\", "/")
Assert-Contract ($normalizedPath -ceq "desktop/scripts/release-build-driver.psm1") `
    "Only the canonical shared release driver may be verified."
Assert-Contract (-not [IO.Path]::IsPathRooted($RelativePath)) `
    "Source-bound path must be repository-relative."
Assert-Contract (-not (@($normalizedPath.Split("/")) -contains "..")) `
    "Source-bound path must not escape the repository."
$candidatePath = [IO.Path]::GetFullPath((Join-Path $script:resolvedRepo $normalizedPath))
$ownedPrefix = $script:resolvedRepo.TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar
Assert-Contract ($candidatePath.StartsWith($ownedPrefix, [StringComparison]::OrdinalIgnoreCase)) `
    "Source-bound path escaped the repository."
Assert-Contract (Test-Path -PathType Leaf -LiteralPath $candidatePath) `
    "Source-bound driver is unavailable in the working tree."

$resolvedCommit = Invoke-GitText @("rev-parse", "--verify", "$SourceCommit^{commit}")
Assert-Contract ($resolvedCommit -ceq $SourceCommit) "Unknown or ambiguous source commit."
$head = Invoke-GitText @("rev-parse", "HEAD")
Assert-Contract ($head -ceq $SourceCommit) "Working tree HEAD is not the approved source commit."
$status = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
Assert-Contract (-not $status) "Approved source working tree is not clean."

$actualBlob = Invoke-GitText @("rev-parse", "$SourceCommit`:$normalizedPath")
Assert-Contract ($actualBlob -ceq $ExpectedGitBlob) `
    "Canonical release driver Git blob drifted."
$canonicalSha256 = Get-GitBlobSha256 $actualBlob
Assert-Contract ($canonicalSha256 -ceq $ExpectedCanonicalSha256) `
    "Canonical release driver content SHA-256 drifted."

$result = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-source-bound-driver-verification"
    decision = "pass"
    validationBasis = "exact-source-git-blob-and-canonical-blob-bytes"
    sourceCommit = $SourceCommit
    relativePath = $normalizedPath
    gitBlob = $actualBlob
    canonicalBlobSha256 = $canonicalSha256
    workingTreePath = $candidatePath
    workingTreeSha256Informational = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $candidatePath
    ).Hash.ToLowerInvariant()
    workingTreeRepresentationGrantsAuthority = $false
    sourceClean = $true
}
$result | ConvertTo-Json -Depth 5
