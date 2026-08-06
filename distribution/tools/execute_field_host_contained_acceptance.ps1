param(
    [Parameter(Mandatory = $true)]
    [string]$PlanPath,
    [Parameter(Mandatory = $true)]
    [string]$BaselineSnapshotPath,
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedEvidenceHead
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$FieldProduct = "DroneDream $([char]0x00b7) FIELD"
$FieldBundleId = "io.dronedream.desktop.field"
$FieldIconSha256 = "b90e188679d209009e5eda859665a3582efe1e9129e5f8ecce3c08783b794559"
$ChineseTitle = -join ([char[]](0x771F, 0x673A, 0x5C31, 0x7EEA, 0x72B6, 0x6001))
$ChineseTakeover = -join ([char[]](0x8BF7, 0x6C42, 0x63A5, 0x7BA1))
$ChineseEmergency = -join ([char[]](0x7D27, 0x6025, 0x505C, 0x6B62))
$ArtifactSha256 = "ce3937440e85655d9532097904286eae783f6ed6b25eb0eb94ee113049139317"
$ProductSource = "c7e25b3862fdd491de99f4a0b02cf0f348b94ea3"
$ActualLocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
$ActualRoamingAppData = [Environment]::GetFolderPath("ApplicationData")
$ActualDesktop = [Environment]::GetFolderPath("Desktop")
$ActualStartMenu = Join-Path $ActualRoamingAppData "Microsoft\Windows\Start Menu\Programs"
$OwnedRoot = Join-Path $ActualLocalAppData "DroneDreamCodexTest\field-host-acceptance-c7e25b3"
$InstallRoot = Join-Path $OwnedRoot "install"
$RedirectedLocal = Join-Path $OwnedRoot "env\LocalAppData"
$RedirectedRoaming = Join-Path $OwnedRoot "env\RoamingAppData"
$RedirectedTemp = Join-Path $OwnedRoot "temp"
$FieldStartMenu = Join-Path $ActualStartMenu "$FieldProduct.lnk"
$FieldDesktop = Join-Path $ActualDesktop "$FieldProduct.lnk"
$FieldUninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$FieldProduct"
$FieldProductKey = "HKCU:\Software\DroneDream\$FieldProduct"
$FieldBundleLocal = Join-Path $ActualLocalAppData "io.dronedream.desktop.field"
$FieldBundleRoaming = Join-Path $ActualRoamingAppData "io.dronedream.desktop.field"
$SnapshotTool = Join-Path $PSScriptRoot "capture_field_host_snapshot.ps1"

$Counts = [ordered]@{
    installerExe = 0
    uninstaller = 0
    applicationLaunch = 0
    rebuild = 0
    networkRequest = 0
    deviceEnumeration = 0
    hardwareAction = 0
    simulation = 0
}
$Phases = [System.Collections.Generic.List[object]]::new()
$UnexpectedWrites = [System.Collections.Generic.List[string]]::new()
$ApplicationProcesses = [System.Collections.Generic.List[object]]::new()
$Result = "fail"
$Failure = $null
$InstallObserved = $false
$UninstallObserved = $false

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Json([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $utf8 = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 20), $utf8)
}

function Add-Phase([string]$Id, [string]$State, [object]$Evidence) {
    $path = Join-Path $OutputRoot "phase-$Id.json"
    Write-Json $path $Evidence
    $Phases.Add([ordered]@{
        phaseId = $Id
        state = $State
        evidencePath = $path
        evidenceSha256 = Get-Sha256 $path
    })
}

function Get-CanonicalJson([object]$Value) {
    return $Value | ConvertTo-Json -Depth 20 -Compress
}

function Assert-EqualJson([object]$Expected, [object]$Actual, [string]$Label) {
    if ((Get-CanonicalJson $Expected) -cne (Get-CanonicalJson $Actual)) {
        throw "$Label drifted"
    }
}

function Capture-Snapshot([string]$Name) {
    $path = Join-Path $OutputRoot "$Name.json"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SnapshotTool -OutputPath $path
    if ($LASTEXITCODE -ne 0) { throw "host snapshot failed: $Name" }
    return $path
}

function Assert-Preconditions([object]$Snapshot) {
    if (-not $Snapshot.paths.universalInstall.digest.exists) { throw "Universal install baseline is missing" }
    foreach ($name in @("fieldDefaultInstall", "ownedRoot", "fieldBundleRoaming", "fieldBundleLocal")) {
        if ($Snapshot.paths.$name.digest.exists) { throw "preexisting Field path: $name" }
    }
    foreach ($name in @("fieldUninstall", "fieldProduct")) {
        if ($Snapshot.registry.$name.exists) { throw "preexisting Field registry: $name" }
    }
    foreach ($name in @("fieldStartMenu", "fieldDesktop")) {
        if ($Snapshot.shortcuts.$name.exists) { throw "preexisting Field shortcut: $name" }
    }
    if (@($Snapshot.processes).Count -ne 0) { throw "DroneDream process is already running" }
    if (-not $Snapshot.webView2.healthy) { throw "WebView2 is unhealthy and repair is forbidden" }
    if ($Snapshot.universalRuntimeStatus.operation.exitCode -ne 0) { throw "shared runtime operation is not idle" }
    if ($Snapshot.universalRuntimeStatus.handoff.exitCode -ne 0) { throw "shared installer handoff is not idle" }
}

function Assert-ProtectedState([object]$Baseline, [object]$Current, [string]$Label) {
    Assert-EqualJson $Baseline.paths.universalInstall.digest $Current.paths.universalInstall.digest "$Label Universal install"
    Assert-EqualJson $Baseline.paths.simDefaultInstall.digest $Current.paths.simDefaultInstall.digest "$Label Sim default install"
    Assert-EqualJson $Baseline.paths.labDefaultInstall.digest $Current.paths.labDefaultInstall.digest "$Label Lab default install"
    Assert-EqualJson $Baseline.paths.fieldDefaultInstall.digest $Current.paths.fieldDefaultInstall.digest "$Label Field default install"
    Assert-EqualJson $Baseline.paths.sharedHandoff.controls $Current.paths.sharedHandoff.controls "$Label shared handoff controls"
    Assert-EqualJson $Baseline.registry.universalUninstall $Current.registry.universalUninstall "$Label Universal uninstall registry"
    Assert-EqualJson $Baseline.registry.simUninstall $Current.registry.simUninstall "$Label Sim uninstall registry"
    Assert-EqualJson $Baseline.registry.labUninstall $Current.registry.labUninstall "$Label Lab uninstall registry"
    Assert-EqualJson $Baseline.shortcuts.universalStartMenu $Current.shortcuts.universalStartMenu "$Label Universal Start Menu shortcut"
    Assert-EqualJson $Baseline.shortcuts.universalDesktop $Current.shortcuts.universalDesktop "$Label Universal desktop shortcut"
    Assert-EqualJson $Baseline.shortcuts.simStartMenu $Current.shortcuts.simStartMenu "$Label Sim Start Menu shortcut"
    Assert-EqualJson $Baseline.shortcuts.simDesktop $Current.shortcuts.simDesktop "$Label Sim desktop shortcut"
    Assert-EqualJson $Baseline.shortcuts.labStartMenu $Current.shortcuts.labStartMenu "$Label Lab Start Menu shortcut"
    Assert-EqualJson $Baseline.shortcuts.labDesktop $Current.shortcuts.labDesktop "$Label Lab desktop shortcut"
    Assert-EqualJson $Baseline.runtime $Current.runtime "$Label DroneDream Runtime"
    Assert-EqualJson $Baseline.webView2 $Current.webView2 "$Label WebView2"
}

function Set-OwnedEnvironment {
    $env:LOCALAPPDATA = $RedirectedLocal
    $env:APPDATA = $RedirectedRoaming
    $env:TEMP = $RedirectedTemp
    $env:TMP = $RedirectedTemp
    $env:HTTP_PROXY = "http://127.0.0.1:9"
    $env:HTTPS_PROXY = "http://127.0.0.1:9"
    $env:NO_PROXY = "127.0.0.1,localhost"
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--disable-background-networking --disable-component-update --disable-domain-reliability --disable-sync --metrics-recording-only --no-first-run --proxy-server=127.0.0.1:9 --proxy-bypass-list=<-loopback>"
}

function Restore-Environment([object]$Saved) {
    foreach ($name in $Saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $Saved[$name], "Process")
    }
}

function Invoke-BoundedOwnedProcess([string]$FilePath, [string[]]$Arguments, [string]$Label) {
    $fullPath = [IO.Path]::GetFullPath($FilePath)
    $allowedPaths = @(
        [IO.Path]::GetFullPath($ArtifactPath),
        [IO.Path]::GetFullPath((Join-Path $InstallRoot "uninstall.exe"))
    )
    if ($fullPath -notin $allowedPaths) { throw "refusing unapproved process path: $fullPath" }
    $process = Start-Process -FilePath $fullPath -ArgumentList $Arguments -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(120000)) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        throw "$Label process exceeded the 120 second timeout"
    }
    $process.Refresh()
    return [int]$process.ExitCode
}

function Get-ShortcutState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return [ordered]@{ exists = $false } }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shellApplication = New-Object -ComObject Shell.Application
    $folder = $shellApplication.Namespace((Split-Path -Parent $Path))
    $item = $folder.ParseName((Split-Path -Leaf $Path))
    return [ordered]@{
        exists = $true
        path = $Path
        target = $shortcut.TargetPath
        iconLocation = $shortcut.IconLocation
        appUserModelId = $item.ExtendedProperty("System.AppUserModel.ID")
        sha256 = Get-Sha256 $Path
    }
}

function Assert-FieldShortcut([string]$Path) {
    $state = Get-ShortcutState $Path
    if (-not $state.exists) { throw "Field shortcut is missing: $Path" }
    $expected = Join-Path $InstallRoot "drone-dream-desktop.exe"
    if ([IO.Path]::GetFullPath($state.target) -ine [IO.Path]::GetFullPath($expected)) {
        throw "Field shortcut target drifted: $Path"
    }
    if ($state.iconLocation -notmatch 'DroneDream\.ico') { throw "Field shortcut icon drifted: $Path" }
    if ($state.appUserModelId -ne $FieldBundleId) { throw "Field shortcut AppUserModelID drifted: $Path" }
    $iconPath = Join-Path $InstallRoot "icons\DroneDream.ico"
    if (-not (Test-Path -LiteralPath $iconPath) -or (Get-Sha256 $iconPath) -ne $FieldIconSha256) {
        throw "installed canonical Field ICO drifted"
    }
    return $state
}

function Invoke-Installer([string[]]$Arguments, [string]$PhaseId) {
    if ($Counts.installerExe -ge 2) { throw "installer invocation budget exhausted" }
    Set-OwnedEnvironment
    try {
        $exitCode = Invoke-BoundedOwnedProcess $ArtifactPath $Arguments $PhaseId
        $Counts.installerExe++
        $evidence = [ordered]@{
            arguments = $Arguments
            exitCode = $exitCode
            diagnostic = $null
        }
        $diagnostic = Join-Path $RedirectedTemp "DroneDream\installer-diagnostics.log"
        if (Test-Path -LiteralPath $diagnostic) {
            $copy = Join-Path $OutputRoot "$PhaseId-installer-diagnostics.log"
            Copy-Item -LiteralPath $diagnostic -Destination $copy -Force
            $evidence.diagnostic = [ordered]@{ path = $copy; sha256 = Get-Sha256 $copy; text = Get-Content -LiteralPath $copy -Raw }
        }
        if ($exitCode -ne 0) { throw "$PhaseId installer exit code $exitCode" }
        Add-Phase $PhaseId "pass" $evidence
    } finally {
        Restore-Environment $SavedEnvironment
    }
}

function Wait-MainWindow([int]$Pid) {
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        $process = Get-Process -Id $Pid -ErrorAction SilentlyContinue
        if ($process) {
            $process.Refresh()
            if ($process.MainWindowHandle -ne 0) { return $process }
        }
        Start-Sleep -Milliseconds 250
    }
    throw "Field application window did not appear"
}

function Find-UiElementByName([System.Windows.Automation.AutomationElement]$Root, [string]$Name) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        $Name
    )
    return $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Capture-Window([System.Windows.Automation.AutomationElement]$Window, [string]$Path) {
    Add-Type -AssemblyName System.Drawing
    $rect = $Window.Current.BoundingRectangle
    $width = [Math]::Max(1, [int][Math]::Ceiling($rect.Width))
    $height = [Math]::Max(1, [int][Math]::Ceiling($rect.Height))
    $bitmap = New-Object Drawing.Bitmap $width, $height
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen([int]$rect.X, [int]$rect.Y, 0, 0, $bitmap.Size)
        $bitmap.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Get-ProcessTreeIds([int]$RootPid) {
    $ids = [System.Collections.Generic.HashSet[int]]::new()
    [void]$ids.Add($RootPid)
    do {
        $before = $ids.Count
        foreach ($process in Get-CimInstance Win32_Process) {
            if ($ids.Contains([int]$process.ParentProcessId)) { [void]$ids.Add([int]$process.ProcessId) }
        }
    } while ($ids.Count -ne $before)
    return @($ids)
}

function Get-ExternalConnections([int]$RootPid) {
    $ids = Get-ProcessTreeIds $RootPid
    $connections = @()
    foreach ($id in $ids) {
        foreach ($connection in Get-NetTCPConnection -OwningProcess $id -ErrorAction SilentlyContinue) {
            $remote = [string]$connection.RemoteAddress
            if ($remote -and $remote -notin @("0.0.0.0", "::", "::1") -and -not $remote.StartsWith("127.")) {
                $connections += [ordered]@{
                    processId = $id
                    state = [string]$connection.State
                    remoteAddress = $remote
                    remotePort = $connection.RemotePort
                }
            }
        }
    }
    return $connections
}

function Stop-FieldApplication([object]$Process) {
    if ($Process.HasExited) { return }
    [void]$Process.CloseMainWindow()
    if (-not $Process.WaitForExit(5000)) {
        $path = $Process.Path
        if ([IO.Path]::GetFullPath($path) -ine [IO.Path]::GetFullPath((Join-Path $InstallRoot "drone-dream-desktop.exe"))) {
            throw "refusing to stop a process outside the owned install root"
        }
        Stop-Process -Id $Process.Id -Force
        $Process.WaitForExit()
    }
}

function Invoke-FieldUi([string]$PhaseId, [string]$ExpectedTitle, [bool]$SwitchToChinese, [bool]$ViaShortcut) {
    if ($Counts.applicationLaunch -ge 2) { throw "application launch budget exhausted" }
    Set-OwnedEnvironment
    try {
        if ($ViaShortcut) {
            $shortcut = Assert-FieldShortcut $FieldStartMenu
            Start-Process -FilePath $FieldStartMenu | Out-Null
            $process = $null
            for ($attempt = 0; $attempt -lt 40 -and -not $process; $attempt++) {
                $process = Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue |
                    Where-Object { $_.Path -and ([IO.Path]::GetFullPath($_.Path) -ieq [IO.Path]::GetFullPath($shortcut.target)) } |
                    Select-Object -First 1
                if (-not $process) { Start-Sleep -Milliseconds 250 }
            }
            if (-not $process) { throw "shortcut did not launch the owned Field application" }
        } else {
            $process = Start-Process -FilePath (Join-Path $InstallRoot "drone-dream-desktop.exe") -PassThru
        }
        $Counts.applicationLaunch++
        $process = Wait-MainWindow $process.Id
        $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
        if ($window.Current.Name -ne $FieldProduct) { throw "Field window identity drifted" }
        if (-not (Find-UiElementByName $window $ExpectedTitle)) { throw "expected UI title is missing: $ExpectedTitle" }
        $takeover = Find-UiElementByName $window $(if ($ExpectedTitle -eq "Field readiness") { "Request takeover" } else { $ChineseTakeover })
        $emergency = Find-UiElementByName $window $(if ($ExpectedTitle -eq "Field readiness") { "Emergency stop" } else { $ChineseEmergency })
        if (-not $takeover -or $takeover.Current.IsEnabled) { throw "takeover control is not disabled" }
        if (-not $emergency -or $emergency.Current.IsEnabled) { throw "emergency control is not disabled" }
        $screenshot = Join-Path $OutputRoot "$PhaseId.png"
        Capture-Window $window $screenshot
        if ($SwitchToChinese) {
            $language = Find-UiElementByName $window "Language"
            if (-not $language) { throw "English language button is missing" }
            $pattern = $language.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $pattern.Invoke()
            Start-Sleep -Seconds 1
            if (-not (Find-UiElementByName $window $ChineseTitle)) { throw "Chinese Field title is missing after locale switch" }
        }
        Start-Sleep -Seconds 2
        $external = @(Get-ExternalConnections $process.Id)
        if ($external.Count -ne 0) {
            $Counts.networkRequest += $external.Count
            throw "Field process tree created external network connections"
        }
        $ApplicationProcesses.Add([ordered]@{ phaseId = $PhaseId; processId = $process.Id; executable = $process.Path })
        Add-Phase $PhaseId "pass" ([ordered]@{
            expectedTitle = $ExpectedTitle
            viaShortcut = $ViaShortcut
            takeoverDisabled = $true
            emergencyDisabled = $true
            windowName = $window.Current.Name
            appUserModelId = $FieldBundleId
            installedIconSha256 = $FieldIconSha256
            externalConnections = $external
            screenshotPath = $screenshot
            screenshotSha256 = Get-Sha256 $screenshot
        })
        Stop-FieldApplication $process
    } finally {
        Restore-Environment $SavedEnvironment
    }
}

function Remove-ProvenNewPath([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd("\")
    $owned = [IO.Path]::GetFullPath($OwnedRoot).TrimEnd("\")
    $allowedExact = @(
        [IO.Path]::GetFullPath($FieldBundleLocal).TrimEnd("\"),
        [IO.Path]::GetFullPath($FieldBundleRoaming).TrimEnd("\")
    )
    if (-not $full.StartsWith($owned + "\", [StringComparison]::OrdinalIgnoreCase) -and $full -ine $owned -and $full -notin $allowedExact) {
        throw "refusing cleanup outside proven-new paths: $full"
    }
    Remove-Item -LiteralPath $full -Recurse -Force
}

function Remove-ProvenNewRegistry {
    if (Test-Path -LiteralPath $FieldUninstallKey) {
        $item = Get-ItemProperty -LiteralPath $FieldUninstallKey
        if ([string]$item.DisplayName -ne $FieldProduct) { throw "Field uninstall key ownership proof failed" }
        Remove-Item -LiteralPath $FieldUninstallKey -Recurse -Force
    }
    if (Test-Path -LiteralPath $FieldProductKey) {
        Remove-Item -LiteralPath $FieldProductKey -Recurse -Force
    }
}

function Remove-ProvenNewShortcut([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $state = Get-ShortcutState $Path
    if (-not $state.target -or -not ([IO.Path]::GetFullPath($state.target).StartsWith([IO.Path]::GetFullPath($OwnedRoot), [StringComparison]::OrdinalIgnoreCase))) {
        throw "shortcut cleanup ownership proof failed: $Path"
    }
    Remove-Item -LiteralPath $Path -Force
}

$SavedEnvironment = [ordered]@{}
foreach ($name in @("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS")) {
    $SavedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes

    $plan = [IO.File]::ReadAllText($PlanPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $baseline = [IO.File]::ReadAllText($BaselineSnapshotPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $head = (git rev-parse HEAD).Trim()
    if ($head -ne $ExpectedEvidenceHead) { throw "evidence HEAD drifted: $head" }
    if (@(git status --porcelain).Count -ne 0) { throw "worktree is not clean" }
    if ($plan.state -ne "yellow-host-contained-requestable" -or @($plan.blockers).Count -ne 0) { throw "plan is not requestable" }
    if ($plan.artifact.productSourceCommit -ne $ProductSource) { throw "product source drifted" }
    if ((Get-Item -LiteralPath $ArtifactPath).Length -ne 11267482 -or (Get-Sha256 $ArtifactPath) -ne $ArtifactSha256) { throw "artifact identity drifted" }
    $os = Get-CimInstance Win32_OperatingSystem
    $memoryUsedPercent = (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize) * 100
    $memoryAvailableGiB = $os.FreePhysicalMemory * 1KB / 1GB
    if ($memoryUsedPercent -ge 80 -or $memoryAvailableGiB -lt 3) { throw "resource serialization gate is not GREEN" }
    $heavy = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'cargo|rustc|tauri|makensis|gazebo|px4' })
    if ($heavy.Count -ne 0) { throw "conflicting heavy process is active" }
    if (Test-Path -LiteralPath $OutputRoot) { throw "execution output root already exists" }
    New-Item -ItemType Directory -Path $OutputRoot | Out-Null

    $preflightPath = Capture-Snapshot "before-snapshot"
    $before = [IO.File]::ReadAllText($preflightPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    Assert-Preconditions $before
    Assert-ProtectedState $baseline $before "preflight"
    Add-Phase "host-baseline" "pass" ([ordered]@{
        sourceHead = $head
        planSha256 = Get-Sha256 $PlanPath
        artifactSha256 = Get-Sha256 $ArtifactPath
        beforeSnapshotPath = $preflightPath
        beforeSnapshotSha256 = Get-Sha256 $preflightPath
    })

    foreach ($path in @($RedirectedLocal, $RedirectedRoaming, $RedirectedTemp, $InstallRoot)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
    New-Item -Path $FieldProductKey -Force | Out-Null
    New-ItemProperty -LiteralPath $FieldProductKey -Name "Installer Language" -PropertyType String -Value "1033" -Force | Out-Null

    Invoke-Installer @("/S", "/D=$InstallRoot") "fresh-install-en"
    $InstallObserved = Test-Path -LiteralPath (Join-Path $InstallRoot "drone-dream-desktop.exe")
    if (-not $InstallObserved) { throw "fresh install did not create the owned executable" }
    $freshRegistry = Get-ItemProperty -LiteralPath $FieldUninstallKey
    if ([string]$freshRegistry.DisplayName -ne $FieldProduct) { throw "fresh install product identity drifted" }
    if ([string]$freshRegistry.InstallLocation -notmatch [regex]::Escape($InstallRoot)) { throw "fresh install root drifted" }
    $freshStartMenu = Assert-FieldShortcut $FieldStartMenu
    $freshDesktop = Assert-FieldShortcut $FieldDesktop
    Invoke-FieldUi "fresh-launch-en" "Field readiness" $true $false

    New-ItemProperty -LiteralPath $FieldProductKey -Name "Installer Language" -PropertyType String -Value "2052" -Force | Out-Null
    Invoke-Installer @("/S", "/UPDATE", "/D=$InstallRoot") "same-version-overlay-zh-CN"
    $overlayStartMenu = Assert-FieldShortcut $FieldStartMenu
    $overlayDesktop = Assert-FieldShortcut $FieldDesktop
    if ($overlayStartMenu.target -ine $freshStartMenu.target -or $overlayDesktop.target -ine $freshDesktop.target) { throw "overlay shortcut target drifted" }
    Invoke-FieldUi "shortcut-launch-zh-CN" $ChineseTitle $false $true

    Set-OwnedEnvironment
    try {
        $uninstaller = Join-Path $InstallRoot "uninstall.exe"
        if (-not (Test-Path -LiteralPath $uninstaller)) { throw "uninstaller is missing" }
        $uninstallExitCode = Invoke-BoundedOwnedProcess $uninstaller @("/S") "uninstall"
        $Counts.uninstaller++
        if ($uninstallExitCode -ne 0) { throw "uninstaller exit code $uninstallExitCode" }
        $UninstallObserved = $true
        Add-Phase "uninstall" "pass" ([ordered]@{ exitCode = $uninstallExitCode })
    } finally {
        Restore-Environment $SavedEnvironment
    }

    Remove-ProvenNewShortcut $FieldStartMenu
    Remove-ProvenNewShortcut $FieldDesktop
    Remove-ProvenNewRegistry
    Remove-ProvenNewPath $FieldBundleLocal
    Remove-ProvenNewPath $FieldBundleRoaming
    Remove-ProvenNewPath $OwnedRoot
    Add-Phase "owned-residue-audit" "pass" ([ordered]@{
        installRootAbsent = -not (Test-Path -LiteralPath $InstallRoot)
        fieldRegistryAbsent = -not (Test-Path -LiteralPath $FieldUninstallKey) -and -not (Test-Path -LiteralPath $FieldProductKey)
        fieldShortcutsAbsent = -not (Test-Path -LiteralPath $FieldStartMenu) -and -not (Test-Path -LiteralPath $FieldDesktop)
        ownedRootAbsent = -not (Test-Path -LiteralPath $OwnedRoot)
    })

    $afterPath = Capture-Snapshot "after-snapshot"
    $after = [IO.File]::ReadAllText($afterPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
    Assert-ProtectedState $before $after "final"
    Assert-Preconditions $after
    Add-Phase "protected-state-rollback-audit" "pass" ([ordered]@{
        afterSnapshotPath = $afterPath
        afterSnapshotSha256 = Get-Sha256 $afterPath
        protectedStateMatched = $true
    })
    $Result = "pass"
} catch {
    $Failure = $_.Exception.Message
} finally {
    Restore-Environment $SavedEnvironment
    foreach ($process in Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue) {
        try {
            if ($process.Path -and [IO.Path]::GetFullPath($process.Path).StartsWith([IO.Path]::GetFullPath($OwnedRoot), [StringComparison]::OrdinalIgnoreCase)) {
                Stop-FieldApplication $process
            }
        } catch {
            $UnexpectedWrites.Add("cleanup-process:$($_.Exception.Message)")
        }
    }
    if ($Result -ne "pass" -and (Test-Path -LiteralPath $OwnedRoot)) {
        try {
            $uninstaller = Join-Path $InstallRoot "uninstall.exe"
            if ((Test-Path -LiteralPath $uninstaller) -and $Counts.uninstaller -lt 1) {
                Set-OwnedEnvironment
                try {
                    $cleanupExitCode = Invoke-BoundedOwnedProcess $uninstaller @("/S") "cleanup-uninstall"
                    $Counts.uninstaller++
                    if ($cleanupExitCode -ne 0) { throw "cleanup uninstaller exit code $cleanupExitCode" }
                } finally {
                    Restore-Environment $SavedEnvironment
                }
            }
            Remove-ProvenNewShortcut $FieldStartMenu
            Remove-ProvenNewShortcut $FieldDesktop
            Remove-ProvenNewRegistry
            Remove-ProvenNewPath $FieldBundleLocal
            Remove-ProvenNewPath $FieldBundleRoaming
            Remove-ProvenNewPath $OwnedRoot
        } catch {
            $UnexpectedWrites.Add("cleanup-owned-state:$($_.Exception.Message)")
        }
    }
    if (Test-Path -LiteralPath $OutputRoot) {
        $observation = [ordered]@{
            schemaVersion = 1
            kind = "dronedream-field-host-contained-execution-observation"
            editionId = "field"
            result = $Result
            failure = $Failure
            productSourceCommit = $ProductSource
            evidenceHead = $ExpectedEvidenceHead
            artifact = [ordered]@{
                path = $ArtifactPath
                bytes = 11267482
                sha256 = $ArtifactSha256
                authenticodeStatus = "NotSigned"
            }
            invocationCounts = $Counts
            phases = $Phases
            applicationProcesses = $ApplicationProcesses
            installObserved = $InstallObserved
            uninstallObserved = $UninstallObserved
            unexpectedWrites = $UnexpectedWrites
            protectedStateMatched = $Result -eq "pass"
            websiteReady = $false
        }
        Write-Json (Join-Path $OutputRoot "execution-observation.json") $observation
    }
}

if ($Result -ne "pass") {
    Write-Error "Field host-contained acceptance failed: $Failure"
    exit 2
}
exit 0
