from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution/editions/lab/lifecycle"
APPLICATION = LIFECYCLE / "final-29730d5-app-only-application.v1.json"
PLAN = LIFECYCLE / "final-29730d5-app-only-plan.v1.json"
TARGET = LIFECYCLE / "final-29730d5-app-only-target-receipt.v1.json"
RUNNER = LIFECYCLE / "run-lab-final-app-only-lifecycle.ps1"
INSPECTOR = LIFECYCLE / "inspect-lab-e3b427e-live-webview2.mjs"
CLASSIFIER = LIFECYCLE / "lab-request-origin-diagnostics.mjs"


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
    for key, path in (
        ("adapter", RUNNER),
        ("liveInspector", INSPECTOR),
        ("requestDiagnosticsClassifier", CLASSIFIER),
    ):
        assert application["executionTools"][key]["lfNormalizedSha256"] == _lf_sha(path)


def test_final_lifecycle_is_one_shot_owned_and_fail_closed() -> None:
    application = _load(APPLICATION)
    counts = application["segments"]["a"]["exactCounts"]

    assert application["attempt"]["maximumExecutionInvocations"] == 1
    assert application["attempt"]["automaticRetryMaximum"] == 0
    assert application["ownedIsolation"]["runId"] == "lab-final-29730d5-segment-a-1"
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
    assert "e3b427e9d1d6209495d629c399a1962913f2d00c" not in source
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
