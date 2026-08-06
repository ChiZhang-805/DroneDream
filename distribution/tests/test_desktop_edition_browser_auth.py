from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution/tools/desktop_edition_browser_auth.py"
CONTRACT_PATH = ROOT / "distribution/desktop/edition-browser-auth.v1.json"
SCHEMA_PATH = ROOT / "distribution/schemas/desktop-edition-browser-auth.schema.json"

SPEC = importlib.util.spec_from_file_location("desktop_edition_browser_auth", TOOL_PATH)
assert SPEC and SPEC.loader
contract_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract_tool
SPEC.loader.exec_module(contract_tool)


def _document() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_browser_auth_contract_and_schema_are_closed_versioned_inputs() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schemaVersion"]["const"] == 1
    assert schema["properties"]["editions"]["minItems"] == 4
    assert all(
        definition["additionalProperties"] is False
        for definition in schema["$defs"].values()
    )
    assert contract_tool.load_contract(ROOT)["contractVersion"] == "1.0.0"


def test_browser_auth_contract_is_exactly_bound_to_coexistence_identity_bytes() -> None:
    document = contract_tool.load_contract(ROOT)
    binding = document["identityBinding"]
    assert contract_tool.sha256_file(ROOT / binding["contractPath"]) == binding["contractSha256"]


def test_every_edition_requires_an_explicit_isolated_transaction() -> None:
    document = contract_tool.load_contract(ROOT)
    account = document["accountAuthority"]
    assert account["sharedAccountSubject"] is True
    assert account["browserSessionMayReduceCredentialEntry"] is True
    assert account["explicitPerEditionAuthorizationRequired"] is True
    assert account["automaticCrossEditionAuthentication"] is False
    assert account["desktopTokenImport"] is False
    for field in (
        "authClientId", "bundleIdentifier", "loopbackPathPrefix", "customProtocol",
        "credentialVaultNamespace", "webViewDataNamespace",
    ):
        values = [edition[field] for edition in document["editions"]]
        assert len(values) == len(set(values)), field


def test_authorization_callback_is_code_only_pkce_and_one_time() -> None:
    protocol = contract_tool.load_contract(ROOT)["authorizationProtocol"]
    assert protocol["flow"] == "hosted-authorization-code-pkce"
    assert protocol["pkceMethod"] == "S256"
    assert protocol["callbackFields"] == ["code", "state", "editionId", "attemptId"]
    assert protocol["callbackMustNotContain"] == [
        "accessToken", "refreshToken", "password", "cookie"
    ]
    assert protocol["oneTimeCallback"] is True
    assert protocol["oneTimeCodeExchange"] is True
    assert protocol["rawTokenLoopbackAllowed"] is False
    assert protocol["directPasswordPageAllowed"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["authorizationProtocol"].update(
                {"rawTokenLoopbackAllowed": True}
            ),
            "legacy raw-token",
        ),
        (
            lambda value: value["authorizationProtocol"].update(
                {"callbackPathTemplate": "/desktop-auth/callback"}
            ),
            "protocol identity",
        ),
        (
            lambda value: value["accountAuthority"].update(
                {"automaticCrossEditionAuthentication": True}
            ),
            "session policy",
        ),
        (
            lambda value: value["credentialStorage"].update(
                {"crossEditionDiscoveryAllowed": True}
            ),
            "credential storage",
        ),
        (
            lambda value: value["releaseGate"].update(
                {"hostedBrokerReceiptRequired": False}
            ),
            "release gate",
        ),
    ],
)
def test_security_or_release_gate_drift_fails_closed(mutation, message: str) -> None:
    document = _document()
    mutation(document)
    with pytest.raises(contract_tool.DesktopEditionBrowserAuthError, match=message):
        contract_tool.validate_contract(document, root=ROOT)


def test_cross_edition_client_callback_or_vault_collision_fails_closed() -> None:
    for field in ("authClientId", "loopbackPathPrefix", "credentialVaultNamespace"):
        document = _document()
        document["editions"][1][field] = document["editions"][0][field]
        with pytest.raises(contract_tool.DesktopEditionBrowserAuthError, match="drifted|collide"):
            contract_tool.validate_contract(document, root=ROOT)


def test_audit_receipt_cannot_allow_tokens_passwords_cookies_or_raw_callback() -> None:
    document = contract_tool.load_contract(ROOT)
    receipt = document["auditReceipt"]
    assert not set(receipt["allowedFields"]) & set(receipt["forbiddenFields"])
    invalid = deepcopy(document)
    invalid["auditReceipt"]["allowedFields"].append("refreshToken")
    with pytest.raises(contract_tool.DesktopEditionBrowserAuthError, match="audit receipt"):
        contract_tool.validate_contract(invalid, root=ROOT)


def test_local_logout_is_edition_scoped_and_global_logout_is_explicit() -> None:
    logout = contract_tool.load_contract(ROOT)["logoutSemantics"]
    assert logout["localLogoutMustNotClearOtherEditions"] is True
    assert logout["globalLogoutRequiresSeparateConfirmation"] is True
    assert "current-edition" in logout["localEditionLogout"]
    assert "revoke-all-sessions" in logout["globalLogout"]
