Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ForbiddenTransientRoots = @(
    "desktop/node_modules/.cache",
    "desktop/node_modules/.vite",
    "desktop/node_modules/.vite-temp",
    "frontend/node_modules/.cache",
    "frontend/node_modules/.vite",
    "frontend/node_modules/.vite-temp"
)

function Get-Sha256Lower {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function Get-OfflineDependencyInventory {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Root)

    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd("\")
    if (-not (Test-Path -LiteralPath $rootFull -PathType Container)) {
        throw "Dependency root is missing."
    }

    $entries = [Collections.Generic.List[object]]::new()
    foreach ($item in @(Get-ChildItem -LiteralPath $rootFull -Recurse -Force)) {
        $relative = $item.FullName.Substring($rootFull.Length + 1).Replace("\", "/")
        if ($relative -ceq "manifest.json") { continue }
        $isReparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
        $type = if ($isReparse) { "reparse" } elseif ($item.PSIsContainer) { "directory" } else { "file" }
        $entries.Add([ordered]@{
            path = $relative
            type = $type
            bytes = if ($type -ceq "file") { [UInt64]$item.Length } else { [UInt64]0 }
            sha256 = if ($type -ceq "file") { Get-Sha256Lower $item.FullName } else { $null }
            target = if ($isReparse) { [string]$item.Target } else { $null }
        })
    }

    $entriesByPath = @{}
    [string[]]$paths = @($entries.ToArray() | ForEach-Object {
        $entriesByPath[[string]$_.path] = $_
        [string]$_.path
    })
    [Array]::Sort($paths, [StringComparer]::Ordinal)
    $orderedEntries = [Collections.Generic.List[object]]::new()
    foreach ($path in $paths) {
        $orderedEntries.Add($entriesByPath[$path])
    }
    $entries = $orderedEntries

    $lines = @($entries | ForEach-Object {
        $sha = if ($null -eq $_.sha256) { "" } else { [string]$_.sha256 }
        $target = if ($null -eq $_.target) { "" } else { [string]$_.target }
        "$($_.path)|$($_.type)|$($_.bytes)|$sha|$target"
    })
    $files = @($entries | Where-Object { $_.type -ceq "file" })
    $directories = @($entries | Where-Object { $_.type -ceq "directory" })
    $reparsePoints = @($entries | Where-Object { $_.type -ceq "reparse" })
    [UInt64]$totalFileBytes = 0
    foreach ($file in $files) {
        $totalFileBytes += [UInt64]$file.bytes
    }
    [ordered]@{
        algorithm = "sha256-lines-v1"
        entries = @($entries)
        treeFingerprint = Get-Sha256Text ($lines -join "`n")
        entryCount = $entries.Count
        fileCount = $files.Count
        directoryCount = $directories.Count
        reparsePointCount = $reparsePoints.Count
        totalFileBytes = $totalFileBytes
    }
}

function Assert-CleanOfflineDependencyTree {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Inventory,
        [Parameter(Mandatory = $true)][string]$ExpectedTreeFingerprint,
        [Parameter(Mandatory = $true)][int]$ExpectedEntryCount,
        [Parameter(Mandatory = $true)][int]$ExpectedFileCount,
        [Parameter(Mandatory = $true)][int]$ExpectedDirectoryCount,
        [Parameter(Mandatory = $true)][UInt64]$ExpectedTotalFileBytes
    )

    if ([int]$Inventory.reparsePointCount -ne 0) {
        throw "Dependency tree contains a reparse point."
    }
    foreach ($entry in @($Inventory.entries)) {
        $path = [string]$entry.path
        foreach ($prefix in $script:ForbiddenTransientRoots) {
            if ($path -ceq $prefix -or $path.StartsWith("$prefix/", [StringComparison]::Ordinal)) {
                throw "Dependency tree contains a generated transient path: $path"
            }
        }
    }
    if ([string]$Inventory.treeFingerprint -cne $ExpectedTreeFingerprint) {
        throw "Dependency tree fingerprint drifted."
    }
    if (
        [int]$Inventory.entryCount -ne $ExpectedEntryCount -or
        [int]$Inventory.fileCount -ne $ExpectedFileCount -or
        [int]$Inventory.directoryCount -ne $ExpectedDirectoryCount -or
        [UInt64]$Inventory.totalFileBytes -ne $ExpectedTotalFileBytes
    ) {
        throw "Dependency tree inventory counts drifted."
    }
    [ordered]@{
        passed = $true
        authority = "clean-offline-npm-ci-output"
        transientPathsPresent = $false
        treeFingerprint = [string]$Inventory.treeFingerprint
        entryCount = [int]$Inventory.entryCount
        fileCount = [int]$Inventory.fileCount
        directoryCount = [int]$Inventory.directoryCount
        totalFileBytes = [UInt64]$Inventory.totalFileBytes
    }
}

Export-ModuleMember -Function Get-OfflineDependencyInventory, Assert-CleanOfflineDependencyTree
