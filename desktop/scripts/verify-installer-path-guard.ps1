param(
    [string]$MakeNsis
)

$ErrorActionPreference = "Stop"

if (-not $MakeNsis) {
    $MakeNsis = Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"
}
$makeNsisPath = (Resolve-Path -LiteralPath $MakeNsis).Path
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\', '/')
$sandbox = Join-Path $tempRoot ("DroneDream-Path-Guard-" + [guid]::NewGuid().ToString("N"))
$sandboxFull = [IO.Path]::GetFullPath($sandbox)
if (-not $sandboxFull.StartsWith($tempRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to create an NSIS path-guard test outside TEMP"
}

try {
    New-Item -ItemType Directory -Path $sandboxFull | Out-Null
    $sourcePath = Join-Path $sandboxFull "path-check.nsi"
    $executablePath = Join-Path $sandboxFull "dronedream-path-check.exe"
    $escapedExecutable = $executablePath.Replace('\', '\\')
    $source = @"
Unicode true
SilentInstall silent
AutoCloseWindow true
RequestExecutionLevel user
OutFile "$escapedExecutable"
!include "LogicLib.nsh"
!include "StrFunc.nsh"
`${StrCase}
`${StrLoc}

Section
  ; A normal application path on C: must not be treated as a child of the
  ; dedicated Runtime root on E:. StrLoc returns an empty string here.
  StrCpy `$1 "C:\Users\Test\AppData\Local\DroneDream"
  StrCpy `$2 "E:\DroneDream"
  `${StrCase} `$1 `$1 "U"
  `${StrCase} `$2 `$2 "U"
  StrCpy `$3 "`$2\"
  `${StrLoc} `$0 `$1 `$3 ">"
  StrCmp `$0 "0" unrelated_failed unrelated_passed
unrelated_failed:
  SetErrorLevel 21
  Quit

unrelated_passed:
  ; A real child path must still be rejected; StrLoc returns the string "0".
  StrCpy `$1 "E:\DroneDream\Desktop"
  `${StrCase} `$1 `$1 "U"
  `${StrLoc} `$0 `$1 `$3 ">"
  StrCmp `$0 "0" child_detected child_missed
child_missed:
  SetErrorLevel 22
  Quit

child_detected:
  SetErrorLevel 0
  Quit
SectionEnd
"@
    [IO.File]::WriteAllText($sourcePath, $source, [Text.UTF8Encoding]::new($false))
    $compilerOutput = (& $makeNsisPath /V2 $sourcePath 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not compile the NSIS path-guard contract:`n$compilerOutput"
    }
    & $executablePath
    if ($LASTEXITCODE -ne 0) {
        throw "NSIS path guard failed with exit code $LASTEXITCODE"
    }
    Write-Host "NSIS application/Runtime path guard verified"
}
finally {
    if (Test-Path -LiteralPath $sandboxFull) {
        for ($attempt = 0; $attempt -lt 10; $attempt++) {
            try {
                Remove-Item -LiteralPath $sandboxFull -Recurse -Force -ErrorAction Stop
                break
            } catch {
                if ($attempt -eq 9) { throw }
                Start-Sleep -Milliseconds 200
            }
        }
    }
}
