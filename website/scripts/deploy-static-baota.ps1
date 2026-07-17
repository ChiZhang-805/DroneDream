[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SshKeyPath,

    [string]$Remote = "root@47.93.180.216",
    [string]$PublicHost = "47.93.180.216",
    [string]$PublicBaseUri = "http://47.93.180.216/",
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,

        [string[]]$CommandArguments = @()
    )

    & $CommandPath @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed with exit code $LASTEXITCODE`: $CommandPath"
    }
}

function Test-SiteIntegrityManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SiteDirectory,

        [Parameter(Mandatory = $true)]
        [string]$ManifestPath
    )

    $siteRoot = [IO.Path]::GetFullPath($SiteDirectory).TrimEnd('\', '/')
    $sitePrefix = "$siteRoot$([IO.Path]::DirectorySeparatorChar)"
    $entryCount = 0
    foreach ($line in Get-Content -LiteralPath $ManifestPath -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw "SHA256SUMS contains an invalid entry."
        }
        $expectedHash = $Matches[1]
        $relativePath = $Matches[2]
        if ([IO.Path]::IsPathRooted($relativePath) -or
            $relativePath.Contains('\') -or
            $relativePath -match '(^|/)\.\.(/|$)') {
            throw "SHA256SUMS contains an unsafe path: $relativePath"
        }
        $localPath = [IO.Path]::GetFullPath(
            (Join-Path $siteRoot ($relativePath.Replace('/', '\')))
        )
        if (-not $localPath.StartsWith($sitePrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "SHA256SUMS path escapes the generated site: $relativePath"
        }
        if (-not (Test-Path -LiteralPath $localPath -PathType Leaf)) {
            throw "SHA256SUMS references a missing file: $relativePath"
        }
        $actualHash = (Get-FileHash -LiteralPath $localPath -Algorithm SHA256).
            Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "SHA256SUMS mismatch: $relativePath"
        }
        $entryCount++
    }
    if ($entryCount -eq 0) {
        throw "SHA256SUMS does not contain any files."
    }
}

function Get-ResponseHeader {
    param(
        [Parameter(Mandatory = $true)]
        $Response,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $value = $Response.Headers[$Name]
    if ($null -eq $value) {
        return ""
    }
    return [string]($value -join ", ")
}

if ($Remote -notmatch '^[A-Za-z_][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*$') {
    throw "Remote must use the safe user@host form without SSH options or paths."
}
if ($PublicHost -notmatch '^[0-9A-Za-z.-]+$') {
    throw "PublicHost contains unsupported characters."
}
try {
    $publicUri = [Uri]$PublicBaseUri
} catch {
    throw "PublicBaseUri must be an absolute HTTP or HTTPS URI."
}
if (-not $publicUri.IsAbsoluteUri -or
    $publicUri.Scheme -notin @('http', 'https') -or
    -not [string]::IsNullOrEmpty($publicUri.UserInfo) -or
    -not [string]::IsNullOrEmpty($publicUri.Query) -or
    -not [string]::IsNullOrEmpty($publicUri.Fragment) -or
    $publicUri.AbsolutePath -notin @('', '/') -or
    $publicUri.DnsSafeHost -ne $PublicHost) {
    throw "PublicBaseUri must be the root HTTP(S) URI for PublicHost."
}
if (-not (Test-Path -LiteralPath $SshKeyPath -PathType Leaf)) {
    throw "SSH private key file does not exist at the supplied path."
}
$resolvedKeyPath = (Resolve-Path -LiteralPath $SshKeyPath).Path

$sshPath = (Get-Command ssh.exe -ErrorAction Stop).Source
$scpPath = (Get-Command scp.exe -ErrorAction Stop).Source
$tarPath = (Get-Command tar.exe -ErrorAction Stop).Source
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$siteDirectory = Join-Path $repositoryRoot 'frontend\site-dist'
$buildScript = Join-Path $PSScriptRoot 'build-release-site.ps1'
$serverDeployScript = Join-Path $PSScriptRoot 'deploy-static-baota.sh'
$stagingConfig = Join-Path $repositoryRoot `
    'website\nginx\baota\dronedream-staging.conf'
$publicConfig = Join-Path $repositoryRoot `
    'website\nginx\baota\dronedream-public.conf'

if (-not $SkipBuild) {
    $windowsPowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
    Invoke-NativeCommand -CommandPath $windowsPowerShell -CommandArguments @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $buildScript
    )
}

$indexPath = Join-Path $siteDirectory 'index.html'
$manifestPath = Join-Path $siteDirectory 'SHA256SUMS'
$metadataPath = Join-Path $siteDirectory 'downloads\latest.json'
foreach ($requiredPath in @(
        $indexPath,
        $manifestPath,
        $metadataPath,
        $serverDeployScript,
        $stagingConfig,
        $publicConfig
    )) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required deployment input is missing: $requiredPath"
    }
}

$metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$version = [string]$metadata.version
$installerName = [string]$metadata.fileName
$installerSha256 = ([string]$metadata.sha256).ToLowerInvariant()
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "latest.json contains an invalid release version."
}
$expectedInstallerName = "DroneDream_${version}_x64-setup.exe"
if ($installerName -ne $expectedInstallerName -or
    $installerSha256 -notmatch '^[0-9a-f]{64}$' -or
    [string]$metadata.downloadUrl -ne "/downloads/$installerName" -or
    [string]$metadata.checksumUrl -ne "/downloads/$installerName.sha256") {
    throw "latest.json contains inconsistent installer metadata."
}
$installerPath = Join-Path $siteDirectory "downloads\$installerName"
$installerChecksumPath = "$installerPath.sha256"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $installerChecksumPath -PathType Leaf)) {
    throw "latest.json references a missing installer or checksum file."
}
$installer = Get-Item -LiteralPath $installerPath
if ([long]$metadata.sizeBytes -ne $installer.Length) {
    throw "latest.json installer size does not match the generated EXE."
}
$actualInstallerSha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).
    Hash.ToLowerInvariant()
if ($actualInstallerSha256 -ne $installerSha256) {
    throw "latest.json installer SHA-256 does not match the generated EXE."
}
$checksumLine = (Get-Content -LiteralPath $installerChecksumPath -Raw -Encoding UTF8).Trim()
if ($checksumLine -notmatch (
        '^' + [regex]::Escape($installerSha256) + '\s+' +
        [regex]::Escape($installerName) + '$'
    )) {
    throw "The published installer checksum file is inconsistent."
}
Test-SiteIntegrityManifest -SiteDirectory $siteDirectory -ManifestPath $manifestPath

$publicConfigText = Get-Content -LiteralPath $publicConfig -Raw -Encoding UTF8
$serverNamePattern = '(?m)^\s*server_name\s+' +
    [regex]::Escape($PublicHost) + ';\s*$'
if ($publicConfigText -notmatch $serverNamePattern) {
    throw "The BaoTa public vhost does not declare server_name $PublicHost."
}

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) `
    ("DroneDream-deploy-" + [Guid]::NewGuid().ToString('N'))
$archivePath = Join-Path $temporaryRoot 'dronedream-site.tar.gz'
$remoteDirectory = '/root/.cache/dronedream-deploy/' +
    [Guid]::NewGuid().ToString('N')
$remoteDirectoryCreated = $false
$sshOptions = @(
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=yes',
    '-o', 'ConnectTimeout=15',
    '-o', 'ServerAliveInterval=15',
    '-i', $resolvedKeyPath
)

New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
try {
    Invoke-NativeCommand -CommandPath $tarPath -CommandArguments @(
        '--create',
        '--gzip',
        '--file', $archivePath,
        '--directory', $siteDirectory,
        '.'
    )
    $archiveSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).
        Hash.ToLowerInvariant()

    $prepareRemoteArguments = @()
    $prepareRemoteArguments += $sshOptions
    $prepareRemoteArguments += $Remote
    $prepareRemoteArguments += "set -eu; install -d -m 0700 '$remoteDirectory'"
    Invoke-NativeCommand -CommandPath $sshPath `
        -CommandArguments $prepareRemoteArguments
    $remoteDirectoryCreated = $true

    foreach ($uploadPath in @(
            $archivePath,
            $serverDeployScript,
            $stagingConfig,
            $publicConfig
        )) {
        $scpArguments = @()
        $scpArguments += $sshOptions
        $scpArguments += $uploadPath
        $scpArguments += "${Remote}:$remoteDirectory/"
        Invoke-NativeCommand -CommandPath $scpPath -CommandArguments $scpArguments
    }

    $remoteDeployCommand = @(
        'set -eu',
        "cd '$remoteDirectory'",
        "printf '%s  %s\n' '$archiveSha256' 'dronedream-site.tar.gz' | sha256sum --check -",
        "bash ./deploy-static-baota.sh ./dronedream-site.tar.gz '$version' '$installerSha256' ./dronedream-staging.conf ./dronedream-public.conf '$PublicHost'"
    ) -join '; '
    $deployArguments = @()
    $deployArguments += $sshOptions
    $deployArguments += $Remote
    $deployArguments += $remoteDeployCommand
    Invoke-NativeCommand -CommandPath $sshPath -CommandArguments $deployArguments

    $publicBase = $publicUri.GetLeftPart([UriPartial]::Authority).TrimEnd('/')
    $homeResponse = Invoke-WebRequest -Uri "$publicBase/" -UseBasicParsing `
        -TimeoutSec 30
    if ($homeResponse.StatusCode -ne 200 -or
        $homeResponse.Content -notmatch '<title>DroneDream') {
        throw "The public homepage did not pass the post-deployment probe."
    }
    $metadataResponse = Invoke-WebRequest `
        -Uri "$publicBase/downloads/latest.json" `
        -UseBasicParsing -TimeoutSec 30
    $publicMetadata = $metadataResponse.Content | ConvertFrom-Json
    if ([string]$publicMetadata.version -ne $version -or
        ([string]$publicMetadata.sha256).ToLowerInvariant() -ne $installerSha256) {
        throw "The public release metadata does not match the deployed release."
    }

    $assetMatches = [regex]::Matches(
        $homeResponse.Content,
        '(?i)(?:src|href)="(/assets/[^"?]+)'
    )
    $assetPaths = @($assetMatches | ForEach-Object { $_.Groups[1].Value } |
        Sort-Object -Unique)
    if ($assetPaths.Count -eq 0) {
        throw "The public homepage does not reference any hashed assets."
    }
    foreach ($assetPath in $assetPaths) {
        $assetResponse = Invoke-WebRequest -Uri "$publicBase$assetPath" `
            -UseBasicParsing -TimeoutSec 30
        $cacheControl = Get-ResponseHeader -Response $assetResponse `
            -Name 'Cache-Control'
        if ($assetResponse.StatusCode -ne 200 -or
            $cacheControl -notmatch '(?i)max-age=31536000' -or
            $cacheControl -notmatch '(?i)immutable') {
            throw "A public hashed asset failed its cache-policy probe: $assetPath"
        }
    }

    Write-Host "Deployed DroneDream $version to $publicBase"
    Write-Host "Installer SHA-256: $installerSha256"
} finally {
    if ($remoteDirectoryCreated) {
        try {
            $cleanupArguments = @()
            $cleanupArguments += $sshOptions
            $cleanupArguments += $Remote
            $cleanupArguments += "rm -rf -- '$remoteDirectory'"
            Invoke-NativeCommand -CommandPath $sshPath `
                -CommandArguments $cleanupArguments
        } catch {
            Write-Warning "Remote deployment staging cleanup failed: $($_.Exception.Message)"
        }
    }
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
