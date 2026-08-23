$ErrorActionPreference = "Stop"

function Assert-Contract {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw "Updater signing contract failed: $Message"
    }
}

function Test-ExactSequence {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Expected,

        [Parameter(Mandatory = $true)]
        [object[]]$Actual
    )

    $differences = @(
        Compare-Object `
            -ReferenceObject $Expected `
            -DifferenceObject $Actual `
            -SyncWindow 0
    )
    return $differences.Count -eq 0
}

Assert-Contract (
    Test-ExactSequence -Expected @("alpha", "beta") -Actual @("alpha", "beta")
) "an empty sequence difference must pass under StrictMode"
Assert-Contract (-not (
    Test-ExactSequence -Expected @("alpha", "beta") -Actual @("alpha", "gamma")
)) "a real sequence difference must fail closed"

$helperPath = Join-Path $PSScriptRoot "invoke-tauri-updater-signer.ps1"
$buildScriptPath = Join-Path $PSScriptRoot "build-windows-llvm.ps1"
$helperText = Get-Content -LiteralPath $helperPath -Raw
$buildScriptText = Get-Content -LiteralPath $buildScriptPath -Raw

$tokens = $null
$parseErrors = $null
$helperAst = [Management.Automation.Language.Parser]::ParseFile(
    $helperPath,
    [ref]$tokens,
    [ref]$parseErrors
)
Assert-Contract ($parseErrors.Count -eq 0) "the helper PowerShell AST must parse without errors"

$nativeInvocation = @($helperAst.FindAll({
    param($node)
    if ($node -isnot [Management.Automation.Language.CommandAst]) {
        return $false
    }
    $elements = @($node.CommandElements)
    if ($elements.Count -lt 2) {
        return $false
    }
    $commandVariable = $elements[0] -as [Management.Automation.Language.VariableExpressionAst]
    $argumentVariable = $elements[1] -as [Management.Automation.Language.VariableExpressionAst]
    return (
        $commandVariable -and
        $commandVariable.VariablePath.UserPath -eq "NodeExecutable" -and
        $argumentVariable -and
        $argumentVariable.Splatted -and
        $argumentVariable.VariablePath.UserPath -eq "signerArguments"
    )
}, $true))
Assert-Contract ($nativeInvocation.Count -eq 1) "the native signer must receive one complete splatted argv vector"
Assert-Contract ($helperText.Contains('[string[]]$signerArguments = @(')) "signer argv must remain a typed String array"
Assert-Contract ($helperText.Contains('$signerArguments += "--password="')) "empty passwords must be explicit"
Assert-Contract ($helperText.Contains('$signerArguments += "--"')) "the installer path must follow an option terminator"
Assert-Contract (
    $helperText.Contains(
        '[string]$PasswordEnvironmentVariable = "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"'
    )
) "production must default to the Tauri password environment variable"
Assert-Contract (-not [regex]::IsMatch(
    $helperText,
    '(?i)--password[^\r\n]*TAURI_SIGNING_PRIVATE_KEY_PASSWORD'
)) "the password environment value must not be copied to argv"
Assert-Contract ($buildScriptText.Contains('invoke-tauri-updater-signer.ps1')) "the LLVM build must use the tested signer helper"
Assert-Contract (-not $buildScriptText.Contains('@updaterPasswordArguments')) "the scalar-splat regression must stay removed"
$preflightIndex = $buildScriptText.IndexOf(
    'verify-updater-signing-contract.ps1',
    [StringComparison]::Ordinal
)
$buildInvocationIndex = $buildScriptText.IndexOf(
    'Invoke-CheckedNativeCommand `',
    [StringComparison]::Ordinal
)
Assert-Contract (
    $preflightIndex -ge 0 -and
    $buildInvocationIndex -ge 0 -and
    $preflightIndex -lt $buildInvocationIndex
) "the signer contract must fail before the expensive desktop and NSIS build starts"

$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporaryRoot = Join-Path $temporaryBase (
    "dronedream-updater-signing-contract-{0}" -f [Guid]::NewGuid().ToString("N")
)
$testPasswordVariable = "DRONEDREAM_SIGNER_TEST_PASSWORD"
$originalTestPassword = [Environment]::GetEnvironmentVariable(
    $testPasswordVariable,
    [EnvironmentVariableTarget]::Process
)

try {
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    $fakeCli = Join-Path $temporaryRoot "fake tauri cli.js"
    $fakeKey = Join-Path $temporaryRoot "test updater key.key"
    $fakeInstaller = Join-Path $temporaryRoot "DroneDream contract x64 setup.exe"
    $argumentRecord = Join-Path $temporaryRoot "argv.json"

    @'
const fs = require("node:fs");

const capturedArguments = process.argv.slice(2);
const passwordVariable = process.env.DRONEDREAM_SIGNER_PASSWORD_VARIABLE;
const password = process.env[passwordVariable];
fs.writeFileSync(
  process.env.DRONEDREAM_SIGNER_ARGV_RECORD,
  `${JSON.stringify({
    script_path: process.argv[1],
    arguments: capturedArguments,
    password_present: password !== undefined,
    password_length: password?.length ?? 0,
  }, null, 2)}\n`,
  "utf8",
);
if (process.env.DRONEDREAM_SIGNER_WRITE_SIGNATURE === "1") {
  fs.writeFileSync(`${capturedArguments.at(-1)}.sig`, "contract-signature\n", "ascii");
}
process.exit(Number(process.env.DRONEDREAM_SIGNER_EXIT_CODE));
'@ | Set-Content -Encoding utf8 -LiteralPath $fakeCli
    "fake-key" | Set-Content -Encoding ascii -LiteralPath $fakeKey
    "fake-installer" | Set-Content -Encoding ascii -LiteralPath $fakeInstaller

    $env:DRONEDREAM_SIGNER_ARGV_RECORD = $argumentRecord
    $env:DRONEDREAM_SIGNER_WRITE_SIGNATURE = "1"
    $env:DRONEDREAM_SIGNER_EXIT_CODE = "0"
    $env:DRONEDREAM_SIGNER_PASSWORD_VARIABLE = $testPasswordVariable
    # PowerShell 7 on Windows can preserve a process variable as an empty
    # entry when SetEnvironmentVariable receives $null. Remove the Env drive
    # entry explicitly so the child-process contract distinguishes absent
    # credentials from an intentionally empty value.
    Remove-Item -LiteralPath "Env:$testPasswordVariable" -ErrorAction SilentlyContinue
    & $helperPath `
        -NodeExecutable "node.exe" `
        -TauriCliPath $fakeCli `
        -UpdaterKeyPath $fakeKey `
        -InstallerPath $fakeInstaller `
        -PasswordEnvironmentVariable $testPasswordVariable
    $emptyPasswordRecord = Get-Content -LiteralPath $argumentRecord -Raw | ConvertFrom-Json
    Assert-Contract (
        [IO.Path]::GetFullPath($emptyPasswordRecord.script_path) -eq [IO.Path]::GetFullPath($fakeCli)
    ) "the native Node process must execute the expected Tauri CLI path"
    $expectedEmptyArguments = @(
        "signer",
        "sign",
        "--private-key-path",
        $fakeKey,
        "--password=",
        "--",
        $fakeInstaller
    )
    Assert-Contract (
        Test-ExactSequence `
            -Expected $expectedEmptyArguments `
            -Actual @($emptyPasswordRecord.arguments)
    ) "empty-password argv must be exact and ordered"
    Assert-Contract (-not $emptyPasswordRecord.password_present) "the empty-password case must not invent an environment secret"

    $testPassword = "contract non-empty password"
    [Environment]::SetEnvironmentVariable(
        $testPasswordVariable,
        $testPassword,
        [EnvironmentVariableTarget]::Process
    )
    & $helperPath `
        -NodeExecutable "node.exe" `
        -TauriCliPath $fakeCli `
        -UpdaterKeyPath $fakeKey `
        -InstallerPath $fakeInstaller `
        -PasswordEnvironmentVariable $testPasswordVariable
    $nonEmptyRecord = Get-Content -LiteralPath $argumentRecord -Raw | ConvertFrom-Json
    $expectedNonEmptyArguments = @(
        "signer",
        "sign",
        "--private-key-path",
        $fakeKey,
        "--",
        $fakeInstaller
    )
    Assert-Contract (
        Test-ExactSequence `
            -Expected $expectedNonEmptyArguments `
            -Actual @($nonEmptyRecord.arguments)
    ) "non-empty passwords must stay out of argv"
    Assert-Contract $nonEmptyRecord.password_present "the non-empty password must remain available to the child environment"
    Assert-Contract (
        $nonEmptyRecord.password_length -eq $testPassword.Length
    ) "the child environment must preserve the non-empty password without recording its value"
    Assert-Contract (
        -not ((@($nonEmptyRecord.arguments) -join "`n").Contains($testPassword))
    ) "the non-empty password value must not appear in argv"

    "stale-signature" | Set-Content -Encoding ascii -LiteralPath "${fakeInstaller}.sig"
    $env:DRONEDREAM_SIGNER_WRITE_SIGNATURE = "0"
    $env:DRONEDREAM_SIGNER_EXIT_CODE = "17"
    $signerFailureClosed = $false
    try {
        & $helperPath `
            -NodeExecutable "node.exe" `
            -TauriCliPath $fakeCli `
            -UpdaterKeyPath $fakeKey `
            -InstallerPath $fakeInstaller `
            -PasswordEnvironmentVariable $testPasswordVariable
    } catch {
        $signerFailureClosed = $_.Exception.Message -match "Tauri updater signing failed"
    }
    Assert-Contract $signerFailureClosed "a non-zero signer exit must fail closed"
    Assert-Contract (
        -not (Test-Path -LiteralPath "${fakeInstaller}.sig")
    ) "a failed signer must not leave a stale signature"

    $env:DRONEDREAM_SIGNER_EXIT_CODE = "0"
    $missingOutputClosed = $false
    try {
        & $helperPath `
            -NodeExecutable "node.exe" `
            -TauriCliPath $fakeCli `
            -UpdaterKeyPath $fakeKey `
            -InstallerPath $fakeInstaller `
            -PasswordEnvironmentVariable $testPasswordVariable
    } catch {
        $missingOutputClosed = $_.Exception.Message -match "without producing a signature"
    }
    Assert-Contract $missingOutputClosed "a zero exit without a signature must fail closed"
} finally {
    if ($null -eq $originalTestPassword) {
        Remove-Item -LiteralPath "Env:$testPasswordVariable" -ErrorAction SilentlyContinue
    } else {
        [Environment]::SetEnvironmentVariable(
            $testPasswordVariable,
            $originalTestPassword,
            [EnvironmentVariableTarget]::Process
        )
    }
    Remove-Item Env:DRONEDREAM_SIGNER_ARGV_RECORD -ErrorAction SilentlyContinue
    Remove-Item Env:DRONEDREAM_SIGNER_WRITE_SIGNATURE -ErrorAction SilentlyContinue
    Remove-Item Env:DRONEDREAM_SIGNER_EXIT_CODE -ErrorAction SilentlyContinue
    Remove-Item Env:DRONEDREAM_SIGNER_PASSWORD_VARIABLE -ErrorAction SilentlyContinue
    $resolvedTemporaryRoot = [IO.Path]::GetFullPath($temporaryRoot)
    if (
        $resolvedTemporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase) -and
        [IO.Path]::GetFileName($resolvedTemporaryRoot).StartsWith(
            "dronedream-updater-signing-contract-",
            [StringComparison]::Ordinal
        )
    ) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host (
    "Updater signing contract verified: AST, empty-password argv, " +
    "non-empty env-only password, signer failure, and missing-output gates passed."
)
