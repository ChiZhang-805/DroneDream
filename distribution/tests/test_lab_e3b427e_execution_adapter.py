import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution/editions/lab/lifecycle"
APPLICATION = LIFECYCLE / "red-e3b427e-app-only-application-v3.v1.json"
COMMAND = LIFECYCLE / "red-e3b427e-app-only-command-v3.v1.json"
PLAN = LIFECYCLE / "red-e3b427e-app-only-plan.v1.json"
TARGET = LIFECYCLE / "red-e3b427e-app-only-target-receipt.v1.json"
ADAPTER = LIFECYCLE / "run-lab-e3b427e-app-only-lifecycle.ps1"
INSPECTOR = LIFECYCLE / "inspect-lab-e3b427e-live-webview2.mjs"
SELECTOR_FIXTURE = LIFECYCLE / "verify-lab-e3b427e-selector-v2.mjs"
REQUEST_DIAGNOSTICS = LIFECYCLE / "lab-request-origin-diagnostics.mjs"
REQUEST_FIXTURE = LIFECYCLE / "verify-lab-e3b427e-request-diagnostics-v3.mjs"
SOURCE_AUDIT = LIFECYCLE / "request-origin-source-audit.v1.json"
CONSUMED_COMMAND = LIFECYCLE / "red-e3b427e-app-only-command-v2.v1.json"
FAILURE_RECEIPT = (
    ROOT
    / "distribution/build-receipts/"
    "lab-e3b427e-red-segment-a1-failure.json"
)
SECOND_FAILURE_RECEIPT = (
    ROOT
    / "distribution/build-receipts/"
    "lab-e3b427e-red-segment-a2-failure.json"
)
SUCCESS_RECEIPT = (
    ROOT
    / "distribution/build-receipts/"
    "lab-e3b427e-red-segment-a3-success.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(_lf_bytes(path)).hexdigest()


def test_application_binds_exact_product_artifact_plan_target_and_tools() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)
    target = _load(TARGET)

    assert application["sourceSeparation"]["artifactProductSourceCommit"] == (
        "e3b427e9d1d6209495d629c399a1962913f2d00c"
    )
    assert application["sourceSeparation"]["applicationEvidenceIsArtifactSource"] is False
    assert application["artifact"]["sha256"] == (
        "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
    )
    assert application["artifact"]["bytes"] == 12081900
    assert application["artifact"]["sha256"] == plan["artifact"]["sha256"]
    assert application["artifact"]["sha256"] == target["artifact"]["sha256"]
    assert application["plan"]["sha256"] == _sha256(PLAN)
    assert application["targetReceipt"]["sha256"] == _sha256(TARGET)

    for key, path in (
        ("adapter", ADAPTER),
        ("liveInspector", INSPECTOR),
        ("requestDiagnosticsClassifier", REQUEST_DIAGNOSTICS),
        ("requestDiagnosticsFixture", REQUEST_FIXTURE),
    ):
        tool = application["executionTools"][key]
        assert tool["lfNormalizedBytes"] == len(_lf_bytes(path))
        assert tool["lfNormalizedSha256"] == _lf_sha256(path)


def test_application_and_command_freeze_exact_counts_without_execution() -> None:
    application = _load(APPLICATION)
    command = _load(COMMAND)
    plan = _load(PLAN)
    target = _load(TARGET)
    counts = application["segments"]["a"]["exactCounts"]

    assert counts == plan["exactCounts"]
    assert counts == target["requiredExactCounts"]
    assert counts == command["exactCounts"]
    assert counts["freshInstallerInvocations"] == 1
    assert counts["overlayInstallerInvocations"] == 1
    assert counts["applicationLaunches"] == 2
    assert counts["applicationCloses"] == 2
    assert counts["uninstallerInvocations"] == 1
    assert counts["ownedPreferenceKeyCleanupInvocations"] == 1
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

    assert application["authorization"]["executionAuthorized"] is False
    assert application["attempt"]["segmentAOrdinal"] == 3
    assert application["attempt"]["priorCommandConsumed"] is True
    assert command["authorization"]["redCommandAuthorizedNow"] is False
    assert command["executedCounts"] == {
        "requestDiagnosticsFixtureInvocations": 1,
        "planOnlyCommandInvocations": 1,
        "redCommandInvocations": 0,
        "installerInvocations": 0,
        "applicationLaunches": 0,
        "uninstallerInvocations": 0,
    }
    assert command["greenValidation"]["planOnlyResult"] == (
        "green-plan-only-preflight-passed-no-execute"
    )
    assert command["greenValidation"]["ownedOutputRootAbsentBeforeAndAfter"] is True


def test_command_contract_binds_application_and_separates_plan_only_from_red() -> None:
    command = _load(COMMAND)

    assert command["application"]["bytes"] == APPLICATION.stat().st_size
    assert command["application"]["sha256"] == _sha256(APPLICATION)
    assert command["plan"]["sha256"] == _sha256(PLAN)
    assert command["targetReceipt"]["sha256"] == _sha256(TARGET)
    assert " -Execute" not in command["planOnlyCommand"]
    assert command["redCommand"].endswith(" -Execute")
    assert command["ownedOutputRoot"]["planOnlyCommandMayCreatePath"] is False
    assert command["ownedOutputRoot"][
        "redCommandMayCreatePathOnlyAfterNewExactStartSignal"
    ] is True
    for tool, path in (
        ("adapter", ADAPTER),
        ("liveInspector", INSPECTOR),
        ("requestDiagnosticsClassifier", REQUEST_DIAGNOSTICS),
        ("requestDiagnosticsFixture", REQUEST_FIXTURE),
    ):
        assert command["tools"][tool]["lfNormalizedSha256"] == _lf_sha256(path)
    assert command["tools"]["requestOriginSourceAudit"]["sha256"] == _sha256(
        SOURCE_AUDIT
    )
    assert command["attempt"]["segmentAOrdinal"] == 3
    assert command["attempt"]["priorCommandConsumed"] is True
    assert command["attempt"]["priorCommandSha256"] == _sha256(CONSUMED_COMMAND)


def test_adapter_has_a_no_write_plan_only_gate_and_owned_a1_a2_a3_sequence() -> None:
    source = ADAPTER.read_text(encoding="utf-8-sig")
    plan_gate = source.index("if (-not $Execute)")
    protected_snapshot = source.index("$protectedBefore = Get-ProtectedState", plan_gate)
    execution_try = source.index("try {", plan_gate)
    first_execution_write = source.index(
        "New-Item -ItemType Directory -Path $outputPath", execution_try
    )

    assert plan_gate < protected_snapshot < execution_try < first_execution_write
    assert "green-plan-only-preflight-passed-no-execute" in source
    assert "outputRootCreated = $false" in source
    assert "exit 0" in source[plan_gate:first_execution_write]
    for fragment in (
        'Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S")',
        'Invoke-ProcessOnce -Executable $installerPath -Arguments @("/S", "/UPDATE")',
        'Invoke-ProcessOnce -Executable $uninstaller -Arguments @("/S")',
        "Assert-AndRemoveOwnedProductPreferenceKey",
        "Assert-LabUninstalled",
        "Assert-ProtectedParity",
        "$counters.applicationCloses++",
        "$counters.protectedStateSnapshots++",
        "$counters.protectedStateParityChecks++",
        "segment-a-failed-no-retry",
        '"lab-e3b427e-segment-a-red3"',
        "$requestDiagnosticsClassifierSha256",
    ):
        assert fragment in source
    for forbidden in (
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "wsl.exe",
        "PX4",
        "Gazebo",
        "Start-Process -FilePath $env:ComSpec",
    ):
        assert forbidden not in source


def test_live_inspector_asserts_settings_lab_theme_3d_and_zero_provider() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    for fragment in (
        "chromium.connectOverCDP(endpoint)",
        "LAB_APP_SHELL_SELECTOR",
        'html[data-brand-edition="lab"] .app-shell',
        '[data-presentation-only="true"]',
        '[data-grants-hardware-authority="false"]',
        ".launcher-settings-panels",
        "singleScreenNoVerticalScroll",
        'const LAB_GRADIENT = ["#A7E84A", "#20C77A", "#087E69"]',
        '.drone-launch-scene[data-theme-edition="lab"]',
        "canvas.drone-launch-canvas",
        "PNG.sync.read(buffer)",
        "beforeSha256 === afterSha256",
        "presentationOnly",
        "grantsHardwareAuthority",
        "existingRuntimeReadOnly: true",
        "forbiddenProviderRequestCount: 0",
        "persistRequestDiagnostics",
        "requestDiagnosticsPath",
        "pageLocation: classifyRequest(page.url()",
        "providerTokenExchangeCount: 0",
        "browserLaunchCount: 0",
    ):
        assert fragment in source
    assert "chromium.launch" not in source
    assert "page.goto(" not in source
    assert "pageUrl: page.url()" not in source
    assert "observedRequests.push(rawUrl)" not in source
    assert ".click();" in source  # Settings and language only.
    assert "sign in" not in source.casefold()


def test_selector_fixture_accepts_lab_and_rejects_drift_without_browser() -> None:
    result = subprocess.run(
        ["node.exe", str(SELECTOR_FIXTURE)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["selector"] == 'html[data-brand-edition="lab"] .app-shell'
    assert payload["fixtureCount"] == 4
    assert payload["results"] == [
        {"id": "lab-root-and-shell", "expected": True, "accepted": True},
        {"id": "wrong-sim-edition", "expected": False, "accepted": False},
        {
            "id": "missing-edition-attribute",
            "expected": False,
            "accepted": False,
        },
        {"id": "missing-app-shell", "expected": False, "accepted": False},
    ]


def test_request_diagnostics_fixture_classifies_and_redacts_without_browser() -> None:
    result = subprocess.run(
        ["node.exe", str(REQUEST_FIXTURE)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["fixtureCount"] == 9
    assert payload["allowedCount"] == 5
    assert payload["deniedCount"] == 4
    assert payload["authSensitiveCount"] == 2
    assert payload["redactionPassed"] is True
    decisions = {item["id"]: item for item in payload["results"]}
    assert decisions["tauri-app-asset"]["decision"] == "allow"
    assert decisions["tauri-ipc-http-origin"]["hostClass"] == "tauri-ipc-origin"
    assert decisions["exact-execution-cdp"]["hostClass"] == "execution-owned-cdp"
    assert decisions["external-supabase"]["decision"] == "deny"
    assert decisions["external-model-api"]["decision"] == "deny"
    assert decisions["unknown-scheme"]["decision"] == "deny"


def test_request_origin_source_audit_keeps_external_origins_fail_closed() -> None:
    audit = _load(SOURCE_AUDIT)
    origins = {item["id"]: item for item in audit["origins"]}

    assert audit["artifactProductSourceCommit"] == (
        "e3b427e9d1d6209495d629c399a1962913f2d00c"
    )
    assert origins["tauri-ipc"]["expectedDuringSegmentA"] is True
    assert origins["updater-external-endpoint"]["segmentADecision"] == (
        "deny-and-persist-redacted-classification"
    )
    assert origins["desktop-auth-provider"]["expectedDuringSegmentA"] is False
    assert origins["settings-cloud-model"]["segmentADecision"] == "deny"
    assert origins["settings-local-backend"]["originClass"] == "local-loopback"
    assert audit["conclusion"]["externalOriginAllowlistForSegmentA"] == []
    assert audit["conclusion"]["unknownOrExternalRequestDecision"] == "fail-closed"
    assert audit["conclusion"]["productNetworkSemanticsChangedByAudit"] is False


def test_zero_pack_deny_and_protected_parity_are_explicit() -> None:
    application = _load(APPLICATION)
    safety = application["safety"]
    protected = application["protectedState"]

    assert safety == {
        "validatedVehiclePackCount": 0,
        "hardwareWriteArmHitlFlightDecision": "deny",
        "requiredAuthorityLayers": ["native", "backend", "runtime"],
        "frontendSettingsThemeOrWorkspaceCountsAsAuthority": False,
        "browserOauthProviderRuntimePx4GazeboHardwareAllowed": False,
    }
    assert protected["snapshotCount"] == 5
    assert protected["parityCheckCount"] == 4
    assert protected["otherEditionOrRuntimeMutationAllowed"] is False
    assert protected["webView2InstallRepairOrUpdateAllowed"] is False
    assert any("SIM" in scope for scope in protected["protectedScopes"])
    assert any("FIELD" in scope for scope in protected["protectedScopes"])
    assert any("Universal" in scope for scope in protected["protectedScopes"])
    assert any("Runtime" in scope for scope in protected["protectedScopes"])


def test_adapter_and_inspector_parse_without_execution() -> None:
    adapter = str(ADAPTER).replace("'", "''")
    parse_script = (
        "$tokens=$null;$errors=$null;"
        f"[Management.Automation.Language.Parser]::ParseFile('{adapter}',"
        "[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count){$errors|ForEach-Object{$_.ToString()};exit 1}"
    )
    ps_result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            parse_script,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert ps_result.returncode == 0, ps_result.stderr

    node_result = subprocess.run(
        ["node.exe", "--check", str(INSPECTOR)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert node_result.returncode == 0, node_result.stderr


def test_first_red_attempt_is_frozen_failed_without_retry_and_rolled_back() -> None:
    receipt = _load(FAILURE_RECEIPT)

    assert receipt["result"] == "segment-a-failed-no-retry"
    assert receipt["sourceSeparation"]["artifactProductSourceCommit"] == (
        "e3b427e9d1d6209495d629c399a1962913f2d00c"
    )
    assert receipt["sourceSeparation"]["executionEvidenceCommit"] == (
        "ebb9f5861eb84c2c590f4ea4eab7a1a17f56fcad"
    )
    assert receipt["sourceSeparation"]["artifactInvalidatedByThisFailure"] is False
    assert receipt["failure"]["classification"] == (
        "execution-adapter-selector-mismatch"
    )
    assert receipt["failure"]["productSourceFacts"] == {
        "launcherShellSelector": ".app-shell.app-shell-launcher",
        "launcherShellHasDataBrandEditionAttribute": False,
        "editionAttributeOwner": "document.documentElement",
        "editionAttributeWriter": (
            "applyUniversalMode through EditionThemeProvider"
        ),
    }
    assert receipt["failure"]["productRuntimeFailureProven"] is False
    assert receipt["actualCounts"]["freshInstallerInvocations"] == 1
    assert receipt["actualCounts"]["overlayInstallerInvocations"] == 0
    assert receipt["actualCounts"]["applicationLaunches"] == 1
    assert receipt["actualCounts"]["uninstallerInvocations"] == 1
    assert receipt["actualCounts"]["browserLaunches"] == 0
    assert receipt["actualCounts"]["runtimeStartsOrMigrations"] == 0
    assert receipt["actualCounts"]["hardwareActions"] == 0
    assert receipt["rollback"]["protectedStateByteEquivalent"] is True
    assert receipt["rollback"]["labInstallRootAbsent"] is True
    assert receipt["rollback"]["labProductKeyAbsent"] is True
    assert receipt["rollback"]["droneDreamProcessCount"] == 0
    assert receipt["rollback"]["oauthPort49212ListenerCount"] == 0
    assert receipt["retry"] == {
        "performed": False,
        "authorized": False,
        "sameCommandMayBeRunAgain": False,
        "requiresPatchedAdapterNewApplicationAndNewExactRedSignal": True,
    }
    assert receipt["releaseReady"] is False
    assert receipt["websiteHandoffReady"] is False


def test_second_red_attempt_is_frozen_at_provider_boundary_and_rolled_back() -> None:
    receipt = _load(SECOND_FAILURE_RECEIPT)

    assert receipt["attemptId"] == "lab-e3b427e-segment-a-red2"
    assert receipt["attemptOrdinal"] == 2
    assert receipt["result"] == "segment-a-failed-no-retry"
    assert receipt["sourceSeparation"] == {
        "artifactProductSourceCommit": (
            "e3b427e9d1d6209495d629c399a1962913f2d00c"
        ),
        "executionEvidenceCommit": "88eeeeedbe31baae6c590992390056363fc262d0",
        "executionEvidenceIsArtifactSource": False,
        "artifactInvalidatedByThisFailure": False,
    }
    assert receipt["authorization"]["commandContractSha256"] == (
        "05d9ba741720f765bccaf53d9432270ebf09aee12fc57be3b89cbed5697bafe2"
    )
    assert receipt["failure"]["classification"] == (
        "forbidden-non-local-request-unidentified"
    )
    assert receipt["failure"]["observedRequestUrlPersisted"] is False
    assert receipt["failure"]["productOrInspectorDefectProven"] is False
    assert receipt["failure"][
        "settingsThemeThreeDAndAuthorityControlFlowPassedBeforeNetworkBoundary"
    ] is True
    assert receipt["failure"]["successfulLiveAssertionReceiptWritten"] is False
    assert receipt["actualCounts"]["freshInstallerInvocations"] == 1
    assert receipt["actualCounts"]["overlayInstallerInvocations"] == 0
    assert receipt["actualCounts"]["applicationLaunches"] == 1
    assert receipt["actualCounts"]["applicationCloses"] == 1
    assert receipt["actualCounts"]["uninstallerInvocations"] == 1
    assert receipt["actualCounts"]["ownedPreferenceKeyCleanupInvocations"] == 1
    assert receipt["actualCounts"]["browserLaunches"] == 0
    assert receipt["actualCounts"]["providerTokenExchanges"] == 0
    assert receipt["actualCounts"]["runtimeStartsOrMigrations"] == 0
    assert receipt["actualCounts"]["hardwareActions"] == 0
    assert receipt["rollback"]["protectedStateByteEquivalent"] is True
    assert receipt["rollback"]["labInstallRootAbsent"] is True
    assert receipt["rollback"]["labProductKeyAbsent"] is True
    assert receipt["rollback"]["droneDreamProcessCount"] == 0
    assert receipt["rollback"]["oauthPort49212ListenerCount"] == 0
    assert receipt["retry"] == {
        "performed": False,
        "authorized": False,
        "sameCommandMayBeRunAgain": False,
        "requiresOfflineDiagnosticPatchNewApplicationAndNewExactRedSignal": True,
    }
    assert receipt["releaseReady"] is False
    assert receipt["websiteHandoffReady"] is False


def test_third_red_attempt_is_frozen_passed_redacted_and_rolled_back() -> None:
    receipt = _load(SUCCESS_RECEIPT)

    assert receipt["attemptId"] == "lab-e3b427e-segment-a-red3"
    assert receipt["attemptOrdinal"] == 3
    assert receipt["result"] == "segment-a-app-only-passed"
    assert receipt["sourceSeparation"] == {
        "artifactProductSourceCommit": (
            "e3b427e9d1d6209495d629c399a1962913f2d00c"
        ),
        "executionEvidenceCommit": "aba53aa4470073bf1cc807e9e5b806a061c0d632",
        "executionEvidenceIsArtifactSource": False,
        "artifactInvalidatedByThisExecution": False,
    }
    assert receipt["artifact"]["bytes"] == 12081900
    assert receipt["artifact"]["sha256BeforeAndAfter"] == (
        "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
    )
    assert receipt["artifact"]["authenticodeStatus"] == "NotSigned"
    assert receipt["artifact"]["rebuiltRelabeledOverwrittenOrDeleted"] is False
    assert receipt["authorization"] == {
        "segment": "A",
        "maximumInvocations": 1,
        "actualInvocations": 1,
        "automaticRetryMaximum": 0,
        "automaticRetryActual": 0,
        "commandContractSha256": (
            "0b26fae910a07c22e85c85888d3764cb47d2ab2e7daff80e3e0f6c222a3d011c"
        ),
        "applicationSha256": (
            "544afe7c5b51999d8a473e5643db5d671aacc4c8cd85d163d534c0b15b67c7fb"
        ),
        "planSha256": (
            "e9b1f1a12d5ebb5fe311d9a88c34fc093da09bd72bd73c3c1aee167a9f1233c5"
        ),
        "targetReceiptSha256": (
            "c16327e43f45c5b9e0b0dd89ebc224ccdfe0241bad23d36f9623527060f8339c"
        ),
    }

    counts = receipt["exactCounts"]
    assert counts == _load(APPLICATION)["segments"]["a"]["exactCounts"]
    assert counts == _load(PLAN)["exactCounts"]
    assert counts == _load(TARGET)["requiredExactCounts"]
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

    for phase in ("freshLiveWebView2", "overlayLiveWebView2"):
        stage = receipt["stageResults"][phase]
        assert stage["passed"] is True
        assert stage["settingsSingleScreenNoVerticalScroll"] is True
        assert stage["labThemeTokens"] == ["#A7E84A", "#20C77A", "#087E69"]
        assert stage["labThemeAndThreeDResponsive"] is True
        assert stage["presentationOnly"] is True
        assert stage["grantsHardwareAuthority"] is False
        assert stage["forbiddenAuthRequestCount"] == 0
        assert stage["forbiddenProviderRequestCount"] == 0

    diagnostics = receipt["requestDiagnostics"]
    assert diagnostics["redactionContract"][
        "rawUrlHostPathQueryHeadersCookieTokenApiKeyOrEmailPersisted"
    ] is False
    assert diagnostics["redactionContract"]["forbiddenPersistedKeyHits"] == []
    assert diagnostics["fresh"]["deniedCount"] == 0
    assert diagnostics["fresh"]["authSensitiveCount"] == 0
    assert diagnostics["overlay"]["deniedCount"] == 0
    assert diagnostics["overlay"]["authSensitiveCount"] == 0
    assert set(diagnostics["fresh"]["hostClasses"]) == {
        "tauri-app-origin",
        "tauri-ipc-origin",
    }
    assert set(diagnostics["overlay"]["hostClasses"]) == {
        "tauri-app-origin",
        "tauri-ipc-origin",
    }

    assert receipt["protectedState"][
        "baseUniversalSimFieldRuntimeAndWebView2Parity"
    ] is True
    assert receipt["protectedState"]["touched"] is False
    assert all(
        receipt["finalState"][key]
        for key in (
            "installRootAbsent",
            "roamingAppDataAbsent",
            "localAppDataAbsent",
            "uninstallKeyAbsent",
            "productKeyAbsent",
            "desktopShortcutAbsent",
            "startMenuShortcutAbsent",
            "protectedStateByteEquivalent",
        )
    )
    assert receipt["finalState"]["droneDreamProcessCount"] == 0
    assert receipt["finalState"]["oauthPort49212ListenerCount"] == 0
    assert receipt["oauthSegmentB"]["state"] == "fail-closed-not-executed"
    assert receipt["oauthSegmentB"]["providerCalled"] is False
    assert receipt["retry"]["sameCommandMayBeRunAgain"] is False
    assert receipt["acceptance"]["segmentAReady"] is True
    assert receipt["releaseReady"] is False
    assert receipt["websiteHandoffReady"] is False
