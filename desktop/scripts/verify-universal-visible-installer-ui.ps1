param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{40}$")][string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-f]{64}$")][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][ValidateRange(1, [long]::MaxValue)][long]$ExpectedBytes,
    [Parameter(Mandatory = $true)][string]$OutputReceipt,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$receiptPath = [IO.Path]::GetFullPath($OutputReceipt)
$validationRoot = Join-Path (Split-Path -Parent $installerPath) "validation"
$uiVerifier = Join-Path $PSScriptRoot "verify-installer-ui.ps1"
$expectedApplication = Join-Path $env:LOCALAPPDATA "DroneDream-Universal"
$absentRecoveryControl = Join-Path (Split-Path -Parent $receiptPath) "absent-recovery-control.exe"

function Get-GitText([string[]]$Arguments) {
    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed." }
    return (($output | Out-String).Trim())
}

function Get-FileRecord([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required file is missing: $Path" }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $item.FullName
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Write-AtomicJson([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = "$Path.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText($temporary, (($Value | ConvertTo-Json -Depth 20) + "`n"), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

$head = Get-GitText @("rev-parse", "HEAD")
$upstream = Get-GitText @("rev-parse", "@{u}")
if ($head -cne $upstream -or (Get-GitText @("status", "--porcelain"))) {
    throw "Visible installer verifier requires an exact clean upstream tool source."
}
& git -C $repoRoot merge-base --is-ancestor $ProductSourceCommit $head
if ($LASTEXITCODE -ne 0) { throw "Product source is not an ancestor of the verifier source." }

$artifact = Get-FileRecord $installerPath
if ($artifact.bytes -ne $ExpectedBytes -or $artifact.sha256 -cne $ExpectedSha256) {
    throw "Frozen Universal artifact drifted."
}
if (-not $receiptPath.StartsWith(([IO.Path]::GetFullPath($validationRoot) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputReceipt must be a new owned child of the artifact validation directory."
}
if (Test-Path -LiteralPath $receiptPath) { throw "Refusing to overwrite an existing visible installer receipt." }
if (Test-Path -LiteralPath $absentRecoveryControl) { throw "Recovery control placeholder must remain absent." }

$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-visible-installer-ui-receipt"
    productSourceCommit = $ProductSourceCommit
    toolSourceCommit = $head
    artifact = $artifact
    executionAuthorized = [bool]$Execute
    exactCounts = [ordered]@{ installerProcesses = 0; installationCommits = 0; languages = 0 }
    cases = @()
    result = [ordered]@{ visibleInstallerUiReady = $false }
}

if (-not $Execute) {
    $receipt.kind = "dronedream-universal-visible-installer-ui-plan"
    Write-AtomicJson $receiptPath $receipt
    Write-Host "Universal visible installer UI plan frozen; no installer process started."
    exit 0
}

try {
    foreach ($language in @("English", "SimpChinese")) {
        $logRoot = Join-Path (Split-Path -Parent $receiptPath) "visible-installer-logs"
        New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
        $stdout = Join-Path $logRoot "$($language.ToLowerInvariant()).stdout.log"
        $stderr = Join-Path $logRoot "$($language.ToLowerInvariant()).stderr.log"
        $arguments = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $uiVerifier,
            "-Installer", $installerPath,
            "-Language", $language,
            "-InstallerProductName", "DroneDream-Universal",
            "-ExpectedApplication", $expectedApplication,
            "-RecoveryControlExecutable", $absentRecoveryControl,
            "-SimulateFreshInstall", "-ValidatePathGuard"
        )
        $receipt.exactCounts.installerProcesses++
        Write-AtomicJson $receiptPath $receipt
        $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -PassThru -Wait `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $exitCode = $process.ExitCode
        $process.Dispose()
        if ($exitCode -ne 0) { throw "Visible installer UI case $language failed with exit code $exitCode." }
        $receipt.exactCounts.languages++
        $receipt.cases += [ordered]@{
            language = $language
            expectedApplication = $expectedApplication
            pathGuard = $true
            installationCommitted = $false
            stdout = Get-FileRecord $stdout
            stderr = Get-FileRecord $stderr
        }
        Write-AtomicJson $receiptPath $receipt
    }
    if ($receipt.exactCounts.installerProcesses -ne 2 -or $receipt.exactCounts.languages -ne 2 -or $receipt.exactCounts.installationCommits -ne 0) {
        throw "Visible installer execution counts drifted from the frozen contract."
    }
    $receipt.result.visibleInstallerUiReady = $true
}
finally {
    $receipt.completedAt = [DateTime]::UtcNow.ToString("O")
    Write-AtomicJson $receiptPath $receipt
}

Write-Host "Universal visible installer UI passed for English and Simplified Chinese without installation commits."
