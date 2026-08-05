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
import subprocess
import sys
from pathlib import Path
from typing import Any

import lab_preinstall_acceptance as preinstall
import verify_lab_preview_artifact as artifact_verifier
import verify_lab_preview_contract as profile_verifier


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "distribution/build-profiles/lab-preview.v1.json"
LAB_MANIFEST_PATH = ROOT / "distribution/editions/lab.v1.json"
REGISTRY_PATH = ROOT / "distribution/vehicle-packs/registry.v1.json"
GATE_POLICY_PATH = ROOT / "distribution/safety/edition-execution-gate.v1.json"
NOTICE_PATH = ROOT / "runtime/THIRD_PARTY_NOTICES.md"
SUPABASE_CLIENT_PATH = ROOT / "frontend/src/features/auth/supabaseClient.ts"
SUPABASE_ENV_EXAMPLE_PATH = ROOT / "frontend/.env.example"
SUPABASE_DESKTOP_VERIFIER_PATH = ROOT / "desktop/scripts/verify-browser-auth-config.mjs"

COMMON_CORE_PRODUCT_SOURCE_COMMIT = artifact_verifier.COMMON_CORE_PRODUCT_SOURCE_COMMIT
EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT = artifact_verifier.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT
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


def evaluate_readiness(*, require_clean: bool = True) -> dict[str, Any]:
    """Return the Lab YELLOW build request readiness audit as JSON data."""

    profile = _load_json(PROFILE_PATH)
    manifest = _load_json(LAB_MANIFEST_PATH)
    source = _source_state()
    common_core = _common_core_binding()
    supabase = _supabase_public_config_source()
    vehicle_packs = _vehicle_pack_state()
    safety = _safety_state(profile)
    profile_result = profile_verifier.verify_lab_preview_contract()

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

    post_build_blockers = [
        "No Lab preview EXE has been built by this GREEN audit.",
        "No real Lab artifact receipt exists for installation acceptance.",
        "Lab preview remains unsigned internal-test material until YELLOW build evidence exists.",
        "There are zero validated Vehicle Packs; hardware write, arm, HITL, and flight stay denied.",
        "No codex/release-lab branch or production promotion is authorized by this audit.",
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
            "requestedCommand": "powershell -NoProfile -ExecutionPolicy Bypass -File desktop\\scripts\\build-lab-preview.ps1 -Build",
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
