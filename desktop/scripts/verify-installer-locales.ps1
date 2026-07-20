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
