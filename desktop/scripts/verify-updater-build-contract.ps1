$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$config = Get-Content -LiteralPath (
    Join-Path $repoRoot "desktop\src-tauri\tauri.conf.json"
) -Raw | ConvertFrom-Json
Assert-Contract ($config.version -ceq "1.0.0") `
    "The user-visible internal-test version must remain 1.0.0."

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
Assert-Contract ($buildScript.Contains('cargo:rerun-if-env-changed=DRONEDREAM_RELEASE_SOURCE_COMMIT')) `
    "The embedded Engine Pack must be rebuilt when frozen release provenance changes."
Assert-Contract ($buildScript.Contains('["rev-parse", "--git-path", &symbolic_ref]')) `
    "The embedded Engine Pack must track the active Git branch ref."
foreach ($requiredText in @(
    'status --porcelain=v1 --untracked-files=all',
    '$env:DRONEDREAM_RELEASE_SOURCE_COMMIT = $releaseSourceCommit',
    '-SourceCommit $releaseSourceCommit',
    '-BuildNumber ([UInt64]$releaseBuildNumber)'
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
    $installerName = "DroneDream_1.0.0_x64-setup.exe"
    [IO.File]::WriteAllBytes((Join-Path $bundle $installerName), [byte[]](1, 2, 3))
    [IO.File]::WriteAllText(
        (Join-Path $bundle "$installerName.sig"),
        "test-updater-signature`n",
        (New-Object Text.UTF8Encoding($false))
    )
    $sourceCommit = "1234567890abcdef1234567890abcdef12345678"
    & (Join-Path $PSScriptRoot "write-updater-manifest.ps1") `
        -BundleDirectory $bundle `
        -Repository "example/DroneDream" `
        -SourceCommit $sourceCommit `
        -BuildNumber 42
    $manifest = Get-Content -LiteralPath (Join-Path $bundle "latest.json") -Raw |
        ConvertFrom-Json
    Assert-Contract ($manifest.version -ceq "1.0.0") `
        "Updater metadata exposed a version other than 1.0.0."
    Assert-Contract ($manifest.notes -cmatch '(?m)^build-number: 42$') `
        "Updater metadata omitted the exact build number."
    Assert-Contract ($manifest.notes -cmatch "(?m)^source-commit: $sourceCommit`$") `
        "Updater metadata omitted the exact source commit."
    Assert-Contract (
        $manifest.platforms.'windows-x86_64'.url -ceq
            "https://github.com/example/DroneDream/releases/download/desktop-v1.0.0/$installerName"
    ) "Updater metadata changed the public 1.0.0 filename or tag."
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}

Write-Host "Verified display-version 1.0.0 plus monotonic updater Build ID contract."
