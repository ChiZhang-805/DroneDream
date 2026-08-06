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

Export-ModuleMember -Function @(
    "Invoke-CheckedNativeCommand",
    "Resolve-EditionGeneratedFrontendContract",
    "Test-PostBuildSourceStatus"
)
