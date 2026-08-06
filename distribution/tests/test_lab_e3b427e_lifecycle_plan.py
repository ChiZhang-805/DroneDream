import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN = (
    ROOT
    / "distribution/editions/lab/lifecycle/"
    "red-e3b427e-app-only-plan.v1.json"
)
TARGET = PLAN.with_name("red-e3b427e-app-only-target-receipt.v1.json")
VERIFIER = PLAN.with_name("verify-lab-e3b427e-lifecycle-plan.ps1")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_plan_binds_exact_artifact_build_receipt_and_non_product_evidence() -> None:
    plan = _load(PLAN)
    receipt_path = ROOT / plan["buildReceipt"]["path"]

    assert plan["state"] == "green-plan-frozen-no-execute"
    assert plan["sourceSeparation"]["artifactProductSourceCommit"] == (
        "e3b427e9d1d6209495d629c399a1962913f2d00c"
    )
    assert plan["sourceSeparation"]["planEvidenceIsArtifactSource"] is False
    assert plan["artifact"]["fileName"] == "DroneDream-Lab-1.0.0.exe"
    assert plan["artifact"]["bytes"] == 12081900
    assert plan["artifact"]["sha256"] == (
        "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
    )
    assert _sha256(receipt_path) == plan["buildReceipt"]["sha256"]


def test_plan_binds_read_only_verifier_and_target_contract() -> None:
    plan = _load(PLAN)

    assert _sha256(VERIFIER) == plan["verificationTool"]["sha256"]
    assert _sha256(TARGET) == plan["targetReceipt"]["sha256"]
    assert plan["verificationTool"]["executeParameterPresent"] is False
    assert plan["verificationTool"]["mutationCapabilityPresent"] is False
    assert _load(TARGET)["state"] == "target-only-no-execution-evidence"


def test_verifier_has_no_execution_or_mutation_surface() -> None:
    verifier = VERIFIER.read_text(encoding="utf-8-sig")

    for forbidden in (
        "[switch]$Execute",
        "Start-Process",
        "Stop-Process",
        "Invoke-Item",
        "Remove-Item",
        "New-Item",
        "Set-ItemProperty",
        "New-ItemProperty",
        "Remove-ItemProperty",
        "Invoke-WebRequest",
        "msiexec",
        "reg.exe",
    ):
        assert forbidden not in verifier


@pytest.mark.skipif(
    not Path(
        "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    ).is_file(),
    reason="PowerShell is Windows-only",
)
def test_verifier_has_valid_powershell_ast() -> None:
    command = rf"""
      $tokens = $null
      $errors = $null
      [Management.Automation.Language.Parser]::ParseFile(
        '{str(VERIFIER).replace("'", "''")}',
        [ref]$tokens,
        [ref]$errors
      ) | Out-Null
      if ($errors.Count -ne 0) {{
        $errors | ForEach-Object {{ Write-Error $_.Message }}
        exit 1
      }}
    """
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_plan_segments_and_target_counts_are_identical() -> None:
    plan = _load(PLAN)
    target = _load(TARGET)

    assert [segment["id"] for segment in plan["segments"]] == [
        "A0",
        "A1",
        "A2",
        "A3",
        "B",
    ]
    assert plan["exactCounts"] == target["requiredExactCounts"]
    assert plan["exactCounts"]["freshInstallerInvocations"] == 1
    assert plan["exactCounts"]["overlayInstallerInvocations"] == 1
    assert plan["exactCounts"]["applicationLaunches"] == 2
    assert plan["exactCounts"]["uninstallerInvocations"] == 1
    assert plan["exactCounts"]["browserLaunches"] == 0
    assert plan["exactCounts"]["providerTokenExchanges"] == 0


def test_plan_protects_base_runtime_other_editions_and_provider_boundary() -> None:
    plan = _load(PLAN)
    protected = plan["protectedState"]
    providers = plan["providers"]

    assert protected["labOwnedNamespaceFresh"] is True
    assert protected["baseApp"]["installRootExists"] is True
    assert protected["runtime"]["mutationAllowed"] is False
    assert protected["otherEditions"]["simProductKeyExists"] is True
    assert protected["otherEditions"]["parityRequiredAfterEveryMutationSegment"] is True
    assert providers["webView2"]["installRepairOrUpdateAllowed"] is False
    assert providers["browserAndOAuth"]["state"] == (
        "blocked-not-authorized-not-required-for-segment-a"
    )
    assert providers["browserAndOAuth"]["providerCallAllowed"] is False


def test_plan_keeps_settings_theme_and_hardware_authority_separate() -> None:
    plan = _load(PLAN)
    ui = plan["uiAcceptance"]
    safety = plan["safety"]

    assert ui["settingsSingleScreenNoVerticalScroll"] is True
    assert ui["fixedThemeEdition"] == "lab"
    assert ui["themePalette"] == ["#A7E84A", "#20C77A", "#087E69"]
    assert ui["settingsOrThemeGrantsHardwareAuthority"] is False
    assert safety["validatedVehiclePackCount"] == 0
    assert safety["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert safety["requiredAuthorityLayers"] == ["native", "backend", "runtime"]


def test_plan_is_not_red_requestable_until_new_adapter_and_signal() -> None:
    plan = _load(PLAN)

    assert plan["redReadiness"]["planVerifierAndTargetFrozen"] is True
    assert plan["redReadiness"]["exactRedRequestable"] is False
    assert "historical debd064 runner" in plan["redReadiness"]["blockers"][0]
    assert plan["authorization"]["executionAuthorized"] is False
    assert all(value == 0 for value in plan["executedCounts"].values())
    assert plan["nonClaims"]["installerExecuted"] is False
    assert plan["nonClaims"]["applicationLaunched"] is False
    assert plan["nonClaims"]["releaseReady"] is False
