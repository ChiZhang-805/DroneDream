param(
    [Parameter(Mandatory = $true)]
    [string] $LiteralPath,

    [ValidateRange(1, 300)]
    [int] $TimeoutSeconds = 30,

    [ValidateRange(10, 5000)]
    [int] $PollIntervalMilliseconds = 250
)

$ErrorActionPreference = "Stop"
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)

while (Test-Path -LiteralPath $LiteralPath) {
    if ([DateTime]::UtcNow -ge $deadline) {
        $rootFull = [System.IO.Path]::GetFullPath($LiteralPath).TrimEnd("\", "/")
        $rootPrefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
        $remainingItems = @(
            $rootItem = Get-Item -LiteralPath $rootFull -Force -ErrorAction SilentlyContinue
            if ($null -ne $rootItem) {
                [ordered]@{
                    path = "."
                    kind = if ($rootItem.PSIsContainer) { "directory" } else { "file" }
                    bytes = if ($rootItem.PSIsContainer) { $null } else { $rootItem.Length }
                    attributes = $rootItem.Attributes.ToString()
                }

                if ($rootItem.PSIsContainer) {
                    Get-ChildItem -LiteralPath $rootFull -Force -Recurse -ErrorAction SilentlyContinue |
                        ForEach-Object {
                            [ordered]@{
                                path = $_.FullName.Substring($rootPrefix.Length)
                                kind = if ($_.PSIsContainer) { "directory" } else { "file" }
                                bytes = if ($_.PSIsContainer) { $null } else { $_.Length }
                                attributes = $_.Attributes.ToString()
                            }
                        }
                }
            }
        )
        $matchingProcesses = @(
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object {
                    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith(
                        $rootPrefix,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )) -or ($_.CommandLine -and $_.CommandLine.Contains(
                        $rootFull,
                        [System.StringComparison]::OrdinalIgnoreCase
                    ))
                } |
                ForEach-Object {
                    [ordered]@{
                        pid = $_.ProcessId
                        parentPid = $_.ParentProcessId
                        name = $_.Name
                        executablePath = $_.ExecutablePath
                        commandLine = $_.CommandLine
                    }
                }
        )
        Write-Warning (
            "Remaining uninstall path inventory: " +
            ($remainingItems | ConvertTo-Json -Depth 4 -Compress)
        )
        Write-Warning (
            "Processes referencing uninstall path: " +
            ($matchingProcesses | ConvertTo-Json -Depth 4 -Compress)
        )
        throw "Timed out after $TimeoutSeconds seconds waiting for path removal: $LiteralPath"
    }

    Start-Sleep -Milliseconds $PollIntervalMilliseconds
}

Write-Host "Confirmed path removal: $LiteralPath"
