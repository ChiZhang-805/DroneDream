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
    [int]$QuiescencePolls = 4,

    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"

$profilePathFull = [System.IO.Path]::GetFullPath($ProfilePath).TrimEnd("\", "/")
$profileToken = Split-Path -Leaf $profilePathFull
if ([string]::IsNullOrWhiteSpace($profileToken)) {
    throw "ProfilePath must identify an application-owned profile directory"
}
$installRootFull = if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    ""
}
else {
    [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd("\", "/")
}
$installRootPrefix = if ($installRootFull) {
    $installRootFull + [System.IO.Path]::DirectorySeparatorChar
}
else {
    ""
}

function Test-PathOwnedByInstallRoot {
    param([string]$Candidate)

    if (-not $installRootPrefix -or [string]::IsNullOrWhiteSpace($Candidate)) {
        return $false
    }

    try {
        $candidateFull = [System.IO.Path]::GetFullPath($Candidate)
        return $candidateFull.StartsWith(
            $installRootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    }
    catch {
        return $false
    }
}

function Get-OwnedDesktopProcesses {
    $processes = @(
        Get-CimInstance Win32_Process `
            -ErrorAction SilentlyContinue
    )

    $descendantIds = [System.Collections.Generic.HashSet[int]]::new()
    if ($RootProcessId -gt 0) {
        [void]$descendantIds.Add($RootProcessId)
        do {
            $foundDescendant = $false
            foreach ($process in $processes) {
                if (
                    $descendantIds.Contains([int]$process.ParentProcessId) -and
                    $descendantIds.Add([int]$process.ProcessId)
                ) {
                    $foundDescendant = $true
                }
            }
        } while ($foundDescendant)
    }

    $processes | Where-Object {
        if ([int]$_.ProcessId -eq $PID) {
            return $false
        }

        (
            $RootProcessId -gt 0 -and
            $descendantIds.Contains([int]$_.ProcessId)
        ) -or (Test-PathOwnedByInstallRoot $_.ExecutablePath) -or (
            $_.Name -ieq "msedgewebview2.exe" -and
            $_.CommandLine -and (
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
    $ownedProcesses = @(Get-OwnedDesktopProcesses)
    if ($ownedProcesses.Count -eq 0) {
        $quietPolls += 1
        if ($quietPolls -ge $QuiescencePolls) {
            exit 0
        }
    }
    else {
        $quietPolls = 0

        foreach ($ownedProcess in $ownedProcesses) {
            Write-Host (
                "Stopping owned desktop child: pid={0} parent={1} name={2}" -f
                $ownedProcess.ProcessId,
                $ownedProcess.ParentProcessId,
                $ownedProcess.Name
            )
            Stop-Process `
                -Id $ownedProcess.ProcessId `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds $PollIntervalMilliseconds
} while ([DateTime]::UtcNow -lt $deadline)

$remainingProcesses = @(Get-OwnedDesktopProcesses)
if ($remainingProcesses.Count -gt 0) {
    $remainingIds = ($remainingProcesses.ProcessId | Sort-Object) -join ", "
    throw (
        "Timed out after $TimeoutSeconds seconds stopping owned desktop processes " +
        "owned by profile '$profilePathFull', install root '$installRootFull', " +
        "or process ${RootProcessId}: " +
        $remainingIds
    )
}

throw (
    "Timed out after $TimeoutSeconds seconds waiting for owned desktop process quiescence " +
    "for profile '$profilePathFull', install root '$installRootFull', " +
    "or process $RootProcessId"
)
