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
        foreach ($name in @('Resolve-InstallerWindowStage', 'Select-SingleOwnedWindowRecord')) {{
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
        Select-SingleOwnedWindowRecord -WindowRecords @([ordered]@{{processId=$pidValue;title='owned'}}) -ExpectedProcessId $pidValue | Out-Null

        $denied = 0
        $negativeCases = @(
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=99;className='#32770';title='Installer Language';visibleText=@('Please select a language.');controls=$selectorControls}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='Unknown Dialog';visibleText=@();controls=@()}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title='Installer Language';visibleText=@('Please select a language.');controls=@()}} }},
          [ordered]@{{ kind='resolve'; value=[ordered]@{{processId=$pidValue;className='#32770';title="$display Setup";visibleText=@($display);controls=@([ordered]@{{controlType='ControlType.Edit';value='C:\\Wrong'}})}} }},
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
        if ($denied -ne 6) {{ throw "expected 6 denials, got $denied" }}
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
