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

$toolchain = "stable-x86_64-pc-windows-gnullvm"
& rustup.exe run $toolchain rustc --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw @"
$toolchain was not found. Install it once with:
  rustup toolchain install $toolchain --profile minimal
"@
}

$llvmBin = Split-Path -Parent $clang.FullName
$requiredTools = @("llvm-dlltool.exe", "llvm-rc.exe", "ld.lld.exe")
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

Write-Host "Building DroneDream Desktop with $toolchain"
& npm.cmd run build -- --target x86_64-pc-windows-gnullvm
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
