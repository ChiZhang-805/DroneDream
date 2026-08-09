import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
APPLICATION = REPO / "distribution/sim/lifecycle/red-85903ff6-codex-sandbox-application-10.v1.json"
HOST = REPO / "distribution/sim/tools/invoke-red-lifecycle-codex-sandbox-host-85903ff6.ps1"
VISIBLE_HOST = REPO / (
    "distribution/sim/tools/"
    "invoke-red-lifecycle-codex-sandbox-visible-host-85903ff6.ps1"
)
GUEST = REPO / "distribution/sim/tools/invoke-red-lifecycle-codex-sandbox-85903ff6.ps1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_application() -> dict:
    return json.loads(APPLICATION.read_text(encoding="utf-8"))


def test_application_binds_frozen_artifact_and_tool_bundle() -> None:
    application = load_application()
    assert application["editionId"] == "sim"
    assert application["executionOrdinal"] == 10
    assert application["state"] == "awaiting-user-present-start"
    assert application["sourceSeparation"]["productSourceCommit"] == (
        "573e8f991eba703bbfd6c4b35f464fbaab78903c"
    )
    assert application["artifact"]["bytes"] == 12_070_633
    assert application["artifact"]["sha256"] == (
        "85903ff6a5dad93224f5396096d90f2e96e71eb5e68980df7ca2691d8001ddae"
    )
    tools = application["toolBundle"]
    assert tools["visibleHostBytes"] == VISIBLE_HOST.stat().st_size
    assert tools["visibleHostSha256"] == sha256(VISIBLE_HOST)
    assert tools["hostLauncherBytes"] == HOST.stat().st_size
    assert tools["hostLauncherSha256"] == sha256(HOST)
    assert tools["guestRunnerBytes"] == GUEST.stat().st_size
    assert tools["guestRunnerSha256"] == sha256(GUEST)
    for prefix in ("contract", "staticAcceptance"):
        path = REPO / tools[f"{prefix}Path"]
        assert tools[f"{prefix}Bytes"] == path.stat().st_size
        assert tools[f"{prefix}Sha256"] == sha256(path)


def test_disposable_user_and_owned_paths_are_exact() -> None:
    application = load_application()
    user = application["disposableWindowsUser"]
    assert user == {
        "userName": "CodexSandboxOffline",
        "sid": "S-1-5-21-2197768555-4123441877-442284878-1020",
        "profile": "C:/Users/CodexSandboxOffline",
        "hostPlanProfileState": "unloaded-or-inaccessible",
        "mustBePreExisting": True,
        "mustBeEnabled": True,
        "passwordEntry": "interactive-runas-window-by-user-only",
        "passwordReadAllowed": False,
        "passwordRecordAllowed": False,
        "passwordTransmitAllowed": False,
        "systemFeatureChangesAllowed": False,
    }
    owned = application["ownedSurface"]
    assert owned["sharedRoot"].startswith("C:/Users/Public/Documents/DroneDream-Codex/Sim-RED/")
    assert (
        owned["sandboxInstallRoot"] == "C:/Users/CodexSandboxOffline/AppData/Local/DroneDream-Sim"
    )
    assert (
        owned["canonicalCurrentUserSimInstallRoot"] == "C:/Users/zju20/AppData/Local/DroneDream-Sim"
    )
    assert (
        owned["canonicalCurrentUserInstallProtectedBySeparateProfileAndHostParitySnapshot"] is True
    )
    assert owned["allRootsMustBeAbsentBeforeExecution"] is True


def test_counts_and_authority_are_fail_closed() -> None:
    application = load_application()
    counts = application["acceptanceMatrix"]["exactMaximumCounts"]
    assert counts["hostLaunchers"] == 1
    assert counts["interactiveRunAsPrompts"] == 1
    assert counts["freshInstallerInvocations"] == 1
    assert counts["overlayInstallerInvocations"] == 1
    assert counts["applicationLaunches"] == 1
    assert counts["uninstallerInvocations"] == 1
    assert counts["automaticRetries"] == 0
    for denied in (
        "browserLoginTransactions",
        "realTokenExchanges",
        "credentialReads",
        "passwordReads",
        "systemFeatureChanges",
        "runtimeStarts",
        "px4Starts",
        "gazeboStarts",
        "hardwareActions",
        "artifactBuilds",
    ):
        assert counts[denied] == 0
    assert application["authorization"]["planOnlyAuthorized"] is True
    assert application["authorization"]["stageCopyAuthorized"] is False
    assert application["authorization"]["interactiveRunAsAuthorized"] is False
    assert application["authorization"]["installerExecutionAuthorized"] is False
    assert application["nonClaims"]["releaseReady"] is False


def test_host_launcher_has_one_interactive_runas_and_no_password_channel() -> None:
    host = HOST.read_text(encoding="utf-8")
    assert host.count('& "$env:SystemRoot\\System32\\runas.exe" @runAsArguments') == 1
    assert 'Start-Process -FilePath "$env:SystemRoot\\System32\\runas.exe"' not in host
    assert '"/user:.\\$expectedUserName"' in host
    assert "$expectedUserSid" in host
    assert 'Registry::HKEY_USERS\\$expectedUserSid' in host
    assert '"unloaded-or-inaccessible"' in host
    assert "Get-HostProtectedState" in host
    assert "canonicalCurrentUserProtectedStateUnchanged" in host
    assert "CodexSandboxOffline is occupied by another Edition lifecycle process" in host
    assert "$isInteractiveRunAs" in host
    assert "$isLifecycleScript" in host
    assert "\\s-File\\s+" in host
    assert "\\s-Mode\\s+(?:Execute|StageAndRunAs)" in host
    assert "-Command" not in host.partition("$conflictingLifecycleProcesses = @(")[2].partition(
        "if ($Mode -ceq"
    )[0]
    forbidden = ("ConvertTo-SecureString", "PSCredential", "-Credential", "Read-Host")
    assert all(token not in host for token in forbidden)


def test_conflict_filter_rejects_only_actual_lifecycle_process_shapes() -> None:
    host = HOST.read_text(encoding="utf-8")
    filter_block = host.partition("$conflictingLifecycleProcesses = @(")[2].partition(
        "if ($Mode -ceq"
    )[0]
    assert "/user:" in filter_block
    assert "CodexSandboxOffline" in filter_block
    assert "invoke-red-lifecycle|red-lifecycle" in filter_block
    assert "Execute|StageAndRunAs" in filter_block
    assert "-Command" not in filter_block


def test_visible_host_transcript_is_scoped_and_does_not_capture_password() -> None:
    visible_host = VISIBLE_HOST.read_text(encoding="utf-8")
    assert "host-launcher-evidence" in visible_host
    assert "Start-Transcript" in visible_host
    assert "-NoClobber" in visible_host
    assert "Visible host transcript escaped its exact evidence root" in visible_host
    assert "Visible host transcript already exists; retry is forbidden" in visible_host
    assert "[Console]::ReadKey($true)" in visible_host
    assert "[ConsoleKey]::Enter" in visible_host
    assert "readiness gate accepts only ENTER" in visible_host
    assert "-Mode StageAndRunAs" in visible_host
    assert "runas.exe" not in visible_host
    forbidden = ("ConvertTo-SecureString", "PSCredential", "-Credential", "Read-Host")
    assert all(token not in visible_host for token in forbidden)


def test_guest_runner_requires_exact_user_profile_and_shortcut_icon_source() -> None:
    guest = GUEST.read_text(encoding="utf-8")
    assert '$expectedUserName = "CodexSandboxOffline"' in guest
    assert '$expectedUserSid = "S-1-5-21-2197768555-4123441877-442284878-1020"' in guest
    assert '$expectedUserProfile = "C:\\Users\\CodexSandboxOffline"' in guest
    assert "WindowsIdentity]::GetCurrent()" in guest
    assert "shortcut icon source is not the installed Sim executable" in guest
    assert 'ValidateSet("Plan", "Execute")' in guest
    assert "Start-Process -FilePath $application -PassThru" in guest
    assert "TcpListener]::new([Net.IPAddress]::Loopback, 49211)" in guest


def test_brand_and_icon_acceptance_remain_canonical_sim() -> None:
    application = load_application()
    brand = application["canonicalSimBrand"]
    assert brand["icoSha256"] == (
        "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c"
    )
    assert brand["icoFrameCount"] == 9
    assert brand["centeredGapPixels"] == {"left": 53, "right": 53, "tolerance": 0}
    assert brand["staticInstallerAndAppIconPixelMatch"] is True
    assert brand["visibleInstalledShortcutAcceptancePending"] is True
