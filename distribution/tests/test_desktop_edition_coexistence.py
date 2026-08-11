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
NSIS_IDENTITY = ROOT / "desktop/src-tauri/nsis/edition-identity.nsh"
NSIS_TEMPLATE = ROOT / "desktop/src-tauri/nsis/installer.nsi"
NSIS_HOOK = ROOT / "desktop/src-tauri/nsis/webview2-health.nsh"
NSIS_COMPILE_CHECK = ROOT / "desktop/scripts/verify-edition-identity-nsis.ps1"

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


def test_nsis_maps_internal_product_identities_to_canonical_display_names() -> None:
    document = contract_tool.load_contract(ROOT)
    identity = NSIS_IDENTITY.read_text(encoding="utf-8")
    for edition in document["editions"]:
        assert f'!if "${{PRODUCTNAME}}" == "{edition["installerProductName"]}"' in identity or (
            edition["editionId"] != "universal"
            and f'!else if "${{PRODUCTNAME}}" == "{edition["installerProductName"]}"' in identity
        )
        assert f'!define DRONEDREAM_DISPLAYNAME "{edition["displayName"]}"' in identity
    assert '!error "Unknown DroneDream installer PRODUCTNAME:' in identity


def test_nsis_keeps_internal_ownership_but_uses_display_shortcuts() -> None:
    template = NSIS_TEMPLATE.read_text(encoding="utf-8")
    identity = NSIS_IDENTITY.read_text(encoding="utf-8")
    hook = NSIS_HOOK.read_text(encoding="utf-8")

    # Internal identity continues to own directories, registry and app data.
    uninstall_key = (
        '!define UNINSTKEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
        '\\${PRODUCTNAME}"'
    )
    assert uninstall_key in template
    assert 'StrCpy $INSTDIR "$LOCALAPPDATA\\${PRODUCTNAME}"' in template
    assert 'RmDir /r "$LOCALAPPDATA\\${BUNDLEID}"' in template
    assert 'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${DRONEDREAM_DISPLAYNAME}"' in template
    assert 'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayVersion" "${VERSION}"' in template
    assert r'WriteRegStr SHCTX "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""' in template
    assert 'WriteRegStr SHCTX "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"' in template

    # Shortcut conflicts are retained, reported and never blindly overwritten.
    assert 'IfFileExists "${SHORTCUT_PATH}" 0 ${LABEL_PREFIX}_create' in identity
    assert 'DetailPrint "$(DD_ShortcutConflict)"' in identity
    assert 'SetErrors' in identity
    assert 'DRONEDREAM_REMOVE_INTERNAL_SHORTCUT' in template
    assert 'IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\\${MAINBINARYNAME}.exe"' in identity

    edition_icon_shortcut = (
        'CreateShortcut "${SHORTCUT_PATH}" "$INSTDIR\\${MAINBINARYNAME}.exe" '
        '"" "$INSTDIR\\${MAINBINARYNAME}.exe" 0'
    )
    assert edition_icon_shortcut in identity
    assert edition_icon_shortcut in hook
    assert "CreateShortcut" not in "\n".join(
        line for line in identity.splitlines() if "DroneDream.ico" in line
    )
    assert "CreateShortcut" not in "\n".join(
        line for line in hook.splitlines() if "DroneDream.ico" in line
    )

    # Every outer expansion supplies a call-site prefix. Nested shortcut macros
    # derive a distinct suffix from that prefix instead of redeclaring the
    # outer completion label (the previous desktop macro emitted the same
    # dronedream_desktop_done label twice).
    assert '!macro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT LABEL_PREFIX' in identity
    assert '!macro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT LABEL_PREFIX' in identity
    assert '${LABEL_PREFIX}_shortcut' in identity
    assert 'dronedream_desktop_done:' not in identity
    assert 'dronedream_startmenu_done:' not in identity
    assert (
        '!insertmacro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT '
        'dronedream_startmenu_entry'
    ) in template
    assert (
        '!insertmacro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT '
        'dronedream_desktop_entry'
    ) in template

    # A prior internal-name shortcut may move only after target ownership proof.
    ownership_check = hook.index(
        'IsShortcutTarget "${INTERNAL_PATH}" "$INSTDIR\\${MAINBINARYNAME}.exe"'
    )
    rename = hook.index('Rename "${INTERNAL_PATH}" "${DISPLAY_PATH}"')
    assert ownership_check < rename


def test_nsis_compile_check_covers_registration_repeated_expansion_and_unknown_editions() -> None:
    script = NSIS_COMPILE_CHECK.read_text(encoding="utf-8")
    for edition_id, product_name, display_name in (
        ("universal", "DroneDream-Universal", "DroneDream"),
        ("sim", "DroneDream-Sim", "DroneDream · SIM"),
        ("lab", "DroneDream-Lab", "DroneDream · LAB"),
        ("field", "DroneDream-Field", "DroneDream · FIELD"),
    ):
        invocation = (
            f'-EditionId "{edition_id}" -ProductName "{product_name}" '
            f'-DisplayName "{display_name}"'
        )
        assert invocation in script
    uninstall_key = (
        '!define UNINSTKEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
        '\\${PRODUCTNAME}"'
    )
    assert uninstall_key in script
    assert 'WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${DRONEDREAM_DISPLAYNAME}"' in script
    assert 'WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"' in script
    assert r'WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""' in script
    assert 'WriteRegStr HKCU "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"' in script
    assert script.count("DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT fixture_") == 2
    assert script.count("DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT fixture_") == 2
    unknown_invocation = (
        'ProductName "DroneDream-Unknown" -DisplayName "DroneDream · UNKNOWN" '
        '-ExpectedSuccess $false'
    )
    assert unknown_invocation in script
    assert 'Remove-Item -LiteralPath $resolved -Recurse -Force' in script


def test_universal_lifecycle_uses_display_name_and_preserves_legacy_shortcut_collision() -> None:
    lifecycle = (ROOT / "desktop/scripts/verify-universal-installer-lifecycle.ps1").read_text(
        encoding="utf-8"
    )
    assert '$productName = "DroneDream-Universal"' in lifecycle
    assert '$displayName = "DroneDream"' in lifecycle
    assert 'DisplayName = $displayName' in lifecycle
    assert 'DisplayName = [string]$registration.DisplayName' in lifecycle
    assert 'comparison = $registrationComparison' in lifecycle
    assert 'Compare-DroneDreamUninstallRegistration' in lifecycle
    assert 'Get-DroneDreamProductRegistrationDisposition' in lifecycle
    assert 'protected-legacy-shortcut-preserved' in lifecycle
    assert 'created a shortcut under the internal product identity' in lifecycle
    assert 'if (-not $Before.baseDesktopShortcut.exists)' in lifecycle
    assert 'if (-not $Before.baseStartMenuShortcut.exists)' in lifecycle
    assert 'displayShortcutPolicy = "preserve-existing-legacy-or-own-when-absent"' in lifecycle
