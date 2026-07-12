param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [ValidateSet("English", "SimpChinese")]
    [string]$Language = "English",
    [string]$ExpectedTarget = "E:\DroneDream"
)

$ErrorActionPreference = "Stop"

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class DroneDreamInstallerUi {
    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern IntPtr GetDlgItem(IntPtr hwnd, int id);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int count);

    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hwnd);

    [DllImport("user32.dll")]
    public static extern bool EnumChildWindows(IntPtr hwnd, EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam);

    public static string ReadText(IntPtr hwnd) {
        var length = GetWindowTextLength(hwnd);
        var buffer = new StringBuilder(Math.Max(length + 1, 2));
        GetWindowText(hwnd, buffer, buffer.Capacity);
        return buffer.ToString();
    }

    public static string ReadDescendants(IntPtr root) {
        var values = new List<string>();
        EnumChildWindows(root, delegate(IntPtr hwnd, IntPtr unused) {
            var value = ReadText(hwnd);
            if (!String.IsNullOrWhiteSpace(value)) values.Add(value.Trim());
            return true;
        }, IntPtr.Zero);
        return String.Join("\n", values);
    }
}
"@

$BM_CLICK = 0x00F5
$CB_SETCURSEL = 0x014E
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$process = $null
$zhWelcome = (-join ([char[]](27426, 36814, 20351, 29992))) + " DroneDream"
$zhInstallLocation = -join ([char[]](36873, 25321, 23433, 35013, 20301, 32622))
$zhInstallContent = -join ([char[]](36873, 25321, 23433, 35013, 20869, 23481))
$zhInstallEverything = -join ([char[]](23433, 35013, 20840, 37096, 65288, 25512, 33616, 65289))

function Wait-InstallerWindow {
    param(
        [Diagnostics.Process]$Process,
        [scriptblock]$Condition,
        [int]$TimeoutSeconds = 30
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastTitle = ""
    $lastBody = ""
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            throw "Installer exited unexpectedly with code $($Process.ExitCode)"
        }
        $Process.Refresh()
        $handle = $Process.MainWindowHandle
        if ($handle -ne [IntPtr]::Zero) {
            $title = [DroneDreamInstallerUi]::ReadText($handle)
            $body = [DroneDreamInstallerUi]::ReadDescendants($handle)
            $lastTitle = $title
            $lastBody = $body
            if (& $Condition $handle $title $body) {
                return @{ Handle = $handle; Title = $title; Body = $body }
            }
        }
        Start-Sleep -Milliseconds 150
    }
    throw "Timed out waiting for the expected installer page. Last title='$lastTitle' controls='$lastBody'"
}

try {
    $process = Start-Process -FilePath $installerPath -PassThru
    $languageDialog = Wait-InstallerWindow -Process $process -Condition {
        param($handle, $title, $body)
        [DroneDreamInstallerUi]::GetDlgItem($handle, 1002) -ne [IntPtr]::Zero
    }
    $languageIndex = if ($Language -eq "English") { 0 } else { 1 }
    $combo = [DroneDreamInstallerUi]::GetDlgItem($languageDialog.Handle, 1002)
    [void][DroneDreamInstallerUi]::SendMessage($combo, $CB_SETCURSEL, [IntPtr]$languageIndex, [IntPtr]::Zero)
    $ok = [DroneDreamInstallerUi]::GetDlgItem($languageDialog.Handle, 1)
    [void][DroneDreamInstallerUi]::SendMessage($ok, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero)

    $welcomeNeedle = if ($Language -eq "English") { "Welcome to DroneDream Setup" } else { $zhWelcome }
    $locationNeedle = if ($Language -eq "English") { "Choose Install Location" } else { $zhInstallLocation }
    $firstPage = Wait-InstallerWindow -Process $process -Condition {
        param($handle, $title, $body)
        $body.Contains($welcomeNeedle) -or $body.Contains($locationNeedle)
    }
    if ($firstPage.Body.Contains($welcomeNeedle)) {
        $welcomeNext = [DroneDreamInstallerUi]::GetDlgItem($firstPage.Handle, 1)
        [void][DroneDreamInstallerUi]::PostMessage($welcomeNext, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    $locationPage = Wait-InstallerWindow -Process $process -Condition {
        param($handle, $title, $body)
        $body.Contains($locationNeedle)
    }
    $next = [DroneDreamInstallerUi]::GetDlgItem($locationPage.Handle, 1)
    [void][DroneDreamInstallerUi]::PostMessage($next, $BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero)

    $runtimeNeedle = if ($Language -eq "English") { "Choose what to install" } else { $zhInstallContent }
    $fullNeedle = if ($Language -eq "English") { "Install everything (recommended)" } else { $zhInstallEverything }
    $forbiddenNeedle = if ($Language -eq "English") { $zhInstallContent } else { "Choose what to install" }
    $runtimePage = Wait-InstallerWindow -Process $process -TimeoutSeconds 45 -Condition {
        param($handle, $title, $body)
        $body.Contains($runtimeNeedle)
    }
    if (-not $runtimePage.Body.Contains($fullNeedle)) {
        throw "The full-install option was not rendered in $Language"
    }
    if ($runtimePage.Body.Contains($forbiddenNeedle)) {
        throw "The $Language page contains text from the other locale"
    }
    if (-not $runtimePage.Body.Contains($ExpectedTarget)) {
        throw "The Runtime page did not recommend $ExpectedTarget"
    }

    Write-Host "Interactive installer UI verified: language=$Language target=$ExpectedTarget"
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
        $process.WaitForExit()
    }
    if ($null -ne $process) {
        $process.Dispose()
    }
}
