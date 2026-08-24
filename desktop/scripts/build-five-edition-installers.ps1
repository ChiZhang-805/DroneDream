param(
    [ValidateSet("all", "universal", "sim", "lab", "field", "autonomy")]
    [string]$Edition = "all",
    [ValidateSet("msvc", "gnullvm")]
    [string]$Toolchain = "msvc",
    [string]$OutputRoot,
    [string]$CargoRoot,
    [string]$StorageRoot,
    [switch]$AllowUnsignedUpdater,
    [switch]$ReuseCargoTarget,
    [switch]$PreserveCargoTarget
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-FullyQualifiedFileSystemPath {
    param([AllowEmptyString()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }

    # System.IO.Path.IsPathFullyQualified is unavailable in the .NET Framework
    # hosted by Windows PowerShell 5.1.  This release script must work in both
    # Windows PowerShell 5.1 and PowerShell 7, so validate the two Windows forms
    # we support directly: a drive-qualified path or a UNC share-qualified path.
    return (
        $Path -match '^[A-Za-z]:[\\/]' -or
        $Path -match '^[\\/]{2}[^\\/]+[\\/][^\\/]+'
    )
}

if ($PSVersionTable.PSEdition -ceq "Desktop") {
    $inboxModuleRoot = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\Modules"
    if (Test-Path -LiteralPath $inboxModuleRoot -PathType Container) {
        $modulePaths = @($inboxModuleRoot) + @(
            $env:PSModulePath -split [IO.Path]::PathSeparator |
                Where-Object { $_ -and $_ -cne $inboxModuleRoot }
        )
        $env:PSModulePath = $modulePaths -join [IO.Path]::PathSeparator
    }
}

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$storageRootFull = $null
if ([string]::IsNullOrWhiteSpace($StorageRoot)) {
    $outputBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream\codex-builds"))
    $cargoBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache"))
} else {
    if (-not (Test-FullyQualifiedFileSystemPath -Path $StorageRoot)) {
        throw "StorageRoot must be an absolute directory."
    }
    $storageRootFull = [IO.Path]::GetFullPath($StorageRoot)
    $storageVolumeRoot = [IO.Path]::GetPathRoot($storageRootFull)
    if ([string]::IsNullOrWhiteSpace($storageVolumeRoot) -or
        $storageRootFull.TrimEnd('\', '/').Equals(
            $storageVolumeRoot.TrimEnd('\', '/'),
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "StorageRoot must not be a drive or share root."
    }
    $outputBase = [IO.Path]::GetFullPath((Join-Path $storageRootFull "codex-builds"))
    $cargoBase = [IO.Path]::GetFullPath((Join-Path $storageRootFull "codex-cache"))
}
$toolchainContract = if ($Toolchain -ceq "msvc") {
    [ordered]@{
        builder = "desktop\scripts\build-windows-msvc.ps1"
        targetTriple = "x86_64-pc-windows-msvc"
        compilerFamily = "msvc"
    }
} else {
    [ordered]@{
        builder = "desktop\scripts\build-windows-llvm.ps1"
        targetTriple = "x86_64-pc-windows-gnullvm"
        compilerFamily = "llvm-mingw"
    }
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $outputBase "core-five-$Toolchain"
}
if ([string]::IsNullOrWhiteSpace($CargoRoot)) {
    $CargoRoot = Join-Path $cargoBase "core-five-$Toolchain-cargo"
}
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot)
$cargoRootFull = [IO.Path]::GetFullPath($CargoRoot)

function Assert-StrictChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $parentPrefix = $Parent.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $Path.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must be a strict child of $Parent"
    }
}

function Test-PathAtOrBelow {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $pathFull = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    if ($pathFull.Equals($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $parentPrefix = $parentFull + [IO.Path]::DirectorySeparatorChar
    return $pathFull.StartsWith($parentPrefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoExistingReparsePointInPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    while (-not [string]::IsNullOrWhiteSpace($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "$Label must not traverse a reparse point: $cursor"
            }
            if ($cursor.Equals($full, [StringComparison]::OrdinalIgnoreCase) -and
                -not $item.PSIsContainer) {
                throw "$Label must be a directory: $full"
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        if ($null -eq $parent -or
            $parent.FullName.Equals($cursor, [StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $cursor = $parent.FullName
    }
}

function Get-SourceFileBinding {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = $RelativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $full = [IO.Path]::GetFullPath((Join-Path $repoRoot $normalized))
    Assert-StrictChildPath -Path $full -Parent $repoRoot -Label "Source binding"
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "Source binding is unavailable: $RelativePath"
    }
    $item = Get-Item -LiteralPath $full -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Source binding must not be a reparse point: $RelativePath"
    }
    return [ordered]@{
        path = $RelativePath.Replace('\', '/')
        bytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Remove-ExactExternalTree {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$AllowedParent
    )
    $full = [IO.Path]::GetFullPath($Path)
    Assert-StrictChildPath -Path $full -Parent $AllowedParent -Label "Cleanup target"
    if (-not (Test-Path -LiteralPath $full)) { return }
    $root = Get-Item -LiteralPath $full -Force
    if ($root.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to delete a reparse-point root: $full"
    }
    $nestedReparse = @(Get-ChildItem -LiteralPath $full -Force -Recurse | Where-Object {
        $_.Attributes -band [IO.FileAttributes]::ReparsePoint
    })
    if ($nestedReparse.Count -ne 0) {
        throw "Refusing to delete a tree containing reparse points: $full"
    }
    [IO.Directory]::Delete($full, $true)
    if (Test-Path -LiteralPath $full) {
        throw "Exact cleanup did not remove $full"
    }
}

function Remove-GeneratedSourceOutputs {
    $paths = @(
        "frontend/dist",
        "frontend/field-dist",
        "frontend/tsconfig.tsbuildinfo",
        "frontend/public/drone-favicon.png",
        "desktop/src-tauri/gen",
        "desktop/src-tauri/target/llvm-bundle",
        "desktop/src-tauri/binaries",
        "desktop/src-tauri/agent-core-resources"
    )
    & git -C $repoRoot clean -fdx -- @paths | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Generated source-output cleanup failed."
    }
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath (Join-Path $repoRoot $path)) {
            throw "Generated source output remains after cleanup: $path"
        }
    }
}

function Get-ProcessEnvironmentSnapshot {
    $snapshot = @{}
    foreach ($entry in [Environment]::GetEnvironmentVariables("Process").GetEnumerator()) {
        $snapshot[[string]$entry.Key] = [string]$entry.Value
    }
    return $snapshot
}

function Restore-ProcessEnvironmentSnapshot {
    param([Parameter(Mandatory = $true)][hashtable]$Snapshot)

    $currentNames = @(
        [Environment]::GetEnvironmentVariables("Process").Keys |
            ForEach-Object { [string]$_ }
    )
    foreach ($name in $currentNames) {
        if (-not $Snapshot.ContainsKey($name)) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
    }
    foreach ($name in $Snapshot.Keys) {
        [Environment]::SetEnvironmentVariable(
            [string]$name,
            [string]$Snapshot[$name],
            "Process"
        )
    }
}

function Get-OAuthClientId {
    param([Parameter(Mandatory = $true)][string]$EditionId)
    $editionVariables = if ($EditionId -eq "autonomy") {
        # AGENT is the product-facing name. AUTONOMY remains a read-only legacy
        # alias so existing developer machines and provider registrations do not
        # need to be changed in lockstep with the visible rename.
        @("DRONEDREAM_OAUTH_CLIENT_ID_AGENT", "DRONEDREAM_OAUTH_CLIENT_ID_AUTONOMY")
    } else {
        @("DRONEDREAM_OAUTH_CLIENT_ID_$($EditionId.ToUpperInvariant())")
    }
    $value = $null
    foreach ($environmentTarget in @("Process", "User")) {
        foreach ($editionVariable in $editionVariables) {
            $candidate = [Environment]::GetEnvironmentVariable(
                $editionVariable,
                $environmentTarget
            )
            if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                $value = $candidate
                break
            }
        }
        if ($value) {
            break
        }
    }
    if (-not $value -and $Edition -ne "all") {
        $value = [Environment]::GetEnvironmentVariable("DRONEDREAM_OAUTH_CLIENT_ID", "Process")
    }
    if ([string]::IsNullOrWhiteSpace($value) -or
        $value -notmatch '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' -or
        $value -match '^dronedream-desktop-(universal|sim|lab|field|autonomy)$') {
        throw "Set an approved public OAuth client ID in $($editionVariables -join ' or ') before building $EditionId."
    }
    return $value
}

function Import-FrontendPublicBuildEnvironment {
    $requiredNames = @("VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY")
    foreach ($name in $requiredNames) {
        if (-not [string]::IsNullOrWhiteSpace(
            [Environment]::GetEnvironmentVariable($name, "Process")
        )) {
            continue
        }
        # These VITE values are public browser application identifiers, not
        # service-role credentials. A reviewed per-user registration must be
        # usable by fresh terminals and by the local release wrapper.
        $userValue = [Environment]::GetEnvironmentVariable($name, "User")
        if (-not [string]::IsNullOrWhiteSpace($userValue)) {
            [Environment]::SetEnvironmentVariable($name, $userValue, "Process")
        }
    }
    $missingNames = @($requiredNames | Where-Object {
        [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_, "Process"))
    })
    if ($missingNames.Count -eq 0) { return }

    $envPath = Join-Path $repoRoot "frontend\.env.production"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        throw "The approved frontend production environment file is unavailable."
    }

    $loadedNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        if ($line -notmatch '^\s*(VITE_SUPABASE_URL|VITE_SUPABASE_PUBLISHABLE_KEY)\s*=\s*(.*?)\s*$') {
            continue
        }
        $name = $Matches[1]
        if ($name -notin $missingNames) { continue }
        $value = $Matches[2].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "The approved frontend production environment file is incomplete."
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
        [void]$loadedNames.Add($name)
    }
    if ($loadedNames.Count -ne $missingNames.Count) {
        throw "The approved frontend production environment file is incomplete."
    }
}

if ($outputRootFull.Equals($cargoRootFull, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot and CargoRoot must be different directories."
}
if ($storageRootFull) {
    if ((Test-PathAtOrBelow -Path $storageRootFull -Parent $repoRoot) -or
        (Test-PathAtOrBelow -Path $repoRoot -Parent $storageRootFull)) {
        throw "StorageRoot must not overlap the source worktree."
    }
    Assert-StrictChildPath -Path $outputBase -Parent $storageRootFull -Label "Output base"
    Assert-StrictChildPath -Path $cargoBase -Parent $storageRootFull -Label "Cargo base"
    Assert-NoExistingReparsePointInPath -Path $storageRootFull -Label "StorageRoot"
    Assert-NoExistingReparsePointInPath -Path $outputBase -Label "Output base"
    Assert-NoExistingReparsePointInPath -Path $cargoBase -Label "Cargo base"
    Assert-NoExistingReparsePointInPath -Path $outputRootFull -Label "OutputRoot"
    Assert-NoExistingReparsePointInPath -Path $cargoRootFull -Label "CargoRoot"
}
Assert-StrictChildPath -Path $outputRootFull -Parent $outputBase -Label "OutputRoot"
Assert-StrictChildPath -Path $cargoRootFull -Parent $cargoBase -Label "CargoRoot"

if (Test-Path -LiteralPath $outputRootFull) {
    throw "OutputRoot must be absent before a five-edition build: $outputRootFull"
}
if ((Test-Path -LiteralPath $cargoRootFull) -and -not $ReuseCargoTarget) {
    throw "CargoRoot must be absent before a five-edition build: $cargoRootFull"
}
if ($ReuseCargoTarget) {
    if (-not (Test-Path -LiteralPath $cargoRootFull -PathType Container)) {
        throw "ReuseCargoTarget requires an existing CargoRoot directory: $cargoRootFull"
    }
    $cargoRootItem = Get-Item -LiteralPath $cargoRootFull -Force
    if ($cargoRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "ReuseCargoTarget refuses a reparse-point CargoRoot: $cargoRootFull"
    }
}
foreach ($name in @("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")) {
    if (-not [string]::IsNullOrWhiteSpace(
        [Environment]::GetEnvironmentVariable($name, "Process")
    )) {
        throw "Clear custom $name before a five-edition build."
    }
}

Remove-GeneratedSourceOutputs

$sourceCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
$sourceTree = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()
$sourceBuildNumber = (& git -C $repoRoot rev-list --count $sourceCommit).Trim()
$sourceStatus = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or
    $sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or
    $sourceTree -cnotmatch '^[0-9a-f]{40}$' -or
    $sourceBuildNumber -cnotmatch '^[1-9][0-9]*$' -or
    $sourceStatus) {
    throw "The five-edition build requires one exact clean source commit."
}

$brandContractRelativePath = "brand/editions.json"
$brandGeneratorRelativePath = "scripts/build-brand-assets.py"
$brandContractBinding = Get-SourceFileBinding -RelativePath $brandContractRelativePath
$brandGeneratorBinding = Get-SourceFileBinding -RelativePath $brandGeneratorRelativePath
$brandContractDocument = Get-Content -LiteralPath (
    Join-Path $repoRoot $brandContractRelativePath
) -Raw -Encoding UTF8 | ConvertFrom-Json
if ($brandContractDocument.kind -cne "dronedream-edition-brand-system") {
    throw "The canonical brand contract identity is invalid."
}

Import-FrontendPublicBuildEnvironment
foreach ($name in @("VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY")) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) {
        throw "Set the approved public $name before building."
    }
}
$desktopVisualQa = [Environment]::GetEnvironmentVariable(
    "VITE_DESKTOP_VISUAL_QA",
    "Process"
) -ceq "true"
if ($desktopVisualQa -and -not $AllowUnsignedUpdater) {
    throw "Desktop visual-QA mode is forbidden for signed updater builds."
}

$defaultUpdaterKey = Join-Path $env:USERPROFILE ".tauri\dronedream-updater.key"
if (-not $AllowUnsignedUpdater -and
    -not $env:TAURI_SIGNING_PRIVATE_KEY_PATH -and
    -not (Test-Path -LiteralPath $defaultUpdaterKey -PathType Leaf)) {
    throw "A local updater signing key is required for the five-edition build."
}

$version = [string](Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\src-tauri\tauri.conf.json"
) -Raw -Encoding UTF8 | ConvertFrom-Json).version
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "The canonical desktop version is invalid."
}

$contracts = [ordered]@{
    universal = [ordered]@{
        config = "desktop\src-tauri\tauri.universal.conf.json"
        product = "DroneDream-Universal"
        profile = "unified-sim-lab"
    }
    sim = [ordered]@{
        config = "desktop\src-tauri\tauri.sim.conf.json"
        product = "DroneDream-Sim"
        profile = "sim-only"
    }
    lab = [ordered]@{
        config = "desktop\src-tauri\tauri.lab.conf.json"
        product = "DroneDream-Lab"
        profile = "unified-sim-lab"
    }
    field = [ordered]@{
        config = "desktop\src-tauri\tauri.field.conf.json"
        product = "DroneDream-Field"
        profile = "field-lightweight"
    }
    autonomy = [ordered]@{
        config = "desktop\src-tauri\tauri.autonomy.conf.json"
        product = "DroneDream-Agent"
        profile = "autonomy-full"
    }
}
$editionIds = if ($Edition -eq "all") { @($contracts.Keys) } else { @($Edition) }

$priorEnvironment = @{}
$environmentNames = @(
    "PATH",
    "CARGO_BUILD_JOBS",
    "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_TARGET_DIR",
    "DRONEDREAM_DESKTOP_EDITION_ID",
    "DRONEDREAM_EDITION_PROFILE",
    "DRONEDREAM_OAUTH_CLIENT_ID",
    "DRONEDREAM_RELEASE_BUILD_NUMBER",
    "DRONEDREAM_RELEASE_SOURCE_COMMIT",
    "RUSTFLAGS",
    "RUSTUP_TOOLCHAIN",
    "VITE_DRONEDREAM_EDITION"
)
foreach ($name in $environmentNames) {
    $priorEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$completed = $false
try {
    [IO.Directory]::CreateDirectory($cargoRootFull) | Out-Null
    [IO.Directory]::CreateDirectory($outputRootFull) | Out-Null

    foreach ($editionId in $editionIds) {
        $contract = $contracts[$editionId]
        $configPath = Join-Path $repoRoot $contract.config
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$config.productName -cne [string]$contract.product) {
            throw "$editionId config productName drifted from the build contract."
        }

        Write-Host "Building $editionId from $sourceCommit"
        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        $builderExitCode = 0
        $editionEnvironment = Get-ProcessEnvironmentSnapshot
        try {
            $env:DRONEDREAM_DESKTOP_EDITION_ID = $editionId
            $env:DRONEDREAM_EDITION_PROFILE = $contract.profile
            $env:DRONEDREAM_OAUTH_CLIENT_ID = Get-OAuthClientId -EditionId $editionId
            $env:VITE_DRONEDREAM_EDITION = $editionId
            # The LLVM fallback deliberately sets RUSTFLAGS. Reset its known
            # process-local output before every edition; the MSVC path also rejects
            # inherited custom flags so both release chains remain deterministic.
            Remove-Item Env:\RUSTFLAGS -ErrorAction SilentlyContinue
            Remove-Item Env:\CARGO_ENCODED_RUSTFLAGS -ErrorAction SilentlyContinue

            & python (Join-Path $repoRoot $brandGeneratorRelativePath) --edition $editionId
            $brandGeneratorExitCode = $LASTEXITCODE
            if ($brandGeneratorExitCode -ne 0) {
                throw "Brand asset generation failed for $editionId with exit code $brandGeneratorExitCode."
            }
            $brandEdition = $brandContractDocument.editions.PSObject.Properties[$editionId]
            if ($null -eq $brandEdition -or
                [string]::IsNullOrWhiteSpace([string]$brandEdition.Value.mark.path)) {
                throw "The canonical brand mark is not declared for $editionId."
            }
            $brandMarkBinding = Get-SourceFileBinding `
                -RelativePath ([string]$brandEdition.Value.mark.path)
            $expectedBrandOutputs = @(
                "desktop/src-tauri/gen/brand/$editionId/windows/32x32.png",
                "desktop/src-tauri/gen/brand/$editionId/windows/128x128.png",
                "desktop/src-tauri/gen/brand/$editionId/windows/128x128@2x.png",
                "desktop/src-tauri/gen/brand/$editionId/windows/icon.ico",
                "frontend/public/drone-favicon.png"
            )
            foreach ($expectedBrandOutput in $expectedBrandOutputs) {
                if (-not (Test-Path -LiteralPath (
                    Join-Path $repoRoot $expectedBrandOutput
                ) -PathType Leaf)) {
                    throw "Brand asset generation did not produce $expectedBrandOutput"
                }
            }

            & (Join-Path $repoRoot "desktop\scripts\stage-agent-core.ps1") `
                -TargetTriple $toolchainContract.targetTriple
            if ($LASTEXITCODE -ne 0) {
                throw "AGENT Core staging failed for $editionId."
            }

            & (Join-Path $repoRoot $toolchainContract.builder) `
                -AdditionalConfigPath $configPath `
                -CargoTargetDir $cargoRootFull `
                -ExpectedProductName $contract.product `
                -EditionId $editionId `
                -AllowUnsignedUpdater:$AllowUnsignedUpdater
            $builderExitCode = $LASTEXITCODE
        } finally {
            $stopwatch.Stop()
            # VsDevCmd mutates dozens of process-scoped variables. Restore the
            # exact pre-edition environment so one package can never poison the
            # next package's Node, Rust, SDK, Python, or linker discovery.
            Restore-ProcessEnvironmentSnapshot -Snapshot $editionEnvironment
        }
        if ($builderExitCode -ne 0) {
            throw "$editionId installer build failed."
        }

        $bundleRoot = Join-Path $cargoRootFull "$($toolchainContract.targetTriple)\release\bundle\nsis"
        $builtApplication = Join-Path $cargoRootFull "$($toolchainContract.targetTriple)\release\drone-dream-desktop.exe"
        $builtInstaller = Join-Path $bundleRoot "$($contract.product)_${version}_x64-setup.exe"
        $builtSignature = "$builtInstaller.sig"
        $builtChecksum = "$builtInstaller.sha256"
        foreach ($required in @($builtApplication, $builtInstaller, $builtChecksum)) {
            if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
                throw "$editionId build did not produce $required"
            }
        }
        if (-not $AllowUnsignedUpdater -and
            -not (Test-Path -LiteralPath $builtSignature -PathType Leaf)) {
            throw "$editionId build did not produce its updater signature."
        }

        $installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $builtInstaller).Hash.ToLowerInvariant()
        $applicationHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $builtApplication).Hash.ToLowerInvariant()
        $checksumLine = (Get-Content -LiteralPath $builtChecksum -Raw -Encoding ASCII).Trim()
        if ($checksumLine -notmatch "^$installerHash\s+") {
            throw "$editionId checksum sidecar does not match the installer."
        }

        $editionOutput = Join-Path $outputRootFull $editionId
        if (Test-Path -LiteralPath $editionOutput) {
            throw "$editionId output slot is not empty."
        }
        [IO.Directory]::CreateDirectory($editionOutput) | Out-Null
        # Preserve the canonical bundle name so the copied sha256 sidecar and
        # updater manifest continue to name the exact installer they attest.
        $handoffInstaller = Join-Path $editionOutput ([IO.Path]::GetFileName($builtInstaller))
        [IO.File]::Copy($builtInstaller, $handoffInstaller, $false)
        [IO.File]::Copy($builtChecksum, "$handoffInstaller.sha256", $false)
        if (-not $AllowUnsignedUpdater) {
            [IO.File]::Copy($builtSignature, "$handoffInstaller.sig", $false)
        }
        $updaterManifest = Join-Path $bundleRoot "latest-$editionId.json"
        if (-not $AllowUnsignedUpdater) {
            if (-not (Test-Path -LiteralPath $updaterManifest -PathType Leaf)) {
                throw "$editionId updater manifest is missing."
            }
            [IO.File]::Copy(
                $updaterManifest,
                (Join-Path $editionOutput "latest-$editionId.json"),
                $false
            )
        }

        [ordered]@{
            schemaVersion = 1
            kind = "dronedream-five-edition-build-receipt"
            editionId = $editionId
            productName = $contract.product
            version = $version
            buildNumber = [UInt64]$sourceBuildNumber
            sourceCommit = $sourceCommit
            sourceTree = $sourceTree
            desktopVisualQa = $desktopVisualQa
            compilerFamily = $toolchainContract.compilerFamily
            targetTriple = $toolchainContract.targetTriple
            brand = [ordered]@{
                contract = $brandContractBinding
                mark = $brandMarkBinding
                generator = $brandGeneratorBinding
            }
            installer = [ordered]@{
                fileName = [IO.Path]::GetFileName($handoffInstaller)
                bytes = (Get-Item -LiteralPath $handoffInstaller).Length
                sha256 = $installerHash
                updaterSignature = -not $AllowUnsignedUpdater
            }
            application = [ordered]@{
                fileName = [IO.Path]::GetFileName($builtApplication)
                bytes = (Get-Item -LiteralPath $builtApplication).Length
                sha256 = $applicationHash
            }
            elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
            generatedAt = [DateTimeOffset]::UtcNow.ToString("o")
        } | ConvertTo-Json -Depth 8 | Set-Content `
            -LiteralPath (Join-Path $editionOutput "build-receipt.json") `
            -Encoding UTF8

        Remove-GeneratedSourceOutputs
        $afterCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
        $afterTree = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()
        $afterStatus = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
        if ($afterCommit -cne $sourceCommit -or
            $afterTree -cne $sourceTree -or
            $afterStatus) {
            throw "The source tree changed after the $editionId build."
        }
    }

    $completed = $true
    Write-Host "Five-edition build handoff: $outputRootFull"
} finally {
    foreach ($name in $environmentNames) {
        $prior = $priorEnvironment[$name]
        if ($null -eq $prior) {
            Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $prior, "Process")
        }
    }
    $cleanupErrors = [Collections.Generic.List[string]]::new()
    try { Remove-GeneratedSourceOutputs } catch { $cleanupErrors.Add($_.Exception.Message) }
    try {
        $finalCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
        $finalTree = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()
        $finalStatus = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
        if ($finalCommit -cne $sourceCommit -or
            $finalTree -cne $sourceTree -or
            $finalStatus) {
            throw "The source commit, tree, or status changed during the five-edition build."
        }
    } catch {
        $cleanupErrors.Add($_.Exception.Message)
    }
    if (-not $PreserveCargoTarget) {
        try {
            Remove-ExactExternalTree -Path $cargoRootFull -AllowedParent $cargoBase
        } catch {
            $cleanupErrors.Add($_.Exception.Message)
        }
    }
    if (-not $completed) {
        try {
            Remove-ExactExternalTree -Path $outputRootFull -AllowedParent $outputBase
        } catch {
            $cleanupErrors.Add($_.Exception.Message)
        }
    }
    if ($cleanupErrors.Count -ne 0) {
        if ($completed -and (Test-Path -LiteralPath $outputRootFull)) {
            try {
                Remove-ExactExternalTree -Path $outputRootFull -AllowedParent $outputBase
                $completed = $false
            } catch {
                $cleanupErrors.Add($_.Exception.Message)
            }
        }
        throw "Build cleanup failed: $($cleanupErrors -join ' | ')"
    }
}
