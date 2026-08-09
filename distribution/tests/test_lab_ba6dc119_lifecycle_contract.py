from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution/editions/lab/lifecycle"
APPLICATION = LIFECYCLE / "final-ba6dc119-app-only-application.v1.json"
PLAN = LIFECYCLE / "final-ba6dc119-app-only-plan.v1.json"
TARGET = LIFECYCLE / "final-ba6dc119-app-only-target-receipt.v1.json"
COMMAND = LIFECYCLE / "final-ba6dc119-app-only-command.v1.json"
STATIC_RECEIPT = (
    ROOT / "distribution/build-receipts/lab-ba6dc119-yellow-attempt14-static-passed.json"
)
RUNNER = LIFECYCLE / "run-lab-final-app-only-lifecycle.ps1"
STAGER = LIFECYCLE / "stage-lab-final-lifecycle-input.ps1"

PRODUCT_SOURCE = "ba6dc119e44721b807c455a2183887102566f73e"
ARTIFACT_SHA256 = "a7a9e2bfebb96cd06f88e70c02cd74bc8ab9c0a24a195ae2d50cdac5e74d6b2b"
ARTIFACT_BYTES = 12_551_766


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lf_identity(path: Path) -> tuple[int, str]:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return len(data), hashlib.sha256(data).hexdigest()


def _assert_powershell_parses(path: Path) -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        f"[Management.Automation.Language.Parser]::ParseFile('{path}',"
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


def test_attempt14_static_acceptance_is_exact_but_not_release_ready() -> None:
    receipt = _load(STATIC_RECEIPT)

    assert receipt["productSource"]["commit"] == PRODUCT_SOURCE
    assert receipt["attempt"] == {
        "globalBuildOrdinal": 14,
        "maximumBuildInvocations": 1,
        "actualBuildInvocations": 1,
        "automaticRetryMaximum": 0,
        "retryPerformed": False,
    }
    assert receipt["artifact"]["bytes"] == ARTIFACT_BYTES
    assert receipt["artifact"]["sha256"] == ARTIFACT_SHA256
    assert receipt["artifact"]["authenticodeStatus"] == "NotSigned"
    assert receipt["iconAcceptance"]["result"] == "passed"
    assert receipt["iconAcceptance"]["installerAndAppPeIconsMatch"] is True
    assert receipt["iconAcceptance"]["allProductPeSurfacesDisplayLabGreen"] is True
    assert receipt["releaseReady"] is False
    assert receipt["websiteHandoffReady"] is False


def test_lifecycle_application_binds_artifact_contracts_and_tools() -> None:
    application = _load(APPLICATION)
    command = _load(COMMAND)

    assert application["sourceSeparation"]["artifactProductSourceCommit"] == PRODUCT_SOURCE
    assert application["artifact"]["bytes"] == ARTIFACT_BYTES
    assert application["artifact"]["sha256"] == ARTIFACT_SHA256
    assert application["plan"]["sha256"] == _sha(PLAN)
    assert application["targetReceipt"]["sha256"] == _sha(TARGET)
    assert application["staticAcceptanceReceipt"]["sha256"] == _sha(STATIC_RECEIPT)
    assert command["application"]["bytes"] == APPLICATION.stat().st_size
    assert command["application"]["sha256"] == _sha(APPLICATION)
    assert command["plan"]["sha256"] == _sha(PLAN)
    assert command["targetReceipt"]["sha256"] == _sha(TARGET)

    for contract_key, path in (
        ("stagingAdapter", STAGER),
        ("adapter", RUNNER),
        ("liveInspector", LIFECYCLE / "inspect-lab-e3b427e-live-webview2.mjs"),
        (
            "requestDiagnosticsClassifier",
            LIFECYCLE / "lab-request-origin-diagnostics.mjs",
        ),
    ):
        expected = application["executionTools"][contract_key]
        assert (expected["lfNormalizedBytes"], expected["lfNormalizedSha256"]) == (
            _lf_identity(path)
        )


def test_staging_manifest_is_minimal_exact_and_non_traversing() -> None:
    application = _load(APPLICATION)
    staging = application["ownedIsolation"]["staging"]
    inputs = staging["inputs"]

    assert staging["maximumInvocations"] == 1
    assert staging["invocationsAtFreeze"] == 0
    assert staging["automaticRetryMaximum"] == 0
    assert staging["additionalInputsAllowed"] is False
    assert staging["preservesRepositoryRelativePaths"] is True
    assert len(inputs) + 1 == 10
    assert len({item["relativePath"] for item in inputs}) == len(inputs)

    for item in inputs:
        relative = item["relativePath"]
        assert not Path(relative).is_absolute()
        assert ".." not in relative
        assert ":" not in relative
        if item["sourceClass"] == "repository-relative":
            source = ROOT / relative
            if item.get("hashMode", "exact-bytes") == "lf-normalized":
                assert _lf_identity(source) == (item["bytes"], item["sha256"])
            else:
                assert source.stat().st_size == item["bytes"]
                assert _sha(source) == item["sha256"]
        else:
            assert item["sourceClass"] == "exact-absolute-artifact"
            assert relative == "artifact/DroneDream-Lab-1.0.0.exe"
            assert item["bytes"] == ARTIFACT_BYTES
            assert item["sha256"] == ARTIFACT_SHA256


def test_provider_identity_and_current_lab_are_fail_closed() -> None:
    application = _load(APPLICATION)
    command = _load(COMMAND)
    runner = RUNNER.read_text(encoding="utf-8-sig")
    stager = STAGER.read_text(encoding="utf-8-sig")

    assert application["provider"]["accountName"] == "CodexSandboxOffline"
    assert application["provider"]["profileLoadedAtFreeze"] is False
    assert application["provider"]["passwordRequired"] is True
    assert application["provider"]["passwordReadOrRecordedAllowed"] is False
    assert application["ownedIsolation"]["currentZju20CanonicalLabProtected"] is True
    assert command["provider"]["passwordPromptMustBeHandledByOperator"] is True
    assert command["provider"]["passwordMayBeReadRecordedOrPassedAsArgument"] is False
    assert "Execution is permitted only inside the exact disposable Windows user profile" in runner
    assert "$env:USERNAME -cne $expectedProvider" in runner
    assert "$actualProfile -cne $expectedProfile" in runner
    assert 'StartsWith("\\\\")' in stager
    assert 'Relative.Contains("..")' in stager
    assert "Unknown lifecycle staging input source class" in stager
    assert "additionalInputsAllowed -ne $false" in stager
    assert stager.index("if (-not $Execute)") < stager.index("New-Item -ItemType Directory")


@pytest.mark.parametrize("unsafe_relative", ["../escape", "//server/share", "C:/escape"])
def test_stager_rejects_traversal_unc_and_drive_paths(
    tmp_path: Path, unsafe_relative: str
) -> None:
    application = _load(APPLICATION)
    application["ownedIsolation"]["staging"]["inputs"][1]["relativePath"] = (
        unsafe_relative
    )
    output_root = (
        Path("C:/Users/Public/DroneDream-Codex/Lab-RED")
        / f"pytest-{tmp_path.name}-{unsafe_relative[0].encode().hex()}"
    )
    application["ownedIsolation"]["stagingRoot"] = output_root.as_posix()
    temp_application = (
        tmp_path
        / "distribution/editions/lab/lifecycle"
        / APPLICATION.name
    )
    temp_application.parent.mkdir(parents=True)
    temp_application.write_text(
        json.dumps(application, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    application_sha = _sha(temp_application)

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STAGER),
            "-Application",
            str(temp_application),
            "-ExpectedApplicationSha256",
            application_sha,
            "-SourceRoot",
            str(tmp_path),
            "-OutputRoot",
            str(output_root),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Staging paths must be simple relative paths without traversal" in (
        result.stdout + result.stderr
    )
    assert not output_root.exists()


def test_stager_rejects_additional_inputs_flag(tmp_path: Path) -> None:
    application = _load(APPLICATION)
    application["ownedIsolation"]["staging"]["additionalInputsAllowed"] = True
    output_root = (
        Path("C:/Users/Public/DroneDream-Codex/Lab-RED")
        / f"pytest-{tmp_path.name}-additional-inputs"
    )
    application["ownedIsolation"]["stagingRoot"] = output_root.as_posix()
    temp_application = (
        tmp_path
        / "distribution/editions/lab/lifecycle"
        / APPLICATION.name
    )
    temp_application.parent.mkdir(parents=True)
    temp_application.write_text(
        json.dumps(application, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STAGER),
            "-Application",
            str(temp_application),
            "-ExpectedApplicationSha256",
            _sha(temp_application),
            "-SourceRoot",
            str(tmp_path),
            "-OutputRoot",
            str(output_root),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "one-shot staging contract is missing or unsafe" in (
        result.stdout + result.stderr
    )
    assert not output_root.exists()


def test_languages_icons_theme_and_hardware_authority_are_exact() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    target = _load(TARGET)
    command = _load(COMMAND)
    runner = RUNNER.read_text(encoding="utf-8-sig")
    counts = application["segments"]["a"]["exactCounts"]

    assert counts == plan["exactCounts"] == target["requiredExactCounts"]
    assert counts == command["exactCounts"]
    assert application["installerLanguages"]["fresh"]["id"] == "1033"
    assert application["installerLanguages"]["overlay"]["id"] == "2052"
    assert 'Arguments @("/S", "/LANG=1033")' in runner
    assert 'Arguments @("/S", "/UPDATE", "/LANG=2052")' in runner
    assert application["iconAcceptance"]["requiredSurfaces"] == [
        "installer",
        "installed-exe",
        "desktop-shortcut",
        "start-menu-shortcut",
    ]
    assert application["liveAssertions"]["themePalette"] == [
        "#A7E84A",
        "#20C77A",
        "#087E69",
    ]
    assert application["liveAssertions"]["themeSettingsAndThreeDGrantHardwareAuthority"] is False
    assert application["safety"]["validatedVehiclePackCount"] == 0
    assert application["safety"]["hardwareWriteArmHitlFlightDecision"] == "deny"
    for forbidden_count in (
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
        assert counts[forbidden_count] == 0


def test_commands_are_frozen_but_not_authorized_and_scripts_parse() -> None:
    command = _load(COMMAND)
    serialized = json.dumps(command, ensure_ascii=True).lower()

    assert command["staging"]["executionAuthorizedNow"] is False
    assert command["segmentA"]["executionAuthorizedNow"] is False
    assert command["authorization"]["newExactStartSignalRequired"] is True
    assert command["segmentA"]["ordinal"] == 1
    assert command["segmentA"]["maximumExecutionInvocations"] == 1
    assert command["segmentA"]["automaticRetryMaximum"] == 0
    assert command["segmentA"]["operatorInteractiveLauncherCommand"].startswith(
        "runas.exe /profile /user:.\\CodexSandboxOffline "
    )
    for forbidden_secret in (
        "openai_api_key",
        "service_role",
        "tauri_signing_private_key",
        "password=",
        "token=",
        "cookie=",
    ):
        assert forbidden_secret not in serialized

    _assert_powershell_parses(RUNNER)
    _assert_powershell_parses(STAGER)
