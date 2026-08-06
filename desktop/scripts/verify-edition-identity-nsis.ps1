[CmdletBinding()]
param(
    [string]$MakensisPath
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$identityPath = Join-Path $repoRoot "desktop\src-tauri\nsis\edition-identity.nsh"
if (-not (Test-Path -LiteralPath $identityPath -PathType Leaf)) {
    throw "The canonical edition identity include is unavailable."
}

if (-not $MakensisPath) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"),
        (Join-Path $env:LOCALAPPDATA "Tauri\NSIS\makensis.exe")
    )
    $MakensisPath = @($candidates | Where-Object {
        Test-Path -LiteralPath $_ -PathType Leaf
    } | Select-Object -First 1)
}
if (-not $MakensisPath -or
    -not (Test-Path -LiteralPath $MakensisPath -PathType Leaf)) {
    throw "makensis.exe is required for the edition identity compile contract."
}
$MakensisPath = (Resolve-Path -LiteralPath $MakensisPath).Path

$temporaryRoot = Join-Path $env:TEMP (
    "dronedream-edition-identity-nsis-{0}" -f [guid]::NewGuid().ToString("N")
)
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
$encoding = [Text.UTF8Encoding]::new($false)
$fixtureTemplate = @'
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!define PRODUCTNAME "__PRODUCT_NAME__"
!define MAINBINARYNAME "drone-dream-desktop"
!define STARTMENUFOLDER ""
!define BUNDLEID "__BUNDLE_ID__"
Var WixMode
Var UpdateMode
Var NoShortcutMode
Var PassiveMode
Var AppStartMenuFolder
Var OldMainBinaryName
!macro IsShortcutTarget SHORTCUT_PATH TARGET_PATH
  Push 1
!macroend
!macro SetLnkAppUserModelId SHORTCUT_PATH
!macroend
LangString DD_ShortcutConflict ${LANG_ENGLISH} "Shortcut conflict"
!include "__IDENTITY_PATH__"
Name "${DRONEDREAM_DISPLAYNAME} identity fixture"
OutFile "__OUTPUT_PATH__"
RequestExecutionLevel user
Section
  StrCpy $WixMode 0
  StrCpy $UpdateMode 0
  StrCpy $NoShortcutMode 0
  StrCpy $PassiveMode 0
  StrCpy $AppStartMenuFolder "DroneDream"
  StrCpy $OldMainBinaryName "DroneDream.exe"
  !insertmacro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT fixture_startmenu_first
  !insertmacro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT fixture_startmenu_second
  !insertmacro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT fixture_desktop_first
  !insertmacro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT fixture_desktop_second
SectionEnd
'@

function Invoke-FixtureCompile {
    param(
        [Parameter(Mandatory = $true)][string]$EditionId,
        [Parameter(Mandatory = $true)][string]$ProductName,
        [Parameter(Mandatory = $true)][bool]$ExpectedSuccess
    )

    $fixturePath = Join-Path $temporaryRoot "$EditionId.nsi"
    $outputPath = Join-Path $temporaryRoot "$EditionId.exe"
    $fixture = $fixtureTemplate.
        Replace("__PRODUCT_NAME__", $ProductName).
        Replace("__BUNDLE_ID__", "io.dronedream.desktop.$EditionId").
        Replace("__IDENTITY_PATH__", $identityPath.Replace("\", "\\")).
        Replace("__OUTPUT_PATH__", $outputPath.Replace("\", "\\"))
    [IO.File]::WriteAllText($fixturePath, $fixture, $encoding)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& $MakensisPath /V4 $fixturePath 2>&1 | Out-String)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($ExpectedSuccess) {
        if ($exitCode -ne 0 -or
            -not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "NSIS edition identity fixture failed for ${EditionId}: $output"
        }
        return [ordered]@{
            editionId = $EditionId
            productName = $ProductName
            repeatedExpansionCompiled = $true
            outputBytes = (Get-Item -LiteralPath $outputPath).Length
        }
    }
    if ($exitCode -eq 0 -or
        $output -notmatch "Unknown DroneDream installer PRODUCTNAME") {
        throw "Unknown NSIS edition did not fail closed: $output"
    }
    return [ordered]@{
        editionId = $EditionId
        productName = $ProductName
        rejected = $true
        reason = "unknown-product-name"
    }
}

try {
    $results = @(
        Invoke-FixtureCompile -EditionId "universal" -ProductName "DroneDream-Universal" -ExpectedSuccess $true
        Invoke-FixtureCompile -EditionId "sim" -ProductName "DroneDream-Sim" -ExpectedSuccess $true
        Invoke-FixtureCompile -EditionId "lab" -ProductName "DroneDream-Lab" -ExpectedSuccess $true
        Invoke-FixtureCompile -EditionId "field" -ProductName "DroneDream-Field" -ExpectedSuccess $true
        Invoke-FixtureCompile -EditionId "unknown" -ProductName "DroneDream-Unknown" -ExpectedSuccess $false
    )
    [ordered]@{
        kind = "dronedream-edition-identity-nsis-compile-check"
        makensis = [IO.Path]::GetFileName($MakensisPath)
        fixtures = $results
        temporaryOutputsRetained = $false
    } | ConvertTo-Json -Depth 5
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolved = (Resolve-Path -LiteralPath $temporaryRoot).Path
        $expectedParent = [IO.Path]::GetFullPath($env:TEMP).TrimEnd("\") + "\"
        if (-not ($resolved + "\").StartsWith(
                $expectedParent,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            -not (Split-Path -Leaf $resolved).StartsWith(
                "dronedream-edition-identity-nsis-"
            )) {
            throw "Refusing to remove an unexpected NSIS fixture directory."
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
