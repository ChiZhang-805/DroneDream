param(
    [string]$ApplicationPath = "$env:LOCALAPPDATA\DroneDream-Agent\drone-dream-desktop.exe",
    [string]$OutputRoot = "Q:\CodexData\Temp\dronedream-updater-minimized",
    [ValidateRange(49152, 65500)]
    [int]$CdpPort = 49441
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$frontendRoot = Join-Path $repoRoot "frontend"
$driverPath = Join-Path $frontendRoot "scripts\verify-installed-updater-flow.mjs"
$applicationFull = [IO.Path]::GetFullPath($ApplicationPath)
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot)

if (-not (Test-Path -LiteralPath $applicationFull -PathType Leaf)) {
    throw "Installed application was not found: $applicationFull"
}
if (-not (Test-Path -LiteralPath $driverPath -PathType Leaf)) {
    throw "Updater flow driver was not found: $driverPath"
}
$existingApplications = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $applicationFull }
)
if ($existingApplications.Count -ne 0) {
    throw "Close the installed application before running the isolated updater verifier."
}
New-Item -ItemType Directory -Path $outputRootFull -Force | Out-Null

$clickedPath = Join-Path $outputRootFull "clicked.signal"
$receiptPath = Join-Path $outputRootFull "updater-flow.json"
$stdoutPath = Join-Path $outputRootFull "driver.stdout.log"
$stderrPath = Join-Path $outputRootFull "driver.stderr.log"
foreach ($path in @($clickedPath, $receiptPath, $stdoutPath, $stderrPath)) {
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}

if ($null -eq ("DroneDreamUpdaterMinimizeNative" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class DroneDreamUpdaterMinimizeNative
{
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr window, int command);
}
'@
}

$nodePath = (Get-Command node -ErrorAction Stop).Source
$previousBrowserArguments = [Environment]::GetEnvironmentVariable(
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "Process"
)
$application = $null
$driver = $null
$verified = $false
try {
    [Environment]::SetEnvironmentVariable(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$CdpPort",
        "Process"
    )
    $application = Start-Process -FilePath $applicationFull -PassThru
    $driverArguments = @(
        "scripts/verify-installed-updater-flow.mjs",
        "--cdp-endpoint=http://127.0.0.1:$CdpPort",
        "--output=$receiptPath",
        "--screenshot-root=$outputRootFull",
        "--clicked-signal=$clickedPath"
    )
    $driver = Start-Process `
        -FilePath $nodePath `
        -ArgumentList $driverArguments `
        -WorkingDirectory $frontendRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
        -PassThru

    $clickDeadline = [DateTime]::UtcNow.AddMinutes(3)
    while (-not (Test-Path -LiteralPath $clickedPath) -and
        -not $driver.HasExited -and
        [DateTime]::UtcNow -lt $clickDeadline) {
        Start-Sleep -Milliseconds 250
        $driver.Refresh()
    }
    if (-not (Test-Path -LiteralPath $clickedPath -PathType Leaf)) {
        throw "The updater button was not clicked within three minutes."
    }

    $windowDeadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $application.Refresh()
        if ($application.MainWindowHandle -ne [IntPtr]::Zero) { break }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $windowDeadline)
    if ($application.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "The updater was clicked, but the application window could not be minimized."
    }
    [void][DroneDreamUpdaterMinimizeNative]::ShowWindow(
        $application.MainWindowHandle,
        6
    )
    Write-Host (
        "Minimized DroneDream immediately after the updater click: " +
        "pid=$($application.Id) hwnd=$($application.MainWindowHandle)"
    )

    if (-not $driver.WaitForExit(720000)) {
        Stop-Process -Id $driver.Id -Force
        throw "The installed updater flow exceeded twelve minutes."
    }
    if ($driver.ExitCode -ne 0) {
        $driverError = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            (Get-Content -LiteralPath $stderrPath -Raw).Trim()
        } else {
            "No driver error output was recorded."
        }
        throw "The installed updater flow failed with exit $($driver.ExitCode): $driverError"
    }
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "The installed updater flow produced no receipt."
    }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    if ([string]$receipt.status -cne "verified" -or
        -not [bool]$receipt.restartObserved -or
        @($receipt.progress | Where-Object { [string]$_.progress -ceq "100%" }).Count -eq 0 -or
        [int]$receipt.final.updateButtonCount -ne 0) {
        throw "The minimized updater receipt did not prove 100%, restart, and current state."
    }
    $verified = $true
    Write-Host "Installed minimized updater flow verified: $receiptPath"
    Get-Content -LiteralPath $receiptPath -Raw
} finally {
    if (-not $verified) {
        if ($null -ne $driver) {
            $driver.Refresh()
            if (-not $driver.HasExited) {
                Stop-Process -Id $driver.Id -Force -ErrorAction SilentlyContinue
            }
        }
        if ($null -ne $application) {
            $application.Refresh()
            if (-not $application.HasExited) {
                [void]$application.CloseMainWindow()
                if (-not $application.WaitForExit(5000)) {
                    Stop-Process -Id $application.Id -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }
    [Environment]::SetEnvironmentVariable(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        $previousBrowserArguments,
        "Process"
    )
}
