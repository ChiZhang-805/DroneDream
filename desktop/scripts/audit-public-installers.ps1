param(
    [Parameter(Mandatory = $true)]
    [string]$GlobalInstaller,
    [Parameter(Mandatory = $true)]
    [string]$GlobalChecksum,
    [Parameter(Mandatory = $true)]
    [string]$MirrorInstaller,
    [Parameter(Mandatory = $true)]
    [string]$MirrorChecksum,
    [Parameter(Mandatory = $true)]
    [string]$WebsiteReceipt,
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseTag,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseTargetCommit,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseInventorySourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$AuditorCommit,
    [Parameter(Mandatory = $true)]
    [string]$GeneratedAt,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [Parameter(Mandatory = $true)]
    [string]$Sha256Output,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$globalInstallerPath = (Resolve-Path -LiteralPath $GlobalInstaller).Path
$globalChecksumPath = (Resolve-Path -LiteralPath $GlobalChecksum).Path
$mirrorInstallerPath = (Resolve-Path -LiteralPath $MirrorInstaller).Path
$mirrorChecksumPath = (Resolve-Path -LiteralPath $MirrorChecksum).Path
$websiteReceiptPath = (Resolve-Path -LiteralPath $WebsiteReceipt).Path
$backendScript = (
    Resolve-Path -LiteralPath (
        Join-Path $PSScriptRoot "..\..\backend\scripts\audit_public_installers.py"
    )
).Path
$outputPath = [IO.Path]::GetFullPath($Output)
$sha256OutputPath = [IO.Path]::GetFullPath($Sha256Output)

# These observations intentionally come from Windows itself. The caller cannot
# provide or override either status through a wrapper parameter.
$globalSignature = Get-AuthenticodeSignature -LiteralPath $globalInstallerPath
$mirrorSignature = Get-AuthenticodeSignature -LiteralPath $mirrorInstallerPath

& $Python $backendScript generate `
    --global-installer $globalInstallerPath `
    --global-checksum $globalChecksumPath `
    --mirror-installer $mirrorInstallerPath `
    --mirror-checksum $mirrorChecksumPath `
    --website-receipt $websiteReceiptPath `
    --global-authenticode-status ([string]$globalSignature.Status) `
    --mirror-authenticode-status ([string]$mirrorSignature.Status) `
    --version $Version `
    --release-tag $ReleaseTag `
    --release-target-commit $ReleaseTargetCommit `
    --release-inventory-source-commit $ReleaseInventorySourceCommit `
    --auditor-commit $AuditorCommit `
    --generated-at $GeneratedAt `
    --output $outputPath `
    --sha256-output $sha256OutputPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& $Python $backendScript verify `
    --audit $outputPath `
    --sha256 $sha256OutputPath `
    --exact-sources `
    --global-installer $globalInstallerPath `
    --global-checksum $globalChecksumPath `
    --mirror-installer $mirrorInstallerPath `
    --mirror-checksum $mirrorChecksumPath `
    --website-receipt $websiteReceiptPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host (
    "Public installer origin audit verified. " +
    "Global Authenticode=$($globalSignature.Status); " +
    "mirror Authenticode=$($mirrorSignature.Status); no publication performed."
)
