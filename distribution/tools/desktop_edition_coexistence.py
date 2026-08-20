"""Fail-closed validation for five independently installed desktop editions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("distribution/desktop/edition-coexistence.v1.json")
EDITION_IDS = ("universal", "sim", "lab", "field", "autonomy")
EDITION_LABELS = {
    "universal": "Universal",
    "sim": "Sim",
    "lab": "Lab",
    "field": "Field",
    "autonomy": "Autonomy",
}
DISPLAY_NAMES = {
    "universal": "DroneDream",
    "sim": "DroneDream · SIM",
    "lab": "DroneDream · LAB",
    "field": "DroneDream · FIELD",
    "autonomy": "DroneDream · AUTONOMY",
}


class DesktopEditionCoexistenceError(RuntimeError):
    """Raised when desktop identities could collide or share authority."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise DesktopEditionCoexistenceError(f"{label} fields drifted")


def _unique(editions: list[dict[str, Any]], field: str) -> None:
    values = [edition[field] for edition in editions]
    if len(set(values)) != len(values):
        raise DesktopEditionCoexistenceError(f"desktop edition {field} values collide")


def validate_contract(document: Any, *, root: Path) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DesktopEditionCoexistenceError("desktop coexistence contract must be an object")
    _require_exact_keys(
        document,
        {
            "schemaVersion",
            "kind",
            "contractVersion",
            "productDisplayVersion",
            "accountAuthority",
            "sharedResources",
            "legacyDesktop",
            "editions",
            "stateMachineVerification",
        },
        "desktop coexistence contract",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-desktop-edition-coexistence"
        or document["contractVersion"] != "1.0.0"
        or document["productDisplayVersion"] != "1.0.0"
    ):
        raise DesktopEditionCoexistenceError("desktop coexistence identity is unsupported")

    account = document["accountAuthority"]
    if account != {
        "provider": "supabase",
        "projectUrl": "https://yggabfynndpzymlqvnim.supabase.co",
        "sharedAccountSubject": True,
        "sharedCloudDataAuthorization": True,
        "desktopSessionSharing": False,
        "desktopTokenImport": False,
    }:
        raise DesktopEditionCoexistenceError("shared account or isolated session policy drifted")

    shared = document["sharedResources"]
    if (
        shared.get("runtimeBaseName") != "DroneDreamRuntime"
        or shared.get("runtimeOwner") != "runtime-base-manager"
        or shared.get("runtimeRemovedByEditionUninstall") is not False
        or shared.get("protocolOwnerPolicy") != "edition-namespaced"
        or shared.get("serviceTaskAutorunPolicy") != "unique-owner-or-edition-namespaced"
    ):
        raise DesktopEditionCoexistenceError("shared resource ownership drifted")

    legacy = document["legacyDesktop"]
    if (
        legacy.get("productName") != "DroneDream"
        or legacy.get("bundleIdentifier") != "io.dronedream.desktop"
        or legacy.get("silentOverwriteAllowed") is not False
        or legacy.get("migrationRequiresOperatorConfirmation") is not True
        or legacy.get("migrationMustPreserveRuntimeAndUserData") is not True
        or legacy.get("unresolvedShortcutConflictBlocksShortcutCreation") is not True
    ):
        raise DesktopEditionCoexistenceError("legacy migration must fail closed")

    editions = document["editions"]
    if not isinstance(editions, list) or [item.get("editionId") for item in editions] != list(
        EDITION_IDS
    ):
        raise DesktopEditionCoexistenceError("desktop editions must be canonical and ordered")
    edition_keys = {
        "editionId",
        "artifactFileName",
        "installerProductName",
        "displayName",
        "bundleIdentifier",
        "installRoot",
        "uninstallRegistryKey",
        "productRegistryKey",
        "startMenuFolder",
        "desktopShortcutName",
        "appUserModelId",
        "updaterChannel",
        "updaterMetadataFileName",
        "runtimeProfileId",
        "authClientId",
        "loopbackPathPrefix",
        "customProtocol",
        "credentialVaultNamespace",
        "webViewDataNamespace",
        "brandEditionId",
        "canonicalWindowsIcon",
    }
    for field in (
        "artifactFileName",
        "installerProductName",
        "bundleIdentifier",
        "installRoot",
        "uninstallRegistryKey",
        "productRegistryKey",
        "desktopShortcutName",
        "appUserModelId",
        "updaterChannel",
        "updaterMetadataFileName",
        "authClientId",
        "loopbackPathPrefix",
        "customProtocol",
        "credentialVaultNamespace",
        "webViewDataNamespace",
    ):
        _unique(editions, field)
    brand_manifest = json.loads(
        (root / "brand/generated/brand-assets.v1.json").read_text(encoding="utf-8")
    )
    brand_assets = {item["path"]: item for item in brand_manifest["assets"]}
    for edition in editions:
        edition_id = edition["editionId"]
        label = EDITION_LABELS[edition_id]
        _require_exact_keys(edition, edition_keys, f"desktop edition {edition_id}")
        expected = {
            "artifactFileName": f"DroneDream-{label}-1.0.0.exe",
            "installerProductName": f"DroneDream-{label}",
            "displayName": DISPLAY_NAMES[edition_id],
            "bundleIdentifier": f"io.dronedream.desktop.{edition_id}",
            "installRoot": f"%LOCALAPPDATA%/DroneDream-{label}",
            "uninstallRegistryKey": (
                "HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/"
                f"DroneDream-{label}"
            ),
            "productRegistryKey": f"HKCU/Software/DroneDream/DroneDream-{label}",
            "startMenuFolder": f"DroneDream-{label}",
            "desktopShortcutName": DISPLAY_NAMES[edition_id],
            "appUserModelId": f"io.dronedream.desktop.{edition_id}",
            "updaterChannel": edition_id,
            "updaterMetadataFileName": f"latest-{edition_id}.json",
            "authClientId": f"dronedream-desktop-{edition_id}",
            "loopbackPathPrefix": f"/desktop-auth/{edition_id}/",
            "customProtocol": f"dronedream-{edition_id}",
            "credentialVaultNamespace": f"DroneDream/Auth/{edition_id}/v1",
            "webViewDataNamespace": f"io.dronedream.desktop.{edition_id}",
            "brandEditionId": edition_id,
            "canonicalWindowsIcon": f"brand/generated/{edition_id}/windows/icon.ico",
        }
        for field, value in expected.items():
            if edition[field] != value:
                raise DesktopEditionCoexistenceError(
                    f"desktop edition {edition_id} {field} drifted"
                )
        icon_path = root / edition["canonicalWindowsIcon"]
        manifest_icon = brand_assets.get(edition["canonicalWindowsIcon"])
        if (
            icon_path.is_symlink()
            or not icon_path.is_file()
            or not isinstance(manifest_icon, dict)
            or manifest_icon.get("format") != "ICO"
            or sha256_file(icon_path) != manifest_icon.get("sha256")
        ):
            raise DesktopEditionCoexistenceError(
                f"desktop edition {edition_id} canonical icon drifted"
            )

    verification = document["stateMachineVerification"]
    if (
        verification.get("installOrderCoverage") != "pairwise-plus-all-five"
        or verification.get("releaseRequiresExecutedReceipt") is not True
        or set(verification.get("requiredStates", []))
        != {
            "all-five-installed",
            "each-edition-upgraded-in-place",
            "each-edition-uninstalled-alone",
            "remaining-four-still-launchable",
            "legacy-detected-without-overwrite",
        }
    ):
        raise DesktopEditionCoexistenceError("coexistence state-machine gate drifted")
    return document


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_PATH
    if path.is_symlink() or not path.is_file():
        raise DesktopEditionCoexistenceError("desktop coexistence contract is unavailable")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopEditionCoexistenceError("desktop coexistence contract is invalid") from error
    return validate_contract(document, root=root)
