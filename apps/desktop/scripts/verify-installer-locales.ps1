param(
    [Parameter(Mandatory = $true)]
    [string]$GeneratedNsi,
    [string]$MakeNsis
)

$ErrorActionPreference = "Stop"

$generatedPath = (Resolve-Path -LiteralPath $GeneratedNsi).Path
if (-not $MakeNsis) {
    $MakeNsis = Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"
}
$makeNsisPath = (Resolve-Path -LiteralPath $MakeNsis).Path

# Compile the same language tables, without compressing the entire payload a
# second time. The shipping installer has already been compiled by Tauri.
$checkDirectory = Split-Path -Parent $generatedPath
$checkScript = Join-Path $checkDirectory "installer-locales.nsi"
$checkOutput = Join-Path $checkDirectory "installer-locales.exe"
$source = Get-Content -LiteralPath $generatedPath -Raw -Encoding UTF8
$compressionPattern = '(?m)^\s*SetCompressor\s+/SOLID\s+"[^"]+"\s*$'
$outputPattern = '(?m)^!define OUTFILE "[^"]+"\s*$'
if ([regex]::Matches($source, $compressionPattern).Count -ne 1 -or
    [regex]::Matches($source, $outputPattern).Count -ne 1) {
    throw "The generated installer compression/output declarations are not recognized."
}
$source = [regex]::Replace($source, $compressionPattern, "  SetCompressor zlib`n  SetCompress off")
$source = [regex]::Replace($source, $outputPattern, '!define OUTFILE "installer-locales.exe"')
try {
    [IO.File]::WriteAllText($checkScript, $source, [Text.UTF8Encoding]::new($false))
    $compilerOutput = (& $makeNsisPath /V4 $checkScript 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "MakeNSIS locale verification failed:`n$compilerOutput"
    }
} finally {
    foreach ($temporaryPath in @($checkScript, $checkOutput)) {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}
if ($compilerOutput -match 'warning 6030: LangString "DD_') {
    throw "A DroneDream language string was compiled more than once for the same locale"
}

foreach ($name in @(
    "DD_ModeHeader",
    "DD_InstallButton",
    "DD_RetryDetection",
    "DD_PlannerFailureDetails",
    "DD_SelectedDriveProbeFailed"
)) {
    $english = [regex]::Matches(
        $compilerOutput,
        "(?m)^LangString:\s+`"$([regex]::Escape($name))`"\s+1033\s+"
    ).Count
    $chinese = [regex]::Matches(
        $compilerOutput,
        "(?m)^LangString:\s+`"$([regex]::Escape($name))`"\s+2052\s+"
    ).Count
    if ($english -ne 1 -or $chinese -ne 1) {
        throw "$name must compile exactly once for English 1033 and Simplified Chinese 2052; observed $english/$chinese"
    }
}

Write-Host "Compiled installer locales verified: English=1033 SimplifiedChinese=2052"
