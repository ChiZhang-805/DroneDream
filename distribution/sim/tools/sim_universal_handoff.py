#!/usr/bin/env python3
"""Verify the path-limited Universal handoff adopted by DroneDream SIM."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

OBSERVED_HEAD = "57b74f59ed4164ebefde623fa7f5102e5c24363f"
OBSERVED_TREE = "5d9b060d14e758ba558bb7d4c7a1c04822bde28d"
AUTH_REVIEWED_HEAD = "6f25bb5051794842a8dfc6d02d199c5f93afce7c"
RUNTIME_REVIEWED_HEAD = "6f25bb5051794842a8dfc6d02d199c5f93afce7c"
NSIS_IDENTITY_FIX_COMMIT = "a11fe7d09fceafaecf102a0cbfba49abb066a557"
RELEASE_BUILD_DRIVER_COMMIT = "f2858e3d2e39f493baab28368b77230e45dd199f"
FRONTEND_DIST_RESOLUTION_COMMIT = "d80f5f99309668d9d1cd50be51371efaa3c5491d"
LIFECYCLE_PREFERENCE_RESIDUE_COMMIT = "8215a2206ec5e1192792410aaaf2a438f6b6127f"
BRAND_PRODUCT = "b8e0d0c7093abe9f54fe36f01022deb95852fa39"

EXACT_GROUPS = {
    "2d19b045c11f5e78ae1a0b6554aee0d0ad382335": (
        "distribution/schemas/desktop-edition-coexistence.schema.json",
        "distribution/tools/desktop_edition_coexistence.py",
    ),
    "8a8ad6ce0ea619a52ec087b7f55142c24311165a": (
        "desktop/src-tauri/nsis/installer-languages.nsh",
        "desktop/src-tauri/nsis/languages/English.nsh",
        "desktop/src-tauri/nsis/languages/SimpChinese.nsh",
        "desktop/src-tauri/nsis/webview2-health.nsh",
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
        "desktop/scripts/verify-updater-build-contract.ps1",
        "desktop/scripts/write-updater-manifest.ps1",
        "desktop/src-tauri/src/app_update.rs",
        "desktop/src-tauri/src/lib.rs",
        "desktop/src-tauri/tauri.conf.json",
        "desktop/src-tauri/tauri.universal.conf.json",
    ),
    "c322cda1c968d15b09e8ac93364f885777b619e8": (
        "distribution/desktop/edition-browser-auth.v1.json",
    ),
    "b099ed00923e9f2b833f812ad79f1614529038de": (
        "desktop/src-tauri/nsis/runtime-mode.nsh",
        "desktop/src-tauri/src/installer_handoff.rs",
    ),
    NSIS_IDENTITY_FIX_COMMIT: (
        "desktop/scripts/verify-nsis-template.ps1",
        "desktop/src-tauri/nsis/edition-identity.nsh",
        "desktop/src-tauri/nsis/installer.nsi",
    ),
    OBSERVED_HEAD: (
        "desktop/scripts/verify-edition-identity-nsis.ps1",
    ),
    LIFECYCLE_PREFERENCE_RESIDUE_COMMIT: (
        "desktop/scripts/edition-installer-lifecycle-contract.ps1",
        "desktop/scripts/verify-universal-installer-lifecycle.ps1",
        "distribution/tests/test_desktop_edition_coexistence.py",
    ),
    RELEASE_BUILD_DRIVER_COMMIT: (
        "desktop/scripts/build-windows-llvm.ps1",
        "desktop/scripts/verify-release-source-policy.mjs",
        "desktop/scripts/verify-updater-signing-contract.ps1",
    ),
    FRONTEND_DIST_RESOLUTION_COMMIT: (
        "desktop/scripts/release-build-driver.psm1",
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


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


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
    _require(
        source.get("frontendDistResolutionCommit") == FRONTEND_DIST_RESOLUTION_COMMIT,
        "frontendDist resolution source drifted",
    )
    _require(
        source.get("lifecyclePreferenceResidueCommit")
        == LIFECYCLE_PREFERENCE_RESIDUE_COMMIT,
        "lifecycle preference residue source drifted",
    )
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
    _require(len(common_paths) == len(set(common_paths)) == 53, "common path inventory drifted")
    for commit, paths in EXACT_GROUPS.items():
        for path in paths:
            _validate_exact_path(root, commit, path)
    path_sync = document.get("pathSync", {})
    _require(path_sync.get("canonicalBrandPathCount") == 94, "brand count receipt drifted")
    _require(path_sync.get("exactCommonPathCount") == 53, "common count receipt drifted")
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
        auth_verifier_sync.get("reviewedHead") == AUTH_REVIEWED_HEAD,
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
        runtime_correction.get("exactTreeCommit") == RUNTIME_REVIEWED_HEAD,
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
        _require(
            _git(root, "rev-parse", f"{RUNTIME_REVIEWED_HEAD}:{path}") == blob,
            f"historical runtime blob drifted: {path}",
        )
        _require(
            hashlib.sha256(
                _git_bytes(root, "cat-file", "blob", f"{RUNTIME_REVIEWED_HEAD}:{path}")
            ).hexdigest()
            == sha256,
            f"historical runtime bytes drifted: {path}",
        )

    nsis_fix = corrections.get("nsisIdentityFix", {})
    _require(
        nsis_fix == {
            "sourceCommit": NSIS_IDENTITY_FIX_COMMIT,
            "parentCommit": AUTH_REVIEWED_HEAD,
            "changedPathCount": 5,
            "rootCause": "duplicate-expanded-desktop-done-label",
            "editionIdentityPreserved": True,
        },
        "NSIS identity fix receipt drifted",
    )
    lifecycle_fix = corrections.get("lifecycleRegistrationValidator", {})
    _require(
        lifecycle_fix == {
            "sourceCommit": OBSERVED_HEAD,
            "parentCommit": "8d60d3d15ca4d454acf5d92196deb63b0dd1314b",
            "changedPathCount": 3,
            "rootCause": "lifecycle-verifier-false-negative",
            "productNsisChanged": False,
            "simExecutionToolReplaced": False,
        },
        "lifecycle registration verifier receipt drifted",
    )
    build_driver = corrections.get("releaseBuildDriver", {})
    _require(
        build_driver.get("sourceCommit") == RELEASE_BUILD_DRIVER_COMMIT,
        "release build driver source drifted",
    )
    _require(
        build_driver.get("parentCommit")
        == "350253f8c17def231d81d39860846d1eb4ab1a94",
        "release build driver parent drifted",
    )
    expected_build_driver_rows = {
        "desktop/scripts/build-windows-llvm.ps1": (
            "f4287f19e96d734dd257ac1421b13677e53e208e",
            "4ac9b141b08aae39275d8538d06e11c711b0ce71c3f74ab7baccf11839d2f6dc",
        ),
        "desktop/scripts/verify-release-source-policy.mjs": (
            "7a0407872f7f24505b376ebfdd1e9f1646acf5ff",
            "97f643d67348ea11e80506e898302210dece51de1aee9cbf66ee55f839cf0d29",
        ),
        "desktop/scripts/verify-updater-signing-contract.ps1": (
            "b95edd472f9b328a92a279547aafca454aa201e1",
            "7a8b480f3fa268fd474c992b1a4d812f3221f4deb76ee06d37692aab3d785117",
        ),
    }
    build_driver_rows = build_driver.get("paths", [])
    _require(
        [row.get("path") for row in build_driver_rows]
        == list(expected_build_driver_rows),
        "release build driver path inventory drifted",
    )
    for row in build_driver_rows:
        path = row["path"]
        blob, object_sha256 = expected_build_driver_rows[path]
        _require(row.get("blob") == blob, f"release build driver blob drifted: {path}")
        _require(
            row.get("objectSha256") == object_sha256,
            f"release build driver object SHA drifted: {path}",
        )
        _require(
            _git(root, "rev-parse", f"{RELEASE_BUILD_DRIVER_COMMIT}:{path}") == blob,
            f"historical release build driver blob drifted: {path}",
        )
        _require(
            hashlib.sha256(
                _git_bytes(root, "cat-file", "blob", f"{RELEASE_BUILD_DRIVER_COMMIT}:{path}")
            ).hexdigest()
            == object_sha256,
            f"historical release build driver bytes drifted: {path}",
        )

    frontend_dist = corrections.get("frontendDistResolution", {})
    _require(
        frontend_dist.get("sourceCommit") == FRONTEND_DIST_RESOLUTION_COMMIT,
        "frontendDist resolution source drifted",
    )
    _require(
        frontend_dist.get("parentCommit") == RELEASE_BUILD_DRIVER_COMMIT,
        "frontendDist resolution parent drifted",
    )
    expected_frontend_dist_rows = {
        "desktop/scripts/release-build-driver.psm1": (
            "81b41137febb7a4ef8bdf86b97360b88f0904873",
            "c176773d35a789d54570620bc109364aa8ecf5004b41e6a5abdc149da839df57",
        ),
        "distribution/tests/test_shared_windows_build_contract.py": (
            "8f19fe61ae00c8d2358527fee87237da0a227bd7",
            "db6ca9f8459980c50bec870f91b72417c44e2aa85031f51c37a6a349a97cc957",
        ),
    }
    frontend_dist_rows = frontend_dist.get("paths", [])
    _require(
        [row.get("path") for row in frontend_dist_rows]
        == list(expected_frontend_dist_rows),
        "frontendDist resolution path inventory drifted",
    )
    for row in frontend_dist_rows:
        path = row["path"]
        blob, object_sha256 = expected_frontend_dist_rows[path]
        _require(row.get("blob") == blob, f"frontendDist resolution blob drifted: {path}")
        _require(
            row.get("objectSha256") == object_sha256,
            f"frontendDist resolution object SHA drifted: {path}",
        )
        _require(
            _git(root, "rev-parse", f"{FRONTEND_DIST_RESOLUTION_COMMIT}:{path}")
            == blob,
            f"historical frontendDist resolution blob drifted: {path}",
        )
        _require(
            hashlib.sha256(
                _git_bytes(
                    root,
                    "cat-file",
                    "blob",
                    f"{FRONTEND_DIST_RESOLUTION_COMMIT}:{path}",
                )
            ).hexdigest()
            == object_sha256,
            f"historical frontendDist resolution bytes drifted: {path}",
        )
    _require(
        frontend_dist.get("canonicalConfigPath")
        == "desktop/src-tauri/tauri.conf.json",
        "frontendDist canonical config path drifted",
    )
    _require(
        frontend_dist.get("overlayLocationChangesResolution") is False,
        "frontendDist overlay location overclaim",
    )
    _require(
        frontend_dist.get("absolutePathsRestrictedToEditionOutputs") is True,
        "frontendDist absolute path restriction drifted",
    )
    _require(
        frontend_dist.get("unknownEditionFailsClosed") is True,
        "frontendDist unknown edition gate drifted",
    )
    _require(
        frontend_dist.get("buildAuthorized") is False,
        "frontendDist donor authorized a build",
    )

    lifecycle_preference = corrections.get("lifecyclePreferenceResidue", {})
    _require(
        lifecycle_preference.get("sourceCommit")
        == LIFECYCLE_PREFERENCE_RESIDUE_COMMIT,
        "lifecycle preference residue source drifted",
    )
    _require(
        lifecycle_preference.get("parentCommit") == FRONTEND_DIST_RESOLUTION_COMMIT,
        "lifecycle preference residue parent drifted",
    )
    expected_lifecycle_preference_rows = {
        "desktop/scripts/edition-installer-lifecycle-contract.ps1": (
            "b06c557e33a0a3b78a2feab138e805ce795e65cc",
            "f2ca2c92a1a6b7f267041002d838599c550438e6ea4490970f94ca2c76d17d4e",
        ),
        "desktop/scripts/verify-universal-installer-lifecycle.ps1": (
            "e90fe02e3c739faedacb9fa3577af7e95463f9fb",
            "0931d4d328c51d780fc3fde3e8303fc8f7393cd70f76ef27f4874f6a978eb8a2",
        ),
        "distribution/tests/test_desktop_edition_coexistence.py": (
            "c2ef54fc554d71015aa581760faed2a8144829ff",
            "81b3ee200b0897d75a9d31050a0e962b1ce99c3c7819849fd8e263258f71c26f",
        ),
    }
    lifecycle_preference_rows = lifecycle_preference.get("simConsumedPaths", [])
    _require(
        [row.get("path") for row in lifecycle_preference_rows]
        == list(expected_lifecycle_preference_rows),
        "lifecycle preference residue path inventory drifted",
    )
    for row in lifecycle_preference_rows:
        path = row["path"]
        blob, object_sha256 = expected_lifecycle_preference_rows[path]
        _require(
            row.get("blob") == blob,
            f"lifecycle preference residue blob drifted: {path}",
        )
        _require(
            row.get("objectSha256") == object_sha256,
            f"lifecycle preference residue SHA drifted: {path}",
        )
        _require(
            _git(root, "rev-parse", f"{LIFECYCLE_PREFERENCE_RESIDUE_COMMIT}:{path}")
            == blob,
            f"historical lifecycle preference residue blob drifted: {path}",
        )
        _require(
            hashlib.sha256(
                _git_bytes(
                    root,
                    "cat-file",
                    "blob",
                    f"{LIFECYCLE_PREFERENCE_RESIDUE_COMMIT}:{path}",
                )
            ).hexdigest()
            == object_sha256,
            f"historical lifecycle preference residue bytes drifted: {path}",
        )
    _require(
        lifecycle_preference.get("universalOnlyTestPath")
        == "distribution/tests/test_universal_installer_contract.py"
        and lifecycle_preference.get("universalOnlyTestRestored") is False,
        "Universal-only lifecycle test boundary drifted",
    )
    _require(
        lifecycle_preference.get("productNsisChanged") is False
        and lifecycle_preference.get("frozenArtifactReuseAllowed") is False
        and lifecycle_preference.get("buildAuthorized") is False,
        "lifecycle preference residue execution overclaim",
    )

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
                "commonPaths": 52,
                "yellow2Ready": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
