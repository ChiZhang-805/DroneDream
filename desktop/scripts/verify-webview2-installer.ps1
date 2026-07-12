param(
    [Parameter(Mandatory = $true)]
    [string]$GeneratedNsi
)

$ErrorActionPreference = "Stop"
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
if ($config.bundle.windows.webviewInstallMode.type -cne "embedBootstrapper") {
    throw "WebView2 bootstrapper must be embedded."
}
if ($config.bundle.windows.nsis.installerHooks -cne "nsis/webview2-health.nsh") {
    throw "The WebView2 NSIS health hook is not configured."
}

$hook = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\src-tauri\nsis\webview2-health.nsh") -Raw
foreach ($required in @(
    '"pv"',
    '"location"',
    'IfFileExists "$2\$1\msedgewebview2.exe"',
    'IfFileExists "$LOCALAPPDATA\Microsoft\EdgeWebView\Application\$1\msedgewebview2.exe"',
    'File "/oname=$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"',
    'ExecWait ''"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install''',
    'Abort "Microsoft WebView2 is still unusable'
)) {
    if (-not $hook.Contains($required)) {
        throw "WebView2 health hook is missing contract fragment: $required"
    }
}
if (([regex]::Matches($hook, 'Call DroneDreamWebView2IsUsable')).Count -lt 2) {
    throw "The WebView2 hook must probe before and after the official installer attempt."
}
$pvCheck = $hook.IndexOf('"pv"', [System.StringComparison]::Ordinal)
$fileCheck = $hook.IndexOf(
    'IfFileExists "$2\msedgewebview2.exe"',
    [System.StringComparison]::Ordinal
)
$readyAssignment = $hook.IndexOf('StrCpy $0 "1"', [System.StringComparison]::Ordinal)
if ($pvCheck -lt 0 -or $fileCheck -le $pvCheck -or $readyAssignment -le $fileCheck) {
    throw "A WebView2 pv value must not mark the runtime usable before a core executable is found."
}

$generated = Get-Content -LiteralPath (Resolve-Path -LiteralPath $GeneratedNsi) -Raw
if ($generated -notmatch '!define INSTALLWEBVIEW2MODE "embedBootstrapper"') {
    throw "Generated NSIS did not select embedBootstrapper."
}
$match = [regex]::Match($generated, '!define WEBVIEW2BOOTSTRAPPERPATH "([^"]+MicrosoftEdgeWebview2Setup\.exe)"')
if (-not $match.Success) {
    throw "Generated NSIS did not resolve the embedded WebView2 bootstrapper path."
}
$webViewSection = $generated.IndexOf('Section WebView2', [System.StringComparison]::Ordinal)
$healthHook = $generated.IndexOf('!insertmacro NSIS_HOOK_PREINSTALL', [System.StringComparison]::Ordinal)
$copyApplication = $generated.IndexOf('File "${MAINBINARYSRCPATH}"', [System.StringComparison]::Ordinal)
if ($webViewSection -lt 0 -or $healthHook -le $webViewSection -or $copyApplication -le $healthHook) {
    throw "The WebView2 health hook must run after Tauri prerequisite handling and before application files are copied."
}
$bootstrapper = $match.Groups[1].Value
if (-not (Test-Path -LiteralPath $bootstrapper -PathType Leaf)) {
    throw "Resolved WebView2 bootstrapper does not exist: $bootstrapper"
}
$signature = Get-AuthenticodeSignature -LiteralPath $bootstrapper
if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
    $signature.SignerCertificate.Subject -notmatch '(?i)\bMicrosoft Corporation\b') {
    throw "Embedded WebView2 bootstrapper is not validly signed by Microsoft Corporation."
}

Write-Host "Verified the WebView2 file-health contract and Microsoft-signed embedded bootstrapper."
