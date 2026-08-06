$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\")
$fixtureRoot = Join-Path $tempBase ("dronedream-field-phase-evidence-" + [guid]::NewGuid().ToString("N"))
$diagnosticPath = Join-Path $fixtureRoot "installer-diagnostics.log"

try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    [IO.File]::WriteAllText(
        $diagnosticPath,
        "installer-init language=1033`r`n",
        [Text.UTF8Encoding]::new($false)
    )
    $evidence = [ordered]@{
        arguments = @("/S", "/D=C:\owned")
        exitCode = 0
        diagnostic = [ordered]@{
            path = $diagnosticPath
            sha256 = (Get-FileHash -LiteralPath $diagnosticPath -Algorithm SHA256).Hash.ToLowerInvariant()
            text = [IO.File]::ReadAllText($diagnosticPath, [Text.Encoding]::UTF8)
        }
    }
    $before = (Get-Process -Id $PID).PrivateMemorySize64
    $json = $evidence | ConvertTo-Json -Depth 20 -Compress
    $growth = (Get-Process -Id $PID).PrivateMemorySize64 - $before
    $properties = @($evidence.diagnostic.text.PSObject.Properties.Name)
    $result = [ordered]@{
        kind = "dronedream-field-phase-evidence-serialization-fixture"
        passed = (
            $evidence.diagnostic.text.GetType().FullName -eq "System.String" -and
            "PSPath" -notin $properties -and
            $json.Length -lt 4096 -and
            $growth -lt 16MB
        )
        textType = $evidence.diagnostic.text.GetType().FullName
        hasPsPath = "PSPath" -in $properties
        jsonLength = $json.Length
        privateMemoryGrowthBytes = $growth
        hardwareActions = 0
        deviceEnumerations = 0
        networkRequests = 0
        installerInvocations = 0
    }
    $result | ConvertTo-Json -Compress
    if (-not $result.passed) { exit 2 }
} finally {
    if (Test-Path -LiteralPath $fixtureRoot) {
        $resolved = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $fixtureRoot).Path)
        if (-not $resolved.StartsWith($tempBase + "\dronedream-field-phase-evidence-", [StringComparison]::OrdinalIgnoreCase)) {
            throw "fixture cleanup escaped the expected temp namespace"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
