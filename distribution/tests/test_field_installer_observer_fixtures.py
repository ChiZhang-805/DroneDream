# ruff: noqa: E501 - embedded PowerShell fixture records are intentionally literal.

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "lifecycle"
    / "inspect-field-owned-installer-language.ps1"
)
DIAGNOSIS = OBSERVER.with_name("attempt1-visible-installer-observer-diagnosis.v1.json")


def test_attempt1_diagnosis_separates_direct_facts_from_static_inference() -> None:
    diagnosis = json.loads(DIAGNOSIS.read_text(encoding="utf-8"))

    assert diagnosis["decision"] == (
        "observer-false-negative-supported-requires-new-application"
    )
    assert diagnosis["attemptReceipt"]["sha256"] == (
        "3f3c5072016e73e16262da70f1558c29ca37eaf6bac6ec45a6521edec754a2e1"
    )
    boundary = diagnosis["dynamicEvidenceBoundary"]
    assert boundary["accessibilityTreePersistedBeforeFailure"] is False
    assert boundary["exactHistoricalWindowTitleKnown"] is False
    assert boundary["exactHistoricalControlIdsKnown"] is False
    assert boundary["retroactiveDynamicClaimsAllowed"] is False
    remediation = diagnosis["remediationContract"]
    assert remediation["genericLanguageSelector"]["productIdentityRequired"] is False
    assert remediation["genericLanguageSelector"]["processIdMustEqualInstallerPid"] is True
    assert remediation["postSelection"]["canonicalDisplayName"] == "DroneDream · FIELD"
    assert remediation["postSelection"]["installActionAllowed"] is False
    assert diagnosis["authorization"]["attempt1RetryAllowed"] is False
    assert diagnosis["authorization"]["currentMessageAuthorizesRed"] is False


def test_window_stage_and_ownership_fixtures_fail_closed() -> None:
    observer = str(OBSERVER).replace("'", "''")
    script = textwrap.dedent(
        f"""
        $ErrorActionPreference = 'Stop'
        $tokens = $null
        $errors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile(
          '{observer}', [ref]$tokens, [ref]$errors
        )
        if ($errors.Count -ne 0) {{ throw 'observer AST failed' }}
        foreach ($name in @(
          'Resolve-InstallerWindowStage', 'Protect-DiagnosticText',
          'Get-DiagnosticWindowRecord', 'Add-PreclassificationSnapshot',
          'Select-SingleOwnedWindowRecord', 'Wait-SingleOwnedWindow'
        )) {{
          $function = $ast.Find({{
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
              $node.Name -eq $name
          }}, $true)
          if ($null -eq $function) {{ throw "missing $name" }}
          Invoke-Expression $function.Extent.Text
        }}

        $pidValue = 4242
        $display = 'DroneDream ' + [char]0x00B7 + ' FIELD'
        $root = 'C:\\Users\\fixture\\AppData\\Local\\DroneDream-Field'
        $fixtureProcess = [Diagnostics.Process]::GetCurrentProcess()
        $script:windowTitles = [Collections.Generic.Queue[string]]::new()
        function Get-SingleOwnedWindow {{
          param([int]$ProcessId)
          if ($ProcessId -ne $fixtureProcess.Id) {{ throw 'fixture received foreign process id' }}
          if ($script:windowTitles.Count -eq 0) {{ throw 'fixture title queue exhausted' }}
          return [pscustomobject]@{{ Current = [pscustomobject]@{{ Name = $script:windowTitles.Dequeue() }} }}
        }}
        $script:windowTitles.Enqueue('Installer Language')
        $firstWindow = Wait-SingleOwnedWindow -Process $fixtureProcess -DifferentFromTitle ''
        if ($firstWindow.Current.Name -cne 'Installer Language') {{ throw 'empty exclusion title fixture failed' }}
        $script:windowTitles.Enqueue('Installer Language')
        $script:windowTitles.Enqueue("$display Setup")
        $nextWindow = Wait-SingleOwnedWindow -Process $fixtureProcess -DifferentFromTitle 'Installer Language'
        if ($nextWindow.Current.Name -cne "$display Setup") {{ throw 'nonempty exclusion title fixture failed' }}
        $selectorControls = @(
          [ordered]@{{ controlType='ControlType.ComboBox'; automationId='1000'; name='English' }},
          [ordered]@{{ controlType='ControlType.Button'; automationId='1'; name='OK' }},
          [ordered]@{{ controlType='ControlType.Button'; automationId='2'; name='Cancel' }}
        )
        foreach ($locale in @('en', 'zh-CN')) {{
          $selector = [ordered]@{{
            processId=$pidValue; className='#32770'; title='Installer Language'
            visibleText=@('Please select a language.'); controls=$selectorControls
          }}
          $stage = Resolve-InstallerWindowStage -WindowRecord $selector -ExpectedProcessId $pidValue -ExpectedDisplayName $display -ExpectedInstallRoot $root
          if ($stage -cne 'language-selector') {{ throw "selector fixture failed: $locale" }}
        }}
        foreach ($percent in @(0, 67, 100)) {{
          $loadingTitle = "unpacking data: $percent%"
          $loadingText = 'Please wait while Setup is loading...'
          $loading = [ordered]@{{
            processId=$pidValue; className='#32770'; title=$loadingTitle
            visibleText=@($loadingTitle, $loadingText); controls=@(
              [ordered]@{{processId=$pidValue;controlType='ControlType.Text';automationId='1030';name=$loadingTitle;value=''}},
              [ordered]@{{processId=$pidValue;controlType='ControlType.Image';automationId='65535';name=$loadingTitle;value=''}},
              [ordered]@{{processId=$pidValue;controlType='ControlType.Text';automationId='76';name=$loadingText;value=''}}
            )
          }}
          if ((Resolve-InstallerWindowStage -WindowRecord $loading -ExpectedProcessId $pidValue -ExpectedDisplayName $display -ExpectedInstallRoot $root) -cne 'loading-progress') {{
            throw "loading progress fixture failed: $percent"
          }}
        }}

        $welcome = [ordered]@{{
          processId=$pidValue; className='#32770'; title="$display Setup"
          visibleText=@($display, 'Welcome'); controls=@()
        }}
        if ((Resolve-InstallerWindowStage -WindowRecord $welcome -ExpectedProcessId $pidValue -ExpectedDisplayName $display -ExpectedInstallRoot $root) -cne 'branded') {{
          throw 'branded fixture failed'
        }}
        $directory = [ordered]@{{
          processId=$pidValue; className='#32770'; title="$display Setup"
          visibleText=@($display); controls=@(
            [ordered]@{{controlType='ControlType.Edit'; automationId='1019'; name=''; value=$root}}
          )
        }}
        if ((Resolve-InstallerWindowStage -WindowRecord $directory -ExpectedProcessId $pidValue -ExpectedDisplayName $display -ExpectedInstallRoot $root) -cne 'directory') {{
          throw 'directory fixture failed'
        }}
        $diagnosticSnapshots = [Collections.Generic.List[object]]::new()
        $identityFailure = [ordered]@{{
          processId=$pidValue; className='#32770'; title='Unexpected Setup'
          automationId=''; visibleText=@('Welcome', 'token=do-not-record'); controls=@(
            [ordered]@{{controlType='ControlType.Text';automationId='10';name='password';value='secret-value'}},
            [ordered]@{{controlType='ControlType.Edit';automationId='11';name='';value='C:\\Sensitive\\outside'}}
          )
        }}
        $pending = Add-PreclassificationSnapshot -WindowRecord $identityFailure -ExpectedProcessId $pidValue -ExpectedInstallRoot $root -Snapshots $diagnosticSnapshots
        try {{
          Resolve-InstallerWindowStage -WindowRecord $identityFailure -ExpectedProcessId $pidValue -ExpectedDisplayName $display -ExpectedInstallRoot $root | Out-Null
          throw 'identity failure fixture unexpectedly accepted'
        }} catch {{
          if ($_.Exception.Message -eq 'identity failure fixture unexpectedly accepted') {{ throw }}
        }}
        if ($diagnosticSnapshots.Count -ne 1 -or $pending.stage -cne 'pending-classification') {{
          throw 'identity failure did not preserve its preclassification snapshot'
        }}
        $diagnosticJson = $diagnosticSnapshots | ConvertTo-Json -Depth 10 -Compress
        if ($diagnosticJson -match 'do-not-record|secret-value|C:\\\\Sensitive') {{
          throw 'diagnostic snapshot leaked sensitive fixture text'
        }}
        if ($diagnosticJson -notmatch '\\[redacted-sensitive\\]' -or $diagnosticJson -notmatch '\\[redacted-path\\]') {{
          throw 'diagnostic snapshot did not record explicit redaction markers'
        }}
        Select-SingleOwnedWindowRecord -WindowRecords @([ordered]@{{processId=$pidValue;title='owned'}}) -ExpectedProcessId $pidValue | Out-Null
        try {{
          Select-SingleOwnedWindowRecord -WindowRecords @() -ExpectedProcessId $pidValue | Out-Null
          throw 'zero-window fixture unexpectedly accepted'
        }} catch {{
          if ($_.Exception.Message -eq 'zero-window fixture unexpectedly accepted') {{ throw }}
          if ($_.Exception.Message -cne 'Expected exactly one visible top-level installer window; observed 0.') {{
            throw "zero-window fixture was not classified for bounded polling: $($_.Exception.Message)"
          }}
        }}

        $denied = 0
        $negativeCases = @(
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=99;className='#32770';title='Installer Language';visibleText=@('Please select a language.');controls=$selectorControls}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='Unknown Dialog';visibleText=@();controls=@()}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='Installer Language';visibleText=@('Please select a language.');controls=@()}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title="$display Setup";visibleText=@($display);controls=@([ordered]@{{controlType='ControlType.Edit';value='C:\\Wrong'}})}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='unpacking data: 101%';visibleText=@('Please wait while Setup is loading...');controls=@()}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='unpacking data: 67%';visibleText=@('Loading text drifted');controls=@()}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='unpacking data: 67%';visibleText=@('unpacking data: 67%','Please wait while Setup is loading...');controls=@([ordered]@{{processId=$pidValue;controlType='ControlType.Button';automationId='1';name='Continue';value=''}})}} }},
          [ordered]@{{ kind='ownership'; value=@([ordered]@{{processId=$pidValue}},[ordered]@{{processId=$pidValue}}) }},
          [ordered]@{{ kind='ownership'; value=@([ordered]@{{processId=99}}) }}
        )
        foreach ($case in $negativeCases) {{
          try {{
            if ($case.kind -eq 'resolve') {{
              Resolve-InstallerWindowStage -WindowRecord $case.value -ExpectedProcessId $pidValue -ExpectedDisplayName $display -ExpectedInstallRoot $root | Out-Null
            }} else {{
              Select-SingleOwnedWindowRecord -WindowRecords $case.value -ExpectedProcessId $pidValue | Out-Null
            }}
            throw 'fixture unexpectedly accepted'
          }} catch {{
            if ($_.Exception.Message -eq 'fixture unexpectedly accepted') {{ throw }}
            $denied++
          }}
        }}
        if ($denied -ne 9) {{ throw "expected 9 denials, got $denied" }}
        Write-Output 'field-installer-observer-fixtures-passed'
        """
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "field-installer-observer-fixtures-passed" in result.stdout
