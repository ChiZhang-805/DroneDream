[CmdletBinding()]
param(
    [ValidateSet("Plan", "Preflight", "Prepare", "Execute")]
    [string]$Mode = "Plan"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProductSource = "413a83bfa097fd81523674f79c418df75e0c19c2"
$ProductTree = "d19eb977ce5e049399f7688bd6c318110784a7a3"
$SemanticFingerprint = "fa7523cb1a93b4b3626a3b9132139fea8ed7e2c165097a03545b2e58eaf68a91"
$ApplicationPath = Join-Path $PSScriptRoot "yellow-build-attempt-13-413a83b-application.v1.json"
$EvidenceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$SourceRoot = "C:\Users\zju20\dds13"
$RunRoot = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-ordinal13-413a83b"
$ReceiptRoot = Join-Path $RunRoot "receipt"
$OutputRoot = Join-Path $RunRoot "bundle"
$NpmLogsRoot = Join-Path $ReceiptRoot "npm-logs"
$CargoTargetDir = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\sim-cargo-target-413a83b-ordinal13"
$GlobalCacheRoot = "C:\Users\zju20\AppData\Local\npm-cache"
$SnapshotOwnedBase = "C:\Users\zju20\AppData\Local\DroneDream\codex-dependencies\npm-snapshots"
$SnapshotRoot = Join-Path $SnapshotOwnedBase "npm-snapshot-ordinal13-413a83b"
$DependencyOwnedBase = "C:\Users\zju20\AppData\Local\DroneDream\codex-dependencies\npm"
$DependencyBundleId = "npm-win32-x64-c9fa658219266f84"
$DependencyRoot = Join-Path $DependencyOwnedBase $DependencyBundleId
$DependencyManifest = Join-Path $DependencyRoot "manifest.json"
$SnapshotReceipt = Join-Path $ReceiptRoot "offline-cache-snapshot.json"
$PreparationCoreReceipt = Join-Path $ReceiptRoot "dependency-preparation-core.json"
$PreparationReceipt = Join-Path $ReceiptRoot "dependency-preparation-receipt.json"
$BuildReceipt = Join-Path $ReceiptRoot "yellow-build-receipt.json"
$BuildLog = Join-Path $ReceiptRoot "build-transcript.log"
$AttemptLock = Join-Path $ReceiptRoot "attempt-lock.json"
$GeneratedInstaller = Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle\nsis\DroneDream-Sim_1.0.0_x64-setup.exe"
$GeneratedSignature = "$GeneratedInstaller.sig"
$FixedArtifact = Join-Path $OutputRoot "DroneDream-Sim-1.0.0.exe"
$FixedSignature = "$FixedArtifact.sig"
$FixedChecksum = "$FixedArtifact.sha256"
$FrozenArtifact = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-20260806T120129Z-f24eb3a\bundle\DroneDream-Sim-1.0.0.exe"
$FrozenArtifactSha256 = "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece"
$UpdaterKeyPath = "C:\Users\zju20\.tauri\dronedream-updater.key"
$OAuthClientId = "0c2ad943-a0cb-4a2f-9eda-eba44b7f58df"
$DependencyContractRelative = "distribution\sim\desktop\offline-dependency-tree-contract.psm1"
$DependencyAuthorityRelative = "distribution\sim\desktop\offline-dependency-tree-authority.v1.json"
$DependencyContractSha256 = "ea9b3f7f49f9a3862d9fb45247a32ca87c82656b1992dd9666f9d982b8cdf053"
$DependencyAuthoritySha256 = "eb54da482498a4e193ea4a4d1f95c9b3936eb4fd3fe69aad8d8425de604e0a4c"
$DependencyContractGitBlob = "ae3daa3a2cf5e295f2e7c6bb2c0da7c8a0640e4b"
$DependencyAuthorityGitBlob = "704cc9951f6121a14403734274ec72cc8c979887"
$OwnedRootContractRelative = "distribution\sim\desktop\owned-build-root-contract.psm1"
$OwnedRootContractSha256 = "9745f04f4024be6a0f69b6fcd4c903e33181c80004aac61acd60e550044d3343"
$OwnedRootContractGitBlob = "44866698486c1a5ae905619ce8323cbe6fe4049c"
$LocalDroneDreamRoot = "C:\Users\zju20\AppData\Local\DroneDream"
$SourceOwnedBase = "C:\Users\zju20"
$RunOwnedBase = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2"
$CargoOwnedBase = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache"
$ExpectedDependencyFingerprint = "96f97b507d5eb15001933d6b22faa1e5e2c8289aa40dc78e4641a5095aacdb88"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-Sha256Lower {
    param([string]$LiteralPath)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Get-Sha256Text {
    param([string]$Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        ([BitConverter]::ToString($algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "").ToLowerInvariant()
    } finally { $algorithm.Dispose() }
}

function Assert-DetachedGitFileBinding {
    param(
        [string]$RepoRoot,
        [string]$RelativePath,
        [string]$ExpectedBlob
    )
    $gitPath = $RelativePath.Replace("\", "/")
    $head = (& git -C $RepoRoot rev-parse HEAD).Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $head -ceq $ProductSource) "Detached source HEAD drifted."
    $blob = (& git -C $RepoRoot rev-parse "$ProductSource`:$gitPath").Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $blob -ceq $ExpectedBlob) "Detached source Git blob drifted: $gitPath"
    Assert-True (Test-Path -LiteralPath (Join-Path $RepoRoot $RelativePath) -PathType Leaf) "Detached source file is missing: $gitPath"
    & git -C $RepoRoot diff --quiet --no-ext-diff -- $gitPath
    Assert-True ($LASTEXITCODE -eq 0) "Detached source file differs from its exact Git blob: $gitPath"
    & git -C $RepoRoot diff --cached --quiet --no-ext-diff -- $gitPath
    Assert-True ($LASTEXITCODE -eq 0) "Detached source index differs from its exact Git blob: $gitPath"
}

function Write-JsonFile {
    param([object]$Document, [string]$LiteralPath)
    $Document | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $LiteralPath -Encoding UTF8
}

function Get-ResourceSnapshot {
    $computer = Get-CimInstance Win32_OperatingSystem
    $total = [double]$computer.TotalVisibleMemorySize * 1KB
    $free = [double]$computer.FreePhysicalMemory * 1KB
    $heavy = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(cargo|rustc|tauri|makensis|px4|gazebo)$' })
    [ordered]@{
        memoryUsedPercent = [Math]::Round((1 - ($free / $total)) * 100, 1)
        memoryFreeBytes = [UInt64]$free
        cFreeBytes = [UInt64](Get-PSDrive C).Free
        zFreeBytes = [UInt64](Get-PSDrive Z).Free
        heavyProcessCount = $heavy.Count
    }
}

function Assert-EvidenceBinding {
    Assert-True (Test-Path -LiteralPath $ApplicationPath -PathType Leaf) "Application is missing."
    $application = Get-Content -LiteralPath $ApplicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$application.sourceSeparation.productSourceCommit -ceq $ProductSource) "Product source drifted."
    Assert-True ([string]$application.sourceSeparation.productSourceTree -ceq $ProductTree) "Product tree drifted."
    Assert-True ((Get-Item -LiteralPath $PSCommandPath).Length -eq [int64]$application.executionPlan.entryScript.bytes) "Entry bytes drifted."
    Assert-True ((Get-Sha256Lower $PSCommandPath) -ceq [string]$application.executionPlan.entryScript.sha256) "Entry SHA drifted."
    $head = (& git -C $EvidenceRoot rev-parse HEAD).Trim()
    $upstream = (& git -C $EvidenceRoot rev-parse '@{upstream}').Trim()
    $status = (& git -C $EvidenceRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $head -ceq $upstream -and -not $status) "Evidence worktree must be clean and upstream exact."
    Assert-True ((& git -C $EvidenceRoot rev-parse $ProductSource).Trim() -ceq $ProductSource) "Product object is unavailable."
    Assert-True ((& git -C $EvidenceRoot rev-parse "$ProductSource`^{tree}").Trim() -ceq $ProductTree) "Product tree object drifted."
    $contractPath = Join-Path $EvidenceRoot $DependencyContractRelative
    $authorityPath = Join-Path $EvidenceRoot $DependencyAuthorityRelative
    $ownedRootContractPath = Join-Path $EvidenceRoot $OwnedRootContractRelative
    Assert-True ((Get-Sha256Lower $contractPath) -ceq $DependencyContractSha256) "Dependency contract module drifted."
    Assert-True ((Get-Sha256Lower $authorityPath) -ceq $DependencyAuthoritySha256) "Dependency authority drifted."
    Assert-True ((Get-Sha256Lower $ownedRootContractPath) -ceq $OwnedRootContractSha256) "Owned root contract module drifted."
    $application
}

function Invoke-CacheTool {
    param(
        [ValidateSet("verify-global", "create-snapshot", "verify-snapshot")]
        [string]$CacheMode,
        [string]$RepoRoot,
        [string]$CacheRoot
    )
    $tool = Join-Path $RepoRoot "distribution\sim\desktop\lockfile-offline-cache.mjs"
    $arguments = @(
        $tool, "--mode", $CacheMode, "--repo-root", $RepoRoot,
        "--cache-root", $CacheRoot,
        "--expected-semantic-fingerprint", $SemanticFingerprint
    )
    if ($CacheMode -ceq "create-snapshot") {
        $arguments += @("--owned-base", $SnapshotOwnedBase, "--snapshot-root", $SnapshotRoot)
    }
    $json = (& node.exe @arguments | Out-String).Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $json) "Stable offline-cache verification failed."
    $json | ConvertFrom-Json
}

function Assert-NewRootsAbsent {
    foreach ($path in @($SourceRoot, $RunRoot, $CargoTargetDir, $SnapshotRoot, $DependencyRoot)) {
        Assert-True (-not (Test-Path -LiteralPath $path)) "A new owned root already exists: $path"
    }
}

function Import-AndAssert-OwnedBases {
    param([string]$RepoRoot)
    $modulePath = Join-Path $RepoRoot $OwnedRootContractRelative
    if ([IO.Path]::GetFullPath($RepoRoot).TrimEnd("\").Equals([IO.Path]::GetFullPath($EvidenceRoot).TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
        Assert-True ((Get-Sha256Lower $modulePath) -ceq $OwnedRootContractSha256) "Owned root contract module drifted."
    } else {
        Assert-DetachedGitFileBinding -RepoRoot $RepoRoot -RelativePath $OwnedRootContractRelative -ExpectedBlob $OwnedRootContractGitBlob
    }
    Import-Module $modulePath -Force
    Assert-CanonicalOwnedDirectory -Path $SourceOwnedBase -ExpectedPath $SourceOwnedBase -AllowedRoot $SourceOwnedBase | Out-Null
    Assert-CanonicalOwnedDirectory -Path $RunOwnedBase -ExpectedPath $RunOwnedBase -AllowedRoot $LocalDroneDreamRoot | Out-Null
    Assert-CanonicalOwnedDirectory -Path $SnapshotOwnedBase -ExpectedPath $SnapshotOwnedBase -AllowedRoot $LocalDroneDreamRoot | Out-Null
    Assert-CanonicalOwnedDirectory -Path $DependencyOwnedBase -ExpectedPath $DependencyOwnedBase -AllowedRoot $LocalDroneDreamRoot | Out-Null
    Assert-CanonicalOwnedDirectory -Path $CargoOwnedBase -ExpectedPath $CargoOwnedBase -AllowedRoot $LocalDroneDreamRoot | Out-Null
}

function Invoke-ReadOnlyPreflight {
    Assert-EvidenceBinding | Out-Null
    Assert-NewRootsAbsent
    Import-AndAssert-OwnedBases $EvidenceRoot
    $cache = Invoke-CacheTool -CacheMode verify-global -RepoRoot $EvidenceRoot -CacheRoot $GlobalCacheRoot
    Assert-True ([int]$cache.contentObjectCount -eq 323 -and [int]$cache.indexKeyCount -eq 323) "Required cache selection count drifted."
    Assert-True (Test-Path -LiteralPath $FrozenArtifact -PathType Leaf) "Frozen historical artifact is missing."
    Assert-True ((Get-Sha256Lower $FrozenArtifact) -ceq $FrozenArtifactSha256) "Frozen historical artifact drifted."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$env:VITE_SUPABASE_URL)) "Public Supabase URL is not injected."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$env:VITE_SUPABASE_PUBLISHABLE_KEY)) "Public Supabase key is not injected."
    Assert-True (Test-Path -LiteralPath $UpdaterKeyPath -PathType Leaf) "Approved updater key path is unavailable."
    $resources = Get-ResourceSnapshot
    Assert-True ($resources.memoryUsedPercent -lt 80) "Memory use is at or above 80 percent."
    Assert-True ($resources.memoryFreeBytes -ge 3GB) "Free memory is below 3 GiB."
    Assert-True ($resources.cFreeBytes -ge 20GB) "C free space is below 20 GiB."
    Assert-True ($resources.zFreeBytes -ge 15GB) "Z free space is below 15 GiB."
    Assert-True ($resources.heavyProcessCount -eq 0) "A heavy build or simulator process is running."
    [ordered]@{ cache = $cache; resources = $resources }
}

function New-DependencyManifest {
    param([object]$Inventory, [string]$PreparationSha, [string]$SnapshotSha)
    [ordered]@{
        schemaVersion = 1; kind = "dronedream-desktop-node-dependency-bundle"; bundleVersion = "1.0.0"
        bundleId = $DependencyBundleId; state = "attested-offline"; editionScope = @("universal", "sim", "lab", "field")
        productSource = [ordered]@{ commit = $ProductSource; tree = $ProductTree }
        ownedBase = $DependencyOwnedBase.Replace("\", "/"); dependencyRoot = $DependencyRoot.Replace("\", "/")
        sourceInputs = @(
            [ordered]@{ sourcePath = "desktop/package.json"; bundlePath = "desktop/package.json"; sha256 = "ba37f6edb95c454ea0f83130b98f708c0f27990133c705c8c23597ac96fd36b6" },
            [ordered]@{ sourcePath = "desktop/package-lock.json"; bundlePath = "desktop/package-lock.json"; sha256 = "1138f300f140dfcaf22a6c47d44f676e9ea9294b77a2caabb7fa08ef8340d058" },
            [ordered]@{ sourcePath = "frontend/package.json"; bundlePath = "frontend/package.json"; sha256 = "cd905e33a1faad2c22b165ba407e16c05d01fbdab1738dd156d616cfee4daf05" },
            [ordered]@{ sourcePath = "frontend/package-lock.json"; bundlePath = "frontend/package-lock.json"; sha256 = "27b8f36c53be1a02eecbd99801033639662a4697c42ad1141d276c78adbc664a" }
        )
        toolchain = [ordered]@{
            operatingSystem = "windows"; architecture = "x64"; nodeVersion = "v24.14.1"; npmVersion = "11.11.0"
            tauriCli = [ordered]@{ version = "2.11.4"; packageJsonPath = "desktop/node_modules/@tauri-apps/cli/package.json"; packageJsonSha256 = "2211ba5e468d2ac8c70d9d5f0b2f017a98e9d2b2932ad47fc3588fc14e103a33"; entrypointPath = "desktop/node_modules/@tauri-apps/cli/tauri.js"; entrypointSha256 = "0dd6ec63c7c63a993fde20955e291d833c03f3760e63e0ee21e83482f6c0b43a" }
            platformCli = [ordered]@{ packageName = "@tauri-apps/cli-win32-x64-msvc"; version = "2.11.4"; packageJsonPath = "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/package.json"; packageJsonSha256 = "9b7ff3368f454c5cc630270556faf181ef9e126a56cef788285470cc98d178f0"; binaryPath = "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/cli.win32-x64-msvc.node"; binarySha256 = "37c4d79256120893f2c12c1385bce5f7510b5063afdeb09b40a9effec28d0208" }
            vite = [ordered]@{ version = "7.3.6"; packageJsonPath = "frontend/node_modules/vite/package.json"; packageJsonSha256 = "e5ed0f85215f871fe22a48987dcd77fcfbe14064a53c0c9f7f48186a6b7e2cf0" }
        }
        mounts = @(
            [ordered]@{ linkPath = "desktop/node_modules"; targetPath = "desktop/node_modules"; linkType = "junction" },
            [ordered]@{ linkPath = "frontend/node_modules"; targetPath = "frontend/node_modules"; linkType = "junction" }
        )
        inventory = [ordered]@{ algorithm = "sha256-lines-v1"; excludedPaths = @("manifest.json"); entries = @($Inventory.entries); treeFingerprint = $Inventory.treeFingerprint }
        policies = [ordered]@{ networkAllowed = $false; systemTauriAllowed = $false; arbitraryPathInjectionAllowed = $false; dependencyMutationAllowed = $false; dependencyPayloadAllowed = $false; preparationAuthorizedSeparately = $true }
        attestation = [ordered]@{ createdAt = [DateTime]::UtcNow.ToString("o"); preparationReceiptSha256 = $PreparationSha; offlineCacheSha256 = $SnapshotSha; lifecycleScriptsAudited = $true }
    }
}

function Invoke-Prepare {
    Assert-EvidenceBinding | Out-Null
    Assert-NewRootsAbsent
    Import-AndAssert-OwnedBases $EvidenceRoot
    New-ExclusiveAttemptDirectory -Path $RunRoot -CanonicalParent $RunOwnedBase -AllowedRoot $LocalDroneDreamRoot | Out-Null
    New-ExclusiveAttemptDirectory -Path $ReceiptRoot -CanonicalParent $RunRoot -AllowedRoot $LocalDroneDreamRoot | Out-Null
    New-ExclusiveAttemptDirectory -Path $NpmLogsRoot -CanonicalParent $ReceiptRoot -AllowedRoot $LocalDroneDreamRoot | Out-Null
    Write-JsonFile ([ordered]@{ globalApplicationOrdinal = 13; preparationOrdinal = 1; buildOrdinal = 1; retry = 0 }) $AttemptLock
    & git -c core.longpaths=true -C $EvidenceRoot worktree add --detach $SourceRoot $ProductSource
    Assert-True ($LASTEXITCODE -eq 0) "Detached source creation failed."
    Assert-True ((& git -C $SourceRoot rev-parse HEAD).Trim() -ceq $ProductSource) "Detached source HEAD drifted."
    Assert-True ((& git -C $SourceRoot rev-parse 'HEAD^{tree}').Trim() -ceq $ProductTree) "Detached source tree drifted."
    $sourceContractPath = Join-Path $SourceRoot $DependencyContractRelative
    $sourceAuthorityPath = Join-Path $SourceRoot $DependencyAuthorityRelative
    $sourceOwnedRootContractPath = Join-Path $SourceRoot $OwnedRootContractRelative
    Assert-DetachedGitFileBinding -RepoRoot $SourceRoot -RelativePath $DependencyContractRelative -ExpectedBlob $DependencyContractGitBlob
    Assert-DetachedGitFileBinding -RepoRoot $SourceRoot -RelativePath $DependencyAuthorityRelative -ExpectedBlob $DependencyAuthorityGitBlob
    Assert-DetachedGitFileBinding -RepoRoot $SourceRoot -RelativePath $OwnedRootContractRelative -ExpectedBlob $OwnedRootContractGitBlob
    $snapshot = Invoke-CacheTool -CacheMode create-snapshot -RepoRoot $SourceRoot -CacheRoot $GlobalCacheRoot
    Write-JsonFile $snapshot $SnapshotReceipt
    $snapshotSha = [string]$snapshot.snapshot.fingerprint
    New-ExclusiveAttemptDirectory -Path $DependencyRoot -CanonicalParent $DependencyOwnedBase -AllowedRoot $LocalDroneDreamRoot | Out-Null
    foreach ($workspace in @("desktop", "frontend")) {
        $target = Join-Path $DependencyRoot $workspace
        New-ExclusiveAttemptDirectory -Path $target -CanonicalParent $DependencyRoot -AllowedRoot $LocalDroneDreamRoot | Out-Null
        Copy-Item -LiteralPath (Join-Path $SourceRoot "$workspace\package.json") -Destination $target
        Copy-Item -LiteralPath (Join-Path $SourceRoot "$workspace\package-lock.json") -Destination $target
    }
    $env:npm_config_offline = "true"; $env:npm_config_cache = $SnapshotRoot
    $env:npm_config_logs_dir = $NpmLogsRoot; $env:npm_config_audit = "false"
    $env:npm_config_fund = "false"; $env:npm_config_update_notifier = "false"
    & npm.cmd --prefix (Join-Path $DependencyRoot "desktop") ci --offline --no-audit --no-fund
    Assert-True ($LASTEXITCODE -eq 0) "Desktop offline npm ci failed."
    & npm.cmd --prefix (Join-Path $DependencyRoot "frontend") ci --offline --no-audit --no-fund
    Assert-True ($LASTEXITCODE -eq 0) "Frontend offline npm ci failed."
    $snapshotAfter = Invoke-CacheTool -CacheMode verify-snapshot -RepoRoot $SourceRoot -CacheRoot $SnapshotRoot
    Assert-True ([string]$snapshotAfter.snapshot.fingerprint -ceq $snapshotSha) "Attempt-owned cache snapshot mutated during npm ci."
    Import-Module $sourceContractPath -Force
    $authority = Get-Content -LiteralPath $sourceAuthorityPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $inventory = Get-OfflineDependencyInventory $DependencyRoot
    Assert-CleanOfflineDependencyTree -Inventory $inventory `
        -ExpectedTreeFingerprint $ExpectedDependencyFingerprint `
        -ExpectedEntryCount ([int]$authority.authoritativeInventory.entryCount) `
        -ExpectedFileCount ([int]$authority.authoritativeInventory.fileCount) `
        -ExpectedDirectoryCount ([int]$authority.authoritativeInventory.directoryCount) `
        -ExpectedTotalFileBytes ([UInt64]$authority.authoritativeInventory.totalFileBytes) | Out-Null
    $core = [ordered]@{ productSource = $ProductSource; semanticFingerprint = $SemanticFingerprint; snapshotFingerprint = $snapshotSha; dependencyFingerprint = $inventory.treeFingerprint; npmCiInvocations = 2; networkInvocations = 0; retry = 0 }
    Write-JsonFile $core $PreparationCoreReceipt
    $coreSha = Get-Sha256Lower $PreparationCoreReceipt
    Write-JsonFile (New-DependencyManifest $inventory $coreSha $snapshotSha) $DependencyManifest
    & (Join-Path $SourceRoot "desktop\scripts\verify-detached-node-dependencies.ps1") -ManifestPath $DependencyManifest -RepoRoot $SourceRoot -EditionId sim -ExpectedSourceCommit $ProductSource -ExpectedSourceTree $ProductTree -FrontendDistPath (Join-Path $SourceRoot "frontend\dist") -InstallerBundlePath (Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle") -ContractOnly | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) "Prepared dependency manifest contract failed."
    Write-JsonFile ([ordered]@{ state = "prepared-attested-awaiting-execute"; snapshotReceiptSha256 = Get-Sha256Lower $SnapshotReceipt; snapshotFingerprint = $snapshotSha; preparationCoreSha256 = $coreSha; manifestSha256 = Get-Sha256Lower $DependencyManifest; dependencyFingerprint = $inventory.treeFingerprint; buildInvocations = 0; retry = 0 }) $PreparationReceipt
    Get-Content -LiteralPath $PreparationReceipt -Raw -Encoding UTF8
}

function Remove-ExactJunction {
    param([string]$LinkPath, [string]$ExpectedTarget)
    if (-not (Test-Path -LiteralPath $LinkPath)) { return }
    $item = Get-Item -LiteralPath $LinkPath -Force
    Assert-True ([bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) "Cleanup refused a non-junction path."
    $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $LinkPath).Path).TrimEnd("\")
    Assert-True ($resolved.Equals([IO.Path]::GetFullPath($ExpectedTarget).TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) "Cleanup refused a junction target mismatch."
    [IO.Directory]::Delete($item.FullName, $false)
}

function Invoke-Execute {
    Assert-EvidenceBinding | Out-Null
    Assert-True (Test-Path -LiteralPath $PreparationReceipt -PathType Leaf) "Preparation receipt is missing."
    Assert-True (Test-Path -LiteralPath $DependencyManifest -PathType Leaf) "Dependency manifest is missing."
    Assert-True (-not (Test-Path -LiteralPath $CargoTargetDir)) "Cargo target already exists."
    Assert-True (-not (Test-Path -LiteralPath $OutputRoot)) "Output root already exists."
    $preparation = Get-Content -LiteralPath $PreparationReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
    $snapshotBefore = Invoke-CacheTool -CacheMode verify-snapshot -RepoRoot $SourceRoot -CacheRoot $SnapshotRoot
    Assert-True ([string]$snapshotBefore.snapshot.fingerprint -ceq [string]$preparation.snapshotFingerprint) "Snapshot receipt binding drifted."
    $desktopLink = Join-Path $SourceRoot "desktop\node_modules"
    $frontendLink = Join-Path $SourceRoot "frontend\node_modules"
    Assert-True (-not (Test-Path $desktopLink) -and -not (Test-Path $frontendLink)) "A dependency junction already exists."
    Import-AndAssert-OwnedBases $SourceRoot
    New-ExclusiveAttemptDirectory -Path $OutputRoot -CanonicalParent $RunRoot -AllowedRoot $LocalDroneDreamRoot | Out-Null
    $transcriptStarted = $false
    try {
        New-Item -ItemType Junction -Path $desktopLink -Target (Join-Path $DependencyRoot "desktop\node_modules") | Out-Null
        New-Item -ItemType Junction -Path $frontendLink -Target (Join-Path $DependencyRoot "frontend\node_modules") | Out-Null
        & (Join-Path $SourceRoot "desktop\scripts\verify-detached-node-dependencies.ps1") -ManifestPath $DependencyManifest -RepoRoot $SourceRoot -EditionId sim -ExpectedSourceCommit $ProductSource -ExpectedSourceTree $ProductTree -FrontendDistPath (Join-Path $SourceRoot "frontend\dist") -InstallerBundlePath (Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle") | Out-Null
        Assert-True ($LASTEXITCODE -eq 0) "Live dependency mount verification failed."
        $env:npm_config_offline = "true"; $env:npm_config_cache = $SnapshotRoot; $env:npm_config_logs_dir = $NpmLogsRoot
        $env:npm_config_audit = "false"; $env:npm_config_fund = "false"; $env:npm_config_update_notifier = "false"
        $env:DRONEDREAM_DESKTOP_EDITION_ID = "sim"; $env:DRONEDREAM_EDITION_PROFILE = "sim-only"
        $env:VITE_DRONEDREAM_EDITION = "sim"; $env:CARGO_BUILD_JOBS = "2"; $env:CARGO_TARGET_DIR = $CargoTargetDir
        $env:DRONEDREAM_OAUTH_CLIENT_ID = $OAuthClientId; $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $UpdaterKeyPath
        $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
        Start-Transcript -LiteralPath $BuildLog -Force | Out-Null; $transcriptStarted = $true
        & (Join-Path $SourceRoot "desktop\scripts\build-windows-llvm.ps1") -AdditionalConfigPath (Join-Path $SourceRoot "distribution\sim\desktop\tauri.sim.conf.json") -CargoTargetDir $CargoTargetDir -DetachedNodeDependencyManifest $DependencyManifest -ExpectedProductName "DroneDream-Sim" -EditionId sim -PreserveBundleHistory
        Assert-True ($LASTEXITCODE -eq 0) "Single build invocation failed."
        Assert-True (Test-Path -LiteralPath $GeneratedInstaller -PathType Leaf) "Generated installer is missing."
        Assert-True (Test-Path -LiteralPath $GeneratedSignature -PathType Leaf) "Generated signature is missing."
        $snapshotAfter = Invoke-CacheTool -CacheMode verify-snapshot -RepoRoot $SourceRoot -CacheRoot $SnapshotRoot
        Assert-True ([string]$snapshotAfter.snapshot.fingerprint -ceq [string]$preparation.snapshotFingerprint) "Snapshot mutated during build."
        Copy-Item -LiteralPath $GeneratedInstaller -Destination $FixedArtifact
        Copy-Item -LiteralPath $GeneratedSignature -Destination $FixedSignature
        $artifactSha = Get-Sha256Lower $FixedArtifact
        "$artifactSha  DroneDream-Sim-1.0.0.exe" | Set-Content -LiteralPath $FixedChecksum -Encoding ASCII
        Write-JsonFile ([ordered]@{ state = "built-frozen-awaiting-static-acceptance"; productSource = $ProductSource; snapshotFingerprint = [string]$preparation.snapshotFingerprint; dependencyFingerprint = $ExpectedDependencyFingerprint; artifactPath = $FixedArtifact; artifactBytes = (Get-Item $FixedArtifact).Length; artifactSha256 = $artifactSha; buildInvocations = 1; retry = 0 }) $BuildReceipt
        Get-Content -LiteralPath $BuildReceipt -Raw -Encoding UTF8
    } finally {
        if ($transcriptStarted) { Stop-Transcript | Out-Null }
        Remove-ExactJunction $desktopLink (Join-Path $DependencyRoot "desktop\node_modules")
        Remove-ExactJunction $frontendLink (Join-Path $DependencyRoot "frontend\node_modules")
        Assert-True ((Get-Sha256Lower $FrozenArtifact) -ceq $FrozenArtifactSha256) "Historical artifact changed."
    }
}

if ($Mode -ceq "Plan") {
    [ordered]@{
        state = "green-plan-only-no-mutation"; productSource = $ProductSource; productTree = $ProductTree
        semanticFingerprint = $SemanticFingerprint; requiredContentObjects = 323; requiredIndexKeys = 323
        sourceRootAbsent = -not (Test-Path $SourceRoot); runRootAbsent = -not (Test-Path $RunRoot)
        cargoRootAbsent = -not (Test-Path $CargoTargetDir); snapshotRootAbsent = -not (Test-Path $SnapshotRoot)
        dependencyRootAbsent = -not (Test-Path $DependencyRoot); preflights = 0; snapshotsCreated = 0
        npmCiInvocations = 0; junctionsCreated = 0; buildInvocations = 0
    } | ConvertTo-Json -Depth 5
} elseif ($Mode -ceq "Preflight") {
    $result = Invoke-ReadOnlyPreflight
    [ordered]@{ state = "preflight-passed-no-mutation"; semanticFingerprint = $result.cache.semanticFingerprint; resources = $result.resources } | ConvertTo-Json -Depth 6
} elseif ($Mode -ceq "Prepare") {
    Invoke-Prepare
} else {
    Invoke-Execute
}
