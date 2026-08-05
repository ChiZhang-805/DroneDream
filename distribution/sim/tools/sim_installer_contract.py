#!/usr/bin/env python3
"""Validate DroneDream Sim build-profile and installer adoption receipts.

This verifier is intentionally read-only. It never invokes Tauri, NSIS, PX4,
Gazebo, release-branch mutation, deployment, or Runtime migration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_PATH_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"
)

PROFILE_KEYS = {
    "schemaVersion",
    "kind",
    "profileVersion",
    "editionId",
    "artifact",
    "source",
    "manifests",
    "deterministicPayload",
    "installerPlan",
    "acceptance",
    "resourceProtocol",
}
PROFILE_ARTIFACT_KEYS = {"fileName", "productVersion", "targetArchitecture", "packaging"}
PROFILE_SOURCE_KEYS = {
    "editionBranch",
    "commonCoreBranch",
    "commonCoreCommit",
    "commonCoreHash",
    "commonCorePaths",
    "sourceCommitPolicy",
    "sourceTreeRequired",
}
PROFILE_MANIFEST_KEYS = {"edition", "capabilityPolicy", "vehiclePacks", "licenseNotice"}
FILE_REF_KEYS = {"path", "sha256"}
LICENSE_REF_KEYS = {"path", "sha256", "sizeBytes"}
PROFILE_PACK_REF_KEYS = {"packId", "path", "sha256", "payloadSha256", "requiredSimulationOnly"}
PROFILE_PAYLOAD_KEYS = {
    "ordering",
    "allowedModules",
    "forbiddenModules",
    "allowedCapabilities",
    "forbiddenCapabilities",
    "allowedVehiclePacks",
    "forbiddenEditionIds",
    "forbiddenCommandFragments",
}
PROFILE_INSTALLER_KEYS = {
    "outputReceiptKind",
    "receiptSchemaPath",
    "unsignedAllowed",
    "unsignedDisclosureRequired",
    "upgradePolicy",
    "rollbackPolicy",
    "uninstallPolicy",
    "releaseBranch",
    "releaseBranchState",
    "universalHandoffRequired",
}
PROFILE_ACCEPTANCE_KEYS = {"exactArtifactRequiredFields", "rejectIf", "adoptionVerifier"}
PROFILE_RESOURCE_KEYS = {
    "currentWorkClass",
    "ordinaryCompileClass",
    "realPx4GazeboStabilityClass",
    "apiKeyUseAllowed",
    "deployAllowed",
    "runtimeMigrationAllowed",
    "buildAllowed",
    "cargoTargetDir",
}

RECEIPT_KEYS = {
    "schemaVersion",
    "kind",
    "receiptVersion",
    "editionId",
    "profile",
    "source",
    "artifact",
    "payload",
    "licenseNotice",
    "installLifecycle",
    "handoff",
}
RECEIPT_PROFILE_KEYS = {"path", "sha256"}
RECEIPT_SOURCE_KEYS = {
    "sourceCommit",
    "sourceTreeState",
    "commonCoreCommit",
    "commonCoreHash",
}
RECEIPT_ARTIFACT_KEYS = {
    "fileName",
    "sha256",
    "bytes",
    "authenticodeState",
    "unsignedDisclosure",
    "updaterSignatureState",
}
RECEIPT_PAYLOAD_KEYS = {"modules", "capabilities", "vehiclePacks", "commandAudit"}
COMMAND_AUDIT_KEYS = {"scannedCommandCount", "observedCommands", "forbiddenFindings"}
INSTALL_LIFECYCLE_KEYS = {"upgradePlan", "rollbackPlan", "uninstallPlan"}
HANDOFF_KEYS = {
    "universalReceiptSha256",
    "universalArtifactSha256",
    "universalSourceCommit",
    "acceptedBy",
}

COMMON_CORE_PATHS = ("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")


class SimInstallerContractError(ValueError):
    """Raised when a Sim installer contract would overstate the artifact."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimInstallerContractError(f"could not read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SimInstallerContractError(f"JSON document must be an object: {path}")
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SimInstallerContractError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise SimInstallerContractError(
            f"{label} keys drifted (missing={sorted(expected - actual)}, extra={sorted(actual - expected)})"
        )
    return value


def _safe_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_PATH_RE.fullmatch(value):
        raise SimInstallerContractError(f"{label} is not a safe repository-relative path")
    return value


def _resolve(root: Path, value: Any, label: str) -> Path:
    relative = _safe_path(value, label)
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise SimInstallerContractError(f"{label} escapes repository root") from exc
    if not candidate.is_file():
        raise SimInstallerContractError(f"{label} does not exist: {relative}")
    return candidate


def _nonempty_string_list(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(set(value)) != len(value)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise SimInstallerContractError(f"{label} must be a non-empty unique string list")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SimInstallerContractError(f"{label} is not a SHA-256 digest")
    return value


def _commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise SimInstallerContractError(f"{label} is not a Git commit")
    return value


def _validate_file_ref(ref: Any, root: Path, label: str) -> dict[str, Any]:
    ref = _exact_keys(ref, FILE_REF_KEYS, label)
    path = _resolve(root, ref["path"], f"{label}.path")
    if sha256_file(path) != _sha(ref["sha256"], f"{label}.sha256"):
        raise SimInstallerContractError(f"{label} SHA-256 drifted")
    return ref


def _validate_license_ref(ref: Any, root: Path, label: str) -> dict[str, Any]:
    ref = _exact_keys(ref, LICENSE_REF_KEYS, label)
    path = _resolve(root, ref["path"], f"{label}.path")
    if sha256_file(path) != _sha(ref["sha256"], f"{label}.sha256"):
        raise SimInstallerContractError(f"{label} SHA-256 drifted")
    size = ref["sizeBytes"]
    if not isinstance(size, int) or size <= 0 or size != path.stat().st_size:
        raise SimInstallerContractError(f"{label}.sizeBytes drifted")
    return ref


def validate_build_profile(document: Any, *, repo_root: Path) -> dict[str, Any]:
    profile = _exact_keys(document, PROFILE_KEYS, "Sim build profile")
    if (
        profile["schemaVersion"] != 1
        or profile["kind"] != "dronedream-sim-build-profile"
        or profile["profileVersion"] != "1.0.0"
        or profile["editionId"] != "sim"
    ):
        raise SimInstallerContractError("Sim build profile identity is unsupported")

    artifact = _exact_keys(profile["artifact"], PROFILE_ARTIFACT_KEYS, "profile.artifact")
    if artifact != {
        "fileName": "DroneDream-Sim-1.0.0.exe",
        "productVersion": "1.0.0",
        "targetArchitecture": "windows-x86_64",
        "packaging": "tauri-nsis-windows",
    }:
        raise SimInstallerContractError("Sim artifact identity drifted")

    source = _exact_keys(profile["source"], PROFILE_SOURCE_KEYS, "profile.source")
    if (
        source["editionBranch"] != "codex/software-sim"
        or source["commonCoreBranch"] != "codex/software"
        or tuple(source["commonCorePaths"]) != COMMON_CORE_PATHS
        or source["sourceCommitPolicy"] != "handoff-exact-clean-source"
        or source["sourceTreeRequired"] != "clean"
    ):
        raise SimInstallerContractError("Sim source policy drifted")
    _commit(source["commonCoreCommit"], "profile.source.commonCoreCommit")
    _sha(source["commonCoreHash"], "profile.source.commonCoreHash")

    manifests = _exact_keys(profile["manifests"], PROFILE_MANIFEST_KEYS, "profile.manifests")
    _validate_file_ref(manifests["edition"], repo_root, "profile.manifests.edition")
    _validate_file_ref(
        manifests["capabilityPolicy"], repo_root, "profile.manifests.capabilityPolicy"
    )
    _validate_license_ref(
        manifests["licenseNotice"], repo_root, "profile.manifests.licenseNotice"
    )

    packs = manifests["vehiclePacks"]
    if not isinstance(packs, list) or len(packs) != 1:
        raise SimInstallerContractError("Sim profile must bind exactly one Vehicle Pack")
    pack_ref = _exact_keys(packs[0], PROFILE_PACK_REF_KEYS, "profile.manifests.vehiclePacks[0]")
    if pack_ref["packId"] != "px4-gazebo-x500-reference" or pack_ref["requiredSimulationOnly"] is not True:
        raise SimInstallerContractError("Sim Vehicle Pack selection drifted")
    pack_path = _resolve(repo_root, pack_ref["path"], "profile Vehicle Pack path")
    if sha256_file(pack_path) != _sha(pack_ref["sha256"], "profile Vehicle Pack sha256"):
        raise SimInstallerContractError("Sim Vehicle Pack manifest SHA-256 drifted")
    pack = load_json(pack_path)
    if (
        pack.get("packId") != pack_ref["packId"]
        or pack.get("integrity", {}).get("payloadSha256") != pack_ref["payloadSha256"]
        or "sim" not in pack.get("supportedEditions", [])
        or pack.get("controllers") != []
        or pack.get("components", {}).get("hardware", {}).get("status") != "unsupported"
    ):
        raise SimInstallerContractError("Sim Vehicle Pack is not simulation-only metadata")

    payload = _exact_keys(
        profile["deterministicPayload"],
        PROFILE_PAYLOAD_KEYS,
        "profile.deterministicPayload",
    )
    allowed_modules = _nonempty_string_list(payload["allowedModules"], "allowedModules")
    forbidden_modules = _nonempty_string_list(payload["forbiddenModules"], "forbiddenModules")
    allowed_caps = _nonempty_string_list(payload["allowedCapabilities"], "allowedCapabilities")
    forbidden_caps = _nonempty_string_list(
        payload["forbiddenCapabilities"], "forbiddenCapabilities"
    )
    forbidden_editions = _nonempty_string_list(
        payload["forbiddenEditionIds"], "forbiddenEditionIds"
    )
    _nonempty_string_list(payload["forbiddenCommandFragments"], "forbiddenCommandFragments")
    if payload["ordering"] != "lexicographic-by-module-then-pack-id":
        raise SimInstallerContractError("payload ordering policy drifted")
    if set(allowed_modules) & set(forbidden_modules):
        raise SimInstallerContractError("module allow/deny lists overlap")
    if set(allowed_caps) & set(forbidden_caps):
        raise SimInstallerContractError("capability allow/deny lists overlap")
    if payload["allowedVehiclePacks"] != ["px4-gazebo-x500-reference"]:
        raise SimInstallerContractError("allowed Vehicle Pack list drifted")
    if set(forbidden_editions) != {"lab", "field"}:
        raise SimInstallerContractError("Sim must forbid Lab and Field edition payloads")
    if any(item.startswith("hardware") for item in allowed_modules + allowed_caps):
        raise SimInstallerContractError("Sim allowlist contains hardware authority")

    installer = _exact_keys(profile["installerPlan"], PROFILE_INSTALLER_KEYS, "installerPlan")
    if (
        installer["outputReceiptKind"] != "dronedream-sim-installer-adoption-receipt"
        or installer["receiptSchemaPath"]
        != "distribution/sim/schemas/sim-installer-receipt.schema.json"
        or installer["unsignedAllowed"] is not True
        or installer["unsignedDisclosureRequired"] is not True
        or installer["releaseBranch"] != "codex/release-sim"
        or installer["releaseBranchState"] != "planned-not-created"
        or installer["universalHandoffRequired"] is not True
    ):
        raise SimInstallerContractError("installer plan drifted")
    for field in ("upgradePolicy", "rollbackPolicy", "uninstallPolicy"):
        if not isinstance(installer[field], str) or not installer[field]:
            raise SimInstallerContractError(f"installerPlan.{field} is empty")

    acceptance = _exact_keys(profile["acceptance"], PROFILE_ACCEPTANCE_KEYS, "acceptance")
    _nonempty_string_list(
        acceptance["exactArtifactRequiredFields"], "acceptance.exactArtifactRequiredFields"
    )
    _nonempty_string_list(acceptance["rejectIf"], "acceptance.rejectIf")
    if acceptance["adoptionVerifier"] != "distribution/sim/tools/sim_installer_contract.py":
        raise SimInstallerContractError("acceptance verifier path drifted")

    resource = _exact_keys(profile["resourceProtocol"], PROFILE_RESOURCE_KEYS, "resourceProtocol")
    if (
        resource["currentWorkClass"] != "GREEN"
        or resource["ordinaryCompileClass"] != "YELLOW"
        or resource["realPx4GazeboStabilityClass"] != "RED"
        or resource["apiKeyUseAllowed"] is not False
        or resource["deployAllowed"] is not False
        or resource["runtimeMigrationAllowed"] is not False
        or resource["buildAllowed"] is not False
    ):
        raise SimInstallerContractError("resource protocol drifted")
    return profile


def _expected_profile_sha(profile: dict[str, Any], profile_path: Path) -> str:
    declared_path = profile["acceptance"]["adoptionVerifier"]
    if declared_path != "distribution/sim/tools/sim_installer_contract.py":
        raise SimInstallerContractError("profile verifier binding drifted")
    return sha256_file(profile_path)


def validate_adoption_receipt(
    document: Any,
    *,
    profile: dict[str, Any],
    profile_path: Path,
    artifact_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> dict[str, Any]:
    receipt = _exact_keys(document, RECEIPT_KEYS, "Sim adoption receipt")
    if (
        receipt["schemaVersion"] != 1
        or receipt["kind"] != "dronedream-sim-installer-adoption-receipt"
        or receipt["receiptVersion"] != "1.0.0"
        or receipt["editionId"] != "sim"
    ):
        raise SimInstallerContractError("Sim adoption receipt identity is unsupported")

    profile_ref = _exact_keys(receipt["profile"], RECEIPT_PROFILE_KEYS, "receipt.profile")
    if profile_ref["path"] != "distribution/sim/build-profile.v1.json":
        raise SimInstallerContractError("receipt profile path drifted")
    if _sha(profile_ref["sha256"], "receipt.profile.sha256") != _expected_profile_sha(
        profile, profile_path
    ):
        raise SimInstallerContractError("receipt profile SHA-256 drifted")

    source = _exact_keys(receipt["source"], RECEIPT_SOURCE_KEYS, "receipt.source")
    source_commit = _commit(source["sourceCommit"], "receipt.source.sourceCommit")
    if expected_source_commit is not None and source_commit != expected_source_commit:
        raise SimInstallerContractError("receipt sourceCommit drifted from expected source")
    if source["sourceTreeState"] != "clean":
        raise SimInstallerContractError("receipt source tree must be clean")
    if source["commonCoreCommit"] != profile["source"]["commonCoreCommit"]:
        raise SimInstallerContractError("receipt commonCoreCommit drifted")
    if source["commonCoreHash"] != profile["source"]["commonCoreHash"]:
        raise SimInstallerContractError("receipt commonCoreHash drifted")

    artifact = _exact_keys(receipt["artifact"], RECEIPT_ARTIFACT_KEYS, "receipt.artifact")
    if artifact["fileName"] != profile["artifact"]["fileName"]:
        raise SimInstallerContractError("receipt artifact filename drifted")
    artifact_sha = _sha(artifact["sha256"], "receipt.artifact.sha256")
    if not isinstance(artifact["bytes"], int) or artifact["bytes"] <= 0:
        raise SimInstallerContractError("receipt artifact bytes are missing or empty")
    if artifact["authenticodeState"] not in {"valid", "not-signed"}:
        raise SimInstallerContractError("receipt Authenticode state is unsupported")
    if artifact["authenticodeState"] == "not-signed" and artifact["unsignedDisclosure"] is not True:
        raise SimInstallerContractError("unsigned Sim artifact must disclose unsigned status")
    if artifact["updaterSignatureState"] not in {"verified", "not-issued"}:
        raise SimInstallerContractError("receipt updater signature state is unsupported")
    if artifact_path is not None:
        if artifact_path.name != artifact["fileName"]:
            raise SimInstallerContractError("artifact path filename drifted")
        if artifact_path.stat().st_size != artifact["bytes"] or sha256_file(artifact_path) != artifact_sha:
            raise SimInstallerContractError("artifact bytes or SHA-256 mismatch")

    payload = _exact_keys(receipt["payload"], RECEIPT_PAYLOAD_KEYS, "receipt.payload")
    expected_payload = profile["deterministicPayload"]
    if payload["modules"] != expected_payload["allowedModules"]:
        raise SimInstallerContractError("receipt modules drifted from Sim profile")
    if payload["capabilities"] != expected_payload["allowedCapabilities"]:
        raise SimInstallerContractError("receipt capabilities drifted from Sim profile")
    if payload["vehiclePacks"] != expected_payload["allowedVehiclePacks"]:
        raise SimInstallerContractError("receipt Vehicle Packs drifted from Sim profile")
    command_audit = _exact_keys(
        payload["commandAudit"], COMMAND_AUDIT_KEYS, "receipt.payload.commandAudit"
    )
    if not isinstance(command_audit["scannedCommandCount"], int) or command_audit[
        "scannedCommandCount"
    ] < 0:
        raise SimInstallerContractError("command audit count is invalid")
    if command_audit["forbiddenFindings"] != []:
        raise SimInstallerContractError("command audit contains forbidden findings")
    observed = command_audit["observedCommands"]
    if not isinstance(observed, list) or any(not isinstance(item, str) for item in observed):
        raise SimInstallerContractError("observed commands must be strings")
    lowered = "\n".join(observed).lower()
    forbidden_fragments = [
        fragment.lower() for fragment in expected_payload["forbiddenCommandFragments"]
    ]
    if any(fragment in lowered for fragment in forbidden_fragments):
        raise SimInstallerContractError("receipt command audit found hardware or HITL command")

    license_notice = _exact_keys(
        receipt["licenseNotice"], LICENSE_REF_KEYS, "receipt.licenseNotice"
    )
    if license_notice != profile["manifests"]["licenseNotice"]:
        raise SimInstallerContractError("receipt license or NOTICE binding drifted")

    lifecycle = _exact_keys(
        receipt["installLifecycle"], INSTALL_LIFECYCLE_KEYS, "receipt.installLifecycle"
    )
    expected_lifecycle = {
        "upgradePlan": profile["installerPlan"]["upgradePolicy"],
        "rollbackPlan": profile["installerPlan"]["rollbackPolicy"],
        "uninstallPlan": profile["installerPlan"]["uninstallPolicy"],
    }
    if lifecycle != expected_lifecycle:
        raise SimInstallerContractError("receipt install lifecycle drifted")

    handoff = _exact_keys(receipt["handoff"], HANDOFF_KEYS, "receipt.handoff")
    _sha(handoff["universalReceiptSha256"], "receipt.handoff.universalReceiptSha256")
    _sha(handoff["universalArtifactSha256"], "receipt.handoff.universalArtifactSha256")
    _commit(handoff["universalSourceCommit"], "receipt.handoff.universalSourceCommit")
    if handoff["acceptedBy"] != "codex/software-sim":
        raise SimInstallerContractError("receipt handoff acceptedBy drifted")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    profile_parser = subparsers.add_parser("verify-profile")
    profile_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    profile_parser.add_argument(
        "profile", type=Path, default=Path("distribution/sim/build-profile.v1.json")
    )
    receipt_parser = subparsers.add_parser("verify-receipt")
    receipt_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    receipt_parser.add_argument(
        "--profile", type=Path, default=Path("distribution/sim/build-profile.v1.json")
    )
    receipt_parser.add_argument("--artifact", type=Path)
    receipt_parser.add_argument("--expected-source-commit")
    receipt_parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "verify-profile":
            validate_build_profile(load_json(args.profile), repo_root=args.repo_root.resolve())
        elif args.command == "verify-receipt":
            profile = validate_build_profile(
                load_json(args.profile), repo_root=args.repo_root.resolve()
            )
            validate_adoption_receipt(
                load_json(args.receipt),
                profile=profile,
                profile_path=args.profile,
                artifact_path=args.artifact,
                expected_source_commit=args.expected_source_commit,
            )
        else:
            raise SimInstallerContractError(f"unsupported command: {args.command}")
    except SimInstallerContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
