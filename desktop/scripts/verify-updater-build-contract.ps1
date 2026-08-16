$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$config = Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\src-tauri\tauri.conf.json"
) -Raw | ConvertFrom-Json
$universalConfig = Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\src-tauri\tauri.universal.conf.json"
) -Raw | ConvertFrom-Json
$familyContract = Get-Content -LiteralPath (
    Join-Path $repoRoot "distribution\desktop\edition-runtime-update-families.v1.json"
) -Raw | ConvertFrom-Json
Assert-Contract ($config.version -ceq "1.0.0") `
    "The user-visible internal-test version must remain 1.0.0."
Assert-Contract (
    $config.plugins.updater.PSObject.Properties.Name -notcontains "endpoints"
) "The shared base config must not contain a cross-edition updater endpoint."
Assert-Contract (
    $universalConfig.plugins.updater.endpoints.Count -eq 1 -and
    $universalConfig.plugins.updater.endpoints[0] -ceq (
        $familyContract.editions |
            Where-Object { $_.editionId -ceq "universal" } |
            Select-Object -ExpandProperty updaterMetadataUrl
    )
) "The Universal updater endpoint must be exact and edition-scoped."

$buildScript = Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\src-tauri\build.rs"
) -Raw -Encoding UTF8
$updateSource = Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\src-tauri\src\app_update.rs"
) -Raw -Encoding UTF8
$llvmBuildScript = Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\scripts\build-windows-llvm.ps1"
) -Raw -Encoding UTF8
Assert-Contract ($buildScript.Contains('DRONEDREAM_BUILD_NUMBER')) `
    "The desktop build must embed a monotonic updater build number."
Assert-Contract ($buildScript.Contains('DRONEDREAM_SOURCE_COMMIT')) `
    "The desktop build must embed its exact source commit."
Assert-Contract ($updateSource.Contains('remote_build_number > local_build_number')) `
    "Equal-version updates must compare strictly increasing build numbers."
Assert-Contract ($updateSource.Contains('remote_source_commit != env!("DRONEDREAM_SOURCE_COMMIT")')) `
    "Equal-version updates must reject the currently installed source commit."
Assert-Contract ($updateSource.Contains('edition_id == COMPILED_EDITION_ID')) `
    "Every updater version must match the compiled desktop edition."
Assert-Contract ($buildScript.Contains('cargo:rerun-if-env-changed=DRONEDREAM_RELEASE_SOURCE_COMMIT')) `
    "The embedded Engine Pack must be rebuilt when frozen release provenance changes."
Assert-Contract ($buildScript.Contains('cargo:rerun-if-env-changed=DRONEDREAM_EDITION_PROFILE')) `
    "The embedded Engine Pack must be rebuilt when the edition profile changes."
Assert-Contract ($buildScript.Contains('--edition-profile')) `
    "The embedded Engine Pack build must bind an explicit edition profile."
Assert-Contract ($buildScript.Contains('["rev-parse", "--git-path", &symbolic_ref]')) `
    "The embedded Engine Pack must track the active Git branch ref."
foreach ($requiredText in @(
    'prepare_generated_directory(&output_directory)',
    'std::fs::symlink_metadata(path)',
    'metadata.is_dir() && !metadata.file_type().is_symlink()',
    'std::fs::remove_dir_all(path)'
)) {
    Assert-Contract ($buildScript.Contains($requiredText)) `
        "Repeated builds are missing the safe generated Engine Pack reset contract: $requiredText"
}
foreach ($requiredText in @(
    'status --porcelain=v1 --untracked-files=all',
    '$env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $releaseSourceCommit',
    '-SourceCommit $releaseSourceCommit',
    '-BuildNumber ([UInt64]$releaseBuildNumber)',
    '-EditionId $EditionId',
    '[IO.Path]::GetFullPath($updaterSignature)',
    '(?:\.sha256|\.sig)?$'
)) {
    Assert-Contract ($llvmBuildScript.Contains($requiredText)) `
        "The LLVM release build is missing its exact-source contract: $requiredText"
}

$temporaryRoot = Join-Path $env:TEMP (
    "dronedream-updater-build-contract-{0}" -f [Guid]::NewGuid().ToString("N")
)
$bundle = Join-Path $temporaryRoot "bundle"
try {
    New-Item -ItemType Directory -Force -Path $bundle | Out-Null
    $sourceCommit = "1234567890abcdef1234567890abcdef12345678"
    $metadataPaths = @()
    $downloadUrls = @()
    foreach ($family in @($familyContract.editions)) {
        $installerName = [string]$family.tauriBundleInstallerFileName
        [IO.File]::WriteAllBytes(
            (Join-Path $bundle $installerName),
            [byte[]](1, 2, 3)
        )
        [IO.File]::WriteAllText(
            (Join-Path $bundle "$installerName.sig"),
            "test-$($family.editionId)-updater-signature`n",
            (New-Object Text.UTF8Encoding($false))
        )
        & (Join-Path $PSScriptRoot "write-updater-manifest.ps1") `
            -BundleDirectory $bundle `
            -Repository "example/DroneDream" `
            -EditionId ([string]$family.editionId) `
            -SourceCommit $sourceCommit `
            -BuildNumber 42
        $metadataPath = Join-Path $bundle ([string]$family.updaterMetadataFileName)
        $manifest = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
        $expectedUrl = "https://github.com/example/DroneDream/releases/download/" +
            "desktop-$($family.editionId)-v1.0.0-build-42/$($family.publicArtifactFileName)"
        Assert-Contract ($manifest.version -ceq "1.0.0") `
            "Updater metadata exposed a version other than 1.0.0."
        Assert-Contract ($manifest.notes -cmatch "(?m)^edition-id: $($family.editionId)`$") `
            "Updater metadata omitted its exact edition identity."
        Assert-Contract ($manifest.notes -cmatch '(?m)^build-number: 42$') `
            "Updater metadata omitted the exact build number."
        Assert-Contract ($manifest.notes -cmatch "(?m)^source-commit: $sourceCommit`$") `
            "Updater metadata omitted the exact source commit."
        Assert-Contract ($manifest.updatePolicy -ceq "recommended") `
            "Routine updater metadata must default to the non-blocking recommended policy."
        Assert-Contract ($manifest.notes -cmatch '(?m)^update-policy: recommended$') `
            "Updater metadata omitted its signed update policy."
        Assert-Contract (
            $manifest.platforms.'windows-x86_64'.url -ceq $expectedUrl
        ) "Updater metadata crossed an edition URL family."
        $metadataPaths += $metadataPath
        $downloadUrls += $manifest.platforms.'windows-x86_64'.url
    }
    Assert-Contract (-not (Test-Path -LiteralPath (Join-Path $bundle "latest.json"))) `
        "A generic latest.json must not alias an edition updater family."
    Assert-Contract (($metadataPaths | Sort-Object -Unique).Count -eq 4) `
        "Edition updater metadata filenames collided."
    Assert-Contract (($downloadUrls | Sort-Object -Unique).Count -eq 4) `
        "Edition updater download URL families collided."
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}

Write-Host (
    "Verified display-version 1.0.0, monotonic Build ID, and four isolated " +
    "desktop updater URL families."
)
