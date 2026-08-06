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
$expectedInstallRoot = Join-Path $env:LOCALAPPDATA "DroneDream-Field"
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
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class DroneDreamInstallerUiNative {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
"@

function Resolve-InstallerWindowStage {
    param(
        [Parameter(Mandatory = $true)]
        [Collections.IDictionary]$WindowRecord,
        [Parameter(Mandatory = $true)]
        [int]$ExpectedProcessId,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedDisplayName,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedInstallRoot
    )
    if ([int]$WindowRecord.processId -ne $ExpectedProcessId) {
        throw "Installer window PID does not belong to this probe."
    }
    if ([string]$WindowRecord.className -cne "#32770") {
        throw "Installer window class is not the exact NSIS dialog class."
    }
    $controls = @($WindowRecord.controls)
    $loadingTitle = [string]$WindowRecord.title
    if ($loadingTitle -match '^unpacking data: (?:100|[1-9]?[0-9])%$') {
        $loadingText = "Please wait while Setup is loading..."
        $visibleText = @($WindowRecord.visibleText)
        $progressText = @($controls | Where-Object {
            $_.controlType -ceq "ControlType.Text" -and
            $_.automationId -ceq "1030" -and $_.name -ceq $loadingTitle
        })
        $progressImage = @($controls | Where-Object {
            $_.controlType -ceq "ControlType.Image" -and
            $_.automationId -ceq "65535" -and $_.name -ceq $loadingTitle
        })
        $waitText = @($controls | Where-Object {
            $_.controlType -ceq "ControlType.Text" -and
            $_.automationId -ceq "76" -and $_.name -ceq $loadingText
        })
        $foreignControls = @($controls | Where-Object {
            $_.processId -ne $ExpectedProcessId -or $_.value -or
            $_.controlType -notin @("ControlType.Text", "ControlType.Image")
        })
        if ($controls.Count -ne 3 -or $progressText.Count -ne 1 -or
            $progressImage.Count -ne 1 -or $waitText.Count -ne 1 -or
            $foreignControls.Count -ne 0 -or $visibleText.Count -ne 2 -or
            -not ($visibleText -contains $loadingTitle) -or
            -not ($visibleText -contains $loadingText)) {
            throw "NSIS loading progress window structure drifted."
        }
        return "loading-progress"
    }
    if ([string]$WindowRecord.title -ceq "Installer Language") {
        $combo = @($controls | Where-Object { $_.controlType -ceq "ControlType.ComboBox" })
        $ok = @($controls | Where-Object {
            $_.controlType -ceq "ControlType.Button" -and
            $_.automationId -ceq "1" -and $_.name -ceq "OK"
        })
        $cancel = @($controls | Where-Object {
            $_.controlType -ceq "ControlType.Button" -and
            $_.automationId -ceq "2" -and $_.name -ceq "Cancel"
        })
        if ($combo.Count -ne 1 -or $ok.Count -ne 1 -or $cancel.Count -ne 1 -or
            -not (@($WindowRecord.visibleText) -contains "Please select a language.")) {
            throw "Generic NSIS language selector controls or text drifted."
        }
        return "language-selector"
    }

    $visibleText = @($WindowRecord.visibleText) -join "`n"
    if ([string]$WindowRecord.title -notlike "*$ExpectedDisplayName*" -and
        $visibleText -notlike "*$ExpectedDisplayName*") {
        throw "The branded NSIS window is missing the canonical Field identity."
    }
    $pathValues = @($controls | Where-Object {
        $_.controlType -ceq "ControlType.Edit" -and $_.value
    } | ForEach-Object { [string]$_.value })
    $pathLikeValues = @($pathValues | Where-Object { $_ -match '^[A-Za-z]:\\' })
    if ($pathLikeValues.Count -gt 0 -and -not ($pathLikeValues -contains $ExpectedInstallRoot)) {
        throw "The branded NSIS directory path drifted from the exact Field install root."
    }
    if ($pathValues -contains $ExpectedInstallRoot) { return "directory" }
    return "branded"
}

function Get-ControlRecord {
    param([Parameter(Mandatory = $true)][Windows.Automation.AutomationElement]$Element)
    $value = $null
    $valuePattern = $null
    if ($Element.TryGetCurrentPattern(
        [Windows.Automation.ValuePattern]::Pattern,
        [ref]$valuePattern
    )) {
        $value = ([Windows.Automation.ValuePattern]$valuePattern).Current.Value
    }
    return [ordered]@{
        name = [string]$Element.Current.Name
        automationId = [string]$Element.Current.AutomationId
        className = [string]$Element.Current.ClassName
        controlType = [string]$Element.Current.ControlType.ProgrammaticName
        processId = [int]$Element.Current.ProcessId
        nativeWindowHandle = [int]$Element.Current.NativeWindowHandle
        enabled = [bool]$Element.Current.IsEnabled
        offscreen = [bool]$Element.Current.IsOffscreen
        value = $value
    }
}

function Get-WindowRecord {
    param([Parameter(Mandatory = $true)][Windows.Automation.AutomationElement]$Window)
    $controls = @($Window.FindAll(
        [Windows.Automation.TreeScope]::Descendants,
        [Windows.Automation.Condition]::TrueCondition
    ) | ForEach-Object { Get-ControlRecord -Element $_ })
    return [ordered]@{
        title = [string]$Window.Current.Name
        automationId = [string]$Window.Current.AutomationId
        className = [string]$Window.Current.ClassName
        processId = [int]$Window.Current.ProcessId
        nativeWindowHandle = [int]$Window.Current.NativeWindowHandle
        visibleText = @($controls | Where-Object { $_.name } | ForEach-Object { $_.name } | Sort-Object -Unique)
        controls = $controls
    }
}

function Protect-DiagnosticText {
    param(
        [AllowNull()][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallRoot
    )
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    if ($Text -match '(?i)(password|passwd|secret|token|bearer|authorization|api[ _-]?key)') {
        return "[redacted-sensitive]"
    }
    if ($Text -match '(?i)https?://') { return "[redacted-uri]" }
    if ($Text -match '(?i)([A-Z]:\\|^\\\\)') {
        if ($Text.IndexOf($ExpectedInstallRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $Text.Replace($ExpectedInstallRoot, "%LOCALAPPDATA%\DroneDream-Field")
        }
        return "[redacted-path]"
    }
    if ($Text.Length -gt 256) { return $Text.Substring(0, 256) + "[truncated]" }
    return $Text
}

function Get-DiagnosticWindowRecord {
    param(
        [Parameter(Mandatory = $true)][Collections.IDictionary]$WindowRecord,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallRoot
    )
    $controls = @($WindowRecord.controls | ForEach-Object {
        [ordered]@{
            controlType = [string]$_.controlType
            automationId = [string]$_.automationId
            name = Protect-DiagnosticText -Text ([string]$_.name) -ExpectedInstallRoot $ExpectedInstallRoot
            value = Protect-DiagnosticText -Text ([string]$_.value) -ExpectedInstallRoot $ExpectedInstallRoot
        }
    })
    return [ordered]@{
        title = Protect-DiagnosticText -Text ([string]$WindowRecord.title) -ExpectedInstallRoot $ExpectedInstallRoot
        automationId = [string]$WindowRecord.automationId
        className = [string]$WindowRecord.className
        processId = [int]$WindowRecord.processId
        visibleText = @($WindowRecord.visibleText | ForEach-Object {
            Protect-DiagnosticText -Text ([string]$_) -ExpectedInstallRoot $ExpectedInstallRoot
        } | Sort-Object -Unique)
        controls = $controls
    }
}

function Add-PreclassificationSnapshot {
    param(
        [Parameter(Mandatory = $true)][Collections.IDictionary]$WindowRecord,
        [Parameter(Mandatory = $true)][int]$ExpectedProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallRoot,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][Collections.Generic.List[object]]$Snapshots
    )
    if ([int]$WindowRecord.processId -ne $ExpectedProcessId) {
        throw "Diagnostic snapshot refuses a foreign installer PID."
    }
    if ([string]$WindowRecord.className -cne "#32770") {
        throw "Diagnostic snapshot refuses a non-NSIS top-level window."
    }
    $snapshot = [ordered]@{
        stage = "pending-classification"
        window = Get-DiagnosticWindowRecord -WindowRecord $WindowRecord -ExpectedInstallRoot $ExpectedInstallRoot
    }
    $Snapshots.Add($snapshot)
    return $snapshot
}

function Select-SingleOwnedWindowRecord {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()]
        [object[]]$WindowRecords,
        [Parameter(Mandatory = $true)]
        [int]$ExpectedProcessId
    )
    if ($WindowRecords.Count -ne 1) {
        throw "Expected exactly one visible top-level installer window; observed $($WindowRecords.Count)."
    }
    if ([int]$WindowRecords[0].processId -ne $ExpectedProcessId) {
        throw "Visible installer window belongs to a foreign PID."
    }
    return $WindowRecords[0]
}

function Get-SingleOwnedWindow {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $windows = @([Windows.Automation.AutomationElement]::RootElement.FindAll(
        [Windows.Automation.TreeScope]::Children,
        [Windows.Automation.PropertyCondition]::new(
            [Windows.Automation.AutomationElement]::ProcessIdProperty,
            $ProcessId
        )
    ) | Where-Object { -not $_.Current.IsOffscreen })
    $ownershipRecords = @($windows | ForEach-Object {
        [ordered]@{ processId = [int]$_.Current.ProcessId; title = [string]$_.Current.Name }
    })
    Select-SingleOwnedWindowRecord -WindowRecords $ownershipRecords -ExpectedProcessId $ProcessId | Out-Null
    return $windows[0]
}

function Wait-SingleOwnedWindow {
    param(
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][AllowNull()][AllowEmptyString()][string]$DifferentFromTitle,
        [DateTime]$DeadlineUtc = [DateTime]::MinValue
    )
    $excludedTitle = if ([string]::IsNullOrEmpty($DifferentFromTitle)) { $null } else { $DifferentFromTitle }
    $deadline = if ($DeadlineUtc -eq [DateTime]::MinValue) {
        [DateTime]::UtcNow.AddSeconds(30)
    } else { $DeadlineUtc }
    do {
        if ($Process.HasExited) { throw "The visible installer exited during observer transition." }
        try {
            $candidate = Get-SingleOwnedWindow -ProcessId $Process.Id
            if ($null -eq $excludedTitle -or $candidate.Current.Name -cne $excludedTitle) {
                return $candidate
            }
        } catch {
            if ($_.Exception.Message -notlike "Expected exactly one visible top-level installer window*") { throw }
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for the exact owned installer window transition."
}

function Wait-ExpectedStageAfterLoading {
    param(
        [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][AllowNull()][AllowEmptyString()][string]$DifferentFromTitle,
        [Parameter(Mandatory = $true)][ValidateSet("language-selector", "branded")][string]$ExpectedStage,
        [Parameter(Mandatory = $true)][string]$ExpectedDisplayName,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallRoot,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][Collections.Generic.List[object]]$Snapshots,
        [ValidateRange(1, 30000)][int]$TimeoutMilliseconds = 30000,
        [ValidateRange(0, 1000)][int]$PollMilliseconds = 250,
        [scriptblock]$WindowRecordProvider
    )
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    if ($null -eq $WindowRecordProvider) {
        $WindowRecordProvider = {
            param($BoundProcess, $ExcludedTitle, $Deadline)
            $window = Wait-SingleOwnedWindow -Process $BoundProcess -DifferentFromTitle $ExcludedTitle -DeadlineUtc $Deadline
            return [ordered]@{ window = $window; record = Get-WindowRecord -Window $window }
        }
    }
    $loadingSnapshotKept = $false
    do {
        $candidate = & $WindowRecordProvider $Process $DifferentFromTitle $deadline
        if ($null -eq $candidate -or $null -eq $candidate.record) {
            throw "Installer window provider returned no classifiable record."
        }
        $snapshot = Add-PreclassificationSnapshot -WindowRecord $candidate.record -ExpectedProcessId $Process.Id -ExpectedInstallRoot $ExpectedInstallRoot -Snapshots $Snapshots
        $stage = Resolve-InstallerWindowStage -WindowRecord $candidate.record -ExpectedProcessId $Process.Id -ExpectedDisplayName $ExpectedDisplayName -ExpectedInstallRoot $ExpectedInstallRoot
        $snapshot["stage"] = $stage
        if ($stage -ceq "loading-progress") {
            if ($loadingSnapshotKept) { $Snapshots.Remove($snapshot) | Out-Null }
            else { $loadingSnapshotKept = $true }
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Timed out waiting for $ExpectedStage after exact NSIS loading progress."
            }
            if ($PollMilliseconds -gt 0) { Start-Sleep -Milliseconds $PollMilliseconds }
            continue
        }
        if ($stage -cne $ExpectedStage) {
            throw "The first non-loading installer window was not the expected $ExpectedStage stage."
        }
        return [ordered]@{ window = $candidate.window; record = $candidate.record; stage = $stage }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $ExpectedStage after exact NSIS loading progress."
}

function Invoke-ExactButton {
    param(
        [Parameter(Mandatory = $true)][Windows.Automation.AutomationElement]$Window,
        [Parameter(Mandatory = $true)][string]$AutomationId,
        [Parameter(Mandatory = $true)][int]$ExpectedProcessId,
        [Parameter(Mandatory = $true)][string]$Action
    )
    $buttons = @($Window.FindAll(
        [Windows.Automation.TreeScope]::Descendants,
        [Windows.Automation.AndCondition]::new(
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::ControlTypeProperty,
                [Windows.Automation.ControlType]::Button
            ),
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::AutomationIdProperty,
                $AutomationId
            )
        )
    ))
    if ($buttons.Count -ne 1 -or $buttons[0].Current.ProcessId -ne $ExpectedProcessId -or
        -not $buttons[0].Current.IsEnabled -or $buttons[0].Current.IsOffscreen) {
        throw "The exact owned $Action button was missing, duplicated, disabled, or offscreen."
    }
    $name = [string]$buttons[0].Current.Name
    if ($name -match '(?i)install' -or $name -match ([string][char]0x5B89 + [char]0x88C5)) {
        throw "Observer refuses to invoke an Install action."
    }
    $pattern = $null
    if (-not $buttons[0].TryGetCurrentPattern(
        [Windows.Automation.InvokePattern]::Pattern,
        [ref]$pattern
    )) { throw "The exact owned $Action button lacks InvokePattern." }
    ([Windows.Automation.InvokePattern]$pattern).Invoke()
}

function Select-ExactLanguage {
    param(
        [Parameter(Mandatory = $true)][Windows.Automation.AutomationElement]$Window,
        [Parameter(Mandatory = $true)][int]$ExpectedProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedLanguageId
    )
    $combos = @($Window.FindAll(
        [Windows.Automation.TreeScope]::Descendants,
        [Windows.Automation.PropertyCondition]::new(
            [Windows.Automation.AutomationElement]::ControlTypeProperty,
            [Windows.Automation.ControlType]::ComboBox
        )
    ))
    if ($combos.Count -ne 1 -or $combos[0].Current.ProcessId -ne $ExpectedProcessId -or
        $combos[0].Current.NativeWindowHandle -eq 0) {
        throw "The exact owned language combo was missing, duplicated, foreign, or had no control handle."
    }
    $languageIndex = if ($ExpectedLanguageId -eq "1033") { 0 } else { 1 }
    $cbSetCurSel = 0x014E
    $selection = [DroneDreamInstallerUiNative]::SendMessage(
        [IntPtr]$combos[0].Current.NativeWindowHandle,
        $cbSetCurSel,
        [IntPtr]$languageIndex,
        [IntPtr]::Zero
    ).ToInt64()
    if ($selection -ne $languageIndex) { throw "The exact language combo rejected the requested index." }
    Invoke-ExactButton -Window $Window -AutomationId "1" -ExpectedProcessId $ExpectedProcessId -Action "language-OK"
}

function Save-WindowScreenshot {
    param(
        [Parameter(Mandatory = $true)][Windows.Automation.AutomationElement]$Window,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $bounds = $Window.Current.BoundingRectangle
    if ($bounds.Width -le 0 -or $bounds.Height -le 0) { throw "Installer window has invalid bounds." }
    $bitmap = [Drawing.Bitmap]::new([int]$bounds.Width, [int]$bounds.Height)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen([int]$bounds.Left, [int]$bounds.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$process = $null
$processId = $null
$snapshots = [Collections.Generic.List[object]]::new()
$result = $null
$failure = $null
try {
    $process = Start-Process -FilePath $installerPath -ArgumentList "/LANG=$LanguageId" -PassThru
    $processId = $process.Id
    $languageResult = Wait-ExpectedStageAfterLoading -Process $process -DifferentFromTitle "" -ExpectedStage "language-selector" -ExpectedDisplayName $displayName -ExpectedInstallRoot $expectedInstallRoot -Snapshots $snapshots
    $languageWindow = $languageResult.window
    Select-ExactLanguage -Window $languageWindow -ExpectedProcessId $process.Id -ExpectedLanguageId $LanguageId

    $welcomeResult = Wait-ExpectedStageAfterLoading -Process $process -DifferentFromTitle "Installer Language" -ExpectedStage "branded" -ExpectedDisplayName $displayName -ExpectedInstallRoot $expectedInstallRoot -Snapshots $snapshots
    $mainWindow = $welcomeResult.window

    $priorText = @((Get-WindowRecord -Window $mainWindow).visibleText) -join "`n"
    Invoke-ExactButton -Window $mainWindow -AutomationId "1" -ExpectedProcessId $process.Id -Action "Next-directory"
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 200
        $mainWindow = Get-SingleOwnedWindow -ProcessId $process.Id
        $record = Get-WindowRecord -Window $mainWindow
        $currentText = @($record.visibleText) -join "`n"
    } while ($currentText -ceq $priorText -and [DateTime]::UtcNow -lt $deadline)
    if ($currentText -ceq $priorText) { throw "The exact Next-directory transition did not advance." }
    $directorySnapshot = Add-PreclassificationSnapshot -WindowRecord $record -ExpectedProcessId $process.Id -ExpectedInstallRoot $expectedInstallRoot -Snapshots $snapshots
    $stage = Resolve-InstallerWindowStage -WindowRecord $record -ExpectedProcessId $process.Id -ExpectedDisplayName $displayName -ExpectedInstallRoot $expectedInstallRoot
    $directorySnapshot["stage"] = $stage
    if ($stage -ne "directory") { throw "The bounded observer did not reach the exact Field directory stage." }

    $screenshot = Join-Path $outputPath "installer-$ExpectedLocale.png"
    Save-WindowScreenshot -Window $mainWindow -Path $screenshot
    $result = [ordered]@{
        schemaVersion = 2
        locale = $ExpectedLocale
        languageId = $LanguageId
        processId = $process.Id
        stages = @($snapshots | ForEach-Object { $_.stage })
        snapshots = @($snapshots)
        screenshotPath = $screenshot
        genericSelectorWasAllowedToOmitProductIdentity = $true
        canonicalFieldIdentityVisibleAfterLanguageSelection = $true
        exactInstallRootVisible = $expectedInstallRoot
        installActionInvoked = $false
        boundedNextInvocations = 2
        passed = $true
    }
} catch {
    $failure = $_.Exception.Message
    throw
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
    $evidence = if ($null -ne $result) { $result } else {
        [ordered]@{
            schemaVersion = 2
            locale = $ExpectedLocale
            languageId = $LanguageId
            processId = $processId
            stages = @($snapshots | ForEach-Object { $_.stage })
            snapshots = @($snapshots)
            installActionInvoked = $false
            failure = $failure
            passed = $false
        }
    }
    $resultPath = Join-Path $outputPath "installer-$ExpectedLocale.json"
    $evidence | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $resultPath -Encoding UTF8
}

Write-Output (Join-Path $outputPath "installer-$ExpectedLocale.json")
