[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)]
    [string]$HandoffRoot,
    [string]$Repository = "ChiZhang-805/DroneDream",
    [ValidateRange(0, 10)]
    [int]$RollbackBuildsToKeep = 1,
    [switch]$PruneObsoleteReleases
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$handoffRootFull = [IO.Path]::GetFullPath($HandoffRoot)
if (-not (Test-Path -LiteralPath $handoffRootFull -PathType Container)) {
    throw "Five-edition handoff root does not exist: $handoffRootFull"
}
if ($Repository -cnotmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "Repository must use owner/name syntax."
}
if ($RollbackBuildsToKeep -ne 1) {
    throw "Public retention requires exactly one rollback five-edition build."
}
if (-not $PruneObsoleteReleases) {
    throw "Publishing requires -PruneObsoleteReleases so Releases and Tags remain exact."
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI is required."
}

function Invoke-GitHubCli {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = (& gh @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "gh $($Arguments -join ' ') failed: $output"
    }
    return $output
}

function Get-ReleaseOrNull {
    param([Parameter(Mandatory = $true)][string]$Tag)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        $output = (& gh release view $Tag --repo $Repository --json tagName,assets,isDraft,isPrerelease 2>$null | Out-String).Trim()
        $releaseViewExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($releaseViewExitCode -ne 0) {
        return $null
    }
    return $output | ConvertFrom-Json
}

function Assert-ExactStringSet {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string[]]$Actual,
        [Parameter(Mandatory = $true)][string[]]$Expected
    )
    $actualSorted = @($Actual | Sort-Object -Unique)
    $expectedSorted = @($Expected | Sort-Object -Unique)
    $difference = @(Compare-Object -ReferenceObject $expectedSorted -DifferenceObject $actualSorted)
    if ($difference.Count -ne 0) {
        $rendered = ($difference | ForEach-Object { "$($_.SideIndicator) $($_.InputObject)" }) -join "; "
        throw "$Label drifted from the exact public retention set: $rendered"
    }
}

$familyContractPath = Join-Path $repoRoot "distribution\desktop\edition-runtime-update-families.v1.json"
$familyContract = Get-Content -LiteralPath $familyContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$version = [string]$familyContract.productDisplayVersion
$editionIds = @("universal", "sim", "lab", "field", "autonomy")
$stageRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "dronedream-five-release-" + [Guid]::NewGuid().ToString("N")
)
[IO.Directory]::CreateDirectory($stageRoot) | Out-Null

try {
    $releaseAssets = [Collections.Generic.List[string]]::new()
    $channelManifests = @{}
    $buildNumber = $null
    $sourceCommit = $null

    foreach ($editionId in $editionIds) {
        $family = @($familyContract.editions | Where-Object { $_.editionId -ceq $editionId })
        if ($family.Count -ne 1) {
            throw "Edition $editionId must resolve to one release family."
        }
        $editionRoot = Join-Path $handoffRootFull $editionId
        $receiptPath = Join-Path $editionRoot "build-receipt.json"
        if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
            throw "Build receipt is missing for $editionId."
        }
        $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$receipt.kind -cne "dronedream-five-edition-build-receipt" -or
            [string]$receipt.editionId -cne $editionId -or
            [string]$receipt.version -cne $version -or
            [string]$receipt.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or
            [UInt64]$receipt.buildNumber -eq 0) {
            throw "Build receipt identity is invalid for $editionId."
        }
        if ($null -eq $buildNumber) {
            $buildNumber = [UInt64]$receipt.buildNumber
            $sourceCommit = [string]$receipt.sourceCommit
        } elseif ([UInt64]$receipt.buildNumber -ne $buildNumber -or
            [string]$receipt.sourceCommit -cne $sourceCommit) {
            throw "All five installers must come from the same source commit and build number."
        }

        $installerName = [string]$family[0].tauriBundleInstallerFileName
        $installerPath = Join-Path $editionRoot $installerName
        $signaturePath = "$installerPath.sig"
        $checksumPath = "$installerPath.sha256"
        foreach ($requiredPath in @($installerPath, $signaturePath, $checksumPath)) {
            if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
                throw "Release input is missing: $requiredPath"
            }
        }
        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installerPath).Hash.ToLowerInvariant()
        $checksumLine = (Get-Content -LiteralPath $checksumPath -Raw -Encoding ASCII).Trim()
        if ($checksumLine -cnotmatch "^$actualHash\s+") {
            throw "Checksum mismatch for $installerName."
        }
        if ([string]$receipt.installer.fileName -cne $installerName -or
            [string]$receipt.installer.sha256 -cne $actualHash -or
            [Int64]$receipt.installer.bytes -ne (Get-Item -LiteralPath $installerPath).Length -or
            -not [bool]$receipt.installer.updaterSignature) {
            throw "Build receipt does not bind the exact installer for $editionId."
        }

        $editionStage = Join-Path $stageRoot $editionId
        [IO.Directory]::CreateDirectory($editionStage) | Out-Null
        $stagedInstaller = Join-Path $editionStage $installerName
        Copy-Item -LiteralPath $installerPath -Destination $stagedInstaller -WhatIf:$false
        Copy-Item -LiteralPath $signaturePath -Destination "$stagedInstaller.sig" -WhatIf:$false
        Copy-Item -LiteralPath $checksumPath -Destination "$stagedInstaller.sha256" -WhatIf:$false
        Copy-Item -LiteralPath $receiptPath -Destination "$stagedInstaller.receipt.json" -WhatIf:$false
        foreach ($assetPath in @(
            $stagedInstaller,
            "$stagedInstaller.sig",
            "$stagedInstaller.sha256",
            "$stagedInstaller.receipt.json"
        )) {
            $releaseAssets.Add($assetPath)
        }
    }

    $releaseTag = "five-edition-v${version}-build-${buildNumber}"
    foreach ($editionId in $editionIds) {
        $editionStage = Join-Path $stageRoot $editionId
        & (Join-Path $PSScriptRoot "write-updater-manifest.ps1") `
            -BundleDirectory $editionStage `
            -Repository $Repository `
            -EditionId $editionId `
            -SourceCommit $sourceCommit `
            -BuildNumber $buildNumber `
            -CombinedReleaseTag $releaseTag
        $channelManifests[$editionId] = Join-Path $editionStage "latest-$editionId.json"
    }

    $expectedAssetNames = @($releaseAssets | ForEach-Object { [IO.Path]::GetFileName($_) } | Sort-Object)
    $release = Get-ReleaseOrNull -Tag $releaseTag
    if ($null -eq $release) {
        if ($PSCmdlet.ShouldProcess("$Repository release $releaseTag", "create and upload 20 signed assets")) {
            $createArguments = @(
                "release", "create", $releaseTag,
                "--repo", $Repository,
                "--target", $sourceCommit,
                "--title", "DroneDream five-edition $version (build $buildNumber)",
                "--notes", "Five synchronized Windows x64 editions from source $sourceCommit. This immutable release is the download and in-app update source.",
                "--prerelease",
                "--latest=false"
            ) + @($releaseAssets)
            Invoke-GitHubCli -Arguments $createArguments | Out-Null
        }
        $release = Get-ReleaseOrNull -Tag $releaseTag
    }
    if ($null -eq $release) {
        if ($WhatIfPreference) {
            Write-Host "WhatIf: combined release validation skipped because it was not created."
            return
        }
        throw "Combined release was not created: $releaseTag"
    }
    $actualAssetNames = @($release.assets | ForEach-Object { [string]$_.name } | Sort-Object)
    if (($actualAssetNames -join "`n") -cne ($expectedAssetNames -join "`n")) {
        throw "Combined release assets differ from the exact 20-file five-edition set."
    }

    foreach ($editionId in $editionIds) {
        $family = @($familyContract.editions | Where-Object { $_.editionId -ceq $editionId })[0]
        $channel = [string]$family.updaterChannelTag
        $manifestPath = [string]$channelManifests[$editionId]
        $manifestName = [IO.Path]::GetFileName($manifestPath)
        $notes = "Authenticated updater metadata for $editionId build $buildNumber.`nbuild-number: $buildNumber`nsource-commit: $sourceCommit"
        $channelRelease = Get-ReleaseOrNull -Tag $channel
        if ($PSCmdlet.ShouldProcess("$Repository release $channel", "publish $manifestName only")) {
            if ($null -eq $channelRelease) {
                Invoke-GitHubCli -Arguments @(
                    "release", "create", $channel,
                    "--repo", $Repository,
                    "--target", $sourceCommit,
                    "--title", "$($family.installerProductName) stable channel",
                    "--notes", $notes,
                    "--prerelease",
                    "--latest=false",
                    $manifestPath
                ) | Out-Null
            } else {
                Invoke-GitHubCli -Arguments @(
                    "release", "upload", $channel, $manifestPath,
                    "--repo", $Repository,
                    "--clobber"
                ) | Out-Null
                Invoke-GitHubCli -Arguments @(
                    "api", "-X", "PATCH",
                    "repos/$Repository/git/refs/tags/$channel",
                    "-f", "sha=$sourceCommit",
                    "-F", "force=true"
                ) | Out-Null
                Invoke-GitHubCli -Arguments @(
                    "release", "edit", $channel,
                    "--repo", $Repository,
                    "--title", "$($family.installerProductName) stable channel",
                    "--notes", $notes,
                    "--prerelease",
                    "--latest=false"
                ) | Out-Null
            }
            $channelRelease = Get-ReleaseOrNull -Tag $channel
            foreach ($asset in @($channelRelease.assets)) {
                if ([string]$asset.name -cne $manifestName) {
                    Invoke-GitHubCli -Arguments @(
                        "release", "delete-asset", $channel, [string]$asset.name,
                        "--repo", $Repository,
                        "--yes"
                    ) | Out-Null
                }
            }
        }
        $channelRelease = Get-ReleaseOrNull -Tag $channel
        if ($null -eq $channelRelease -or
            @($channelRelease.assets).Count -ne 1 -or
            [string]$channelRelease.assets[0].name -cne $manifestName) {
            throw "Stable channel $channel must contain only $manifestName."
        }
    }

    if ($PruneObsoleteReleases) {
        $releaseList = Invoke-GitHubCli -Arguments @(
            "release", "list", "--repo", $Repository,
            "--limit", "100", "--json", "tagName,publishedAt"
        ) | ConvertFrom-Json
        $combinedReleases = @(
            $releaseList |
                Where-Object { [string]$_.tagName -match '^five-edition-v[0-9]+\.[0-9]+\.[0-9]+-build-[1-9][0-9]*$' } |
                Sort-Object { [UInt64]([regex]::Match([string]$_.tagName, 'build-([1-9][0-9]*)$').Groups[1].Value) } -Descending
        )
        $keepCombined = @($combinedReleases | Select-Object -First (1 + $RollbackBuildsToKeep) | ForEach-Object { [string]$_.tagName })
        $runtimeReleases = @(
            $releaseList |
                Where-Object { [string]$_.tagName -match '^runtime-v' } |
                Sort-Object publishedAt -Descending
        )
        $keepRuntime = @($runtimeReleases | Select-Object -First 1 | ForEach-Object { [string]$_.tagName })
        $channelTags = @($familyContract.editions | ForEach-Object { [string]$_.updaterChannelTag })
        $obsoleteTags = [Collections.Generic.List[string]]::new()
        foreach ($item in $releaseList) {
            $tag = [string]$item.tagName
            if ($channelTags -contains $tag -or $keepCombined -contains $tag -or $keepRuntime -contains $tag) {
                continue
            }
            if ($tag -match '^five-edition-v' -or
                $tag -match '^desktop-(universal|sim|lab|field|autonomy)-v' -or
                $tag -match '^desktop-v' -or
                $tag -match '^four-edition-v' -or
                $tag -match '^website-deploy-' -or
                $tag -match '^signpath-candidate-' -or
                $tag -match '^runtime-v' -or
                $tag -match '^v[0-9]+\.[0-9]+\.[0-9]+-(alpha|beta|rc)') {
                $obsoleteTags.Add($tag)
            }
        }
        foreach ($tag in @($obsoleteTags | Sort-Object -Unique)) {
            if ($PSCmdlet.ShouldProcess("$Repository release and tag $tag", "permanently delete obsolete release assets and tag")) {
                Invoke-GitHubCli -Arguments @(
                    "release", "delete", $tag,
                    "--repo", $Repository,
                    "--cleanup-tag",
                    "--yes"
                ) | Out-Null
            }
        }

        if (-not $WhatIfPreference) {
            $expectedPublicTags = @($channelTags + $keepCombined + $keepRuntime | Sort-Object -Unique)
            if ($expectedPublicTags.Count -ne 8) {
                throw "Release retention failed: the canonical public set must contain exactly eight entries."
            }
            $finalReleaseList = Invoke-GitHubCli -Arguments @(
                "release", "list", "--repo", $Repository,
                "--limit", "100", "--json", "tagName"
            ) | ConvertFrom-Json
            $finalReleaseTags = @($finalReleaseList | ForEach-Object { [string]$_.tagName })
            $remoteTagOutput = Invoke-GitHubCli -Arguments @(
                "api", "--paginate", "repos/$Repository/git/matching-refs/tags",
                "--jq", ".[].ref"
            )
            $remoteTags = @(
                $remoteTagOutput -split "`r?`n" |
                    Where-Object { $_ } |
                    ForEach-Object { $_ -replace '^refs/tags/', '' }
            )
            Assert-ExactStringSet -Label "GitHub Release inventory" -Actual $finalReleaseTags -Expected $expectedPublicTags
            Assert-ExactStringSet -Label "GitHub Tag inventory" -Actual $remoteTags -Expected $expectedPublicTags
            $expectedBranches = @(
                "main",
                "codex/software",
                "codex/software-agent",
                "codex/software-field",
                "codex/software-lab",
                "codex/software-sim",
                "codex/technical-report",
                "codex/website"
            )
            $remoteBranchOutput = Invoke-GitHubCli -Arguments @(
                "api", "--paginate", "repos/$Repository/branches?per_page=100",
                "--jq", ".[].name"
            )
            $remoteBranches = @($remoteBranchOutput -split "`r?`n" | Where-Object { $_ })
            Assert-ExactStringSet -Label "GitHub long-lived branch inventory" -Actual $remoteBranches -Expected $expectedBranches
        }
    }

    Write-Host "Published $releaseTag and advanced all five updater channels."
} finally {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $stageRootFull = [IO.Path]::GetFullPath($stageRoot)
    if ($stageRootFull.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        [IO.Path]::GetFileName($stageRootFull).StartsWith("dronedream-five-release-", [StringComparison]::Ordinal)) {
        Remove-Item -LiteralPath $stageRootFull -Recurse -Force -ErrorAction SilentlyContinue -WhatIf:$false
    }
}
