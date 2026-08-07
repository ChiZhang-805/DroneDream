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

    [switch]$Generate
)

$ErrorActionPreference = "Stop"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
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

function Get-GitBlobBytes([string]$ObjectName) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = "git.exe"
    $startInfo.Arguments = @(
        "-C",
        (Quote-ProcessArgument $script:resolvedRepo),
        "cat-file",
        "blob",
        (Quote-ProcessArgument $ObjectName)
    ) -join " "
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    $memory = [IO.MemoryStream]::new()
    try {
        $process.StandardOutput.BaseStream.CopyTo($memory)
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "Unable to read Git blob: $($stderr.Trim())"
        }
        return $memory.ToArray()
    } finally {
        $memory.Dispose()
    }
}

function Get-BytesSha256([byte[]]$Bytes) {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha256.ComputeHash($Bytes)
    } finally {
        $sha256.Dispose()
    }
    return ([BitConverter]::ToString($digest) -replace "-", "").ToLowerInvariant()
}

function Get-Utf8Bytes([string]$Text) {
    return [Text.UTF8Encoding]::new($false).GetBytes($Text)
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

function Assert-TrackedBlobBinding(
    [string]$Commit,
    [string]$Path,
    [string]$ExpectedBlob,
    [string]$ExpectedSha256,
    [string]$Label
) {
    Assert-Contract ($Path -cmatch '^[a-zA-Z0-9_./-]+$') "$Label path is invalid."
    Assert-Contract (-not (@($Path.Split('/')) -contains '..')) "$Label path escapes."
    $blob = Invoke-GitText @("rev-parse", "$Commit`:$Path")
    Assert-Contract ($blob -ceq $ExpectedBlob) "$Label Git blob changed."
    [byte[]]$bytes = @(Get-GitBlobBytes $blob)
    Assert-Contract ((Get-BytesSha256 $bytes) -ceq $ExpectedSha256) `
        "$Label canonical SHA-256 changed."
    $headBlob = Invoke-GitText @("rev-parse", "HEAD`:$Path")
    Assert-Contract ($headBlob -ceq $ExpectedBlob) "$Label drifted in evidence HEAD."
    return $bytes
}

function Render-Template([string]$Template, [hashtable]$Tokens, [string]$Label) {
    $rendered = $Template
    foreach ($entry in $Tokens.GetEnumerator()) {
        Assert-Contract (-not $entry.Value.Contains('"')) `
            "$Label token contains an unsupported quote: $($entry.Key)"
        $rendered = $rendered.Replace("@@$($entry.Key)@@", $entry.Value)
    }
    Assert-Contract (-not ($rendered -match '@@[A-Z0-9_]+@@')) `
        "$Label contains unresolved tokens."
    Assert-Contract (-not ($rendered -match '560f574')) `
        "$Label contains the historical cargo leaf."
    $errors = $null
    $tokens = $null
    [Management.Automation.Language.Parser]::ParseInput(
        $rendered,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    Assert-Contract ($errors.Count -eq 0) "$Label does not parse as PowerShell 5.1."
    return $rendered
}

function New-FileRecord([string]$Path, [byte[]]$Bytes) {
    return [ordered]@{
        path = $Path
        bytes = $Bytes.Length
        sha256 = Get-BytesSha256 $Bytes
    }
}

function Write-NewFile([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try { $stream.Write($Bytes, 0, $Bytes.Length) } finally { $stream.Dispose() }
}

Assert-Contract ($Plan.IsPresent -xor $Generate.IsPresent) `
    "Select exactly one of -Plan or -Generate."
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
[byte[]]$applicationBytes = [IO.File]::ReadAllBytes($applicationPath)
$applicationSha256 = Get-BytesSha256 $applicationBytes
Assert-Contract ($applicationSha256 -ceq $ExpectedApplicationSha256) `
    "YELLOW application SHA-256 changed."
$document = [Text.UTF8Encoding]::new($false).GetString($applicationBytes) |
    ConvertFrom-Json
Assert-Contract ($document.kind -ceq "dronedream-field-yellow-command-files-application") `
    "Unknown YELLOW command-file application kind."
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
Assert-Contract ($suffix -ceq "-preflight2-generate1") `
    "Unknown command-file path ordinal."
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
    ([string]$document.ownedPaths.outputRoot) $runRoot "artifact" "outputRoot"
$applicationCopy = Assert-ExactChildPath `
    ([string]$document.ownedPaths.applicationCopy) $runRoot `
    "yellow-build-application.json" "applicationCopy"
$overlayPath = Assert-ExactChildPath `
    ([string]$document.ownedPaths.authorizationOverlay) $runRoot `
    "tauri-yellow-authorized.json" "authorizationOverlay"
$preflightScript = Assert-ExactChildPath `
    ([string]$document.ownedPaths.preflightScript) $runRoot `
    "preflight-approved-build.ps1" "preflightScript"
$buildScript = Assert-ExactChildPath `
    ([string]$document.ownedPaths.buildScript) $runRoot `
    "invoke-approved-build.ps1" "buildScript"
$runFilesReceiptPath = Assert-ExactChildPath `
    ([string]$document.ownedPaths.runFilesReceipt) $runRoot `
    "run-files-receipt.json" "runFilesReceipt"

foreach ($path in @($sourceRoot, $cargoTarget, $runRoot, $outputRoot)) {
    Assert-Contract (-not (Test-Path -LiteralPath $path)) `
        "A fresh owned path already exists: $path"
}
$runOwner = [IO.Path]::GetFullPath([string]$document.commandBinding.runOwner)
Assert-Contract (Test-Path -PathType Container -LiteralPath $runOwner) `
    "Run owner does not exist."
Assert-NoReparsePoint $runOwner "runOwner"

$resolvedProduct = Invoke-GitText @("rev-parse", "--verify", "$productCommit^{commit}")
Assert-Contract ($resolvedProduct -ceq $productCommit) `
    "Product source is unknown or ambiguous."
$productTree = Invoke-GitText @("rev-parse", "$productCommit^{tree}")
Assert-Contract ($productTree -ceq [string]$document.source.productTree) `
    "Product source tree changed."
$head = Invoke-GitText @("rev-parse", "HEAD")
$upstream = Invoke-GitText @("rev-parse", "@{upstream}")
$status = Invoke-GitText @("status", "--porcelain=v1", "--untracked-files=all")
Assert-Contract ($head -ceq $ExpectedEvidenceHead) `
    "Evidence HEAD does not match the frozen command."
Assert-Contract ($upstream -ceq $ExpectedEvidenceHead) `
    "Evidence upstream does not match the frozen command."
Assert-Contract (-not $status) "Evidence worktree is not clean."

$toolCommit = [string]$document.generatorBinding.sourceCommit
Assert-Contract ($toolCommit -cmatch '^[0-9a-f]{40}$') `
    "Generator source commit is invalid."
[byte[]]$generatorBytes = @(Assert-TrackedBlobBinding `
    $toolCommit `
    ([string]$document.generatorBinding.path) `
    ([string]$document.generatorBinding.gitBlob) `
    ([string]$document.generatorBinding.canonicalBlobSha256) `
    "generator")

$templateBytes = @{}
foreach ($binding in @($document.templateBindings)) {
    [byte[]]$bytes = @(Assert-TrackedBlobBinding `
        $toolCommit `
        ([string]$binding.path) `
        ([string]$binding.gitBlob) `
        ([string]$binding.canonicalBlobSha256) `
        ([string]$binding.id))
    $templateBytes[[string]$binding.id] = $bytes
}
Assert-Contract ($templateBytes.ContainsKey("preflight")) `
    "Preflight template binding is missing."
Assert-Contract ($templateBytes.ContainsKey("build")) `
    "Build template binding is missing."

$overlaySourcePath = [string]$document.overlayContract.sourcePath
$overlayBlob = Invoke-GitText @("rev-parse", "$productCommit`:$overlaySourcePath")
Assert-Contract ($overlayBlob -ceq [string]$document.overlayContract.sourceGitBlob) `
    "Tracked Field overlay source changed."
[byte[]]$overlaySourceBytes = @(Get-GitBlobBytes $overlayBlob)
Assert-Contract ((Get-BytesSha256 $overlaySourceBytes) -ceq [string]$document.overlayContract.sourceCanonicalSha256) `
    "Tracked Field overlay source SHA-256 changed."
$overlayDocument = [Text.UTF8Encoding]::new($false).GetString($overlaySourceBytes) |
    ConvertFrom-Json
Assert-Contract ($overlayDocument.build.beforeBuildCommand -ceq "npm run frontend:field-build-gated") `
    "Fail-closed Field build command changed."
$overlayDocument.build.beforeBuildCommand = "npm run frontend:field-build"
$overlayText = ($overlayDocument | ConvertTo-Json -Depth 100) + "`n"
[byte[]]$overlayBytes = @(Get-Utf8Bytes $overlayText)
$overlaySha256 = Get-BytesSha256 $overlayBytes

$tokens = @{
    SOURCE_ROOT = $sourceRoot
    RUN_ROOT = $runRoot
    OUTPUT_ROOT = $outputRoot
    CARGO_TARGET = $cargoTarget
    CARGO_LEAF = $expectedCargoLeaf
    PRODUCT_COMMIT = $productCommit
    EVIDENCE_HEAD = $ExpectedEvidenceHead
    APPLICATION_FILE_SHA256 = $applicationSha256
    APPLICATION_CANONICAL_SHA256 = [string]$document.integrity.canonicalSha256
    APPLICATION_ID = [string]$document.applicationId
    OVERLAY_SHA256 = $overlaySha256
}
$preflightTemplate = [Text.UTF8Encoding]::new($false).GetString(
    [byte[]]$templateBytes["preflight"]
)
$buildTemplate = [Text.UTF8Encoding]::new($false).GetString(
    [byte[]]$templateBytes["build"]
)
$preflightText = Render-Template $preflightTemplate $tokens "preflight"
$buildText = Render-Template $buildTemplate $tokens "build"
[byte[]]$preflightBytes = @(Get-Utf8Bytes $preflightText)
[byte[]]$buildBytes = @(Get-Utf8Bytes $buildText)

$applicationRecord = New-FileRecord $applicationCopy $applicationBytes
$overlayRecord = New-FileRecord $overlayPath $overlayBytes
$preflightRecord = New-FileRecord $preflightScript $preflightBytes
$buildRecord = New-FileRecord $buildScript $buildBytes
$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-yellow-command-files-receipt"
    decision = "generated-exclusive"
    productSource = $productCommit
    evidenceHead = $ExpectedEvidenceHead
    generator = [ordered]@{
        sourceCommit = $toolCommit
        gitBlob = [string]$document.generatorBinding.gitBlob
        canonicalBlobSha256 = [string]$document.generatorBinding.canonicalBlobSha256
    }
    attemptOrdinal = [ordered]@{
        preflight = 2
        buildScript = 1
        retryMaximum = 0
    }
    application = [ordered]@{
        sourcePath = $applicationPath
        fileSha256 = $applicationSha256
        canonicalSha256 = [string]$document.integrity.canonicalSha256
        copy = $applicationRecord
    }
    generatedFiles = [ordered]@{
        overlay = $overlayRecord
        preflight = $preflightRecord
        build = $buildRecord
    }
    ownedPaths = [ordered]@{
        sourceRoot = $sourceRoot
        cargoTarget = $cargoTarget
        runRoot = $runRoot
        outputRoot = $outputRoot
    }
    safety = [ordered]@{
        exclusiveCreate = $true
        sourceRootCreated = $false
        cargoTargetCreated = $false
        outputRootCreated = $false
        buildInvoked = $false
        validatedHardwarePackCount = 0
        hardwareDecision = "deny"
    }
}
$receiptText = ($receipt | ConvertTo-Json -Depth 20) + "`n"
[byte[]]$receiptBytes = @(Get-Utf8Bytes $receiptText)
$receiptRecord = New-FileRecord $runFilesReceiptPath $receiptBytes

if ($Generate) {
    Assert-Contract (-not (Test-Path -LiteralPath $runRoot)) `
        "Run root must be absent for exclusive generation."
    New-Item -ItemType Directory -Path $runRoot -ErrorAction Stop | Out-Null
    Assert-NoReparsePoint $runRoot "runRoot"
    Write-NewFile $applicationCopy $applicationBytes
    Write-NewFile $overlayPath $overlayBytes
    Write-NewFile $preflightScript $preflightBytes
    Write-NewFile $buildScript $buildBytes
    Write-NewFile $runFilesReceiptPath $receiptBytes
}

$modeName = if ($Plan) { "plan" } else { "generation" }
$result = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-yellow-command-files-$modeName"
    decision = if ($Plan) { "pass-plan-zero-write" } else { "generated-exclusive" }
    productSource = $productCommit
    evidenceHead = $ExpectedEvidenceHead
    application = [ordered]@{
        bytes = $applicationBytes.Length
        fileSha256 = $applicationSha256
        canonicalSha256 = [string]$document.integrity.canonicalSha256
    }
    generatedFiles = [ordered]@{
        applicationCopy = $applicationRecord
        overlay = $overlayRecord
        preflight = $preflightRecord
        build = $buildRecord
        runFilesReceipt = $receiptRecord
    }
    effects = [ordered]@{
        runRootCreated = [int]$Generate.IsPresent
        filesCreated = if ($Generate) { 5 } else { 0 }
        sourceRootCreated = 0
        cargoTargetCreated = 0
        outputRootCreated = 0
        preflightInvocations = 0
        buildInvocations = 0
        frontendInvocations = 0
        tauriInvocations = 0
        cargoInvocations = 0
        nsisInvocations = 0
    }
}
$result | ConvertTo-Json -Depth 12
