param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ExpectedSourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [Parameter(Mandatory = $true)]
    [string]$CargoTargetDir,
    [Parameter(Mandatory = $true)]
    [string]$LogRoot,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f-]{36}$")]
    [string]$OAuthClientId,
    [string]$GitHubRepository = "ChiZhang-805/DroneDream"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Invoke-GitText {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $text = (& git -C $sourcePath @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Git failed while checking the exact LAB product source."
    }
    return $text
}

function Get-PublicActionsVariable {
    param([Parameter(Mandatory = $true)][string]$Name)
    $value = (& gh variable get $Name --repo $GitHubRepository | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        throw "Approved public GitHub Actions variable is unavailable: $Name"
    }
    return $value
}

$sourcePath = [IO.Path]::GetFullPath($SourceRoot).TrimEnd("\")
$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")
$cargoPath = [IO.Path]::GetFullPath($CargoTargetDir).TrimEnd("\")
$logPath = [IO.Path]::GetFullPath($LogRoot).TrimEnd("\")
$ownedCache = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "DroneDream\codex-cache")
).TrimEnd("\")
foreach ($path in @($sourcePath, $outputPath, $cargoPath, $logPath)) {
    if (-not ($path + "\").StartsWith(
        $ownedCache + "\",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "LAB build paths must remain under the owned codex-cache root."
    }
}
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "The exact detached LAB product source worktree is missing."
}
if (Test-Path -LiteralPath $outputPath) {
    throw "The fresh LAB artifact OutputRoot already exists."
}
if (Test-Path -LiteralPath $logPath) {
    throw "The one-shot LAB log root already exists."
}
if ((Invoke-GitText @("rev-parse", "HEAD")) -cne $ExpectedSourceCommit) {
    throw "The detached LAB product source commit does not match."
}
if (Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")) {
    throw "The detached LAB product source is not clean."
}
if ((Invoke-GitText @("rev-parse", "--abbrev-ref", "HEAD")) -cne "HEAD") {
    throw "The LAB product source must remain detached at the exact commit."
}

$os = Get-CimInstance Win32_OperatingSystem
$freeGiB = [double]$os.FreePhysicalMemory / 1MB
$usedPercent = (1 - ([double]$os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100
if ($usedPercent -ge 80 -or $freeGiB -lt 3) {
    throw "The LAB build resource gate is closed."
}
$heavy = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(cargo|rustc|tauri|makensis|px4|gazebo)\.exe$'
})
if ($heavy.Count -ne 0) {
    throw "Another heavy build, simulator, or hardware process is active."
}

$publicUrl = Get-PublicActionsVariable -Name "VITE_SUPABASE_URL"
$publicKey = Get-PublicActionsVariable -Name "VITE_SUPABASE_PUBLISHABLE_KEY"
$keyPath = Join-Path $env:USERPROFILE ".tauri\dronedream-updater.key"
if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) {
    throw "The controller-approved updater signing key path is unavailable."
}

New-Item -ItemType Directory -Path $logPath | Out-Null
$stdoutPath = Join-Path $logPath "build.stdout.log"
$stderrPath = Join-Path $logPath "build.stderr.log"
$oldEnvironment = [ordered]@{}
foreach ($name in @(
    "CARGO_BUILD_JOBS",
    "DRONEDREAM_OAUTH_CLIENT_ID",
    "TAURI_SIGNING_PRIVATE_KEY_PATH",
    "TAURI_SIGNING_PRIVATE_KEY_PASSWORD",
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_PUBLISHABLE_KEY"
)) {
    $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $env:CARGO_BUILD_JOBS = "2"
    $env:DRONEDREAM_OAUTH_CLIENT_ID = $OAuthClientId
    $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $keyPath
    $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
    $env:VITE_SUPABASE_URL = $publicUrl
    $env:VITE_SUPABASE_PUBLISHABLE_KEY = $publicKey

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "desktop\scripts\build-lab-preview.ps1",
        "-Build",
        "-Toolchain", "gnullvm",
        "-OutputRoot", $outputPath,
        "-CargoTargetDir", $cargoPath,
        "-ExpectedSourceCommit", $ExpectedSourceCommit
    )
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $arguments `
        -WorkingDirectory $sourcePath `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru `
        -Wait `
        -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) {
            throw "The exact LAB build process exited with code $($process.ExitCode)."
        }
    } finally {
        $process.Dispose()
    }
} finally {
    foreach ($entry in $oldEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
    $publicUrl = $null
    $publicKey = $null
}

Write-Output ([ordered]@{
    result = "build-process-passed"
    productSourceCommit = $ExpectedSourceCommit
    outputRoot = $outputPath
    logRoot = $logPath
    stdoutLog = $stdoutPath
    stderrLog = $stderrPath
    publicVariableValuesRecorded = $false
} | ConvertTo-Json -Compress)
