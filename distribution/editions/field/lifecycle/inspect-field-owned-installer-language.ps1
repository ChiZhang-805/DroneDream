param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{64}$")]
    [string]$ExpectedInstallerSha256,
    [Parameter(Mandatory = $true)]
    [ValidateSet("1033", "2052")]
    [string]$LanguageId,
    [Parameter(Mandatory = $true)]
    [ValidateSet("en", "zh-CN")]
    [string]$ExpectedLocale,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$displayName = "DroneDream $([char]0x00B7) FIELD"
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$outputPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd("\")

if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    $ExpectedInstallerSha256) {
    throw "The visible-language probe is not bound to the frozen Field installer."
}
if (-not (Test-Path -LiteralPath $outputPath -PathType Container)) {
    throw "The lifecycle runner must create the exact owned output root first."
}
if (($LanguageId -eq "1033") -ne ($ExpectedLocale -eq "en")) {
    throw "LanguageId and ExpectedLocale do not describe the same locale."
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing

$process = $null
$window = $null
$result = $null
try {
    $process = Start-Process -FilePath $installerPath -ArgumentList "/LANG=$LanguageId" -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        if ($process.HasExited) { throw "The visible installer exited before inspection." }
        $window = [Windows.Automation.AutomationElement]::RootElement.FindFirst(
            [Windows.Automation.TreeScope]::Children,
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::ProcessIdProperty,
                $process.Id
            )
        )
        if ($null -eq $window) { Start-Sleep -Milliseconds 250 }
    } while ($null -eq $window -and [DateTime]::UtcNow -lt $deadline)
    if ($null -eq $window) { throw "Timed out waiting for the exact Field installer window." }

    $texts = @($window.FindAll(
        [Windows.Automation.TreeScope]::Descendants,
        [Windows.Automation.Condition]::TrueCondition
    ) | ForEach-Object { [string]$_.Current.Name } | Where-Object { $_ } | Sort-Object -Unique)
    $joined = $texts -join "`n"
    $localeMarkers = if ($ExpectedLocale -eq "en") {
        @("Choose", "Install", "Next", "Cancel")
    } else {
        @(
            (-join @([char]0x9009, [char]0x62E9)),
            (-join @([char]0x5B89, [char]0x88C5)),
            (-join @([char]0x4E0B, [char]0x4E00, [char]0x6B65)),
            (-join @([char]0x53D6, [char]0x6D88))
        )
    }
    if ($window.Current.Name -notlike "*$displayName*" -and $joined -notlike "*$displayName*") {
        throw "The visible installer did not present the canonical Field identity."
    }
    if (@($localeMarkers | Where-Object { $joined -like "*$_*" }).Count -eq 0) {
        throw "The visible installer did not expose the expected $ExpectedLocale language markers."
    }

    $bounds = $window.Current.BoundingRectangle
    if ($bounds.Width -le 0 -or $bounds.Height -le 0) {
        throw "The visible installer window has invalid bounds."
    }
    $bitmap = [Drawing.Bitmap]::new([int]$bounds.Width, [int]$bounds.Height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen(
            [int]$bounds.Left,
            [int]$bounds.Top,
            0,
            0,
            $bitmap.Size,
            [Drawing.CopyPixelOperation]::SourceCopy
        )
        $screenshot = Join-Path $outputPath "installer-$ExpectedLocale.png"
        $bitmap.Save($screenshot, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }

    $result = [ordered]@{
        schemaVersion = 1
        locale = $ExpectedLocale
        languageId = $LanguageId
        processId = $process.Id
        windowTitle = $window.Current.Name
        visibleText = $texts
        screenshotPath = $screenshot
        canonicalFieldIdentityVisible = $true
        installActionInvoked = $false
        passed = $true
    }
} finally {
    if ($null -ne $process) {
        if (-not $process.HasExited) {
            $process.CloseMainWindow() | Out-Null
            if (-not $process.WaitForExit(5000)) {
                Stop-Process -Id $process.Id -Force
                $process.WaitForExit(5000) | Out-Null
            }
        }
        $process.Dispose()
    }
}

$resultPath = Join-Path $outputPath "installer-$ExpectedLocale.json"
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $resultPath -Encoding UTF8
Write-Output $resultPath
