param(
    [string]$AdditionalConfigPath,
    [string]$CargoTargetDir,
    [string]$DetachedNodeDependencyManifest,
    [string]$ExpectedProductName = "DroneDream",
    [ValidateSet("universal", "sim", "lab", "field")]
    [string]$EditionId = "universal",
    [switch]$AllowUnsignedUpdater,
    [switch]$PreserveBundleHistory
)

$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "release-build-driver.psm1") -Force

& (Join-Path $PSScriptRoot "verify-updater-signing-contract.ps1")
& (Join-Path $PSScriptRoot "verify-updater-build-contract.ps1")

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$releaseSourceCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $releaseSourceCommit -cnotmatch '^[0-9a-f]{40}$') {
    throw "Unable to freeze the exact release source commit."
}
$releaseSourceTree = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()
if ($LASTEXITCODE -ne 0 -or $releaseSourceTree -cnotmatch '^[0-9a-f]{40}$') {
    throw "Unable to freeze the exact release source tree."
}
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $releaseBranch = (& git -C $repoRoot symbolic-ref --short -q HEAD 2>$null | Out-String).Trim()
    $releaseBranchExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($releaseBranchExitCode -notin @(0, 1)) {
    throw "Unable to classify the release source branch state."
}
if (-not $releaseBranch -and -not $DetachedNodeDependencyManifest) {
    throw "Detached release sources require an exact attested Node dependency manifest."
}
$releaseBuildNumber = (& git -C $repoRoot rev-list --count $releaseSourceCommit).Trim()
if ($LASTEXITCODE -ne 0 -or $releaseBuildNumber -notmatch '^[1-9][0-9]*$') {
    throw "Unable to freeze the exact release build number."
}
$releaseSourceStatus = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $releaseSourceStatus) {
    throw "The desktop release source must be an exact clean Git commit."
}
$env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $releaseSourceCommit
$env:DRONEDREAM_RELEASE_BUILD_NUMBER = $releaseBuildNumber

$desktopVisualQa = [Environment]::GetEnvironmentVariable(
    "VITE_DESKTOP_VISUAL_QA",
    "Process"
) -ceq "true"
if ($desktopVisualQa -and -not $AllowUnsignedUpdater) {
    throw "Desktop visual-QA mode is forbidden for signed updater builds."
}
$visualQaConfig = if ($desktopVisualQa) {
    $candidate = Join-Path $PSScriptRoot (
        "..\src-tauri\visual-qa\tauri.$EditionId.visual-qa.conf.json"
    )
    $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction Stop
    $config = Get-Content -LiteralPath $resolved.Path -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $expectedIdentifier = "io.dronedream.desktop.$EditionId.visual-qa"
    if ([string]$config.identifier -cne $expectedIdentifier) {
        throw "Desktop visual-QA config must use isolated identifier $expectedIdentifier."
    }
    $resolved.Path
} else {
    $null
}

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path -LiteralPath $cargoBin) {
    $env:PATH = "$cargoBin;$env:PATH"
}
if (-not (Get-Command rustup.exe -ErrorAction SilentlyContinue)) {
    throw "rustup was not found. Install Rust before building DroneDream Desktop."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js before building DroneDream Desktop."
}

$requiredRustVersion = "1.97.0"
$toolchainCandidates = @(
    "1.97.0-x86_64-pc-windows-msvc",
    "stable-x86_64-pc-windows-msvc"
)
$targetTriple = "x86_64-pc-windows-msvc"
$toolchain = $null
foreach ($candidate in $toolchainCandidates) {
    $rustcMetadata = (& rustup.exe run $candidate rustc -Vv 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0) { continue }
    $releaseMatch = [regex]::Match($rustcMetadata, '(?m)^release:\s*(\S+)\s*$')
    $hostMatch = [regex]::Match($rustcMetadata, '(?m)^host:\s*(\S+)\s*$')
    if ($releaseMatch.Success -and
        $hostMatch.Success -and
        $releaseMatch.Groups[1].Value -ceq $requiredRustVersion -and
        $hostMatch.Groups[1].Value -ceq $targetTriple) {
        $toolchain = $candidate
        break
    }
}
if (-not $toolchain) {
    throw @"
Rust $requiredRustVersion for $targetTriple was not found. Install it once with:
  rustup toolchain install 1.97.0-x86_64-pc-windows-msvc --profile minimal
"@
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw "Visual Studio Installer and vswhere were not found. Install the repository .vsconfig."
}
$visualStudioRoot = (& $vswhere -latest -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath | Out-String).Trim()
if (-not $visualStudioRoot) {
    throw "No complete MSVC x64 build environment was found. Install the repository .vsconfig."
}
$developerCommand = Join-Path $visualStudioRoot "Common7\Tools\VsDevCmd.bat"
if (-not (Test-Path -LiteralPath $developerCommand -PathType Leaf)) {
    throw "The Visual Studio developer environment is incomplete: $developerCommand"
}
$developerEnvironmentCommand = (
    '"' + $developerCommand + '" -no_logo -arch=amd64 -host_arch=amd64 && set'
)
$developerEnvironment = & $env:ComSpec /d /s /c $developerEnvironmentCommand
if ($LASTEXITCODE -ne 0) {
    throw "Visual Studio failed to initialize its x64 developer environment."
}
foreach ($line in $developerEnvironment) {
    if ($line -match '^([^=][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}
foreach ($toolName in @("cl.exe", "link.exe", "rc.exe", "dumpbin.exe")) {
    if (-not (Get-Command $toolName -ErrorAction SilentlyContinue)) {
        throw "The MSVC developer environment is missing $toolName."
    }
}
$env:RUSTUP_TOOLCHAIN = $toolchain
if (-not $env:CARGO_BUILD_JOBS) {
    $env:CARGO_BUILD_JOBS = "4"
}
if ($env:RUSTFLAGS -or $env:CARGO_ENCODED_RUSTFLAGS) {
    throw "Clear custom RUSTFLAGS and CARGO_ENCODED_RUSTFLAGS before using the MSVC release build."
}

$defaultCargoTarget = Join-Path $PSScriptRoot "..\src-tauri\target"
$cargoTargetRoot = if ($CargoTargetDir) {
    [IO.Path]::GetFullPath($CargoTargetDir)
} elseif ($env:CARGO_TARGET_DIR) {
    [IO.Path]::GetFullPath($env:CARGO_TARGET_DIR)
} else {
    [IO.Path]::GetFullPath($defaultCargoTarget)
}
$env:CARGO_TARGET_DIR = $cargoTargetRoot
$targetOutputRoot = Join-Path $cargoTargetRoot "$targetTriple\release"
$installerBundleRoot = Join-Path $targetOutputRoot "bundle\nsis"
$detachedDependencyContract = $null

$additionalConfig = $null
if ($AdditionalConfigPath) {
    $additionalConfig = (Resolve-Path -LiteralPath $AdditionalConfigPath -ErrorAction Stop).Path
    $additionalConfigText = Get-Content -LiteralPath $additionalConfig -Raw -Encoding UTF8
    try {
        $additionalConfigObject = $additionalConfigText | ConvertFrom-Json
    } catch {
        throw "The additional edition config is not valid JSON: $AdditionalConfigPath"
    }
    if ($additionalConfigObject.productName -cne $ExpectedProductName) {
        throw "The additional edition config productName does not match $ExpectedProductName."
    }
}
$frontendDistContract = Resolve-EditionGeneratedFrontendContract `
    -RepoRoot $repoRoot `
    -BaseConfigPath (Join-Path $PSScriptRoot "..\src-tauri\tauri.conf.json") `
    -AdditionalConfigPath $additionalConfig `
    -EditionId $EditionId
if ($DetachedNodeDependencyManifest) {
    $detachedDependencyContract = & (Join-Path $PSScriptRoot "verify-detached-node-dependencies.ps1") `
        -ManifestPath $DetachedNodeDependencyManifest `
        -RepoRoot $repoRoot `
        -EditionId $EditionId `
        -ExpectedSourceCommit $releaseSourceCommit `
        -ExpectedSourceTree $releaseSourceTree `
        -FrontendDistPath $frontendDistContract.absolutePath `
        -InstallerBundlePath $installerBundleRoot
    if (-not $detachedDependencyContract.liveMountValidated -or
        $detachedDependencyContract.mountCount -ne 2) {
        throw "The detached Node dependency mounts were not live-validated."
    }
    $env:npm_config_offline = "true"
    $env:npm_config_audit = "false"
    $env:npm_config_fund = "false"
    $env:npm_config_update_notifier = "false"
}

$runtimeUpdateFamilies = Get-Content -LiteralPath (
    Join-Path $repoRoot "distribution\desktop\edition-runtime-update-families.v1.json"
) -Raw -Encoding UTF8 | ConvertFrom-Json
$editionFamilies = @($runtimeUpdateFamilies.editions | Where-Object {
    $_.editionId -ceq $EditionId
})
if ($runtimeUpdateFamilies.kind -cne "dronedream-desktop-runtime-update-families" -or
    $editionFamilies.Count -ne 1) {
    throw "The desktop updater family contract is unavailable or ambiguous."
}
$editionFamily = $editionFamilies[0]
if ($env:DRONEDREAM_DESKTOP_EDITION_ID -and
    $env:DRONEDREAM_DESKTOP_EDITION_ID -cne $EditionId) {
    throw "The compiled desktop edition does not match its updater family."
}
if ($AdditionalConfigPath -and
    $ExpectedProductName -cne [string]$editionFamily.installerProductName) {
    throw "The edition overlay productName does not match its updater family."
}
if (-not $AdditionalConfigPath -and -not $AllowUnsignedUpdater) {
    throw "Signed updater builds require an explicit edition config overlay."
}

& (Join-Path $PSScriptRoot "verify-desktop-version.ps1")
& (Join-Path $PSScriptRoot "verify-nsis-template.ps1")

Write-Host "Building DroneDream Desktop with $toolchain and MSVC from $visualStudioRoot"
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$tauriConfigArguments = @("--target", $targetTriple)
if ($additionalConfig) {
    $tauriConfigArguments += @("--config", $additionalConfig)
}
if ($visualQaConfig) {
    $tauriConfigArguments += @("--config", $visualQaConfig)
}
Invoke-CheckedNativeCommand `
    -FilePath "npm.cmd" `
    -DisplayName "Tauri desktop MSVC build" `
    -ArgumentList (@("--prefix", $desktopRoot, "run", "build", "--") + $tauriConfigArguments)

Invoke-CheckedNativeCommand `
    -FilePath "node.exe" `
    -DisplayName "$EditionId frontend ownership verification" `
    -ArgumentList @(
        (Join-Path $repoRoot "frontend\scripts\verify-edition-build-boundaries.mjs"),
        "--edition", $EditionId,
        "--dist", $frontendDistContract.absolutePath
    )

$postBuildCommit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
$postBuildStatusLines = @(
    & git -C $repoRoot status --porcelain=v1 --untracked-files=all
)
$postBuildStatusExitCode = $LASTEXITCODE
$postBuildStatus = Test-PostBuildSourceStatus `
    -StatusLines $postBuildStatusLines `
    -AllowedGeneratedPath $frontendDistContract.relativePath
if ($postBuildStatusExitCode -ne 0 -or
    $postBuildCommit -cne $releaseSourceCommit -or
    $postBuildStatus.unexpectedCount -ne 0) {
    throw "The release source changed while the desktop installer was building."
}
if ($postBuildStatus.allowedGeneratedCount -gt 0) {
    Write-Host (
        "Accepted $($postBuildStatus.allowedGeneratedCount) generated frontend files " +
        "under $($frontendDistContract.relativePath)."
    )
}
if ($detachedDependencyContract) {
    $postBuildDependencyContract = & (Join-Path $PSScriptRoot "verify-detached-node-dependencies.ps1") `
        -ManifestPath $DetachedNodeDependencyManifest `
        -RepoRoot $repoRoot `
        -EditionId $EditionId `
        -ExpectedSourceCommit $releaseSourceCommit `
        -ExpectedSourceTree $releaseSourceTree `
        -FrontendDistPath $frontendDistContract.absolutePath `
        -InstallerBundlePath $installerBundleRoot `
        -InspectOutputPayload
    if (-not $postBuildDependencyContract.liveMountValidated -or
        $postBuildDependencyContract.treeFingerprint -cne $detachedDependencyContract.treeFingerprint -or
        $postBuildDependencyContract.manifestSha256 -cne $detachedDependencyContract.manifestSha256) {
        throw "The detached Node dependency bundle changed during the release build."
    }
}

$application = Join-Path $targetOutputRoot "drone-dream-desktop.exe"
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "The MSVC build completed without producing $application"
}
$importReport = (& dumpbin.exe /dependents $application | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the MSVC executable import table."
}
$forbiddenRuntimeDlls = @(
    "libunwind.dll",
    "libc++.dll",
    "libc++abi.dll",
    "libgcc_s_seh-1.dll",
    "libstdc++-6.dll",
    "libwinpthread-1.dll"
)
$dynamicToolchainDlls = @($forbiddenRuntimeDlls | Where-Object {
    $importReport -match "(?im)^\s*$([regex]::Escape($_))\s*$"
})
if ($dynamicToolchainDlls.Count -gt 0) {
    throw "The MSVC executable unexpectedly depends on non-MSVC toolchain DLLs: $($dynamicToolchainDlls -join ', ')"
}
Write-Host "Verified the native MSVC executable dependency contract."

$generatedNsi = Join-Path $targetOutputRoot "nsis\x64\installer.nsi"
if (-not (Test-Path -LiteralPath $generatedNsi -PathType Leaf)) {
    throw "The MSVC build completed without producing $generatedNsi"
}
& (Join-Path $PSScriptRoot "verify-webview2-installer.ps1") -GeneratedNsi $generatedNsi
& (Join-Path $PSScriptRoot "verify-installer-path-guard.ps1")
& (Join-Path $PSScriptRoot "verify-installer-locales.ps1") -GeneratedNsi $generatedNsi
& (Join-Path $PSScriptRoot "verify-installer-planner.ps1") `
    -Application $application `
    -EditionId $EditionId

$tauriConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\src-tauri\tauri.conf.json") -Raw |
    ConvertFrom-Json
$bundleDirectory = Join-Path $targetOutputRoot "bundle\nsis"
$installer = Join-Path $bundleDirectory "${ExpectedProductName}_$($tauriConfig.version)_x64-setup.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "The MSVC build completed without producing the versioned installer $installer"
}

$updaterSignature = "${installer}.sig"
if ($AllowUnsignedUpdater) {
    if (Test-Path -LiteralPath $updaterSignature -PathType Leaf) {
        throw "Unsigned builds require an empty updater-signature slot: $updaterSignature"
    }
} else {
    $updaterKeyPath = $env:TAURI_SIGNING_PRIVATE_KEY_PATH
    if (-not $updaterKeyPath) {
        $localUpdaterKey = Join-Path $env:USERPROFILE ".tauri\dronedream-updater.key"
        if (Test-Path -LiteralPath $localUpdaterKey -PathType Leaf) {
            $updaterKeyPath = $localUpdaterKey
        }
    }
    if (-not $updaterKeyPath -or
        -not (Test-Path -LiteralPath $updaterKeyPath -PathType Leaf)) {
        throw "Set TAURI_SIGNING_PRIVATE_KEY_PATH before signing the updater artifact."
    }
    $tauriCli = if ($detachedDependencyContract) {
        [string]$detachedDependencyContract.tauriCliPath
    } else {
        Join-Path $PSScriptRoot "..\node_modules\@tauri-apps\cli\tauri.js"
    }
    if (-not (Test-Path -LiteralPath $tauriCli -PathType Leaf)) {
        throw "The installed Tauri CLI was not found at $tauriCli"
    }
    & (Join-Path $PSScriptRoot "invoke-tauri-updater-signer.ps1") `
        -NodeExecutable "node.exe" `
        -TauriCliPath $tauriCli `
        -UpdaterKeyPath $updaterKeyPath `
        -InstallerPath $installer
}

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $installer
$checksumPath = "$installer.sha256"
"$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($installer))" |
    Set-Content -Encoding ascii -LiteralPath $checksumPath
Write-Host "Wrote verified installer checksum to $checksumPath"

if (-not $AllowUnsignedUpdater) {
    if (-not (Test-Path -LiteralPath $updaterSignature -PathType Leaf)) {
        throw "The signed Tauri updater artifact is missing: $updaterSignature"
    }
    & (Join-Path $PSScriptRoot "write-updater-manifest.ps1") `
        -BundleDirectory $bundleDirectory `
        -EditionId $EditionId `
        -SourceCommit $releaseSourceCommit `
        -BuildNumber ([UInt64]$releaseBuildNumber)
}

$bundleDirectoryFull = [IO.Path]::GetFullPath($bundleDirectory).TrimEnd('\', '/')
$expectedBundleRoot = [IO.Path]::GetFullPath(
    (Join-Path $targetOutputRoot "bundle\nsis")
).TrimEnd('\', '/')
if (-not $bundleDirectoryFull.Equals($expectedBundleRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to prune installer artifacts outside the MSVC NSIS bundle directory."
}
$currentArtifacts = @(
    [IO.Path]::GetFullPath($installer),
    [IO.Path]::GetFullPath($checksumPath),
    [IO.Path]::GetFullPath($updaterSignature)
)
if (-not $PreserveBundleHistory) {
    Get-ChildItem -LiteralPath $bundleDirectoryFull -File |
        Where-Object {
            $_.Name -match ("^" + [regex]::Escape($ExpectedProductName) +
                "_.+_x64-setup\.exe(?:\.sha256|\.sig)?$") -and
            $_.FullName -notin $currentArtifacts
        } |
        ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Host "Removed stale local installer artifact $($_.Name)"
        }
}
