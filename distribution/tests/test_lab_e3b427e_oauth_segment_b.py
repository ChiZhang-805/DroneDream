import copy
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / "distribution/editions/lab/lifecycle"
SOURCE_AUDIT = LIFECYCLE / "oauth-segment-b-source-audit.v1.json"
PLAN = LIFECYCLE / "red-e3b427e-oauth-segment-b-plan.v1.json"
APPLICATION = LIFECYCLE / "red-e3b427e-oauth-segment-b-application.v1.json"
COMMAND = LIFECYCLE / "red-e3b427e-oauth-segment-b-command.v1.json"
ADAPTER = LIFECYCLE / "run-lab-e3b427e-oauth-segment-b.ps1"
INSPECTOR = LIFECYCLE / "inspect-lab-e3b427e-oauth-segment-b.mjs"
AUTH_CONTRACT = ROOT / "distribution/desktop/edition-browser-auth.v1.json"
A3_RECEIPT = ROOT / "distribution/build-receipts/lab-e3b427e-red-segment-a3-success.json"
PREPARATION_RECEIPT = (
    ROOT
    / "distribution/build-receipts/"
    "lab-e3b427e-oauth-segment-b-green-preparation.json"
)

PRODUCT_SOURCE = "e3b427e9d1d6209495d629c399a1962913f2d00c"
ARTIFACT_SHA = "e0776b09a46b4e4223ec2bbecad89a48951d7a72edb918193d09e59d7dbe80e4"
CLIENT_ID = "0b9e7a8d-2c90-4b76-8842-511363f555bd"
CALLBACK = "http://127.0.0.1:49212/desktop-auth/lab/callback"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(_lf_bytes(path)).hexdigest()


def test_application_binds_exact_product_artifact_a3_and_public_registration() -> None:
    application = _load(APPLICATION)

    assert application["productSourceCommit"] == PRODUCT_SOURCE
    assert application["artifact"]["sha256"] == ARTIFACT_SHA
    assert application["artifact"]["bytes"] == 12081900
    assert application["artifact"]["authenticodeStatus"] == "NotSigned"
    assert application["segmentA"]["mayBeReplayed"] is False
    assert application["segmentA"]["successReceiptSha256"] == _sha256(A3_RECEIPT)
    assert application["publicOAuth"] == {
        "clientId": CLIENT_ID,
        "clientIdSha256": hashlib.sha256(CLIENT_ID.encode()).hexdigest(),
        "clientType": "public",
        "tokenEndpointAuthMethod": "none",
        "clientSecretAllowed": False,
        "redirectUri": CALLBACK,
        "redirectUriSha256": hashlib.sha256(CALLBACK.encode()).hexdigest(),
        "authorizationUiEndpoint": "https://getdronedream.com/oauth/consent",
    }


def test_application_binds_plan_source_audit_and_tools_by_exact_hash() -> None:
    application = _load(APPLICATION)

    assert application["contracts"]["sourceAudit"] == {
        "path": "distribution/editions/lab/lifecycle/oauth-segment-b-source-audit.v1.json",
        "bytes": SOURCE_AUDIT.stat().st_size,
        "sha256": _sha256(SOURCE_AUDIT),
    }
    assert application["contracts"]["plan"] == {
        "path": "distribution/editions/lab/lifecycle/red-e3b427e-oauth-segment-b-plan.v1.json",
        "bytes": PLAN.stat().st_size,
        "sha256": _sha256(PLAN),
    }
    for name, path in (("adapter", ADAPTER), ("webViewInspector", INSPECTOR)):
        assert application["tools"][name]["lfNormalizedBytes"] == len(_lf_bytes(path))
        assert application["tools"][name]["lfNormalizedSha256"] == _lf_sha256(path)


def test_runtime_prerequisite_is_explicitly_split_from_oauth_transaction() -> None:
    audit = _load(SOURCE_AUDIT)
    plan = _load(PLAN)
    application = _load(APPLICATION)

    assert audit["runtimePrerequisite"] == {
        "exists": True,
        "sourcePath": "frontend/src/pages/DesktopSetup.tsx",
        "loginGestureRequires": [
            "localRuntimeReady",
            "fresh prerequisite and Runtime probes",
            "desktop Runtime access status ready",
            "browser auth status idle",
        ],
        "nativeOAuthDependsOnRuntimeApi": False,
        "nativeOwner": "Tauri browser_auth command and fixed loopback listener",
        "decision": "split runtime-readiness-only B0 from OAuth transaction B1",
    }
    assert application["runtimeSplit"]["sameRedAuthorizationMayCoverBoth"] is False
    assert plan["authorizationModel"]["b0AndB1RequireSeparateExactRedSignals"] is True
    assert plan["authorizationModel"]["b0SuccessDoesNotAuthorizeB1"] is True
    assert plan["b0RuntimePrerequisite"]["exactCounts"]["runtimeStartsOrMigrations"] == 0
    assert plan["b0RuntimePrerequisite"]["exactCounts"]["browserLaunches"] == 0
    assert plan["b0RuntimePrerequisite"]["exactCounts"]["oauthTransactions"] == 0
    assert plan["b1OAuthTransaction"]["exactCounts"]["browserLaunches"] == 1
    assert plan["b1OAuthTransaction"]["exactCounts"]["oauthTransactions"] == 1


def test_source_audit_matches_current_software_bytes_and_auth_contract() -> None:
    audit = _load(SOURCE_AUDIT)
    contract = _load(AUTH_CONTRACT)
    lab = next(item for item in contract["editions"] if item["editionId"] == "lab")

    assert lab["loopbackPort"] == 49212
    assert lab["redirectUri"] == CALLBACK
    assert lab["credentialVaultNamespace"] == "DroneDream/Auth/lab/v1"
    assert contract["authorizationProtocol"]["pkceMethod"] == "S256"
    assert contract["authorizationProtocol"]["oneTimeCallback"] is True
    assert contract["authorizationProtocol"]["replayedCallbackDenied"] is True
    assert contract["authorizationProtocol"]["crossEditionCallbackDenied"] is True
    for source in audit["softwareSources"]:
        path = ROOT / source["path"]
        assert source["bytes"] == path.stat().st_size
        assert source["sha256"] == _sha256(path)
    assert audit["websiteCommittedSource"]["worktreeWasDirty"] is True
    assert audit["websiteCommittedSource"]["dirtyPathsWereOAuthRelated"] is False
    assert audit["websiteCommittedSource"]["liveEndpointOrProviderVerifiedByThisAudit"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["publicOAuth"].update(clientId="wrong"), "client"),
        (
            lambda value: value["publicOAuth"].update(
                redirectUri="http://127.0.0.1:49213/desktop-auth/field/callback"
            ),
            "redirect",
        ),
        (lambda value: value["protocol"].update(pkceMethod="plain"), "pkce"),
        (
            lambda value: value["protocol"].update(
                otherEditionSessionImportDecision="allow"
            ),
            "edition",
        ),
        (
            lambda value: value["runtimeSplit"].update(
                sameRedAuthorizationMayCoverBoth=True
            ),
            "split",
        ),
    ],
)
def test_high_risk_contract_drift_is_detectable(mutation, message: str) -> None:
    application = _load(APPLICATION)
    mutated = copy.deepcopy(application)
    mutation(mutated)

    valid = (
        mutated["publicOAuth"]["clientId"] == CLIENT_ID
        and mutated["publicOAuth"]["redirectUri"] == CALLBACK
        and mutated["protocol"]["pkceMethod"] == "S256"
        and mutated["protocol"]["otherEditionSessionImportDecision"] == "deny"
        and mutated["runtimeSplit"]["sameRedAuthorizationMayCoverBoth"] is False
    )
    assert not valid, f"{message} mutation did not fail closed"


def test_adapter_plan_only_precedes_all_execution_and_b1_requires_b0_hash() -> None:
    source = ADAPTER.read_text(encoding="utf-8-sig")
    plan_only = source.index("if (-not $Execute)")
    first_write = source.index("New-Item -ItemType Directory -Path $outputPath")

    assert plan_only < first_write
    assert "green-plan-only-preflight-passed-no-execute" in source[plan_only:first_write]
    assert "B1 requires an exact accepted B0 receipt path and SHA-256" in source
    assert 'if ($b0.result -cne "runtime-prerequisite-passed"' in source
    assert "Assert-PortFree" in source
    assert "Assert-ProtectedParity" in source
    assert "sameCommandMayBeRunAgain = $false" in source
    for forbidden in (
        "OPENAI_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "Get-Credential",
        "cmdkey /list",
        "wsl.exe",
        "PX4",
        "Gazebo",
    ):
        assert forbidden not in source


def test_inspector_never_observes_browser_network_or_persists_sensitive_values() -> None:
    source = INSPECTOR.read_text(encoding="utf-8")

    assert '"runtime-prerequisite"' in source
    assert '"oauth-transaction"' in source
    assert '"vault-cleanup"' in source
    assert 'button.launcher-primary-action' in source
    assert 'button.account-sign-out' in source
    assert 'invoke("clear_browser_auth_vault")' in source
    assert 'page.on("request"' not in source
    assert "context.cookies" not in source
    assert "passwordValue" not in source
    assert "accountIdentityPersisted: false" in source
    assert (
        "rawPasswordTokenCookieAuthorizationCodeVerifierStateNonceEmailOrCallbackPersisted: false"
        in source
    )


def test_command_freezes_exact_b0_and_fail_closed_b1_dependency() -> None:
    command = _load(COMMAND)

    assert command["application"]["bytes"] == APPLICATION.stat().st_size
    assert command["application"]["sha256"] == _sha256(APPLICATION)
    assert command["plan"]["sha256"] == _sha256(PLAN)
    assert command["tool"]["lfNormalizedSha256"] == _lf_sha256(ADAPTER)
    assert " -Execute" not in command["b0"]["planOnlyCommand"]
    assert command["b0"]["exactFutureRedCommand"].endswith(" -Execute")
    assert command["b0"]["executionAuthorizedNow"] is False
    assert command["b0"]["browserOauthProviderRuntimeMutationCounts"] == 0
    assert command["b1"]["runtimePrerequisiteReceiptSha256"] is None
    assert "<EXACT_B0_RECEIPT_SHA256>" in command["b1"]["deterministicCommandTemplate"]
    assert command["b1"]["exactFutureRedCommandFrozen"] is False
    assert command["b1"]["onlyUnresolvedField"] == "ExpectedRuntimePrerequisiteReceiptSha256"
    assert command["b1"]["executionAuthorizedNow"] is False


def test_zero_pack_hardware_authority_and_release_gates_remain_closed() -> None:
    application = _load(APPLICATION)
    plan = _load(PLAN)

    assert application["safety"] == {
        "validatedVehiclePackCount": 0,
        "hardwareWriteArmHitlFlightDecision": "deny",
        "requiredAuthorityLayers": ["native", "backend", "runtime"],
        "frontendThemeWorkspaceOrLoginCountsAsAuthority": False,
    }
    assert application["authorization"]["b0ExecutionAuthorized"] is False
    assert application["authorization"]["b1ExecutionAuthorized"] is False
    assert application["authorization"]["providerExecutionAuthorized"] is False
    assert application["releaseReady"] is False
    assert application["websiteHandoffReady"] is False
    assert plan["releaseReady"] is False
    assert plan["websiteHandoffReady"] is False


def test_green_preparation_receipt_binds_files_and_preserves_execution_boundary() -> None:
    receipt = _load(PREPARATION_RECEIPT)

    assert receipt["result"] == "offline-contract-and-b0-plan-only-passed-no-execute"
    for binding in receipt["boundFiles"]:
        path = ROOT / binding["path"]
        if binding.get("hashMode") == "lf-normalized":
            assert binding["bytes"] == len(_lf_bytes(path))
            assert binding["sha256"] == _lf_sha256(path)
        else:
            assert binding["bytes"] == path.stat().st_size
            assert binding["sha256"] == _sha256(path)
    assert receipt["greenPlanOnly"]["invocations"] == 1
    assert receipt["greenPlanOnly"]["ownedB0RootAbsentBeforeAndAfter"] is True
    assert receipt["greenPlanOnly"][
        "installerApplicationBrowserOauthProviderRuntimeInvocations"
    ] == 0
    assert receipt["commandReadiness"]["b0ExactFutureRedCommandFrozen"] is True
    assert receipt["commandReadiness"]["b0ExecutionAuthorized"] is False
    assert receipt["commandReadiness"]["b1ExactFutureRedCommandFrozen"] is False
    assert receipt["commandReadiness"]["b1OnlyUnresolvedField"] == (
        "ExpectedRuntimePrerequisiteReceiptSha256"
    )
    assert all(value == 0 for value in receipt["sideEffects"].values())
    assert receipt["releaseReady"] is False
    assert receipt["websiteHandoffReady"] is False
