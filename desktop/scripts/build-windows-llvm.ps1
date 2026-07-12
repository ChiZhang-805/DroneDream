$ErrorActionPreference = "Stop"

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path -LiteralPath $cargoBin) {
    $env:PATH = "$cargoBin;$env:PATH"
}

$packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
$llvmPackage = Get-ChildItem -LiteralPath $packageRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "MartinStorsjo.LLVM-MinGW.UCRT_*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$clang = if ($llvmPackage) {
    Get-ChildItem -LiteralPath $llvmPackage.FullName -Recurse -Filter "x86_64-w64-mingw32-clang.exe" -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
} else {
    $null
}

if (-not $clang) {
    throw @"
LLVM-MinGW was not found. Install the portable compiler once with:
  winget install --id MartinStorsjo.LLVM-MinGW.UCRT --exact --scope user
"@
}

if (-not (Get-Command rustup.exe -ErrorAction SilentlyContinue)) {
    throw "rustup was not found. Install Rust before building DroneDream Desktop."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js before building DroneDream Desktop."
}

$toolchain = "1.97.0-x86_64-pc-windows-gnullvm"
& rustup.exe run $toolchain rustc --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw @"
$toolchain was not found. Install it once with:
  rustup toolchain install $toolchain --profile minimal
"@
}

$llvmBin = Split-Path -Parent $clang.FullName
$requiredTools = @(
    "llvm-dlltool.exe",
    "llvm-rc.exe",
    "llvm-readobj.exe",
    "ld.lld.exe"
)
$missingTools = @($requiredTools | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $llvmBin $_))
})
if ($missingTools.Count -gt 0) {
    throw "LLVM-MinGW is incomplete; missing: $($missingTools -join ', ')"
}

$env:PATH = "$llvmBin;$cargoBin;$env:PATH"
$env:RUSTUP_TOOLCHAIN = $toolchain
if (-not $env:CARGO_BUILD_JOBS) {
    $env:CARGO_BUILD_JOBS = "4"
}

# The gnullvm target otherwise links libunwind.dll dynamically. Tauri's NSIS
# bundler does not discover that toolchain DLL, so the installed application
# would fail before Rust can start. Keep this fallback build deterministic and
# link the LLVM runtime statically instead of depending on the build machine.
if ($env:RUSTFLAGS -or $env:CARGO_ENCODED_RUSTFLAGS) {
    throw "Clear custom RUSTFLAGS and CARGO_ENCODED_RUSTFLAGS before using the LLVM fallback build."
}
$env:RUSTFLAGS = "-C target-feature=+crt-static"

# webview2-com intentionally links WebView2Loader dynamically for non-MSVC
# targets. Locate the exact locked crate instead of relying on a user-specific
# Cargo registry path, then stage the redistributable loader for the NSIS
# resource map in tauri.llvm.conf.json.
$manifest = Join-Path $PSScriptRoot "..\src-tauri\Cargo.toml"
$metadataJson = (& rustup.exe run $toolchain cargo metadata `
    --locked `
    --format-version 1 `
    --manifest-path $manifest `
    --filter-platform x86_64-pc-windows-gnullvm | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Could not resolve the locked Cargo dependency graph."
}
try {
    $metadata = $metadataJson | ConvertFrom-Json
} catch {
    throw "Cargo returned invalid metadata: $($_.Exception.Message)"
}
$webViewPackages = @($metadata.packages | Where-Object {
    $_.name -ceq "webview2-com-sys"
})
if ($webViewPackages.Count -ne 1) {
    throw "Expected one locked webview2-com-sys package, found $($webViewPackages.Count)."
}
$webViewPackageRoot = Split-Path -Parent $webViewPackages[0].manifest_path
$webViewLoaderSource = Join-Path $webViewPackageRoot "x64\WebView2Loader.dll"
if (-not (Test-Path -LiteralPath $webViewLoaderSource -PathType Leaf)) {
    throw "The locked WebView2Loader.dll was not found at $webViewLoaderSource"
}
$loaderStageDirectory = Join-Path $PSScriptRoot "..\src-tauri\target\llvm-bundle"
$webViewLoaderStaged = Join-Path $loaderStageDirectory "WebView2Loader.dll"
New-Item -ItemType Directory -Force -Path $loaderStageDirectory | Out-Null
Copy-Item -LiteralPath $webViewLoaderSource -Destination $webViewLoaderStaged -Force

$llvmBundleConfig = Join-Path $PSScriptRoot "..\src-tauri\tauri.llvm.conf.json"
if (-not (Test-Path -LiteralPath $llvmBundleConfig -PathType Leaf)) {
    throw "The LLVM bundle configuration was not found at $llvmBundleConfig"
}

& (Join-Path $PSScriptRoot "verify-desktop-version.ps1")
& (Join-Path $PSScriptRoot "verify-nsis-template.ps1")

Write-Host "Building DroneDream Desktop with $toolchain"
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
& npm.cmd --prefix $desktopRoot run build -- `
    --target x86_64-pc-windows-gnullvm `
    --config $llvmBundleConfig
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$application = Join-Path $PSScriptRoot "..\src-tauri\target\x86_64-pc-windows-gnullvm\release\drone-dream-desktop.exe"
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "The LLVM build completed without producing $application"
}

$readObj = Join-Path $llvmBin "llvm-readobj.exe"
$importReport = (& $readObj --coff-imports $application | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the LLVM executable import table."
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
    $importReport -match "(?im)^\s*Name:\s*$([regex]::Escape($_))\s*$"
})
if ($dynamicToolchainDlls.Count -gt 0) {
    throw "The LLVM executable still depends on unbundled toolchain DLLs: $($dynamicToolchainDlls -join ', ')"
}

$loaderImportReport = (& $readObj --coff-imports $webViewLoaderStaged | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the staged WebView2Loader.dll import table."
}
$loaderToolchainDlls = @($forbiddenRuntimeDlls | Where-Object {
    $loaderImportReport -match "(?im)^\s*Name:\s*$([regex]::Escape($_))\s*$"
})
if ($loaderToolchainDlls.Count -gt 0) {
    throw "The staged WebView2 loader depends on unbundled toolchain DLLs: $($loaderToolchainDlls -join ', ')"
}
if ($importReport -notmatch "(?im)^\s*Name:\s*WebView2Loader\.dll\s*$") {
    throw "The LLVM executable no longer imports the staged WebView2Loader.dll; review the bundle contract."
}
Write-Host "Verified static LLVM runtime linkage and the bundled WebView2 loader."

$generatedNsi = Join-Path $PSScriptRoot "..\src-tauri\target\x86_64-pc-windows-gnullvm\release\nsis\x64\installer.nsi"
if (-not (Test-Path -LiteralPath $generatedNsi -PathType Leaf)) {
    throw "The LLVM build completed without producing $generatedNsi"
}
& (Join-Path $PSScriptRoot "verify-webview2-installer.ps1") -GeneratedNsi $generatedNsi
& (Join-Path $PSScriptRoot "verify-installer-locales.ps1") -GeneratedNsi $generatedNsi
& (Join-Path $PSScriptRoot "verify-installer-planner.ps1") `
    -Application $application `
    -WebViewLoader $webViewLoaderStaged

$tauriConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\src-tauri\tauri.conf.json") -Raw |
    ConvertFrom-Json
$bundleDirectory = Join-Path $PSScriptRoot "..\src-tauri\target\x86_64-pc-windows-gnullvm\release\bundle\nsis"
$installer = Join-Path $bundleDirectory "DroneDream_$($tauriConfig.version)_x64-setup.exe"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "The LLVM build completed without producing the versioned installer $installer"
}
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $installer
$checksumPath = "$installer.sha256"
"$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($installer))" |
    Set-Content -Encoding ascii -LiteralPath $checksumPath
Write-Host "Wrote verified installer checksum to $checksumPath"
