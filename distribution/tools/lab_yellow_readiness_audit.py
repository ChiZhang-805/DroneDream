#!/usr/bin/env python3
"""Read-only Lab YELLOW preview build readiness audit.

This audit prepares a machine-readable request for a future YELLOW build
without invoking Tauri, NSIS, installers, simulators, hardware, providers, or
secret-bearing environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import lab_preinstall_acceptance as preinstall
import verify_lab_preview_artifact as artifact_verifier
import verify_lab_preview_contract as profile_verifier
import verify_lab_website_handoff as website_handoff_verifier


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "distribution/build-profiles/lab-preview.v1.json"
LAB_MANIFEST_PATH = ROOT / "distribution/editions/lab.v1.json"
BRAND_MANIFEST_PATH = ROOT / "distribution/editions/lab/brand-source-manifest.v1.json"
BRAND_DONOR_PATH = ROOT / "brand/brand-editions.v1.json"
TAURI_OVERLAY_PATH = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
REGISTRY_PATH = ROOT / "distribution/vehicle-packs/registry.v1.json"
GATE_POLICY_PATH = ROOT / "distribution/safety/edition-execution-gate.v1.json"
NOTICE_PATH = ROOT / "runtime/THIRD_PARTY_NOTICES.md"
SUPABASE_CLIENT_PATH = ROOT / "frontend/src/features/auth/supabaseClient.ts"
SUPABASE_ENV_EXAMPLE_PATH = ROOT / "frontend/.env.example"
WEBSITE_HANDOFF_PATH = website_handoff_verifier.CONTRACT_PATH
SUPABASE_DESKTOP_VERIFIER_PATH = ROOT / "desktop/scripts/verify-browser-auth-config.mjs"

COMMON_CORE_PRODUCT_SOURCE_COMMIT = artifact_verifier.COMMON_CORE_PRODUCT_SOURCE_COMMIT
EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT = artifact_verifier.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT
CANONICAL_BRAND_DONOR_COMMIT = "b8e0d0c7093abe9f54fe36f01022deb95852fa39"
COMMON_CORE_PATHS = ("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")
HARDWARE_ACTIONS = (
    "hardware.parameter.write",
    "hardware.arm",
    "hardware.flight",
    "hardware.hitl.execute",
)


class LabYellowReadinessError(ValueError):
    """Raised when the readiness audit cannot be evaluated safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabYellowReadinessError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LabYellowReadinessError(f"{path} must contain a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_version_command(arguments: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        return {"available": False, "output": "", "error": str(exc)}
    output = "\n".join(
        value.strip() for value in (completed.stdout, completed.stderr) if value.strip()
    )
    return {
        "available": completed.returncode == 0,
        "output": output,
        "error": None if completed.returncode == 0 else f"exit {completed.returncode}",
    }


def _pinned_file(path: Path | None, expected: dict[str, Any]) -> dict[str, Any]:
    exists = path is not None and path.is_file()
    observed_bytes = path.stat().st_size if exists else None
    observed_sha256 = _sha256_file(path) if exists else None
    return {
        "path": str(path) if path is not None else None,
        "available": exists,
        "bytes": observed_bytes,
        "sha256": observed_sha256,
        "expectedBytes": expected["bytes"],
        "expectedSha256": expected["sha256"],
        "matchesPin": (
            exists
            and observed_bytes == expected["bytes"]
            and observed_sha256 == expected["sha256"]
        ),
    }


def _git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise LabYellowReadinessError(detail)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _git_success(*args: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.returncode == 0


def _file_ref(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256_file(path)}


def _source_state() -> dict[str, Any]:
    return {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "--verify", "HEAD"),
        "upstream": _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"),
        "statusPorcelain": _git("status", "--porcelain=v1", "--untracked-files=all"),
    }


def _common_core_binding() -> dict[str, Any]:
    observed_origin = _git("rev-parse", "--verify", "origin/codex/software", check=False)
    product_hash = artifact_verifier.common_core_hash(COMMON_CORE_PRODUCT_SOURCE_COMMIT)
    excluded_hash = artifact_verifier.common_core_hash(EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT)
    return {
        "authorityName": "Universal/Core",
        "authorityBranch": "codex/software",
        "productSourceCommit": COMMON_CORE_PRODUCT_SOURCE_COMMIT,
        "productSourceExists": _git_success(
            "cat-file", "-e", f"{COMMON_CORE_PRODUCT_SOURCE_COMMIT}^{{commit}}"
        ),
        "productSourceIsAncestorOfLabHead": _git_success(
            "merge-base", "--is-ancestor", COMMON_CORE_PRODUCT_SOURCE_COMMIT, "HEAD"
        ),
        "productCommonCoreHash": product_hash,
        "excludedSimPreviewEvidenceCommit": EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT,
        "excludedSimPreviewEvidenceHash": excluded_hash,
        "observedOriginSoftwareHead": observed_origin,
        "observedOriginHeadIsProductSource": observed_origin == COMMON_CORE_PRODUCT_SOURCE_COMMIT,
        "sameCommonCoreInventoryAsExcludedEvidence": product_hash == excluded_hash,
        "commonCorePaths": list(COMMON_CORE_PATHS),
    }


def _supabase_public_config_source() -> dict[str, Any]:
    env_example = SUPABASE_ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    client = SUPABASE_CLIENT_PATH.read_text(encoding="utf-8")
    verifier = SUPABASE_DESKTOP_VERIFIER_PATH.read_text(encoding="utf-8")
    return {
        "envExample": _file_ref(SUPABASE_ENV_EXAMPLE_PATH),
        "clientSource": _file_ref(SUPABASE_CLIENT_PATH),
        "desktopVerifier": _file_ref(SUPABASE_DESKTOP_VERIFIER_PATH),
        "sourceUsesVitePublicEnv": (
            "import.meta.env.VITE_SUPABASE_URL" in client
            and "import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY" in client
        ),
        "envExampleLeavesPublicValuesBlank": (
            "VITE_SUPABASE_URL=\n" in env_example
            and "VITE_SUPABASE_PUBLISHABLE_KEY=\n" in env_example
        ),
        "desktopVerifierRejectsServiceRole": (
            'EXPECTED_ACCOUNT_URL = "https://yggabfynndpzymlqvnim.supabase.co"' in verifier
            and 'decodedJwtRole(publishableKey) === "service_role"' in verifier
            and "sb_secret_" in verifier
        ),
        "actualEnvironmentRead": False,
        "secretMaterialRequiredForAudit": False,
    }


def _vehicle_pack_state() -> dict[str, Any]:
    registry = _load_json(REGISTRY_PATH)
    packs = registry.get("packs")
    if not isinstance(packs, list):
        raise LabYellowReadinessError("vehicle pack registry packs must be a list")
    validated = [
        pack["packId"]
        for pack in packs
        if isinstance(pack, dict)
        and pack.get("currentValidationStatus") == "validated"
        and pack.get("currentValidationTier") == "validated"
    ]
    selected = next(
        pack for pack in packs if isinstance(pack, dict) and pack.get("packId") == "holybro-s500-v2-pixhawk6c"
    )
    return {
        "registry": _file_ref(REGISTRY_PATH),
        "totalPacks": len(packs),
        "validatedPackCount": len(validated),
        "validatedPacks": validated,
        "selectedLabPackId": selected["packId"],
        "selectedLabPackValidationStatus": selected["currentValidationStatus"],
        "selectedLabPackValidationTier": selected["currentValidationTier"],
    }


def _brand_state() -> dict[str, Any]:
    manifest = _load_json(BRAND_MANIFEST_PATH)
    donor = _load_json(BRAND_DONOR_PATH)
    overlay = _load_json(TAURI_OVERLAY_PATH)
    assets = manifest.get("assets")
    derivatives = manifest.get("derivation", {}).get("assets")
    if not isinstance(assets, list) or not isinstance(derivatives, list):
        raise LabYellowReadinessError("Lab brand source or derivative assets are missing")

    refs = []
    for entry in [*assets, *derivatives]:
        if not isinstance(entry, dict):
            raise LabYellowReadinessError("Lab brand asset entry must be an object")
        repository_path = entry.get("repositoryPath")
        expected_sha256 = entry.get("repositorySha256", entry.get("sha256"))
        if not isinstance(repository_path, str) or not isinstance(expected_sha256, str):
            raise LabYellowReadinessError("Lab brand asset binding is incomplete")
        path = ROOT / repository_path
        refs.append(
            {
                "path": repository_path,
                "sha256": _sha256_file(path),
                "matchesManifest": _sha256_file(path) == expected_sha256,
            }
        )

    expected_icons = [
        f"../../{entry['repositoryPath']}"
        for entry in derivatives
        if isinstance(entry, dict)
    ]
    integration = manifest.get("integration")
    theme = manifest.get("theme")
    source_authority = manifest.get("sourceAuthority")
    merge_head = _git("rev-parse", "--verify", "MERGE_HEAD", check=False)
    donor_is_ancestor = _git_success(
        "merge-base", "--is-ancestor", CANONICAL_BRAND_DONOR_COMMIT, "HEAD"
    ) or merge_head == CANONICAL_BRAND_DONOR_COMMIT
    donor_paths = tuple(
        path
        for path in _git(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            CANONICAL_BRAND_DONOR_COMMIT,
        ).splitlines()
        if path
    )
    donor_paths_match = bool(donor_paths) and _git_success(
        "diff",
        "--quiet",
        CANONICAL_BRAND_DONOR_COMMIT,
        "HEAD",
        "--",
        *donor_paths,
    )
    donor_is_integrated = donor_is_ancestor or donor_paths_match
    ready = (
        manifest.get("displayName") == "DroneDream · LAB"
        and isinstance(source_authority, dict)
        and source_authority.get("donorCommit") == CANONICAL_BRAND_DONOR_COMMIT
        and source_authority.get("canonicalContract", {}).get("sha256")
        == _sha256_file(BRAND_DONOR_PATH)
        and donor.get("editions", {}).get("lab", {}).get("productName")
        == "DroneDream · LAB"
        and donor.get("safety", {}).get("grantsHardwareAuthority") is False
        and donor.get("approval", {}).get("editionLabelHeightRatio") == 0.9
        and donor.get("approval", {}).get("preserveNaturalLabelWidth") is True
        and donor_is_integrated
        and isinstance(theme, dict)
        and theme.get("palette") == ["#A7E84A", "#20C77A", "#087E69"]
        and theme.get("grantsHardwareAuthority") is False
        and all(ref["matchesManifest"] for ref in refs)
        and overlay.get("productName") == "DroneDream · LAB"
        and overlay.get("bundle", {}).get("icon") == expected_icons
        and isinstance(integration, dict)
        and integration.get("application")
        == "canonical-large-label-lockup-selected-by-lab-gate"
        and integration.get("installer") == "canonical-lab-icon-bound-in-overlay-not-built"
        and integration.get("shortcut") == "canonical-lab-executable-icon-bound-not-built"
    )
    return {
        "sourceManifest": _file_ref(BRAND_MANIFEST_PATH),
        "canonicalDonor": {
            "commit": CANONICAL_BRAND_DONOR_COMMIT,
            "file": _file_ref(BRAND_DONOR_PATH),
            "integrated": donor_is_integrated,
            "isAncestor": donor_is_ancestor,
            "exactChangedPathsMatch": donor_paths_match,
            "integrationMode": (
                "ancestor" if donor_is_ancestor else "audited-authorized-cherry-pick"
            ),
        },
        "tauriOverlay": _file_ref(TAURI_OVERLAY_PATH),
        "displayName": manifest.get("displayName"),
        "palette": theme.get("palette") if isinstance(theme, dict) else None,
        "grantsHardwareAuthority": (
            theme.get("grantsHardwareAuthority") if isinstance(theme, dict) else None
        ),
        "assets": refs,
        "readyForYellowBuild": ready,
    }


def _toolchain_state(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile if profile is not None else _load_json(PROFILE_PATH)
    policy = profile.get("toolchainPolicy")
    if not isinstance(policy, dict):
        raise LabYellowReadinessError("Lab toolchain policy is missing")

    rust_policy = policy["rust"]
    llvm_policy = policy["llvmMingw"]
    loader_policy = policy["webView2Loader"]
    tauri_policy = policy["tauriCli"]
    nsis_policy = policy["nsis"]
    environment_policy = policy["environment"]

    rustup_path = shutil.which("rustup.exe") or shutil.which("rustup")
    rust_toolchain = rust_policy["rustupToolchain"]
    rustc = (
        _run_version_command([rustup_path, "run", rust_toolchain, "rustc", "-vV"])
        if rustup_path
        else {"available": False, "output": "", "error": "rustup unavailable"}
    )
    cargo = (
        _run_version_command([rustup_path, "run", rust_toolchain, "cargo", "-Vv"])
        if rustup_path
        else {"available": False, "output": "", "error": "rustup unavailable"}
    )
    rustc["matchesPin"] = rustc["available"] and all(
        marker in rustc["output"]
        for marker in (
            f"release: {rust_policy['rustcVersion']}",
            f"commit-hash: {rust_policy['rustcCommitHash']}",
            f"commit-date: {rust_policy['rustcCommitDate']}",
            f"host: {policy['targetTriple']}",
            f"LLVM version: {rust_policy['llvmVersion']}",
        )
    )
    cargo["matchesPin"] = cargo["available"] and all(
        marker in cargo["output"]
        for marker in (
            f"release: {rust_policy['cargoVersion']}",
            f"commit-hash: {rust_policy['cargoCommitHash']}",
            f"commit-date: {rust_policy['cargoCommitDate']}",
            f"host: {policy['targetTriple']}",
        )
    )

    local_app_data = os.environ.get("LOCALAPPDATA")
    package_root = (
        Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if local_app_data
        else None
    )
    llvm_roots: list[Path] = []
    if package_root and package_root.is_dir():
        for package in package_root.glob("MartinStorsjo.LLVM-MinGW.UCRT_*"):
            candidate = package / llvm_policy["packageDirectoryName"]
            if candidate.is_dir():
                llvm_roots.append(candidate)
    llvm_root = llvm_roots[0] if len(llvm_roots) == 1 else None
    llvm_tools = {
        expected["name"]: _pinned_file(
            llvm_root / "bin" / expected["name"] if llvm_root else None,
            expected,
        )
        for expected in llvm_policy["requiredTools"]
    }
    clang = llvm_tools["x86_64-w64-mingw32-clang.exe"]
    clang_version = (
        _run_version_command([clang["path"], "--version"])
        if clang["available"]
        else {"available": False, "output": "", "error": "pinned clang unavailable"}
    )
    clang_version["matchesPin"] = clang_version["available"] and all(
        marker in clang_version["output"]
        for marker in (
            f"clang version {llvm_policy['clangVersion']}",
            f"Target: {llvm_policy['clangTarget']}",
        )
    )

    user_profile = os.environ.get("USERPROFILE")
    loader_candidates: list[Path] = []
    if user_profile:
        registry_sources = Path(user_profile) / ".cargo" / "registry" / "src"
        loader_candidates = list(
            registry_sources.glob(
                f"*/{loader_policy['cargoPackage']}-{loader_policy['cargoPackageVersion']}/"
                + loader_policy["relativePath"]
            )
        )
    loader_path = loader_candidates[0] if len(loader_candidates) == 1 else None
    loader = _pinned_file(loader_path, loader_policy)

    tauri_package_path = ROOT / tauri_policy["packagePath"]
    tauri_entrypoint_path = ROOT / tauri_policy["entrypointPath"]
    tauri_package_version = None
    if tauri_package_path.is_file():
        try:
            tauri_package_version = _load_json(tauri_package_path).get("version")
        except LabYellowReadinessError:
            tauri_package_version = None
    tauri_entrypoint = _pinned_file(
        tauri_entrypoint_path,
        {
            "bytes": tauri_policy["entrypointBytes"],
            "sha256": tauri_policy["entrypointSha256"],
        },
    )
    tauri = {
        "packagePath": str(tauri_package_path),
        "observedVersion": tauri_package_version,
        "expectedVersion": tauri_policy["version"],
        "entrypoint": tauri_entrypoint,
        "matchesPin": (
            tauri_package_version == tauri_policy["version"]
            and tauri_entrypoint["matchesPin"]
        ),
    }

    nsis_path = (
        Path(local_app_data)
        / Path(nsis_policy["cacheRelativeToLocalAppData"])
        / Path(nsis_policy["executableRelativePath"])
        if local_app_data
        else None
    )
    nsis = _pinned_file(nsis_path, {
        "bytes": nsis_policy["executableBytes"],
        "sha256": nsis_policy["executableSha256"],
    })
    nsis["invoked"] = False

    node_path = shutil.which("node.exe") or shutil.which("node")
    npm_path = shutil.which("npm.cmd") or shutil.which("npm")
    node_version = (
        _run_version_command([node_path, "--version"])
        if node_path
        else {"available": False, "output": "", "error": "node unavailable"}
    )
    npm_version = (
        _run_version_command([npm_path, "--version"])
        if npm_path
        else {"available": False, "output": "", "error": "npm unavailable"}
    )

    gnullvm_blockers: list[str] = []
    if not rustc["matchesPin"]:
        gnullvm_blockers.append("pinned Rust 1.97.0 gnullvm rustc is unavailable or drifted")
    if not cargo["matchesPin"]:
        gnullvm_blockers.append("pinned Rust 1.97.0 gnullvm Cargo is unavailable or drifted")
    if len(llvm_roots) != 1:
        gnullvm_blockers.append("exactly one pinned LLVM-MinGW UCRT package root is required")
    if not all(tool["matchesPin"] for tool in llvm_tools.values()):
        gnullvm_blockers.append("one or more pinned LLVM-MinGW tool bytes drifted")
    if not clang_version["matchesPin"]:
        gnullvm_blockers.append("pinned LLVM-MinGW clang version or target drifted")
    if not loader["matchesPin"]:
        gnullvm_blockers.append("locked WebView2Loader.dll is unavailable or drifted")
    if not tauri["matchesPin"]:
        gnullvm_blockers.append("pinned Tauri CLI package or entrypoint drifted")
    if not nsis["matchesPin"]:
        gnullvm_blockers.append("pinned cached NSIS executable is unavailable or drifted")
    if not node_version["available"] or not npm_version["available"]:
        gnullvm_blockers.append("Node.js or npm is unavailable")

    expected_cargo_target = Path(environment_policy["cargoTargetDir"])
    repository_target = ROOT / "desktop" / "src-tauri" / "target"
    try:
        cargo_target_is_repository = expected_cargo_target.resolve().is_relative_to(
            repository_target.resolve()
        )
    except OSError:
        cargo_target_is_repository = False
    if cargo_target_is_repository:
        gnullvm_blockers.append("Lab Cargo target resolves inside the repository target")

    strict_ready = not gnullvm_blockers
    rustc_path = shutil.which("rustc.exe") or shutil.which("rustc")
    cargo_path = shutil.which("cargo.exe") or shutil.which("cargo")
    default_rust = (
        _run_version_command([rustc_path, "-vV"])
        if rustc_path
        else {"available": False, "output": "", "error": "rustc unavailable"}
    )
    default_host = next(
        (
            line.removeprefix("host: ")
            for line in default_rust["output"].splitlines()
            if line.startswith("host: ")
        ),
        None,
    )
    required_msvc_linker = "link.exe" if default_host and default_host.endswith("-msvc") else None
    msvc_linker_path = shutil.which(required_msvc_linker) if required_msvc_linker else None
    msvc_ready = (
        default_rust["available"]
        and cargo_path is not None
        and required_msvc_linker is not None
        and msvc_linker_path is not None
    )

    return {
        "selectedToolchain": "gnullvm" if strict_ready else ("msvc" if msvc_ready else None),
        "selectionPolicy": policy["selection"],
        "strictPinnedToolchainReady": strict_ready,
        "candidates": {
            "gnullvm": {
                "targetTriple": policy["targetTriple"],
                "rustupToolchain": rust_toolchain,
                "rustupPath": rustup_path,
                "rustc": rustc,
                "cargo": cargo,
                "llvmRoot": str(llvm_root) if llvm_root else None,
                "llvmRootCandidates": [str(path) for path in llvm_roots],
                "llvmTools": llvm_tools,
                "clangVersion": clang_version,
                "webView2Loader": loader,
                "tauriCli": tauri,
                "nsis": nsis,
                "requiresMsvcLinkExe": False,
                "strictlyPinnedReady": strict_ready,
                "blockers": gnullvm_blockers,
            },
            "msvc": {
                "rustcAvailable": default_rust["available"],
                "cargoAvailable": cargo_path is not None,
                "rustHost": default_host,
                "requiredLinker": required_msvc_linker,
                "linkerAvailable": msvc_linker_path is not None,
                "linkerPath": msvc_linker_path,
                "ready": msvc_ready,
            },
        },
        "environment": {
            "node": {"path": node_path, **node_version},
            "npm": {"path": npm_path, **npm_version},
            "expectedCargoTargetDir": expected_cargo_target.as_posix(),
            "repositoryCargoTargetDir": repository_target.as_posix(),
            "cargoTargetIsRepositoryTarget": cargo_target_is_repository,
            "cargoBuildJobsMaximum": environment_policy["cargoBuildJobsMaximum"],
            "rustflags": environment_policy["rustflags"],
            "additionalConfigTransport": environment_policy["additionalConfigTransport"],
        },
        "tauriInvoked": False,
        "nsisInvoked": False,
    }


def _safety_state(profile: dict[str, Any]) -> dict[str, Any]:
    gate = _load_json(GATE_POLICY_PATH)
    safety = profile["safetyPolicy"]
    preinstall_result = preinstall.evaluate_preinstall()
    return {
        "executionGatePolicy": _file_ref(GATE_POLICY_PATH),
        "profileSafetyPolicy": safety,
        "preinstallDecision": preinstall_result["decision"],
        "preinstallSideEffects": preinstall_result["sideEffects"],
        "zeroValidatedPackDecision": gate["editionBoundaries"]["zeroValidatedPackDecision"],
        "hardwareActionsRequireValidatedSignedPack": gate["editionBoundaries"][
            "hardwareActionsRequireValidatedSignedPack"
        ],
        "quorumRequiredLayers": gate["quorum"]["requiredLayers"],
        "frontendAcceptedAsAuthority": gate["quorum"]["frontendReceiptAccepted"],
        "hardwareActions": list(HARDWARE_ACTIONS),
        "hardwareActionDecisionAtZeroValidatedPacks": "deny",
    }


def evaluate_readiness(
    *,
    require_clean: bool = True,
    toolchain_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the Lab YELLOW build request readiness audit as JSON data."""

    profile = _load_json(PROFILE_PATH)
    manifest = _load_json(LAB_MANIFEST_PATH)
    source = _source_state()
    common_core = _common_core_binding()
    supabase = _supabase_public_config_source()
    vehicle_packs = _vehicle_pack_state()
    brand = _brand_state()
    toolchain = toolchain_state if toolchain_state is not None else _toolchain_state(profile)
    safety = _safety_state(profile)
    profile_result = profile_verifier.verify_lab_preview_contract()
    website_handoff = website_handoff_verifier.validate_handoff(
        _load_json(WEBSITE_HANDOFF_PATH),
        verify_files=False,
        require_release_ready=False,
    )

    request_blockers: list[str] = []
    if source["branch"] != "codex/software-lab":
        request_blockers.append("source branch is not codex/software-lab")
    if source["upstream"] != "origin/codex/software-lab":
        request_blockers.append("upstream is not origin/codex/software-lab")
    if require_clean and source["statusPorcelain"]:
        request_blockers.append("source tree is not clean")
    if not common_core["productSourceExists"]:
        request_blockers.append("Universal/Core product source commit is unavailable")
    if not common_core["productSourceIsAncestorOfLabHead"]:
        request_blockers.append("Lab source does not descend from the Universal/Core product source")
    if not supabase["sourceUsesVitePublicEnv"] or not supabase["desktopVerifierRejectsServiceRole"]:
        request_blockers.append("public Supabase client configuration source is not closed")
    if vehicle_packs["validatedPackCount"] != 0:
        request_blockers.append("validated Vehicle Pack count drifted from zero")
    if safety["zeroValidatedPackDecision"] != "deny":
        request_blockers.append("zero-validated-pack hardware decision is not deny")
    if not brand["readyForYellowBuild"]:
        request_blockers.append("Lab brand source, application, or installer binding drifted")
    if toolchain.get("selectedToolchain") != "gnullvm":
        gnullvm = toolchain.get("candidates", {}).get("gnullvm", {})
        gnullvm_blockers = gnullvm.get("blockers", [])
        request_blockers.extend(
            f"strict pinned gnullvm: {blocker}" for blocker in gnullvm_blockers
        )
        if not gnullvm_blockers:
            request_blockers.append("strict pinned gnullvm toolchain is not ready")

    post_build_blockers = [
        "No Lab preview EXE has been built by this GREEN audit.",
        "No real Lab artifact receipt exists for installation acceptance.",
        "Lab preview remains unsigned internal-test material until YELLOW build evidence exists.",
        "There are zero validated Vehicle Packs; hardware write, arm, HITL, and flight stay denied.",
        "No codex/release-lab branch or production promotion is authorized by this audit.",
        "Website exact artifact remains not release-ready until validation, publication, and cross-Edition evidence are complete.",
    ]

    return {
        "schemaVersion": 1,
        "kind": "dronedream-lab-yellow-readiness-audit",
        "auditMode": "green-read-only",
        "editionId": "lab",
        "productDisplayVersion": "1.0.0",
        "buildArtifactFileName": "DroneDream-Lab-1.0.0.exe",
        "source": source,
        "commonCore": common_core,
        "labManifest": {
            "file": _file_ref(LAB_MANIFEST_PATH),
            "displayName": manifest["displayName"],
            "description": manifest["description"],
            "implementationStatus": manifest["implementationStatus"],
            "validationTier": manifest["validationTier"],
        },
        "profile": {"file": _file_ref(PROFILE_PATH), "verified": profile_result},
        "websiteExactExeHandoff": {
            "file": _file_ref(WEBSITE_HANDOFF_PATH),
            "receiverSourceCommit": website_handoff["receiver"]["websiteSourceCommit"],
            "receiverEvidenceCommit": website_handoff["receiver"]["websiteEvidenceCommit"],
            "state": website_handoff["state"],
            "fileName": website_handoff["edition"]["fileName"],
            "releaseReady": website_handoff["releaseReady"],
        },
        "brand": brand,
        "toolchain": toolchain,
        "workspaceContract": profile["workspaces"],
        "publicSupabaseClientConfigSource": supabase,
        "licenseNotice": _file_ref(NOTICE_PATH),
        "vehiclePacks": vehicle_packs,
        "safety": safety,
        "sideEffects": {
            "tauri": False,
            "nsis": False,
            "install": False,
            "hardwareProbe": False,
            "px4Gazebo": False,
            "readApiKey": False,
            "readProviderSecrets": False,
            "createReleaseBranch": False,
        },
        "yellowBuildRequest": {
            "requestable": not request_blockers,
            "classification": "YELLOW",
            "requiresControllerApprovalBeforeBuild": True,
            "requestedCommand": "powershell -NoProfile -ExecutionPolicy Bypass -File desktop\\scripts\\build-lab-preview.ps1 -Build -Toolchain gnullvm",
            "expectedReceiptKind": "dronedream-lab-preview-artifact-receipt",
            "requestBlockers": request_blockers,
        },
        "postBuildAcceptance": {
            "installableNow": False,
            "blockers": post_build_blockers,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="for unit tests only; the CLI still records the dirty state in JSON",
    )
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        result = evaluate_readiness(require_clean=not args.allow_dirty)
    except (LabYellowReadinessError, profile_verifier.LabPreviewContractError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
