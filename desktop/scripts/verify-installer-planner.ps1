param(
    [Parameter(Mandatory = $true)]
    [string]$Application,
    [string]$WebViewLoader,
    [string]$ExpectedTarget,
    [ValidateSet("universal", "sim", "lab", "field", "autonomy")]
    [string]$EditionId = "universal"
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
$stdoutTask = $null
$stderrTask = $null

function Remove-PlannerSmokeSandbox {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedTempRoot,
        [int]$MaximumAttempts = 40,
        [int]$RetryDelayMilliseconds = 250
    )

    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $fullTempRoot = [IO.Path]::GetFullPath($ExpectedTempRoot).TrimEnd('\', '/')
    $expectedPrefix = $fullTempRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not [IO.Path]::GetFileName($fullPath).StartsWith("DroneDream-Planner-Smoke-", [StringComparison]::Ordinal)) {
        throw "Refusing to remove an unexpected planner smoke directory: $fullPath"
    }

    for ($attempt = 1; $attempt -le $MaximumAttempts; $attempt++) {
        if (-not (Test-Path -LiteralPath $fullPath)) {
            return
        }
        $root = Get-Item -LiteralPath $fullPath -Force
        if (($root.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to remove a reparse-point planner smoke directory: $fullPath"
        }
        try {
            Remove-Item -LiteralPath $fullPath -Recurse -Force
            if (-not (Test-Path -LiteralPath $fullPath)) {
                return
            }
        } catch [UnauthorizedAccessException], [IO.IOException] {
            if ($attempt -eq $MaximumAttempts) {
                throw
            }
        }
        Start-Sleep -Milliseconds $RetryDelayMilliseconds
    }
    throw "Planner smoke directory remained after $MaximumAttempts cleanup attempts: $fullPath"
}

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
    $startInfo.Arguments = if ($EditionId -eq "field") {
        "--clear-installer-handoff"
    } else {
        "--write-installer-plan `"$plan`""
    }
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
    # Drain both redirected pipes while the probe runs. Waiting first and
    # reading afterwards can deadlock when either native pipe buffer fills.
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(90000)) {
        $process.Kill()
        $process.WaitForExit()
        throw "The extracted planner did not finish within 90 seconds"
    }
    # Complete the native process-exit bookkeeping before releasing the copied
    # executable. Antivirus scanners can briefly retain the file afterwards,
    # so the finally block also uses a bounded exact-path retry.
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
    $stderr = $stderrTask.GetAwaiter().GetResult().Trim()
    if ($process.ExitCode -ne 0) {
        throw "The extracted planner exited with $($process.ExitCode). stdout='$stdout' stderr='$stderr'"
    }
    if ($EditionId -eq "field") {
        if (Test-Path -LiteralPath $plan) {
            throw "The FIELD app-only command unexpectedly created a Runtime plan."
        }
        Write-Host "Extracted FIELD app-only installer command verified."
        return
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
        Remove-PlannerSmokeSandbox -Path $sandboxFull -ExpectedTempRoot $tempRoot
    }
}
