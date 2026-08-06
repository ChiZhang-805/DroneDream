#!/usr/bin/env python3
"""Verify the path-limited SIM adoption of the installer coexistence donor."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

DONOR = "8a8ad6ce0ea619a52ec087b7f55142c24311165a"
DONOR_PARENT = "7482647f1c2fcb92f58aaef009efc99764792297"
DONOR_TREE = "b07389020a5e55e2016612f1ad92ec031706ad26"
DONOR_TEST_PATH = "distribution/tests/test_desktop_edition_coexistence.py"
EXPECTED_RUNTIME_PATHS = (
    "desktop/scripts/verify-nsis-template.ps1",
    "desktop/src-tauri/nsis/edition-identity.nsh",
    "desktop/src-tauri/nsis/installer-languages.nsh",
    "desktop/src-tauri/nsis/installer.nsi",
    "desktop/src-tauri/nsis/languages/English.nsh",
    "desktop/src-tauri/nsis/languages/SimpChinese.nsh",
    "desktop/src-tauri/nsis/webview2-health.nsh",
)
EXPECTED_PREREQUISITES = (
    "distribution/tools/desktop_edition_coexistence.py",
    "distribution/desktop/edition-coexistence.v1.json",
    "distribution/schemas/desktop-edition-coexistence.schema.json",
    "desktop/src-tauri/tauri.universal.conf.json",
    "desktop/src-tauri/nsis/runtime-mode.nsh",
)


class SimCoexistenceSyncError(ValueError):
    """Raised when coexistence source identity or fail-closed state drifts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SimCoexistenceSyncError(message)


def _git(repo_root: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    return result.stdout if binary else result.stdout.strip()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_sync(document: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    _require(document.get("schemaVersion") == 1, "schemaVersion must be 1")
    _require(
        document.get("kind") == "dronedream-sim-coexistence-common-core-sync",
        "unexpected receipt kind",
    )
    _require(document.get("editionId") == "sim", "editionId must be sim")
    source = document.get("source", {})
    _require(source.get("donorCommit") == DONOR, "donor commit drifted")
    _require(source.get("donorParentCommit") == DONOR_PARENT, "donor parent drifted")
    _require(source.get("donorTree") == DONOR_TREE, "donor tree drifted")
    _require(source.get("wholeCommitCherryPicked") is False, "whole commit overclaim")
    _require(source.get("unrelatedParentChainAdopted") is False, "parent chain overclaim")
    _require(_git(repo_root, "rev-parse", f"{DONOR}^") == DONOR_PARENT, "observed parent drifted")
    _require(
        _git(repo_root, "show", "-s", "--format=%T", DONOR) == DONOR_TREE, "observed tree drifted"
    )

    donor_paths = str(
        _git(repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", DONOR)
    ).splitlines()
    _require(
        source.get("donorChangedPathCount") == len(donor_paths) == 8, "donor path count drifted"
    )
    _require(
        set(donor_paths) == set(EXPECTED_RUNTIME_PATHS) | {DONOR_TEST_PATH},
        "donor path set drifted",
    )

    rows = document.get("synchronizedRuntimePaths")
    _require(isinstance(rows, list) and len(rows) == 7, "runtime path inventory drifted")
    _require(
        tuple(row.get("path") for row in rows) == EXPECTED_RUNTIME_PATHS,
        "runtime path order drifted",
    )
    canonical_rows: list[dict[str, str]] = []
    for row in rows:
        path = row["path"]
        donor_blob = str(_git(repo_root, "rev-parse", f"{DONOR}:{path}"))
        current_blob = str(_git(repo_root, "hash-object", "--", path))
        payload = (repo_root / path).read_bytes()
        _require(row.get("blob") == donor_blob == current_blob, f"runtime blob drifted: {path}")
        _require(row.get("sha256") == _sha256(payload), f"runtime SHA drifted: {path}")
        canonical_rows.append({"path": path, "blob": donor_blob})
    canonical = (json.dumps(canonical_rows, sort_keys=True, separators=(",", ":")) + "\n").encode()
    _require(
        document.get("synchronizedRuntimeBlobSetSha256") == _sha256(canonical),
        "runtime blob set SHA drifted",
    )

    observed_test = document.get("observedNotAdoptedTest", {})
    test_payload = _git(repo_root, "show", f"{DONOR}:{DONOR_TEST_PATH}", binary=True)
    _require(observed_test.get("path") == DONOR_TEST_PATH, "observed test path drifted")
    _require(
        observed_test.get("blob") == _git(repo_root, "rev-parse", f"{DONOR}:{DONOR_TEST_PATH}"),
        "observed test blob drifted",
    )
    _require(observed_test.get("sha256") == _sha256(test_payload), "observed test SHA drifted")
    _require(not (repo_root / DONOR_TEST_PATH).exists(), "unclosed donor test was adopted")

    prerequisites = document.get("pendingPrerequisitePaths")
    _require(
        tuple(row.get("path") for row in prerequisites) == EXPECTED_PREREQUISITES,
        "prerequisite path set drifted",
    )
    for row in prerequisites:
        path = repo_root / row["path"]
        _require(
            row.get("donorBlob") == _git(repo_root, "rev-parse", f"{DONOR}:{row['path']}"),
            f"prerequisite donor blob drifted: {row['path']}",
        )
        if row.get("state") == "missing-in-sim":
            _require(not path.exists(), f"unhanded prerequisite adopted: {row['path']}")
        elif row.get("state") == "present-but-not-donor-blob":
            _require(path.is_file(), f"divergent prerequisite disappeared: {row['path']}")
            current_blob = str(_git(repo_root, "hash-object", "--", row["path"]))
            _require(
                row.get("currentBlob") == current_blob,
                f"current prerequisite blob drifted: {row['path']}",
            )
            _require(
                current_blob != row.get("donorBlob"),
                f"unhanded prerequisite silently adopted: {row['path']}",
            )
            _require(
                row.get("currentSha256") == _sha256(path.read_bytes()),
                f"current prerequisite SHA drifted: {row['path']}",
            )
            donor_payload = _git(repo_root, "show", f"{DONOR}:{row['path']}", binary=True)
            _require(
                row.get("donorSha256") == _sha256(donor_payload),
                f"prerequisite donor SHA drifted: {row['path']}",
            )
        else:
            raise SimCoexistenceSyncError(f"unknown prerequisite state: {row['path']}")

    classification = document.get("commonCoreClassification", {})
    _require(classification.get("baselineUpdated") is False, "baseline update overclaimed")
    _require(
        classification.get("candidateHashClaimedAsCurrent") is False,
        "candidate hash relabeled",
    )
    overlay = document.get("simOverlay", {})
    overlay_path = repo_root / overlay.get("path", "")
    overlay_document = json.loads(overlay_path.read_text(encoding="utf-8"))
    _require(_sha256(overlay_path.read_bytes()) == overlay.get("sha256"), "overlay SHA drifted")
    _require(
        overlay.get("installerProductName") == "DroneDream-Sim",
        "internal name receipt drifted",
    )
    _require(overlay.get("displayName") == "DroneDream \u00b7 SIM", "display receipt drifted")
    _require(overlay.get("bundleIdentifier") == "io.dronedream.sim", "bundle receipt drifted")
    _require(overlay_document.get("productName") == "DroneDream-Sim", "internal name drifted")
    _require(overlay_document.get("identifier") == "io.dronedream.sim", "bundle identity drifted")
    _require(
        overlay_document.get("app", {}).get("windows", [{}])[0].get("title")
        == "DroneDream \u00b7 SIM",
        "display name drifted",
    )
    _require(overlay.get("hardwareAuthorityGranted") is False, "hardware authority overclaim")

    identity = (repo_root / "desktop/src-tauri/nsis/edition-identity.nsh").read_text(
        encoding="utf-8"
    )
    installer = (repo_root / "desktop/src-tauri/nsis/installer.nsi").read_text(encoding="utf-8")
    for required in (
        '!else if "${PRODUCTNAME}" == "DroneDream-Sim"',
        '!define DRONEDREAM_DISPLAYNAME "DroneDream \u00b7 SIM"',
        '!error "Unknown DroneDream installer PRODUCTNAME:',
        'IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\\${MAINBINARYNAME}.exe"',
        'DetailPrint "$(DD_ShortcutConflict)"',
        "SetErrors",
    ):
        _require(required in identity, f"identity guard missing: {required}")
    for required in (
        '!define UNINSTKEY "Software\\Microsoft\\Windows\\'
        'CurrentVersion\\Uninstall\\${PRODUCTNAME}"',
        'StrCpy $INSTDIR "$LOCALAPPDATA\\${PRODUCTNAME}"',
        'RmDir /r "$LOCALAPPDATA\\${BUNDLEID}"',
        'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${DRONEDREAM_DISPLAYNAME}"',
        "DRONEDREAM_REMOVE_INTERNAL_SHORTCUT",
    ):
        _require(required in installer, f"installer ownership guard missing: {required}")

    acceptance = document.get("staticAcceptance", {})
    _require(acceptance.get("validatedVehiclePackCount") == 0, "pack count overclaim")
    _require(
        all(
            value is True for key, value in acceptance.items() if key != "validatedVehiclePackCount"
        ),
        "static acceptance must be explicit",
    )
    verification = document.get("verification", {})
    _require(
        verification.get("exactSynchronizedRuntimeBlobsPassed") is True,
        "runtime verification drifted",
    )
    _require(
        verification.get("simOwnedNegativeTestsPassed") is True, "negative verification drifted"
    )
    _require(
        verification.get("donorVendoredNsisVerifierPassed") is False, "vendored verifier overclaim"
    )
    _require(
        verification.get("compiledLocaleVerifierExecuted") is False, "locale execution overclaim"
    )
    _require(
        verification.get("installerUiVerifierExecuted") is False, "installer UI execution overclaim"
    )
    execution = document.get("execution", {})
    _require(
        execution and all(value is False for value in execution.values()), "execution overclaim"
    )
    non_claims = document.get("nonClaims", {})
    _require(
        non_claims and all(value is False for value in non_claims.values()), "nonClaims drifted"
    )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.receipt.read_text(encoding="utf-8"))
    validate_sync(document, args.repo_root.resolve())
    print(
        json.dumps(
            {
                "valid": True,
                "donorCommit": DONOR,
                "synchronizedRuntimePathCount": 7,
                "commonCoreBaselineUpdated": False,
                "releaseAsset": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
