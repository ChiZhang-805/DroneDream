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
        throw "Timed out after $TimeoutSeconds seconds waiting for path removal: $LiteralPath"
    }

    Start-Sleep -Milliseconds $PollIntervalMilliseconds
}

Write-Host "Confirmed path removal: $LiteralPath"
