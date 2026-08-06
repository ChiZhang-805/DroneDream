"""Validate shared Runtime ownership and isolated desktop update families."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path("distribution/desktop/edition-runtime-update-families.v1.json")
EDITION_IDS = ("universal", "sim", "lab", "field")
EDITION_LABELS = {
    "universal": "Universal",
    "sim": "Sim",
    "lab": "Lab",
    "field": "Field",
}
RUNTIME_PROFILES = {
    "universal": "unified-sim-lab",
    "sim": "sim-only",
    "lab": "unified-sim-lab",
    "field": "field-lightweight",
}


class DesktopRuntimeUpdateFamilyError(RuntimeError):
    """Raised when Runtime ownership or an updater family can collide."""


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise DesktopRuntimeUpdateFamilyError(f"{label} fields drifted")


def _unique(editions: list[dict[str, Any]], field: str) -> None:
    values = [edition[field] for edition in editions]
    if len(values) != len(set(values)):
        raise DesktopRuntimeUpdateFamilyError(f"desktop {field} families collide")


def validate_contract(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise DesktopRuntimeUpdateFamilyError("Runtime/update contract must be an object")
    _require_exact_keys(
        document,
        {
            "schemaVersion",
            "kind",
            "contractVersion",
            "productDisplayVersion",
            "sharedRuntimeBase",
            "updaterPolicy",
            "editions",
        },
        "Runtime/update contract",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-desktop-runtime-update-families"
        or document["contractVersion"] != "1.0.0"
        or document["productDisplayVersion"] != "1.0.0"
    ):
        raise DesktopRuntimeUpdateFamilyError("Runtime/update contract identity is unsupported")

    shared = document["sharedRuntimeBase"]
    if shared != {
        "productId": "DroneDreamRuntime",
        "wslDistributionName": "DroneDreamRuntime",
        "owner": "runtime-base-manager",
        "managerNamespace": "io.dronedream.runtime-base-manager",
        "operationLeaseFileName": "runtime-operation-v1.lock",
        "legacyCompatibilityLeaseRelativePath": (
            "io.dronedream.desktop/runtime-operation-v1.lock"
        ),
        "legacyCompatibilityLeaseRequired": True,
        "downloadCacheDirectoryName": "DroneDream.download-cache",
        "diagnosticsRootDirectoryName": "diagnostics",
        "editionUninstallMayRemoveRuntime": False,
        "editionOperationsMayUseIndependentLocks": False,
    }:
        raise DesktopRuntimeUpdateFamilyError("shared Runtime ownership drifted")

    policy = document["updaterPolicy"]
    if policy != {
        "repository": "ChiZhang-805/DroneDream",
        "metadataOrigin": "https://github.com/ChiZhang-805/DroneDream/releases/download",
        "channelTagTemplate": "desktop-{editionId}-channel",
        "metadataFileTemplate": "latest-{editionId}.json",
        "releaseTagTemplate": "desktop-{editionId}-v{version}-build-{buildNumber}",
        "sameEditionUrlFamilyRequired": True,
        "crossEditionMetadataAllowed": False,
        "crossEditionArtifactAllowed": False,
        "sourceCommitAndBuildNumberRequired": True,
        "updaterSignatureRequired": True,
    }:
        raise DesktopRuntimeUpdateFamilyError("updater family policy drifted")

    editions = document["editions"]
    if not isinstance(editions, list) or [item.get("editionId") for item in editions] != list(
        EDITION_IDS
    ):
        raise DesktopRuntimeUpdateFamilyError(
            "desktop update families must be canonical and ordered"
        )
    edition_keys = {
        "editionId",
        "runtimeProfileId",
        "localRuntimeStateNamespace",
        "diagnosticsRelativePath",
        "installerProductName",
        "publicArtifactFileName",
        "tauriBundleInstallerFileName",
        "updaterChannelTag",
        "updaterMetadataFileName",
        "updaterMetadataUrl",
        "updaterReleaseTagPrefix",
    }
    for field in (
        "localRuntimeStateNamespace",
        "diagnosticsRelativePath",
        "installerProductName",
        "publicArtifactFileName",
        "tauriBundleInstallerFileName",
        "updaterChannelTag",
        "updaterMetadataFileName",
        "updaterMetadataUrl",
        "updaterReleaseTagPrefix",
    ):
        _unique(editions, field)
    origin = policy["metadataOrigin"]
    for edition in editions:
        edition_id = edition["editionId"]
        label = EDITION_LABELS[edition_id]
        _require_exact_keys(edition, edition_keys, f"desktop {edition_id} family")
        expected = {
            "runtimeProfileId": RUNTIME_PROFILES[edition_id],
            "localRuntimeStateNamespace": f"io.dronedream.desktop.{edition_id}/runtime",
            "diagnosticsRelativePath": f"diagnostics/{edition_id}",
            "installerProductName": f"DroneDream-{label}",
            "publicArtifactFileName": f"DroneDream-{label}-1.0.0.exe",
            "tauriBundleInstallerFileName": f"DroneDream-{label}_1.0.0_x64-setup.exe",
            "updaterChannelTag": f"desktop-{edition_id}-channel",
            "updaterMetadataFileName": f"latest-{edition_id}.json",
            "updaterMetadataUrl": (
                f"{origin}/desktop-{edition_id}-channel/latest-{edition_id}.json"
            ),
            "updaterReleaseTagPrefix": f"desktop-{edition_id}-v1.0.0-build-",
        }
        for field, value in expected.items():
            if edition[field] != value:
                raise DesktopRuntimeUpdateFamilyError(
                    f"desktop {edition_id} {field} drifted"
                )
    return document


def load_contract(root: Path) -> dict[str, Any]:
    path = root / CONTRACT_PATH
    if path.is_symlink() or not path.is_file():
        raise DesktopRuntimeUpdateFamilyError("Runtime/update contract is unavailable")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesktopRuntimeUpdateFamilyError("Runtime/update contract is invalid") from error
    return validate_contract(document)
