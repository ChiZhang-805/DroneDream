from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution/editions/lab/lifecycle"
APPLICATION = LIFECYCLE / "final-29730d5-app-only-application-v3.v1.json"
PLAN = LIFECYCLE / "final-29730d5-app-only-plan.v1.json"
TARGET = LIFECYCLE / "final-29730d5-app-only-target-receipt.v1.json"
RUNNER = LIFECYCLE / "run-lab-final-app-only-lifecycle.ps1"
INSPECTOR = LIFECYCLE / "inspect-lab-e3b427e-live-webview2.mjs"
CLASSIFIER = LIFECYCLE / "lab-request-origin-diagnostics.mjs"
FINAL_MANIFEST = (
    ROOT / "distribution/build-receipts/lab-final-1.0.0-29730d5.manifest.json"
)
FINAL_HANDOFF = (
    ROOT / "distribution/editions/lab/website-exact-exe-handoff.final.v1.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lf_sha(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_final_lifecycle_contract_binds_exact_artifact_and_tools() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    target = _load(TARGET)

    assert application["sourceSeparation"]["artifactProductSourceCommit"] == (
        "29730d5d9928817872d7b9dca9e853873b7acdc3"
    )
    assert application["artifact"]["sha256"] == (
        "c8357f8b936e2109a7a88679744875bac15d8c89127a09b57895b37bbfd89c7e"
    )
    assert application["artifact"]["bytes"] == 12464388
    assert application["artifact"]["sha256"] == plan["artifact"]["sha256"]
    assert application["artifact"]["sha256"] == target["artifact"]["sha256"]
    assert application["plan"]["sha256"] == _sha(PLAN)
    assert application["targetReceipt"]["sha256"] == _sha(TARGET)
    assert application["executionTools"]["adapter"]["lfNormalizedSha256"] == (
        "7d704aa296f9165875fadff45b0e500c69b747035d34611fa94a46cbf3794756"
    )
    for key, path in (
        ("liveInspector", INSPECTOR),
        ("requestDiagnosticsClassifier", CLASSIFIER),
    ):
        assert application["executionTools"][key]["lfNormalizedSha256"] == _lf_sha(path)


def test_final_lifecycle_is_one_shot_owned_and_fail_closed() -> None:
    application = _load(APPLICATION)
    counts = application["segments"]["a"]["exactCounts"]

    assert application["attempt"]["maximumExecutionInvocations"] == 1
    assert application["attempt"]["automaticRetryMaximum"] == 0
    assert application["ownedIsolation"]["runId"] == "lab-final-29730d5-segment-a-3"
    assert counts == _load(PLAN)["exactCounts"]
    assert counts == _load(TARGET)["requiredExactCounts"]
    for name in (
        "browserLaunches",
        "oauthBoundaryChecks",
        "providerTokenExchanges",
        "accountReads",
        "artifactBuilds",
        "runtimeStartsOrMigrations",
        "px4Starts",
        "gazeboStarts",
        "hardwareActions",
        "uploadsOrDeployments",
    ):
        assert counts[name] == 0
    assert application["safety"]["validatedVehiclePackCount"] == 0
    assert application["safety"]["hardwareWriteArmHitlFlightDecision"] == "deny"
    assert application["liveAssertions"]["themePalette"] == [
        "#A7E84A",
        "#20C77A",
        "#087E69",
    ]
    assert application["liveAssertions"]["themeSettingsAndThreeDGrantHardwareAuthority"] is False


def test_final_lifecycle_runner_is_parameterized_and_parses() -> None:
    source = RUNNER.read_text(encoding="utf-8-sig")
    assert "$ExpectedProductSourceCommit" in source
    assert "$productSource = $ExpectedProductSourceCommit" in source
    assert "maximumExecutionInvocations -ne 1" in source
    assert "automaticRetryMaximum -ne 0" in source
    for non_product_directory in (
        '"codex-cache"',
        '"codex-dependencies"',
        '"codex-handoffs"',
        '"codex-runs"',
        '"codex-sandboxes"',
        '"handoffs"',
        '"validation"',
    ):
        assert non_product_directory in source
    assert "ExcludedTopLevelNames" in source
    assert "e3b427e9d1d6209495d629c399a1962913f2d00c" not in source
    assert "Get-NormalizedShortcutIconSource" in source
    assert "Write-LabIconEvidence" in source
    assert "windows-shell-rendered-icon-evidence" in source
    assert "67b5747de298ffcf64d062294829306bd9b66df4ee52cfa8a8e3498cb94d5fa1" in source
    assert "e8d22185013bb6e15bdabb2a03fd82a8f6b5d7db690d336f8067ff6e0a7dcfcc" in source
    assert "installerAndAppPeIconsMatch" in source
    assert "allProductSurfacesDisplayLabGreen" in source
    assert 'Arguments @("/S", "/LANG=1033")' in source
    assert 'Arguments @("/S", "/UPDATE", "/LANG=2052")' in source
    assert "Assert-InstallerLanguage" in source
    for forbidden in (
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "wsl.exe",
        "PX4",
        "Gazebo",
    ):
        assert forbidden not in source

    command = (
        "$tokens=$null;$errors=$null;"
        f"[Management.Automation.Language.Parser]::ParseFile('{RUNNER}',"
        "[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count){$errors|ForEach-Object{$_.ToString()};exit 1}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_final_website_handoff_is_exact_and_not_deployed() -> None:
    manifest = _load(FINAL_MANIFEST)
    handoff = _load(FINAL_HANDOFF)

    assert handoff["productSource"]["commit"] == manifest["productSource"]["commit"]
    assert handoff["files"]["installer"]["sha256"] == manifest["artifact"]["sha256"]
    assert handoff["files"]["updaterSignature"]["sha256"] == manifest[
        "updaterSignature"
    ]["sha256"]
    assert handoff["files"]["manifest"]["sha256"] == _sha(FINAL_MANIFEST)
    assert handoff["files"]["manifest"]["bytes"] == FINAL_MANIFEST.stat().st_size
    assert handoff["validation"]["freshInstall"] == "passed"
    assert handoff["validation"]["sameVersionOverlay"] == "passed"
    assert handoff["validation"]["uninstallAndOwnedCleanup"] == "passed"
    assert handoff["publication"]["internalPreviewReady"] is True
    assert handoff["publication"]["publicReleaseReady"] is False
    assert handoff["publication"]["websiteDeploymentPerformed"] is False
    assert handoff["safety"]["validatedVehiclePackCount"] == 0
    assert handoff["safety"]["hardwareWriteArmHitlFlightDecision"] == "deny"
