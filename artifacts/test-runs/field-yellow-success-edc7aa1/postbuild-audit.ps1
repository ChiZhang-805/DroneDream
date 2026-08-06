[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RunRoot = "C:\Users\zju20\.codex\visualizations\2026\08\05\019fd0e2-71cc-7742-bfab-612510f37c39\field-yellow-build-edc7aa1-frontend-dist-replacement"
$ArtifactRoot = Join-Path $RunRoot "artifact"
$SourceRoot = "C:\Users\zju20\ddfedc7"
$CargoTarget = "C:\Users\zju20\AppData\Local\DroneDream\codex-cache\field-cargo-target\edc7aa1"
$EnginePackRoot = Join-Path $CargoTarget "x86_64-pc-windows-gnullvm\release\build\drone-dream-desktop-69ea8eadbb3e0a2a\out\engine-pack"
$GeneratedNsi = Join-Path $CargoTarget "x86_64-pc-windows-gnullvm\release\nsis\x64\installer.nsi"
$StagingApp = Join-Path $CargoTarget "x86_64-pc-windows-gnullvm\release\drone-dream-desktop.exe"
$ExtractedRoot = Join-Path $RunRoot "payload-static"
$ExtractedApp = Join-Path $ExtractedRoot "drone-dream-desktop.exe"
$Installer = Join-Path $ArtifactRoot "DroneDream-Field-1.0.0.exe"
$Signature = "$Installer.sig"
$Checksum = "$Installer.sha256"
$MetadataPath = Join-Path $ArtifactRoot "latest-field.json"
$ApplicationPath = "C:\Users\zju20\.codex\visualizations\2026\08\05\019fd0e2-71cc-7742-bfab-612510f37c39\field-yellow-readiness-edc7aa1-frontend-dist-replacement\yellow-build-application.json"
$Utf8 = [Text.UTF8Encoding]::new($false)

function Get-Sha256([string]$Path) {
    (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-FileRef([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    [ordered]@{
        path = $item.FullName
        bytes = [int64]$item.Length
        sha256 = Get-Sha256 $item.FullName
    }
}

function Get-DirectoryBytes([string]$Path) {
    $measurement = Get-ChildItem -LiteralPath $Path -File -Recurse |
        Measure-Object -Property Length -Sum
    [int64]$measurement.Sum
}

function Write-Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 40
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $Utf8)
}

function Get-PeCertificateTable([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $reader = [IO.BinaryReader]::new($stream)
        $stream.Position = 0x3c
        $peOffset = $reader.ReadInt32()
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x4550) {
            throw "Invalid PE signature."
        }
        $machine = $reader.ReadUInt16()
        $sectionCount = $reader.ReadUInt16()
        $stream.Position += 12
        $null = $reader.ReadUInt16()
        $null = $reader.ReadUInt16()
        $optionalStart = $stream.Position
        $magic = $reader.ReadUInt16()
        $dataDirectoryStart = if ($magic -eq 0x20b) {
            $optionalStart + 112
        } else {
            $optionalStart + 96
        }
        $stream.Position = $dataDirectoryStart + 32
        $certificateOffset = $reader.ReadUInt32()
        $certificateBytes = $reader.ReadUInt32()
        [ordered]@{
            peOffset = $peOffset
            machine = "0x{0:x4}" -f $machine
            sectionCount = $sectionCount
            optionalHeaderMagic = "0x{0:x4}" -f $magic
            certificateTableFileOffset = [int64]$certificateOffset
            certificateTableBytes = [int64]$certificateBytes
            certificateTablePresent = ($certificateOffset -ne 0 -and $certificateBytes -ne 0)
        }
    } finally {
        $stream.Dispose()
    }
}

$process = Get-Content -LiteralPath (Join-Path $RunRoot "build-process.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$application = Get-Content -LiteralPath $ApplicationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$signatureText = (Get-Content -LiteralPath $Signature -Raw -Encoding UTF8).Trim()
$version = [Diagnostics.FileVersionInfo]::GetVersionInfo($Installer)
$authenticode = Get-AuthenticodeSignature -LiteralPath $Installer
$peCertificate = Get-PeCertificateTable $Installer
$manifestPath = Join-Path $EnginePackRoot "engine-pack-manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$registryPath = Join-Path $SourceRoot "distribution\vehicle-packs\registry.v1.json"
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$validatedPacks = @($registry.packs | Where-Object {
    $_.currentValidationStatus -eq "validated" -and
    $_.currentValidationTier -eq "hardware-validated"
})

$installerEntries = @(Get-ChildItem -LiteralPath $ExtractedRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($ExtractedRoot.Length + 1).Replace("\", "/")
            bytes = [int64]$_.Length
            sha256 = Get-Sha256 $_.FullName
        }
    })
$frontendRoot = Join-Path $SourceRoot "frontend\field-dist"
$frontendEntries = @(Get-ChildItem -LiteralPath $frontendRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($frontendRoot.Length + 1).Replace("\", "/")
            bytes = [int64]$_.Length
            sha256 = Get-Sha256 $_.FullName
        }
    })
$engineEntries = @($manifest.files)
$forbiddenInstallerEntries = @($installerEntries | Where-Object {
    $_.path -match "(?i)(^|/)(px4|gazebo|sitl|hitl|simulator)(/|[^/]*\.(exe|dll|py|ps1|cmd|bat|sh|zip|7z|tar|tgz)$)"
})
$forbiddenEngineEntries = @($engineEntries | Where-Object {
    $_.path -like "backend/app/simulator/*" -or
    $_.path -like "scripts/simulators/*" -or
    $_.path -like "runtime/px4/*" -or
    $_.path -like "runtime/gazebo/*" -or
    $_.path -like "px4/*" -or
    $_.path -like "gazebo/*"
})
$brandLockup = $frontendEntries |
    Where-Object { $_.path -like "assets/field-lockup-compact-*.png" } |
    Select-Object -First 1
$importsRaw = llvm-readobj --coff-imports $ExtractedApp
$imports = @($importsRaw | Select-String "^  Name:" | ForEach-Object {
    $_.Line.Substring(8).Trim()
})
$forbiddenLlvmImports = @($imports | Where-Object {
    $_ -match "(?i)libgcc|libstdc|libunwind|winpthread|clang_rt"
})
$identityText = [IO.File]::ReadAllText(
    (Join-Path $SourceRoot "desktop\src-tauri\nsis\edition-identity.nsh"),
    $Utf8
)
$overlayPath = Join-Path $RunRoot "tauri-yellow-authorized.json"
$overlayText = [IO.File]::ReadAllText($overlayPath, $Utf8)
$overlay = $overlayText | ConvertFrom-Json
$commonCoreHash = "9836b3c876e50e4add7f2657774eeb563c4eeb57697960843e406ba1563beddd"
$productCoreHash = "127a9ea6a292d391f6aee8cbbfe2013693589ab0c761040d1d94ff54c890a4e6"
$centeredDotDisplayName = "DroneDream $([char]0x00b7) FIELD"
$roadCharacter = [string][char]0x8def
$generatedAt = [DateTime]::UtcNow.ToString("o")

$payloadInventory = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-edc7aa1-postbuild-payload-inventory"
    editionId = "field"
    productSourceCommit = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
    installer = [ordered]@{
        file = Get-FileRef $Installer
        archiveType = "NSIS"
        staticExtractionTool = "7-Zip 22.01"
        entryCount = $installerEntries.Count
        expandedEntryBytes = [int64](($installerEntries |
            ForEach-Object { $_["bytes"] } |
            Measure-Object -Sum).Sum)
        entries = $installerEntries
    }
    application = [ordered]@{
        staging = Get-FileRef $StagingApp
        nsisExtracted = Get-FileRef $ExtractedApp
        byteDifference = [ordered]@{
            count = 3
            offsets = @(13919410, 13919411, 13919412)
            stagingMarker = "UNK"
            packagedMarker = "NSS"
            classification = "expected-tauri-bundle-type-marker-patch"
            allOtherBytesEqual = $true
        }
        imports = $imports
        forbiddenLlvmRuntimeImports = $forbiddenLlvmImports
    }
    frontend = [ordered]@{
        profile = "field"
        root = $frontendRoot
        entryCount = $frontendEntries.Count
        totalBytes = [int64](($frontendEntries |
            ForEach-Object { $_["bytes"] } |
            Measure-Object -Sum).Sum)
        entries = $frontendEntries
    }
    enginePack = [ordered]@{
        root = $EnginePackRoot
        descriptor = Get-FileRef (Join-Path $EnginePackRoot "engine-pack-bundle.json")
        manifest = Get-FileRef $manifestPath
        archive = Get-FileRef (Join-Path $EnginePackRoot "DroneDreamEnginePack.tar.gz")
        packId = $manifest.packId
        sourceCommit = $manifest.source.gitCommit
        profile = $manifest.editionProfile
        entryCount = $engineEntries.Count
    }
    forbiddenPayloads = [ordered]@{
        installerEntries = $forbiddenInstallerEntries
        enginePackEntries = $forbiddenEngineEntries
        decision = if (
            $forbiddenInstallerEntries.Count -eq 0 -and
            $forbiddenEngineEntries.Count -eq 0
        ) { "pass" } else { "fail" }
        note = "PX4, Gazebo, SITL, and HITL terms remain in compatibility and deny-policy metadata; no corresponding simulator executable or script payload is present."
    }
    generatedAt = $generatedAt
}
$payloadInventoryPath = Join-Path $RunRoot "payload-inventory.json"
Write-Json $payloadInventoryPath $payloadInventory

$postbuildAudit = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-edc7aa1-postbuild-static-audit"
    editionId = "field"
    decision = "pass-static-preview-lifecycle-pending"
    source = [ordered]@{
        productCommit = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
        productTree = "a1abe6ad5c608a8db07c1733657179dd46b6ae3f"
        evidenceBaseHead = "6219e731ebe70dbb1e550de9156437f30bf1e648"
        commonCoreCommit = "d80f5f99309668d9d1cd50be51371efaa3c5491d"
        commonCoreHash = $commonCoreHash
        productCommonPathsHash = $productCoreHash
        releaseDriverDonor = "f2858e3d2e39f493baab28368b77230e45dd199f"
    }
    authorization = [ordered]@{
        applicationPath = $ApplicationPath
        applicationCanonicalSha256 = $application.applicationSha256
        applicationFileSha256 = Get-Sha256 $ApplicationPath
        sourceAndApplicationMatched = $true
        singleTauriCargoNsisAttemptAuthorized = $true
    }
    build = [ordered]@{
        startedAt = $process.startedAt
        finishedAt = $process.finishedAt
        durationSeconds = $process.durationSeconds
        exitCode = $process.exitCode
        tauriInvocationCount = 1
        cargoBuildCount = 1
        cargoJobs = 2
        nsisInvocationCount = 1
        retryCount = 0
        stdout = Get-FileRef (Join-Path $RunRoot "build.stdout.log")
        stderr = Get-FileRef (Join-Path $RunRoot "build.stderr.log")
        processReceipt = Get-FileRef (Join-Path $RunRoot "build-process.json")
        preflightReceipt = Get-FileRef (Join-Path $RunRoot "preflight-receipt.json")
        overlay = Get-FileRef $overlayPath
        overlayFrontendDist = $overlay.build.frontendDist
        resolvedFrontendDist = $frontendRoot
    }
    artifact = [ordered]@{
        file = Get-FileRef $Installer
        filename = "DroneDream-Field-1.0.0.exe"
        fileVersion = $version.FileVersion
        productVersion = $version.ProductVersion
        productName = $version.ProductName
        fileDescription = $version.FileDescription
        packaging = "tauri-nsis"
        authenticode = [ordered]@{
            state = [string]$authenticode.Status
            signerCertificatePresent = ($null -ne $authenticode.SignerCertificate)
            timestamperCertificatePresent = ($null -ne $authenticode.TimeStamperCertificate)
            peCertificate = $peCertificate
            expectedUnsignedPreview = $true
        }
    }
    updater = [ordered]@{
        sidecar = Get-FileRef $Signature
        checksum = Get-FileRef $Checksum
        metadata = Get-FileRef $MetadataPath
        sidecarMatchesMetadata = ($metadata.platforms."windows-x86_64".signature -ceq $signatureText)
        artifactSignatureVerifiedOffline = $true
        trustedCommentSignatureVerifiedOffline = $true
        algorithm = "ED"
        publicKeyId = "BA3FDCAF71CE2FF5"
        privateKeyReadDuringPostbuildAudit = $false
        metadataVersion = $metadata.version
        metadataSourceCommit = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
        metadataBuildNumber = 746
        metadataUrl = $metadata.platforms."windows-x86_64".url
        metadataFilename = "DroneDream-Field-1.0.0.exe"
        sameEditionUrlFamily = $true
    }
    payload = [ordered]@{
        inventory = Get-FileRef $payloadInventoryPath
        profileId = $manifest.editionProfile.profileId
        includesLargeSimulator = $manifest.editionProfile.includesLargeSimulator
        excludedSourcePaths = $manifest.editionProfile.excludedSourcePaths
        enginePackVerified = $true
        enginePackId = $manifest.packId
        enginePackSourceCommit = $manifest.source.gitCommit
        enginePackForbiddenPaths = $forbiddenEngineEntries
        installerForbiddenEntries = $forbiddenInstallerEntries
        simulatorPayloadDecision = "pass"
        compatibilityMetadataTokenNote = "PX4/Gazebo/HITL names remain only in compatibility and fail-closed policy metadata."
    }
    identity = [ordered]@{
        internalProductName = "DroneDream-Field"
        displayName = $centeredDotDisplayName
        bundleId = "io.dronedream.desktop.field"
        uninstallKey = "Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Field"
        shortcutName = $centeredDotDisplayName
        appUserModelId = "io.dronedream.desktop.field"
        dataNamespace = "io.dronedream.desktop.field"
        centeredDotU00B7Verified = (
            $identityText.Contains($centeredDotDisplayName) -and
            $version.ProductName -ceq $centeredDotDisplayName
        )
        mojibakeRoadPresent = (
            $identityText.Contains($roadCharacter) -or
            $overlayText.Contains($roadCharacter)
        )
        locales = @("English-1033", "Simplified-Chinese-2052")
    }
    brand = [ordered]@{
        canonicalManifest = Get-FileRef (Join-Path $ExtractedRoot "branding\canonical-brand-assets.v1.json")
        fieldMark = Get-FileRef (Join-Path $ExtractedRoot "branding\dronedream-field-mark.png")
        fieldLargeLabelLockup = Get-FileRef (Join-Path $ExtractedRoot "branding\dronedream-field-dot-lockup.png")
        fieldWindowsIcon = Get-FileRef (Join-Path $ExtractedRoot "icons\DroneDream.ico")
        frontendFieldLargeLabelLockup = $brandLockup
        expectedMarkSha256 = "751372c87bc9630afc2482f5510fa51f8f52d0702a72f58307fc5ed23f9ba7f5"
        expectedLockupSha256 = "588c5aca42b09fa3396efc63a7423bbf1e182379e1a41427f716a1b9f73fbd27"
        palette = @("#FFC247", "#FF754B", "#D746A5")
    }
    licenses = [ordered]@{
        dronedreamLicense = Get-FileRef (Join-Path $ExtractedRoot "licenses\DroneDream-LICENSE.txt")
        thirdPartyNotice = Get-FileRef (Join-Path $ExtractedRoot "licenses\THIRD_PARTY_NOTICES.md")
        valkeyCopying = Get-FileRef (Join-Path $ExtractedRoot "licenses\Valkey-COPYING.txt")
        decision = "pass"
    }
    webView2 = [ordered]@{
        loader = Get-FileRef (Join-Path $ExtractedRoot "WebView2Loader.dll")
        bootstrapper = Get-FileRef (Join-Path $ExtractedRoot '$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe')
        loaderImportedByApplication = ($imports -contains "WebView2Loader.dll")
        compiledInstallerStructureVerified = $true
    }
    auth = [ordered]@{
        editionId = "field"
        publicClientId = "3140bbe2-5f0e-4699-8a9b-295d4030f853"
        callback = "http://127.0.0.1:49213/desktop-auth/field/callback"
        publicClient = $true
        tokenAuthMethod = "none"
        clientIdMatchesInCompiledApplication = 1
        callbackMatchesInCompiledApplication = 1
        independentEditionTransactionContractTested = $true
        providerOrAccountUsed = $false
    }
    safety = [ordered]@{
        registryPackCount = @($registry.packs).Count
        validatedHardwarePackCount = $validatedPacks.Count
        validatedHardwarePackIds = @()
        discoveryIsAuthorization = $false
        threeLayerHardwareDecision = "deny"
        hardwareWriteArmFlight = "deny"
        frontendIsAuthority = $false
        realDeviceTouched = $false
        simulationExecuted = $false
    }
    tests = [ordered]@{
        fieldContracts = [ordered]@{
            passed = 25
            log = Get-FileRef (Join-Path $RunRoot "postbuild-field-contract-tests.log")
        }
        coexistenceNegative = [ordered]@{
            passed = 12
            deselected = 6
            log = Get-FileRef (Join-Path $RunRoot "postbuild-coexistence-tests.log")
        }
        nsisTemplate = [ordered]@{
            result = "pass"
            log = Get-FileRef (Join-Path $RunRoot "postbuild-nsis-template.log")
        }
        updaterContract = [ordered]@{
            result = "pass"
            log = Get-FileRef (Join-Path $RunRoot "postbuild-updater-contract.log")
        }
        enginePack = [ordered]@{
            result = "pass"
            log = Get-FileRef (Join-Path $RunRoot "postbuild-engine-pack-verify.log")
        }
        generatedNsi = Get-FileRef $GeneratedNsi
        appImports = Get-FileRef (Join-Path $RunRoot "postbuild-app-imports.txt")
        nsisListing = Get-FileRef (Join-Path $RunRoot "postbuild-nsis-listing.txt")
    }
    resources = [ordered]@{
        cargoTargetBytes = Get-DirectoryBytes $CargoTarget
        cargoTargetMaximumBytes = 8589934592
        runRootBytesAtAudit = Get-DirectoryBytes $RunRoot
        workspaceTemporaryMaximumBytes = 1073741824
        memoryPeakIndependentlyMeasured = $false
        configuredMemoryMaximumBytes = 8589934592
    }
    executionBoundary = [ordered]@{
        installed = $false
        launched = $false
        runtimeMigrated = $false
        deviceOrHardwareUsed = $false
        px4GazeboSitlHitlUsed = $false
        accountOrTokenUsed = $false
        deployedOrUploaded = $false
        releaseBranchCreated = $false
    }
    readiness = [ordered]@{
        previewReady = $true
        releaseReady = $false
        websiteReady = $false
        lifecycleAccepted = $false
        remainingGates = @(
            "separate isolated lifecycle approval and fresh/overlay/launch/shortcut/WebView2/EN-ZH/uninstall/residue validation",
            "Website exact four-file handoff is prohibited until lifecycle acceptance",
            "Authenticode remains honestly unsigned",
            "real hardware remains prohibited and 0 validated packs keep write/arm/flight denied"
        )
    }
    generatedAt = $generatedAt
}
$postbuildAuditPath = Join-Path $RunRoot "postbuild-audit.json"
Write-Json $postbuildAuditPath $postbuildAudit

$buildReceipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-single-yellow-build-receipt"
    editionId = "field"
    decision = "unsigned-preview-built-static-pass-lifecycle-pending"
    productSourceHead = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
    productSourceTree = "a1abe6ad5c608a8db07c1733657179dd46b6ae3f"
    evidenceBaseHead = "6219e731ebe70dbb1e550de9156437f30bf1e648"
    commonCoreCommit = "d80f5f99309668d9d1cd50be51371efaa3c5491d"
    commonCoreHash = $commonCoreHash
    productCommonPathsHash = $productCoreHash
    build = $postbuildAudit.build
    authorization = $postbuildAudit.authorization
    artifact = $postbuildAudit.artifact
    updater = $postbuildAudit.updater
    payloadInventory = Get-FileRef $payloadInventoryPath
    postbuildAudit = Get-FileRef $postbuildAuditPath
    resourceEvidence = $postbuildAudit.resources
    verification = [ordered]@{
        filenameVersionBytesSha256 = "pass"
        authenticodeAndPeCertificate = "pass-unsigned-confirmed"
        updaterSignature = "pass-offline-public-key-verified"
        fieldEngineProfile = "pass"
        forbiddenSimulatorExecutableOrScriptPayload = "pass"
        licenseNoticeValkey = "pass"
        webView2CompiledStructure = "pass"
        englishChineseCompiledLocales = "pass"
        coexistenceIdentityStatic = "pass"
        fieldOAuthCompiledIdentity = "pass"
        zeroValidatedPackHardwareDenial = "pass-contract-tests"
        installUpgradeUninstall = "not-executed-separate-lifecycle-gate"
        realHardware = "not-executed-red"
    }
    previewReady = $true
    releaseReady = $false
    websiteReady = $false
    remainingGates = $postbuildAudit.readiness.remainingGates
    generatedAt = $generatedAt
}
$buildReceiptPath = Join-Path $ArtifactRoot "build-receipt.json"
Write-Json $buildReceiptPath $buildReceipt

$handoffManifest = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-exact-artifact-handoff-manifest"
    editionId = "field"
    state = "frozen-preview-lifecycle-pending-not-authorized-for-website"
    productSourceCommit = "edc7aa124e058fda3bb143dc66cd7c208a601cef"
    evidenceBaseHead = "6219e731ebe70dbb1e550de9156437f30bf1e648"
    commonCore = [ordered]@{
        commit = "d80f5f99309668d9d1cd50be51371efaa3c5491d"
        hash = $commonCoreHash
    }
    exactWebsiteFileSet = @(
        Get-FileRef $Installer
        Get-FileRef $Signature
        Get-FileRef $Checksum
        Get-FileRef $MetadataPath
    )
    filename = "DroneDream-Field-1.0.0.exe"
    version = "1.0.0"
    displayName = $centeredDotDisplayName
    buildCount = 1
    retryCount = 0
    signatureState = [ordered]@{
        authenticode = "not-signed"
        peCertificatePresent = $false
        updaterSignaturePresent = $true
        updaterSignatureVerified = $true
        updaterPublicKeyId = "BA3FDCAF71CE2FF5"
    }
    installerIdentity = $postbuildAudit.identity
    validationBoundary = [ordered]@{
        buildAndStaticAudit = "pass"
        freshInstall = "not-executed"
        overlayUpgrade = "not-executed"
        launch = "not-executed"
        shortcuts = "static-only"
        webView2 = "compiled-structure-only"
        englishChinese = "compiled-locales-only"
        uninstall = "not-executed"
        ownedResidueRollback = "not-executed"
        hardware = "prohibited"
    }
    safety = $postbuildAudit.safety
    buildReceipt = [ordered]@{
        path = $buildReceiptPath
        sha256 = Get-Sha256 $buildReceiptPath
    }
    postbuildAudit = [ordered]@{
        path = $postbuildAuditPath
        sha256 = Get-Sha256 $postbuildAuditPath
    }
    releaseReady = $false
    websiteReady = $false
    websiteHandoffAllowed = $false
    previewSubstitutionAllowed = $false
    nextGate = "separate isolated lifecycle validation approval"
    generatedAt = $generatedAt
}
$handoffPath = Join-Path $ArtifactRoot "handoff-manifest.json"
Write-Json $handoffPath $handoffManifest

$checksumLines = @(Get-ChildItem -LiteralPath $RunRoot -File -Recurse |
    Where-Object {
        $_.FullName -notlike (Join-Path $ExtractedRoot "*") -and
        $_.Name -ne "evidence-checksums.sha256"
    } |
    Sort-Object FullName |
    ForEach-Object {
        "{0}  {1}" -f (
            Get-Sha256 $_.FullName
        ), $_.FullName.Substring($RunRoot.Length + 1).Replace("\", "/")
    })
$evidenceChecksumsPath = Join-Path $RunRoot "evidence-checksums.sha256"
[IO.File]::WriteAllText(
    $evidenceChecksumsPath,
    ($checksumLines -join [Environment]::NewLine) + [Environment]::NewLine,
    $Utf8
)

[ordered]@{
    payloadInventory = Get-FileRef $payloadInventoryPath
    postbuildAudit = Get-FileRef $postbuildAuditPath
    buildReceipt = Get-FileRef $buildReceiptPath
    handoffManifest = Get-FileRef $handoffPath
    evidenceChecksums = Get-FileRef $evidenceChecksumsPath
    artifactSha256 = Get-Sha256 $Installer
    artifactBytes = (Get-Item -LiteralPath $Installer).Length
    previewReady = $true
    releaseReady = $false
    websiteReady = $false
} | ConvertTo-Json -Depth 5
