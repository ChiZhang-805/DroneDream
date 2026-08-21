param(
    [Parameter(Mandatory = $true)]
    [string] $UninstallerPath,

    [Parameter(Mandatory = $true)]
    [string] $InstallRoot
)

$ErrorActionPreference = "Stop"

$uninstallerFull = [System.IO.Path]::GetFullPath($UninstallerPath)
$installRootFull = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd("\", "/")
$installRootPrefix = $installRootFull + [System.IO.Path]::DirectorySeparatorChar

if (-not $uninstallerFull.StartsWith(
    $installRootPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Uninstaller must be located inside the declared install root"
}
if (-not (Test-Path -LiteralPath $uninstallerFull -PathType Leaf)) {
    throw "NSIS uninstaller was not found: $uninstallerFull"
}

# NSIS uninstallers normally start a short-lived launcher that copies itself to
# a temporary directory. Waiting for that launcher is not the same as waiting
# for the copied uninstaller. Run the copied executable explicitly with NSIS's
# documented _?= install-root override so the lifecycle check observes the
# process that executes the Uninstall section.
$systemTemp = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::GetTempPath()
).TrimEnd("\", "/")
$systemTempPrefix = $systemTemp + [System.IO.Path]::DirectorySeparatorChar
$temporaryRoot = Join-Path $systemTemp (
    "dronedream-nsis-uninstall-{0}" -f [Guid]::NewGuid().ToString("N")
)
$temporaryRootFull = [System.IO.Path]::GetFullPath($temporaryRoot)
if (-not $temporaryRootFull.StartsWith(
    $systemTempPrefix,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to create an uninstaller copy outside the system temp root"
}

$temporaryUninstaller = Join-Path $temporaryRootFull "uninstall-runner.exe"
$uninstallProcess = $null

try {
    New-Item -ItemType Directory -Path $temporaryRootFull | Out-Null
    Copy-Item -LiteralPath $uninstallerFull -Destination $temporaryUninstaller

    # NSIS requires _?= to be the final argument. Its value consumes the rest
    # of the command line, so an install root containing spaces remains intact.
    $uninstallProcess = Start-Process -FilePath $temporaryUninstaller `
        -ArgumentList @("/S", "_?=$installRootFull") -Wait -PassThru
    if ($uninstallProcess.ExitCode -ne 0) {
        throw "Silent NSIS uninstaller failed with exit code $($uninstallProcess.ExitCode)"
    }
}
finally {
    if ($null -ne $uninstallProcess -and -not $uninstallProcess.HasExited) {
        $uninstallProcess.Kill()
        $uninstallProcess.WaitForExit()
    }

    # The resolved path was proven to be a GUID child of the system temp root.
    if (Test-Path -LiteralPath $temporaryRootFull) {
        Remove-Item -LiteralPath $temporaryRootFull -Recurse -Force
    }
}

Write-Host "Silent NSIS uninstall section completed for: $installRootFull"
