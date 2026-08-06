$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$sourceRoot = "C:\Users\zju20\ddfedc7"
$runRoot = "C:\Users\zju20\.codex\visualizations\2026\08\05\019fd0e2-71cc-7742-bfab-612510f37c39\field-yellow-build-edc7aa1-frontend-dist-replacement"
$outputRoot = Join-Path $runRoot "artifact"
$cargoTarget = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\field-cargo-target\edc7aa1"
$expectedHead = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
$expectedEvidenceHead = "6219e731ebe70dbb1e550de9156437f30bf1e648"
$applicationPath = "C:\Users\zju20\.codex\visualizations\2026\08\05\019fd0e2-71cc-7742-bfab-612510f37c39\field-yellow-readiness-edc7aa1-frontend-dist-replacement\yellow-build-application.json"
$applicationSha256 = "e756dc9272d2a5981a6dc674d0d2ae62cd217128876ffb70f81dcc1d611aca35"
$applicationFileSha256 = "0bdb64d8b28ae91e2d05c3f169bd568b5ca577258b21752a69fc7adc4cd25e9e"
$updaterKeyPath = "C:\Users\zju20\.tauri\dronedream-updater.key"
$oauthClientId = "3140bbe2-5f0e-4699-8a9b-295d4030f853"
$oauthCallback = "http://127.0.0.1:49213/desktop-auth/field/callback"
$overlayPath = Join-Path $runRoot "tauri-yellow-authorized.json"
$preflightReceiptPath = Join-Path $runRoot "preflight-receipt.json"

function Assert-Contract([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Get-Sha256Lower([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Assert-OwnedPath([string]$Path, [string]$OwnedRoot, [string]$Label) {
    $full = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetFullPath($OwnedRoot).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    Assert-Contract ($full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) `
        "$Label escapes its owned root: $full"
}

Assert-Contract ((Get-Sha256Lower $applicationPath) -ceq $applicationFileSha256) `
    "Approved YELLOW application file changed."
$application = Get-Content -LiteralPath $applicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-Contract ($application.applicationSha256 -ceq $applicationSha256) `
    "Approved YELLOW application canonical SHA changed."
Assert-Contract ($application.source.productCommit -ceq $expectedHead) `
    "Approved YELLOW application product source changed."
Assert-Contract ($application.source.evidenceCommit -ceq $expectedEvidenceHead) `
    "Approved YELLOW application evidence head changed."

$head = (& git -C $sourceRoot rev-parse HEAD).Trim()
$status = (& git -C $sourceRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
$remoteHead = (& git -C $sourceRoot rev-parse refs/remotes/origin/codex/software-field).Trim()
& git -C $sourceRoot merge-base --is-ancestor $expectedHead $remoteHead
$sourceOnPushedLineage = $LASTEXITCODE -eq 0
Assert-Contract ($head -ceq $expectedHead) "Approved Field product source changed."
Assert-Contract (-not $status) "Approved Field product source is not clean."
Assert-Contract $sourceOnPushedLineage "Approved Field source is not on the pushed Field lineage."
Assert-Contract ($remoteHead -ceq $expectedEvidenceHead) "Field upstream evidence head changed after approval."

$runRootFull = [IO.Path]::GetFullPath($runRoot)
$visualizationRoot = [IO.Path]::GetFullPath(
    "C:\Users\zju20\.codex\visualizations\2026\08\05\019fd0e2-71cc-7742-bfab-612510f37c39"
).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
Assert-Contract ($runRootFull.StartsWith($visualizationRoot, [StringComparison]::OrdinalIgnoreCase)) `
    "Run root is outside the approved external evidence owner."
Assert-OwnedPath $outputRoot $runRoot "OutputRoot"
Assert-OwnedPath (Join-Path $outputRoot "DroneDream-Field-1.0.0.exe") $outputRoot "artifact"
Assert-OwnedPath (Join-Path $outputRoot "DroneDream-Field-1.0.0.exe.sig") $outputRoot "updater signature"
Assert-OwnedPath (Join-Path $outputRoot "DroneDream-Field-1.0.0.exe.sha256") $outputRoot "checksum"
Assert-OwnedPath (Join-Path $outputRoot "latest-field.json") $outputRoot "updater metadata"
Assert-OwnedPath (Join-Path $outputRoot "build-receipt.json") $outputRoot "build receipt"
Assert-OwnedPath (Join-Path $outputRoot "handoff-manifest.json") $outputRoot "handoff manifest"
Assert-Contract (-not (Test-Path -LiteralPath $outputRoot)) "OutputRoot must not exist before the unique build."
Assert-Contract (-not (Test-Path -LiteralPath $cargoTarget)) "Source-specific Cargo target must start absent."

$cargoOwner = [IO.Path]::GetFullPath(
    "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\field-cargo-target"
).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
$cargoTargetFull = [IO.Path]::GetFullPath($cargoTarget)
Assert-Contract ($cargoTargetFull.StartsWith($cargoOwner, [StringComparison]::OrdinalIgnoreCase)) `
    "Cargo target is outside the Field-owned cache."
Assert-Contract ((Split-Path -Leaf $cargoTargetFull) -ceq "edc7aa1") `
    "Cargo target is not bound to the approved source."

$desktopModules = Get-Item -LiteralPath (Join-Path $sourceRoot "desktop\node_modules") -Force
$frontendModules = Get-Item -LiteralPath (Join-Path $sourceRoot "frontend\node_modules") -Force
Assert-Contract ($desktopModules.LinkType -ceq "Junction") "Desktop dependencies are not an owned junction."
Assert-Contract ($frontendModules.LinkType -ceq "Junction") "Frontend dependencies are not an owned junction."
Assert-Contract (Test-Path -LiteralPath (Join-Path $sourceRoot "desktop\node_modules\@tauri-apps\cli\tauri.js") -PathType Leaf) `
    "Pinned Tauri CLI is unavailable."

$fieldConfigPath = Join-Path $sourceRoot "desktop\src-tauri\tauri.field.conf.json"
$fieldConfigText = Get-Content -LiteralPath $fieldConfigPath -Raw -Encoding UTF8
$fieldConfig = $fieldConfigText | ConvertFrom-Json
$overlay = $fieldConfigText | ConvertFrom-Json
$originalBeforeBuild = [string]$fieldConfig.build.beforeBuildCommand
$overlay.build.beforeBuildCommand = "npm run frontend:field-build"
Assert-Contract ($fieldConfig.productName -ceq "DroneDream-Field") "Field internal product identity drifted."
Assert-Contract ($fieldConfig.identifier -ceq "io.dronedream.desktop.field") "Field bundle identity drifted."
Assert-Contract ($originalBeforeBuild -ceq "npm run frontend:field-build-gated") `
    "Field fail-closed default build gate drifted."
Assert-Contract ($fieldConfig.build.frontendDist -ceq "../../frontend/field-dist") `
    "Field frontend output drifted."
$releaseDriverPath = Join-Path $sourceRoot "desktop\scripts\release-build-driver.psm1"
Import-Module $releaseDriverPath -Force
$fieldDistContract = Resolve-EditionGeneratedFrontendContract `
    -RepoRoot $sourceRoot `
    -BaseConfigPath (Join-Path $sourceRoot "desktop\src-tauri\tauri.conf.json") `
    -AdditionalConfigPath $fieldConfigPath `
    -EditionId field
Assert-Contract ($fieldDistContract.relativePath -ceq "frontend/field-dist") `
    "Shared release driver did not resolve the exact Field generated directory."
$donorFiles = [ordered]@{
    "desktop\scripts\build-windows-llvm.ps1" = "4ac9b141b08aae39275d8538d06e11c711b0ce71c3f74ab7baccf11839d2f6dc"
    "desktop\scripts\verify-release-source-policy.mjs" = "97f643d67348ea11e80506e898302210dece51de1aee9cbf66ee55f839cf0d29"
    "desktop\scripts\verify-updater-signing-contract.ps1" = "7a8b480f3fa268fd474c992b1a4d812f3221f4deb76ee06d37692aab3d785117"
    "distribution\tests\test_shared_windows_build_contract.py" = "db6ca9f8459980c50bec870f91b72417c44e2aa85031f51c37a6a349a97cc957"
}
foreach ($entry in $donorFiles.GetEnumerator()) {
    Assert-Contract ((Get-Sha256Lower (Join-Path $sourceRoot $entry.Key)) -ceq $entry.Value) `
        "Shared release donor file drifted: $($entry.Key)"
}
$releaseDriverBlob = (& git -C $sourceRoot rev-parse "HEAD:desktop/scripts/release-build-driver.psm1").Trim()
$donorReleaseDriverBlob = (& git -C $sourceRoot rev-parse "d80f5f99309668d9d1cd50be51371efaa3c5491d:desktop/scripts/release-build-driver.psm1").Trim()
Assert-Contract ($releaseDriverBlob -ceq $donorReleaseDriverBlob) `
    "Shared release driver Git blob drifted."
Assert-Contract ($fieldConfig.app.windows[0].title -ceq ("DroneDream " + [char]0x00B7 + " FIELD")) `
    "Field display title drifted."
$normalizedSource = $fieldConfig | ConvertTo-Json -Depth 100 -Compress
$overlayForComparison = ($overlay | ConvertTo-Json -Depth 100) | ConvertFrom-Json
$overlayForComparison.build.beforeBuildCommand = $originalBeforeBuild
$normalizedRoundTrip = $overlayForComparison | ConvertTo-Json -Depth 100 -Compress
Assert-Contract ($normalizedSource -ceq $normalizedRoundTrip) `
    "Tauri authorization overlay changes more than beforeBuildCommand."
[IO.File]::WriteAllText(
    $overlayPath,
    (($overlay | ConvertTo-Json -Depth 100) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
$effectiveOverlayContract = Resolve-EditionGeneratedFrontendContract `
    -RepoRoot $sourceRoot `
    -BaseConfigPath (Join-Path $sourceRoot "desktop\src-tauri\tauri.conf.json") `
    -AdditionalConfigPath $overlayPath `
    -EditionId field
Assert-Contract ($effectiveOverlayContract.relativePath -ceq "frontend/field-dist") `
    "Authorized overlay does not resolve to the exact Field generated directory."

$publicEnvPath = Join-Path $sourceRoot "frontend\.env.production"
Assert-Contract (Test-Path -LiteralPath $publicEnvPath -PathType Leaf) `
    "Tracked public Supabase production variables are unavailable."
Assert-Contract (Test-Path -LiteralPath $updaterKeyPath -PathType Leaf) `
    "Approved updater key path is unavailable."
Assert-Contract ($oauthClientId -match '^[0-9a-f-]{36}$') "Field public OAuth client ID is invalid."
Assert-Contract ($oauthCallback -ceq "http://127.0.0.1:49213/desktop-auth/field/callback") `
    "Field OAuth callback drifted."

$requiredCommands = @("git.exe", "node.exe", "npm.cmd", "rustup.exe")
$missingCommands = @($requiredCommands | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
Assert-Contract ($missingCommands.Count -eq 0) "Required build commands are missing: $($missingCommands -join ', ')"
$makensis = Join-Path $env:LOCALAPPDATA "tauri\NSIS\makensis.exe"
Assert-Contract (Test-Path -LiteralPath $makensis -PathType Leaf) "Cached makensis is unavailable."
$llvmRoot = Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages") `
    -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "MartinStorsjo.LLVM-MinGW.UCRT_*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
Assert-Contract ($null -ne $llvmRoot) "LLVM-MinGW is unavailable."
$clang = Get-ChildItem -LiteralPath $llvmRoot.FullName -Recurse `
    -Filter "x86_64-w64-mingw32-clang.exe" -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
Assert-Contract ($null -ne $clang) "LLVM-MinGW clang is unavailable."
& rustup.exe run 1.97.0-x86_64-pc-windows-gnullvm rustc --version | Out-Null
Assert-Contract ($LASTEXITCODE -eq 0) "Pinned Rust gnullvm toolchain is unavailable."

$os = Get-CimInstance Win32_OperatingSystem
$cDrive = Get-PSDrive C
$zDrive = Get-PSDrive Z
$heavy = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match 'cargo|rustc|tauri|makensis|px4|gazebo'
})
Assert-Contract ($heavy.Count -eq 0) "A heavy build or simulator process is already running."
Assert-Contract ([int64]$os.FreePhysicalMemory * 1024 -ge 6GB) "Available memory is below the approved gate."
Assert-Contract ([int64]$cDrive.Free -ge 20GB) "C drive free space is below the approved gate."
Assert-Contract ([int64]$zDrive.Free -ge 10GB) "Z drive free space is below the approved gate."

$planned = [ordered]@{
    outputRoot = [IO.Path]::GetFullPath($outputRoot)
    artifact = [IO.Path]::GetFullPath((Join-Path $outputRoot "DroneDream-Field-1.0.0.exe"))
    updaterSignature = [IO.Path]::GetFullPath((Join-Path $outputRoot "DroneDream-Field-1.0.0.exe.sig"))
    checksum = [IO.Path]::GetFullPath((Join-Path $outputRoot "DroneDream-Field-1.0.0.exe.sha256"))
    updaterMetadata = [IO.Path]::GetFullPath((Join-Path $outputRoot "latest-field.json"))
    buildReceipt = [IO.Path]::GetFullPath((Join-Path $outputRoot "build-receipt.json"))
    handoffManifest = [IO.Path]::GetFullPath((Join-Path $outputRoot "handoff-manifest.json"))
}
$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-replacement-yellow-preflight-receipt"
    decision = "allow-one-build-after-preflight"
    source = [ordered]@{
        productCommit = $expectedHead
        upstreamEvidenceCommit = $remoteHead
        clean = $true
        pushedLineage = $true
    }
    authorization = [ordered]@{
        applicationSha256 = $applicationSha256
        applicationFileSha256 = $applicationFileSha256
        serialGateReleased = $true
        cargoBuildCountMaximum = 1
        nsisInvocationMaximum = 1
        cargoBuildJobs = 2
        preCargoGateFailureCount = 0
        tauriCargoNsisInvocationCountBeforeThisReceipt = 0
    }
    paths = [ordered]@{
        sourceRoot = [IO.Path]::GetFullPath($sourceRoot)
        runRoot = $runRootFull
        cargoTarget = $cargoTargetFull
        overlay = [IO.Path]::GetFullPath($overlayPath)
        plannedOutputs = $planned
        allOutputPathsOwned = $true
        outputSlotsEmpty = $true
    }
    configuration = [ordered]@{
        editionId = "field"
        editionProfile = "field-lightweight"
        artifactFileName = "DroneDream-Field-1.0.0.exe"
        oauthClientId = $oauthClientId
        oauthCallback = $oauthCallback
        supabasePublicSourcePath = $publicEnvPath
        supabasePublicSourceSha256 = Get-Sha256Lower $publicEnvPath
        updaterKeyPath = $updaterKeyPath
        updaterKeyId = "BA3FDCAF71CE2FF5"
        updaterKeyReadDuringPreflight = $false
        updaterKeyPasswordMode = "empty"
        overlaySha256 = Get-Sha256Lower $overlayPath
        overlayOnlySemanticChange = "build.beforeBuildCommand=npm run frontend:field-build"
    }
    resources = [ordered]@{
        memoryFreeBytes = [int64]$os.FreePhysicalMemory * 1024
        cFreeBytes = [int64]$cDrive.Free
        zFreeBytes = [int64]$zDrive.Free
        heavyProcessCount = $heavy.Count
    }
    safety = [ordered]@{
        networkAllowed = $false
        installAllowed = $false
        runtimeMigrationAllowed = $false
        deviceOrHardwareAllowed = $false
        simulationAllowed = $false
        deploymentAllowed = $false
        validatedHardwarePackCount = 0
        hardwareDecision = "deny"
    }
    buildInvoked = $false
}
[IO.File]::WriteAllText(
    $preflightReceiptPath,
    (($receipt | ConvertTo-Json -Depth 20) + "`n"),
    [Text.UTF8Encoding]::new($false)
)
Write-Host "Field replacement YELLOW preflight passed; unique build remains unconsumed."
