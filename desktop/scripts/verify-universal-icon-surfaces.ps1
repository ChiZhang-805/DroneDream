param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [string]$ProductSourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedSha256,
    [Parameter(Mandatory = $true)]
    [long]$ExpectedBytes,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$outputRootFull = [IO.Path]::GetFullPath($OutputRoot)
$validationRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "DroneDream\handoffs"))
if (-not $outputRootFull.StartsWith(
        $validationRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Icon evidence output must stay under the owned DroneDream handoff root."
}
if ($ProductSourceCommit -cnotmatch "^[0-9a-f]{40}$") {
    throw "ProductSourceCommit must be a full lowercase Git SHA."
}
& git -C $repoRoot cat-file -e "$ProductSourceCommit^{commit}"
if ($LASTEXITCODE -ne 0) {
    throw "ProductSourceCommit is not available in the repository."
}

$actualSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$actualBytes = (Get-Item -LiteralPath $installerPath).Length
if ($actualSha256 -cne $ExpectedSha256 -or $actualBytes -ne $ExpectedBytes) {
    throw "Installer identity does not match the frozen Universal artifact."
}
if ((Split-Path -Leaf $installerPath) -cne "DroneDream-Universal-1.0.0.exe") {
    throw "Unexpected Universal Website handoff filename."
}

$canonicalIcon = Join-Path $repoRoot "brand\generated\universal\windows\icon.ico"
$canonicalPng = Join-Path $repoRoot "brand\generated\universal\windows\32x32.png"
$tauriIcon = Join-Path $repoRoot "desktop\src-tauri\icons\icon.ico"
$canonicalIconSha256 = (Get-FileHash -LiteralPath $canonicalIcon -Algorithm SHA256).Hash.ToLowerInvariant()
$canonicalPngSha256 = (Get-FileHash -LiteralPath $canonicalPng -Algorithm SHA256).Hash.ToLowerInvariant()
$tauriIconSha256 = (Get-FileHash -LiteralPath $tauriIcon -Algorithm SHA256).Hash.ToLowerInvariant()
if ($canonicalIconSha256 -cne "88223fab6c2b0d493aaedab932c04d40def4da58e28f6d670adbfd745a6ca8ba" -or
    $canonicalPngSha256 -cne "acd4ef1fc198bf157c73c26edfb6c2814d46286857b69bfbd857a7328243d19f" -or
    $tauriIconSha256 -cne $canonicalIconSha256) {
    throw "Universal canonical and Tauri icon bytes are not the approved purple asset."
}
foreach ($path in @(
    "brand/generated/universal/windows/icon.ico",
    "desktop/src-tauri/icons/icon.ico"
)) {
    & git -C $repoRoot diff --quiet $ProductSourceCommit -- $path
    if ($LASTEXITCODE -ne 0) {
        throw "Current icon evidence source drifted from the product source: $path"
    }
}

$installRoot = Join-Path $env:LOCALAPPDATA "DroneDream-Universal"
$installedExe = Join-Path $installRoot "drone-dream-desktop.exe"
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DroneDream-Universal"
$productKey = "HKCU:\Software\DroneDream\DroneDream-Universal"
$desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "DroneDream.lnk"
$startMenuShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "DroneDream.lnk"
$shortcuts = @($desktopShortcut, $startMenuShortcut)
$receiptPath = Join-Path $outputRootFull "universal-icon-surfaces-receipt.json"
$screenshotPath = Join-Path $outputRootFull "universal-icon-surfaces.png"
$backupRoot = Join-Path $outputRootFull "shortcut-backup"

function Get-ShortcutRecord {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; exists = $false }
    }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        return [ordered]@{
            path = $Path
            exists = $true
            bytes = (Get-Item -LiteralPath $Path).Length
            sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
            target = [string]$shortcut.TargetPath
            iconLocation = [string]$shortcut.IconLocation
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
}

function Invoke-CheckedProcess {
    param([string]$FilePath, [string[]]$Arguments, [string]$Stage)
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -PassThru -Wait -WindowStyle Hidden
    try {
        if ($process.ExitCode -ne 0) {
            throw "$Stage exited with code $($process.ExitCode)."
        }
    }
    finally {
        $process.Dispose()
    }
}

function Resolve-ShortcutIconSource {
    param([object]$Shortcut)
    $iconLocation = [string]$Shortcut.iconLocation
    if ($iconLocation) {
        $candidate = ($iconLocation -replace ',[0-9-]+$', '').Trim('"')
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    return [IO.Path]::GetFullPath([string]$Shortcut.target)
}

function Save-AssociatedIconPng {
    param([string]$Source, [string]$Destination)
    Add-Type -AssemblyName System.Drawing
    $icon = [Drawing.Icon]::ExtractAssociatedIcon($Source)
    if (-not $icon) { throw "Could not extract an icon from $Source" }
    try {
        $bitmap = $icon.ToBitmap()
        try { $bitmap.Save($Destination, [Drawing.Imaging.ImageFormat]::Png) }
        finally { $bitmap.Dispose() }
    }
    finally { $icon.Dispose() }
}

function Test-ImagePixelEquality {
    param([string]$Reference, [string]$Actual)
    Add-Type -AssemblyName System.Drawing
    $referenceBitmap = [Drawing.Bitmap]::FromFile($Reference)
    $actualBitmap = [Drawing.Bitmap]::FromFile($Actual)
    try {
        if ($referenceBitmap.Width -ne $actualBitmap.Width -or
            $referenceBitmap.Height -ne $actualBitmap.Height) {
            return $false
        }
        for ($y = 0; $y -lt $referenceBitmap.Height; $y++) {
            for ($x = 0; $x -lt $referenceBitmap.Width; $x++) {
                if ($referenceBitmap.GetPixel($x, $y).ToArgb() -ne
                    $actualBitmap.GetPixel($x, $y).ToArgb()) {
                    return $false
                }
            }
        }
        return $true
    }
    finally {
        $referenceBitmap.Dispose()
        $actualBitmap.Dispose()
    }
}

function Save-EvidenceBoard {
    param([object[]]$Surfaces, [string]$Destination)
    Add-Type -AssemblyName System.Drawing
    $bitmap = New-Object Drawing.Bitmap 1120, 280
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $font = New-Object Drawing.Font "Segoe UI", 13
    $smallFont = New-Object Drawing.Font "Consolas", 9
    $brush = [Drawing.Brushes]::Black
    try {
        $graphics.Clear([Drawing.Color]::White)
        $graphics.DrawString("DroneDream Universal - actual icon surfaces", $font, $brush, 24, 18)
        for ($index = 0; $index -lt $Surfaces.Count; $index++) {
            $surface = $Surfaces[$index]
            $x = 24 + ($index * 270)
            $image = [Drawing.Image]::FromFile([string]$surface.pngPath)
            try { $graphics.DrawImage($image, $x + 70, 55, 96, 96) }
            finally { $image.Dispose() }
            $graphics.DrawString([string]$surface.label, $font, $brush, $x, 162)
            $graphics.DrawString(([string]$surface.sourceSha256).Substring(0, 20), $smallFont, $brush, $x, 195)
            $graphics.DrawString("source hash prefix", $smallFont, [Drawing.Brushes]::DimGray, $x, 218)
        }
        $bitmap.Save($Destination, [Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $smallFont.Dispose()
        $font.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$preflight = [ordered]@{
    installRootAbsent = -not (Test-Path -LiteralPath $installRoot)
    uninstallKeyAbsent = -not (Test-Path -LiteralPath $uninstallKey)
    productKeyAbsent = -not (Test-Path -LiteralPath $productKey)
    appProcessAbsent = @(Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue).Count -eq 0
}
if (@($preflight.Values | Where-Object { -not $_ }).Count -ne 0) {
    throw "Universal icon verification requires an absent isolated product state."
}

$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-icon-surfaces-receipt"
    productSourceCommit = $ProductSourceCommit
    executionToolHead = (& git -C $repoRoot rev-parse HEAD).Trim()
    installer = [ordered]@{ path = $installerPath; bytes = $actualBytes; sha256 = $actualSha256 }
    canonicalIcon = [ordered]@{ path = $canonicalIcon; bytes = (Get-Item $canonicalIcon).Length; sha256 = $canonicalIconSha256 }
    canonicalPng = [ordered]@{ path = $canonicalPng; bytes = (Get-Item $canonicalPng).Length; sha256 = $canonicalPngSha256 }
    preflight = $preflight
    counts = [ordered]@{ installer = 0; uninstaller = 0; ownedCleanup = 0; shortcutBackups = 0; shortcutRestores = 0 }
    surfaces = @()
    screenshot = $null
    protectedShortcutParity = $false
    executionAuthorized = [bool]$Execute
    passed = $false
}

if (-not $Execute) {
    $receipt.result = "plan-only"
    $receipt | ConvertTo-Json -Depth 10 | Write-Output
    exit 0
}
if (Test-Path -LiteralPath $outputRootFull) {
    throw "Refusing to replace an existing icon evidence directory: $outputRootFull"
}
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$beforeShortcuts = @($shortcuts | ForEach-Object { Get-ShortcutRecord $_ })
$installed = $false
try {
    for ($index = 0; $index -lt $shortcuts.Count; $index++) {
        $path = $shortcuts[$index]
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $shortcutBaseName = [IO.Path]::GetFileNameWithoutExtension($path)
            $backup = Join-Path $backupRoot ("{0}-{1}.lnk" -f $index, $shortcutBaseName)
            Move-Item -LiteralPath $path -Destination $backup
            $receipt.counts.shortcutBackups++
        }
    }

    Invoke-CheckedProcess -FilePath $installerPath -Arguments @("/S", "/L=1033") -Stage "fresh-with-shortcuts"
    $receipt.counts.installer++
    $installed = $true
    if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf)) {
        throw "Universal application was not installed at the expected path."
    }
    $shortcutRecords = @($shortcuts | ForEach-Object { Get-ShortcutRecord $_ })
    foreach ($shortcut in $shortcutRecords) {
        if (-not $shortcut.exists -or [IO.Path]::GetFullPath([string]$shortcut.target) -cne [IO.Path]::GetFullPath($installedExe)) {
            throw "Universal installer did not create the expected shortcut: $($shortcut.path)"
        }
    }

    $surfaceInputs = @(
        [ordered]@{ label = "Installer EXE"; source = $installerPath },
        [ordered]@{ label = "Installed EXE"; source = $installedExe },
        [ordered]@{ label = "Desktop shortcut"; source = (Resolve-ShortcutIconSource $shortcutRecords[0]) },
        [ordered]@{ label = "Start Menu shortcut"; source = (Resolve-ShortcutIconSource $shortcutRecords[1]) }
    )
    $surfaces = New-Object System.Collections.Generic.List[object]
    for ($index = 0; $index -lt $surfaceInputs.Count; $index++) {
        $surface = $surfaceInputs[$index]
        $png = Join-Path $outputRootFull ("surface-{0}.png" -f $index)
        Save-AssociatedIconPng -Source $surface.source -Destination $png
        if (-not (Test-ImagePixelEquality -Reference $canonicalPng -Actual $png)) {
            throw "The $($surface.label) icon pixels do not match the canonical Universal icon."
        }
        $sourceSha = (Get-FileHash -LiteralPath $surface.source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($index -ge 2 -and ([string]$surface.source).EndsWith(".ico", [StringComparison]::OrdinalIgnoreCase) -and $sourceSha -cne $canonicalIconSha256) {
            throw "Shortcut icon source is not the canonical Universal icon: $($surface.source)"
        }
        $surfaces.Add([ordered]@{
            label = $surface.label
            source = $surface.source
            sourceSha256 = $sourceSha
            pngPath = $png
            pngSha256 = (Get-FileHash -LiteralPath $png -Algorithm SHA256).Hash.ToLowerInvariant()
        })
    }
    Save-EvidenceBoard -Surfaces $surfaces -Destination $screenshotPath
    $receipt.surfaces = @($surfaces)
    $receipt.screenshot = [ordered]@{
        path = $screenshotPath
        bytes = (Get-Item -LiteralPath $screenshotPath).Length
        sha256 = (Get-FileHash -LiteralPath $screenshotPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $receipt.passed = $true
    $receipt.result = "passed"
}
finally {
    if ($installed -and (Test-Path -LiteralPath (Join-Path $installRoot "uninstall.exe") -PathType Leaf)) {
        Invoke-CheckedProcess -FilePath (Join-Path $installRoot "uninstall.exe") -Arguments @("/S", "/L=1033") -Stage "icon-audit-uninstall"
        $receipt.counts.uninstaller++
    }
    if (Test-Path -LiteralPath $productKey) {
        if (@(Get-ChildItem -LiteralPath $productKey -ErrorAction Stop).Count -ne 0) {
            throw "Refusing to remove a Universal product key with child keys."
        }
        Remove-Item -LiteralPath $productKey -Force
        $receipt.counts.ownedCleanup++
    }
    if (Test-Path -LiteralPath $installRoot) {
        $remaining = @(Get-ChildItem -LiteralPath $installRoot -Force)
        if ($remaining.Count -eq 1 -and $remaining[0].Name -ceq "uninstall.exe") {
            Remove-Item -LiteralPath $remaining[0].FullName -Force
            Remove-Item -LiteralPath $installRoot -Force
            $receipt.counts.ownedCleanup++
        }
    }
    for ($index = 0; $index -lt $shortcuts.Count; $index++) {
        $path = $shortcuts[$index]
        $shortcutBaseName = [IO.Path]::GetFileNameWithoutExtension($path)
        $backup = Join-Path $backupRoot ("{0}-{1}.lnk" -f $index, $shortcutBaseName)
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Remove-Item -LiteralPath $path -Force
        }
        if (Test-Path -LiteralPath $backup -PathType Leaf) {
            Move-Item -LiteralPath $backup -Destination $path
            $receipt.counts.shortcutRestores++
        }
    }
    $afterShortcuts = @($shortcuts | ForEach-Object { Get-ShortcutRecord $_ })
    $receipt.protectedShortcutParity = (($beforeShortcuts | ConvertTo-Json -Depth 6 -Compress) -ceq ($afterShortcuts | ConvertTo-Json -Depth 6 -Compress))
    if (-not $receipt.protectedShortcutParity) {
        throw "Protected legacy shortcut state was not restored exactly."
    }
    if ((Test-Path -LiteralPath $uninstallKey) -or
        (Test-Path -LiteralPath $installRoot)) {
        throw "Universal icon audit left installed product state behind."
    }
    $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $receiptPath -Encoding utf8
}

Write-Host "Universal icon surfaces verified from the exact frozen artifact."
