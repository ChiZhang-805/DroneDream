param(
    [Parameter(Mandatory = $true)]
    [string]$Application,
    [string]$WebViewLoader,
    [string]$ExpectedTarget
)

$ErrorActionPreference = "Stop"

$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\', '/')
$sandbox = Join-Path $tempRoot ("DroneDream-Planner-Smoke-" + [guid]::NewGuid().ToString("N"))
$sandboxFull = [IO.Path]::GetFullPath($sandbox)
$tempPrefix = $tempRoot + [IO.Path]::DirectorySeparatorChar
if (-not $sandboxFull.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to create a planner smoke directory outside TEMP: $sandboxFull"
}

$process = $null
try {
    New-Item -ItemType Directory -Path $sandboxFull | Out-Null
    # Names containing installer/setup trigger Windows' legacy installer
    # detection and can make an ordinary current-user launch fail with 740.
    $probe = Join-Path $sandboxFull "dronedream-runtime-probe.exe"
    Copy-Item -LiteralPath $applicationPath -Destination $probe
    if ($WebViewLoader) {
        $loaderPath = (Resolve-Path -LiteralPath $WebViewLoader).Path
        Copy-Item -LiteralPath $loaderPath -Destination (Join-Path $sandboxFull "WebView2Loader.dll")
    }

    $plan = Join-Path $sandboxFull "dronedream-installer-plan-v1.ini"
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $probe
    $startInfo.Arguments = "--write-installer-plan `"$plan`""
    $startInfo.WorkingDirectory = $sandboxFull
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        [void]$process.Start()
    } catch {
        throw "The extracted planner could not start without elevation: $($_.Exception.Message)"
    }
    if (-not $process.WaitForExit(90000)) {
        $process.Kill()
        throw "The extracted planner did not finish within 90 seconds"
    }
    $stdout = $process.StandardOutput.ReadToEnd().Trim()
    $stderr = $process.StandardError.ReadToEnd().Trim()
    if ($process.ExitCode -ne 0) {
        throw "The extracted planner exited with $($process.ExitCode). stdout='$stdout' stderr='$stderr'"
    }
    if (-not (Test-Path -LiteralPath $plan -PathType Leaf)) {
        throw "The extracted planner did not create its authenticated sibling result"
    }

    $entries = @{}
    foreach ($line in Get-Content -LiteralPath $plan) {
        if ($line -match '^([^=]+)=(.*)$') {
            $entries[$matches[1]] = $matches[2]
        }
    }
    foreach ($required in @(
        @{ Name = "schemaVersion"; Value = "1" },
        @{ Name = "downloadBytes"; Value = "8589934592" },
        @{ Name = "installedBytes"; Value = "25769803776" },
        @{ Name = "minimumFreeBytes"; Value = "55834574848" }
    )) {
        if ($entries[$required.Name] -cne $required.Value) {
            throw "Planner result has invalid $($required.Name): '$($entries[$required.Name])'"
        }
    }
    if ($entries.canInstall -notin @("0", "1")) {
        throw "Planner result has an invalid canInstall value"
    }
    if ($ExpectedTarget -and $entries.targetRoot -cne $ExpectedTarget) {
        throw "Planner recommended '$($entries.targetRoot)' instead of '$ExpectedTarget'"
    }
    Write-Host "Extracted current-user planner verified: target=$($entries.targetRoot) canInstall=$($entries.canInstall)"
}
finally {
    if ($null -ne $process) {
        $process.Dispose()
    }
    if (Test-Path -LiteralPath $sandboxFull) {
        Remove-Item -LiteralPath $sandboxFull -Recurse -Force
    }
}
