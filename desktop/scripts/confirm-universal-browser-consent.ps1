param(
    [Parameter(Mandatory = $true)][string]$OutputReceipt,
    [ValidateRange(5, 120)][int]$TimeoutSeconds = 90,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$receiptPath = [IO.Path]::GetFullPath($OutputReceipt)

function Write-AtomicJson([string]$Path, $Value) {
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = "$Path.tmp-$PID"
    try {
        [IO.File]::WriteAllText(
            $temporary,
            (($Value | ConvertTo-Json -Depth 12) + "`n"),
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { [IO.File]::Delete($temporary) }
    }
}

$receipt = [ordered]@{
    schemaVersion = 1
    kind = "dronedream-universal-browser-consent-receipt"
    executionAuthorized = [bool]$Execute
    attempted = $false
    clicked = $false
    credentialsRead = $false
    screenshotPersisted = $false
    exactWindowTitle = "DroneDream - Google Chrome"
    exactWindowClass = "Chrome_WidgetWin_1"
}

if (-not $Execute) {
    $receipt.kind = "dronedream-universal-browser-consent-plan"
    Write-AtomicJson $receiptPath $receipt
    Write-Host "Universal browser-consent plan frozen; no window or pointer action ran."
    exit 0
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class DroneDreamConsentNative {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT point);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
"@

function Find-ConsentTarget {
    $desktop = [System.Windows.Automation.AutomationElement]::RootElement
    $windows = $desktop.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    $matches = @($windows | Where-Object {
        $_.Current.Name -ceq $receipt.exactWindowTitle -and
        $_.Current.ClassName -ceq $receipt.exactWindowClass
    })
    if ($matches.Count -ne 1) { return $null }

    $window = $matches[0]
    $process = Get-Process -Id $window.Current.ProcessId -ErrorAction Stop
    if (-not $process.Path -or [IO.Path]::GetFileName($process.Path) -cne "chrome.exe") { return $null }
    $signature = Get-AuthenticodeSignature -FilePath $process.Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) { return $null }

    $rect = New-Object DroneDreamConsentNative+RECT
    if (-not [DroneDreamConsentNative]::GetWindowRect([IntPtr]$window.Current.NativeWindowHandle, [ref]$rect)) {
        return $null
    }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -lt 1000 -or $height -lt 650) { return $null }

    $bitmap = [Drawing.Bitmap]::new($width, $height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, [Drawing.Size]::new($width, $height))
        $minX = $width; $minY = $height; $maxX = -1; $maxY = -1; $count = 0
        $xStart = [int]($width * 0.25); $xEnd = [int]($width * 0.75)
        $yStart = [int]($height * 0.40); $yEnd = [int]($height * 0.78)
        for ($y = $yStart; $y -lt $yEnd; $y += 2) {
            for ($x = $xStart; $x -lt $xEnd; $x += 2) {
                $pixel = $bitmap.GetPixel($x, $y)
                if ($pixel.R -ge 65 -and $pixel.R -le 155 -and
                    $pixel.G -ge 25 -and $pixel.G -le 125 -and
                    $pixel.B -ge 145 -and
                    ($pixel.B - $pixel.R) -ge 35 -and
                    ($pixel.B - $pixel.G) -ge 55) {
                    $count++
                    if ($x -lt $minX) { $minX = $x }
                    if ($x -gt $maxX) { $maxX = $x }
                    if ($y -lt $minY) { $minY = $y }
                    if ($y -gt $maxY) { $maxY = $y }
                }
            }
        }
        if ($count -lt 1200) { return $null }
        $buttonWidth = $maxX - $minX
        $buttonHeight = $maxY - $minY
        if ($buttonWidth -lt 280 -or $buttonWidth -gt 760 -or
            $buttonHeight -lt 35 -or $buttonHeight -gt 100) { return $null }
        return [ordered]@{
            handle = [IntPtr]$window.Current.NativeWindowHandle
            processId = [int]$window.Current.ProcessId
            window = [ordered]@{ left = $rect.Left; top = $rect.Top; width = $width; height = $height }
            target = [ordered]@{
                x = $rect.Left + [int](($minX + $maxX) / 2)
                y = $rect.Top + [int](($minY + $maxY) / 2)
                detectedWidth = $buttonWidth
                detectedHeight = $buttonHeight
                sampledPixels = $count
            }
        }
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
        $process.Dispose()
    }
}

$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$target = $null
while ([DateTime]::UtcNow -lt $deadline -and $null -eq $target) {
    $target = Find-ConsentTarget
    if ($null -eq $target) { Start-Sleep -Milliseconds 500 }
}
if ($null -eq $target) { throw "The exact signed Chrome consent surface was not detected within the bounded window." }

$receipt.attempted = $true
$receipt.processId = $target.processId
$receipt.window = $target.window
$receipt.target = $target.target
Write-AtomicJson $receiptPath $receipt

$original = New-Object DroneDreamConsentNative+POINT
if (-not [DroneDreamConsentNative]::GetCursorPos([ref]$original)) { throw "Unable to preserve the pointer position." }
try {
    if (-not [DroneDreamConsentNative]::SetForegroundWindow($target.handle)) { throw "Unable to focus the exact consent window." }
    Start-Sleep -Milliseconds 300
    if ([DroneDreamConsentNative]::GetForegroundWindow() -ne $target.handle) { throw "The exact consent window did not retain focus." }
    if (-not [DroneDreamConsentNative]::SetCursorPos($target.target.x, $target.target.y)) { throw "Unable to position the pointer over the verified consent target." }
    [DroneDreamConsentNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 80
    [DroneDreamConsentNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    $receipt.clicked = $true
    Write-AtomicJson $receiptPath $receipt
}
finally {
    [DroneDreamConsentNative]::SetCursorPos($original.X, $original.Y) | Out-Null
}

Write-Host "Clicked one verified non-credential Universal consent action and restored the pointer."
