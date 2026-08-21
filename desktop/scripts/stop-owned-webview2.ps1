param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProfilePath,

    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 10,

    [ValidateRange(50, 5000)]
    [int]$PollIntervalMilliseconds = 250,

    [ValidateRange(0, 2147483647)]
    [int]$RootProcessId = 0,

    [ValidateRange(2, 20)]
    [int]$QuiescencePolls = 4
)

$ErrorActionPreference = "Stop"

$profilePathFull = [System.IO.Path]::GetFullPath($ProfilePath).TrimEnd("\", "/")
$profileToken = Split-Path -Leaf $profilePathFull
if ([string]::IsNullOrWhiteSpace($profileToken)) {
    throw "ProfilePath must identify an application-owned profile directory"
}

function Get-OwnedWebView2Processes {
    $webViewProcesses = @(
        Get-CimInstance Win32_Process `
            -Filter "Name = 'msedgewebview2.exe'" `
            -ErrorAction SilentlyContinue
    )

    $descendantIds = [System.Collections.Generic.HashSet[int]]::new()
    if ($RootProcessId -gt 0) {
        [void]$descendantIds.Add($RootProcessId)
        do {
            $foundDescendant = $false
            foreach ($process in $webViewProcesses) {
                if (
                    $descendantIds.Contains([int]$process.ParentProcessId) -and
                    $descendantIds.Add([int]$process.ProcessId)
                ) {
                    $foundDescendant = $true
                }
            }
        } while ($foundDescendant)
    }

    $webViewProcesses | Where-Object {
        (
            $RootProcessId -gt 0 -and
            $descendantIds.Contains([int]$_.ProcessId)
        ) -or ($_.CommandLine -and (
            $_.CommandLine.Contains(
                $profilePathFull,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            $_.CommandLine.Contains(
                $profileToken,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ))
    }
}

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$quietPolls = 0
do {
    $ownedProcesses = @(Get-OwnedWebView2Processes)
    if ($ownedProcesses.Count -eq 0) {
        $quietPolls += 1
        if ($quietPolls -ge $QuiescencePolls) {
            exit 0
        }
    }
    else {
        $quietPolls = 0

        foreach ($ownedProcess in $ownedProcesses) {
            Stop-Process `
                -Id $ownedProcess.ProcessId `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds $PollIntervalMilliseconds
} while ([DateTime]::UtcNow -lt $deadline)

$remainingProcesses = @(Get-OwnedWebView2Processes)
if ($remainingProcesses.Count -gt 0) {
    $remainingIds = ($remainingProcesses.ProcessId | Sort-Object) -join ", "
    throw (
        "Timed out after $TimeoutSeconds seconds stopping WebView2 processes " +
        "owned by profile '$profilePathFull' or process ${RootProcessId}: " +
        $remainingIds
    )
}

throw (
    "Timed out after $TimeoutSeconds seconds waiting for WebView2 quiescence " +
    "for profile '$profilePathFull' or process $RootProcessId"
)
