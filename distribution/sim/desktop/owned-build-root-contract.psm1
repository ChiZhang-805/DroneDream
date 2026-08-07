Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NormalizedFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    [IO.Path]::GetFullPath($Path).TrimEnd("\")
}

function Assert-DirectoryIsNotReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Required canonical directory is missing or is not a directory: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force
    if ([bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Canonical directory must not be a reparse point: $Path"
    }
}

function Assert-CanonicalOwnedDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedPath,
        [Parameter(Mandatory = $true)][string]$AllowedRoot
    )

    $full = Get-NormalizedFullPath $Path
    $expected = Get-NormalizedFullPath $ExpectedPath
    $allowed = Get-NormalizedFullPath $AllowedRoot
    if (-not $full.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Canonical directory path drifted."
    }
    if (
        -not $full.Equals($allowed, [StringComparison]::OrdinalIgnoreCase) -and
        -not $full.StartsWith("$allowed\", [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Canonical directory escaped its allowed root."
    }

    Assert-DirectoryIsNotReparsePoint $allowed
    $cursor = $allowed
    $relative = $full.Substring($allowed.Length).TrimStart("\")
    if ($relative) {
        foreach ($segment in $relative.Split("\")) {
            if (-not $segment -or $segment -ceq "." -or $segment -ceq "..") {
                throw "Canonical directory contains an invalid path segment."
            }
            $cursor = Join-Path $cursor $segment
            Assert-DirectoryIsNotReparsePoint $cursor
        }
    }

    $resolved = Get-NormalizedFullPath (Resolve-Path -LiteralPath $full).Path
    if (-not $resolved.Equals($full, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Canonical directory resolved to a different path."
    }
    [ordered]@{
        passed = $true
        path = $full.Replace("\", "/")
        allowedRoot = $allowed.Replace("\", "/")
        pathType = "directory"
        reparsePoint = $false
    }
}

function Assert-ExclusiveAttemptPathAbsent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$CanonicalParent,
        [Parameter(Mandatory = $true)][string]$AllowedRoot
    )

    $parent = Get-NormalizedFullPath $CanonicalParent
    Assert-CanonicalOwnedDirectory -Path $parent -ExpectedPath $parent -AllowedRoot $AllowedRoot | Out-Null
    $full = Get-NormalizedFullPath $Path
    $declaredParent = Get-NormalizedFullPath (Split-Path -Parent $full)
    if (-not $declaredParent.Equals($parent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Attempt directory must be a direct child of its canonical parent."
    }
    if (Test-Path -LiteralPath $full) {
        throw "Attempt-specific path already exists."
    }
    [ordered]@{
        passed = $true
        path = $full.Replace("\", "/")
        canonicalParent = $parent.Replace("\", "/")
        absent = $true
    }
}

function New-ExclusiveAttemptDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$CanonicalParent,
        [Parameter(Mandatory = $true)][string]$AllowedRoot
    )

    $assertion = Assert-ExclusiveAttemptPathAbsent -Path $Path -CanonicalParent $CanonicalParent -AllowedRoot $AllowedRoot
    $full = Get-NormalizedFullPath $Path
    New-Item -ItemType Directory -Path $full -ErrorAction Stop | Out-Null
    Assert-DirectoryIsNotReparsePoint $full
    [ordered]@{
        passed = $true
        path = $assertion.path
        canonicalParent = $assertion.canonicalParent
        created = $true
        exclusive = $true
        forceUsed = $false
        reparsePoint = $false
    }
}

Export-ModuleMember -Function Assert-CanonicalOwnedDirectory, Assert-ExclusiveAttemptPathAbsent, New-ExclusiveAttemptDirectory
