[CmdletBinding()]
param(
    [ValidateSet("Plan", "ExecuteSequence")]
    [string]$Mode = "Plan",
    [string]$EntryScript,
    [string]$EntryScriptSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repository = "ChiZhang-805/DroneDream"
$AllowedVariableNames = @(
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_PUBLISHABLE_KEY"
)
$ChildPhases = @("Preflight", "Prepare", "Execute")
$PowerShellExe = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
$SimDesktopRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd("\")

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Get-Sha256Lower {
    param([string]$LiteralPath)
    (Get-FileHash -Algorithm SHA256 -LiteralPath $LiteralPath).Hash.ToLowerInvariant()
}

function Get-PublicRepositoryVariable {
    param([string]$Name)

    Assert-True ($Name -cin $AllowedVariableNames) "A repository variable name is not allowlisted."
    $endpoint = "repos/$Repository/actions/variables/$Name"
    $responseText = (& gh.exe api $endpoint 2>$null | Out-String)
    Assert-True ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($responseText)) "Public repository variable capture failed."
    try {
        $response = $responseText | ConvertFrom-Json
    } catch {
        throw "Public repository variable response was not valid JSON."
    }
    Assert-True ([string]$response.name -ceq $Name) "Public repository variable response name drifted."
    $value = [string]$response.value
    Assert-True (-not [string]::IsNullOrWhiteSpace($value)) "Public repository variable value was empty."
    $value
}

function Assert-EntryScriptBinding {
    Assert-True (-not [string]::IsNullOrWhiteSpace($EntryScript)) "Entry script is required."
    Assert-True ($EntryScriptSha256 -cmatch "^[0-9a-f]{64}$") "Entry script SHA must be lowercase SHA-256."
    $entryFull = [IO.Path]::GetFullPath($EntryScript)
    $ownedPrefix = "$SimDesktopRoot\"
    Assert-True ($entryFull.StartsWith($ownedPrefix, [StringComparison]::OrdinalIgnoreCase)) "Entry script escaped the owned desktop root."
    $relative = $entryFull.Substring($ownedPrefix.Length)
    Assert-True (
        $relative -cmatch "^invoke-yellow-build-attempt-[0-9]+-[0-9a-f]{7}\.ps1$"
    ) "Entry script must be an exact Sim attempt script under the owned desktop root."
    Assert-True (Test-Path -LiteralPath $entryFull -PathType Leaf) "Entry script is missing."
    Assert-True ((Get-Sha256Lower $entryFull) -ceq $EntryScriptSha256) "Entry script SHA drifted."
    $entryFull
}

function Invoke-ControlledChildPhase {
    param(
        [string]$EntryFull,
        [string]$Phase,
        [Collections.Generic.Dictionary[string, string]]$PublicValues
    )

    Assert-True ($Phase -cin $ChildPhases) "Child phase is not allowlisted."
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $PowerShellExe
    $startInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$EntryFull`" -Mode $Phase"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    foreach ($name in $AllowedVariableNames) {
        Assert-True ($PublicValues.ContainsKey($name)) "A required public value is unavailable."
        $startInfo.EnvironmentVariables[$name] = $PublicValues[$name]
    }

    $process = $null
    try {
        $process = [Diagnostics.Process]::Start($startInfo)
        Assert-True ($null -ne $process) "Controlled child process did not start."
        $process.WaitForExit()
        Assert-True ($process.ExitCode -eq 0) "Controlled child phase failed."
    } finally {
        foreach ($name in $AllowedVariableNames) {
            $startInfo.EnvironmentVariables.Remove($name)
        }
        if ($null -ne $process) { $process.Dispose() }
    }
}

if ($Mode -ceq "Plan") {
    [ordered]@{
        schemaVersion = 1
        kind = "dronedream-sim-public-repository-variable-launcher-plan"
        state = "green-plan-only-no-provider-no-child"
        repository = $Repository
        allowedVariableNames = $AllowedVariableNames
        captureEndpoints = @(
            "repos/$Repository/actions/variables/VITE_SUPABASE_URL",
            "repos/$Repository/actions/variables/VITE_SUPABASE_PUBLISHABLE_KEY"
        )
        childPhases = $ChildPhases
        valuesRead = $false
        valuesPrinted = $false
        valuesPersisted = $false
        providerInvocations = 0
        childInvocations = 0
    } | ConvertTo-Json -Depth 5
    exit 0
}

$entryFull = Assert-EntryScriptBinding
foreach ($name in $AllowedVariableNames) {
    Assert-True ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) "Launching process already contains a public build variable."
}

$publicValues = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::Ordinal)
$urlValue = $null
$keyValue = $null
try {
    $urlValue = Get-PublicRepositoryVariable -Name "VITE_SUPABASE_URL"
    $keyValue = Get-PublicRepositoryVariable -Name "VITE_SUPABASE_PUBLISHABLE_KEY"
    $publicValues.Add("VITE_SUPABASE_URL", $urlValue)
    $publicValues.Add("VITE_SUPABASE_PUBLISHABLE_KEY", $keyValue)
    foreach ($phase in $ChildPhases) {
        Invoke-ControlledChildPhase -EntryFull $entryFull -Phase $phase -PublicValues $publicValues
    }
    [ordered]@{
        schemaVersion = 1
        kind = "dronedream-sim-public-repository-variable-launcher-result"
        state = "controlled-sequence-completed"
        variableNames = $AllowedVariableNames
        providerInvocations = 2
        childInvocations = 3
        valuesPrinted = $false
        valuesPersisted = $false
    } | ConvertTo-Json -Depth 4
} finally {
    foreach ($name in $AllowedVariableNames) {
        $publicValues.Remove($name) | Out-Null
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    $urlValue = $null
    $keyValue = $null
    $publicValues.Clear()
}
