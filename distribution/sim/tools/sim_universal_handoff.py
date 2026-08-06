#!/usr/bin/env python3
"""Verify the path-limited Universal handoff adopted by DroneDream SIM."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

OBSERVED_HEAD = "6f25bb5051794842a8dfc6d02d199c5f93afce7c"
OBSERVED_TREE = "d5d6acb39fec0af65bac4fbd4f964b6aeab73b3d"
BRAND_PRODUCT = "b8e0d0c7093abe9f54fe36f01022deb95852fa39"

EXACT_GROUPS = {
    "2d19b045c11f5e78ae1a0b6554aee0d0ad382335": (
        "distribution/schemas/desktop-edition-coexistence.schema.json",
        "distribution/tools/desktop_edition_coexistence.py",
    ),
    "8a8ad6ce0ea619a52ec087b7f55142c24311165a": (
        "desktop/src-tauri/nsis/edition-identity.nsh",
        "desktop/src-tauri/nsis/installer-languages.nsh",
        "desktop/src-tauri/nsis/installer.nsi",
        "desktop/src-tauri/nsis/languages/English.nsh",
        "desktop/src-tauri/nsis/languages/SimpChinese.nsh",
        "desktop/src-tauri/nsis/webview2-health.nsh",
        "distribution/tests/test_desktop_edition_coexistence.py",
    ),
    "ba1b44955a96b88dda50b7f7bd8b6db58ac91a75": (
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
    "c322cda1c968d15b09e8ac93364f885777b619e8": (
        "distribution/desktop/edition-browser-auth.v1.json",
    ),
    "b099ed00923e9f2b833f812ad79f1614529038de": (
        "desktop/src-tauri/nsis/runtime-mode.nsh",
        "desktop/src-tauri/src/installer_handoff.rs",
    ),
    OBSERVED_HEAD: (
        "desktop/scripts/verify-nsis-template.ps1",
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
    _require(source.get("observedTree") == OBSERVED_TREE, "observed tree drifted")
    _require(source.get("observedHeadIsEvidenceOnly") is False, "product head relabelled")
    _require(
        source.get("observedHeadUsedAsWholeProductSource") is False,
        "whole Universal head overclaim",
    )
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
        "observed Universal product head is not reachable from its branch",
    )
    _require(
        _git(root, "show", "-s", "--format=%T", OBSERVED_HEAD) == OBSERVED_TREE,
        "observed Universal tree identity drifted",
    )

    brand_paths = _brand_paths(root)
    _require(len(brand_paths) == 94, "canonical brand path count drifted")
    for path in brand_paths:
        _validate_exact_path(root, BRAND_PRODUCT, path)
    common_paths = [path for paths in EXACT_GROUPS.values() for path in paths]
    _require(len(common_paths) == len(set(common_paths)) == 47, "common path inventory drifted")
    for commit, paths in EXACT_GROUPS.items():
        for path in paths:
            _validate_exact_path(root, commit, path)
    path_sync = document.get("pathSync", {})
    _require(path_sync.get("canonicalBrandPathCount") == 94, "brand count receipt drifted")
    _require(path_sync.get("exactCommonPathCount") == 47, "common count receipt drifted")
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

    corrections = document.get("corrections", {})
    auth_correction = corrections.get("authBinding", {})
    _require(
        auth_correction == {
            "sourceCommit": "c322cda1c968d15b09e8ac93364f885777b619e8",
            "path": "distribution/desktop/edition-browser-auth.v1.json",
            "blob": "2b314e9c13215f7d0c08c7c75a340261be6c7f40",
            "sha256": "0cde18e10ed10b68f66a9efb6ef229076dc22255b734337a1c98852015d22345",
            "identityBindingContractSha256": (
                "47531767aca4d529ceadecd22b25623f0aeb39ec65098c6944f06b0d358b079a"
            ),
        },
        "auth correction receipt drifted",
    )
    coexistence_sha = _sha256(root / "distribution/desktop/edition-coexistence.v1.json")
    auth = json.loads(
        (root / "distribution/desktop/edition-browser-auth.v1.json").read_text(encoding="utf-8")
    )
    _require(
        auth_correction["identityBindingContractSha256"]
        == auth.get("identityBinding", {}).get("contractSha256")
        == coexistence_sha,
        "auth binding correction is not exact",
    )
    auth_verifier_sync = corrections.get("authVerifierAtomicSync", {})
    _require(
        auth_verifier_sync.get("sourceCommit")
        == "ba1b44955a96b88dda50b7f7bd8b6db58ac91a75",
        "auth verifier source drifted",
    )
    _require(
        auth_verifier_sync.get("reviewedHead") == OBSERVED_HEAD,
        "auth verifier reviewed head drifted",
    )
    expected_auth_verifier_rows = {
        "distribution/schemas/desktop-edition-browser-auth.schema.json": (
            "57087ee0f3bd5d3f9fd99d69fbcf8a29b6d4b09e",
            "1d5a9c2a5ba3a4ebc77d8f35897e145d52f95f310a6a6d1ef0a59a8667fd1af2",
        ),
        "distribution/tools/desktop_edition_browser_auth.py": (
            "be2d864e7cd8db2c3a5788f515364c7cb0517bbf",
            "752661e552a0b2a07c007492b62c45319ab89d0a6ff985b3e317d324495fac56",
        ),
        "distribution/tests/test_desktop_edition_browser_auth.py": (
            "4a922be5189e7690b5bf1da4f21ed649ede292f9",
            "1e5e99ea095800a55365e181d42b65491702ac891e5a6d347a88b7200ee07a44",
        ),
    }
    auth_rows = auth_verifier_sync.get("paths", [])
    _require(
        [row.get("path") for row in auth_rows]
        == list(expected_auth_verifier_rows),
        "auth verifier migration order drifted",
    )
    for row in auth_rows:
        path = row["path"]
        blob, sha256 = expected_auth_verifier_rows[path]
        _require(row.get("blob") == blob, f"auth verifier blob drifted: {path}")
        _require(row.get("sha256") == sha256, f"auth verifier SHA drifted: {path}")
        _require(_git(root, "hash-object", "--", path) == blob, f"auth verifier drifted: {path}")
        _require(_sha256(root / path) == sha256, f"auth verifier bytes drifted: {path}")

    runtime_correction = corrections.get("runtimeModeAtomicReview", {})
    _require(
        runtime_correction.get("sourceCommit")
        == "b099ed00923e9f2b833f812ad79f1614529038de",
        "runtime correction source drifted",
    )
    _require(
        runtime_correction.get("exactTreeCommit") == OBSERVED_HEAD,
        "runtime correction exact tree drifted",
    )
    expected_runtime_rows = {
        "desktop/scripts/verify-nsis-template.ps1": (
            "0e1d94e8de358057cfd0d95bcc0ae332f8d71cf1",
            "d23770d685b3ac41679857e37d3c5e127929ad14b5eef5fc80de139f4dc83432",
        ),
        "desktop/src-tauri/nsis/runtime-mode.nsh": (
            "9af1787fa8607e725c4495fa14a5763de781a5a3",
            "daa73c6e7f6ea4e4cc05fda1c8602ef358d5e42e7daabf711d357144c600cbfa",
        ),
        "desktop/src-tauri/src/installer_handoff.rs": (
            "d6ed51beb4730264c835d0b77f10cd14ee448b89",
            "cee0a2cd6bbf889ed07951cfc640e52cb70dee91239237b77c5cec897e2e1663",
        ),
    }
    rows = runtime_correction.get("paths", [])
    _require(len(rows) == 3, "runtime correction path count drifted")
    for row in rows:
        path = row.get("path")
        _require(path in expected_runtime_rows, "runtime correction path drifted")
        blob, sha256 = expected_runtime_rows[path]
        _require(row.get("blob") == blob, f"runtime correction blob drifted: {path}")
        _require(row.get("sha256") == sha256, f"runtime correction SHA drifted: {path}")
        _require(_git(root, "hash-object", "--", path) == blob, f"runtime blob drifted: {path}")
        _require(_sha256(root / path) == sha256, f"runtime bytes drifted: {path}")

    _require(document.get("upstreamBlockers") == [], "resolved blocker was retained")

    verification = document.get("verification", {})
    _require(
        verification and all(value is True for value in verification.values()),
        "verification claim drifted",
    )
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
    expected_validated = {"authContractValidated", "nsisTemplateValidated"}
    for key, value in non_claims.items():
        _require(value is (key in expected_validated), f"release overclaim: {key}")
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
                "commonPaths": 47,
                "yellow2Ready": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
