param(
    [ValidateSet("all", "universal", "sim", "lab", "field")]
    [string]$Edition = "all",
    [string]$OutputRoot = (Join-Path $env:LOCALAPPDATA "DroneDream\codex-builds\core-four-main"),
    [string]$CargoRoot = (Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache\core-four-main-cargo"),
    [switch]$AllowUnsignedUpdater,
    [switch]$ReuseCargoTarget,
    [switch]$PreserveCargoTarget
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$outputBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream\codex-builds"))
$cargoBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache"))
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
        "desktop/src-tauri/gen",
        "desktop/src-tauri/target/llvm-bundle"
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

function Get-OAuthClientId {
    param([Parameter(Mandatory = $true)][string]$EditionId)
    $editionVariable = "DRONEDREAM_OAUTH_CLIENT_ID_$($EditionId.ToUpperInvariant())"
    $value = [Environment]::GetEnvironmentVariable($editionVariable, "Process")
    if (-not $value) {
        # OAuth client IDs are public application identifiers. Keep an explicit
        # process override for CI, while allowing the reviewed per-user desktop
        # registration to drive a local four-edition release build.
        $value = [Environment]::GetEnvironmentVariable($editionVariable, "User")
    }
    if (-not $value -and $Edition -ne "all") {
        $value = [Environment]::GetEnvironmentVariable("DRONEDREAM_OAUTH_CLIENT_ID", "Process")
    }
    if ([string]::IsNullOrWhiteSpace($value) -or
        $value -notmatch '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' -or
        $value -match '^dronedream-desktop-(universal|sim|lab|field)$') {
        throw "Set the approved public $editionVariable before building $EditionId."
    }
    return $value
}

function Import-FrontendPublicBuildEnvironment {
    $requiredNames = @("VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY")
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
Assert-StrictChildPath -Path $outputRootFull -Parent $outputBase -Label "OutputRoot"
Assert-StrictChildPath -Path $cargoRootFull -Parent $cargoBase -Label "CargoRoot"

if (Test-Path -LiteralPath $outputRootFull) {
    throw "OutputRoot must be absent before a four-edition build: $outputRootFull"
}
if ((Test-Path -LiteralPath $cargoRootFull) -and -not $ReuseCargoTarget) {
    throw "CargoRoot must be absent before a four-edition build: $cargoRootFull"
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
        throw "Clear custom $name before a four-edition build."
    }
}

$sourceCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
$sourceTree = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()
$sourceStatus = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or
    $sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or
    $sourceTree -cnotmatch '^[0-9a-f]{40}$' -or
    $sourceStatus) {
    throw "The four-edition build requires one exact clean source commit."
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
    throw "A local updater signing key is required for the four-edition build."
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

        $env:DRONEDREAM_DESKTOP_EDITION_ID = $editionId
        $env:DRONEDREAM_EDITION_PROFILE = $contract.profile
        $env:DRONEDREAM_OAUTH_CLIENT_ID = Get-OAuthClientId -EditionId $editionId
        $env:VITE_DRONEDREAM_EDITION = $editionId
        # The shared lower-level builder deliberately sets RUSTFLAGS for the
        # pinned gnullvm build. Reset only its known process-local output before
        # the next edition so the lower-level custom-flag gate remains strict.
        Remove-Item Env:\RUSTFLAGS -ErrorAction SilentlyContinue
        Remove-Item Env:\CARGO_ENCODED_RUSTFLAGS -ErrorAction SilentlyContinue

        Write-Host "Building $editionId from $sourceCommit"
        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        & (Join-Path $repoRoot "desktop\scripts\build-windows-llvm.ps1") `
            -AdditionalConfigPath $configPath `
            -CargoTargetDir $cargoRootFull `
            -ExpectedProductName $contract.product `
            -EditionId $editionId `
            -AllowUnsignedUpdater:$AllowUnsignedUpdater
        $stopwatch.Stop()
        if ($LASTEXITCODE -ne 0) {
            throw "$editionId installer build failed."
        }

        $bundleRoot = Join-Path $cargoRootFull "x86_64-pc-windows-gnullvm\release\bundle\nsis"
        $builtInstaller = Join-Path $bundleRoot "$($contract.product)_${version}_x64-setup.exe"
        $builtSignature = "$builtInstaller.sig"
        $builtChecksum = "$builtInstaller.sha256"
        foreach ($required in @($builtInstaller, $builtChecksum)) {
            if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
                throw "$editionId build did not produce $required"
            }
        }
        if (-not $AllowUnsignedUpdater -and
            -not (Test-Path -LiteralPath $builtSignature -PathType Leaf)) {
            throw "$editionId build did not produce its updater signature."
        }

        $installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $builtInstaller).Hash.ToLowerInvariant()
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
            kind = "dronedream-four-edition-build-receipt"
            editionId = $editionId
            productName = $contract.product
            version = $version
            sourceCommit = $sourceCommit
            sourceTree = $sourceTree
            desktopVisualQa = $desktopVisualQa
            installer = [ordered]@{
                fileName = [IO.Path]::GetFileName($handoffInstaller)
                bytes = (Get-Item -LiteralPath $handoffInstaller).Length
                sha256 = $installerHash
                updaterSignature = -not $AllowUnsignedUpdater
            }
            elapsedSeconds = [Math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
            generatedAt = [DateTimeOffset]::UtcNow.ToString("o")
        } | ConvertTo-Json -Depth 8 | Set-Content `
            -LiteralPath (Join-Path $editionOutput "build-receipt.json") `
            -Encoding UTF8

        Remove-GeneratedSourceOutputs
        $afterCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
        $afterStatus = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
        if ($afterCommit -cne $sourceCommit -or $afterStatus) {
            throw "The source tree changed after the $editionId build."
        }
    }

    $completed = $true
    Write-Host "Four-edition build handoff: $outputRootFull"
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
        throw "Build cleanup failed: $($cleanupErrors -join ' | ')"
    }
}
