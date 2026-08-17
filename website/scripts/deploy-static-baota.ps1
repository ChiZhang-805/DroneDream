[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SshKeyPath,

    [ValidateSet("Production", "Preview")]
    [string]$TargetMode = "Production",

    [string]$Remote = "",
    [string]$PublicHost = "",
    [string]$PublicBaseUri = "",

    [ValidateSet("preserve", "install")]
    [string]$VhostMode = "preserve",

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

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$targetConfigPath = Join-Path $repositoryRoot 'website\deployment-targets.json'
if (-not (Test-Path -LiteralPath $targetConfigPath -PathType Leaf)) {
    throw "Deployment target configuration is missing: $targetConfigPath"
}
$targets = Get-Content -LiteralPath $targetConfigPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$targetName = $TargetMode.ToLowerInvariant()
$target = $targets.$targetName
if ($null -eq $target) {
    throw "Deployment target configuration does not define $targetName."
}
if ([string]::IsNullOrWhiteSpace($Remote)) {
    $Remote = [string]$target.remote
}
if ([string]::IsNullOrWhiteSpace($PublicHost)) {
    $PublicHost = [string]$target.publicHost
}
if ([string]::IsNullOrWhiteSpace($PublicBaseUri)) {
    $PublicBaseUri = [string]$target.publicBaseUri
}
if (-not $PSBoundParameters.ContainsKey("VhostMode")) {
    $VhostMode = [string]$target.vhostMode
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
    -not $publicUri.IsDefaultPort -or
    $publicUri.DnsSafeHost -ne $PublicHost) {
    throw "PublicBaseUri must be the default-port root HTTP(S) URI for PublicHost."
}
$expectedRemote = [string]$target.remote
$expectedHost = [string]$target.publicHost
$expectedScheme = ([Uri][string]$target.publicBaseUri).Scheme
$expectedVhostMode = [string]$target.vhostMode
if ($Remote -cne $expectedRemote -or
    $PublicHost -cne $expectedHost -or
    $publicUri.Scheme -cne $expectedScheme -or
    $VhostMode -cne $expectedVhostMode) {
    throw (
        "$TargetMode deployments require Remote=$expectedRemote, " +
        "PublicHost=$expectedHost, " +
        "scheme=$expectedScheme, and VhostMode=$expectedVhostMode."
    )
}
if ($TargetMode -ceq "Production" -and $publicUri.Scheme -cne "https") {
    throw "Production deployments require HTTPS."
}
if ($TargetMode -ceq "Preview" -and $publicUri.Scheme -cne "http") {
    throw "Preview deployments use the explicit bare-IP HTTP target."
}
if (-not (Test-Path -LiteralPath $SshKeyPath -PathType Leaf)) {
    throw "SSH private key file does not exist at the supplied path."
}
$resolvedKeyPath = (Resolve-Path -LiteralPath $SshKeyPath).Path

$sshPath = (Get-Command ssh.exe -ErrorAction Stop).Source
$scpPath = (Get-Command scp.exe -ErrorAction Stop).Source
$tarPath = (Get-Command tar.exe -ErrorAction Stop).Source
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
$hasEdition = $null -ne $metadata.PSObject.Properties['edition']
$hasBuildNumber = $null -ne $metadata.PSObject.Properties['buildNumber']
if ($hasEdition -xor $hasBuildNumber) {
    throw "latest.json edition metadata is incomplete."
}
if ($hasEdition) {
    $editionProducts = @{
        universal = "DroneDream-Universal"
        sim = "DroneDream-Sim"
        lab = "DroneDream-Lab"
        field = "DroneDream-Field"
    }
    $edition = [string]$metadata.edition
    $buildNumber = [long]$metadata.buildNumber
    if (-not $editionProducts.ContainsKey($edition) -or $buildNumber -le 0) {
        throw "latest.json contains invalid edition release metadata."
    }
    $expectedInstallerName = "$($editionProducts[$edition])-$version.exe"
} else {
    $expectedInstallerName = "DroneDream_${version}_x64-setup.exe"
}
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
Write-Host "Verified local website release manifest for DroneDream $version."

$publicConfigText = Get-Content -LiteralPath $publicConfig -Raw -Encoding UTF8
$configuredServerNames = @(
    [regex]::Matches(
        $publicConfigText,
        '(?m)^\s*server_name\s+([^;]+);'
    ) | ForEach-Object {
        $_.Groups[1].Value -split '\s+'
    }
)
foreach ($requiredServerName in @(
        [string]$targets.production.publicHost,
        [string]$targets.preview.publicHost
    )) {
    if ($requiredServerName -notin $configuredServerNames) {
        throw "The BaoTa managed vhost does not declare server_name $requiredServerName."
    }
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
    Write-Host "Packed the website release archive."

    $prepareRemoteArguments = @()
    $prepareRemoteArguments += $sshOptions
    $prepareRemoteArguments += $Remote
    $prepareRemoteArguments += "set -eu; install -d -m 0700 '$remoteDirectory'"
    Invoke-NativeCommand -CommandPath $sshPath `
        -CommandArguments $prepareRemoteArguments
    $remoteDirectoryCreated = $true
    Write-Host "Prepared the remote deployment staging directory."

    foreach ($uploadPath in @(
            $archivePath,
            $serverDeployScript,
            $stagingConfig,
            $publicConfig
        )) {
        $scpArguments = @()
        # Windows OpenSSH can stall while negotiating the default SFTP transport
        # against this Baota host. The legacy SCP transport is deterministic here.
        $scpArguments += '-O'
        $scpArguments += $sshOptions
        $scpArguments += $uploadPath
        $scpArguments += "${Remote}:$remoteDirectory/"
        Invoke-NativeCommand -CommandPath $scpPath -CommandArguments $scpArguments
        Write-Host "Uploaded $([IO.Path]::GetFileName($uploadPath))."
    }

    $remoteDeployCommand = @(
        'set -eu',
        "cd '$remoteDirectory'",
        "printf '%s  %s\n' '$archiveSha256' 'dronedream-site.tar.gz' | sha256sum --check -",
        "bash ./deploy-static-baota.sh ./dronedream-site.tar.gz '$version' '$installerSha256' ./dronedream-staging.conf ./dronedream-public.conf '$PublicHost' '$($publicUri.Scheme)' '$VhostMode'"
    ) -join '; '
    $deployArguments = @()
    $deployArguments += $sshOptions
    $deployArguments += $Remote
    $deployArguments += $remoteDeployCommand
    Invoke-NativeCommand -CommandPath $sshPath -CommandArguments $deployArguments
    Write-Host "Activated the remote release; starting public verification."

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

    # Treat the public download path as part of the release, not as a separate
    # best-effort upload. A cache-busting query also verifies that Nginx applies
    # its download rules by normalized URI rather than accidentally falling
    # back to the generic cache policy when a query string is present.
    $publicInstallerPath = Join-Path $temporaryRoot 'public-installer.exe'
    $publicInstallerUri = "$publicBase$([string]$publicMetadata.downloadUrl)" +
        "?sha256=$installerSha256"
    $publicInstallerResponse = Invoke-WebRequest -Uri $publicInstallerUri `
        -UseBasicParsing -OutFile $publicInstallerPath -PassThru -TimeoutSec 120
    $publicInstallerCacheControl = Get-ResponseHeader `
        -Response $publicInstallerResponse -Name 'Cache-Control'
    $publicInstallerDisposition = Get-ResponseHeader `
        -Response $publicInstallerResponse -Name 'Content-Disposition'
    $publicInstaller = Get-Item -LiteralPath $publicInstallerPath
    $publicInstallerSha256 = (Get-FileHash -LiteralPath $publicInstallerPath `
        -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($publicInstaller.Length -ne $installer.Length -or
        $publicInstallerSha256 -ne $installerSha256 -or
        $publicInstallerCacheControl -notmatch '(?i)(?:^|,)\s*no-cache(?:,|$)' -or
        $publicInstallerDisposition -notmatch '(?i)^attachment(?:;|$)') {
        throw "The public installer re-download did not match the local release or download policy."
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
    Write-Host "Verified the public installer by re-downloading and hashing it."
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
