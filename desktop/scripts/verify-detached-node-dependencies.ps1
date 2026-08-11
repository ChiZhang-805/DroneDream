param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [ValidateSet("universal", "sim", "lab", "field")]
    [string]$EditionId,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedSourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedSourceTree,
    [Parameter(Mandatory = $true)]
    [string]$FrontendDistPath,
    [Parameter(Mandatory = $true)]
    [string]$InstallerBundlePath,
    [switch]$ContractOnly,
    [switch]$InspectOutputPayload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "release-build-driver.psm1") -Force

function Assert-ExactProperties {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,
        [Parameter(Mandatory = $true)]
        [string[]]$Names,
        [Parameter(Mandatory = $true)]
        [string]$Context
    )
    $actual = @($Value.PSObject.Properties.Name)
    $missing = @($Names | Where-Object { $_ -cnotin $actual })
    $unknown = @($actual | Where-Object { $_ -cnotin $Names })
    if ($missing.Count -gt 0 -or $unknown.Count -gt 0) {
        throw "$Context has missing or unknown fields."
    }
}

function Get-Sha256Lower {
    param([Parameter(Mandatory = $true)][string]$Path)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Convert-ToWindowsFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    [IO.Path]::GetFullPath($Path.Replace('/', '\')).TrimEnd('\', '/')
}

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][string]$Text)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = New-Object Text.UTF8Encoding($false)
        $hash = $algorithm.ComputeHash($bytes.GetBytes($Text))
        -join ($hash | ForEach-Object { $_.ToString("x2") })
    } finally {
        $algorithm.Dispose()
    }
}

function Get-InventoryLine {
    param([Parameter(Mandatory = $true)][object]$Entry)
    $sha = if ($null -eq $Entry.sha256) { "" } else { [string]$Entry.sha256 }
    $target = if ($null -eq $Entry.target) { "" } else { [string]$Entry.target }
    "$([string]$Entry.path)|$([string]$Entry.type)|$([UInt64]$Entry.bytes)|$sha|$target"
}

function Get-ActualInventory {
    param([Parameter(Mandatory = $true)][string]$Root)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $entries = [Collections.Generic.List[object]]::new()
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($rootFull)
    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        foreach ($item in @(Get-ChildItem -LiteralPath $current -Force)) {
            $relative = $item.FullName.Substring($rootFull.Length).TrimStart('\', '/').Replace('\', '/')
            if ($relative -ceq "manifest.json") {
                continue
            }
            $isReparse = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
            if ($isReparse) {
                $targets = @($item.Target)
                if ($targets.Count -ne 1) {
                    throw "A dependency bundle reparse point has an ambiguous target."
                }
                $targetValue = [string]$targets[0]
                $targetCandidate = if ([IO.Path]::IsPathRooted($targetValue)) {
                    $targetValue
                } else {
                    Join-Path (Split-Path -Parent $item.FullName) $targetValue
                }
                $targetFull = [IO.Path]::GetFullPath($targetCandidate).TrimEnd('\', '/')
                if (-not (Test-PathIsWithinRoot -Path $targetFull -Root $rootFull)) {
                    throw "A nested dependency bundle reparse point escapes the bundle root."
                }
                $targetRelative = $targetFull.Substring($rootFull.Length).TrimStart('\', '/').Replace('\', '/')
                $entries.Add([pscustomobject]@{
                    path = $relative
                    type = "reparse"
                    bytes = [UInt64]0
                    sha256 = $null
                    target = $targetRelative
                })
            } elseif ($item.PSIsContainer) {
                $entries.Add([pscustomobject]@{
                    path = $relative
                    type = "directory"
                    bytes = [UInt64]0
                    sha256 = $null
                    target = $null
                })
                $pending.Push($item.FullName)
            } else {
                $entries.Add([pscustomobject]@{
                    path = $relative
                    type = "file"
                    bytes = [UInt64]$item.Length
                    sha256 = Get-Sha256Lower -Path $item.FullName
                    target = $null
                })
            }
        }
    }
    $entriesByPath = @{}
    [string[]]$paths = @($entries.ToArray() | ForEach-Object {
        $entriesByPath[[string]$_.path] = $_
        [string]$_.path
    })
    [Array]::Sort($paths, [StringComparer]::Ordinal)
    $array = @($paths | ForEach-Object { $entriesByPath[$_] })
    $array
}

$schemaPath = Join-Path $PSScriptRoot "..\..\distribution\schemas\desktop-node-dependency-bundle.schema.json"
if (-not (Test-Path -LiteralPath $schemaPath -PathType Leaf)) {
    throw "The detached dependency schema is missing."
}
$manifestFull = (Resolve-Path -LiteralPath $ManifestPath -ErrorAction Stop).Path
$repoRootFull = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path.TrimEnd('\', '/')
$manifest = Get-Content -LiteralPath $manifestFull -Raw -Encoding UTF8 | ConvertFrom-Json

$topLevelFields = @(
    "schemaVersion", "kind", "bundleVersion", "bundleId", "state",
    "editionScope", "productSource", "ownedBase", "dependencyRoot",
    "sourceInputs", "toolchain", "mounts", "inventory", "policies", "attestation"
)
Assert-ExactProperties -Value $manifest -Names $topLevelFields -Context "The dependency manifest"
if ([int]$manifest.schemaVersion -ne 1 -or
    [string]$manifest.kind -cne "dronedream-desktop-node-dependency-bundle" -or
    [string]$manifest.bundleVersion -cne "1.0.0" -or
    [string]$manifest.state -cne "attested-offline" -or
    [string]$manifest.bundleId -cnotmatch '^npm-win32-x64-[0-9a-f]{16}$') {
    throw "The detached dependency manifest identity is unsupported."
}
$expectedEditions = @("universal", "sim", "lab", "field")
if (@($manifest.editionScope).Count -ne 4 -or
    (Compare-Object -CaseSensitive -SyncWindow 0 $expectedEditions @($manifest.editionScope))) {
    throw "The detached dependency bundle is not scoped to all four exact Editions."
}

Assert-ExactProperties -Value $manifest.productSource -Names @("commit", "tree") -Context "productSource"
if ([string]$manifest.productSource.commit -cne $ExpectedSourceCommit -or
    [string]$manifest.productSource.tree -cne $ExpectedSourceTree) {
    throw "The detached dependency bundle is bound to a different product source."
}
$observedCommit = (& git -C $repoRootFull rev-parse --verify HEAD).Trim()
$observedTree = (& git -C $repoRootFull rev-parse 'HEAD^{tree}').Trim()
if ($LASTEXITCODE -ne 0 -or
    $observedCommit -cne $ExpectedSourceCommit -or
    $observedTree -cne $ExpectedSourceTree) {
    throw "The release source commit or tree drifted from the dependency manifest."
}

$ownedBaseFull = Convert-ToWindowsFullPath -Path ([string]$manifest.ownedBase)
$dependencyRootFull = Convert-ToWindowsFullPath -Path ([string]$manifest.dependencyRoot)
if (-not $dependencyRootFull.Equals(
    (Split-Path -Parent $manifestFull).TrimEnd('\', '/'),
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "The dependency manifest must be located at the exact dependency root."
}
if (-not (Test-PathIsWithinRoot -Path $dependencyRootFull -Root $ownedBaseFull)) {
    throw "The dependency root is outside the exact owned base."
}
if (-not (Split-Path -Parent $dependencyRootFull).Equals(
    $ownedBaseFull,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "The dependency root must be one source-bound bundle directly below the owned base."
}
if ((Split-Path -Leaf $dependencyRootFull) -cne [string]$manifest.bundleId) {
    throw "The dependency root name must equal the source-bound bundle identity."
}
$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $dependencyGitRoot = (& git -C $dependencyRootFull rev-parse --show-toplevel 2>$null | Out-String).Trim()
    $dependencyGitExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
if ($dependencyGitExitCode -eq 0 -and $dependencyGitRoot) {
    throw "The dependency root must remain outside every Git worktree."
}

$sourceInputNames = @(
    "desktop/package.json", "desktop/package-lock.json",
    "frontend/package.json", "frontend/package-lock.json"
)
if (@($manifest.sourceInputs).Count -ne 4) {
    throw "Exactly four package and lock source inputs are required."
}
for ($index = 0; $index -lt 4; $index += 1) {
    $input = @($manifest.sourceInputs)[$index]
    Assert-ExactProperties -Value $input -Names @("sourcePath", "bundlePath", "sha256") -Context "sourceInputs[$index]"
    if ([string]$input.sourcePath -cne $sourceInputNames[$index] -or
        [string]$input.bundlePath -cne $sourceInputNames[$index] -or
        [string]$input.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "A package or lock source input path is not exact."
    }
    $sourceFile = Join-Path $repoRootFull ([string]$input.sourcePath)
    $bundleFile = Join-Path $dependencyRootFull ([string]$input.bundlePath)
    $sourceHash = Get-Sha256Lower -Path $sourceFile
    $bundleHash = Get-Sha256Lower -Path $bundleFile
    if ($sourceHash -cne [string]$input.sha256 -or $bundleHash -cne $sourceHash) {
        throw "A package or lock file differs from the exact product source."
    }
}

Assert-ExactProperties -Value $manifest.toolchain -Names @(
    "operatingSystem", "architecture", "nodeVersion", "npmVersion",
    "tauriCli", "platformCli", "vite"
) -Context "toolchain"
if ([string]$manifest.toolchain.operatingSystem -cne "windows" -or
    [string]$manifest.toolchain.architecture -cne "x64") {
    throw "The dependency bundle platform is unsupported."
}
$nodeVersion = (& node.exe --version).Trim()
$npmVersion = (& npm.cmd --version).Trim()
if ($LASTEXITCODE -ne 0 -or
    $nodeVersion -cne [string]$manifest.toolchain.nodeVersion -or
    $npmVersion -cne [string]$manifest.toolchain.npmVersion) {
    throw "The active Node or npm version differs from the attested bundle."
}
$lockProbe = @'
const fs = require("fs");
const desktop = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const frontend = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
process.stdout.write(JSON.stringify({
  desktopLockfileVersion: desktop.lockfileVersion,
  frontendLockfileVersion: frontend.lockfileVersion,
  tauriCliVersion: desktop.packages["node_modules/@tauri-apps/cli"]?.version,
  platformCliVersion: desktop.packages["node_modules/@tauri-apps/cli-win32-x64-msvc"]?.version,
  viteVersion: frontend.packages["node_modules/vite"]?.version
}));
'@
$lockContractJson = ($lockProbe | & node.exe - `
    (Join-Path $repoRootFull "desktop\package-lock.json") `
    (Join-Path $repoRootFull "frontend\package-lock.json") | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $lockContractJson) {
    throw "The exact package locks could not be parsed."
}
$lockContract = $lockContractJson | ConvertFrom-Json
if ([int]$lockContract.desktopLockfileVersion -ne 3 -or
    [int]$lockContract.frontendLockfileVersion -ne 3 -or
    [string]$lockContract.tauriCliVersion -cne "2.11.4" -or
    [string]$lockContract.platformCliVersion -cne "2.11.4" -or
    [string]$lockContract.viteVersion -cne "7.3.6") {
    throw "The exact package locks do not contain the approved desktop tool versions."
}
$sourceInputHashes = @($manifest.sourceInputs | ForEach-Object { [string]$_.sha256 })
$identityLines = @([string]$manifest.productSource.commit) + $sourceInputHashes + @(
    $nodeVersion, $npmVersion, "windows", "x64"
)
$expectedBundleId = "npm-win32-x64-$((Get-Sha256Text -Text ($identityLines -join "`n")).Substring(0, 16))"
if ([string]$manifest.bundleId -cne $expectedBundleId) {
    throw "The dependency bundle identity is not derived from the exact source, locks, and platform."
}

$toolDefinitions = @(
    [pscustomobject]@{
        value = $manifest.toolchain.tauriCli
        fields = @("version", "packageJsonPath", "packageJsonSha256", "entrypointPath", "entrypointSha256")
        version = "2.11.4"
        packagePath = "desktop/node_modules/@tauri-apps/cli/package.json"
        hashFields = @(
            [pscustomobject]@{ pathField = "packageJsonPath"; hashField = "packageJsonSha256" },
            [pscustomobject]@{ pathField = "entrypointPath"; hashField = "entrypointSha256" }
        )
    },
    [pscustomobject]@{
        value = $manifest.toolchain.platformCli
        fields = @("packageName", "version", "packageJsonPath", "packageJsonSha256", "binaryPath", "binarySha256")
        version = "2.11.4"
        packagePath = "desktop/node_modules/@tauri-apps/cli-win32-x64-msvc/package.json"
        hashFields = @(
            [pscustomobject]@{ pathField = "packageJsonPath"; hashField = "packageJsonSha256" },
            [pscustomobject]@{ pathField = "binaryPath"; hashField = "binarySha256" }
        )
    },
    [pscustomobject]@{
        value = $manifest.toolchain.vite
        fields = @("version", "packageJsonPath", "packageJsonSha256")
        version = "7.3.6"
        packagePath = "frontend/node_modules/vite/package.json"
        hashFields = @(
            [pscustomobject]@{ pathField = "packageJsonPath"; hashField = "packageJsonSha256" }
        )
    }
)
foreach ($definition in $toolDefinitions) {
    Assert-ExactProperties -Value $definition.value -Names $definition.fields -Context "toolchain package"
    if ([string]$definition.value.version -cne $definition.version) {
        throw "A locked desktop tool version differs from the contract."
    }
    $packageFile = Join-Path $dependencyRootFull $definition.packagePath
    $packageJson = Get-Content -LiteralPath $packageFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$packageJson.version -cne $definition.version) {
        throw "An installed desktop tool version differs from its manifest."
    }
    foreach ($hashDefinition in $definition.hashFields) {
        $pathField = [string]$hashDefinition.pathField
        $hashField = [string]$hashDefinition.hashField
        $toolRelativePath = [string]($definition.value | Select-Object -ExpandProperty $pathField)
        $expectedToolHash = [string]($definition.value | Select-Object -ExpandProperty $hashField)
        $toolPath = Join-Path $dependencyRootFull $toolRelativePath
        if ((Get-Sha256Lower -Path $toolPath) -cne $expectedToolHash) {
            throw "An installed desktop tool file differs from its attested hash."
        }
    }
}
if ([string]$manifest.toolchain.platformCli.packageName -cne "@tauri-apps/cli-win32-x64-msvc") {
    throw "The platform-native Tauri package is not allowlisted."
}

Assert-ExactProperties -Value $manifest.policies -Names @(
    "networkAllowed", "systemTauriAllowed", "arbitraryPathInjectionAllowed",
    "dependencyMutationAllowed", "dependencyPayloadAllowed", "preparationAuthorizedSeparately"
) -Context "policies"
if ([bool]$manifest.policies.networkAllowed -or
    [bool]$manifest.policies.systemTauriAllowed -or
    [bool]$manifest.policies.arbitraryPathInjectionAllowed -or
    [bool]$manifest.policies.dependencyMutationAllowed -or
    [bool]$manifest.policies.dependencyPayloadAllowed -or
    -not [bool]$manifest.policies.preparationAuthorizedSeparately) {
    throw "The detached dependency policy does not fail closed."
}
foreach ($mount in @($manifest.mounts)) {
    Assert-ExactProperties -Value $mount -Names @("linkPath", "targetPath", "linkType") -Context "mount"
}
Assert-ExactProperties -Value $manifest.attestation -Names @(
    "createdAt", "preparationReceiptSha256", "offlineCacheSha256", "lifecycleScriptsAudited"
) -Context "attestation"
$attestationTime = [DateTimeOffset]::MinValue
if (-not [DateTimeOffset]::TryParse(
    [string]$manifest.attestation.createdAt,
    [Globalization.CultureInfo]::InvariantCulture,
    [Globalization.DateTimeStyles]::AssumeUniversal,
    [ref]$attestationTime
) -or
    [string]$manifest.attestation.preparationReceiptSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    [string]$manifest.attestation.offlineCacheSha256 -cnotmatch '^[0-9a-f]{64}$' -or
    -not [bool]$manifest.attestation.lifecycleScriptsAudited) {
    throw "The detached dependency preparation attestation is invalid."
}

$mountContract = Resolve-DetachedNodeDependencyMountContract `
    -RepoRoot $repoRootFull `
    -OwnedBase $ownedBaseFull `
    -DependencyRoot $dependencyRootFull `
    -Mounts @($manifest.mounts) `
    -FrontendDistPath $FrontendDistPath `
    -InstallerBundlePath $InstallerBundlePath `
    -InspectFileSystem:(-not $ContractOnly)

Assert-ExactProperties -Value $manifest.inventory -Names @(
    "algorithm", "excludedPaths", "entries", "treeFingerprint"
) -Context "inventory"
if ([string]$manifest.inventory.algorithm -cne "sha256-lines-v1" -or
    @($manifest.inventory.excludedPaths).Count -ne 1 -or
    [string]@($manifest.inventory.excludedPaths)[0] -cne "manifest.json") {
    throw "The dependency inventory algorithm or exclusion is unsupported."
}
$declaredEntries = @($manifest.inventory.entries)
$actualEntries = @(Get-ActualInventory -Root $dependencyRootFull)
if ($declaredEntries.Count -ne $actualEntries.Count) {
    throw "The dependency tree contains undeclared or missing entries."
}
$declaredLines = [Collections.Generic.List[string]]::new()
for ($index = 0; $index -lt $declaredEntries.Count; $index += 1) {
    $declared = $declaredEntries[$index]
    Assert-ExactProperties -Value $declared -Names @("path", "type", "bytes", "sha256", "target") -Context "inventory entry"
    $declaredLine = Get-InventoryLine -Entry $declared
    $actualLine = Get-InventoryLine -Entry $actualEntries[$index]
    if ($declaredLine -cne $actualLine) {
        throw "The dependency tree inventory differs from the attested manifest at '$([string]$declared.path)'."
    }
    $declaredLines.Add($declaredLine)
}
$treeFingerprint = Get-Sha256Text -Text ($declaredLines.ToArray() -join "`n")
if ($treeFingerprint -cne [string]$manifest.inventory.treeFingerprint) {
    throw "The dependency tree fingerprint differs from the attested manifest."
}

if ($InspectOutputPayload) {
    $payloadIsolation = Test-DetachedDependencyPayloadIsolation -OutputPaths @(
        $FrontendDistPath,
        $InstallerBundlePath
    )
    if ($payloadIsolation.violationCount -ne 0) {
        throw "Detached dependency bytes or links entered a product output."
    }
}

$tauriCliPath = Join-Path $dependencyRootFull ([string]$manifest.toolchain.tauriCli.entrypointPath)
[pscustomobject]@{
    schemaVersion = 1
    editionId = $EditionId
    bundleId = [string]$manifest.bundleId
    productSourceCommit = $ExpectedSourceCommit
    productSourceTree = $ExpectedSourceTree
    manifestPath = $manifestFull
    manifestSha256 = Get-Sha256Lower -Path $manifestFull
    dependencyRoot = $dependencyRootFull
    treeFingerprint = $treeFingerprint
    mountCount = $mountContract.mountCount
    mounts = @($mountContract.mounts)
    liveMountValidated = $mountContract.liveMountValidated
    outputPayloadInspected = [bool]$InspectOutputPayload
    tauriCliPath = $tauriCliPath
    networkAllowed = $false
    systemTauriAllowed = $false
}
