$ErrorActionPreference = "Stop"

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

if (-not (Get-Command rustup -ErrorAction SilentlyContinue)) {
    throw "rustup was not found. Install Rust before building DroneDream Desktop."
}

$toolchain = "stable-x86_64-pc-windows-gnullvm"
& rustup run $toolchain rustc --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw @"
$toolchain was not found. Install it once with:
  rustup toolchain install $toolchain --profile minimal
"@
}

$llvmBin = Split-Path -Parent $clang.FullName
$env:PATH = "$llvmBin;$env:USERPROFILE\.cargo\bin;$env:PATH"
$env:RUSTUP_TOOLCHAIN = $toolchain
if (-not $env:CARGO_BUILD_JOBS) {
    $env:CARGO_BUILD_JOBS = "4"
}

Write-Host "Building DroneDream Desktop with $toolchain"
& npm run build -- --target x86_64-pc-windows-gnullvm
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
