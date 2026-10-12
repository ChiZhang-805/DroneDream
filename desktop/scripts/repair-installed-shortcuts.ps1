param(
    [ValidateSet('all', 'universal', 'sim', 'lab', 'field', 'autonomy')]
    [string]$Edition = 'all',
    [Parameter(Mandatory = $true)][string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$contract = Get-Content (Join-Path $repoRoot 'distribution\desktop\edition-coexistence.v1.json') -Raw | ConvertFrom-Json
$output = [IO.Path]::GetFullPath($OutputRoot)
[IO.Directory]::CreateDirectory($output) | Out-Null

# Packaged developer hosts can redirect LocalAppData. Explorer does not inherit
# that mapping: shortcut targets and icon sources must name the physical file.
if (-not ('DroneDream.ShortcutPaths' -as [type])) {
    Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace DroneDream {
    public static class ShortcutPaths {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        public static extern uint GetFinalPathNameByHandle(SafeFileHandle file, StringBuilder path, uint size, uint flags);
        [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
        public static extern void SHChangeNotify(uint change, uint flags, string item1, IntPtr item2);
    }
}
'@
}

function Resolve-PhysicalFile([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $buffer = [Text.StringBuilder]::new(32768)
        $length = [DroneDream.ShortcutPaths]::GetFinalPathNameByHandle($stream.SafeFileHandle, $buffer, 32768, 0)
        if ($length -eq 0 -or $length -ge 32768) { throw "Cannot resolve installed file: $Path" }
        $physical = $buffer.ToString()
        if ($physical.StartsWith('\\?\UNC\')) { return '\\' + $physical.Substring(8) }
        if ($physical.StartsWith('\\?\')) { return $physical.Substring(4) }
        return $physical
    } finally { $stream.Dispose() }
}

$shell = New-Object -ComObject WScript.Shell
$records = [Collections.Generic.List[object]]::new()
try {
    foreach ($entry in $contract.editions) {
        if ($Edition -ne 'all' -and $entry.editionId -ne $Edition) { continue }
        $logical = Join-Path ([Environment]::ExpandEnvironmentVariables($entry.installRoot)) 'drone-dream-desktop.exe'
        if (-not (Test-Path -LiteralPath $logical -PathType Leaf)) { continue }
        $physical = Resolve-PhysicalFile $logical
        $paths = @(
            Join-Path ([Environment]::GetFolderPath('Desktop')) "$($entry.desktopShortcutName).lnk"
            Get-ChildItem -LiteralPath ([Environment]::GetFolderPath('Programs')) -Filter "$($entry.desktopShortcutName).lnk" -Recurse -File | Select-Object -ExpandProperty FullName
        ) | Select-Object -Unique
        foreach ($path in $paths) {
            # Respect missing shortcuts and links owned by other installations.
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
            $link = $shell.CreateShortcut($path)
            try {
                $before = [ordered]@{ target = $link.TargetPath; icon = $link.IconLocation; workingDirectory = $link.WorkingDirectory }
                if ($before.target -ine $logical -and $before.target -ine $physical) { continue }
                $backup = Join-Path $output ("{0}-{1}.lnk" -f $entry.editionId, [Guid]::NewGuid().ToString('N'))
                Copy-Item -LiteralPath $path -Destination $backup
                $link.TargetPath = $physical
                $link.IconLocation = "$physical,0"
                $link.WorkingDirectory = Split-Path -Parent $physical
                $link.Save()
                $records.Add([ordered]@{ edition = $entry.editionId; shortcut = $path; backup = $backup; before = $before; target = $physical; icon = "$physical,0" })
                [DroneDream.ShortcutPaths]::SHChangeNotify(0x2000, 0x1005, $path, [IntPtr]::Zero)
            } finally { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($link) | Out-Null }
        }
    }
    [DroneDream.ShortcutPaths]::SHChangeNotify(0x08000000, 0, $null, [IntPtr]::Zero)
} finally { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
$records.ToArray() | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $output 'shortcut-repair.json')
$records.ToArray() | ForEach-Object { [pscustomobject]$_ } | Select-Object edition, shortcut, target | ConvertTo-Json -Compress
