from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution/tools/desktop_edition_coexistence.py"
CONTRACT_PATH = ROOT / "distribution/desktop/edition-coexistence.v1.json"
SCHEMA_PATH = ROOT / "distribution/schemas/desktop-edition-coexistence.schema.json"
UNIVERSAL_OVERLAY = ROOT / "desktop/src-tauri/tauri.universal.conf.json"

SPEC = importlib.util.spec_from_file_location("desktop_edition_coexistence", TOOL_PATH)
assert SPEC and SPEC.loader
contract_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract_tool
SPEC.loader.exec_module(contract_tool)


def _document() -> dict[str, object]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_schema_and_contract_are_closed_versioned_inputs() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schemaVersion"]["const"] == 1
    assert schema["properties"]["editions"]["minItems"] == 4
    for name in ("accountAuthority", "sharedResources", "legacyDesktop"):
        nested = schema["properties"][name]
        assert nested["additionalProperties"] is False
        assert set(nested["required"]) == set(nested["properties"])
        assert set(_document()[name]) == set(nested["properties"])
    assert contract_tool.load_contract(ROOT)["contractVersion"] == "1.0.0"


def test_edition_separator_is_the_canonical_middle_dot_codepoint() -> None:
    document = contract_tool.load_contract(ROOT)
    for edition in document["editions"][1:]:
        assert edition["displayName"].split()[1] == "\u00b7"
        assert edition["desktopShortcutName"].split()[1] == "\u00b7"


def test_all_desktop_identities_channels_auth_and_icons_are_unique() -> None:
    document = contract_tool.load_contract(ROOT)
    editions = document["editions"]
    for field in (
        "artifactFileName",
        "installerProductName",
        "bundleIdentifier",
        "installRoot",
        "uninstallRegistryKey",
        "productRegistryKey",
        "desktopShortcutName",
        "appUserModelId",
        "updaterMetadataFileName",
        "authClientId",
        "loopbackPathPrefix",
        "customProtocol",
        "credentialVaultNamespace",
        "webViewDataNamespace",
    ):
        values = [edition[field] for edition in editions]
        assert len(values) == len(set(values)), field


def test_shared_account_does_not_imply_shared_desktop_session_or_runtime_ownership() -> None:
    document = contract_tool.load_contract(ROOT)
    assert document["accountAuthority"] == {
        "provider": "supabase",
        "projectUrl": "https://yggabfynndpzymlqvnim.supabase.co",
        "sharedAccountSubject": True,
        "sharedCloudDataAuthorization": True,
        "desktopSessionSharing": False,
        "desktopTokenImport": False,
    }
    assert document["sharedResources"]["runtimeRemovedByEditionUninstall"] is False
    assert document["sharedResources"]["runtimeOwner"] == "runtime-base-manager"


def test_legacy_collision_requires_explicit_migration_and_never_silent_overwrite() -> None:
    document = contract_tool.load_contract(ROOT)
    legacy = document["legacyDesktop"]
    assert legacy["silentOverwriteAllowed"] is False
    assert legacy["migrationRequiresOperatorConfirmation"] is True
    assert legacy["migrationMustPreserveRuntimeAndUserData"] is True
    assert legacy["unresolvedShortcutConflictBlocksShortcutCreation"] is True


@pytest.mark.parametrize(
    "field",
    [
        "installRoot",
        "uninstallRegistryKey",
        "desktopShortcutName",
        "appUserModelId",
        "updaterMetadataFileName",
        "credentialVaultNamespace",
    ],
)
def test_collision_in_any_windows_or_session_identity_fails_closed(field: str) -> None:
    document = _document()
    document["editions"][1][field] = document["editions"][0][field]
    with pytest.raises(contract_tool.DesktopEditionCoexistenceError, match="collide"):
        contract_tool.validate_contract(document, root=ROOT)


def test_wrong_brand_byte_or_unapproved_display_name_fails_closed() -> None:
    document = _document()
    document["editions"][2]["displayName"] = "DroneDream LAB"
    with pytest.raises(contract_tool.DesktopEditionCoexistenceError, match="displayName drifted"):
        contract_tool.validate_contract(document, root=ROOT)
    document = _document()
    document["editions"][2]["canonicalWindowsIcon"] = (
        "brand/generated/universal/windows/icon.ico"
    )
    with pytest.raises(
        contract_tool.DesktopEditionCoexistenceError,
        match="canonicalWindowsIcon drifted",
    ):
        contract_tool.validate_contract(document, root=ROOT)


def test_universal_overlay_matches_its_namespaced_install_identity() -> None:
    document = contract_tool.load_contract(ROOT)
    universal = document["editions"][0]
    overlay = json.loads(UNIVERSAL_OVERLAY.read_text(encoding="utf-8"))
    assert overlay["productName"] == universal["installerProductName"]
    assert overlay["identifier"] == universal["bundleIdentifier"]
    assert overlay["app"]["windows"][0]["title"] == universal["displayName"]
    assert universal["artifactFileName"] == "DroneDream-Universal-1.0.0.exe"
    overlay_icons = {
        (UNIVERSAL_OVERLAY.parent / path).resolve().relative_to(ROOT).as_posix()
        for path in overlay["bundle"]["icon"]
    }
    assert universal["canonicalWindowsIcon"] in overlay_icons


def test_state_machine_requires_all_four_upgrade_uninstall_and_legacy_states() -> None:
    document = contract_tool.load_contract(ROOT)
    assert document["stateMachineVerification"] == {
        "installOrderCoverage": "pairwise-plus-all-four",
        "requiredStates": [
            "all-four-installed",
            "each-edition-upgraded-in-place",
            "each-edition-uninstalled-alone",
            "remaining-three-still-launchable",
            "legacy-detected-without-overwrite",
        ],
        "releaseRequiresExecutedReceipt": True,
    }
    invalid = deepcopy(document)
    invalid["stateMachineVerification"]["requiredStates"].pop()
    with pytest.raises(contract_tool.DesktopEditionCoexistenceError, match="state-machine"):
        contract_tool.validate_contract(invalid, root=ROOT)
