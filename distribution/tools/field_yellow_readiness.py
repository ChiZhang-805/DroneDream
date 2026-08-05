from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FIELD_BRANCH = "codex/software-field"
FIELD_RELEASE_BRANCH = "codex/release-field"
COMMON_CORE_REF = "origin/codex/software"
KIND = "dronedream-field-yellow-build-request-readiness-receipt"
FIELD_ARTIFACT = "DroneDream-Field-1.0.0.exe"
FIELD_UPDATER_MANIFEST = "field-latest.json"
FIELD_ENGINE_PROFILE = "field-lightweight"
COMMON_CORE_PATHS = ("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")
REQUIRED_LAYERS = ("native", "backend", "runtime")
DENIED_ACTIONS = (
    "hardware.parameter.write",
    "hardware.unlock",
    "hardware.arm",
    "hardware.flight",
)
ENGINE_SOURCE_UPPER_BOUND_BYTES = 16 * 1024 * 1024
INSTALLER_UPPER_BOUND_BYTES = 256 * 1024 * 1024
CARGO_TARGET = r"C:\Users\zju20\AppData\Local\DroneDream\codex-cache\field-cargo-target"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

LAYER_CONTRACTS = {
    "native": {
        "sourcePath": "desktop/src-tauri/src/edition_safety.rs",
        "testPath": "desktop/src-tauri/src/edition_safety.rs",
        "denyReasonCode": "native.pack.unvalidated",
        "denyTest": "current_catalog_denies_hardware_with_zero_validated_packs",
        "noHandlerTest": "native_decision_is_not_registered_as_a_tauri_command_or_action_handler",
    },
    "backend": {
        "sourcePath": "backend/app/distribution_safety.py",
        "testPath": "backend/tests/test_distribution_safety.py",
        "denyReasonCode": "backend.pack.unvalidated",
        "denyTest": "test_current_catalog_fails_closed_with_zero_validated_packs",
        "noHandlerTest": "test_backend_module_exposes_no_action_or_device_handler",
    },
    "runtime": {
        "sourcePath": "runtime/scripts/edition-safety-gate.py",
        "testPath": "runtime/tests/test_edition_safety_gate.py",
        "denyReasonCode": "runtime.pack.unvalidated",
        "denyTest": "test_runtime_independently_denies_current_unvalidated_catalog",
        "noHandlerTest": "test_runtime_module_exposes_no_action_or_device_handler",
    },
}

REQUIRED_ENGINE_RESOURCES = (
    "LICENSE",
    "runtime/THIRD_PARTY_NOTICES.md",
    "distribution/editions/field.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/vehicle-packs/registry.v1.json",
    "distribution/tools/field_lifecycle_contract.py",
    "distribution/tools/field_prerelease_audit.py",
    "distribution/schemas/field-yellow-readiness.schema.json",
    "distribution/tools/field_yellow_readiness.py",
)


class FieldYellowReadinessError(ValueError):
    pass


def canonical_bytes(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_canonical(document: object) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise FieldYellowReadinessError(f"expected JSON object: {path}")
    return document


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FieldYellowReadinessError(f"cannot load contract module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo_root: Path, *args: str, allow_failure: bool = False) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode and not allow_failure:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise FieldYellowReadinessError(detail)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def common_core_hash(repo_root: Path, commit: str) -> str:
    if COMMIT_RE.fullmatch(commit) is None:
        raise FieldYellowReadinessError("common-core commit is invalid")
    listing = _git(repo_root, "ls-tree", "-r", "--full-tree", commit, "--", *COMMON_CORE_PATHS)
    if not listing:
        raise FieldYellowReadinessError("common-core inventory is empty")
    return hashlib.sha256(listing.encode("utf-8")).hexdigest()


def _branch_exists(repo_root: Path, ref: str) -> bool:
    return bool(_git(repo_root, "show-ref", "--verify", "--hash", ref, allow_failure=True))


def _engine_payload(repo_root: Path) -> dict[str, Any]:
    engine_pack = _load_module(
        "field_yellow_engine_pack", repo_root / "engine-pack" / "tools" / "engine_pack.py"
    )
    files = engine_pack.production_files(
        repo_root, edition_profile=engine_pack.FIELD_EDITION_PROFILE
    )
    paths = [path for path, _ in files]
    path_set = set(paths)
    simulator_references = sorted(
        path
        for path in paths
        if any(token in path.lower() for token in ("gazebo", "sitl", "hitl", "simulator"))
    )
    control_plane_metadata = sorted(
        path
        for path in simulator_references
        if path.startswith("distribution/vehicle-packs/") and path.endswith(".json")
    )
    forbidden = sorted(
        path
        for path in simulator_references
        if path not in control_plane_metadata
        or path.startswith("backend/app/simulator/")
        or path.startswith("scripts/simulators/")
        or Path(path).suffix.lower()
        in {".7z", ".bat", ".cmd", ".dll", ".exe", ".msi", ".ps1", ".py", ".sh", ".so", ".tar", ".tgz", ".zip"}
    )
    return {
        "profileId": FIELD_ENGINE_PROFILE,
        "includesLargeSimulator": False,
        "excludedSourcePaths": ["backend/app/simulator", "scripts/simulators"],
        "fileCount": len(files),
        "sourceBytes": sum(path.stat().st_size for _, path in files),
        "sourceUpperBoundBytes": ENGINE_SOURCE_UPPER_BOUND_BYTES,
        "requiredResources": [path for path in REQUIRED_ENGINE_RESOURCES if path in path_set],
        "missingRequiredResources": [path for path in REQUIRED_ENGINE_RESOURCES if path not in path_set],
        "controlPlaneSimulatorMetadata": control_plane_metadata,
        "forbiddenSimulatorPayloads": forbidden,
        "artifactBuilt": False,
        "artifactPayloadScanPending": True,
    }


def _layer_contracts(repo_root: Path) -> list[dict[str, Any]]:
    records = []
    for layer in REQUIRED_LAYERS:
        contract = LAYER_CONTRACTS[layer]
        source_path = repo_root / contract["sourcePath"]
        test_path = repo_root / contract["testPath"]
        source = source_path.read_text(encoding="utf-8")
        tests = test_path.read_text(encoding="utf-8")
        records.append(
            {
                "layer": layer,
                "decisionWithCurrentCatalog": "deny",
                "denyReasonCode": contract["denyReasonCode"],
                "sourcePath": contract["sourcePath"],
                "sourceSha256": sha256_file(source_path),
                "testPath": contract["testPath"],
                "testSha256": sha256_file(test_path),
                "denyTest": contract["denyTest"],
                "noHandlerTest": contract["noHandlerTest"],
                "sourceContractPresent": contract["denyReasonCode"] in source,
                "testContractPresent": contract["denyTest"] in tests
                and contract["noHandlerTest"] in tests,
                "testExecutedByGenerator": False,
            }
        )
    return records


def _readonly_discovery(repo_root: Path, common_commit: str, common_hash: str) -> dict[str, Any]:
    prerelease = _load_module(
        "field_yellow_prerelease",
        repo_root / "distribution" / "tools" / "field_prerelease_audit.py",
    )
    manifest_hash = sha256_file(repo_root / "distribution" / "editions" / "field.v1.json")
    observation = prerelease.fake_readonly_observation(
        observation_id="obs:field-yellow-readiness-fake",
        device_id="fake-device:unknown",
        hardware_identity_hash="0" * 64,
        controller_model="Unknown controller",
        firmware_family="unknown",
        firmware_version="unknown",
        firmware_identity_hash="0" * 64,
        pack_id="unknown-pack",
        common_core_commit=common_commit,
        common_core_hash=common_hash,
        field_manifest_sha256=manifest_hash,
    )
    validated = prerelease.validate_readonly_observation(observation)
    return {
        "contractPath": "distribution/tools/field_prerelease_audit.py",
        "contractSha256": sha256_file(
            repo_root / "distribution" / "tools" / "field_prerelease_audit.py"
        ),
        "observationSha256": prerelease.sha256_canonical(validated),
        "transport": validated["transport"],
        "packId": validated["vehiclePack"]["packId"],
        "validationStatus": validated["vehiclePack"]["validationStatus"],
        "signatureState": validated["vehiclePack"]["signatureState"],
        "discoveryIsAuthorization": validated["authorization"]["discoveryIsAuthorization"],
        "decision": validated["authorization"]["decision"],
    }


def _lifecycle(repo_root: Path, common_commit: str, common_hash: str) -> dict[str, Any]:
    lifecycle = _load_module(
        "field_yellow_lifecycle",
        repo_root / "distribution" / "tools" / "field_lifecycle_contract.py",
    )
    contract = lifecycle.create_lifecycle_contract(
        common_core_commit=common_commit,
        common_core_hash=common_hash,
        field_manifest_sha256=sha256_file(
            repo_root / "distribution" / "editions" / "field.v1.json"
        ),
        capability_policy_sha256=sha256_file(
            repo_root / "distribution" / "capabilities" / "core-capabilities.v1.json"
        ),
        execution_gate_policy_sha256=sha256_file(
            repo_root / "distribution" / "safety" / "edition-execution-gate.v1.json"
        ),
    )
    lifecycle.validate_lifecycle_contract(contract)
    return {
        "contractPath": "distribution/tools/field_lifecycle_contract.py",
        "contractFileSha256": sha256_file(
            repo_root / "distribution" / "tools" / "field_lifecycle_contract.py"
        ),
        "contractSha256": contract["contractSha256"],
        "scenarios": [
            {
                "scenarioId": scenario["scenarioId"],
                "state": scenario["state"],
                "decision": scenario["decision"],
                "executed": scenario["installerBuilt"] or scenario["installerInstalled"],
            }
            for scenario in contract["lifecycleScenarios"]
        ],
        "dangerousActions": {
            item["action"]: item["decision"]
            for item in contract["refusalScenarios"]
            if item["scenarioId"].startswith("dangerous-")
        },
        "localizedLanguages": contract["accessibilityPolicy"]["localizedLanguages"],
        "screenReaderSummaryRequired": contract["accessibilityPolicy"][
            "screenReaderSummaryRequired"
        ],
        "keyboardAccessibleReviewActionRequired": contract["accessibilityPolicy"][
            "keyboardAccessibleReviewActionRequired"
        ],
    }


def evaluate_candidate(candidate: dict[str, Any], *, expected_common_core: str) -> list[str]:
    blockers: list[str] = []
    source = candidate["source"]
    if source["branch"] != FIELD_BRANCH or source["headCommit"] == "":
        blockers.append("field.source.identity")
    if not source["clean"] or source["upstreamAhead"] or source["upstreamBehind"]:
        blockers.append("field.source.not-clean-and-pushed")
    if source["commonCoreCommit"] != expected_common_core or not source["commonCoreAncestor"]:
        blockers.append("field.source.common-core")

    artifact = candidate["artifact"]
    if artifact["filename"] != FIELD_ARTIFACT or artifact["updaterManifest"] != FIELD_UPDATER_MANIFEST:
        blockers.append("field.artifact.filename")
    if artifact["signatureState"] != "not-issued-unsigned-preview":
        blockers.append("field.artifact.signature-claim")

    payload = candidate["payload"]
    if (
        payload["profileId"] != FIELD_ENGINE_PROFILE
        or payload["includesLargeSimulator"]
        or payload["forbiddenSimulatorPayloads"]
        or payload["missingRequiredResources"]
    ):
        blockers.append("field.payload.simulator-or-required-resource")
    if payload["sourceBytes"] > payload["sourceUpperBoundBytes"]:
        blockers.append("field.payload.source-upper-bound")

    desktop = candidate["desktop"]
    resources = {record["source"]: record["destination"] for record in desktop["effectiveResources"]}
    if (
        "icons/icon.ico" in resources
        or resources.get("../../brand/generated/field/windows/icon.ico") != "icons/DroneDream.ico"
        or not desktop["verified"]
    ):
        blockers.append("field.branding.shortcut-or-overlay")
    if not all(
        path in resources
        for path in (
            "../../LICENSE",
            "../../runtime/THIRD_PARTY_NOTICES.md",
            "../../runtime/licenses/valkey-COPYING",
        )
    ):
        blockers.append("field.license.notice")
    if desktop["effectiveResourceBytes"] > desktop["resourceUpperBoundBytes"]:
        blockers.append("field.desktop.resource-upper-bound")

    safety = candidate["safety"]
    if safety["validatedHardwarePackCount"] != 0:
        blockers.append("field.registry.expected-zero-drift")
    if safety["hardwareActionHandlersImplemented"]:
        blockers.append("field.hardware.handlers-present")
    if safety["requiredLayers"] != list(REQUIRED_LAYERS) or [
        layer["layer"] for layer in safety["layers"]
    ] != list(REQUIRED_LAYERS):
        blockers.append("field.quorum.layers")
    if any(
        layer["decisionWithCurrentCatalog"] != "deny"
        or not layer["sourceContractPresent"]
        or not layer["testContractPresent"]
        for layer in safety["layers"]
    ):
        blockers.append("field.quorum.layer-contract")
    if set(safety["actionDecisions"]) != set(DENIED_ACTIONS) or any(
        decision != "deny" for decision in safety["actionDecisions"].values()
    ):
        blockers.append("field.hardware.action-allow")
    discovery = safety["readonlyDiscovery"]
    if (
        discovery["discoveryIsAuthorization"]
        or discovery["decision"] != "deny"
        or discovery["transport"]["openedDevice"]
        or discovery["transport"]["writeAttempted"]
        or discovery["transport"]["writeOperations"]
    ):
        blockers.append("field.discovery.authority-or-write")

    lifecycle = candidate["lifecycle"]
    if any(item["decision"] != "deny" or item["executed"] for item in lifecycle["scenarios"]):
        blockers.append("field.lifecycle.executed-or-allowed")
    if lifecycle["dangerousActions"] != {action: "deny" for action in DENIED_ACTIONS}:
        blockers.append("field.lifecycle.dangerous-action")
    if candidate["releaseBranch"]["localPresent"] or candidate["releaseBranch"]["originPresent"]:
        blockers.append("field.release-branch.present")
    return sorted(set(blockers))


def _negative_cases(candidate: dict[str, Any], expected_common_core: str) -> list[dict[str, Any]]:
    cases: list[tuple[str, str, Any]] = []

    def wrong_filename(value: dict[str, Any]) -> None:
        value["artifact"]["filename"] = "DroneDream-Sim-1.0.0.exe"

    def simulator_script(value: dict[str, Any]) -> None:
        value["payload"]["forbiddenSimulatorPayloads"] = ["scripts/simulators/run-gazebo.ps1"]

    def universal_icon(value: dict[str, Any]) -> None:
        value["desktop"]["effectiveResources"].append(
            {"source": "icons/icon.ico", "destination": "icons/DroneDream.ico", "sizeBytes": 1, "sha256": "0" * 64}
        )

    def missing_notice(value: dict[str, Any]) -> None:
        value["desktop"]["effectiveResources"] = [
            record
            for record in value["desktop"]["effectiveResources"]
            if record["source"] != "../../runtime/THIRD_PARTY_NOTICES.md"
        ]

    def wrong_common(value: dict[str, Any]) -> None:
        value["source"]["commonCoreCommit"] = "0" * 40

    def hardware_allow(value: dict[str, Any]) -> None:
        value["safety"]["actionDecisions"]["hardware.arm"] = "allow"

    def missing_layer(value: dict[str, Any]) -> None:
        value["safety"]["layers"] = value["safety"]["layers"][:-1]

    cases.extend(
        [
            ("wrong-edition-filename", "field.artifact.filename", wrong_filename),
            ("simulator-script-in-payload", "field.payload.simulator-or-required-resource", simulator_script),
            ("universal-shortcut-icon-source", "field.branding.shortcut-or-overlay", universal_icon),
            ("missing-third-party-notice", "field.license.notice", missing_notice),
            ("wrong-common-core", "field.source.common-core", wrong_common),
            ("hardware-action-allow", "field.hardware.action-allow", hardware_allow),
            ("missing-runtime-quorum-layer", "field.quorum.layers", missing_layer),
        ]
    )
    results = []
    for case_id, expected_blocker, mutate in cases:
        drifted = deepcopy(candidate)
        mutate(drifted)
        blockers = evaluate_candidate(drifted, expected_common_core=expected_common_core)
        results.append(
            {
                "caseId": case_id,
                "decision": "deny",
                "expectedBlocker": expected_blocker,
                "observedBlockers": blockers,
                "verified": expected_blocker in blockers,
            }
        )
    return results


def create_yellow_readiness_receipt(
    *,
    repo_root: Path = ROOT,
    source_head: str | None = None,
    source_tree_clean: bool | None = None,
    source_branch: str | None = None,
    upstream_ahead: int | None = None,
    upstream_behind: int | None = None,
    common_core_ref: str = COMMON_CORE_REF,
) -> dict[str, Any]:
    drift = _load_module(
        "field_yellow_drift",
        repo_root / "distribution" / "tools" / "field_common_drift_readiness_audit.py",
    )
    head = source_head or _git(repo_root, "rev-parse", "HEAD")
    branch = source_branch or _git(repo_root, "branch", "--show-current")
    clean = (
        source_tree_clean
        if source_tree_clean is not None
        else not bool(_git(repo_root, "status", "--porcelain", "--untracked-files=all"))
    )
    if upstream_ahead is None or upstream_behind is None:
        counts = _git(repo_root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        ahead_text, behind_text = counts.split()
        observed_ahead, observed_behind = int(ahead_text), int(behind_text)
    else:
        observed_ahead, observed_behind = upstream_ahead, upstream_behind
    common_commit = _git(repo_root, "rev-parse", common_core_ref)
    common_hash = common_core_hash(repo_root, common_commit)
    ancestor = (
        subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", common_commit, head],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
    desktop = drift.field_desktop_preview_structure(repo_root)
    registry = load_json(repo_root / "distribution" / "vehicle-packs" / "registry.v1.json")
    validated = [
        pack
        for pack in registry["packs"]
        if pack["currentValidationStatus"] == "validated"
        and pack["currentValidationTier"] == "hardware-validated"
    ]
    gate = load_json(repo_root / "distribution" / "safety" / "edition-execution-gate.v1.json")
    candidate = {
        "source": {
            "branch": branch,
            "headCommit": head,
            "clean": clean,
            "upstreamAhead": observed_ahead,
            "upstreamBehind": observed_behind,
            "commonCoreRef": common_core_ref,
            "commonCoreCommit": common_commit,
            "commonCoreHash": common_hash,
            "commonCoreAncestor": ancestor,
        },
        "artifact": {
            "filename": FIELD_ARTIFACT,
            "packaging": "tauri-nsis",
            "updaterManifest": FIELD_UPDATER_MANIFEST,
            "signatureState": "not-issued-unsigned-preview",
            "artifactBuilt": False,
            "artifactSha256": None,
            "artifactBytes": None,
            "installerUpperBoundBytes": INSTALLER_UPPER_BOUND_BYTES,
        },
        "payload": _engine_payload(repo_root),
        "desktop": desktop,
        "safety": {
            "executionGatePath": "distribution/safety/edition-execution-gate.v1.json",
            "executionGateSha256": sha256_file(
                repo_root / "distribution" / "safety" / "edition-execution-gate.v1.json"
            ),
            "frontendIsAuthority": gate["frontendIsAuthority"],
            "hardwareActionHandlersImplemented": gate["hardwareActionHandlersImplemented"],
            "zeroValidatedPackDecision": gate["editionBoundaries"]["zeroValidatedPackDecision"],
            "validatedHardwarePackCount": len(validated),
            "requiredLayers": gate["requiredDecisionLayers"],
            "layers": _layer_contracts(repo_root),
            "actionDecisions": {action: "deny" for action in DENIED_ACTIONS},
            "readonlyDiscovery": _readonly_discovery(repo_root, common_commit, common_hash),
        },
        "lifecycle": _lifecycle(repo_root, common_commit, common_hash),
        "releaseBranch": {
            "name": FIELD_RELEASE_BRANCH,
            "localPresent": _branch_exists(repo_root, f"refs/heads/{FIELD_RELEASE_BRANCH}"),
            "originPresent": _branch_exists(
                repo_root, f"refs/remotes/origin/{FIELD_RELEASE_BRANCH}"
            ),
            "creationAllowed": False,
        },
        "staticPolicy": {
            "releaseSourceVerifierPath": "desktop/scripts/verify-release-source-policy.mjs",
            "releaseSourceVerifierSha256": sha256_file(
                repo_root / "desktop" / "scripts" / "verify-release-source-policy.mjs"
            ),
            "nsisVerifierPath": "desktop/scripts/verify-nsis-template.ps1",
            "nsisVerifierSha256": sha256_file(
                repo_root / "desktop" / "scripts" / "verify-nsis-template.ps1"
            ),
            "licensePath": "LICENSE",
            "licenseSha256": sha256_file(repo_root / "LICENSE"),
            "noticePath": "runtime/THIRD_PARTY_NOTICES.md",
            "noticeSha256": sha256_file(repo_root / "runtime" / "THIRD_PARTY_NOTICES.md"),
            "runtimeContractRegistryPath": "distribution/runtime-contract-registry.v1.json",
            "runtimeContractRegistrySha256": sha256_file(
                repo_root / "distribution" / "runtime-contract-registry.v1.json"
            ),
        },
    }
    blockers = evaluate_candidate(candidate, expected_common_core=common_commit)
    negative_cases = _negative_cases(candidate, common_commit)
    if not all(case["verified"] for case in negative_cases):
        blockers.append("field.negative-package-case.unverified")
    receipt = {
        "schemaVersion": 1,
        "kind": KIND,
        "editionId": "field",
        "candidate": candidate,
        "decision": "ready-to-request-yellow" if not blockers else "deny",
        "yellowBuildAuthorized": False,
        "buildExecuted": False,
        "installExecuted": False,
        "deviceEnumerationExecuted": False,
        "hardwareActionsAllowed": False,
        "simulationExecuted": False,
        "apiKeyRead": False,
        "releaseBranchCreated": False,
        "blockers": sorted(set(blockers)),
        "negativePackageCases": negative_cases,
        "yellowResourceRequest": {
            "scope": "unsigned Field frontend plus Rust/Tauri/NSIS preview build only",
            "expectedCpuImpact": "high-transient",
            "expectedMemoryUpperBoundBytes": 8 * 1024 * 1024 * 1024,
            "cargoTargetPath": CARGO_TARGET,
            "cargoTargetDiskUpperBoundBytes": 8 * 1024 * 1024 * 1024,
            "workspaceTemporaryDiskUpperBoundBytes": 1024 * 1024 * 1024,
            "expectedDurationMinutes": {"minimum": 20, "maximum": 45},
            "networkAllowed": False,
            "deviceAccessAllowed": False,
            "installationAllowed": False,
            "simulationAllowed": False,
            "apiKeyAccessAllowed": False,
        },
        "finalWebsiteHandoff": {
            "websiteSourceCommit": "afdcdee5b60883290c9d1cc0c036141920066659",
            "websiteEvidenceCommit": "1a82e36b362c95983473c4a0d0d967d8c7415f92",
            "state": "awaiting-exact-handoff",
            "productSourceCommit": head,
            "uniqueExeAbsolutePath": None,
            "filename": FIELD_ARTIFACT,
            "version": "1.0.0",
            "bytes": None,
            "sha256": None,
            "signatureState": "not-issued",
            "updaterSignaturePath": None,
            "updaterSignatureSha256": None,
            "receiptPath": None,
            "receiptSha256": None,
            "manifestPath": None,
            "manifestSha256": None,
            "buildCount": 0,
            "validationBoundary": {
                "freshInstall": "not-executed",
                "upgrade": "not-executed",
                "uninstall": "not-executed",
                "shortcut": "static-contract-only",
                "webview2": "static-contract-only",
                "englishChinese": "static-contract-only",
            },
            "singleEditionUrlFamilyVerified": False,
            "previewSubstitutionAllowed": False,
            "crossEditionAttachmentAllowed": False,
            "duplicateShaUrlOrTagAllowed": False,
            "releaseReady": False,
        },
        "remainingGates": [
            "total-control YELLOW approval for the exact clean source and resource request",
            "build gate remains deny until a separately approved exact authorization contract is installed",
            "native Rust deny test must execute during the approved build verification",
            "built payload must be rescanned for simulator binaries, scripts, backend modules, and wrong-edition assets",
            "artifact filename, bytes, SHA-256, unsigned state, license closure, and receipt must be recorded",
            "fresh install, upgrade, uninstall, and rollback require separate approval and remain unexecuted",
            "real USB, serial, flight controller, motor, arm, and flight tests remain RED",
        ],
    }
    receipt["receiptSha256"] = sha256_canonical(receipt)
    return receipt


def validate_yellow_readiness_receipt(document: dict[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "schemaVersion",
        "kind",
        "editionId",
        "candidate",
        "decision",
        "yellowBuildAuthorized",
        "buildExecuted",
        "installExecuted",
        "deviceEnumerationExecuted",
        "hardwareActionsAllowed",
        "simulationExecuted",
        "apiKeyRead",
        "releaseBranchCreated",
        "blockers",
        "negativePackageCases",
        "yellowResourceRequest",
        "finalWebsiteHandoff",
        "remainingGates",
        "receiptSha256",
    }
    if set(document) != expected_fields:
        raise FieldYellowReadinessError("Field YELLOW receipt fields drifted")
    expected_hash = document["receiptSha256"]
    unhashed = deepcopy(document)
    unhashed.pop("receiptSha256")
    if SHA256_RE.fullmatch(str(expected_hash)) is None or sha256_canonical(unhashed) != expected_hash:
        raise FieldYellowReadinessError("Field YELLOW receipt hash drifted")
    if document["schemaVersion"] != 1 or document["kind"] != KIND or document["editionId"] != "field":
        raise FieldYellowReadinessError("Field YELLOW receipt identity is invalid")
    for field in (
        "yellowBuildAuthorized",
        "buildExecuted",
        "installExecuted",
        "deviceEnumerationExecuted",
        "hardwareActionsAllowed",
        "simulationExecuted",
        "apiKeyRead",
        "releaseBranchCreated",
    ):
        if document[field] is not False:
            raise FieldYellowReadinessError(f"{field} must remain false")
    common_commit = document["candidate"]["source"]["commonCoreCommit"]
    blockers = evaluate_candidate(document["candidate"], expected_common_core=common_commit)
    if document["blockers"] != blockers:
        raise FieldYellowReadinessError("Field YELLOW blocker evaluation drifted")
    expected_decision = "ready-to-request-yellow" if not blockers else "deny"
    if document["decision"] != expected_decision:
        raise FieldYellowReadinessError("Field YELLOW decision drifted")
    if not document["negativePackageCases"] or not all(
        case["decision"] == "deny"
        and case["verified"]
        and case["expectedBlocker"] in case["observedBlockers"]
        for case in document["negativePackageCases"]
    ):
        raise FieldYellowReadinessError("Field wrong-package denial evidence drifted")
    handoff = document["finalWebsiteHandoff"]
    if (
        handoff["state"] != "awaiting-exact-handoff"
        or handoff["productSourceCommit"] != document["candidate"]["source"]["headCommit"]
        or handoff["filename"] != FIELD_ARTIFACT
        or handoff["version"] != "1.0.0"
        or handoff["buildCount"] != 0
        or handoff["signatureState"] != "not-issued"
        or handoff["releaseReady"] is not False
        or handoff["previewSubstitutionAllowed"] is not False
        or handoff["crossEditionAttachmentAllowed"] is not False
        or handoff["duplicateShaUrlOrTagAllowed"] is not False
    ):
        raise FieldYellowReadinessError("Field final Website handoff boundary drifted")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Field readiness to request a YELLOW build")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = validate_yellow_readiness_receipt(
        create_yellow_readiness_receipt(repo_root=args.repo_root.resolve())
    )
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if receipt["decision"] == "ready-to-request-yellow" else 2


if __name__ == "__main__":
    raise SystemExit(main())
