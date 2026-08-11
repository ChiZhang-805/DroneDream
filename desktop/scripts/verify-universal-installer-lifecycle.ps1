param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedSha256,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long]$ExpectedBytes,
    [Parameter(Mandatory = $true)]
    [string]$OutputReceipt,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "edition-installer-lifecycle-contract.ps1")

$productName = "DroneDream-Universal"
$displayName = "DroneDream"
$mainBinaryName = "drone-dream-desktop.exe"
$bundleId = "io.dronedream.desktop.universal"
$installDirectory = Join-Path $env:LOCALAPPDATA $productName
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
$productKey = "HKCU:\Software\DroneDream\$productName"
$baseInstallDirectory = Join-Path $env:LOCALAPPDATA "DroneDream"
$baseUninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream"
$baseProductKey = "HKCU:\Software\DroneDream\DroneDream"
$internalDesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$productName.lnk"
$internalStartMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$productName.lnk"
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "$displayName.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$displayName.lnk"
$baseDesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "DroneDream.lnk"
$baseStartMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "DroneDream.lnk"
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$outputPath = [IO.Path]::GetFullPath($OutputReceipt)
$outputDirectory = Split-Path -Parent $outputPath
$lifecycleEvents = [Collections.Generic.List[object]]::new()
$createdUniversalState = $false

function Get-FileRecord {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; exists = $false; bytes = $null; sha256 = $null }
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $item.FullName
        exists = $true
        bytes = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-RegistryRecord {
    param(
        [string]$Path,
        [string[]]$Names
    )

    $values = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ path = $Path; exists = $false; values = $values }
    }
    $properties = Get-ItemProperty -LiteralPath $Path
    foreach ($name in $Names) {
        $value = $properties.$name
        $values[$name] = if ($null -eq $value) { $null } else { [string]$value }
    }
    return [ordered]@{ path = $Path; exists = $true; values = $values }
}

function Get-ShortcutRecord {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; exists = $false; target = $null; iconLocation = $null }
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        return [ordered]@{
            path = $Path
            exists = $true
            target = $shortcut.TargetPath
            iconLocation = $shortcut.IconLocation
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}

function Get-WebView2Record {
    $appGuid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $keys = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$appGuid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$appGuid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$appGuid"
    )
    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $properties = Get-ItemProperty -LiteralPath $key
        $version = [string]$properties.pv
        $location = [string]$properties.location
        $candidates = @(
            (Join-Path $location "msedgewebview2.exe"),
            (Join-Path $location "$version\msedgewebview2.exe"),
            (Join-Path $location "Application\$version\msedgewebview2.exe")
        )
        $executable = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
        if ($version -and $version -ne "0.0.0.0" -and $executable) {
            return [ordered]@{
                registryPath = $key
                version = $version
                executable = (Resolve-Path -LiteralPath $executable).Path
                executableSha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    throw "A usable WebView2 Runtime was not found; refusing a lifecycle run that could invoke prerequisite repair."
}

function Get-ProtectedState {
    return [ordered]@{
        baseApplication = Get-FileRecord -Path (Join-Path $baseInstallDirectory $mainBinaryName)
        baseUninstaller = Get-FileRecord -Path (Join-Path $baseInstallDirectory "uninstall.exe")
        baseUninstallRegistration = Get-RegistryRecord -Path $baseUninstallKey -Names @(
            "DisplayName", "DisplayVersion", "InstallLocation", "UninstallString", "MainBinaryName"
        )
        baseProductRegistration = Get-RegistryRecord -Path $baseProductKey -Names @(
            "DroneDreamRuntimeInstallMode", "DroneDreamRuntimeDrive", "DroneDreamRuntimeOperationProtocol"
        )
        baseDesktopShortcut = Get-ShortcutRecord -Path $baseDesktopShortcut
        baseStartMenuShortcut = Get-ShortcutRecord -Path $baseStartMenuShortcut
        runtimeRoots = @(
            Get-PSDrive -PSProvider FileSystem | ForEach-Object {
                $candidate = Join-Path $_.Root "DroneDream"
                $item = Get-Item -LiteralPath $candidate -ErrorAction SilentlyContinue
                [ordered]@{
                    path = $candidate
                    exists = ($null -ne $item)
                    lastWriteTimeUtc = if ($null -ne $item) { $item.LastWriteTimeUtc.ToString("O") } else { $null }
                }
            }
        )
        webView2 = Get-WebView2Record
    }
}

function ConvertTo-CanonicalJson {
    param([object]$Value)
    return $Value | ConvertTo-Json -Depth 20 -Compress
}

function Assert-ProtectedStateUnchanged {
    param(
        [object]$Before,
        [string]$Stage
    )

    $after = Get-ProtectedState
    # The Universal display shortcut intentionally uses the mother-brand name.
    # It is protected when a legacy shortcut existed at preflight, but may be
    # created by this isolated install when the path was previously absent.
    # Assert-UniversalInstalled/Uninstalled owns the latter lifecycle check.
    if (-not $Before.baseDesktopShortcut.exists) {
        $after.baseDesktopShortcut = $Before.baseDesktopShortcut
    }
    if (-not $Before.baseStartMenuShortcut.exists) {
        $after.baseStartMenuShortcut = $Before.baseStartMenuShortcut
    }
    if ((ConvertTo-CanonicalJson $Before) -cne (ConvertTo-CanonicalJson $after)) {
        throw "Protected existing DroneDream, Runtime, shortcut, registry, or WebView2 state changed during '$Stage'."
    }
    $script:lifecycleEvents.Add([ordered]@{ stage = $Stage; protectedStateParity = $true })
}

function Wait-ForPathState {
    param(
        [string]$Path,
        [bool]$ShouldExist,
        [int]$TimeoutSeconds = 45
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if ((Test-Path -LiteralPath $Path) -eq $ShouldExist) { return }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for path state exists=${ShouldExist}: $Path"
}

function Invoke-CheckedProcess {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Stage
    )

    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) {
            throw "$Stage exited with code $($process.ExitCode)."
        }
        $script:lifecycleEvents.Add([ordered]@{
            stage = $Stage
            processExitCode = $process.ExitCode
        })
    }
    finally {
        $process.Dispose()
    }
}

function Assert-UniversalInstalled {
    param(
        [bool]$ExpectShortcuts,
        [string]$Stage
    )

    $application = Join-Path $installDirectory $mainBinaryName
    foreach ($required in @(
        $application,
        (Join-Path $installDirectory "uninstall.exe"),
        (Join-Path $installDirectory "distribution\universal-build-profile.v1.json"),
        (Join-Path $installDirectory "distribution\editions\sim.v1.json"),
        (Join-Path $installDirectory "distribution\editions\lab.v1.json"),
        (Join-Path $installDirectory "distribution\editions\field.v1.json"),
        (Join-Path $installDirectory "distribution\desktop\edition-coexistence.v1.json"),
        (Join-Path $installDirectory "distribution\desktop\edition-browser-auth.v1.json"),
        (Join-Path $installDirectory "distribution\desktop\edition-runtime-update-families.v1.json"),
        (Join-Path $installDirectory "distribution\safety\edition-execution-gate.v1.json"),
        (Join-Path $installDirectory "distribution\vehicle-packs\registry.v1.json"),
        (Join-Path $installDirectory "brand\brand-editions.v1.json"),
        (Join-Path $installDirectory "icons\DroneDream.ico"),
        (Join-Path $installDirectory "WebView2Loader.dll")
    )) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "$Stage is missing installed payload: $required"
        }
    }

    $versionInfo = [Diagnostics.FileVersionInfo]::GetVersionInfo($application)
    if ($versionInfo.ProductVersion -notmatch '^1\.0\.0(?:\.0)?$') {
        throw "$Stage installed unexpected product version '$($versionInfo.ProductVersion)'."
    }
    $registration = Get-ItemProperty -LiteralPath $uninstallKey
    $actualRegistration = [ordered]@{
        DisplayName = [string]$registration.DisplayName
        DisplayVersion = [string]$registration.DisplayVersion
        InstallLocation = ([string]$registration.InstallLocation).Trim('"')
        MainBinaryName = [string]$registration.MainBinaryName
    }
    $expectedRegistration = [ordered]@{
        DisplayName = $displayName
        DisplayVersion = "1.0.0"
        InstallLocation = $installDirectory
        MainBinaryName = $mainBinaryName
    }
    $registrationComparison = Compare-DroneDreamUninstallRegistration `
        -Expected $expectedRegistration `
        -Actual $actualRegistration
    $script:lifecycleEvents.Add([ordered]@{
        stage = "$Stage-uninstall-registration"
        internalProductName = $productName
        comparison = $registrationComparison
    })
    if (-not $registrationComparison.passed) {
        throw "$Stage produced an invalid Universal uninstall registration: $($registrationComparison.mismatches -join ', ')."
    }
    $product = Get-ItemProperty -LiteralPath $productKey
    if ([string]$product.DroneDreamRuntimeInstallMode -cne "install-app-only" -or
        -not [string]::IsNullOrEmpty([string]$product.DroneDreamRuntimeDrive) -or
        [int]$product.DroneDreamRuntimeOperationProtocol -ne 2) {
        throw "$Stage did not remain app-only or did not establish protocol 2."
    }

    $registry = Get-Content -LiteralPath (Join-Path $installDirectory "distribution\vehicle-packs\registry.v1.json") -Raw | ConvertFrom-Json
    if ($registry.kind -cne "dronedream-vehicle-pack-registry" -or @($registry.packs).Count -eq 0) {
        throw "$Stage installed an invalid or empty Vehicle Pack registry."
    }
    $validatedCount = @(
        $registry.packs | Where-Object {
            $_.currentValidationTier -in @("sim-validated", "hardware-validated", "validated")
        }
    ).Count
    if ($validatedCount -ne 0) {
        throw "$Stage unexpectedly contains validated hardware Vehicle Packs."
    }
    $profile = Get-Content -LiteralPath (Join-Path $installDirectory "distribution\universal-build-profile.v1.json") -Raw | ConvertFrom-Json
    if ($profile.capabilityAuthority.frontendCanAuthorize -ne $false -or
        $profile.capabilityAuthority.hardwareActionDecision -cne "deny") {
        throw "$Stage does not preserve Universal capability denial."
    }
    $coexistencePath = Join-Path $installDirectory "distribution\desktop\edition-coexistence.v1.json"
    $browserAuthPath = Join-Path $installDirectory "distribution\desktop\edition-browser-auth.v1.json"
    $runtimeFamiliesPath = Join-Path $installDirectory "distribution\desktop\edition-runtime-update-families.v1.json"
    $coexistence = Get-Content -LiteralPath $coexistencePath -Raw | ConvertFrom-Json
    $browserAuth = Get-Content -LiteralPath $browserAuthPath -Raw | ConvertFrom-Json
    $runtimeFamilies = Get-Content -LiteralPath $runtimeFamiliesPath -Raw | ConvertFrom-Json
    $installedCoexistenceSha256 = (
        Get-FileHash -LiteralPath $coexistencePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $coexistenceIdentity = @($coexistence.editions | Where-Object { $_.editionId -ceq "universal" })
    $browserAuthIdentity = @($browserAuth.editions | Where-Object { $_.editionId -ceq "universal" })
    $runtimeFamilyIdentity = @($runtimeFamilies.editions | Where-Object { $_.editionId -ceq "universal" })
    if ($coexistenceIdentity.Count -ne 1 -or
        $browserAuthIdentity.Count -ne 1 -or
        $runtimeFamilyIdentity.Count -ne 1 -or
        $browserAuth.identityBinding.contractSha256 -cne $installedCoexistenceSha256 -or
        $browserAuthIdentity[0].authClientId -cne "dronedream-desktop-universal" -or
        $browserAuthIdentity[0].credentialVaultNamespace -cne "DroneDream/Auth/universal/v1" -or
        $runtimeFamilyIdentity[0].runtimeProfileId -cne "unified-sim-lab" -or
        $runtimeFamilyIdentity[0].updaterMetadataFileName -cne "latest-universal.json") {
        throw "$Stage installed inconsistent Universal coexistence, browser-auth, or Runtime/update contracts."
    }

    $expectedTarget = [IO.Path]::GetFullPath($application)
    foreach ($internalShortcutPath in @($internalDesktopShortcut, $internalStartMenuShortcut)) {
        if (Test-Path -LiteralPath $internalShortcutPath -PathType Leaf) {
            throw "$Stage created a shortcut under the internal product identity: $internalShortcutPath"
        }
    }
    foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
        $shortcut = Get-ShortcutRecord -Path $shortcutPath
        $protectedShortcut = if ($shortcutPath -ceq $desktopShortcut) {
            $protectedBefore.baseDesktopShortcut
        } else {
            $protectedBefore.baseStartMenuShortcut
        }
        if ($ExpectShortcuts) {
            if ($protectedShortcut.exists) {
                if ((ConvertTo-CanonicalJson $shortcut) -cne (ConvertTo-CanonicalJson $protectedShortcut)) {
                    throw "$Stage overwrote a protected legacy shortcut instead of preserving the collision: $shortcutPath"
                }
                $script:lifecycleEvents.Add([ordered]@{
                    stage = "$Stage-shortcut-conflict"
                    path = $shortcutPath
                    outcome = "protected-legacy-shortcut-preserved"
                })
            }
            elseif (-not $shortcut.exists -or [IO.Path]::GetFullPath([string]$shortcut.target) -cne $expectedTarget) {
                throw "$Stage did not create the expected isolated Universal shortcut: $shortcutPath"
            }
        }
        elseif ($protectedShortcut.exists) {
            if ((ConvertTo-CanonicalJson $shortcut) -cne (ConvertTo-CanonicalJson $protectedShortcut)) {
                throw "$Stage changed a protected legacy shortcut despite /NS: $shortcutPath"
            }
        }
        elseif ($shortcut.exists) {
            throw "$Stage created a shortcut despite /NS: $shortcutPath"
        }
    }

    $running = @(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue)
    if ($running.Count -ne 0) {
        throw "$Stage unexpectedly launched the desktop application."
    }
    $script:lifecycleEvents.Add([ordered]@{
        stage = "$Stage-installed-contract"
        installedApplicationSha256 = (Get-FileHash -LiteralPath $application -Algorithm SHA256).Hash.ToLowerInvariant()
        version = $versionInfo.ProductVersion
        appOnly = $true
        validatedVehiclePackCount = 0
        hardwareActionDecision = "deny"
        shortcutsExpected = $ExpectShortcuts
    })
}

function Assert-UniversalUninstalled {
    param([string]$Stage)

    Wait-ForPathState -Path $installDirectory -ShouldExist $false
    if (Test-Path -LiteralPath $uninstallKey) {
        throw "$Stage left the Universal uninstall registration behind."
    }
    foreach ($shortcutPath in @($internalDesktopShortcut, $internalStartMenuShortcut)) {
        if (Test-Path -LiteralPath $shortcutPath) {
            throw "$Stage left the Universal shortcut behind: $shortcutPath"
        }
    }
    foreach ($shortcutPath in @($desktopShortcut, $startMenuShortcut)) {
        $shortcut = Get-ShortcutRecord -Path $shortcutPath
        $protectedShortcut = if ($shortcutPath -ceq $desktopShortcut) {
            $protectedBefore.baseDesktopShortcut
        } else {
            $protectedBefore.baseStartMenuShortcut
        }
        if ((ConvertTo-CanonicalJson $shortcut) -cne (ConvertTo-CanonicalJson $protectedShortcut)) {
            throw "$Stage did not restore the protected display shortcut state: $shortcutPath"
        }
    }
    $script:lifecycleEvents.Add([ordered]@{
        stage = "$Stage-uninstalled-contract"
        applicationRemoved = $true
        uninstallRegistrationRemoved = $true
        shortcutsRemoved = $true
    })
}

function Invoke-UniversalUninstall {
    param([string]$Stage)

    $uninstaller = Join-Path $installDirectory "uninstall.exe"
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
        throw "$Stage cannot find the isolated Universal uninstaller."
    }
    Invoke-CheckedProcess -Executable $uninstaller -Arguments @("/S", "/L=1033") -Stage $Stage
    Assert-UniversalUninstalled -Stage $Stage
}

function Remove-TestCreatedProductRegistration {
    if (-not (Test-Path -LiteralPath $productKey)) { return $false }
    $properties = Get-ItemProperty -LiteralPath $productKey
    $values = [ordered]@{
        "(default)" = [string](Get-Item -LiteralPath $productKey).GetValue("")
    }
    foreach ($property in @($properties.PSObject.Properties | Sort-Object Name)) {
        if ($property.Name -notmatch '^PS' -and $property.Name -ne '(default)') {
            $values[$property.Name] = $property.Value
        }
    }
    $disposition = Get-DroneDreamProductRegistrationDisposition `
        -Values $values `
        -ExpectedInstallDirectory $installDirectory `
        -PreflightProductKeyAbsent $true
    $script:lifecycleEvents.Add([ordered]@{
        stage = "test-created-product-registration"
        disposition = $disposition
    })
    Remove-Item -LiteralPath $productKey -Force
    return $true
}

$actualSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$actualBytes = (Get-Item -LiteralPath $installerPath).Length
if ($actualSha256 -cne $ExpectedSha256 -or $actualBytes -ne $ExpectedBytes) {
    throw "Installer bytes do not match the frozen Universal candidate."
}
if ((Split-Path -Leaf $installerPath) -cne "DroneDream-Universal-1.0.0.exe") {
    throw "Universal lifecycle validation requires the fixed Website handoff filename."
}
if ($installDirectory.StartsWith($baseInstallDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
    $installDirectory -ceq $baseInstallDirectory) {
    throw "Universal install directory overlaps the existing DroneDream installation."
}
if ((Test-Path -LiteralPath $installDirectory) -or
    (Test-Path -LiteralPath $uninstallKey) -or
    (Test-Path -LiteralPath $productKey) -or
    (Test-Path -LiteralPath $internalDesktopShortcut) -or
    (Test-Path -LiteralPath $internalStartMenuShortcut)) {
    throw "Universal lifecycle preflight found pre-existing product state and will not overwrite or clean it."
}
if (@(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -ne 0) {
    throw "DroneDream is currently running. Close it before isolated lifecycle validation; the verifier will never terminate it."
}

$protectedBefore = Get-ProtectedState
$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-installer-lifecycle-receipt"
    productSourceCommit = $ProductSourceCommit
    executionToolHead = (& git -C (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path rev-parse HEAD).Trim()
    installer = [ordered]@{
        absolutePath = $installerPath
        fileName = Split-Path -Leaf $installerPath
        version = "1.0.0"
        bytes = $actualBytes
        sha256 = $actualSha256
        authenticodeStatus = [string](Get-AuthenticodeSignature -LiteralPath $installerPath).Status
    }
    executionAuthorized = [bool]$Execute
    resourceClass = if ($Execute) { "RED" } else { "GREEN" }
    isolation = [ordered]@{
        productName = $productName
        displayName = $displayName
        bundleId = $bundleId
        installDirectory = $installDirectory
        uninstallKey = $uninstallKey
        baseInstallDirectory = $baseInstallDirectory
        runtimeMode = "install-app-only"
        productRegistrationAfterStandardUninstall = "retained-unless-delete-app-data-selected"
        displayShortcutPolicy = "preserve-existing-legacy-or-own-when-absent"
        protectedStateBefore = $protectedBefore
    }
    lifecycle = [ordered]@{
        freshInstall = "not-run"
        inPlaceSameVersionUpdate = "not-run"
        uninstall = "not-run"
        shortcut = "not-run"
        webView2 = "preflight-usable"
        locales = "not-run"
        browserAuth = "not-run-separate-headed-gate"
    }
    events = $lifecycleEvents
    installerLifecycleReady = $false
    releaseReady = $false
}

try {
    if ($Execute) {
        Invoke-CheckedProcess -Executable $installerPath -Arguments @("/S", "/NS", "/L=1033") -Stage "fresh-app-only-no-shortcut"
        $createdUniversalState = $true
        Wait-ForPathState -Path $installDirectory -ShouldExist $true
        Assert-UniversalInstalled -ExpectShortcuts $false -Stage "fresh-app-only-no-shortcut"
        Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "fresh-app-only-no-shortcut"
        $receipt.lifecycle.freshInstall = "pass"
        $receipt.lifecycle.webView2 = "pass-existing-runtime-unchanged"

        Invoke-CheckedProcess -Executable $installerPath -Arguments @("/S", "/NS", "/UPDATE", "/L=1033") -Stage "same-version-in-place-update"
        Assert-UniversalInstalled -ExpectShortcuts $false -Stage "same-version-in-place-update"
        Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "same-version-in-place-update"
        $receipt.lifecycle.inPlaceSameVersionUpdate = "pass"

        Invoke-UniversalUninstall -Stage "post-update-uninstall"
        Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "post-update-uninstall"
        $receipt.lifecycle.uninstall = "pass-first-cycle"

        Invoke-CheckedProcess -Executable $installerPath -Arguments @("/S", "/L=1033") -Stage "fresh-with-shortcuts"
        Wait-ForPathState -Path $installDirectory -ShouldExist $true
        Assert-UniversalInstalled -ExpectShortcuts $true -Stage "fresh-with-shortcuts"
        Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "fresh-with-shortcuts"
        $receipt.lifecycle.shortcut = "pass"

        Invoke-UniversalUninstall -Stage "final-uninstall"
        $registrationRemoved = Remove-TestCreatedProductRegistration
        Assert-ProtectedStateUnchanged -Before $protectedBefore -Stage "final-uninstall"
        $receipt.lifecycle.uninstall = "pass-both-cycles"
        $receipt.isolation.testCreatedProductRegistrationRemoved = $registrationRemoved
        $receipt.installerLifecycleReady = $true
    }
    else {
        $receipt.lifecycle.freshInstall = "plan-only"
        $receipt.lifecycle.inPlaceSameVersionUpdate = "plan-only"
        $receipt.lifecycle.uninstall = "plan-only"
        $receipt.lifecycle.shortcut = "plan-only"
    }
}
catch {
    $receipt.failure = [ordered]@{
        type = $_.Exception.GetType().FullName
        message = $_.Exception.Message
    }
    throw
}
finally {
    $receipt.events = @($lifecycleEvents)
    if ($Execute -and $createdUniversalState -and (Test-Path -LiteralPath (Join-Path $installDirectory "uninstall.exe")) ) {
        try {
            Invoke-UniversalUninstall -Stage "failure-recovery-uninstall"
            [void](Remove-TestCreatedProductRegistration)
            $receipt.failureRecovery = "isolated-uninstaller-succeeded"
        }
        catch {
            $receipt.failureRecovery = "isolated-uninstaller-failed-manual-attention-required"
            $receipt.failureRecoveryError = $_.Exception.Message
        }
    }
    $receipt.completedAt = [DateTime]::UtcNow.ToString("O")
    if (-not (Test-Path -LiteralPath $outputDirectory)) {
        New-Item -ItemType Directory -Path $outputDirectory | Out-Null
    }
    $temporaryReceipt = "$outputPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllText(
            $temporaryReceipt,
            ($receipt | ConvertTo-Json -Depth 30),
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporaryReceipt -Destination $outputPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryReceipt) {
            Remove-Item -LiteralPath $temporaryReceipt -Force
        }
    }
}

if ($Execute) {
    Write-Host "Universal isolated lifecycle verified; separate exact browser-auth validation still gates release readiness."
}
else {
    Write-Host "Universal lifecycle plan verified; no application, Runtime, shortcut, or registry state was changed."
}
