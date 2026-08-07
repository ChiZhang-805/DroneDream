param(
    [Parameter(Mandatory = $true)]
    [string]$Application,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedApplicationSha256,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedEvidenceHead,

    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $true)]
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) {
        throw $Message
    }
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-GitText([string[]]$Arguments) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git.exe"
    $quoted = @("-C", (Quote-ProcessArgument $script:resolvedRepo))
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

function Assert-ExactChildPath(
    [string]$Path,
    [string]$Parent,
    [string]$ExpectedLeaf,
    [string]$Label
) {
    Assert-Contract ([IO.Path]::IsPathRooted($Path)) "$Label must be absolute."
    Assert-Contract ([IO.Path]::IsPathRooted($Parent)) "$Label owner must be absolute."
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

Assert-Contract $PlanOnly.IsPresent "Only -PlanOnly is permitted by this GREEN tool."
Assert-Contract ($ExpectedApplicationSha256 -cmatch '^[0-9a-f]{64}$') `
    "Expected application SHA-256 must be lowercase hexadecimal."
Assert-Contract ($ExpectedEvidenceHead -cmatch '^[0-9a-f]{40}$') `
    "Expected evidence HEAD must be an exact lowercase object ID."
Assert-Contract (Test-Path -PathType Container -LiteralPath $RepoRoot) `
    "Evidence repository does not exist."
Assert-Contract (Test-Path -PathType Leaf -LiteralPath $Application) `
    "YELLOW application does not exist."

$script:resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
$applicationPath = (Resolve-Path -LiteralPath $Application).Path
$applicationSha256 = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $applicationPath
).Hash.ToLowerInvariant()
Assert-Contract ($applicationSha256 -ceq $ExpectedApplicationSha256) `
    "YELLOW application SHA-256 changed."

$document = Get-Content -Raw -Encoding UTF8 -LiteralPath $applicationPath |
    ConvertFrom-Json
Assert-Contract ($document.kind -ceq "dronedream-field-yellow-command-binding-application") `
    "Unknown YELLOW command-binding application kind."
Assert-Contract ($document.editionId -ceq "field") "Edition must be field."

$productCommit = [string]$document.source.productCommit
Assert-Contract ($productCommit -cmatch '^[0-9a-f]{40}$') `
    "Product source must be an exact lowercase commit."
$sourceId = $productCommit.Substring(0, 7)
Assert-Contract ([string]$document.commandBinding.sourceId -ceq $sourceId) `
    "Command binding source ID does not match product source."
Assert-Contract ([int]$document.attemptOrdinal.preflight -eq 2) `
    "Preflight ordinal must be 2."
Assert-Contract ([int]$document.attemptOrdinal.buildScript -eq 1) `
    "Build ordinal must remain 1."
Assert-Contract ([int]$document.attemptOrdinal.retryMaximum -eq 0) `
    "Retry maximum must remain zero."

$suffix = [string]$document.commandBinding.pathOrdinalSuffix
Assert-Contract ($suffix -ceq "-preflight2") `
    "Unknown command-binding path ordinal."
$expectedSourceLeaf = "ddf$sourceId$suffix"
$expectedCargoLeaf = "$sourceId$suffix"
$expectedRunLeaf = "field-yellow-build-$sourceId-lightweight-installer$suffix"

$sourceRoot = Assert-ExactChildPath `
    ([string]$document.ownedPaths.sourceRoot) `
    ([string]$document.commandBinding.sourceOwner) `
    $expectedSourceLeaf `
    "sourceRoot"
$cargoTarget = Assert-ExactChildPath `
    ([string]$document.ownedPaths.cargoTarget) `
    ([string]$document.commandBinding.cargoOwner) `
    $expectedCargoLeaf `
    "cargoTarget"
$runRoot = Assert-ExactChildPath `
    ([string]$document.ownedPaths.runRoot) `
    ([string]$document.commandBinding.runOwner) `
    $expectedRunLeaf `
    "runRoot"
$outputRoot = Assert-ExactChildPath `
    ([string]$document.ownedPaths.outputRoot) `
    $runRoot `
    "artifact" `
    "outputRoot"
$preflightScript = Assert-ExactChildPath `
    ([string]$document.ownedPaths.preflightScript) `
    $runRoot `
    "preflight-approved-build.ps1" `
    "preflightScript"
$buildScript = Assert-ExactChildPath `
    ([string]$document.ownedPaths.buildScript) `
    $runRoot `
    "invoke-approved-build.ps1" `
    "buildScript"

foreach ($path in @($sourceRoot, $cargoTarget, $runRoot, $outputRoot)) {
    Assert-Contract (-not (Test-Path -LiteralPath $path)) `
        "A fresh owned path already exists: $path"
}

$resolvedProduct = Invoke-GitText @(
    "rev-parse", "--verify", "$productCommit^{commit}"
)
Assert-Contract ($resolvedProduct -ceq $productCommit) `
    "Product source is unknown or ambiguous."
$productTree = Invoke-GitText @("rev-parse", "$productCommit^{tree}")
Assert-Contract ($productTree -ceq [string]$document.source.productTree) `
    "Product source tree changed."

$head = Invoke-GitText @("rev-parse", "HEAD")
$upstream = Invoke-GitText @("rev-parse", "@{upstream}")
$status = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
Assert-Contract ($head -ceq $ExpectedEvidenceHead) `
    "Evidence HEAD does not match the frozen application command."
Assert-Contract ($upstream -ceq $ExpectedEvidenceHead) `
    "Evidence upstream does not match the frozen application command."
Assert-Contract (-not $status) "Evidence worktree is not clean."

$result = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-yellow-command-binding-plan"
    decision = "pass-plan-only"
    productSource = $productCommit
    evidenceHead = $head
    sourceId = $sourceId
    attemptOrdinal = [ordered]@{
        preflight = 2
        buildScript = 1
        retryMaximum = 0
    }
    ownedPaths = [ordered]@{
        sourceRoot = $sourceRoot
        cargoTarget = $cargoTarget
        runRoot = $runRoot
        outputRoot = $outputRoot
        preflightScript = $preflightScript
        buildScript = $buildScript
    }
    effects = [ordered]@{
        directoriesCreated = 0
        commandFilesCreated = 0
        preflightInvocations = 0
        buildInvocations = 0
        frontendInvocations = 0
        tauriInvocations = 0
        cargoInvocations = 0
        nsisInvocations = 0
    }
    generationRule = `
        "Future command files must consume these resolved paths; literal source leaves are forbidden."
}
$result | ConvertTo-Json -Depth 8
