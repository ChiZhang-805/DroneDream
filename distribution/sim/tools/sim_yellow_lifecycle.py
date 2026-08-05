#!/usr/bin/env python3
"""Validate and render Sim YELLOW staging/rollback plans without changing the host."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^sim-y(?P<stage>[23])-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
RUN_ID_CONTRACT_PATTERN = r"^sim-y(?:2|3)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$"
RUNTIME_ROOT_RE = re.compile(r"^[A-Za-z]:/DroneDream(?:$|\.download-cache(?:/|$))")
PLAN_PATH = "distribution/sim/lifecycle/yellow-execution-plan.v1.json"

PLAN_KEYS = {
    "schemaVersion",
    "kind",
    "planVersion",
    "editionId",
    "executionClass",
    "state",
    "authorization",
    "yellow1VisualBinding",
    "approvedEditionAssetGate",
    "artifactGate",
    "staging",
    "protectedInventory",
    "ownedResiduePolicy",
    "yellow3Matrix",
    "rollback",
    "nonClaims",
}
AUTHORIZATION_KEYS = {
    "yellow1Approved",
    "yellow2Approved",
    "yellow3Approved",
    "separateApprovalRequiredForEachStage",
    "redRuntimeOrSimulatorApproved",
}
VISUAL_BINDING_KEYS = {
    "path",
    "sha256",
    "requiredCaseIds",
    "browserStarted",
    "productionBuildExecuted",
}
APPROVED_ASSET_GATE_KEYS = {
    "manifestPath",
    "manifestSha256",
    "requiredAssetRoles",
    "requiredAssetSha256",
    "applicationSourceWired",
    "installerDerivativeReady",
    "canonicalUniversalDonorIntegrated",
}
ARTIFACT_GATE_KEYS = {
    "yellow2OutputFileName",
    "yellow2ReceiptKind",
    "yellow3RequiresExactYellow2Receipt",
    "yellow2BlockedUntilInstallerDerivativeContract",
    "requiredReceiptFields",
    "ineligiblePreview",
    "unsignedAllowedWithDisclosure",
    "validatedVehiclePackCount",
}
STAGING_KEYS = {"runIdPattern", "yellow2", "yellow3"}
YELLOW2_KEYS = {
    "hostIsolation",
    "sourceRoot",
    "runRootTemplate",
    "bundleOutputTemplate",
    "receiptOutputTemplate",
    "cargoTargetDir",
    "cargoTargetOwnership",
    "cleanupCargoTargetAllowed",
}
YELLOW3_KEYS = {
    "hostIsolation",
    "hostSnapshotRequired",
    "networkMode",
    "runtimeSelection",
    "runRootTemplate",
    "installRootTemplate",
    "evidenceRootTemplate",
    "sourceArtifactCopyTemplate",
    "runtimeStartAllowed",
    "px4StartAllowed",
    "gazeboStartAllowed",
}
PROTECTED_KEYS = {
    "hostPaths",
    "guestPathTemplates",
    "guestRegistryKeys",
    "wslDistributions",
    "protectionRule",
}
OWNED_POLICY_KEYS = {
    "allowedKinds",
    "runRootDescendantsRequireExactRunId",
    "externalFilesRequireObservedSha256",
    "shortcutsRequireObservedSha256AndExpectedTarget",
    "registryKeysRequireExpectedValues",
    "allowedGuestRegistryKeys",
    "allowedGuestShortcutTemplates",
    "allowedExternalFileTemplates",
    "expectedShortcutTargetTemplate",
    "diagnosticsPreservedUntilReceiptFrozen",
    "expectedYellow2Entries",
    "expectedYellow3Entries",
}
EXPECTED_ENTRY_KEYS = {"kind", "pathTemplate", "disposition"}
MATRIX_KEYS = {
    "caseId",
    "phase",
    "locale",
    "webView2Fixture",
    "desktopShortcut",
    "priorInstall",
    "expected",
    "status",
}
ROLLBACK_KEYS = {
    "authoritativeMechanism",
    "ownedResidueTool",
    "toolMode",
    "inventoryRequired",
    "protectedInventoryMustBeRechecked",
    "historicalEvidenceDeletionAllowed",
    "cargoCacheDeletionAllowed",
    "runtimeDeletionAllowed",
    "webView2DeletionAllowed",
}
INVENTORY_KEYS = {
    "schemaVersion",
    "kind",
    "inventoryVersion",
    "editionId",
    "stage",
    "runId",
    "runRoot",
    "sourceReceiptSha256",
    "entries",
    "protectedObservations",
    "nonClaims",
}
INVENTORY_ENTRY_KEYS = {
    "kind",
    "path",
    "observed",
    "sha256",
    "expectedTarget",
    "expectedRegistryValues",
    "disposition",
}


class SimYellowLifecycleError(ValueError):
    """Raised when a YELLOW plan could touch unowned or protected state."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimYellowLifecycleError(f"could not read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SimYellowLifecycleError(f"JSON document must be an object: {path}")
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SimYellowLifecycleError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise SimYellowLifecycleError(
            f"{label} keys drifted (missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)})"
        )
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SimYellowLifecycleError(f"{label} is not a SHA-256 digest")
    return value


def _string_list(value: Any, label: str, *, expected_count: int | None = None) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
        or (expected_count is not None and len(value) != expected_count)
    ):
        raise SimYellowLifecycleError(f"{label} must be a unique string list")
    return value


def _repo_file(repo_root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or relative.startswith(("/", "\\")) or ".." in relative:
        raise SimYellowLifecycleError(f"{label} is not repository-relative")
    target = (repo_root / relative).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SimYellowLifecycleError(f"{label} escapes repository root") from exc
    if not target.is_file():
        raise SimYellowLifecycleError(f"{label} does not exist: {relative}")
    return target


def _normalize(value: str) -> str:
    return value.replace("\\", "/").rstrip("/").casefold()


def _is_within(value: str, root: str) -> bool:
    normalized_value = _normalize(value)
    normalized_root = _normalize(root)
    return normalized_value == normalized_root or normalized_value.startswith(f"{normalized_root}/")


def _expand(template: str, run_id: str) -> str:
    return template.replace("{runId}", run_id)


def validate_execution_plan(document: Any, *, repo_root: Path) -> dict[str, Any]:
    plan = _exact_keys(document, PLAN_KEYS, "Sim YELLOW execution plan")
    if (
        plan["schemaVersion"] != 1
        or plan["kind"] != "dronedream-sim-yellow-execution-plan"
        or plan["planVersion"] != "1.0.0"
        or plan["editionId"] != "sim"
        or plan["executionClass"] != "GREEN-plan-only"
        or plan["state"] != "pre-registered-not-authorized"
    ):
        raise SimYellowLifecycleError("Sim YELLOW execution plan identity drifted")

    authorization = _exact_keys(plan["authorization"], AUTHORIZATION_KEYS, "authorization")
    if authorization != {
        "yellow1Approved": False,
        "yellow2Approved": False,
        "yellow3Approved": False,
        "separateApprovalRequiredForEachStage": True,
        "redRuntimeOrSimulatorApproved": False,
    }:
        raise SimYellowLifecycleError("YELLOW/RED authorization state drifted")

    visual = _exact_keys(plan["yellow1VisualBinding"], VISUAL_BINDING_KEYS, "yellow1VisualBinding")
    visual_path = _repo_file(repo_root, visual["path"], "yellow1 visual contract")
    if sha256_file(visual_path) != _sha(visual["sha256"], "yellow1 visual SHA-256"):
        raise SimYellowLifecycleError("YELLOW-1 visual contract SHA-256 drifted")
    visual_contract = load_json(visual_path)
    expected_visual_cases = [
        f"{viewport['id']}-{locale['id']}"
        for viewport in visual_contract["viewports"]
        for locale in visual_contract["locales"]
    ]
    if (
        visual["requiredCaseIds"] != expected_visual_cases
        or visual["browserStarted"] is not False
        or visual["productionBuildExecuted"] is not False
    ):
        raise SimYellowLifecycleError("YELLOW-1 six-case registration drifted")

    approved_assets = _exact_keys(
        plan["approvedEditionAssetGate"],
        APPROVED_ASSET_GATE_KEYS,
        "approvedEditionAssetGate",
    )
    approved_manifest_path = _repo_file(
        repo_root, approved_assets["manifestPath"], "approved edition asset manifest"
    )
    if sha256_file(approved_manifest_path) != _sha(
        approved_assets["manifestSha256"], "approved edition asset manifest SHA-256"
    ):
        raise SimYellowLifecycleError("approved edition asset manifest SHA-256 drifted")
    approved_manifest = load_json(approved_manifest_path)
    approved_manifest_assets = approved_manifest.get("assets")
    if not isinstance(approved_manifest_assets, list):
        raise SimYellowLifecycleError("approved edition asset inventory is missing")
    manifest_hashes: dict[str, str] = {}
    for asset in approved_manifest_assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("destination"), dict):
            raise SimYellowLifecycleError("approved edition asset inventory drifted")
        role = asset.get("role")
        sha256 = asset["destination"].get("sha256")
        if not isinstance(role, str) or role in manifest_hashes:
            raise SimYellowLifecycleError("approved edition asset roles drifted")
        manifest_hashes[role] = _sha(sha256, f"approved asset {role} SHA-256")
    if (
        approved_assets["requiredAssetRoles"] != ["sim-mark-png", "sim-dot-lockup-png"]
        or approved_assets["requiredAssetSha256"] != manifest_hashes
        or approved_assets["applicationSourceWired"] is not True
        or approved_assets["installerDerivativeReady"] is not False
        or approved_assets["canonicalUniversalDonorIntegrated"] is not False
        or approved_manifest.get("integrationState", {}).get("applicationSourceWired") is not True
        or approved_manifest.get("integrationState", {}).get("windowsIcoGenerated") is not False
    ):
        raise SimYellowLifecycleError("approved edition asset gate drifted")

    artifact = _exact_keys(plan["artifactGate"], ARTIFACT_GATE_KEYS, "artifactGate")
    if (
        artifact["yellow2OutputFileName"] != "DroneDream-Sim-1.0.0.exe"
        or artifact["yellow2ReceiptKind"] != "dronedream-sim-yellow-build-receipt"
        or artifact["yellow3RequiresExactYellow2Receipt"] is not True
        or artifact["yellow2BlockedUntilInstallerDerivativeContract"] is not True
        or artifact["unsignedAllowedWithDisclosure"] is not True
        or artifact["validatedVehiclePackCount"] != 0
    ):
        raise SimYellowLifecycleError("YELLOW artifact gate drifted")
    _string_list(artifact["requiredReceiptFields"], "artifact required fields", expected_count=17)
    ineligible = artifact["ineligiblePreview"]
    if (
        not isinstance(ineligible, dict)
        or ineligible.get("sha256")
        != "b7d8481a6bf79678b7ca80ead7c4bf01a7a65bbeb81e93e6e4f28d0cea205863"
        or "not built" not in str(ineligible.get("reason", ""))
    ):
        raise SimYellowLifecycleError("ineligible preview boundary drifted")

    staging = _exact_keys(plan["staging"], STAGING_KEYS, "staging")
    if staging["runIdPattern"] != RUN_ID_CONTRACT_PATTERN:
        raise SimYellowLifecycleError("YELLOW run-id pattern drifted")
    yellow2 = _exact_keys(staging["yellow2"], YELLOW2_KEYS, "staging.yellow2")
    if (
        yellow2["hostIsolation"] != "authorized-local-build-host"
        or yellow2["cargoTargetDir"]
        != "C:/Users/zju20/AppData/Local/DroneDream/codex-cache/sim-cargo-target"
        or yellow2["cargoTargetOwnership"] != "persistent-cache-protected-not-owned-residue"
        or yellow2["cleanupCargoTargetAllowed"] is not False
        or "{runId}" not in yellow2["runRootTemplate"]
    ):
        raise SimYellowLifecycleError("YELLOW-2 staging boundary drifted")
    yellow3 = _exact_keys(staging["yellow3"], YELLOW3_KEYS, "staging.yellow3")
    if (
        yellow3["hostIsolation"] != "dedicated-disposable-windows-sandbox-or-vm"
        or yellow3["hostSnapshotRequired"] is not True
        or yellow3["runtimeSelection"] != "install-app-only"
        or any(
            yellow3[key] is not False
            for key in ("runtimeStartAllowed", "px4StartAllowed", "gazeboStartAllowed")
        )
        or "{runId}" not in yellow3["runRootTemplate"]
        or "{runId}" not in yellow3["installRootTemplate"]
    ):
        raise SimYellowLifecycleError("YELLOW-3 staging boundary drifted")

    protected = _exact_keys(plan["protectedInventory"], PROTECTED_KEYS, "protectedInventory")
    host_paths = _string_list(protected["hostPaths"], "protected host paths", expected_count=4)
    if (
        yellow2["sourceRoot"] not in host_paths
        or yellow2["cargoTargetDir"] not in host_paths
        or protected["wslDistributions"] != ["DroneDreamRuntime"]
        or protected["protectionRule"] != "never-delete-never-move-never-overwrite"
    ):
        raise SimYellowLifecycleError("protected inventory drifted")
    _string_list(protected["guestPathTemplates"], "protected guest paths", expected_count=2)
    _string_list(protected["guestRegistryKeys"], "protected guest registry", expected_count=2)

    owned = _exact_keys(plan["ownedResiduePolicy"], OWNED_POLICY_KEYS, "ownedResiduePolicy")
    if (
        owned["allowedKinds"]
        != ["run-root", "install-root", "file", "shortcut", "registry-key"]
        or any(
            owned[key] is not True
            for key in (
                "runRootDescendantsRequireExactRunId",
                "externalFilesRequireObservedSha256",
                "shortcutsRequireObservedSha256AndExpectedTarget",
                "registryKeysRequireExpectedValues",
                "diagnosticsPreservedUntilReceiptFrozen",
            )
        )
    ):
        raise SimYellowLifecycleError("owned residue policy drifted")
    _string_list(owned["allowedGuestRegistryKeys"], "allowed registry keys", expected_count=2)
    _string_list(owned["allowedGuestShortcutTemplates"], "allowed shortcuts", expected_count=3)
    _string_list(owned["allowedExternalFileTemplates"], "allowed external files", expected_count=1)
    for stage, expected_count in (("expectedYellow2Entries", 4), ("expectedYellow3Entries", 9)):
        entries = owned[stage]
        if not isinstance(entries, list) or len(entries) != expected_count:
            raise SimYellowLifecycleError(f"{stage} residue inventory drifted")
        for index, raw_entry in enumerate(entries):
            entry = _exact_keys(raw_entry, EXPECTED_ENTRY_KEYS, f"{stage}[{index}]")
            if (
                entry["kind"] not in owned["allowedKinds"]
                or entry["disposition"] not in {"candidate-after-reverification", "preserve"}
                or not isinstance(entry["pathTemplate"], str)
                or not entry["pathTemplate"]
            ):
                raise SimYellowLifecycleError(f"{stage} residue entry drifted")

    matrix = plan["yellow3Matrix"]
    if not isinstance(matrix, list) or len(matrix) != 12:
        raise SimYellowLifecycleError("YELLOW-3 matrix must contain exactly 12 cases")
    case_ids: set[str] = set()
    phase_counts = {"fresh": 0, "overlay": 0, "uninstall": 0, "rollback": 0}
    for index, raw_case in enumerate(matrix):
        case = _exact_keys(raw_case, MATRIX_KEYS, f"yellow3Matrix[{index}]")
        if (
            case["caseId"] in case_ids
            or case["phase"] not in phase_counts
            or case["locale"] not in {"en", "zh-CN"}
            or case["webView2Fixture"] not in {"present", "missing"}
            or not isinstance(case["desktopShortcut"], bool)
            or case["status"] != "planned-not-executed"
        ):
            raise SimYellowLifecycleError("YELLOW-3 matrix case drifted")
        case_ids.add(case["caseId"])
        phase_counts[case["phase"]] += 1
    if phase_counts != {"fresh": 4, "overlay": 4, "uninstall": 2, "rollback": 2}:
        raise SimYellowLifecycleError("YELLOW-3 phase coverage drifted")

    rollback = _exact_keys(plan["rollback"], ROLLBACK_KEYS, "rollback")
    if (
        rollback["authoritativeMechanism"] != "restore-disposable-guest-snapshot"
        or rollback["ownedResidueTool"] != "distribution/sim/tools/sim_yellow_lifecycle.py"
        or rollback["toolMode"] != "validate-and-plan-only-never-delete"
        or any(
            rollback[key] is not False
            for key in (
                "historicalEvidenceDeletionAllowed",
                "cargoCacheDeletionAllowed",
                "runtimeDeletionAllowed",
                "webView2DeletionAllowed",
            )
        )
    ):
        raise SimYellowLifecycleError("rollback policy drifted")
    non_claims = plan["nonClaims"]
    if not isinstance(non_claims, dict) or any(value is not False for value in non_claims.values()):
        raise SimYellowLifecycleError("YELLOW plan non-claims must remain false")
    return plan


def create_stage_plan(contract: dict[str, Any], *, stage: str, run_id: str) -> dict[str, Any]:
    match = RUN_ID_RE.fullmatch(run_id)
    expected_digit = {"yellow-2": "2", "yellow-3": "3"}.get(stage)
    if match is None or expected_digit is None or match.group("stage") != expected_digit:
        raise SimYellowLifecycleError("runId does not match requested YELLOW stage")
    staging = contract["staging"][stage.replace("-", "")]
    expanded = {
        key: _expand(value, run_id) if isinstance(value, str) else value
        for key, value in staging.items()
    }
    return {
        "schemaVersion": 1,
        "kind": "dronedream-sim-yellow-stage-plan",
        "editionId": "sim",
        "stage": stage,
        "runId": run_id,
        "executionAuthorized": False,
        "paths": expanded,
        "approvedEditionAssetGate": contract["approvedEditionAssetGate"],
        "artifactGate": contract["artifactGate"],
        "protectedInventory": contract["protectedInventory"],
        "yellow3Matrix": contract["yellow3Matrix"] if stage == "yellow-3" else [],
        "nonClaims": {
            "directoriesCreated": False,
            "buildExecuted": False,
            "installerExecuted": False,
            "rollbackExecuted": False,
        },
    }


def validate_owned_inventory(
    document: Any, *, contract: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inventory = _exact_keys(document, INVENTORY_KEYS, "owned residue inventory")
    if (
        inventory["schemaVersion"] != 1
        or inventory["kind"] != "dronedream-sim-owned-residue-inventory"
        or inventory["inventoryVersion"] != "1.0.0"
        or inventory["editionId"] != "sim"
        or inventory["stage"] not in {"yellow-2", "yellow-3"}
    ):
        raise SimYellowLifecycleError("owned residue inventory identity drifted")
    run_id = inventory["runId"]
    expected_stage = "2" if inventory["stage"] == "yellow-2" else "3"
    match = RUN_ID_RE.fullmatch(run_id) if isinstance(run_id, str) else None
    if match is None or match.group("stage") != expected_stage:
        raise SimYellowLifecycleError("owned residue runId drifted")
    staging = contract["staging"][inventory["stage"].replace("-", "")]
    expected_run_root = _expand(staging["runRootTemplate"], run_id)
    if inventory["runRoot"] != expected_run_root:
        raise SimYellowLifecycleError("owned residue run root drifted")
    _sha(inventory["sourceReceiptSha256"], "owned residue source receipt")

    protected = contract["protectedInventory"]["hostPaths"]
    policy = contract["ownedResiduePolicy"]
    allowed_registry = set(policy["allowedGuestRegistryKeys"])
    allowed_shortcuts = {
        _expand(item, run_id) for item in policy["allowedGuestShortcutTemplates"]
    }
    allowed_external_files = {
        _expand(item, run_id) for item in policy["allowedExternalFileTemplates"]
    }
    expected_target = _expand(policy["expectedShortcutTargetTemplate"], run_id)
    expected_install_root = _expand(
        contract["staging"]["yellow3"]["installRootTemplate"], run_id
    )
    entries = inventory["entries"]
    if not isinstance(entries, list) or not entries:
        raise SimYellowLifecycleError("owned residue entries are missing")
    seen: set[tuple[str, str]] = set()
    operations: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entries):
        entry = _exact_keys(raw_entry, INVENTORY_ENTRY_KEYS, f"inventory.entries[{index}]")
        kind = entry["kind"]
        value = entry["path"]
        if kind not in policy["allowedKinds"] or not isinstance(value, str) or not value:
            raise SimYellowLifecycleError("owned residue kind or path drifted")
        identity = (kind, _normalize(value))
        if identity in seen:
            raise SimYellowLifecycleError("owned residue entries are duplicated")
        seen.add(identity)
        if any(_is_within(value, protected_path) for protected_path in protected):
            raise SimYellowLifecycleError("owned residue overlaps protected host evidence")
        if RUNTIME_ROOT_RE.match(value) or "artifacts/test-runs" in _normalize(value):
            raise SimYellowLifecycleError("owned residue overlaps Runtime or historical evidence")
        if entry["disposition"] not in {"candidate-after-reverification", "preserve"}:
            raise SimYellowLifecycleError("owned residue disposition drifted")

        if kind == "run-root" and value != expected_run_root:
            raise SimYellowLifecycleError("run-root entry is not exact")
        if kind == "install-root" and (
            inventory["stage"] != "yellow-3" or value != expected_install_root
        ):
            raise SimYellowLifecycleError("install-root entry is not exact")
        if (
            kind == "file"
            and not _is_within(value, expected_run_root)
            and value not in allowed_external_files
        ):
            raise SimYellowLifecycleError("owned file is outside the exact run root")
        if kind == "shortcut":
            if value not in allowed_shortcuts or entry["expectedTarget"] != expected_target:
                raise SimYellowLifecycleError("shortcut ownership proof drifted")
            if entry["observed"] is True:
                _sha(entry["sha256"], "observed shortcut SHA-256")
        if kind == "registry-key":
            expected_values = entry["expectedRegistryValues"]
            if value not in allowed_registry or not isinstance(expected_values, dict):
                raise SimYellowLifecycleError("registry ownership proof drifted")
            required_values = {
                "DisplayName",
                "DisplayVersion",
                "InstallLocation",
                "UninstallString",
            }
            if set(expected_values) != required_values:
                raise SimYellowLifecycleError("registry ownership values are incomplete")
            if expected_values["DisplayName"] != "DroneDream · SIM":
                raise SimYellowLifecycleError("registry display identity drifted")
        if kind == "file" and entry["observed"] is True:
            _sha(entry["sha256"], "observed file SHA-256")
        operations.append(
            {
                "kind": kind,
                "path": value,
                "action": (
                    "preserve"
                    if entry["disposition"] == "preserve"
                    else "remove-only-after-yellow-reverification"
                ),
                "executed": False,
            }
        )

    observations = inventory["protectedObservations"]
    if not isinstance(observations, dict) or any(
        value is not False for value in observations.values()
    ):
        raise SimYellowLifecycleError("protected residue was observed as modified")
    non_claims = inventory["nonClaims"]
    if not isinstance(non_claims, dict) or any(value is not False for value in non_claims.values()):
        raise SimYellowLifecycleError("owned residue non-claims must remain false")
    return inventory, operations


def _write_or_print(document: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(encoded, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract", type=Path, default=Path(PLAN_PATH)
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-plan")
    create_parser = subparsers.add_parser("create-stage-plan")
    create_parser.add_argument("--stage", choices=("yellow-2", "yellow-3"), required=True)
    create_parser.add_argument("--run-id", required=True)
    create_parser.add_argument("--output", type=Path)
    rollback_parser = subparsers.add_parser("plan-rollback")
    rollback_parser.add_argument("inventory", type=Path)
    rollback_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        repo_root = args.repo_root.resolve()
        contract = validate_execution_plan(load_json(args.contract), repo_root=repo_root)
        if args.command == "verify-plan":
            return 0
        if args.command == "create-stage-plan":
            _write_or_print(
                create_stage_plan(contract, stage=args.stage, run_id=args.run_id),
                args.output,
            )
            return 0
        if args.command == "plan-rollback":
            inventory, operations = validate_owned_inventory(
                load_json(args.inventory), contract=contract
            )
            _write_or_print(
                {
                    "schemaVersion": 1,
                    "kind": "dronedream-sim-owned-residue-rollback-plan",
                    "editionId": "sim",
                    "stage": inventory["stage"],
                    "runId": inventory["runId"],
                    "authoritativeRollback": "restore-disposable-guest-snapshot",
                    "operations": operations,
                    "executionImplemented": False,
                    "historicalEvidenceTouched": False,
                },
                args.output,
            )
            return 0
        raise SimYellowLifecycleError(f"unsupported command: {args.command}")
    except SimYellowLifecycleError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
