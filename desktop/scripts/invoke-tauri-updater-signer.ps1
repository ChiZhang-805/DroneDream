[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$NodeExecutable,

    [Parameter(Mandatory = $true)]
    [string]$TauriCliPath,

    [Parameter(Mandatory = $true)]
    [string]$UpdaterKeyPath,

    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [ValidatePattern("^[A-Za-z_][A-Za-z0-9_]*$")]
    [string]$PasswordEnvironmentVariable = "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command $NodeExecutable -ErrorAction SilentlyContinue)) {
    throw "The Node executable was not found."
}
if (-not (Test-Path -LiteralPath $TauriCliPath -PathType Leaf)) {
    throw "The installed Tauri CLI was not found."
}
if (-not (Test-Path -LiteralPath $UpdaterKeyPath -PathType Leaf)) {
    throw "The updater signing key file was not found."
}
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "The installer to sign was not found."
}

$signaturePath = "${InstallerPath}.sig"
if (Test-Path -LiteralPath $signaturePath) {
    Remove-Item -LiteralPath $signaturePath -Force
}

# Keep this as a typed, complete argv vector. A single-item array emitted from
# a PowerShell `if` expression is otherwise unwrapped to a String, and splatting
# that String passes one character per argument. Non-empty passwords remain in
# the inherited process environment and are never copied to argv.
[string[]]$signerArguments = @(
    $TauriCliPath
    "signer"
    "sign"
    "--private-key-path"
    $UpdaterKeyPath
)
$updaterPassword = [Environment]::GetEnvironmentVariable(
    $PasswordEnvironmentVariable,
    [EnvironmentVariableTarget]::Process
)
if ([string]::IsNullOrEmpty($updaterPassword)) {
    $signerArguments += "--password="
}
$signerArguments += "--"
$signerArguments += $InstallerPath

try {
    & $NodeExecutable @signerArguments
    $signerExitCode = $LASTEXITCODE
} catch {
    Remove-Item -LiteralPath $signaturePath -Force -ErrorAction SilentlyContinue
    throw
}

if ($null -eq $signerExitCode -or $signerExitCode -ne 0) {
    Remove-Item -LiteralPath $signaturePath -Force -ErrorAction SilentlyContinue
    throw "Tauri updater signing failed."
}
if (-not (Test-Path -LiteralPath $signaturePath -PathType Leaf)) {
    throw "Tauri updater signing reported success without producing a signature."
}
if ((Get-Item -LiteralPath $signaturePath).Length -le 0) {
    Remove-Item -LiteralPath $signaturePath -Force
    throw "Tauri updater signing produced an empty signature."
}

Write-Host "Verified Tauri updater signature output."
