import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution" / "editions" / "field" / "lifecycle"
APPLICATION = LIFECYCLE / "final-95a4623-disposable-lifecycle-application.v1.json"
PLAN = LIFECYCLE / "final-95a4623-disposable-lifecycle-plan.v1.json"
COMMAND = LIFECYCLE / "final-95a4623-disposable-lifecycle-command.v1.json"
STAGER = LIFECYCLE / "stage-field-final-lifecycle-input.ps1"
RUNNER = LIFECYCLE / "run-field-final-disposable-lifecycle.ps1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lf_identity(path: Path) -> tuple[int, str]:
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    payload = normalized.encode()
    return len(payload), hashlib.sha256(payload).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_application_binds_exact_product_artifact_provider_and_tools() -> None:
    application = load(APPLICATION)
    assert application["productSource"] == {
        "commit": "95a4623f935fc82af0c3912528c57054f4aaa0a7",
        "tree": "860bc5fa6481f57c7f40739cc208f234b47abd06",
    }
    assert application["artifact"]["bytes"] == 6_348_757
    assert application["artifact"]["sha256"] == (
        "153c1eadbe07fa51a2bc050755e0aa2fec2e40f1a2bd7710f2b9640f4ccb97ff"
    )
    provider = application["provider"]
    assert provider["accountName"] == "CodexSandboxOffline"
    assert provider["sid"] == "S-1-5-21-2197768555-4123441877-442284878-1020"
    assert provider["profileRoot"] == "C:/Users/CodexSandboxOffline"
    assert provider["passwordReadRecordedOrPassedAllowed"] is False
    assert provider["zju20CanonicalFieldFallbackAllowed"] is False
    for name, path in (("stagingAdapter", STAGER), ("runner", RUNNER)):
        size, digest = lf_identity(path)
        assert application["tools"][name]["lfNormalizedBytes"] == size
        assert application["tools"][name]["lfNormalizedSha256"] == digest


def test_command_is_interactive_one_shot_and_never_carries_password() -> None:
    command = load(COMMAND)
    application = command["application"]
    assert application["bytes"] == APPLICATION.stat().st_size
    assert application["sha256"] == sha256(APPLICATION)
    runas = command["commands"]["operatorInteractiveRunas"]
    assert runas.startswith("runas.exe /profile /user:.\\CodexSandboxOffline ")
    assert "-Execute" in runas
    assert "password" not in runas.lower()
    assert command["attempt"] == {
        "ordinal": 1,
        "maximum": 1,
        "executionsAtFreeze": 0,
        "stagingMaximum": 1,
        "stagingAtFreeze": 0,
        "retryMaximum": 0,
    }
    assert command["authorization"]["executeNow"] is False


def test_runner_fails_closed_on_provider_and_dangerous_boundaries() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    for required in (
        '$env:USERNAME -cne $expectedUser',
        "$actualUser.User.Value -cne $expectedSid",
        "$actualProfile -cne $expectedProfile",
        'throw "Execution is restricted to the exact CodexSandboxOffline account',
        'browserLaunches = 0',
        'oauthTransactions = 0',
        'runtimeActions = 0',
        'px4Actions = 0',
        'gazeboActions = 0',
        'hardwareActions = 0',
    ):
        assert required in runner
    assert "WindowsSandbox" not in runner
    assert "Enable-WindowsOptionalFeature" not in runner
    assert "service_role" not in runner
    assert "C:\\Users\\zju20\\AppData\\Local\\DroneDream-Field" not in runner


def test_plan_is_honest_about_live_settings_auth_boundary() -> None:
    application = load(APPLICATION)
    plan = load(PLAN)
    assert application["counts"] == plan["counts"]
    assert plan["counts"]["settingsLiveChecks"] == 0
    assert plan["uiAcceptance"]["settingsStaticEvidenceBound"] is True
    assert plan["uiAcceptance"]["settingsLiveExecutionState"].startswith("deferred-fail-closed")
    assert application["inspection"]["externalBrowserAllowed"] is False
    assert application["inspection"]["oauthAllowed"] is False
    assert application["safety"]["validatedVehiclePackCount"] == 0
    assert application["safety"]["hardwareWriteArmHitlFlightDecision"] == "deny"


def test_owned_roots_are_exact_and_distinct() -> None:
    application = load(APPLICATION)
    staging = application["isolation"]["stagingRoot"]
    run_root = application["isolation"]["runRoot"]
    assert staging == (
        "C:/Users/Public/DroneDream-Codex/Field-RED/"
        "field-95a4623-segment-a-red1-input"
    )
    assert run_root == (
        "C:/Users/CodexSandboxOffline/AppData/Local/DroneDream-Codex/Field-RED/"
        "field-95a4623-segment-a-red1"
    )
    assert staging != run_root
    assert application["isolation"]["currentZju20CanonicalFieldProtected"] is True
