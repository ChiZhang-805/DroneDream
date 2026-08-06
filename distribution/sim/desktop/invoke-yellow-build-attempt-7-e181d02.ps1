[CmdletBinding()]
param(
    [ValidateSet("Plan", "Preflight", "Prepare", "Execute")]
    [string]$Mode = "Plan"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProductSource = "e181d029278e50788afe8460ec0cafd9c78a6623"
$ProductTree = "bd864336aeb7ecfc3e5f9aa30c779840a4c2cf04"
$ApplicationName = "yellow-build-attempt-7-e181d02-application.v1.json"
$EvidenceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$ApplicationPath = Join-Path $PSScriptRoot $ApplicationName
$SourceRoot = "C:\Users\zju20\dds7"
$RunRoot = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-ordinal7-e181d02"
$ReceiptRoot = Join-Path $RunRoot "receipt"
$OutputRoot = Join-Path $RunRoot "bundle"
$CargoTargetDir = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\sim-cargo-target-e181d02-ordinal7"
$DependencyOwnedBase = "C:\Users\zju20\AppData\Local\DroneDream\codex-dependencies\npm"
$DependencyBundleId = "npm-win32-x64-f6cd1f826b44b604"
$DependencyRoot = Join-Path $DependencyOwnedBase $DependencyBundleId
$DependencyManifest = Join-Path $DependencyRoot "manifest.json"
$NpmCacheRoot = "C:\Users\zju20\AppData\Local\npm-cache"
$ExpectedNpmCacheFingerprint = "ddd06a60a0345bf03c6f045efa6a7641f316229e0f1186979fc15a0f3b47480d"
$ExpectedDependencyFingerprint = "7f4dc4d394ca98a8458f84f7cc5dfe40603f9fe662e1610d910651d04fbe6aea"
$ExpectedDependencyEntries = 18851
$ExpectedDependencyFiles = 17339
$ExpectedDependencyBytes = [UInt64]263384543
$GeneratedInstaller = Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle\nsis\DroneDream-Sim_1.0.0_x64-setup.exe"
$GeneratedSignature = "$GeneratedInstaller.sig"
$FixedArtifact = Join-Path $OutputRoot "DroneDream-Sim-1.0.0.exe"
$FixedSignature = "$FixedArtifact.sig"
$FixedChecksum = "$FixedArtifact.sha256"
$BuildReceipt = Join-Path $ReceiptRoot "yellow-build-receipt.json"
$PreparationCoreReceipt = Join-Path $ReceiptRoot "dependency-preparation-core.json"
$PreparationReceipt = Join-Path $ReceiptRoot "dependency-preparation-receipt.json"
$AttemptLock = Join-Path $ReceiptRoot "attempt-lock.json"
$BuildLog = Join-Path $ReceiptRoot "build-transcript.log"
$FrozenArtifact = "C:\Users\zju20\AppData\Local\DroneDream\codex-sandboxes\software-sim\yellow-2\sim-y2-20260806T120129Z-f24eb3a\bundle\DroneDream-Sim-1.0.0.exe"
$FrozenArtifactSha256 = "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece"
$UpdaterKeyPath = "C:\Users\zju20\.tauri\dronedream-updater.key"
$OAuthClientId = "0c2ad943-a0cb-4a2f-9eda-eba44b7f58df"

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
    } finally {
        $algorithm.Dispose()
    }
}

function Write-JsonFile {
    param([object]$Document, [string]$LiteralPath)
    $Document | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $LiteralPath -Encoding UTF8
}

function Get-FileTreeFingerprint {
    param([string]$Root)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd("\")
    $lines = [Collections.Generic.List[string]]::new()
    [UInt64]$bytes = 0
    $files = @(Get-ChildItem -LiteralPath $rootFull -Recurse -File -Force | Sort-Object FullName)
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($rootFull.Length + 1).Replace("\", "/")
        $hash = Get-Sha256Lower -LiteralPath $file.FullName
        $lines.Add("$relative`t$($file.Length)`t$hash")
        $bytes += [UInt64]$file.Length
    }
    [ordered]@{
        algorithm = "sha256-file-lines-v1"
        fileCount = $files.Count
        totalBytes = $bytes
        fingerprint = Get-Sha256Text -Text ($lines -join "`n")
    }
}

function Get-DependencyInventory {
    param([string]$Root)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd("\")
    $entries = [Collections.Generic.List[object]]::new()
    foreach ($item in @(Get-ChildItem -LiteralPath $rootFull -Recurse -Force | Sort-Object FullName)) {
        $relative = $item.FullName.Substring($rootFull.Length + 1).Replace("\", "/")
        if ($relative -ceq "manifest.json") { continue }
        $isReparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
        $type = if ($isReparse) { "reparse" } elseif ($item.PSIsContainer) { "directory" } else { "file" }
        $entries.Add([ordered]@{
            path = $relative
            type = $type
            bytes = if ($type -ceq "file") { [UInt64]$item.Length } else { 0 }
            sha256 = if ($type -ceq "file") { Get-Sha256Lower -LiteralPath $item.FullName } else { $null }
            target = if ($isReparse) { [string]$item.Target } else { $null }
        })
    }
    $lines = @($entries | ForEach-Object {
        $sha = if ($null -eq $_.sha256) { "" } else { [string]$_.sha256 }
        $target = if ($null -eq $_.target) { "" } else { [string]$_.target }
        "$($_.path)`t$($_.type)`t$($_.bytes)`t$sha`t$target"
    })
    [ordered]@{
        entries = @($entries)
        treeFingerprint = Get-Sha256Text -Text ($lines -join "`n")
        fileCount = @($entries | Where-Object type -ceq "file").Count
        totalFileBytes = [UInt64](($entries | Where-Object type -ceq "file" | Measure-Object bytes -Sum).Sum)
    }
}

function Get-ResourceSnapshot {
    $computer = Get-CimInstance Win32_OperatingSystem
    $totalBytes = [double]$computer.TotalVisibleMemorySize * 1KB
    $freeBytes = [double]$computer.FreePhysicalMemory * 1KB
    $heavy = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(cargo|rustc|tauri|makensis|px4|gazebo)$' })
    [ordered]@{
        memoryUsedPercent = [Math]::Round((1 - ($freeBytes / $totalBytes)) * 100, 1)
        memoryFreeBytes = [UInt64]$freeBytes
        cFreeBytes = [UInt64](Get-PSDrive -Name C).Free
        zFreeBytes = [UInt64](Get-PSDrive -Name Z).Free
        heavyProcessCount = $heavy.Count
    }
}

function Assert-EvidenceAndApplication {
    Assert-True (Test-Path -LiteralPath $ApplicationPath -PathType Leaf) "Application is missing."
    $application = Get-Content -LiteralPath $ApplicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ([string]$application.sourceSeparation.productSourceCommit -ceq $ProductSource) "Product commit drifted."
    Assert-True ([string]$application.sourceSeparation.productSourceTree -ceq $ProductTree) "Product tree drifted."
    Assert-True ((Get-Item -LiteralPath $PSCommandPath).Length -eq [int64]$application.executionPlan.entryScript.bytes) "Entry bytes drifted."
    Assert-True ((Get-Sha256Lower -LiteralPath $PSCommandPath) -ceq [string]$application.executionPlan.entryScript.sha256) "Entry hash drifted."
    $head = (& git -C $EvidenceRoot rev-parse HEAD).Trim()
    $upstream = (& git -C $EvidenceRoot rev-parse '@{upstream}').Trim()
    $status = (& git -C $EvidenceRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
    Assert-True ($LASTEXITCODE -eq 0 -and $head -ceq $upstream -and -not $status) "Evidence branch must be clean and upstream exact."
    Assert-True ((& git -C $EvidenceRoot rev-parse $ProductSource).Trim() -ceq $ProductSource) "Product object is unavailable."
    Assert-True ((& git -C $EvidenceRoot rev-parse "$ProductSource`^{tree}").Trim() -ceq $ProductTree) "Product tree object drifted."
    return $application
}

function Assert-Preflight {
    $application = Assert-EvidenceAndApplication
    foreach ($path in @($SourceRoot, $RunRoot, $CargoTargetDir, $DependencyRoot)) {
        Assert-True (-not (Test-Path -LiteralPath $path)) "A new owned root already exists: $path"
    }
    Assert-True (Test-Path -LiteralPath $NpmCacheRoot -PathType Container) "The exact offline npm cache is missing."
    $cache = Get-FileTreeFingerprint -Root $NpmCacheRoot
    Assert-True ($cache.fingerprint -ceq $ExpectedNpmCacheFingerprint) "The offline npm cache fingerprint drifted."
    Assert-True (Test-Path -LiteralPath $FrozenArtifact -PathType Leaf) "The frozen historical artifact is missing."
    Assert-True ((Get-Sha256Lower -LiteralPath $FrozenArtifact) -ceq $FrozenArtifactSha256) "The frozen historical artifact drifted."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$env:VITE_SUPABASE_URL)) "Public Supabase URL is not injected."
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$env:VITE_SUPABASE_PUBLISHABLE_KEY)) "Public Supabase key is not injected."
    Assert-True (Test-Path -LiteralPath $UpdaterKeyPath -PathType Leaf) "The approved updater key path is unavailable."
    $resources = Get-ResourceSnapshot
    Assert-True ($resources.memoryUsedPercent -lt 80) "Memory use is at or above 80 percent."
    Assert-True ($resources.memoryFreeBytes -ge 3GB) "Free memory is below 3 GiB."
    Assert-True ($resources.cFreeBytes -ge 20GB) "C free space is below 20 GiB."
    Assert-True ($resources.zFreeBytes -ge 15GB) "Z free space is below 15 GiB."
    Assert-True ($resources.heavyProcessCount -eq 0) "A heavy build or simulator process is running."
    [ordered]@{ application = $application; cache = $cache; resources = $resources }
}

function New-DependencyManifest {
    param([object]$Inventory, [string]$PreparationReceiptSha256)
    [ordered]@{
        schemaVersion = 1
        kind = "dronedream-desktop-node-dependency-bundle"
        bundleVersion = "1.0.0"
        bundleId = $DependencyBundleId
        state = "attested-offline"
        editionScope = @("universal", "sim", "lab", "field")
        productSource = [ordered]@{ commit = $ProductSource; tree = $ProductTree }
        ownedBase = $DependencyOwnedBase.Replace("\", "/")
        dependencyRoot = $DependencyRoot.Replace("\", "/")
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
        attestation = [ordered]@{ createdAt = [DateTime]::UtcNow.ToString("o"); preparationReceiptSha256 = $PreparationReceiptSha256; offlineCacheSha256 = $ExpectedNpmCacheFingerprint; lifecycleScriptsAudited = $true }
    }
}

function Invoke-Prepare {
    $preflight = Assert-Preflight
    New-Item -ItemType Directory -Path $RunRoot, $ReceiptRoot, $DependencyOwnedBase, $DependencyRoot | Out-Null
    Write-JsonFile ([ordered]@{ globalApplicationOrdinal = 7; dependencyPreparationOrdinal = 1; maximum = 1; retry = 0; createdAt = [DateTime]::UtcNow.ToString("o") }) -LiteralPath $AttemptLock
    & git -c core.longpaths=true -C $EvidenceRoot worktree add --detach $SourceRoot $ProductSource
    Assert-True ($LASTEXITCODE -eq 0) "Detached source creation failed."
    Assert-True ((& git -C $SourceRoot rev-parse HEAD).Trim() -ceq $ProductSource) "Detached source HEAD drifted."
    Assert-True ((& git -C $SourceRoot rev-parse 'HEAD^{tree}').Trim() -ceq $ProductTree) "Detached source tree drifted."
    foreach ($name in @("desktop", "frontend")) {
        New-Item -ItemType Directory -Path (Join-Path $DependencyRoot $name) | Out-Null
        Copy-Item -LiteralPath (Join-Path $SourceRoot "$name\package.json") -Destination (Join-Path $DependencyRoot "$name\package.json")
        Copy-Item -LiteralPath (Join-Path $SourceRoot "$name\package-lock.json") -Destination (Join-Path $DependencyRoot "$name\package-lock.json")
    }
    $env:npm_config_offline = "true"
    $env:npm_config_cache = $NpmCacheRoot
    $env:npm_config_audit = "false"
    $env:npm_config_fund = "false"
    $env:npm_config_update_notifier = "false"
    & npm.cmd --prefix (Join-Path $DependencyRoot "desktop") ci --offline --no-audit --no-fund
    Assert-True ($LASTEXITCODE -eq 0) "Desktop offline npm ci failed."
    & npm.cmd --prefix (Join-Path $DependencyRoot "frontend") ci --offline --no-audit --no-fund
    Assert-True ($LASTEXITCODE -eq 0) "Frontend offline npm ci failed."
    $inventory = Get-DependencyInventory -Root $DependencyRoot
    Assert-True ($inventory.treeFingerprint -ceq $ExpectedDependencyFingerprint) "Prepared dependency tree fingerprint drifted."
    Assert-True ($inventory.entries.Count -eq $ExpectedDependencyEntries) "Prepared dependency entry count drifted."
    Assert-True ($inventory.fileCount -eq $ExpectedDependencyFiles) "Prepared dependency file count drifted."
    Assert-True ($inventory.totalFileBytes -eq $ExpectedDependencyBytes) "Prepared dependency byte count drifted."
    $core = [ordered]@{ productSourceCommit = $ProductSource; productSourceTree = $ProductTree; bundleId = $DependencyBundleId; cacheFingerprint = $preflight.cache.fingerprint; treeFingerprint = $inventory.treeFingerprint; entryCount = $inventory.entries.Count; fileCount = $inventory.fileCount; totalFileBytes = $inventory.totalFileBytes; npmCiInvocations = 2; networkAllowed = $false; retry = 0 }
    Write-JsonFile $core -LiteralPath $PreparationCoreReceipt
    $coreSha = Get-Sha256Lower -LiteralPath $PreparationCoreReceipt
    Write-JsonFile (New-DependencyManifest -Inventory $inventory -PreparationReceiptSha256 $coreSha) -LiteralPath $DependencyManifest
    & (Join-Path $SourceRoot "desktop\scripts\verify-detached-node-dependencies.ps1") -ManifestPath $DependencyManifest -RepoRoot $SourceRoot -EditionId sim -ExpectedSourceCommit $ProductSource -ExpectedSourceTree $ProductTree -FrontendDistPath (Join-Path $SourceRoot "frontend\dist") -InstallerBundlePath (Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle") -ContractOnly | Out-Null
    Assert-True ($LASTEXITCODE -eq 0) "Prepared dependency manifest contract failed."
    $cacheAfter = Get-FileTreeFingerprint -Root $NpmCacheRoot
    Assert-True ($cacheAfter.fingerprint -ceq $ExpectedNpmCacheFingerprint) "Offline cache mutated during preparation."
    Write-JsonFile ([ordered]@{ state = "prepared-attested-awaiting-separate-build-authorization"; coreReceiptSha256 = $coreSha; manifestSha256 = Get-Sha256Lower -LiteralPath $DependencyManifest; dependencyTreeFingerprint = $inventory.treeFingerprint; sourceRoot = $SourceRoot; dependencyRoot = $DependencyRoot; junctionsCreated = 0; buildInvocations = 0; retry = 0 }) -LiteralPath $PreparationReceipt
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
    Assert-EvidenceAndApplication | Out-Null
    Assert-True (Test-Path -LiteralPath $PreparationReceipt -PathType Leaf) "Frozen dependency preparation receipt is missing."
    Assert-True (Test-Path -LiteralPath $DependencyManifest -PathType Leaf) "Attested dependency manifest is missing."
    Assert-True (Test-Path -LiteralPath $SourceRoot -PathType Container) "Prepared detached source is missing."
    Assert-True (-not (Test-Path -LiteralPath $CargoTargetDir)) "Cargo target already exists."
    Assert-True (-not (Test-Path -LiteralPath $OutputRoot)) "Output root already exists."
    $desktopLink = Join-Path $SourceRoot "desktop\node_modules"
    $frontendLink = Join-Path $SourceRoot "frontend\node_modules"
    Assert-True (-not (Test-Path -LiteralPath $desktopLink)) "Desktop node_modules mount already exists."
    Assert-True (-not (Test-Path -LiteralPath $frontendLink)) "Frontend node_modules mount already exists."
    New-Item -ItemType Directory -Path $OutputRoot | Out-Null
    $transcriptStarted = $false
    try {
        New-Item -ItemType Junction -Path $desktopLink -Target (Join-Path $DependencyRoot "desktop\node_modules") | Out-Null
        New-Item -ItemType Junction -Path $frontendLink -Target (Join-Path $DependencyRoot "frontend\node_modules") | Out-Null
        & (Join-Path $SourceRoot "desktop\scripts\verify-detached-node-dependencies.ps1") -ManifestPath $DependencyManifest -RepoRoot $SourceRoot -EditionId sim -ExpectedSourceCommit $ProductSource -ExpectedSourceTree $ProductTree -FrontendDistPath (Join-Path $SourceRoot "frontend\dist") -InstallerBundlePath (Join-Path $CargoTargetDir "x86_64-pc-windows-gnullvm\release\bundle") | Out-Null
        Assert-True ($LASTEXITCODE -eq 0) "Live dependency mount verification failed."
        $env:DRONEDREAM_DESKTOP_EDITION_ID = "sim"
        $env:DRONEDREAM_EDITION_PROFILE = "sim-only"
        $env:VITE_DRONEDREAM_EDITION = "sim"
        $env:CARGO_BUILD_JOBS = "2"
        $env:CARGO_TARGET_DIR = $CargoTargetDir
        $env:DRONEDREAM_OAUTH_CLIENT_ID = $OAuthClientId
        $env:TAURI_SIGNING_PRIVATE_KEY_PATH = $UpdaterKeyPath
        $env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
        Start-Transcript -LiteralPath $BuildLog -Force | Out-Null
        $transcriptStarted = $true
        & (Join-Path $SourceRoot "desktop\scripts\build-windows-llvm.ps1") -AdditionalConfigPath (Join-Path $SourceRoot "distribution\sim\desktop\tauri.sim.conf.json") -CargoTargetDir $CargoTargetDir -DetachedNodeDependencyManifest $DependencyManifest -ExpectedProductName "DroneDream-Sim" -EditionId sim -PreserveBundleHistory
        Assert-True ($LASTEXITCODE -eq 0) "The single build invocation failed."
        Assert-True (Test-Path -LiteralPath $GeneratedInstaller -PathType Leaf) "Generated installer is missing."
        Assert-True (Test-Path -LiteralPath $GeneratedSignature -PathType Leaf) "Generated updater signature is missing."
        Copy-Item -LiteralPath $GeneratedInstaller -Destination $FixedArtifact
        Copy-Item -LiteralPath $GeneratedSignature -Destination $FixedSignature
        $artifactSha = Get-Sha256Lower -LiteralPath $FixedArtifact
        "$artifactSha  DroneDream-Sim-1.0.0.exe" | Set-Content -LiteralPath $FixedChecksum -Encoding ASCII
        Write-JsonFile ([ordered]@{ state = "built-frozen-awaiting-static-acceptance"; productSourceCommit = $ProductSource; dependencyManifestSha256 = Get-Sha256Lower -LiteralPath $DependencyManifest; dependencyTreeFingerprint = $ExpectedDependencyFingerprint; artifactPath = $FixedArtifact; artifactBytes = (Get-Item -LiteralPath $FixedArtifact).Length; artifactSha256 = $artifactSha; buildScriptInvocations = 1; frontendMaximum = 1; tauriMaximum = 1; cargoMaximum = 1; nsisMaximum = 1; retry = 0 }) -LiteralPath $BuildReceipt
        Get-Content -LiteralPath $BuildReceipt -Raw -Encoding UTF8
    } finally {
        if ($transcriptStarted) { Stop-Transcript | Out-Null }
        Remove-ExactJunction -LinkPath $desktopLink -ExpectedTarget (Join-Path $DependencyRoot "desktop\node_modules")
        Remove-ExactJunction -LinkPath $frontendLink -ExpectedTarget (Join-Path $DependencyRoot "frontend\node_modules")
        Assert-True ((Get-Sha256Lower -LiteralPath $FrozenArtifact) -ceq $FrozenArtifactSha256) "Historical artifact changed."
    }
}

if ($Mode -ceq "Plan") {
    [ordered]@{
        state = "green-plan-only-no-mutation"
        productSourceCommit = $ProductSource
        productSourceTree = $ProductTree
        dependencyBundleId = $DependencyBundleId
        dependencyTreeFingerprint = $ExpectedDependencyFingerprint
        sourceRootAbsent = -not (Test-Path -LiteralPath $SourceRoot)
        runRootAbsent = -not (Test-Path -LiteralPath $RunRoot)
        cargoTargetAbsent = -not (Test-Path -LiteralPath $CargoTargetDir)
        dependencyRootAbsent = -not (Test-Path -LiteralPath $DependencyRoot)
        preparationInvocations = 0
        npmCiInvocations = 0
        junctionsCreated = 0
        buildInvocations = 0
    } | ConvertTo-Json -Depth 6
} elseif ($Mode -ceq "Preflight") {
    $result = Assert-Preflight
    [ordered]@{ state = "preflight-passed-no-mutation"; cacheFingerprint = $result.cache.fingerprint; resources = $result.resources } | ConvertTo-Json -Depth 6
} elseif ($Mode -ceq "Prepare") {
    Invoke-Prepare
} else {
    Invoke-Execute
}
