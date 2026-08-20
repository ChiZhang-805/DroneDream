from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("distribution/desktop/edition-browser-auth.v1.json")
EDITION_IDS = ("universal", "sim", "lab", "field", "autonomy")


class DesktopEditionBrowserAuthError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise DesktopEditionBrowserAuthError(f"{label} fields drifted")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DesktopEditionBrowserAuthError(f"{label} is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopEditionBrowserAuthError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise DesktopEditionBrowserAuthError(f"{label} must be an object")
    return value


def validate_contract(document: Any, *, root: Path) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DesktopEditionBrowserAuthError("browser auth contract must be an object")
    _require_exact_keys(
        document,
        {
            "schemaVersion", "kind", "contractVersion", "identityBinding",
            "accountAuthority", "authorizationProtocol", "credentialStorage",
            "logoutSemantics", "auditReceipt", "editions", "releaseGate",
        },
        "browser auth contract",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-desktop-edition-browser-auth"
        or document["contractVersion"] != "1.0.0"
    ):
        raise DesktopEditionBrowserAuthError("browser auth contract identity is unsupported")

    binding = document["identityBinding"]
    _require_exact_keys(binding, {"contractPath", "contractSha256"}, "identity binding")
    if binding["contractPath"] != "distribution/desktop/edition-coexistence.v1.json":
        raise DesktopEditionBrowserAuthError("identity contract path drifted")
    identity_path = root / binding["contractPath"]
    if sha256_file(identity_path) != binding["contractSha256"]:
        raise DesktopEditionBrowserAuthError("identity contract hash drifted")
    identity = _load_json(identity_path, "desktop coexistence contract")

    expected_account = {
        "provider": "supabase",
        "projectUrl": "https://yggabfynndpzymlqvnim.supabase.co",
        "sharedAccountSubject": True,
        "sharedCloudAuthorization": True,
        "explicitPerEditionAuthorizationRequired": True,
        "browserSessionMayReduceCredentialEntry": True,
        "automaticCrossEditionAuthentication": False,
        "desktopTokenImport": False,
    }
    if document["accountAuthority"] != expected_account:
        raise DesktopEditionBrowserAuthError("account and per-edition session policy drifted")

    protocol = document["authorizationProtocol"]
    if (
        protocol.get("protocolVersion") != "desktop-browser-auth-pkce-v1"
        or protocol.get("flow") != "hosted-authorization-code-pkce"
        or protocol.get("pkceMethod") != "S256"
        or protocol.get("nativeVerifierBytes") != 32
        or protocol.get("stateBytes") != 32
        or protocol.get("nonceBytes") != 32
        or protocol.get("attemptIdBytes") != 16
        or protocol.get("transactionTtlSeconds") != 600
        or protocol.get("providerRetryCount") != 0
        or protocol.get("callbackTransport") != "loopback-http"
        or protocol.get("loopbackHost") != "127.0.0.1"
        or protocol.get("callbackPathTemplate") != "/desktop-auth/{editionId}/callback"
    ):
        raise DesktopEditionBrowserAuthError("authorization protocol identity drifted")
    if protocol.get("authorizationEndpoint") != (
        "https://yggabfynndpzymlqvnim.supabase.co/auth/v1/oauth/authorize"
    ) or protocol.get("tokenExchangeEndpoint") != (
        "https://yggabfynndpzymlqvnim.supabase.co/auth/v1/oauth/token"
    ) or protocol.get("authorizationUiEndpoint") != (
        "https://getdronedream.com/oauth/consent"
    ):
        raise DesktopEditionBrowserAuthError("hosted authorization broker drifted")
    required_true = {
        "singleActiveAttemptPerEdition", "oneTimeCallback", "oneTimeCodeExchange",
        "fixedRegisteredLoopbackPortRequired", "strictHostAndOriginRequired",
        "browserConfirmationRequired", "uninitiatedCallbackDenied",
        "crossEditionCallbackDenied", "crossPortCallbackDenied", "expiredCallbackDenied",
        "replayedCallbackDenied",
    }
    if any(protocol.get(field) is not True for field in required_true):
        raise DesktopEditionBrowserAuthError("browser transaction fail-closed policy drifted")
    if protocol.get("directPasswordPageAllowed") is not False or protocol.get(
        "rawTokenLoopbackAllowed"
    ) is not False:
        raise DesktopEditionBrowserAuthError("legacy raw-token browser flow cannot be released")
    if protocol.get("callbackFields") != ["code", "state"]:
        raise DesktopEditionBrowserAuthError("callback field allowlist drifted")
    if protocol.get("nativeBoundContext") != [
        "editionId", "authClientId", "attemptId", "callbackPort", "codeVerifier", "nonce"
    ]:
        raise DesktopEditionBrowserAuthError("native transaction binding drifted")
    if protocol.get("callbackMustNotContain") != [
        "accessToken", "refreshToken", "password", "cookie"
    ]:
        raise DesktopEditionBrowserAuthError("callback secret denylist drifted")

    storage = document["credentialStorage"]
    if storage != {
        "refreshTokenPersistence": "windows-credential-manager",
        "accessTokenPersistence": "edition-webview-session-cache",
        "plainTextPasswordPersistence": False,
        "plainTextTokenFileAllowed": False,
        "crossEditionDiscoveryAllowed": False,
        "crossEditionImportAllowed": False,
        "vaultEntryKeyTemplate": "{credentialVaultNamespace}/{accountSubjectHash}",
        "webViewStorageMustMatchBundleIdentifier": True,
    }:
        raise DesktopEditionBrowserAuthError("edition credential storage policy drifted")

    if document["logoutSemantics"] != {
        "localEditionLogout": (
            "revoke-current-edition-session-and-clear-current-edition-vault-only"
        ),
        "globalLogout": "explicit-server-side-revoke-all-sessions",
        "localLogoutMustNotClearOtherEditions": True,
        "globalLogoutRequiresSeparateConfirmation": True,
    }:
        raise DesktopEditionBrowserAuthError("logout scope policy drifted")

    editions = document["editions"]
    identity_editions = identity.get("editions")
    if not isinstance(editions, list) or not isinstance(identity_editions, list):
        raise DesktopEditionBrowserAuthError("edition identities are invalid")
    if [entry.get("editionId") for entry in editions] != list(EDITION_IDS):
        raise DesktopEditionBrowserAuthError("browser auth editions must be canonical and ordered")
    identity_by_id = {entry["editionId"]: entry for entry in identity_editions}
    edition_keys = {
        "editionId", "authClientId", "providerClientIdBuildVariable", "bundleIdentifier",
        "loopbackPathPrefix", "loopbackPort", "redirectUri", "customProtocol",
        "credentialVaultNamespace", "webViewDataNamespace",
    }
    for edition in editions:
        edition_id = edition["editionId"]
        _require_exact_keys(edition, edition_keys, f"browser auth edition {edition_id}")
        identity_edition = identity_by_id.get(edition_id)
        if not isinstance(identity_edition, dict):
            raise DesktopEditionBrowserAuthError(f"identity edition {edition_id} is unavailable")
        for field in edition_keys - {
            "editionId", "providerClientIdBuildVariable", "loopbackPort", "redirectUri"
        }:
            if edition[field] != identity_edition.get(field):
                raise DesktopEditionBrowserAuthError(
                    f"browser auth edition {edition_id} {field} drifted"
                )
        if edition["providerClientIdBuildVariable"] != "DRONEDREAM_OAUTH_CLIENT_ID":
            raise DesktopEditionBrowserAuthError(
                f"browser auth edition {edition_id} provider client source drifted"
            )
        expected_port = 49210 + EDITION_IDS.index(edition_id)
        expected_redirect = (
            f"http://127.0.0.1:{expected_port}/desktop-auth/{edition_id}/callback"
        )
        if edition["loopbackPort"] != expected_port or edition["redirectUri"] != expected_redirect:
            raise DesktopEditionBrowserAuthError(
                f"browser auth edition {edition_id} registered redirect drifted"
            )
    for field in edition_keys - {"editionId", "providerClientIdBuildVariable"}:
        values = [edition[field] for edition in editions]
        if len(values) != len(set(values)):
            raise DesktopEditionBrowserAuthError(f"browser auth edition {field} values collide")

    receipt = document["auditReceipt"]
    forbidden = {
        "accessToken",
        "refreshToken",
        "password",
        "cookie",
        "rawCallback",
        "providerRequestId",
    }
    allowed = set(receipt.get("allowedFields", []))
    if (
        receipt.get("kind") != "dronedream-desktop-browser-auth-attempt"
        or receipt.get("receiptVersion") != 1
        or set(receipt.get("forbiddenFields", [])) != forbidden
        or allowed & forbidden
        or not {"editionId", "attemptIdHash", "stateHash", "subjectHash", "result"} <= allowed
    ):
        raise DesktopEditionBrowserAuthError("auth audit receipt policy drifted")

    gate = document["releaseGate"]
    if gate != {
        "nativeProtocolEnforcementReceiptRequired": True,
        "hostedBrokerReceiptRequired": True,
        "credentialVaultReceiptRequired": True,
        "fiveEditionConcurrencyReceiptRequired": True,
        "cancelTimeoutOfflineSwitchAccountReceiptRequired": True,
        "releaseMayUseLegacyDirectTokenLoopback": False,
    }:
        raise DesktopEditionBrowserAuthError("browser auth release gate drifted")
    return document


def load_contract(root: Path) -> dict[str, Any]:
    return validate_contract(_load_json(root / CONTRACT_PATH, "browser auth contract"), root=root)
