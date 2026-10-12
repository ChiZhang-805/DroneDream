param(
    [Parameter(Mandatory=$true)][string]$ExecutablePath,
    [ValidateSet('Check','Stop')][string]$Action='Check'
)
$ErrorActionPreference='Stop'
if (!(Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) { exit 0 }

# Resolve the actual file: packaged Windows hosts can redirect LocalAppData.
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class InstalledAppPath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint GetFinalPathNameByHandle(SafeFileHandle file, StringBuilder path, uint size, uint flags);
}
'@
$file=[IO.File]::OpenRead($ExecutablePath)
try {
    $buffer=[Text.StringBuilder]::new(32768)
    $length=[InstalledAppPath]::GetFinalPathNameByHandle($file.SafeFileHandle,$buffer,32768,0)
    if ($length -eq 0 -or $length -ge 32768) { throw 'Cannot resolve installed executable' }
    $target=$buffer.ToString()
    if ($target.StartsWith('\\?\UNC\')) { $target='\\'+$target.Substring(8) }
    elseif ($target.StartsWith('\\?\')) { $target=$target.Substring(4) }
} finally { $file.Dispose() }

$name=[IO.Path]::GetFileNameWithoutExtension($ExecutablePath)
$matching=@(Get-Process -Name $name -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $target })
if ($Action -eq 'Check') { if ($matching.Count) { exit 10 }; exit 0 }
foreach ($app in $matching) {
    # The installer has already obtained consent to stop this installation.
    # Never use a process-name-wide kill: every edition uses the same filename.
    $app.Kill()
    if (!$app.WaitForExit(15000)) { throw 'Installed application did not stop' }
}
exit 0
