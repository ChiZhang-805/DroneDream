param(
    [Parameter(Mandatory = $true)]
    [string]$Application,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedApplicationSha256,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedEvidenceHead,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [switch]$Plan,

    [switch]$Prepare
)

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-Git([string]$WorkingDirectory, [string[]]$Arguments) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git.exe"
    $quoted = @()
    if ($WorkingDirectory) {
        $quoted += @("-C", (Quote-ProcessArgument $WorkingDirectory))
    }
    $quoted += @($Arguments | ForEach-Object { Quote-ProcessArgument $_ })
    $startInfo.Arguments = $quoted -join " "
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Git command failed ($($process.ExitCode)): $($stderr.Trim())"
    }
    return $stdout.Trim()
}

function Assert-NoReparsePoint([string]$Path, [string]$Label) {
    $item = Get-Item -Force -LiteralPath $Path
    Assert-Contract (-not (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) `
        "$Label must not be a reparse point."
}

function Assert-ExactChildPath(
    [string]$Path,
    [string]$Parent,
    [string]$ExpectedLeaf,
    [string]$Label
) {
    $resolvedParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $resolvedPath = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $expectedPath = [IO.Path]::GetFullPath(
        (Join-Path $resolvedParent $ExpectedLeaf)
    ).TrimEnd('\', '/')
    Assert-Contract (
        $resolvedPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase)
    ) "$Label does not match its source-derived exact path."
    Assert-Contract ((Split-Path -Leaf $resolvedPath) -ceq $ExpectedLeaf) `
        "$Label leaf is not source-derived."
    return $resolvedPath
}

function Assert-FileBinding(
    [string]$Path,
    [int64]$ExpectedBytes,
    [string]$ExpectedSha256,
    [string]$Label
) {
    Assert-Contract (Test-Path -PathType Leaf -LiteralPath $Path) `
        "$Label is missing."
    $item = Get-Item -LiteralPath $Path
    $sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    Assert-Contract ($item.Length -eq $ExpectedBytes) "$Label byte count changed."
    Assert-Contract ($sha256 -ceq $ExpectedSha256) "$Label SHA-256 changed."
}

Assert-Contract ($Plan.IsPresent -xor $Prepare.IsPresent) `
    "Select exactly one of -Plan or -Prepare."
Assert-Contract ($ExpectedApplicationSha256 -cmatch '^[0-9a-f]{64}$') `
    "Expected application SHA-256 must be lowercase hexadecimal."
Assert-Contract ($ExpectedEvidenceHead -cmatch '^[0-9a-f]{40}$') `
    "Expected evidence HEAD must be an exact lowercase object ID."
Assert-Contract (Test-Path -PathType Container -LiteralPath $RepoRoot) `
    "Evidence repository does not exist."
Assert-Contract (Test-Path -PathType Leaf -LiteralPath $Application) `
    "Source-preparation application does not exist."

$resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$applicationSha256 = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $applicationPath
).Hash.ToLowerInvariant()
Assert-Contract ($applicationSha256 -ceq $ExpectedApplicationSha256) `
    "Source-preparation application SHA-256 changed."
$document = Get-Content -Raw -Encoding UTF8 -LiteralPath $applicationPath |
    ConvertFrom-Json
Assert-Contract ($document.kind -ceq "dronedream-field-yellow-source-preparation-application") `
    "Unknown source-preparation application kind."
Assert-Contract ($document.editionId -ceq "field") "Edition must be field."

$productCommit = [string]$document.source.productCommit
Assert-Contract ($productCommit -cmatch '^[0-9a-f]{40}$') `
    "Product commit must be exact lowercase hexadecimal."
$sourceId = $productCommit.Substring(0, 7)
Assert-Contract ($sourceId -ceq "6672320") "Unknown product source ID."
Assert-Contract ([int]$document.attemptOrdinal.sourcePreparation -eq 1) `
    "Source-preparation ordinal must be 1."
Assert-Contract ([int]$document.attemptOrdinal.retryMaximum -eq 0) `
    "Retry maximum must remain zero."

$sourceOwner = [IO.Path]::GetFullPath([string]$document.ownedPaths.sourceOwner)
$sourceRoot = Assert-ExactChildPath `
    ([string]$document.ownedPaths.sourceRoot) `
    $sourceOwner `
    "ddf6672320-preflight2-generate1" `
    "sourceRoot"
Assert-Contract (Test-Path -PathType Container -LiteralPath $sourceOwner) `
    "Source owner does not exist."
Assert-NoReparsePoint $sourceOwner "sourceOwner"
if (Test-Path -LiteralPath $sourceRoot) {
    Assert-NoReparsePoint $sourceRoot "sourceRoot"
    throw "Source root already exists."
}

$expectedDesktopTarget = [IO.Path]::GetFullPath(
    (Join-Path $resolvedRepo "desktop\node_modules")
)
$expectedFrontendTarget = [IO.Path]::GetFullPath(
    (Join-Path $resolvedRepo "frontend\node_modules")
)
Assert-Contract (
    [IO.Path]::GetFullPath([string]$document.junctions.desktop.target).Equals(
        $expectedDesktopTarget,
        [StringComparison]::OrdinalIgnoreCase
    )
) "Desktop node_modules junction target changed."
Assert-Contract (
    [IO.Path]::GetFullPath([string]$document.junctions.frontend.target).Equals(
        $expectedFrontendTarget,
        [StringComparison]::OrdinalIgnoreCase
    )
) "Frontend node_modules junction target changed."
foreach ($target in @($expectedDesktopTarget, $expectedFrontendTarget)) {
    Assert-Contract (Test-Path -PathType Container -LiteralPath $target) `
        "Bound node_modules target is unavailable: $target"
}

$head = Invoke-Git $resolvedRepo @("rev-parse", "HEAD")
$upstream = Invoke-Git $resolvedRepo @("rev-parse", "@{upstream}")
$status = Invoke-Git $resolvedRepo @("status", "--porcelain=v1", "--untracked-files=all")
Assert-Contract ($head -ceq $ExpectedEvidenceHead) "Evidence HEAD changed."
Assert-Contract ($upstream -ceq $ExpectedEvidenceHead) "Evidence upstream changed."
Assert-Contract (-not $status) "Evidence worktree is not clean."

$resolvedProduct = Invoke-Git $resolvedRepo @(
    "rev-parse", "--verify", "$productCommit^{commit}"
)
Assert-Contract ($resolvedProduct -ceq $productCommit) `
    "Product commit is unknown or ambiguous."
$productTree = Invoke-Git $resolvedRepo @("rev-parse", "$productCommit^{tree}")
Assert-Contract ($productTree -ceq [string]$document.source.productTree) `
    "Product tree changed."
$remoteEvidence = Invoke-Git $resolvedRepo @(
    "rev-parse", "refs/remotes/origin/codex/software-field"
)
Assert-Contract ($remoteEvidence -ceq $ExpectedEvidenceHead) `
    "Local authoritative evidence ref changed."
$originUrl = Invoke-Git $resolvedRepo @("config", "--get", "remote.origin.url")
Assert-Contract ($originUrl -ceq [string]$document.source.originUrl) `
    "Authoritative origin URL changed."

foreach ($binding in @($document.frozenRunFiles)) {
    Assert-FileBinding `
        ([string]$binding.path) `
        ([int64]$binding.bytes) `
        ([string]$binding.sha256) `
        ([string]$binding.id)
}
Assert-Contract (-not (Test-Path -LiteralPath ([string]$document.ownedPaths.cargoTarget))) `
    "Cargo target must remain absent."
Assert-Contract (-not (Test-Path -LiteralPath ([string]$document.ownedPaths.outputRoot))) `
    "Output root must remain absent."

if ($Prepare) {
    Invoke-Git "" @(
        "clone",
        "--shared",
        "--no-checkout",
        "--no-tags",
        $resolvedRepo,
        $sourceRoot
    ) | Out-Null
    Assert-NoReparsePoint $sourceRoot "sourceRoot"
    Invoke-Git $sourceRoot @("remote", "set-url", "origin", [string]$document.source.originUrl) |
        Out-Null
    Invoke-Git $sourceRoot @(
        "update-ref",
        "refs/remotes/origin/codex/software-field",
        $ExpectedEvidenceHead
    ) | Out-Null
    Invoke-Git $sourceRoot @("checkout", "--detach", $productCommit) | Out-Null

    $desktopLink = Join-Path $sourceRoot "desktop\node_modules"
    $frontendLink = Join-Path $sourceRoot "frontend\node_modules"
    New-Item -ItemType Junction -Path $desktopLink -Target $expectedDesktopTarget |
        Out-Null
    New-Item -ItemType Junction -Path $frontendLink -Target $expectedFrontendTarget |
        Out-Null

    Assert-NoReparsePoint $sourceRoot "sourceRoot"
    $preparedHead = Invoke-Git $sourceRoot @("rev-parse", "HEAD")
    $preparedTree = Invoke-Git $sourceRoot @("rev-parse", "HEAD^{tree}")
    $preparedStatus = Invoke-Git $sourceRoot @(
        "status", "--porcelain=v1", "--untracked-files=all"
    )
    $preparedRemote = Invoke-Git $sourceRoot @(
        "rev-parse", "refs/remotes/origin/codex/software-field"
    )
    Assert-Contract ($preparedHead -ceq $productCommit) `
        "Prepared source HEAD changed."
    Assert-Contract ($preparedTree -ceq [string]$document.source.productTree) `
        "Prepared source tree changed."
    Assert-Contract (-not $preparedStatus) "Prepared source is not clean."
    Assert-Contract ($preparedRemote -ceq $ExpectedEvidenceHead) `
        "Prepared evidence ref changed."
    foreach ($entry in @(
        @($desktopLink, $expectedDesktopTarget, "desktop"),
        @($frontendLink, $expectedFrontendTarget, "frontend")
    )) {
        $item = Get-Item -Force -LiteralPath $entry[0]
        Assert-Contract ($item.LinkType -ceq "Junction") `
            "$($entry[2]) node_modules is not a junction."
        $actualTarget = [IO.Path]::GetFullPath([string]$item.Target[0])
        Assert-Contract (
            $actualTarget.Equals($entry[1], [StringComparison]::OrdinalIgnoreCase)
        ) "$($entry[2]) node_modules junction target changed."
    }
}

$result = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-yellow-source-preparation"
    decision = if ($Plan) { "pass-plan-zero-write" } else { "prepared-once" }
    productSource = $productCommit
    productTree = [string]$document.source.productTree
    evidenceHead = $ExpectedEvidenceHead
    sourceRoot = $sourceRoot
    sourcePreparationOrdinal = 1
    retryMaximum = 0
    effects = [ordered]@{
        sourceRootCreated = [int]$Prepare.IsPresent
        detachedCheckoutCreated = [int]$Prepare.IsPresent
        junctionsCreated = if ($Prepare) { 2 } else { 0 }
        cargoTargetCreated = 0
        runFilesModified = 0
        outputRootCreated = 0
        preflightInvocations = 0
        buildInvocations = 0
    }
}
$result | ConvertTo-Json -Depth 8
