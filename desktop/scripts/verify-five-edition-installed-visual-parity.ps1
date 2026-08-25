param(
    [ValidateSet("universal", "sim", "lab", "field", "autonomy")]
    [string[]]$EditionIds = @("universal", "sim", "lab", "field", "autonomy"),
    [string]$OutputRoot = (Join-Path $PSScriptRoot "..\..\artifacts\desktop-visual-parity"),
    [string]$BuildOutputRoot = "",
    [string]$ApplicationMapPath = "",
    [ValidateRange(5, 120)]
    [int]$WindowTimeoutSeconds = 30,
    [ValidateRange(100, 5000)]
    [int]$StateSettleMilliseconds = 750,
    [ValidateRange(49152, 65500)]
    [int]$CdpBasePort = 49340,
    [ValidateSet("en", "zh-CN")]
    [string[]]$Locales = @("en", "zh-CN"),
    [switch]$KeepLaunchedApplications,
    [switch]$SelfTest,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$coexistenceContractPath = Join-Path $repoRoot "distribution\desktop\edition-coexistence.v1.json"
$surfaceDriverPath = Join-Path $repoRoot "frontend\scripts\drive-installed-five-edition-surface.mjs"
$allEditionIds = @("universal", "sim", "lab", "field", "autonomy")
$selectedEditionIds = @($allEditionIds | Where-Object { $_ -in $EditionIds })

if ($EditionIds.Count -ne @($EditionIds | Select-Object -Unique).Count -or
    $selectedEditionIds.Count -ne $EditionIds.Count) {
    throw "EditionIds must be unique and use the canonical five-edition identifiers."
}
if ($Locales.Count -ne @($Locales | Select-Object -Unique).Count) {
    throw "Locales must be unique."
}
if ($env:OS -cne "Windows_NT") {
    throw "Exact installed-window capture is supported only on Windows."
}

Add-Type -AssemblyName System.Drawing

if ($null -eq ("DroneDreamInstalledVisualNative" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class DroneDreamInstalledVisualNative
{
    public const int SW_HIDE = 0;
    public const int SW_SHOWNORMAL = 1;
    public const int SW_SHOWMINIMIZED = 2;
    public const int SW_SHOWMAXIMIZED = 3;
    public const int SW_RESTORE = 9;
    public const int SW_MAXIMIZE = 3;
    public const int SW_MINIMIZE = 6;
    public const uint MONITOR_DEFAULTTONEAREST = 2;
    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_NOZORDER = 0x0004;
    public const uint SWP_NOACTIVATE = 0x0010;
    public const uint SWP_FRAMECHANGED = 0x0020;
    public const uint SWP_SHOWWINDOW = 0x0040;
    public const int DWMWA_EXTENDED_FRAME_BOUNDS = 9;

    public static readonly IntPtr HWND_TOP = new IntPtr(0);
    public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    public static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
    public static readonly IntPtr DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = new IntPtr(-4);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct MONITORINFO
    {
        public int cbSize;
        public RECT rcMonitor;
        public RECT rcWork;
        public uint dwFlags;
    }

    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetProcessDpiAwarenessContext(IntPtr value);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int GetWindowTextLengthW(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder text, int maximumCount);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsZoomed(IntPtr hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool ShowWindow(IntPtr hWnd, int command);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetWindowPos(
        IntPtr hWnd,
        IntPtr insertAfter,
        int x,
        int y,
        int width,
        int height,
        uint flags
    );

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern uint GetDpiForWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr MonitorFromWindow(IntPtr hWnd, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetMonitorInfoW(IntPtr monitor, ref MONITORINFO monitorInfo);

    [DllImport("dwmapi.dll", SetLastError = true)]
    public static extern int DwmGetWindowAttribute(
        IntPtr hWnd,
        int attribute,
        out RECT value,
        int valueSize
    );

    [DllImport("dwmapi.dll")]
    public static extern int DwmFlush();

    public static IntPtr[] GetVisibleTopLevelWindows(uint processId)
    {
        List<IntPtr> windows = new List<IntPtr>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            uint candidateProcessId;
            GetWindowThreadProcessId(hWnd, out candidateProcessId);
            if (candidateProcessId == processId && IsWindowVisible(hWnd))
            {
                windows.Add(hWnd);
            }
            return true;
        }, IntPtr.Zero);
        return windows.ToArray();
    }

    public static string GetTitle(IntPtr hWnd)
    {
        int length = GetWindowTextLengthW(hWnd);
        StringBuilder value = new StringBuilder(Math.Max(1, length + 1));
        GetWindowTextW(hWnd, value, value.Capacity);
        return value.ToString();
    }
}
'@
}

function Assert-Condition {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    if (-not $Condition) { throw $Message }
}

function Convert-NativeRect {
    param([DroneDreamInstalledVisualNative+RECT]$Rect)
    return [ordered]@{
        left = [int]$Rect.Left
        top = [int]$Rect.Top
        right = [int]$Rect.Right
        bottom = [int]$Rect.Bottom
        width = [int]($Rect.Right - $Rect.Left)
        height = [int]($Rect.Bottom - $Rect.Top)
    }
}

function Get-RectIntersection {
    param(
        [Parameter(Mandatory = $true)]$First,
        [Parameter(Mandatory = $true)]$Second
    )
    $left = [Math]::Max([int]$First.left, [int]$Second.left)
    $top = [Math]::Max([int]$First.top, [int]$Second.top)
    $right = [Math]::Min([int]$First.right, [int]$Second.right)
    $bottom = [Math]::Min([int]$First.bottom, [int]$Second.bottom)
    Assert-Condition ($right -gt $left -and $bottom -gt $top) "Window and monitor work area do not intersect."
    return [ordered]@{
        left = $left
        top = $top
        right = $right
        bottom = $bottom
        width = $right - $left
        height = $bottom - $top
    }
}

function Get-NativeWindowRect {
    param([IntPtr]$Handle)
    $native = New-Object DroneDreamInstalledVisualNative+RECT
    Assert-Condition (
        [DroneDreamInstalledVisualNative]::GetWindowRect($Handle, [ref]$native)
    ) "GetWindowRect failed for HWND $Handle."
    return Convert-NativeRect $native
}

function Get-NativeClientRect {
    param([IntPtr]$Handle)
    $native = New-Object DroneDreamInstalledVisualNative+RECT
    Assert-Condition (
        [DroneDreamInstalledVisualNative]::GetClientRect($Handle, [ref]$native)
    ) "GetClientRect failed for HWND $Handle."
    return Convert-NativeRect $native
}

function Get-DwmVisibleFrameRect {
    param([IntPtr]$Handle)
    $native = New-Object DroneDreamInstalledVisualNative+RECT
    $size = [Runtime.InteropServices.Marshal]::SizeOf([type][DroneDreamInstalledVisualNative+RECT])
    $result = [DroneDreamInstalledVisualNative]::DwmGetWindowAttribute(
        $Handle,
        [DroneDreamInstalledVisualNative]::DWMWA_EXTENDED_FRAME_BOUNDS,
        [ref]$native,
        $size
    )
    Assert-Condition ($result -eq 0) "DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS) failed with HRESULT 0x$('{0:X8}' -f $result)."
    $rect = Convert-NativeRect $native
    Assert-Condition ($rect.width -gt 0 -and $rect.height -gt 0) "DWM returned an empty visible frame."
    return $rect
}

function Get-MonitorRects {
    param([IntPtr]$Handle)
    $monitor = [DroneDreamInstalledVisualNative]::MonitorFromWindow(
        $Handle,
        [DroneDreamInstalledVisualNative]::MONITOR_DEFAULTTONEAREST
    )
    Assert-Condition ($monitor -ne [IntPtr]::Zero) "MonitorFromWindow failed for HWND $Handle."
    $info = New-Object DroneDreamInstalledVisualNative+MONITORINFO
    $info.cbSize = [Runtime.InteropServices.Marshal]::SizeOf(
        [type][DroneDreamInstalledVisualNative+MONITORINFO]
    )
    Assert-Condition (
        [DroneDreamInstalledVisualNative]::GetMonitorInfoW($monitor, [ref]$info)
    ) "GetMonitorInfoW failed for HWND $Handle."
    return [ordered]@{
        monitor = Convert-NativeRect $info.rcMonitor
        workArea = Convert-NativeRect $info.rcWork
    }
}

function Wait-WindowState {
    param(
        [IntPtr]$Handle,
        [bool]$ExpectedMaximized,
        [int]$TimeoutSeconds
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $maximized = [DroneDreamInstalledVisualNative]::IsZoomed($Handle)
        $minimized = [DroneDreamInstalledVisualNative]::IsIconic($Handle)
        if ($maximized -eq $ExpectedMaximized -and -not $minimized) { return }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "HWND $Handle did not reach the expected $(if ($ExpectedMaximized) { 'maximized' } else { 'restored' }) state."
}

function Wait-ExactEditionWindow {
    param(
        [Diagnostics.Process]$Process,
        [string]$ExpectedTitle,
        [int]$TimeoutSeconds
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if ($Process.HasExited) {
            throw "Process $($Process.Id) exited before its main window became available."
        }
        $matching = @(
            [DroneDreamInstalledVisualNative]::GetVisibleTopLevelWindows([uint32]$Process.Id) |
                Where-Object {
                    [DroneDreamInstalledVisualNative]::GetTitle($_) -ceq $ExpectedTitle
                }
        )
        if ($matching.Count -eq 1) { return [IntPtr]$matching[0] }
        if ($matching.Count -gt 1) {
            throw "Process $($Process.Id) owns more than one visible top-level window titled '$ExpectedTitle'."
        }
        Start-Sleep -Milliseconds 150
        $Process.Refresh()
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Process $($Process.Id) did not expose exactly one visible window titled '$ExpectedTitle'."
}

function Set-CanonicalDefaultWindow {
    param(
        [IntPtr]$Handle,
        [int]$ClientWidthDip,
        [int]$ClientHeightDip,
        [int]$TimeoutSeconds
    )
    [DroneDreamInstalledVisualNative]::ShowWindow(
        $Handle,
        [DroneDreamInstalledVisualNative]::SW_RESTORE
    ) | Out-Null
    Wait-WindowState -Handle $Handle -ExpectedMaximized $false -TimeoutSeconds $TimeoutSeconds

    $dpi = [int][DroneDreamInstalledVisualNative]::GetDpiForWindow($Handle)
    Assert-Condition ($dpi -ge 96 -and $dpi -le 768) "GetDpiForWindow returned an invalid DPI value: $dpi."
    $targetClientWidthPixels = [int][Math]::Round($ClientWidthDip * $dpi / 96.0)
    $targetClientHeightPixels = [int][Math]::Round($ClientHeightDip * $dpi / 96.0)

    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        $window = Get-NativeWindowRect $Handle
        $client = Get-NativeClientRect $Handle
        $targetWindowWidth = $window.width + ($targetClientWidthPixels - $client.width)
        $targetWindowHeight = $window.height + ($targetClientHeightPixels - $client.height)
        $monitorRects = Get-MonitorRects $Handle
        $work = $monitorRects.workArea
        Assert-Condition (
            $targetWindowWidth -le $work.width -and $targetWindowHeight -le $work.height
        ) "The canonical ${ClientWidthDip}x${ClientHeightDip} DIP client does not fit in the active monitor work area at ${dpi} DPI."
        $targetX = $work.left + [int][Math]::Floor(($work.width - $targetWindowWidth) / 2.0)
        $targetY = $work.top + [int][Math]::Floor(($work.height - $targetWindowHeight) / 2.0)
        Assert-Condition (
            [DroneDreamInstalledVisualNative]::SetWindowPos(
                $Handle,
                [DroneDreamInstalledVisualNative]::HWND_TOP,
                $targetX,
                $targetY,
                $targetWindowWidth,
                $targetWindowHeight,
                [DroneDreamInstalledVisualNative]::SWP_FRAMECHANGED -bor
                    [DroneDreamInstalledVisualNative]::SWP_SHOWWINDOW
            )
        ) "SetWindowPos failed while applying the canonical default client size."
        Start-Sleep -Milliseconds 125
        $actual = Get-NativeClientRect $Handle
        if ([Math]::Abs($actual.width - $targetClientWidthPixels) -le 1 -and
            [Math]::Abs($actual.height - $targetClientHeightPixels) -le 1) {
            break
        }
    }

    $client = Get-NativeClientRect $Handle
    Assert-Condition (
        [Math]::Abs($client.width - $targetClientWidthPixels) -le 1 -and
        [Math]::Abs($client.height - $targetClientHeightPixels) -le 1
    ) "The restored client is $($client.width)x$($client.height) px; expected ${targetClientWidthPixels}x${targetClientHeightPixels} px at ${dpi} DPI."
    Assert-Condition (-not [DroneDreamInstalledVisualNative]::IsZoomed($Handle)) "The canonical default window is unexpectedly maximized."
    return [ordered]@{
        dpi = $dpi
        clientPixels = $client
        clientDip = [ordered]@{
            width = [Math]::Round($client.width * 96.0 / $dpi, 2)
            height = [Math]::Round($client.height * 96.0 / $dpi, 2)
        }
    }
}

function Set-MaximizedWindow {
    param(
        [IntPtr]$Handle,
        [int]$TimeoutSeconds
    )
    [DroneDreamInstalledVisualNative]::ShowWindow(
        $Handle,
        [DroneDreamInstalledVisualNative]::SW_MAXIMIZE
    ) | Out-Null
    Wait-WindowState -Handle $Handle -ExpectedMaximized $true -TimeoutSeconds $TimeoutSeconds
    Assert-Condition ([DroneDreamInstalledVisualNative]::IsZoomed($Handle)) "The requested maximized state was not retained."
}

function Set-CaptureForeground {
    param([IntPtr]$Handle)
    [DroneDreamInstalledVisualNative]::SetWindowPos(
        $Handle,
        [DroneDreamInstalledVisualNative]::HWND_TOPMOST,
        0,
        0,
        0,
        0,
        [DroneDreamInstalledVisualNative]::SWP_NOMOVE -bor
            [DroneDreamInstalledVisualNative]::SWP_NOSIZE -bor
            [DroneDreamInstalledVisualNative]::SWP_SHOWWINDOW
    ) | Out-Null
    [DroneDreamInstalledVisualNative]::BringWindowToTop($Handle) | Out-Null
    [DroneDreamInstalledVisualNative]::SetForegroundWindow($Handle) | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    while ([DroneDreamInstalledVisualNative]::GetForegroundWindow() -ne $Handle -and
        [DateTime]::UtcNow -lt $deadline) {
        [DroneDreamInstalledVisualNative]::BringWindowToTop($Handle) | Out-Null
        [DroneDreamInstalledVisualNative]::SetForegroundWindow($Handle) | Out-Null
        Start-Sleep -Milliseconds 100
    }
    Assert-Condition (
        [DroneDreamInstalledVisualNative]::GetForegroundWindow() -eq $Handle
    ) "The exact application window could not retain foreground focus for screen capture."
}

function Release-CaptureForeground {
    param([IntPtr]$Handle)
    Assert-Condition (
        [DroneDreamInstalledVisualNative]::SetWindowPos(
            $Handle,
            [DroneDreamInstalledVisualNative]::HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            [DroneDreamInstalledVisualNative]::SWP_NOMOVE -bor
                [DroneDreamInstalledVisualNative]::SWP_NOSIZE -bor
                [DroneDreamInstalledVisualNative]::SWP_NOACTIVATE -bor
                [DroneDreamInstalledVisualNative]::SWP_SHOWWINDOW
        )
    ) "The target application window could not leave temporary capture topmost state."
}

function Save-ExactScreenRectangle {
    param(
        [Parameter(Mandatory = $true)]$Rect,
        [Parameter(Mandatory = $true)][string]$Path
    )
    Assert-Condition ($Rect.width -gt 0 -and $Rect.height -gt 0) "The requested capture rectangle is empty."
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = "$Path.tmp-$PID.png"
    $bitmap = [Drawing.Bitmap]::new(
        [int]$Rect.width,
        [int]$Rect.height,
        [Drawing.Imaging.PixelFormat]::Format32bppArgb
    )
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen(
            [int]$Rect.left,
            [int]$Rect.top,
            0,
            0,
            [Drawing.Size]::new([int]$Rect.width, [int]$Rect.height),
            [Drawing.CopyPixelOperation]::SourceCopy
        )
        $bitmap.Save($temporary, [Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    Move-Item -LiteralPath $temporary -Destination $Path -Force

    $saved = [Drawing.Image]::FromFile($Path)
    try {
        Assert-Condition (
            $saved.Width -eq $Rect.width -and $saved.Height -eq $Rect.height
        ) "Saved PNG dimensions $($saved.Width)x$($saved.Height) do not match the capture rectangle $($Rect.width)x$($Rect.height)."
    }
    finally {
        $saved.Dispose()
    }
    return [ordered]@{
        path = (Resolve-Path -LiteralPath $Path).Path
        width = [int]$Rect.width
        height = [int]$Rect.height
        bytes = [long](Get-Item -LiteralPath $Path).Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-CaptureGeometry {
    param(
        [IntPtr]$Handle,
        [ValidateSet("default", "maximized")]
        [string]$State
    )
    $frame = Get-DwmVisibleFrameRect $Handle
    $monitorRects = Get-MonitorRects $Handle
    $work = $monitorRects.workArea
    $capture = if ($State -ceq "maximized") {
        Get-RectIntersection -First $frame -Second $work
    } else {
        $frame
    }
    if ($State -ceq "default") {
        Assert-Condition (
            $capture.left -ge $work.left -and
            $capture.top -ge $work.top -and
            $capture.right -le $work.right -and
            $capture.bottom -le $work.bottom
        ) "The canonical default visible frame is not fully contained in the monitor work area."
    } else {
        Assert-Condition (
            $capture.left -ge $work.left -and
            $capture.top -ge $work.top -and
            $capture.right -le $work.right -and
            $capture.bottom -le $work.bottom
        ) "The maximized capture rectangle escaped the monitor work area."
        Assert-Condition ($capture.bottom -le $work.bottom) "The maximized capture includes pixels below the taskbar-excluding work area."
    }
    return [ordered]@{
        state = $State
        windowRect = Get-NativeWindowRect $Handle
        visibleFrame = $frame
        monitor = $monitorRects.monitor
        workArea = $work
        captureRect = $capture
        maximized = [bool][DroneDreamInstalledVisualNative]::IsZoomed($Handle)
    }
}

function Write-AtomicJson {
    param(
        [string]$Path,
        $Value
    )
    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = "$Path.tmp-$PID"
    try {
        [IO.File]::WriteAllText(
            $temporary,
            (($Value | ConvertTo-Json -Depth 20) + "`n"),
            [Text.UTF8Encoding]::new($false)
        )
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            [IO.File]::Delete($temporary)
        }
    }
}

function Get-CleanRepositorySourceBinding {
    $commit = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
    Assert-Condition (
        $LASTEXITCODE -eq 0 -and $commit -cmatch '^[0-9a-f]{40}$'
    ) "Unable to resolve the repository HEAD commit."
    $tree = (& git -C $repoRoot rev-parse 'HEAD^{tree}').Trim()
    Assert-Condition (
        $LASTEXITCODE -eq 0 -and $tree -cmatch '^[0-9a-f]{40}$'
    ) "Unable to resolve the repository HEAD tree."
    $status = (& git -C $repoRoot status --porcelain=v1 --untracked-files=all | Out-String).Trim()
    Assert-Condition ([string]::IsNullOrWhiteSpace($status)) (
        "Installed-binary verification requires a clean source worktree. " +
        "Commit or remove every tracked and untracked change before -Execute."
    )
    return [ordered]@{ commit = $commit; tree = $tree; clean = $true }
}

function Find-ByteSequenceOccurrences {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][byte[]]$Sequence
    )

    if ($Sequence.Length -eq 0 -or $Bytes.Length -lt $Sequence.Length) {
        return @()
    }
    # ASCII decoding preserves one character per byte and maps non-ASCII bytes
    # to '?', which cannot fabricate this ASCII-only sentinel. String.IndexOf
    # keeps this scan native-speed even for a 60+ MB executable under PS 5.1.
    $haystack = [Text.Encoding]::ASCII.GetString($Bytes)
    $needle = [Text.Encoding]::ASCII.GetString($Sequence)
    $matches = [Collections.Generic.List[int]]::new()
    $searchFrom = 0
    while ($searchFrom -le $haystack.Length - $needle.Length) {
        $offset = $haystack.IndexOf($needle, $searchFrom, [StringComparison]::Ordinal)
        if ($offset -lt 0) { break }
        $matches.Add($offset)
        $searchFrom = $offset + 1
    }
    return $matches.ToArray()
}

function Get-ByteArraySha256 {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($algorithm.ComputeHash($Bytes) | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $algorithm.Dispose()
    }
}

function Get-NormalizedInstalledApplicationBinding {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)]$Contract
    )

    $prefix = [string]$Contract.prefix
    $buildMarker = [string]$Contract.buildMarker
    $installedMarker = [string]$Contract.installedMarker
    Assert-Condition (
        $prefix -ceq "__TAURI_BUNDLE_TYPE_VAR_" -and
        $buildMarker -ceq "UNK" -and
        $installedMarker -ceq "NSS" -and
        [int]$Contract.occurrenceCount -eq 1
    ) "Unsupported Tauri bundle-type normalization contract."
    $prefixBytes = [Text.Encoding]::ASCII.GetBytes($prefix)
    $buildMarkerBytes = [Text.Encoding]::ASCII.GetBytes($buildMarker)
    $installedMarkerBytes = [Text.Encoding]::ASCII.GetBytes($installedMarker)
    Assert-Condition (
        $buildMarkerBytes.Length -eq $installedMarkerBytes.Length
    ) "Tauri build and installed bundle markers must have equal byte lengths."
    $occurrences = @(Find-ByteSequenceOccurrences -Bytes $Bytes -Sequence $prefixBytes)
    Assert-Condition (
        $occurrences.Count -eq [int]$Contract.occurrenceCount
    ) "Installed application must contain exactly one Tauri bundle-type prefix; found $($occurrences.Count)."
    $markerOffset = [int]$occurrences[0] + $prefixBytes.Length
    Assert-Condition (
        $markerOffset + $installedMarkerBytes.Length -le $Bytes.Length
    ) "Installed application Tauri bundle-type marker is truncated."
    for ($index = 0; $index -lt $installedMarkerBytes.Length; $index++) {
        Assert-Condition (
            $Bytes[$markerOffset + $index] -eq $installedMarkerBytes[$index]
        ) "Installed application does not contain the expected Tauri NSS marker."
    }
    [byte[]]$normalized = $Bytes.Clone()
    for ($index = 0; $index -lt $buildMarkerBytes.Length; $index++) {
        $normalized[$markerOffset + $index] = $buildMarkerBytes[$index]
    }
    return [ordered]@{
        occurrenceCount = $occurrences.Count
        markerOffset = $markerOffset
        installedMarker = $installedMarker
        normalizedSha256 = Get-ByteArraySha256 -Bytes $normalized
    }
}

function Get-InstalledApplicationBinding {
    param(
        [Parameter(Mandatory = $true)][string]$ApplicationPath,
        [Parameter(Mandatory = $true)]$BuildReceipt
    )
    Assert-Condition (
        (Test-Path -LiteralPath $ApplicationPath -PathType Leaf)
    ) "Installed application is missing: $ApplicationPath"
    $file = Get-Item -LiteralPath $ApplicationPath
    [byte[]]$bytes = [IO.File]::ReadAllBytes($ApplicationPath)
    $hash = Get-ByteArraySha256 -Bytes $bytes
    $normalization = Get-NormalizedInstalledApplicationBinding `
        -Bytes $bytes `
        -Contract $BuildReceipt.application.bundleTypeNormalization
    Assert-Condition (
        [long]$file.Length -eq [long]$BuildReceipt.application.bytes -and
        [string]$normalization.normalizedSha256 -ceq [string]$BuildReceipt.application.bundleTypeNormalization.normalizedSha256 -and
        [string]$normalization.normalizedSha256 -ceq [string]$BuildReceipt.application.sha256
    ) "Installed application differs from the exact build application beyond the one permitted Tauri UNK-to-NSS marker change: $ApplicationPath"
    $version = $file.VersionInfo
    Assert-Condition (
        [string]$version.FileVersion -ceq [string]$BuildReceipt.version -and
        [string]$version.ProductVersion -ceq [string]$BuildReceipt.version
    ) "Installed application version does not match build receipt version $($BuildReceipt.version): $ApplicationPath"
    Assert-Condition (
        [string]$version.ProductName -ceq [string]$BuildReceipt.productName
    ) "Installed application product identity does not match the build receipt: $ApplicationPath"
    return [ordered]@{
        path = $file.FullName
        bytes = [long]$file.Length
        sha256 = $hash
        bundleTypeNormalization = $normalization
        fileVersion = [string]$version.FileVersion
        productVersion = [string]$version.ProductVersion
        productName = [string]$version.ProductName
        fileDescription = [string]$version.FileDescription
        creationTimeUtc = $file.CreationTimeUtc.ToString("O")
        lastWriteTimeUtc = $file.LastWriteTimeUtc.ToString("O")
    }
}

function Get-FiveEditionBuildBindings {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)]$SourceBinding,
        [Parameter(Mandatory = $true)]$Plans
    )
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($Root)) "BuildOutputRoot is required for -Execute."
    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    Assert-Condition (Test-Path -LiteralPath $resolvedRoot -PathType Container) "BuildOutputRoot is not a directory: $resolvedRoot"
    $receiptFiles = @(Get-ChildItem -LiteralPath $resolvedRoot -Filter "build-receipt.json" -File -Recurse)
    Assert-Condition ($receiptFiles.Count -eq 5) "BuildOutputRoot must contain exactly five build-receipt.json files; found $($receiptFiles.Count)."

    $planByEdition = @{}
    foreach ($plan in $Plans) { $planByEdition[[string]$plan.editionId] = $plan }
    $bindings = [Collections.Generic.List[object]]::new()
    foreach ($editionId in $allEditionIds) {
        Assert-Condition ($planByEdition.ContainsKey($editionId)) "No installed-application plan exists for build edition '$editionId'."
        $editionRoot = Join-Path $resolvedRoot $editionId
        $receiptPath = Join-Path $editionRoot "build-receipt.json"
        Assert-Condition (Test-Path -LiteralPath $receiptPath -PathType Leaf) "Missing canonical $editionId build receipt: $receiptPath"
        $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Condition (
            [int]$receipt.schemaVersion -eq 1 -and
            [string]$receipt.kind -ceq "dronedream-five-edition-build-receipt" -and
            [string]$receipt.editionId -ceq $editionId
        ) "Unsupported or misidentified build receipt: $receiptPath"
        Assert-Condition (
            [string]$receipt.sourceCommit -ceq [string]$SourceBinding.commit -and
            [string]$receipt.sourceTree -ceq [string]$SourceBinding.tree
        ) "$editionId build receipt is not bound to the current clean HEAD/tree."
        Assert-Condition (
            [string]$receipt.productName -ceq [string]$planByEdition[$editionId].productName -and
            -not [string]::IsNullOrWhiteSpace([string]$receipt.version)
        ) "$editionId build receipt product or version is inconsistent."
        $generatedAt = [DateTimeOffset]::MinValue
        Assert-Condition (
            [DateTimeOffset]::TryParse([string]$receipt.generatedAt, [ref]$generatedAt)
        ) "$editionId build receipt has no valid generatedAt timestamp."
        Assert-Condition (
            $null -ne $receipt.installer -and
            [IO.Path]::GetFileName([string]$receipt.installer.fileName) -ceq [string]$receipt.installer.fileName -and
            [long]$receipt.installer.bytes -gt 0 -and
            [string]$receipt.installer.sha256 -cmatch '^[0-9a-f]{64}$'
        ) "$editionId build receipt has no valid installer binding."
        Assert-Condition (
            $null -ne $receipt.application -and
            [string]$receipt.application.fileName -ceq "drone-dream-desktop.exe" -and
            [long]$receipt.application.bytes -gt 0 -and
            [string]$receipt.application.sha256 -cmatch '^[0-9a-f]{64}$' -and
            $null -ne $receipt.application.bundleTypeNormalization -and
            [string]$receipt.application.bundleTypeNormalization.prefix -ceq "__TAURI_BUNDLE_TYPE_VAR_" -and
            [string]$receipt.application.bundleTypeNormalization.buildMarker -ceq "UNK" -and
            [string]$receipt.application.bundleTypeNormalization.installedMarker -ceq "NSS" -and
            [int]$receipt.application.bundleTypeNormalization.occurrenceCount -eq 1 -and
            [string]$receipt.application.bundleTypeNormalization.normalizedSha256 -ceq [string]$receipt.application.sha256
        ) "$editionId build receipt has no exact application executable binding."
        $installerPath = Join-Path $editionRoot ([string]$receipt.installer.fileName)
        Assert-Condition (Test-Path -LiteralPath $installerPath -PathType Leaf) "$editionId installer recorded by the receipt is missing."
        $installer = Get-Item -LiteralPath $installerPath
        $installerHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Assert-Condition (
            [long]$installer.Length -eq [long]$receipt.installer.bytes -and
            $installerHash -ceq [string]$receipt.installer.sha256
        ) "$editionId installer bytes or SHA-256 drifted from its build receipt."
        $installed = Get-InstalledApplicationBinding `
            -ApplicationPath ([string]$planByEdition[$editionId].applicationPath) `
            -BuildReceipt $receipt
        $bindings.Add([ordered]@{
            editionId = $editionId
            receipt = [ordered]@{
                path = (Resolve-Path -LiteralPath $receiptPath).Path
                sha256 = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
                sourceCommit = [string]$receipt.sourceCommit
                sourceTree = [string]$receipt.sourceTree
                buildNumber = [UInt64]$receipt.buildNumber
                version = [string]$receipt.version
                generatedAt = [string]$receipt.generatedAt
            }
            installer = [ordered]@{
                path = (Resolve-Path -LiteralPath $installerPath).Path
                bytes = [long]$installer.Length
                sha256 = $installerHash
            }
            application = [ordered]@{
                fileName = [string]$receipt.application.fileName
                bytes = [long]$receipt.application.bytes
                sha256 = [string]$receipt.application.sha256
                bundleTypeNormalization = $receipt.application.bundleTypeNormalization
            }
            installedApplication = $installed
        })
    }
    return [ordered]@{ root = $resolvedRoot; editions = $bindings.ToArray() }
}

function New-UniqueOutputRunRoot {
    param([Parameter(Mandatory = $true)][string]$BaseRoot)
    $base = [IO.Path]::GetFullPath($BaseRoot)
    Assert-Condition (-not (Test-Path -LiteralPath $base -PathType Leaf)) "OutputRoot points to a file: $base"
    New-Item -ItemType Directory -Path $base -Force | Out-Null
    $runName = "run-{0}-{1}" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ"), ([Guid]::NewGuid().ToString("N").Substring(0, 8))
    $runRoot = Join-Path $base $runName
    Assert-Condition (-not (Test-Path -LiteralPath $runRoot)) "Unique output run directory already exists: $runRoot"
    New-Item -ItemType Directory -Path $runRoot | Out-Null
    return (Resolve-Path -LiteralPath $runRoot).Path
}

function Get-SurfaceMatrix {
    Assert-Condition (
        (Test-Path -LiteralPath $surfaceDriverPath -PathType Leaf)
    ) "Installed-surface CDP driver is missing: $surfaceDriverPath"
    $node = Get-Command node -ErrorAction SilentlyContinue
    Assert-Condition ($null -ne $node) "Node.js is required to enumerate and drive installed surfaces."
    $lines = @(& $node.Source $surfaceDriverPath --list-surfaces 2>&1)
    Assert-Condition ($LASTEXITCODE -eq 0) (
        "Installed-surface CDP driver could not enumerate its matrix: " +
        (($lines | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
    )
    $json = ($lines | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    try {
        $matrix = $json | ConvertFrom-Json
    }
    catch {
        throw "Installed-surface CDP driver returned invalid JSON: $($_.Exception.Message)"
    }
    Assert-Condition (
        [int]$matrix.schemaVersion -eq 1 -and
        [string]$matrix.kind -ceq "dronedream-five-edition-installed-surface-matrix"
    ) "Installed-surface CDP matrix is missing or unsupported."
    return $matrix
}

function Get-EditionSurfaces {
    param(
        [Parameter(Mandatory = $true)]$Matrix,
        [Parameter(Mandatory = $true)][string]$EditionId
    )
    $property = $Matrix.editions.PSObject.Properties[$EditionId]
    Assert-Condition ($null -ne $property) "Surface matrix has no '$EditionId' edition."
    $surfaces = @($property.Value)
    Assert-Condition ($surfaces.Count -gt 0) "Surface matrix for '$EditionId' is empty."
    $ids = @($surfaces | ForEach-Object { [string]$_.id })
    Assert-Condition (
        $ids.Count -eq @($ids | Select-Object -Unique).Count
    ) "Surface matrix for '$EditionId' contains duplicate surface identifiers."
    return $surfaces
}

function Assert-SurfaceMatrix {
    param([Parameter(Mandatory = $true)]$Matrix)
    $requiredEverywhere = @(
        "assistant", "jobs-new", "dashboard", "history", "scenarios", "compare",
        "autonomy-overview", "autonomy-aircraft",
        "autonomy-maps", "autonomy-plugins", "autonomy-harness", "autonomy-live",
        "autonomy-evidence", "launcher", "quick-settings", "settings-general",
        "settings-memory", "settings-model", "settings-course", "settings-runtime",
        "account-menu"
    )
    foreach ($editionId in $allEditionIds) {
        $ids = @(Get-EditionSurfaces -Matrix $Matrix -EditionId $editionId |
            ForEach-Object { [string]$_.id })
        Assert-Condition (
            $ids[0] -ceq "launcher"
        ) "$editionId must capture the launcher and establish Runtime readiness before guarded routes."
        foreach ($requiredId in $requiredEverywhere) {
            Assert-Condition ($requiredId -in $ids) "$editionId is missing required surface '$requiredId'."
        }
    }
    $universalIds = @(Get-EditionSurfaces -Matrix $Matrix -EditionId "universal" |
        ForEach-Object { [string]$_.id })
    foreach ($requiredId in @(
        "lab-workspace", "lab-hardware",
        "lab-validation", "field-device", "field-tuning", "field-operations"
    )) {
        Assert-Condition ($requiredId -in $universalIds) "Universal is missing required surface '$requiredId'."
    }
    foreach ($modeId in @("sim", "lab", "field", "autonomy")) {
        foreach ($sharedId in @("assistant", "jobs-new", "dashboard", "history", "scenarios", "compare")) {
            Assert-Condition (
                "$modeId-$sharedId" -in $universalIds
            ) "Universal/$modeId is missing shared surface '$sharedId'."
        }
    }
    foreach ($requiredId in @("job-detail", "trial-detail")) {
        $skipped = @($Matrix.skippedDataDependentSurfaces |
            Where-Object { [string]$_.id -ceq $requiredId })
        Assert-Condition (
            $skipped.Count -eq 1 -and
            [string]$skipped[0].status -ceq "skipped" -and
            -not [string]::IsNullOrWhiteSpace([string]$skipped[0].reason)
        ) "Data-dependent surface '$requiredId' needs one explicit skipped receipt reason."
    }
}

function Test-TcpPortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        try { $listener.Stop() } catch { }
    }
}

function Wait-CdpEndpoint {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(1)
    $endpoint = "http://127.0.0.1:$Port/json/version"
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    try {
        do {
            try {
                $payload = $client.GetStringAsync($endpoint).GetAwaiter().GetResult()
                $metadata = $payload | ConvertFrom-Json
                if (-not [string]::IsNullOrWhiteSpace([string]$metadata.webSocketDebuggerUrl)) {
                    return "http://127.0.0.1:$Port"
                }
            }
            catch {
                Start-Sleep -Milliseconds 150
            }
        } while ([DateTime]::UtcNow -lt $deadline)
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
    throw "WebView2 CDP endpoint did not become ready on loopback port $Port."
}

function Invoke-SurfaceDriver {
    param(
        [Parameter(Mandatory = $true)][string]$CdpEndpoint,
        [Parameter(Mandatory = $true)][string]$EditionId,
        [Parameter(Mandatory = $true)][string]$SurfaceId,
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$Locale,
        [Parameter(Mandatory = $true)][string]$ExpectedEditionId,
        [Parameter(Mandatory = $true)][string]$ExpectedDocumentTitle,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $node = Get-Command node -ErrorAction SilentlyContinue
    Assert-Condition ($null -ne $node) "Node.js is required to drive installed surfaces."
    $arguments = @(
        $surfaceDriverPath,
        "--cdp-endpoint=$CdpEndpoint",
        "--edition=$EditionId",
        "--surface=$SurfaceId",
        "--state=$State",
        "--locale=$Locale",
        "--expected-edition=$ExpectedEditionId",
        "--expected-document-title=$ExpectedDocumentTitle",
        "--output=$OutputPath"
    )
    $lines = @(& $node.Source @arguments 2>&1)
    Assert-Condition ($LASTEXITCODE -eq 0) (
        "Surface driver failed for $EditionId/$Locale/$SurfaceId/${State}: " +
        (($lines | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
    )
    Assert-Condition (
        (Test-Path -LiteralPath $OutputPath -PathType Leaf)
    ) "Surface driver did not write its semantic receipt: $OutputPath"
    $receipt = Get-Content -LiteralPath $OutputPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Condition (
        [string]$receipt.kind -ceq "dronedream-installed-surface-semantic-receipt" -and
        [string]$receipt.edition -ceq $EditionId -and
        [string]$receipt.surface -ceq $SurfaceId -and
        [string]$receipt.state -ceq $State -and
        [string]$receipt.locale -ceq $Locale -and
        [string]$receipt.expectedIdentity.edition -ceq $ExpectedEditionId -and
        [string]$receipt.expectedIdentity.documentTitle -ceq $ExpectedDocumentTitle
    ) "Surface driver semantic receipt identity is inconsistent."
    if ([string]$receipt.status -ceq "skipped") {
        Assert-Condition (
            -not [string]::IsNullOrWhiteSpace([string]$receipt.reason)
        ) "Surface driver skipped receipt has no reason."
    } else {
        Assert-Condition ($null -ne $receipt.metrics) "Surface driver semantic receipt has no metrics."
    }
    return $receipt
}

function Convert-SemanticParityFingerprint {
    param([Parameter(Mandatory = $true)]$Metrics)
    $contract = [ordered]@{
        route = [string]$Metrics.route
        title = [string]$Metrics.title
        titleLineCount = [int]$Metrics.titleLineCount
        headings = @($Metrics.headings)
        navigationOrder = @($Metrics.navigationOrder)
        controlOrder = @($Metrics.controlOrder)
        overlay = [string]$Metrics.overlay
        overlayHeadings = @($Metrics.overlayHeadings)
        overlayControlOrder = @($Metrics.overlayControlOrder)
        visualTopology = $Metrics.visualTopology
        moduleTopology = $Metrics.moduleTopology
    }
    return ($contract | ConvertTo-Json -Depth 20 -Compress)
}

function Get-EditionPlan {
    $contract = Get-Content -LiteralPath $coexistenceContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-Condition (
        [int]$contract.schemaVersion -eq 1 -and
        [string]$contract.kind -ceq "dronedream-desktop-edition-coexistence"
    ) "The five-edition coexistence contract is missing or unsupported."

    $applicationOverrides = @{}
    if (-not [string]::IsNullOrWhiteSpace($ApplicationMapPath)) {
        $resolvedMapPath = (Resolve-Path -LiteralPath $ApplicationMapPath).Path
        $map = Get-Content -LiteralPath $resolvedMapPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($property in $map.PSObject.Properties) {
            $applicationOverrides[[string]$property.Name] = [string]$property.Value
        }
    }

    $indexHtml = Get-Content -LiteralPath (Join-Path $repoRoot "frontend\index.html") -Raw -Encoding UTF8
    $documentTitleMatch = [regex]::Match($indexHtml, '<title>([^<]+)</title>', 'IgnoreCase')
    Assert-Condition ($documentTitleMatch.Success) "frontend/index.html has no canonical document title."
    $plans = foreach ($editionId in $allEditionIds) {
        $edition = @($contract.editions | Where-Object { [string]$_.editionId -ceq $editionId })
        Assert-Condition ($edition.Count -eq 1) "Edition '$editionId' did not resolve exactly once in the coexistence contract."
        $configPath = Join-Path $repoRoot "desktop\src-tauri\tauri.$editionId.conf.json"
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $window = $config.app.windows[0]
        Assert-Condition (
            [bool]$window.resizable -and [bool]$window.maximizable
        ) "Edition '$editionId' must remain both resizable and maximizable for the two-state visual contract."
        Assert-Condition (
            [int]$window.width -gt 0 -and [int]$window.height -gt 0
        ) "Edition '$editionId' has an invalid canonical default client size."
        $defaultApplicationPath = Join-Path (
            [Environment]::ExpandEnvironmentVariables([string]$edition[0].installRoot).Replace('/', '\')
        ) "drone-dream-desktop.exe"
        $applicationPath = if ($applicationOverrides.ContainsKey($editionId)) {
            [IO.Path]::GetFullPath($applicationOverrides[$editionId])
        } else {
            [IO.Path]::GetFullPath($defaultApplicationPath)
        }
        [ordered]@{
            editionId = $editionId
            displayName = [string]$edition[0].displayName
            productName = [string]$config.productName
            applicationPath = $applicationPath
            windowTitle = [string]$window.title
            documentTitle = [Net.WebUtility]::HtmlDecode($documentTitleMatch.Groups[1].Value.Trim())
            defaultClientDip = [ordered]@{
                width = [int]$window.width
                height = [int]$window.height
            }
        }
    }
    return @($plans)
}

function Find-RunningEditionProcess {
    param([string]$ApplicationPath)
    $matches = @(
        Get-Process -Name "drone-dream-desktop" -ErrorAction SilentlyContinue |
            Where-Object {
                try {
                    [string]::Equals($_.Path, $ApplicationPath, [StringComparison]::OrdinalIgnoreCase)
                } catch {
                    $false
                }
            }
    )
    Assert-Condition ($matches.Count -le 1) "More than one running process uses '$ApplicationPath'."
    if ($matches.Count -eq 1) { return $matches[0] }
    return $null
}

function Get-OriginalWindowState {
    param([IntPtr]$Handle)
    return [ordered]@{
        maximized = [bool][DroneDreamInstalledVisualNative]::IsZoomed($Handle)
        minimized = [bool][DroneDreamInstalledVisualNative]::IsIconic($Handle)
        windowRect = Get-NativeWindowRect $Handle
    }
}

function Restore-OriginalWindowState {
    param(
        [IntPtr]$Handle,
        $Original
    )
    [DroneDreamInstalledVisualNative]::ShowWindow(
        $Handle,
        [DroneDreamInstalledVisualNative]::SW_RESTORE
    ) | Out-Null
    if ($Original.maximized) {
        [DroneDreamInstalledVisualNative]::ShowWindow(
            $Handle,
            [DroneDreamInstalledVisualNative]::SW_MAXIMIZE
        ) | Out-Null
    } else {
        [DroneDreamInstalledVisualNative]::SetWindowPos(
            $Handle,
            [DroneDreamInstalledVisualNative]::HWND_TOP,
            [int]$Original.windowRect.left,
            [int]$Original.windowRect.top,
            [int]$Original.windowRect.width,
            [int]$Original.windowRect.height,
            [DroneDreamInstalledVisualNative]::SWP_NOACTIVATE -bor
                [DroneDreamInstalledVisualNative]::SWP_NOZORDER -bor
                [DroneDreamInstalledVisualNative]::SWP_SHOWWINDOW
        ) | Out-Null
        if ($Original.minimized) {
            [DroneDreamInstalledVisualNative]::ShowWindow(
                $Handle,
                [DroneDreamInstalledVisualNative]::SW_MINIMIZE
            ) | Out-Null
        }
    }
}

function Invoke-InMemorySelfTest {
    $work = [ordered]@{ left = 0; top = 0; right = 2560; bottom = 1528; width = 2560; height = 1528 }
    $maximizedFrame = [ordered]@{ left = -8; top = -8; right = 2568; bottom = 1536; width = 2576; height = 1544 }
    $intersection = Get-RectIntersection -First $maximizedFrame -Second $work
    Assert-Condition (
        $intersection.left -eq 0 -and
        $intersection.top -eq 0 -and
        $intersection.right -eq 2560 -and
        $intersection.bottom -eq 1528
    ) "Work-area intersection self-test failed."

    $negativeWork = [ordered]@{ left = -1920; top = 0; right = 0; bottom = 1040; width = 1920; height = 1040 }
    $negativeFrame = [ordered]@{ left = -1928; top = -8; right = 8; bottom = 1048; width = 1936; height = 1056 }
    $negativeIntersection = Get-RectIntersection -First $negativeFrame -Second $negativeWork
    Assert-Condition (
        $negativeIntersection.left -eq -1920 -and
        $negativeIntersection.right -eq 0 -and
        $negativeIntersection.bottom -eq 1040
    ) "Negative-coordinate monitor intersection self-test failed."

    $memory = [IO.MemoryStream]::new()
    $bitmap = [Drawing.Bitmap]::new(17, 11, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        $bitmap.Save($memory, [Drawing.Imaging.ImageFormat]::Png)
        $memory.Position = 0
        $decoded = [Drawing.Image]::FromStream($memory)
        try {
            Assert-Condition ($decoded.Width -eq 17 -and $decoded.Height -eq 11) "PNG dimension self-test failed."
        }
        finally {
            $decoded.Dispose()
        }
    }
    finally {
        $bitmap.Dispose()
        $memory.Dispose()
    }

    $prefix = "__TAURI_BUNDLE_TYPE_VAR_"
    [byte[]]$buildBytes = [Text.Encoding]::ASCII.GetBytes("before-$($prefix)UNK-after")
    $normalizationContract = [ordered]@{
        prefix = $prefix
        buildMarker = "UNK"
        installedMarker = "NSS"
        occurrenceCount = 1
        normalizedSha256 = Get-ByteArraySha256 -Bytes $buildBytes
    }
    [byte[]]$installedBytes = $buildBytes.Clone()
    $prefixOffset = [Text.Encoding]::ASCII.GetString($installedBytes).IndexOf($prefix, [StringComparison]::Ordinal)
    $markerOffset = $prefixOffset + [Text.Encoding]::ASCII.GetByteCount($prefix)
    [byte[]]$installedMarker = [Text.Encoding]::ASCII.GetBytes("NSS")
    [Array]::Copy($installedMarker, 0, $installedBytes, $markerOffset, $installedMarker.Length)
    $normalized = Get-NormalizedInstalledApplicationBinding -Bytes $installedBytes -Contract $normalizationContract
    Assert-Condition (
        [string]$normalized.normalizedSha256 -ceq [string]$normalizationContract.normalizedSha256
    ) "Tauri UNK-to-NSS normalization self-test failed."

    $missingRejected = $false
    try {
        Get-NormalizedInstalledApplicationBinding `
            -Bytes ([Text.Encoding]::ASCII.GetBytes("no-bundle-marker")) `
            -Contract $normalizationContract | Out-Null
    }
    catch { $missingRejected = $true }
    Assert-Condition $missingRejected "Missing Tauri bundle marker was not rejected."

    $duplicateRejected = $false
    try {
        [byte[]]$duplicateBytes = [Text.Encoding]::ASCII.GetBytes("$($prefix)NSS-$($prefix)NSS")
        Get-NormalizedInstalledApplicationBinding -Bytes $duplicateBytes -Contract $normalizationContract | Out-Null
    }
    catch { $duplicateRejected = $true }
    Assert-Condition $duplicateRejected "Duplicate Tauri bundle markers were not rejected."

    [byte[]]$mutatedBytes = $installedBytes.Clone()
    $mutatedBytes[0] = $mutatedBytes[0] -bxor 1
    $mutated = Get-NormalizedInstalledApplicationBinding -Bytes $mutatedBytes -Contract $normalizationContract
    $unrelatedMutationRejected = $false
    try {
        Assert-Condition (
            [string]$mutated.normalizedSha256 -ceq [string]$normalizationContract.normalizedSha256
        ) "Unrelated installed-application byte mutation rejected by receipt SHA-256."
    }
    catch { $unrelatedMutationRejected = $true }
    Assert-Condition $unrelatedMutationRejected "An unrelated installed-application byte mutation was not rejected."
    return [ordered]@{
        intersection = $intersection
        negativeCoordinateIntersection = $negativeIntersection
        pngDimensions = [ordered]@{ width = 17; height = 11 }
        bundleTypeNormalization = [ordered]@{
            permittedTransition = "UNK-to-NSS"
            missingMarkerRejected = $missingRejected
            duplicateMarkerRejected = $duplicateRejected
            unrelatedMutationRejected = $unrelatedMutationRejected
        }
    }
}

$processDpiAwarenessApplied = [DroneDreamInstalledVisualNative]::SetProcessDpiAwarenessContext(
    [DroneDreamInstalledVisualNative]::DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
)
$previousThreadDpiContext = [DroneDreamInstalledVisualNative]::SetThreadDpiAwarenessContext(
    [DroneDreamInstalledVisualNative]::DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
)
Assert-Condition (
    $previousThreadDpiContext -ne [IntPtr]::Zero
) "Unable to enter a per-monitor-v2 DPI-aware thread context."

try {
    $surfaceMatrix = Get-SurfaceMatrix
    Assert-SurfaceMatrix -Matrix $surfaceMatrix

    if ($SelfTest) {
        $selfTestResult = Invoke-InMemorySelfTest
        $surfaceCounts = [ordered]@{}
        foreach ($editionId in $allEditionIds) {
            $surfaceCounts[$editionId] = @(Get-EditionSurfaces -Matrix $surfaceMatrix -EditionId $editionId).Count
        }
        [pscustomobject][ordered]@{
            schemaVersion = 1
            kind = "dronedream-installed-visual-parity-self-test"
            processDpiAwarenessApplied = [bool]$processDpiAwarenessApplied
            threadDpiAwareness = "per-monitor-v2"
            result = $selfTestResult
            surfaceMatrix = [ordered]@{
                editionCounts = $surfaceCounts
                skippedDataDependentSurfaces = @($surfaceMatrix.skippedDataDependentSurfaces)
            }
        }
        return
    }

    $allPlans = @(Get-EditionPlan)
    $plans = @($allPlans | Where-Object { [string]$_.editionId -in $selectedEditionIds })
    foreach ($plan in $plans) {
        $plan["surfaces"] = @(Get-EditionSurfaces -Matrix $surfaceMatrix -EditionId $plan.editionId)
    }
    $expectedCaptureCount = [int](
        ($plans | ForEach-Object { @($_.surfaces).Count } | Measure-Object -Sum).Sum *
        $Locales.Count * 2
    )
    if (-not $Execute) {
        [pscustomobject][ordered]@{
            schemaVersion = 1
            kind = "dronedream-five-edition-installed-visual-parity-plan"
            executionAuthorized = $false
            processDpiAwarenessApplied = [bool]$processDpiAwarenessApplied
            threadDpiAwareness = "per-monitor-v2"
            outputRoot = [IO.Path]::GetFullPath($OutputRoot)
            buildOutputRoot = if ([string]::IsNullOrWhiteSpace($BuildOutputRoot)) { $null } else { [IO.Path]::GetFullPath($BuildOutputRoot) }
            states = @("default", "maximized")
            locales = @($Locales)
            expectedCaptureCount = $expectedCaptureCount
            skippedDataDependentSurfaces = @($surfaceMatrix.skippedDataDependentSurfaces)
            executeNote = "Execution starts each edition with an isolated loopback-only WebView2 CDP profile; close installed instances first. Visual-QA binaries or an authenticated isolated profile are required for protected pages."
            editions = $plans
        }
        return
    }

    $sourceBinding = Get-CleanRepositorySourceBinding
    $buildBindings = Get-FiveEditionBuildBindings `
        -Root $BuildOutputRoot `
        -SourceBinding $sourceBinding `
        -Plans $allPlans
    $outputRootPath = New-UniqueOutputRunRoot -BaseRoot $OutputRoot
    $sourceCommit = [string]$sourceBinding.commit
    $buildBindingByEdition = @{}
    foreach ($binding in @($buildBindings.editions)) {
        $buildBindingByEdition[[string]$binding.editionId] = $binding
    }
    $cases = [Collections.Generic.List[object]]::new()
    $semanticBaselines = @{}
    $runtimeSkippedCaptureCount = 0
    $protectedSkippedCases = [Collections.Generic.List[object]]::new()
    $skippedCases = @(
        $surfaceMatrix.skippedDataDependentSurfaces | ForEach-Object {
            [ordered]@{
                surface = [string]$_.id
                routeTemplate = [string]$_.routeTemplate
                status = "skipped"
                reason = [string]$_.reason
                editionScope = @($selectedEditionIds)
            }
        }
    )

    for ($editionIndex = 0; $editionIndex -lt $plans.Count; $editionIndex++) {
        $plan = $plans[$editionIndex]
        Assert-Condition (
            (Test-Path -LiteralPath $plan.applicationPath -PathType Leaf)
        ) "Installed application is missing for $($plan.editionId): $($plan.applicationPath)"
        $runningProcess = Find-RunningEditionProcess -ApplicationPath $plan.applicationPath
        Assert-Condition (
            $null -eq $runningProcess
        ) "Close the running $($plan.displayName) instance before exhaustive CDP visual capture; CDP cannot be attached retroactively."
        $cdpPort = $CdpBasePort + $editionIndex
        Assert-Condition ($cdpPort -le 65535) "CDP port range exceeds 65535."
        Assert-Condition (Test-TcpPortAvailable -Port $cdpPort) "Loopback CDP port $cdpPort is already in use."
        $profilePath = Join-Path $outputRootPath "webview2-profile\$($plan.editionId)"
        New-Item -ItemType Directory -Path $profilePath -Force | Out-Null

        $process = $null
        $handle = [IntPtr]::Zero
        $previousBrowserArguments = [Environment]::GetEnvironmentVariable(
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            [EnvironmentVariableTarget]::Process
        )
        $previousProfile = [Environment]::GetEnvironmentVariable(
            "WEBVIEW2_USER_DATA_FOLDER",
            [EnvironmentVariableTarget]::Process
        )
        try {
            Assert-Condition (
                [string]::IsNullOrWhiteSpace($previousBrowserArguments) -or
                $previousBrowserArguments -notmatch '--remote-debugging-(?:address|port)'
            ) "Process-level WebView2 arguments already define remote debugging and would make capture ambiguous."
            $browserArguments = (
                "$previousBrowserArguments --remote-debugging-address=127.0.0.1 --remote-debugging-port=$cdpPort"
            ).Trim()
            [Environment]::SetEnvironmentVariable(
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                $browserArguments,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                "WEBVIEW2_USER_DATA_FOLDER",
                $profilePath,
                [EnvironmentVariableTarget]::Process
            )
            try {
                $process = Start-Process -FilePath $plan.applicationPath -PassThru
            }
            finally {
                [Environment]::SetEnvironmentVariable(
                    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                    $previousBrowserArguments,
                    [EnvironmentVariableTarget]::Process
                )
                [Environment]::SetEnvironmentVariable(
                    "WEBVIEW2_USER_DATA_FOLDER",
                    $previousProfile,
                    [EnvironmentVariableTarget]::Process
                )
            }
            $handle = Wait-ExactEditionWindow `
                -Process $process `
                -ExpectedTitle $plan.windowTitle `
                -TimeoutSeconds $WindowTimeoutSeconds
            $cdpEndpoint = Wait-CdpEndpoint -Port $cdpPort -TimeoutSeconds $WindowTimeoutSeconds

            foreach ($locale in $Locales) {
                $localeSegment = $locale.Replace('-', '_')
                foreach ($state in @("default", "maximized")) {
                    foreach ($surface in @($plan.surfaces)) {
                        $defaultWindowMetrics = $null
                        if ($state -ceq "default") {
                            $defaultWindowMetrics = Set-CanonicalDefaultWindow `
                                -Handle $handle `
                                -ClientWidthDip $plan.defaultClientDip.width `
                                -ClientHeightDip $plan.defaultClientDip.height `
                                -TimeoutSeconds $WindowTimeoutSeconds
                            Assert-Condition (-not [DroneDreamInstalledVisualNative]::IsZoomed($handle)) "Default capture state is maximized."
                        } else {
                            Set-MaximizedWindow -Handle $handle -TimeoutSeconds $WindowTimeoutSeconds
                            Assert-Condition ([DroneDreamInstalledVisualNative]::IsZoomed($handle)) "Maximized capture state is restored."
                        }

                        $semanticPath = Join-Path $outputRootPath (
                            "semantics\$($plan.editionId)-$localeSegment-$($surface.id)-$state.json"
                        )
                        $semantic = Invoke-SurfaceDriver `
                            -CdpEndpoint $cdpEndpoint `
                            -EditionId $plan.editionId `
                            -SurfaceId ([string]$surface.id) `
                            -State $state `
                            -Locale $locale `
                            -ExpectedEditionId $plan.editionId `
                            -ExpectedDocumentTitle $plan.documentTitle `
                            -OutputPath $semanticPath
                        if ([string]$semantic.status -ceq "skipped") {
                            $runtimeSkippedCaptureCount++
                            $protectedSkippedCases.Add([ordered]@{
                                surface = [string]$surface.id
                                route = [string]$surface.route
                                status = "skipped"
                                reason = [string]$semantic.reason
                                editionScope = @([string]$plan.editionId)
                                locale = $locale
                                state = $state
                                semanticReceipt = (Resolve-Path -LiteralPath $semanticPath).Path
                            })
                            continue
                        }
                        $fingerprint = Convert-SemanticParityFingerprint -Metrics $semantic.metrics
                        $baselineKey = "$($plan.editionId)|$locale|$($surface.id)"
                        if ($state -ceq "default") {
                            $semanticBaselines[$baselineKey] = $fingerprint
                        } else {
                            Assert-Condition (
                                $semanticBaselines.ContainsKey($baselineKey) -and
                                [string]$semanticBaselines[$baselineKey] -ceq $fingerprint
                            ) "$($plan.editionId)/$locale/$($surface.id): semantic or screen-coordinate visual topology differs between default and maximized states."
                        }

                        $screenshotPath = Join-Path $outputRootPath (
                            "$($plan.editionId)-$localeSegment-$($surface.id)-$state.png"
                        )
                        Set-CaptureForeground $handle
                        try {
                            Start-Sleep -Milliseconds $StateSettleMilliseconds
                            [DroneDreamInstalledVisualNative]::DwmFlush() | Out-Null
                            $geometry = Get-CaptureGeometry -Handle $handle -State $state
                            Assert-Condition (
                                $geometry.maximized -eq ($state -ceq "maximized")
                            ) "$($plan.editionId)/$locale/$($surface.id)/$state window-state assertion failed."
                            $image = Save-ExactScreenRectangle -Rect $geometry.captureRect -Path $screenshotPath
                        }
                        finally {
                            Release-CaptureForeground $handle
                        }
                        $cases.Add([ordered]@{
                            editionId = $plan.editionId
                            displayName = $plan.displayName
                            locale = $locale
                            surface = [string]$surface.id
                            route = [string]$semantic.metrics.route
                            title = [string]$semantic.metrics.title
                            titleLineCount = [int]$semantic.metrics.titleLineCount
                            navigationOrder = @($semantic.metrics.navigationOrder)
                            controlOrder = @($semantic.metrics.controlOrder)
                            overlay = [string]$semantic.metrics.overlay
                            overlayControlOrder = @($semantic.metrics.overlayControlOrder)
                            visualTopology = $semantic.metrics.visualTopology
                            moduleTopology = $semantic.metrics.moduleTopology
                            horizontalClipping = @($semantic.metrics.horizontalClipping)
                            verticalClipping = @($semantic.metrics.verticalClipping)
                            overlapIssues = @($semantic.metrics.overlapIssues)
                            semanticReceipt = (Resolve-Path -LiteralPath $semanticPath).Path
                            processId = [int]$process.Id
                            windowHandle = [string]$handle.ToInt64()
                            windowTitle = $plan.windowTitle
                            buildReceiptSha256 = [string]$buildBindingByEdition[$plan.editionId].receipt.sha256
                            installedApplicationSha256 = [string]$buildBindingByEdition[$plan.editionId].installedApplication.sha256
                            state = $state
                            defaultClient = $defaultWindowMetrics
                            geometry = $geometry
                            screenshot = $image
                        })
                    }
                }
            }
        }
        finally {
            [Environment]::SetEnvironmentVariable(
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                $previousBrowserArguments,
                [EnvironmentVariableTarget]::Process
            )
            [Environment]::SetEnvironmentVariable(
                "WEBVIEW2_USER_DATA_FOLDER",
                $previousProfile,
                [EnvironmentVariableTarget]::Process
            )
            if ($null -ne $process -and -not $KeepLaunchedApplications -and -not $process.HasExited) {
                $process.CloseMainWindow() | Out-Null
                $process.WaitForExit(5000) | Out-Null
            }
            if ($null -ne $process) { $process.Dispose() }
        }
    }

    $receipt = [ordered]@{
        schemaVersion = 1
        kind = "dronedream-five-edition-installed-visual-parity-receipt"
        generatedAtUtc = [DateTime]::UtcNow.ToString("O")
        sourceCommit = $sourceCommit
        sourceTree = [string]$sourceBinding.tree
        sourceWorktreeClean = [bool]$sourceBinding.clean
        outputBaseRoot = [IO.Path]::GetFullPath($OutputRoot)
        buildOutputRoot = [string]$buildBindings.root
        editionBuildBindings = @($buildBindings.editions)
        processDpiAwarenessApplied = [bool]$processDpiAwarenessApplied
        threadDpiAwareness = "per-monitor-v2"
        outputRoot = $outputRootPath
        locales = @($Locales)
        states = @("default", "maximized")
        plannedCaptureCount = $expectedCaptureCount
        expectedCaptureCount = $expectedCaptureCount - $runtimeSkippedCaptureCount
        actualCaptureCount = $cases.Count
        skippedDataDependentSurfaces = $skippedCases
        skippedProtectedSurfaces = @($protectedSkippedCases)
        cases = @($cases)
    }
    Assert-Condition ($receipt.actualCaptureCount -eq $receipt.expectedCaptureCount) "The five-edition capture matrix is incomplete after explicit protected-surface skips."
    $receiptPath = Join-Path $outputRootPath "receipt.json"
    Write-AtomicJson -Path $receiptPath -Value $receipt
    [pscustomobject]$receipt
}
finally {
    [DroneDreamInstalledVisualNative]::SetThreadDpiAwarenessContext(
        $previousThreadDpiContext
    ) | Out-Null
}
