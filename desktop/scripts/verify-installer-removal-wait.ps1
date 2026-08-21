param()

$ErrorActionPreference = "Stop"
$waitScript = Join-Path $PSScriptRoot "wait-path-removal.ps1"
$stopWebViewScript = Join-Path $PSScriptRoot "stop-owned-webview2.ps1"
$workflow = Join-Path $PSScriptRoot "..\..\.github\workflows\desktop-installer.yml"

if (-not (Test-Path -LiteralPath $waitScript -PathType Leaf)) {
    throw "Installer path-removal wait helper is missing: $waitScript"
}
if (-not (Test-Path -LiteralPath $stopWebViewScript -PathType Leaf)) {
    throw "Owned WebView2 shutdown helper is missing: $stopWebViewScript"
}

$workflowText = Get-Content -LiteralPath $workflow -Raw
$stopWebViewCall = "./desktop/scripts/stop-owned-webview2.ps1"
$waitPathCall = "./desktop/scripts/wait-path-removal.ps1"
$stopWebViewIndex = $workflowText.IndexOf($stopWebViewCall, [System.StringComparison]::Ordinal)
$waitPathIndex = $workflowText.IndexOf($waitPathCall, [System.StringComparison]::Ordinal)
if ($waitPathIndex -lt 0) {
    throw "Desktop installer workflow does not invoke the path-removal wait helper"
}
if ($stopWebViewIndex -lt 0) {
    throw "Desktop installer workflow does not stop app-owned WebView2 processes"
}
if ($stopWebViewIndex -gt $waitPathIndex) {
    throw "Desktop installer workflow must stop app-owned WebView2 before waiting for uninstall"
}
if ($workflowText -notmatch "-TimeoutSeconds 30") {
    throw "Desktop installer workflow must keep the bounded 30-second removal deadline"
}

$unusedProfile = Join-Path ([System.IO.Path]::GetTempPath()) (
    "dronedream-webview-unused-{0}" -f [Guid]::NewGuid().ToString("N")
)
& $stopWebViewScript `
    -ProfilePath $unusedProfile `
    -TimeoutSeconds 1 `
    -PollIntervalMilliseconds 50

$missingPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "dronedream-removal-missing-{0}" -f [Guid]::NewGuid().ToString("N")
)
& $waitScript -LiteralPath $missingPath -TimeoutSeconds 1 -PollIntervalMilliseconds 10

$delayedPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "dronedream-removal-delayed-{0}.tmp" -f [Guid]::NewGuid().ToString("N")
)
Set-Content -LiteralPath $delayedPath -Value "pending"
$removalJob = Start-Job -ScriptBlock {
    param($PathToRemove)
    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath $PathToRemove -Force
} -ArgumentList $delayedPath

try {
    & $waitScript -LiteralPath $delayedPath -TimeoutSeconds 15 -PollIntervalMilliseconds 50
    Wait-Job -Job $removalJob -Timeout 5 | Out-Null
    Receive-Job -Job $removalJob -ErrorAction Stop | Out-Null
}
finally {
    Remove-Job -Job $removalJob -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $delayedPath -Force -ErrorAction SilentlyContinue
}

$persistentPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    "dronedream-removal-persistent-{0}.tmp" -f [Guid]::NewGuid().ToString("N")
)
Set-Content -LiteralPath $persistentPath -Value "still-present"
$timedOut = $false

try {
    & $waitScript -LiteralPath $persistentPath -TimeoutSeconds 1 -PollIntervalMilliseconds 25
}
catch {
    $timedOut = $_.Exception.Message -match "Timed out after 1 seconds"
}
finally {
    Remove-Item -LiteralPath $persistentPath -Force -ErrorAction SilentlyContinue
}

if (-not $timedOut) {
    throw "Path-removal wait helper did not fail closed for a persistent path"
}

Write-Host "Installer path-removal wait contract verified."
