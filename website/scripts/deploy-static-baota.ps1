[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SshKeyPath,

    [string]$ArtifactDirectory = "",

    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedCommit = ""
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
$globalTarget = $targets.global
$target = $targets.mirror
if ($null -eq $globalTarget -or $null -eq $target) {
    throw "Deployment target configuration must define global and mirror."
}
$Remote = [string]$target.remote
$PublicHost = [string]$target.publicHost
$PublicBaseUri = [string]$target.publicBaseUri
$VhostMode = [string]$target.vhostMode

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
if ([string]$globalTarget.platform -cne "github-pages" -or
    [string]$globalTarget.publicHost -cne "getdronedream.com" -or
    [string]$globalTarget.publicBaseUri -cne "https://getdronedream.com/" -or
    [string]$target.platform -cne "baota" -or
    $Remote -cne "root@47.93.180.216" -or
    $PublicHost -cne "47.93.180.216" -or
    $publicUri.Scheme -cne "http" -or
    $VhostMode -cne "install" -or
    [string]$globalTarget.artifactDirectory -cne
        [string]$target.artifactDirectory) {
    throw "Deployment targets do not match the approved GitHub Pages and bare-IP mirror topology."
}
if (-not (Test-Path -LiteralPath $SshKeyPath -PathType Leaf)) {
    throw "SSH private key file does not exist at the supplied path."
}
$resolvedKeyPath = (Resolve-Path -LiteralPath $SshKeyPath).Path

$sshPath = (Get-Command ssh.exe -ErrorAction Stop).Source
$scpPath = (Get-Command scp.exe -ErrorAction Stop).Source
$tarPath = (Get-Command tar.exe -ErrorAction Stop).Source
$configuredArtifactDirectory = Join-Path $repositoryRoot `
    ([string]$target.artifactDirectory)
if ([string]::IsNullOrWhiteSpace($ArtifactDirectory)) {
    $ArtifactDirectory = $configuredArtifactDirectory
}
if (-not (Test-Path -LiteralPath $ArtifactDirectory -PathType Container)) {
    throw "The shared website artifact directory does not exist: $ArtifactDirectory"
}
$siteDirectory = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$serverDeployScript = Join-Path $PSScriptRoot 'deploy-static-baota.sh'
$stagingConfig = Join-Path $repositoryRoot `
    'website\nginx\baota\dronedream-staging.conf'
$publicConfig = Join-Path $repositoryRoot `
    'website\nginx\baota\dronedream-public.conf'

$indexPath = Join-Path $siteDirectory 'index.html'
$manifestPath = Join-Path $siteDirectory 'SHA256SUMS'
$buildManifestPath = Join-Path $siteDirectory 'build-manifest.json'
$metadataPath = Join-Path $siteDirectory 'downloads\latest.json'
foreach ($requiredPath in @(
        $indexPath,
        $manifestPath,
        $buildManifestPath,
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
$buildManifest = Get-Content -LiteralPath $buildManifestPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$version = [string]$metadata.version
$installerName = [string]$metadata.fileName
$installerSha256 = ([string]$metadata.sha256).ToLowerInvariant()
$sourceCommit = ([string]$buildManifest.sourceCommit).ToLowerInvariant()
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "latest.json contains an invalid release version."
}
$expectedInstallerName = "DroneDream_${version}_x64-setup.exe"
$releaseTag = [string]$buildManifest.release.releaseTag
$expectedDownloadUrl = "https://github.com/ChiZhang-805/DroneDream/releases/download/" +
    "$releaseTag/$installerName"
$expectedChecksumUrl = "$expectedDownloadUrl.sha256"
if ([int]$buildManifest.schemaVersion -ne 1 -or
    [string]$buildManifest.artifactKind -cne "dronedream-shared-static-site" -or
    $sourceCommit -notmatch '^[0-9a-f]{40}$' -or
    ($ExpectedCommit -and $sourceCommit -cne $ExpectedCommit) -or
    [string]$buildManifest.origins.global -cne
        [string]$globalTarget.publicBaseUri -or
    [string]$buildManifest.origins.mirror -cne $PublicBaseUri -or
    [string]$buildManifest.release.version -cne $version -or
    [string]$buildManifest.release.fileName -cne $installerName -or
    ([string]$buildManifest.release.sha256).ToLowerInvariant() -cne
        $installerSha256 -or
    [long]$buildManifest.release.sizeBytes -ne [long]$metadata.sizeBytes -or
    [string]$buildManifest.release.publishedAt -cne
        [string]$metadata.publishedAt) {
    throw "build-manifest.json does not match the approved shared artifact contract."
}
if ($releaseTag -notmatch '^[A-Za-z0-9._-]+$' -or
    $installerName -cne $expectedInstallerName -or
    $installerSha256 -notmatch '^[0-9a-f]{64}$' -or
    [long]$metadata.sizeBytes -le 0 -or
    [string]$metadata.downloadUrl -cne $expectedDownloadUrl -or
    [string]$metadata.checksumUrl -cne $expectedChecksumUrl) {
    throw "latest.json contains inconsistent installer metadata."
}
Test-SiteIntegrityManifest -SiteDirectory $siteDirectory -ManifestPath $manifestPath
Write-Host "Verified shared website artifact $sourceCommit for DroneDream $version."

$publicConfigText = Get-Content -LiteralPath $publicConfig -Raw -Encoding UTF8
$configuredServerNames = @(
    [regex]::Matches(
        $publicConfigText,
        '(?m)^\s*server_name\s+([^;]+);'
    ) | ForEach-Object {
        $_.Groups[1].Value -split '\s+'
    }
)
if ($PublicHost -notin $configuredServerNames -or
    "cn.getdronedream.com" -in $configuredServerNames) {
    throw "The BaoTa mirror vhost must declare only the approved bare-IP host."
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
    $verifiedInstallerPath = Join-Path $temporaryRoot $installerName
    $verifiedChecksumPath = "$verifiedInstallerPath.sha256"
    Invoke-WebRequest -Uri "$expectedDownloadUrl?sha256=$installerSha256" `
        -UseBasicParsing -OutFile $verifiedInstallerPath -TimeoutSec 120
    Invoke-WebRequest -Uri "$expectedChecksumUrl?sha256=$installerSha256" `
        -UseBasicParsing -OutFile $verifiedChecksumPath -TimeoutSec 30
    $verifiedInstaller = Get-Item -LiteralPath $verifiedInstallerPath
    $verifiedInstallerSha256 = (Get-FileHash -LiteralPath $verifiedInstallerPath `
        -Algorithm SHA256).Hash.ToLowerInvariant()
    $verifiedChecksumLine = (
        Get-Content -LiteralPath $verifiedChecksumPath -Raw -Encoding UTF8
    ).Trim()
    if ($verifiedInstaller.Length -ne [long]$metadata.sizeBytes -or
        $verifiedInstallerSha256 -ne $installerSha256 -or
        $verifiedChecksumLine -notmatch (
            '^' + [regex]::Escape($installerSha256) + '\s+' +
            [regex]::Escape($installerName) + '$'
        )) {
        throw "The versioned GitHub release asset does not match the shared artifact metadata."
    }
    Write-Host "Verified the versioned GitHub release asset and checksum."

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
        "bash ./deploy-static-baota.sh ./dronedream-site.tar.gz '$version' '$installerSha256' ./dronedream-staging.conf ./dronedream-public.conf '$PublicHost'"
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
    if ([string]$publicMetadata.version -cne $version -or
        ([string]$publicMetadata.sha256).ToLowerInvariant() -cne
            $installerSha256 -or
        [string]$publicMetadata.downloadUrl -cne $expectedDownloadUrl -or
        [string]$publicMetadata.checksumUrl -cne $expectedChecksumUrl) {
        throw "The public release metadata does not match the deployed release."
    }

    $publicBuildManifest = (
        Invoke-WebRequest -Uri "$publicBase/build-manifest.json" `
            -UseBasicParsing -TimeoutSec 30
    ).Content | ConvertFrom-Json
    if ([string]$publicBuildManifest.sourceCommit -cne $sourceCommit -or
        [string]$publicBuildManifest.artifactKind -cne
            "dronedream-shared-static-site") {
        throw "The public build manifest does not identify the deployed shared artifact."
    }

    $publicIntegrityManifestPath = Join-Path $temporaryRoot `
        'public-SHA256SUMS'
    Invoke-WebRequest -Uri "$publicBase/SHA256SUMS" -UseBasicParsing `
        -OutFile $publicIntegrityManifestPath -TimeoutSec 30
    $localManifestSha256 = (Get-FileHash -LiteralPath $manifestPath `
        -Algorithm SHA256).Hash.ToLowerInvariant()
    $publicManifestSha256 = (Get-FileHash `
        -LiteralPath $publicIntegrityManifestPath -Algorithm SHA256).
        Hash.ToLowerInvariant()
    if ($publicManifestSha256 -cne $localManifestSha256) {
        throw "The mirror integrity manifest does not match the shared artifact."
    }

    $verifiedArtifactPaths = @()
    foreach ($line in Get-Content -LiteralPath $manifestPath -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw "SHA256SUMS contains an invalid entry during public verification."
        }
        $expectedHash = $Matches[1]
        $relativePath = $Matches[2]
        if ($relativePath -notmatch (
                '^(?:index|site|404)\.html$|' +
                '^(?:assets|console/assets)/.+\.(?:js|css)$|' +
                '^console/index\.html$'
            )) {
            continue
        }
        $downloadPath = Join-Path $temporaryRoot `
            ("public-artifact-" + [Guid]::NewGuid().ToString('N'))
        Invoke-WebRequest -Uri "$publicBase/$relativePath" -UseBasicParsing `
            -OutFile $downloadPath -TimeoutSec 30
        $actualHash = (Get-FileHash -LiteralPath $downloadPath `
            -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -cne $expectedHash) {
            throw "The mirror artifact differs from the shared artifact: $relativePath"
        }
        $verifiedArtifactPaths += $relativePath
    }
    if ($verifiedArtifactPaths.Count -lt 4) {
        throw "The public artifact parity check covered too few HTML, JS, and CSS files."
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
    Write-Host "Shared artifact source commit: $sourceCommit"
    Write-Host "Verified $($verifiedArtifactPaths.Count) public HTML, JS, and CSS files byte-for-byte."
    Write-Host "Installer SHA-256: $installerSha256"
    Write-Host "Verified the versioned public installer independently from the site artifact."
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
