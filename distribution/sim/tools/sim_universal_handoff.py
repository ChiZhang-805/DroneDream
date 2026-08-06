#!/usr/bin/env python3
"""Verify the path-limited Universal handoff adopted by DroneDream SIM."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

OBSERVED_HEAD = "528ecf39ef7c4f2a85b88af73a76057f87184e35"
BRAND_PRODUCT = "b8e0d0c7093abe9f54fe36f01022deb95852fa39"

EXACT_GROUPS = {
    "2d19b045c11f5e78ae1a0b6554aee0d0ad382335": (
        "distribution/schemas/desktop-edition-coexistence.schema.json",
        "distribution/tools/desktop_edition_coexistence.py",
    ),
    "8a8ad6ce0ea619a52ec087b7f55142c24311165a": (
        "desktop/scripts/verify-nsis-template.ps1",
        "desktop/src-tauri/nsis/edition-identity.nsh",
        "desktop/src-tauri/nsis/installer-languages.nsh",
        "desktop/src-tauri/nsis/installer.nsi",
        "desktop/src-tauri/nsis/languages/English.nsh",
        "desktop/src-tauri/nsis/languages/SimpChinese.nsh",
        "desktop/src-tauri/nsis/webview2-health.nsh",
        "distribution/tests/test_desktop_edition_coexistence.py",
    ),
    "6355aad351370178a7171b504a5d2f235fb12ceb": (
        "distribution/desktop/edition-browser-auth.v1.json",
        "distribution/schemas/desktop-edition-browser-auth.schema.json",
        "distribution/tests/test_desktop_edition_browser_auth.py",
        "distribution/tools/desktop_edition_browser_auth.py",
    ),
    "2f1dbc5fef092ae4cf58366e1178684672ae26c2": (
        "desktop/scripts/verify-browser-auth-config.mjs",
        "desktop/src-tauri/browser-auth.html",
        "frontend/scripts/verify-desktop-browser-auth.mjs",
        "frontend/src/__tests__/browserAuth.test.ts",
        "frontend/src/features/auth/browserAuth.ts",
    ),
    "bed637c726462e1a38b74eba46915543d007869d": (
        "desktop/src-tauri/Cargo.toml",
        "desktop/src-tauri/src/browser_auth_vault.rs",
        "frontend/src/__tests__/AuthContext.test.tsx",
        "frontend/src/__tests__/DesktopSetup.test.tsx",
        "frontend/src/__tests__/desktopBridge.test.ts",
        "frontend/src/__tests__/supabaseClient.test.ts",
        "frontend/src/desktop/bridge.ts",
        "frontend/src/features/auth/AuthContext.tsx",
        "frontend/src/features/auth/supabaseClient.ts",
    ),
    "4c779b7ca316c0953f94f7ef3f4f850881ef2d58": (
        "desktop/src-tauri/src/browser_auth.rs",
        "desktop/src-tauri/src/browser_auth_audit.rs",
    ),
    "8a0828c258782fa77506ee32c7c016e5b18ad292": (
        "desktop/src-tauri/build.rs",
        "desktop/src-tauri/src/runtime_installer.rs",
        "distribution/desktop/edition-coexistence.v1.json",
        "distribution/desktop/edition-runtime-update-families.v1.json",
        "distribution/schemas/desktop-edition-runtime-update-families.schema.json",
        "distribution/tests/test_desktop_runtime_update_families.py",
        "distribution/tools/desktop_runtime_update_families.py",
    ),
    "a918113282b94cf5ebb0b6af3354c5cf2e2ad51d": (
        "desktop/scripts/build-windows-llvm.ps1",
        "desktop/scripts/verify-updater-build-contract.ps1",
        "desktop/scripts/write-updater-manifest.ps1",
        "desktop/src-tauri/src/app_update.rs",
        "desktop/src-tauri/src/lib.rs",
        "desktop/src-tauri/tauri.conf.json",
        "desktop/src-tauri/tauri.universal.conf.json",
        "distribution/tests/test_shared_windows_build_contract.py",
    ),
}


class SimUniversalHandoffError(ValueError):
    """Raised when handoff provenance or SIM isolation drifts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SimUniversalHandoffError(message)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _brand_paths(root: Path) -> tuple[str, ...]:
    paths = _git(root, "ls-tree", "-r", "--name-only", BRAND_PRODUCT).splitlines()
    selected = []
    for path in paths:
        if (
            path in {".gitattributes", "scripts/build-brand-assets.py"}
            or path.startswith("brand/")
            or path.startswith("docs/assets/brand/")
            or path == "docs/assets/drone-dream-icon.png"
            or path == "frontend/public/drone-favicon.png"
            or path.startswith("frontend/src/assets/brand/")
            or path.startswith("frontend/src/assets/drone-dream-")
            or path.startswith("frontend/src/brand/")
            or path in {
                "desktop/src-tauri/app-icon.png",
                "desktop/src-tauri/icon-source.svg",
            }
            or path.startswith("desktop/src-tauri/icons/")
        ):
            selected.append(path)
    return tuple(selected)


def exact_synchronized_paths(root: Path) -> tuple[str, ...]:
    """Return the canonical path set consumed from the listed product donors."""
    common_paths = tuple(path for paths in EXACT_GROUPS.values() for path in paths)
    return _brand_paths(root) + common_paths


def _validate_exact_path(root: Path, commit: str, path: str) -> None:
    _require((root / path).is_file(), f"synchronized path missing: {path}")
    donor_blob = _git(root, "rev-parse", f"{commit}:{path}")
    current_blob = _git(root, "hash-object", "--", path)
    _require(current_blob == donor_blob, f"synchronized blob drifted: {path}")


def validate_handoff(document: dict[str, Any], root: Path) -> dict[str, Any]:
    _require(document.get("schemaVersion") == 1, "schemaVersion must be 1")
    _require(
        document.get("kind") == "dronedream-sim-universal-common-core-handoff",
        "unexpected handoff kind",
    )
    _require(document.get("editionId") == "sim", "editionId must be sim")
    source = document.get("source", {})
    _require(source.get("observedHead") == OBSERVED_HEAD, "observed head drifted")
    _require(source.get("observedHeadIsEvidenceOnly") is True, "evidence head relabelled")
    _require(source.get("evidenceCommitUsedAsProductSource") is False, "evidence overclaim")
    observed_head_is_ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "merge-base",
            "--is-ancestor",
            OBSERVED_HEAD,
            "origin/codex/software",
        ],
        check=False,
        capture_output=True,
    ).returncode == 0
    _require(
        observed_head_is_ancestor,
        "observed Universal evidence head is not reachable from its branch",
    )

    brand_paths = _brand_paths(root)
    _require(len(brand_paths) == 94, "canonical brand path count drifted")
    for path in brand_paths:
        _validate_exact_path(root, BRAND_PRODUCT, path)
    common_paths = [path for paths in EXACT_GROUPS.values() for path in paths]
    _require(len(common_paths) == len(set(common_paths)) == 45, "common path inventory drifted")
    for commit, paths in EXACT_GROUPS.items():
        for path in paths:
            _validate_exact_path(root, commit, path)
    path_sync = document.get("pathSync", {})
    _require(path_sync.get("canonicalBrandPathCount") == 94, "brand count receipt drifted")
    _require(path_sync.get("exactCommonPathCount") == 45, "common count receipt drifted")
    _require(path_sync.get("unrelatedBenchmarkPathsAdopted") is False, "Benchmark overclaim")
    _require(path_sync.get("hardwareAuthorityGranted") is False, "hardware authority overclaim")

    brand = document.get("brand", {})
    _require(
        _sha256(root / brand["manifestPath"]) == brand.get("manifestSha256"),
        "brand manifest SHA drifted",
    )
    _require(
        _sha256(root / brand["simLargeLabelPath"])
        == brand.get("simLargeLabelSha256"),
        "SIM lockup SHA drifted",
    )
    _require(
        _sha256(root / brand["simIcoPath"]) == brand.get("simIcoSha256"),
        "SIM ICO SHA drifted",
    )
    _require(brand.get("presentationOnly") is True, "brand presentation boundary drifted")
    _require(brand.get("grantsHardwareAuthority") is False, "brand authority overclaim")

    identity = document.get("simBuildIdentity", {})
    _require(identity.get("desktopEditionId") == "sim", "desktop edition drifted")
    _require(identity.get("runtimeProfileId") == "sim-only", "runtime profile drifted")
    _require(identity.get("frontendEditionId") == "sim", "frontend edition drifted")
    _require(identity.get("oauthClientId") == "dronedream-desktop-sim", "OAuth client drifted")
    _require(identity.get("validatedVehiclePackCount") == 0, "vehicle validation overclaim")
    overlay = json.loads(
        (root / "distribution/sim/desktop/tauri.sim.conf.json").read_text(encoding="utf-8")
    )
    _require(overlay.get("productName") == "DroneDream-Sim", "SIM product identity drifted")
    _require(overlay.get("identifier") == "io.dronedream.sim", "SIM bundle identity drifted")
    _require(
        overlay.get("app", {}).get("windows", [{}])[0].get("title")
        == "DroneDream \u00b7 SIM",
        "SIM display identity drifted",
    )
    profile = json.loads(
        (root / "distribution/sim/build-profile.v1.json").read_text(encoding="utf-8")
    )
    _require(profile.get("editionId") == "sim", "SIM profile edition drifted")
    _require(
        profile.get("manifests", {}).get("enginePackProfile", {}).get("profileId")
        == "sim-only",
        "SIM Engine Pack profile drifted",
    )

    adapter = (root / path_sync["simSemanticAdapterPath"]).read_text(encoding="utf-8")
    for required in (
        "<SimEditionBadge compact />",
        "restoreBrowserAuthVault()",
        "beginBrowserAuth({ locale })",
        "clearBrowserAuthVault()",
    ):
        _require(required in adapter, f"SIM auth adapter drifted: {required}")

    blockers = document.get("upstreamBlockers", [])
    _require([item.get("id") for item in blockers] == [
        "AUTH-COEXISTENCE-SHA-DRIFT",
        "NSIS-RUNTIME-MODE-DONOR-OMITTED",
    ], "upstream blockers drifted")
    coexistence_sha = _sha256(root / "distribution/desktop/edition-coexistence.v1.json")
    auth = json.loads(
        (root / "distribution/desktop/edition-browser-auth.v1.json").read_text(encoding="utf-8")
    )
    _require(
        blockers[0].get("boundCoexistenceSha256")
        == auth.get("identityBinding", {}).get("contractSha256"),
        "auth bound SHA receipt drifted",
    )
    _require(
        blockers[0].get("currentCoexistenceSha256") == coexistence_sha,
        "coexistence SHA receipt drifted",
    )
    _require(
        blockers[0]["boundCoexistenceSha256"] != coexistence_sha,
        "auth blocker silently resolved",
    )
    runtime_path = blockers[1]["path"]
    _require(
        _git(root, "hash-object", "--", runtime_path)
        == blockers[1]["currentBlob"],
        "runtime blocker drifted",
    )
    _require(
        blockers[1]["currentBlob"] != blockers[1]["requiredObservedBlob"],
        "runtime blocker silently resolved",
    )

    verification = document.get("verification", {})
    for key, value in verification.items():
        expected = key not in {"authContractBindingPassed", "nsisTemplateGatePassed"}
        _require(value is expected, f"verification claim drifted: {key}")
    classification = document.get("commonCoreClassification", {})
    _require(classification.get("baselineUpdated") is False, "commonCore update overclaim")
    _require(
        classification.get("candidateClaimedAsValidatedCommonCore") is False,
        "candidate commonCore overclaim",
    )
    execution = document.get("execution", {})
    _require(
        execution and all(value is False for value in execution.values()),
        "execution overclaim",
    )
    non_claims = document.get("nonClaims", {})
    _require(
        non_claims and all(value is False for value in non_claims.values()),
        "release overclaim",
    )
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.receipt.read_text(encoding="utf-8"))
    validate_handoff(document, args.repo_root.resolve())
    print(
        json.dumps(
            {
                "valid": True,
                "brandPaths": 94,
                "commonPaths": 45,
                "yellow2Ready": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
