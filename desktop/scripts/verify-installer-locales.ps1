param(
    [Parameter(Mandatory = $true)]
    [string]$GeneratedNsi,
    [string]$MakeNsis
)

$ErrorActionPreference = "Stop"

$generatedPath = (Resolve-Path -LiteralPath $GeneratedNsi).Path
$generatedSource = Get-Content -LiteralPath $generatedPath -Raw -Encoding UTF8
$productMatches = [regex]::Matches(
    $generatedSource,
    '(?m)^!define\s+PRODUCTNAME\s+"([^"]+)"\s*$'
)
if ($productMatches.Count -ne 1) {
    throw "Generated NSIS must define PRODUCTNAME exactly once; observed $($productMatches.Count)"
}

$productName = $productMatches[0].Groups[1].Value
$runtimeModePageEnabled = switch ($productName) {
    "DroneDream-Universal" { $true }
    "DroneDream-Sim" { $true }
    "DroneDream-Lab" { $true }
    "DroneDream-Field" { $false }
    "DroneDream" { $true }
    default { throw "Unknown DroneDream installer PRODUCTNAME: $productName" }
}

if (-not $MakeNsis) {
    $MakeNsis = Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"
}
$makeNsisPath = (Resolve-Path -LiteralPath $MakeNsis).Path

# Recompile once with verbose output. This is intentionally a real compiler
# contract: the bug that mixed languages looked correct in source but emitted
# both locale tables as language 1033.
$compilerOutput = (& $makeNsisPath /V4 $generatedPath 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "MakeNSIS locale verification failed:`n$compilerOutput"
}
if ($compilerOutput -match 'warning 6030: LangString "DD_') {
    throw "A DroneDream language string was compiled more than once for the same locale"
}

$alwaysPresentNames = @(
    "DD_ShortcutConflict"
)
$runtimeModeNames = @(
    "DD_ModeHeader",
    "DD_InstallButton",
    "DD_RetryDetection",
    "DD_PlannerFailureDetails",
    "DD_SelectedDriveProbeFailed"
)

foreach ($name in $alwaysPresentNames + $runtimeModeNames) {
    $english = [regex]::Matches(
        $compilerOutput,
        "(?m)^LangString:\s+`"$([regex]::Escape($name))`"\s+1033\s+"
    ).Count
    $chinese = [regex]::Matches(
        $compilerOutput,
        "(?m)^LangString:\s+`"$([regex]::Escape($name))`"\s+2052\s+"
    ).Count
    $expected = 1
    if ($runtimeModeNames -contains $name -and -not $runtimeModePageEnabled) {
        $expected = 0
    }
    if ($english -ne $expected -or $chinese -ne $expected) {
        throw "$name must compile exactly $expected time(s) for English 1033 and Simplified Chinese 2052 for $productName; observed $english/$chinese"
    }
}

Write-Host "Compiled installer locales verified: product=$productName runtimeModePageEnabled=$runtimeModePageEnabled English=1033 SimplifiedChinese=2052"
