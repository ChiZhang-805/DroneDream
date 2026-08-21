param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProfilePath,

    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 10,

    [ValidateRange(50, 5000)]
    [int]$PollIntervalMilliseconds = 250
)

$ErrorActionPreference = "Stop"

$profilePathFull = [System.IO.Path]::GetFullPath($ProfilePath).TrimEnd("\", "/")
$profileToken = Split-Path -Leaf $profilePathFull
if ([string]::IsNullOrWhiteSpace($profileToken)) {
    throw "ProfilePath must identify an application-owned profile directory"
}

function Get-OwnedWebView2Processes {
    @(
        Get-CimInstance Win32_Process `
            -Filter "Name = 'msedgewebview2.exe'" `
            -ErrorAction SilentlyContinue
    ) | Where-Object {
        $_.CommandLine -and (
            $_.CommandLine.Contains(
                $profilePathFull,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            $_.CommandLine.Contains(
                $profileToken,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        )
    }
}

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
do {
    $ownedProcesses = @(Get-OwnedWebView2Processes)
    if ($ownedProcesses.Count -eq 0) {
        exit 0
    }

    foreach ($ownedProcess in $ownedProcesses) {
        Stop-Process `
            -Id $ownedProcess.ProcessId `
            -Force `
            -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds $PollIntervalMilliseconds
} while ([DateTime]::UtcNow -lt $deadline)

$remainingProcesses = @(Get-OwnedWebView2Processes)
if ($remainingProcesses.Count -gt 0) {
    $remainingIds = ($remainingProcesses.ProcessId | Sort-Object) -join ", "
    throw (
        "Timed out after $TimeoutSeconds seconds stopping WebView2 processes " +
        "owned by profile '$profilePathFull': $remainingIds"
    )
}
