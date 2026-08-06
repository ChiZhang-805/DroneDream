param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$productName = "DroneDream $([char]0x00b7) FIELD"
$labProductName = "DroneDream $([char]0x00b7) LAB"
$fieldBundleId = "io.dronedream.desktop.field"
$local = [Environment]::GetFolderPath("LocalApplicationData")
$roaming = [Environment]::GetFolderPath("ApplicationData")
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $roaming "Microsoft\Windows\Start Menu\Programs"
$ownedRoot = Join-Path $local "DroneDreamCodexTest\field-host-acceptance-c7e25b3"

function Get-TreeDigest([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ exists = $false; fileCount = 0; bytes = 0; sha256 = $null }
    }
    $root = (Resolve-Path -LiteralPath $Path).Path
    $lines = [System.Collections.Generic.List[string]]::new()
    $bytes = [int64]0
    $files = @(Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction Stop | Sort-Object FullName)
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($root.Length).TrimStart("\")
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $lines.Add("$relative`t$($file.Length)`t$hash")
        $bytes += $file.Length
    }
    $canonical = [string]::Join("`n", $lines)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))
        $sha = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
    } finally {
        $hasher.Dispose()
    }
    return [ordered]@{ exists = $true; fileCount = $files.Count; bytes = $bytes; sha256 = $sha }
}

function Get-RegistryState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ exists = $false; values = @{} }
    }
    $values = [ordered]@{}
    $item = Get-ItemProperty -LiteralPath $Path
    foreach ($property in $item.PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' } | Sort-Object Name) {
        $values[$property.Name] = $property.Value
    }
    return [ordered]@{ exists = $true; values = $values }
}

function Get-ShortcutState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ exists = $false; target = $null; sha256 = $null }
    }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    return [ordered]@{
        exists = $true
        target = $shortcut.TargetPath
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-WebView2State {
    $guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    $keys = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$guid",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$guid"
    )
    foreach ($key in $keys) {
        if (-not (Test-Path -LiteralPath $key)) { continue }
        $item = Get-ItemProperty -LiteralPath $key
        $version = [string]$item.pv
        $location = [string]$item.location
        $candidates = @(
            (Join-Path $location "msedgewebview2.exe"),
            (Join-Path $location "$version\msedgewebview2.exe"),
            (Join-Path $location "Application\$version\msedgewebview2.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Microsoft\EdgeWebView\Application\$version\msedgewebview2.exe"),
            (Join-Path $env:ProgramFiles "Microsoft\EdgeWebView\Application\$version\msedgewebview2.exe"),
            (Join-Path $local "Microsoft\EdgeWebView\Application\$version\msedgewebview2.exe")
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        if ($version -and $version -ne "0.0.0.0" -and $candidates.Count -gt 0) {
            $binary = (Resolve-Path -LiteralPath $candidates[0]).Path
            return [ordered]@{
                healthy = $true
                registryKey = $key
                version = $version
                binary = $binary
                binarySha256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    return [ordered]@{ healthy = $false; registryKey = $null; version = $null; binary = $null; binarySha256 = $null }
}

function Get-ControlFileState([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return [ordered]@{ exists = $false; bytes = $null; sha256 = $null }
    }
    $file = Get-Item -LiteralPath $Path
    return [ordered]@{
        exists = $true
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-EarlyCommandStatus([string]$Executable, [string]$Argument) {
    if (-not (Test-Path -LiteralPath $Executable)) {
        return [ordered]@{ available = $false; exitCode = $null }
    }
    $process = Start-Process -FilePath $Executable -ArgumentList @($Argument) -WindowStyle Hidden -Wait -PassThru
    return [ordered]@{ available = $true; exitCode = $process.ExitCode }
}

$runtimeRoot = "E:\DroneDream"
$sharedHandoffRoot = Join-Path $local "io.dronedream.desktop"
$universalExecutable = Join-Path $local "DroneDream\drone-dream-desktop.exe"
$runtimeTopLevel = @()
if (Test-Path -LiteralPath $runtimeRoot) {
    $runtimeTopLevel = @(Get-ChildItem -LiteralPath $runtimeRoot -Force | Sort-Object Name | ForEach-Object {
        [ordered]@{
            name = $_.Name
            kind = if ($_.PSIsContainer) { "directory" } else { "file" }
            length = if ($_.PSIsContainer) { $null } else { $_.Length }
            lastWriteTimeUtc = $_.LastWriteTimeUtc.ToString("o")
        }
    })
}

$snapshot = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-field-host-contained-host-snapshot"
    capturedAtUtc = [DateTime]::UtcNow.ToString("o")
    host = [ordered]@{
        computerName = $env:COMPUTERNAME
        userName = $env:USERNAME
        os = (Get-CimInstance Win32_OperatingSystem).Caption
        build = [Environment]::OSVersion.Version.ToString()
    }
    paths = [ordered]@{
        universalInstall = [ordered]@{ path = (Join-Path $local "DroneDream"); digest = Get-TreeDigest (Join-Path $local "DroneDream") }
        labDefaultInstall = [ordered]@{ path = (Join-Path $local $labProductName); digest = Get-TreeDigest (Join-Path $local $labProductName) }
        fieldDefaultInstall = [ordered]@{ path = (Join-Path $local $productName); digest = Get-TreeDigest (Join-Path $local $productName) }
        ownedRoot = [ordered]@{ path = $ownedRoot; digest = Get-TreeDigest $ownedRoot }
        sharedHandoff = [ordered]@{
            path = $sharedHandoffRoot
            digest = Get-TreeDigest $sharedHandoffRoot
            controls = [ordered]@{
                receipt = Get-ControlFileState (Join-Path $sharedHandoffRoot "installer-runtime-handoff-v1.bin")
                terminal = Get-ControlFileState (Join-Path $sharedHandoffRoot "installer-runtime-handoff-v1.terminal.bin")
                quiesce = Get-ControlFileState (Join-Path $sharedHandoffRoot "runtime-quiesce-v1.bin")
                legacyLock = Get-ControlFileState (Join-Path $sharedHandoffRoot "runtime-operation-v1.lock")
            }
        }
        fieldBundleRoaming = [ordered]@{ path = (Join-Path $roaming $fieldBundleId); digest = Get-TreeDigest (Join-Path $roaming $fieldBundleId) }
        fieldBundleLocal = [ordered]@{ path = (Join-Path $local $fieldBundleId); digest = Get-TreeDigest (Join-Path $local $fieldBundleId) }
    }
    registry = [ordered]@{
        universalUninstall = Get-RegistryState "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream"
        labUninstall = Get-RegistryState "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$labProductName"
        fieldUninstall = Get-RegistryState "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$productName"
        fieldProduct = Get-RegistryState "HKCU:\Software\DroneDream\$productName"
        fieldAutorun = Get-RegistryState "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    }
    shortcuts = [ordered]@{
        universalStartMenu = Get-ShortcutState (Join-Path $startMenu "DroneDream.lnk")
        universalDesktop = Get-ShortcutState (Join-Path $desktop "DroneDream.lnk")
        labStartMenu = Get-ShortcutState (Join-Path $startMenu "$labProductName.lnk")
        labDesktop = Get-ShortcutState (Join-Path $desktop "$labProductName.lnk")
        fieldStartMenu = Get-ShortcutState (Join-Path $startMenu "$productName.lnk")
        fieldDesktop = Get-ShortcutState (Join-Path $desktop "$productName.lnk")
    }
    runtime = [ordered]@{
        root = $runtimeRoot
        exists = Test-Path -LiteralPath $runtimeRoot
        topLevel = $runtimeTopLevel
    }
    webView2 = Get-WebView2State
    universalRuntimeStatus = [ordered]@{
        operation = Get-EarlyCommandStatus $universalExecutable "--runtime-operation-status"
        handoff = Get-EarlyCommandStatus $universalExecutable "--installer-handoff-status"
    }
    processes = @(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue | ForEach-Object {
        [ordered]@{ id = $_.Id; path = $_.Path }
    })
}

$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($OutputPath, ($snapshot | ConvertTo-Json -Depth 12), $utf8)
