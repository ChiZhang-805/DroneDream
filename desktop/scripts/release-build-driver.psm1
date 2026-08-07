Set-StrictMode -Version Latest

function Invoke-CheckedNativeCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$DisplayName = $FilePath
    )

    # Windows PowerShell 5.1 can promote a native process' stderr records to
    # terminating NativeCommandError exceptions when the caller uses Stop.
    # Native tools such as Tauri legitimately write progress to stderr, so the
    # process exit code is the authority. Keep stderr visible and restore every
    # preference before enforcing the non-zero fail-closed boundary.
    $previousErrorActionPreference = $ErrorActionPreference
    $nativePreferenceVariable = Get-Variable `
        -Name PSNativeCommandUseErrorActionPreference `
        -ErrorAction SilentlyContinue
    $previousNativePreference = if ($nativePreferenceVariable) {
        $nativePreferenceVariable.Value
    } else {
        $null
    }
    $nativeExitCode = $null
    try {
        $ErrorActionPreference = "Continue"
        if ($nativePreferenceVariable) {
            Set-Variable -Name PSNativeCommandUseErrorActionPreference -Value $false
        }
        & $FilePath @ArgumentList 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                # Preserve the native diagnostic text on stderr without
                # re-emitting a PowerShell NativeCommandError record.
                [Console]::Error.WriteLine($_.Exception.Message)
            } else {
                Write-Output $_
            }
        }
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($nativePreferenceVariable) {
            Set-Variable `
                -Name PSNativeCommandUseErrorActionPreference `
                -Value $previousNativePreference
        }
    }

    if ($null -eq $nativeExitCode -or $nativeExitCode -ne 0) {
        throw "$DisplayName failed with native exit code $nativeExitCode."
    }
}

function Resolve-EditionGeneratedFrontendContract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$BaseConfigPath,
        [string]$AdditionalConfigPath,
        [Parameter(Mandatory = $true)]
        [ValidateSet("universal", "sim", "lab", "field")]
        [string]$EditionId
    )

    $repoRootFull = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/')
    $baseConfigFull = (Resolve-Path -LiteralPath $BaseConfigPath -ErrorAction Stop).Path
    $expectedBaseConfig = [IO.Path]::GetFullPath(
        (Join-Path $repoRootFull "desktop\src-tauri\tauri.conf.json")
    )
    if (-not $baseConfigFull.Equals(
        $expectedBaseConfig,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "The canonical Tauri base config must be desktop/src-tauri/tauri.conf.json."
    }
    $baseConfig = Get-Content -LiteralPath $baseConfigFull -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $effectiveBuildConfig = $baseConfig.build
    if ($AdditionalConfigPath) {
        $additionalConfigFull = (
            Resolve-Path -LiteralPath $AdditionalConfigPath -ErrorAction Stop
        ).Path
        $additionalConfig = Get-Content `
            -LiteralPath $additionalConfigFull `
            -Raw `
            -Encoding UTF8 | ConvertFrom-Json
        $additionalHasBuild = $additionalConfig.PSObject.Properties.Name -ccontains "build"
        if ($additionalHasBuild -and
            $additionalConfig.build -and
            $additionalConfig.build.PSObject.Properties.Name -ccontains "frontendDist") {
            $effectiveBuildConfig = $additionalConfig.build
        }
    }

    if (-not $effectiveBuildConfig -or
        -not $effectiveBuildConfig.PSObject.Properties.Name -ccontains "frontendDist" -or
        -not $effectiveBuildConfig.frontendDist) {
        throw "The effective Tauri config does not declare build.frontendDist."
    }

    # Tauri --config files are merged into the canonical tauri.conf.json. A
    # relative frontendDist remains relative to that canonical config directory;
    # relocating an authorization overlay must never change path semantics.
    $canonicalConfigDirectory = Split-Path -Parent $baseConfigFull
    $frontendDistValue = [string]$effectiveBuildConfig.frontendDist
    $frontendDistCandidate = if ([IO.Path]::IsPathRooted($frontendDistValue)) {
        $frontendDistValue
    } else {
        Join-Path $canonicalConfigDirectory $frontendDistValue
    }
    $frontendDistFull = [IO.Path]::GetFullPath(
        $frontendDistCandidate
    ).TrimEnd('\', '/')
    $repoPrefix = "$repoRootFull\"
    if (-not $frontendDistFull.StartsWith(
        $repoPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "The frontend build output must remain inside the repository."
    }
    $frontendDistRelative = $frontendDistFull.Substring($repoPrefix.Length).
        Replace('\', '/')

    # Universal and the current shared-core Sim/Lab overlays use the canonical
    # Vite dist. Dedicated Edition frontends may use only their namespaced
    # directory. Field already uses field-dist. No arbitrary config path is an
    # accepted source-cleanliness exemption.
    $allowedRelativePaths = switch ($EditionId) {
        "universal" { @("frontend/dist") }
        "sim" { @("frontend/dist", "frontend/sim-dist") }
        "lab" { @("frontend/dist", "frontend/lab-dist") }
        "field" { @("frontend/field-dist") }
    }
    if ($frontendDistRelative -cnotin $allowedRelativePaths) {
        throw (
            "The $EditionId frontendDist '$frontendDistRelative' is outside " +
            "the explicit generated-output contract."
        )
    }

    [pscustomobject]@{
        editionId = $EditionId
        relativePath = $frontendDistRelative
        absolutePath = $frontendDistFull
    }
}

function Test-PostBuildSourceStatus {
    [CmdletBinding()]
    param(
        [string[]]$StatusLines = @(),
        [Parameter(Mandatory = $true)]
        [string]$AllowedGeneratedPath
    )

    $allowedPath = $AllowedGeneratedPath.TrimEnd('/').Replace('\', '/')
    if ($allowedPath -notmatch '^frontend/(?:dist|sim-dist|lab-dist|field-dist)$') {
        throw "The generated frontend path is not an approved release-build path."
    }

    $allowedGenerated = New-Object System.Collections.Generic.List[string]
    $unexpected = New-Object System.Collections.Generic.List[string]
    foreach ($statusLineValue in @($StatusLines)) {
        $statusLine = [string]$statusLineValue
        if (-not $statusLine) {
            continue
        }
        if ($statusLine.Length -lt 4) {
            $unexpected.Add($statusLine)
            continue
        }
        $statusCode = $statusLine.Substring(0, 2)
        $statusPath = $statusLine.Substring(3).Replace('\', '/')
        $isExactGeneratedFile = $statusCode -ceq '??' -and
            $statusPath.StartsWith(
                "$allowedPath/",
                [StringComparison]::Ordinal
            )
        if ($isExactGeneratedFile) {
            $allowedGenerated.Add($statusLine)
        } else {
            # Tracked changes inside the dist, untracked files elsewhere,
            # renames, and malformed/quoted paths all remain release blockers.
            $unexpected.Add($statusLine)
        }
    }

    [pscustomobject]@{
        allowedGeneratedCount = $allowedGenerated.Count
        allowedGenerated = @($allowedGenerated)
        unexpectedCount = $unexpected.Count
        unexpected = @($unexpected)
    }
}

function Test-PathIsWithinRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [switch]$AllowEqual
    )

    $pathFull = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    if ($AllowEqual -and $pathFull.Equals(
        $rootFull,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        return $true
    }
    return $pathFull.StartsWith(
        "$rootFull\",
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Resolve-DetachedNodeDependencyMountContract {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$OwnedBase,
        [Parameter(Mandatory = $true)]
        [string]$DependencyRoot,
        [Parameter(Mandatory = $true)]
        [object[]]$Mounts,
        [Parameter(Mandatory = $true)]
        [string]$FrontendDistPath,
        [Parameter(Mandatory = $true)]
        [string]$InstallerBundlePath,
        [switch]$InspectFileSystem
    )

    $repoRootFull = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/')
    $ownedBaseFull = [IO.Path]::GetFullPath($OwnedBase).TrimEnd('\', '/')
    $dependencyRootFull = [IO.Path]::GetFullPath($DependencyRoot).TrimEnd('\', '/')
    if (-not (Test-PathIsWithinRoot -Path $dependencyRootFull -Root $ownedBaseFull)) {
        throw "The dependency root must remain inside the exact owned base."
    }
    if (Test-PathIsWithinRoot -Path $dependencyRootFull -Root $repoRootFull -AllowEqual) {
        throw "The dependency root must remain outside the release source worktree."
    }

    foreach ($outputPath in @($FrontendDistPath, $InstallerBundlePath)) {
        $outputFull = [IO.Path]::GetFullPath($outputPath).TrimEnd('\', '/')
        if ((Test-PathIsWithinRoot -Path $outputFull -Root $dependencyRootFull -AllowEqual) -or
            (Test-PathIsWithinRoot -Path $dependencyRootFull -Root $outputFull -AllowEqual)) {
            throw "The dependency root must not overlap frontendDist or installer output."
        }
    }

    $expected = @(
        [pscustomobject]@{
            linkPath = "desktop/node_modules"
            targetPath = "desktop/node_modules"
            linkType = "junction"
        },
        [pscustomobject]@{
            linkPath = "frontend/node_modules"
            targetPath = "frontend/node_modules"
            linkType = "junction"
        }
    )
    if (@($Mounts).Count -ne $expected.Count) {
        throw "Exactly two detached dependency junctions are required."
    }

    $resolved = @()
    for ($index = 0; $index -lt $expected.Count; $index += 1) {
        $actual = @($Mounts)[$index]
        $wanted = $expected[$index]
        if ([string]$actual.linkPath -cne $wanted.linkPath -or
            [string]$actual.targetPath -cne $wanted.targetPath -or
            [string]$actual.linkType -cne $wanted.linkType) {
            throw "Detached dependency junction $index does not match the allowlist."
        }
        $linkFull = [IO.Path]::GetFullPath(
            (Join-Path $repoRootFull ([string]$actual.linkPath))
        ).TrimEnd('\', '/')
        $targetFull = [IO.Path]::GetFullPath(
            (Join-Path $dependencyRootFull ([string]$actual.targetPath))
        ).TrimEnd('\', '/')
        if (-not (Test-PathIsWithinRoot -Path $linkFull -Root $repoRootFull)) {
            throw "A detached dependency junction escapes the release source."
        }
        if (-not (Test-PathIsWithinRoot -Path $targetFull -Root $dependencyRootFull)) {
            throw "A detached dependency junction target escapes the bundle root."
        }

        if ($InspectFileSystem) {
            $linkItem = Get-Item -LiteralPath $linkFull -Force -ErrorAction Stop
            if (-not ($linkItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                [string]$linkItem.LinkType -cne "Junction") {
                throw "The detached dependency mount is not an exact junction: $linkFull"
            }
            $observedTargets = @($linkItem.Target)
            if ($observedTargets.Count -ne 1) {
                throw "The detached dependency junction has an ambiguous target: $linkFull"
            }
            $observedTargetValue = [string]$observedTargets[0]
            $observedTargetCandidate = if ([IO.Path]::IsPathRooted($observedTargetValue)) {
                $observedTargetValue
            } else {
                Join-Path (Split-Path -Parent $linkFull) $observedTargetValue
            }
            $observedTarget = [IO.Path]::GetFullPath(
                $observedTargetCandidate
            ).TrimEnd('\', '/')
            if (-not $observedTarget.Equals(
                $targetFull,
                [StringComparison]::OrdinalIgnoreCase
            )) {
                throw "The detached dependency junction target differs from the manifest."
            }
        }

        $resolved += [pscustomobject]@{
            linkPath = [string]$actual.linkPath
            linkAbsolutePath = $linkFull
            targetPath = [string]$actual.targetPath
            targetAbsolutePath = $targetFull
            linkType = "junction"
        }
    }

    [pscustomobject]@{
        mountCount = $resolved.Count
        mounts = $resolved
        dependencyRoot = $dependencyRootFull
        liveMountValidated = [bool]$InspectFileSystem
    }
}

function Test-DetachedDependencyPayloadIsolation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$OutputPaths
    )

    $violations = @()
    foreach ($outputPath in @($OutputPaths)) {
        if (-not (Test-Path -LiteralPath $outputPath)) {
            continue
        }
        $outputFull = [IO.Path]::GetFullPath($outputPath).TrimEnd('\', '/')
        $pending = New-Object System.Collections.Generic.Stack[string]
        $pending.Push($outputFull)
        while ($pending.Count -gt 0) {
            $current = $pending.Pop()
            foreach ($item in @(Get-ChildItem -LiteralPath $current -Force)) {
                $relative = $item.FullName.Substring($outputFull.Length).
                    TrimStart('\', '/').Replace('\', '/')
                $segments = @($relative -split '/')
                $isReparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
                $isDependencyManifest = $item.Name -ceq "desktop-node-dependency-bundle.json"
                if (-not $isDependencyManifest -and
                    -not $item.PSIsContainer -and
                    $item.Name -ceq "manifest.json" -and
                    $item.Length -le 1048576) {
                    $manifestPrefix = Get-Content -LiteralPath $item.FullName -Raw -Encoding UTF8
                    $isDependencyManifest = $manifestPrefix -match (
                        '"kind"\s*:\s*"dronedream-desktop-node-dependency-bundle"'
                    )
                }
                if ($segments -contains "node_modules" -or
                    $isDependencyManifest -or
                    $isReparse) {
                    $violations += $item.FullName
                }
                if ($item.PSIsContainer -and -not $isReparse) {
                    $pending.Push($item.FullName)
                }
            }
        }
    }
    [pscustomobject]@{
        violationCount = $violations.Count
        violations = $violations
    }
}

function Remove-ExactEmptyDetachedBuildScratch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DependencyRoot
    )

    $dependencyRootFull = (
        Resolve-Path -LiteralPath $DependencyRoot -ErrorAction Stop
    ).Path.TrimEnd('\', '/')
    $scratchPath = Join-Path $dependencyRootFull "frontend\node_modules\.vite-temp"
    if (-not (Test-Path -LiteralPath $scratchPath)) {
        return [pscustomobject]@{
            removed = $false
            relativePath = "frontend/node_modules/.vite-temp"
        }
    }

    $scratch = Get-Item -LiteralPath $scratchPath -Force
    if (-not $scratch.PSIsContainer) {
        throw "The exact Vite build scratch path is not a directory."
    }
    if ([bool]($scratch.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "The exact Vite build scratch directory must not be a reparse point."
    }
    if (@(Get-ChildItem -LiteralPath $scratch.FullName -Force).Count -ne 0) {
        throw "The exact Vite build scratch directory is not empty."
    }

    [IO.Directory]::Delete($scratch.FullName, $false)
    [pscustomobject]@{
        removed = $true
        relativePath = "frontend/node_modules/.vite-temp"
    }
}

Export-ModuleMember -Function @(
    "Invoke-CheckedNativeCommand",
    "Resolve-EditionGeneratedFrontendContract",
    "Test-PostBuildSourceStatus",
    "Test-PathIsWithinRoot",
    "Resolve-DetachedNodeDependencyMountContract",
    "Test-DetachedDependencyPayloadIsolation",
    "Remove-ExactEmptyDetachedBuildScratch"
)
