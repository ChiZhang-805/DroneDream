#!/usr/bin/env python3
"""Validate DroneDream Sim build-profile and installer adoption receipts.

This verifier is intentionally read-only. It never invokes Tauri, NSIS, PX4,
Gazebo, release-branch mutation, deployment, or Runtime migration.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
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
    "autonomousOptimizationContract",
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
PROFILE_MANIFEST_KEYS = {
    "edition",
    "capabilityPolicy",
    "enginePackProfile",
    "runtimeContractRegistry",
    "vehiclePackRegistry",
    "vehiclePacks",
    "licenseNotice",
}
FILE_REF_KEYS = {"path", "sha256"}
PROFILE_ENGINE_PACK_REF_KEYS = {"profileId", "path", "sha256"}
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
PROFILE_AUTONOMY_KEYS = {
    "requiredOptimizer",
    "modelCapabilities",
    "harnessControls",
    "maximumModelTurnsPerGeneration",
    "normalModelTurnsPerGeneration",
    "hardwareAuthorityGranted",
    "candidateClassification",
    "holdoutOutcomesVisibleToModel",
    "sameJobEvidenceRequired",
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
READINESS_KEYS = {
    "schemaVersion",
    "kind",
    "auditVersion",
    "editionId",
    "readinessState",
    "executionClass",
    "artifact",
    "adoption",
    "staticContracts",
    "lifecyclePlan",
    "externalDependencies",
    "securityAndSigning",
    "vehiclePackAndCapabilityFence",
    "negativeAssertions",
    "nextAuthorization",
}
READINESS_ARTIFACT_KEYS = {
    "path",
    "fileName",
    "bytes",
    "sha256",
    "productSubjectCommit",
    "postAdoptionEvidenceHead",
}
READINESS_ADOPTION_KEYS = {"receiptPath", "receiptSha256", "sidecarPath", "sidecarSha256"}
READINESS_CONTRACT_REF_KEYS = {"path", "sha256", "coverage"}
READINESS_LIFECYCLE_KEYS = {
    "freshInstall",
    "overlayUpgrade",
    "uninstall",
    "rollback",
    "shortcuts",
    "locales",
    "webView2",
}
READINESS_STEP_KEYS = {"status", "nextValidationClass", "checks", "blockers"}
READINESS_DEPS_KEYS = {"runtimeBase", "enginePack"}
READINESS_DEP_KEYS = {"mode", "embedded", "requiredForFullStack", "evidence"}
READINESS_SIGNING_KEYS = {
    "authenticodeStatus",
    "peCertificateTableEmpty",
    "sigSidecarPathExists",
    "updaterSignatureState",
    "unsignedDisclosureRequired",
    "unsignedDisclosurePresent",
}
READINESS_FENCE_KEYS = {
    "validatedVehiclePackCount",
    "allowedCapabilities",
    "forbiddenCapabilities",
    "forbiddenEditionIds",
}
READINESS_NEXT_AUTH_KEYS = {"yellowRequiresApproval", "yellowScope", "redRequiresApproval", "redScope"}

SURFACE_KEYS = {
    "schemaVersion",
    "kind",
    "contractVersion",
    "editionId",
    "executionClass",
    "identity",
    "overlay",
    "brandDonor",
    "websiteHandoff",
    "staticSourceRefs",
    "installerUi",
    "shortcuts",
    "lifecycleReadiness",
    "capabilityFence",
    "nonClaims",
}
SURFACE_IDENTITY_KEYS = {
    "displayName",
    "separator",
    "artifactFileName",
    "productVersion",
    "bundleIdentifier",
}
SURFACE_OVERLAY_KEYS = {
    "path",
    "sha256",
    "baseConfigPath",
    "baseConfigSha256",
    "baseConfigMustRemainUniversal",
    "artifactRenameRequired",
    "buildCommand",
}
SURFACE_BRAND_KEYS = {
    "approvedConceptHandoffSha256",
    "intakePath",
    "intakeSha256",
    "approvedEditionAssetManifestPath",
    "approvedEditionAssetManifestSha256",
    "approvedEditionAssetState",
    "approvedEditionAssetHashesVerified",
    "approvedEditionApplicationSourceWired",
    "canonicalDonorState",
    "canonicalDonorReceiptPath",
    "canonicalDonorReceiptSha256",
    "canonicalDonorManifestPath",
    "canonicalDonorManifestSha256",
    "canonicalDonorCommit",
    "commonCoreCommit",
    "commonCoreHash",
    "commonCoreUpdated",
    "commonCoreBindingVerified",
    "assetHashesVerified",
    "iconOverridePresent",
    "iconPath",
    "iconSha256",
    "iconBytes",
    "iconFrameSizesPx",
    "masterRedrawAllowed",
}
SURFACE_WEBSITE_HANDOFF_KEYS = {"path", "sha256", "state"}
SURFACE_SOURCE_REF_KEYS = {"path", "sha256", "requiredText"}
SURFACE_UI_KEYS = {
    "locales",
    "requiredSurfaces",
    "editionStateDisclosure",
    "unsignedDisclosureRequired",
    "externalDependencies",
    "forbiddenSurfaceTerms",
}
SURFACE_SHORTCUT_KEYS = {
    "startMenuName",
    "desktopShortcutName",
    "desktopShortcutDefault",
    "uninstallMustRemoveOwnedShortcuts",
}
SURFACE_LIFECYCLE_KEYS = {"path", "sha256", "requiredPlannedScenarios"}
SURFACE_FENCE_KEYS = {
    "validatedVehiclePackCount",
    "allowedTargetKinds",
    "forbiddenTargetKinds",
    "frontendIsAuthority",
}
SURFACE_NONCLAIM_KEYS = {
    "installerBuiltFromOverlay",
    "installerExecuted",
    "shortcutsObserved",
    "uninstallObserved",
    "rollbackObserved",
    "validated",
    "promotionReady",
}
WEBSITE_HANDOFF_KEYS = {
    "schemaVersion",
    "kind",
    "contractVersion",
    "editionId",
    "state",
    "recipient",
    "artifactIdentity",
    "requiredHandoffFields",
    "consistency",
    "current",
    "execution",
}
WEBSITE_RECIPIENT_KEYS = {
    "branch",
    "productSourceCommit",
    "evidenceCommit",
    "evidenceCommitIsProductSource",
    "behavior",
}
WEBSITE_IDENTITY_KEYS = {
    "fileName",
    "version",
    "editionDisplayName",
    "previewSubstitutionAllowed",
    "crossEditionSubstitutionAllowed",
}
WEBSITE_CONSISTENCY_KEYS = {
    "sameEditionRequired",
    "sameUrlFamilyRequired",
    "uniqueShaUrlTagRequired",
    "sourceAndEvidenceMustRemainSeparate",
    "signatureSidecarOptionalOnlyWhenStateNotIssued",
}
WEBSITE_CURRENT_KEYS = {
    "exactExeReceived",
    "productSourceCommit",
    "absoluteExePath",
    "bytes",
    "sha256",
    "authenticodeState",
    "updaterSigPath",
    "updaterSigSha256",
    "receiptPath",
    "receiptSha256",
    "manifestPath",
    "manifestSha256",
    "buildCount",
    "lifecycleValidated",
    "releaseReady",
}
WEBSITE_EXECUTION_KEYS = {
    "installerBuilt",
    "installerExecuted",
    "uploaded",
    "releaseBranchCreated",
}
WEBSITE_REQUIRED_FIELDS = (
    "exactCleanProductSourceCommit",
    "absoluteExePath",
    "fileName",
    "version",
    "bytes",
    "sha256Lowercase",
    "authenticodeState",
    "updaterSigPath",
    "updaterSigSha256",
    "receiptPath",
    "receiptSha256",
    "manifestPath",
    "manifestSha256",
    "buildCount",
    "freshInstallBoundary",
    "overlayBoundary",
    "uninstallBoundary",
    "shortcutBoundary",
    "webView2Boundary",
    "localeBoundary",
    "releaseReady",
)

SIM_DISPLAY_NAME = "DroneDream \u00b7 SIM"
SURFACE_SOURCE_REQUIREMENTS = {
    "desktop/src-tauri/nsis/installer.nsi": (
        '!define PRODUCTNAME "{{product_name}}"',
        '!define BUNDLEID "{{bundle_id}}"',
        'Name "${DRONEDREAM_DISPLAYNAME}"',
        'OutFile "${OUTFILE}"',
        '!define UNINSTKEY "Software\\Microsoft\\Windows\\'
        'CurrentVersion\\Uninstall\\${PRODUCTNAME}"',
        'WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "${DRONEDREAM_DISPLAYNAME}"',
        'RmDir /r "$LOCALAPPDATA\\${BUNDLEID}"',
        "DRONEDREAM_REMOVE_INTERNAL_SHORTCUT",
        'WriteUninstaller "$INSTDIR\\uninstall.exe"',
    ),
    "desktop/src-tauri/nsis/edition-identity.nsh": (
        '!else if "${PRODUCTNAME}" == "DroneDream-Sim"',
        '!define DRONEDREAM_DISPLAYNAME "DroneDream · SIM"',
        '!error "Unknown DroneDream installer PRODUCTNAME: ${PRODUCTNAME}"',
        "!macro DRONEDREAM_CREATE_DISPLAY_SHORTCUT SHORTCUT_PATH LABEL_PREFIX",
        "IsShortcutTarget",
        "SetErrors",
    ),
    "desktop/src-tauri/nsis/installer-languages.nsh": (
        "LangString DD_ShortcutConflict ${LANG_ENGLISH}",
        "LangString DD_ShortcutConflict ${LANG_SIMPCHINESE}",
    ),
    "desktop/src-tauri/nsis/languages/English.nsh": (
        "LangString createDesktop ${LANG_ENGLISH}",
    ),
    "desktop/src-tauri/nsis/languages/SimpChinese.nsh": (
        "LangString createDesktop ${LANG_SIMPCHINESE}",
    ),
}
SURFACE_UI_SURFACES = (
    "welcome",
    "license",
    "maintenance-choice",
    "install-directory",
    "start-menu",
    "external-runtime-choice",
    "progress",
    "finish",
    "uninstall-confirmation",
    "uninstall-result",
)
SURFACE_LIFECYCLE_SCENARIOS = (
    "freshInstall",
    "overlayUpgrade",
    "uninstall",
    "rollback",
    "shortcuts",
    "locales",
    "webView2",
)

COMMON_CORE_PATHS = ("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")


class SimInstallerContractError(ValueError):
    """Raised when a Sim installer contract would overstate the artifact."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _historical_sibling_bytes(
    repo_root: Path, record_path: str, sibling_path: str
) -> bytes:
    record_path = _safe_path(record_path, "historical record path")
    sibling_path = _safe_path(sibling_path, "historical sibling path")
    commit = subprocess.run(
        ["git", "-C", str(repo_root), "log", "-1", "--format=%H", "--", record_path],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    _commit(commit, "historical record commit")
    return subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{commit}:{sibling_path}"],
        check=True,
        capture_output=True,
    ).stdout


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
    edition_ref = _validate_file_ref(
        manifests["edition"], repo_root, "profile.manifests.edition"
    )
    edition_doc = load_json(_resolve(repo_root, edition_ref["path"], "profile edition path"))
    if (
        edition_doc.get("editionId") != "sim"
        or edition_doc.get("artifactBaseName") != artifact["fileName"]
        or edition_doc.get("productDisplayVersion") != artifact["productVersion"]
    ):
        raise SimInstallerContractError("profile drifted from Sim edition manifest identity")
    _validate_file_ref(
        manifests["capabilityPolicy"], repo_root, "profile.manifests.capabilityPolicy"
    )
    engine_ref = _exact_keys(
        manifests["enginePackProfile"],
        PROFILE_ENGINE_PACK_REF_KEYS,
        "profile.manifests.enginePackProfile",
    )
    engine_path = _resolve(
        repo_root, engine_ref["path"], "profile.manifests.enginePackProfile.path"
    )
    if (
        engine_ref["profileId"] != "sim-only"
        or engine_ref["path"] != "distribution/engine-pack-profiles/sim-only.v1.json"
        or sha256_file(engine_path)
        != _sha(engine_ref["sha256"], "profile.manifests.enginePackProfile.sha256")
    ):
        raise SimInstallerContractError("Sim Engine Pack profile binding drifted")
    engine_profile = load_json(engine_path)
    if (
        engine_profile.get("profileId") != "sim-only"
        or engine_profile.get("hardwarePayloadAllowed") is not False
        or engine_profile.get("allowedEditionIds") != ["sim"]
        or engine_profile.get("allowedVehiclePackIds")
        != ["px4-gazebo-x500-reference"]
    ):
        raise SimInstallerContractError("Sim Engine Pack profile is not fail-closed")
    runtime_registry_ref = _validate_file_ref(
        manifests["runtimeContractRegistry"],
        repo_root,
        "profile.manifests.runtimeContractRegistry",
    )
    vehicle_registry_ref = _validate_file_ref(
        manifests["vehiclePackRegistry"],
        repo_root,
        "profile.manifests.vehiclePackRegistry",
    )
    observed_mappings = {
        item.get("sourcePath"): item.get("sourceSha256")
        for item in engine_profile.get("sourceMappings", [])
        if isinstance(item, dict)
    }
    if observed_mappings != {
        runtime_registry_ref["path"]: runtime_registry_ref["sha256"],
        vehicle_registry_ref["path"]: vehicle_registry_ref["sha256"],
    }:
        raise SimInstallerContractError("Sim Engine Pack registry mapping drifted")
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
    if allowed_modules != edition_doc.get("modules", {}).get("required"):
        raise SimInstallerContractError("profile allowed modules drifted from Sim manifest")
    if forbidden_modules != edition_doc.get("modules", {}).get("forbidden"):
        raise SimInstallerContractError("profile forbidden modules drifted from Sim manifest")
    if allowed_caps != edition_doc.get("capabilities", {}).get("enabledOrConditioned"):
        raise SimInstallerContractError("profile allowed capabilities drifted from Sim manifest")
    if forbidden_caps != edition_doc.get("capabilities", {}).get("forbidden"):
        raise SimInstallerContractError("profile forbidden capabilities drifted from Sim manifest")
    if payload["allowedVehiclePacks"] != ["px4-gazebo-x500-reference"]:
        raise SimInstallerContractError("allowed Vehicle Pack list drifted")
    if set(forbidden_editions) != {"lab", "field"}:
        raise SimInstallerContractError("Sim must forbid Lab and Field edition payloads")
    if any(item.startswith("hardware") for item in allowed_modules + allowed_caps):
        raise SimInstallerContractError("Sim allowlist contains hardware authority")

    autonomy = _exact_keys(
        profile["autonomousOptimizationContract"],
        PROFILE_AUTONOMY_KEYS,
        "profile.autonomousOptimizationContract",
    )
    model_capabilities = _nonempty_string_list(
        autonomy["modelCapabilities"], "autonomousOptimizationContract.modelCapabilities"
    )
    harness_controls = _nonempty_string_list(
        autonomy["harnessControls"], "autonomousOptimizationContract.harnessControls"
    )
    if (
        autonomy["requiredOptimizer"] != "llm_harness"
        or autonomy["normalModelTurnsPerGeneration"] != 2
        or autonomy["maximumModelTurnsPerGeneration"] != 4
        or autonomy["hardwareAuthorityGranted"] is not False
        or autonomy["holdoutOutcomesVisibleToModel"] is not False
        or autonomy["sameJobEvidenceRequired"] is not True
        or autonomy["candidateClassification"]
        != "simulation-hypothesis-not-hardware-approved"
        or "propose-one-direct-bounded-candidate" not in model_capabilities
        or "analyze-structured-telemetry-and-failure-feedback"
        not in model_capabilities
        or "parameter-name-type-bound-step-and-choice-validation"
        not in harness_controls
        or "qualification-independent-holdout-and-rollback" not in harness_controls
    ):
        raise SimInstallerContractError("autonomous optimization contract drifted")
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
    expected_profile_sha256: str | None = None,
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
    expected_profile_sha = (
        _sha(expected_profile_sha256, "expected historical profile SHA-256")
        if expected_profile_sha256 is not None
        else _expected_profile_sha(profile, profile_path)
    )
    if _sha(profile_ref["sha256"], "receipt.profile.sha256") != expected_profile_sha:
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


def _validate_audit_contract_refs(
    refs: Any, *, repo_root: Path
) -> list[dict[str, Any]]:
    if not isinstance(refs, list) or not refs:
        raise SimInstallerContractError("readiness staticContracts must be non-empty")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, ref in enumerate(refs):
        label = f"readiness.staticContracts[{index}]"
        item = _exact_keys(ref, READINESS_CONTRACT_REF_KEYS, label)
        if item["path"] in seen:
            raise SimInstallerContractError("readiness static contract path is duplicated")
        seen.add(item["path"])
        path = _resolve(repo_root, item["path"], f"{label}.path")
        if sha256_file(path) != _sha(item["sha256"], f"{label}.sha256"):
            raise SimInstallerContractError(f"{label} SHA-256 drifted")
        _nonempty_string_list(item["coverage"], f"{label}.coverage")
        validated.append(item)
    return validated


def _validate_readiness_step(value: Any, label: str) -> dict[str, Any]:
    step = _exact_keys(value, READINESS_STEP_KEYS, label)
    if step["status"] != "planned-not-executed":
        raise SimInstallerContractError(f"{label} must remain planned-not-executed")
    if step["nextValidationClass"] not in {"YELLOW", "RED"}:
        raise SimInstallerContractError(f"{label} next validation class is unsupported")
    _nonempty_string_list(step["checks"], f"{label}.checks")
    if not isinstance(step["blockers"], list) or any(
        not isinstance(item, str) or not item for item in step["blockers"]
    ):
        raise SimInstallerContractError(f"{label}.blockers must be a text list")
    return step


def validate_install_readiness_audit(
    document: Any,
    *,
    profile: dict[str, Any],
    profile_path: Path,
    repo_root: Path,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    audit = _exact_keys(document, READINESS_KEYS, "Sim install readiness audit")
    if (
        audit["schemaVersion"] != 1
        or audit["kind"] != "dronedream-sim-install-lifecycle-readiness-audit"
        or audit["auditVersion"] != "1.0.0"
        or audit["editionId"] != "sim"
        or audit["readinessState"] != "ready-for-yellow-install-lifecycle-validation"
        or audit["executionClass"] != "GREEN-static-only"
    ):
        raise SimInstallerContractError("Sim install readiness audit identity is unsupported")

    artifact = _exact_keys(audit["artifact"], READINESS_ARTIFACT_KEYS, "readiness.artifact")
    if artifact["fileName"] != profile["artifact"]["fileName"]:
        raise SimInstallerContractError("readiness artifact filename drifted")
    _commit(artifact["productSubjectCommit"], "readiness.artifact.productSubjectCommit")
    _commit(artifact["postAdoptionEvidenceHead"], "readiness.artifact.postAdoptionEvidenceHead")
    if artifact["productSubjectCommit"] == artifact["postAdoptionEvidenceHead"]:
        raise SimInstallerContractError("readiness evidence head must not masquerade as source")
    if not isinstance(artifact["bytes"], int) or artifact["bytes"] <= 0:
        raise SimInstallerContractError("readiness artifact bytes are invalid")
    artifact_sha = _sha(artifact["sha256"], "readiness.artifact.sha256")
    if artifact_path is not None:
        if artifact_path.name != artifact["fileName"]:
            raise SimInstallerContractError("readiness artifact path filename drifted")
        if artifact_path.stat().st_size != artifact["bytes"] or sha256_file(artifact_path) != artifact_sha:
            raise SimInstallerContractError("readiness artifact bytes or SHA-256 mismatch")

    adoption = _exact_keys(audit["adoption"], READINESS_ADOPTION_KEYS, "readiness.adoption")
    receipt_path = _resolve(repo_root, adoption["receiptPath"], "readiness adoption receipt")
    sidecar_path = _resolve(repo_root, adoption["sidecarPath"], "readiness adoption sidecar")
    if sha256_file(receipt_path) != _sha(adoption["receiptSha256"], "readiness receipt sha256"):
        raise SimInstallerContractError("readiness adoption receipt SHA-256 drifted")
    if sha256_file(sidecar_path) != _sha(adoption["sidecarSha256"], "readiness sidecar sha256"):
        raise SimInstallerContractError("readiness adoption sidecar SHA-256 drifted")
    receipt_document = load_json(receipt_path)
    receipt_profile_ref = _exact_keys(
        receipt_document["profile"], RECEIPT_PROFILE_KEYS, "receipt.profile"
    )
    receipt_profile_sha = _sha(
        receipt_profile_ref["sha256"], "receipt.profile.sha256"
    )
    receipt_profile = profile
    if receipt_profile_sha != sha256_file(profile_path):
        historical_profile_bytes = _historical_sibling_bytes(
            repo_root, adoption["receiptPath"], receipt_profile_ref["path"]
        )
        if sha256_bytes(historical_profile_bytes) != receipt_profile_sha:
            raise SimInstallerContractError("historical receipt profile SHA-256 drifted")
        try:
            receipt_profile = json.loads(historical_profile_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SimInstallerContractError("historical receipt profile is invalid") from exc
        if not isinstance(receipt_profile, dict):
            raise SimInstallerContractError("historical receipt profile must be an object")
    receipt = validate_adoption_receipt(
        receipt_document,
        profile=receipt_profile,
        profile_path=profile_path,
        artifact_path=artifact_path,
        expected_source_commit=artifact["productSubjectCommit"],
        expected_profile_sha256=receipt_profile_sha,
    )
    sidecar = load_json(sidecar_path)
    if sidecar.get("sourceSeparation", {}).get("postAdoptionEvidenceHead") != artifact[
        "postAdoptionEvidenceHead"
    ]:
        raise SimInstallerContractError("readiness evidence head drifted from sidecar")
    if sidecar.get("classification", {}).get("notValidated") is not True:
        raise SimInstallerContractError("readiness must not claim validation")

    coverage = {
        item
        for ref in _validate_audit_contract_refs(audit["staticContracts"], repo_root=repo_root)
        for item in ref["coverage"]
    }
    required_coverage = {
        "fresh-install",
        "overlay-upgrade",
        "uninstall",
        "rollback",
        "shortcut",
        "en-locale",
        "zh-locale",
        "webview2",
        "runtime-external",
        "license-notice",
    }
    if not required_coverage <= coverage:
        raise SimInstallerContractError("readiness static contract coverage is incomplete")

    lifecycle = _exact_keys(audit["lifecyclePlan"], READINESS_LIFECYCLE_KEYS, "lifecyclePlan")
    for key in sorted(READINESS_LIFECYCLE_KEYS):
        step = _validate_readiness_step(lifecycle[key], f"lifecyclePlan.{key}")
        if key != "webView2" and step["nextValidationClass"] != "YELLOW":
            raise SimInstallerContractError(f"lifecyclePlan.{key} must require YELLOW")

    dependencies = _exact_keys(audit["externalDependencies"], READINESS_DEPS_KEYS, "externalDependencies")
    for key in ("runtimeBase", "enginePack"):
        dep = _exact_keys(dependencies[key], READINESS_DEP_KEYS, f"externalDependencies.{key}")
        if dep["mode"] != "external-dependency" or dep["embedded"] is not False:
            raise SimInstallerContractError(f"externalDependencies.{key} must remain external")
        if dep["requiredForFullStack"] is not True:
            raise SimInstallerContractError(f"externalDependencies.{key} must be required for full stack")
        if not isinstance(dep["evidence"], dict):
            raise SimInstallerContractError(f"externalDependencies.{key}.evidence must be an object")

    signing = _exact_keys(audit["securityAndSigning"], READINESS_SIGNING_KEYS, "securityAndSigning")
    expected_signing = {
        "authenticodeStatus": "NotSigned",
        "peCertificateTableEmpty": True,
        "sigSidecarPathExists": False,
        "updaterSignatureState": "not-issued",
        "unsignedDisclosureRequired": True,
        "unsignedDisclosurePresent": True,
    }
    if signing != expected_signing:
        raise SimInstallerContractError("readiness signing facts drifted")
    if receipt["artifact"]["authenticodeState"] != "not-signed":
        raise SimInstallerContractError("readiness receipt signing state drifted")

    fence = _exact_keys(
        audit["vehiclePackAndCapabilityFence"],
        READINESS_FENCE_KEYS,
        "vehiclePackAndCapabilityFence",
    )
    if fence["validatedVehiclePackCount"] != 0:
        raise SimInstallerContractError("readiness must preserve zero validated packs")
    payload = profile["deterministicPayload"]
    if fence["allowedCapabilities"] != payload["allowedCapabilities"]:
        raise SimInstallerContractError("readiness allowed capabilities drifted")
    if fence["forbiddenCapabilities"] != payload["forbiddenCapabilities"]:
        raise SimInstallerContractError("readiness forbidden capabilities drifted")
    if set(fence["forbiddenEditionIds"]) != {"lab", "field"}:
        raise SimInstallerContractError("readiness must forbid Lab and Field")
    if any(item.startswith("hardware.") or "hitl" in item for item in fence["allowedCapabilities"]):
        raise SimInstallerContractError("readiness allowed hardware or HITL capability")

    assertions = audit["negativeAssertions"]
    if not isinstance(assertions, dict):
        raise SimInstallerContractError("negativeAssertions must be an object")
    required_false = {
        "installed",
        "rebuilt",
        "uploaded",
        "releaseBranchCreated",
        "runtimeStarted",
        "px4Started",
        "gazeboStarted",
        "validated",
        "promotionReady",
        "fullStackValidated",
        "runtimeEmbedded",
        "hardwareOrHitlAuthorized",
    }
    missing = sorted(required_false - set(assertions))
    if missing:
        raise SimInstallerContractError(f"negativeAssertions missing {missing}")
    if any(assertions[key] is not False for key in required_false):
        raise SimInstallerContractError("negativeAssertions must all remain false")

    next_auth = _exact_keys(audit["nextAuthorization"], READINESS_NEXT_AUTH_KEYS, "nextAuthorization")
    if next_auth["yellowRequiresApproval"] is not True or next_auth["redRequiresApproval"] is not True:
        raise SimInstallerContractError("next authorization gates must require approval")
    _nonempty_string_list(next_auth["yellowScope"], "nextAuthorization.yellowScope")
    _nonempty_string_list(next_auth["redScope"], "nextAuthorization.redScope")
    return audit


def _contains_icon_override(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() == "icon" or _contains_icon_override(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_icon_override(item) for item in value)
    return False


def _load_brand_donor_module() -> Any:
    tool_path = Path(__file__).with_name("sim_brand_donor.py")
    spec = importlib.util.spec_from_file_location("sim_brand_donor_for_installer", tool_path)
    if spec is None or spec.loader is None:
        raise SimInstallerContractError("could not load Sim brand donor verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_large_label_module() -> Any:
    tool_path = Path(__file__).with_name("sim_large_label_adoption.py")
    spec = importlib.util.spec_from_file_location("sim_large_label_for_installer", tool_path)
    if spec is None or spec.loader is None:
        raise SimInstallerContractError("could not load Sim large-label verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_surface_source_refs(value: Any, *, repo_root: Path) -> None:
    if not isinstance(value, list) or len(value) != len(SURFACE_SOURCE_REQUIREMENTS):
        raise SimInstallerContractError("installer surface source refs are incomplete")
    paths: list[str] = []
    for index, raw_ref in enumerate(value):
        label = f"staticSourceRefs[{index}]"
        ref = _exact_keys(raw_ref, SURFACE_SOURCE_REF_KEYS, label)
        path_value = _safe_path(ref["path"], f"{label}.path")
        paths.append(path_value)
        expected_text = SURFACE_SOURCE_REQUIREMENTS.get(path_value)
        if expected_text is None or tuple(ref["requiredText"]) != expected_text:
            raise SimInstallerContractError(f"{label} required text contract drifted")
        path = _resolve(repo_root, path_value, f"{label}.path")
        if sha256_file(path) != _sha(ref["sha256"], f"{label}.sha256"):
            raise SimInstallerContractError(f"{label} SHA-256 drifted")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SimInstallerContractError(f"could not read installer source: {path_value}") from exc
        if any(required not in source for required in expected_text):
            raise SimInstallerContractError(f"{label} required installer behavior is absent")
    if tuple(paths) != tuple(SURFACE_SOURCE_REQUIREMENTS):
        raise SimInstallerContractError("installer surface source ref ordering drifted")


def validate_website_handoff_contract(document: Any) -> dict[str, Any]:
    contract = _exact_keys(
        document, WEBSITE_HANDOFF_KEYS, "Website exact EXE handoff contract"
    )
    if (
        contract["schemaVersion"] != 1
        or contract["kind"] != "dronedream-sim-website-exact-exe-handoff-contract"
        or contract["contractVersion"] != "1.0.0"
        or contract["editionId"] != "sim"
        or contract["state"] != "awaiting-exact-yellow2-and-lifecycle-handoff"
    ):
        raise SimInstallerContractError("Website exact EXE handoff identity drifted")
    recipient = _exact_keys(
        contract["recipient"], WEBSITE_RECIPIENT_KEYS, "Website handoff recipient"
    )
    if recipient != {
        "branch": "codex/website",
        "productSourceCommit": "afdcdee5b60883290c9d1cc0c036141920066659",
        "evidenceCommit": "1a82e36b362c95983473c4a0d0d967d8c7415f92",
        "evidenceCommitIsProductSource": False,
        "behavior": "read-only-receive-no-rebuild-no-rename",
    }:
        raise SimInstallerContractError("Website source/evidence binding drifted")
    identity = _exact_keys(
        contract["artifactIdentity"], WEBSITE_IDENTITY_KEYS, "Website artifact identity"
    )
    if identity != {
        "fileName": "DroneDream-Sim-1.0.0.exe",
        "version": "1.0.0",
        "editionDisplayName": SIM_DISPLAY_NAME,
        "previewSubstitutionAllowed": False,
        "crossEditionSubstitutionAllowed": False,
    }:
        raise SimInstallerContractError("Website Sim artifact identity drifted")
    if tuple(contract["requiredHandoffFields"]) != WEBSITE_REQUIRED_FIELDS:
        raise SimInstallerContractError("Website required handoff fields drifted")
    consistency = _exact_keys(
        contract["consistency"], WEBSITE_CONSISTENCY_KEYS, "Website handoff consistency"
    )
    if any(value is not True for value in consistency.values()):
        raise SimInstallerContractError("Website URL and edition consistency drifted")
    current = _exact_keys(
        contract["current"], WEBSITE_CURRENT_KEYS, "Website current handoff state"
    )
    if any(
        value is not False if key in {"exactExeReceived", "lifecycleValidated", "releaseReady"}
        else value is not None
        for key, value in current.items()
    ):
        raise SimInstallerContractError("Website handoff overclaims exact EXE readiness")
    execution = _exact_keys(
        contract["execution"], WEBSITE_EXECUTION_KEYS, "Website handoff execution"
    )
    if any(value is not False for value in execution.values()):
        raise SimInstallerContractError("Website handoff execution must remain false")
    return contract


def validate_sim_tauri_overlay_config(
    document: Any, *, repo_root: Path
) -> dict[str, Any]:
    expected = {
        "$schema": "https://schema.tauri.app/config/2",
        "productName": "DroneDream-Sim",
        "identifier": "io.dronedream.sim",
        "app": {
            "windows": [
                {
                    "label": "main",
                    "title": SIM_DISPLAY_NAME,
                    "width": 1440,
                    "height": 900,
                    "minWidth": 390,
                    "minHeight": 700,
                    "resizable": True,
                    "fullscreen": False,
                }
            ]
        },
        "bundle": {
            "icon": ["../../distribution/sim/desktop/icons/dronedream-sim.ico"],
            "shortDescription": "PX4 SITL and Gazebo simulation workspace",
            "longDescription": (
                f"{SIM_DISPLAY_NAME} provides simulation-only PX4 SITL and Gazebo workflows. "
                "Runtime Base and Engine Pack remain external dependencies. Hardware and HITL "
                "capabilities are not included or authorized."
            ),
        },
    }
    if document != expected:
        raise SimInstallerContractError("Sim desktop overlay identity drifted")
    icon_relative = document["bundle"]["icon"][0]
    icon_path = (repo_root / "desktop" / "src-tauri" / icon_relative).resolve()
    expected_icon = (
        repo_root / "distribution" / "sim" / "desktop" / "icons" / "dronedream-sim.ico"
    ).resolve()
    if icon_path != expected_icon or not icon_path.is_file():
        raise SimInstallerContractError("Sim desktop overlay icon path drifted")
    if (
        icon_path.stat().st_size != 54431
        or sha256_file(icon_path)
        != "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c"
    ):
        raise SimInstallerContractError("Sim desktop overlay icon bytes drifted")
    return document


def validate_installer_surface_contract(
    document: Any,
    *,
    profile: dict[str, Any],
    profile_path: Path,
    repo_root: Path,
    donor_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = _exact_keys(document, SURFACE_KEYS, "Sim installer surface contract")
    if (
        contract["schemaVersion"] != 1
        or contract["kind"] != "dronedream-sim-installer-surface-contract"
        or contract["contractVersion"] != "1.0.0"
        or contract["editionId"] != "sim"
        or contract["executionClass"] != "GREEN-static-only"
    ):
        raise SimInstallerContractError("Sim installer surface contract identity is unsupported")

    identity = _exact_keys(contract["identity"], SURFACE_IDENTITY_KEYS, "surface.identity")
    if identity != {
        "displayName": SIM_DISPLAY_NAME,
        "separator": " \u00b7 ",
        "artifactFileName": profile["artifact"]["fileName"],
        "productVersion": profile["artifact"]["productVersion"],
        "bundleIdentifier": "io.dronedream.sim",
    }:
        raise SimInstallerContractError("Sim installer surface identity drifted")

    overlay = _exact_keys(contract["overlay"], SURFACE_OVERLAY_KEYS, "surface.overlay")
    if (
        overlay["path"] != "distribution/sim/desktop/tauri.sim.conf.json"
        or overlay["sha256"]
        != "718a9c0f8ec10144979f50fc4b06b75bcf68d38a810ced11e9b76384f6621359"
        or overlay["baseConfigPath"] != "desktop/src-tauri/tauri.conf.json"
        or overlay["baseConfigMustRemainUniversal"] is not True
        or overlay["artifactRenameRequired"] is not True
        or overlay["buildCommand"]
        != (
            "npm --prefix desktop run tauri -- build --config "
            "../distribution/sim/desktop/tauri.sim.conf.json"
        )
    ):
        raise SimInstallerContractError("Sim desktop overlay policy drifted")
    base_path = _resolve(repo_root, overlay["baseConfigPath"], "surface.overlay.baseConfigPath")
    if sha256_file(base_path) != _sha(
        overlay["baseConfigSha256"], "surface.overlay.baseConfigSha256"
    ):
        raise SimInstallerContractError("Universal desktop base config SHA-256 drifted")
    base_config = load_json(base_path)
    if (
        base_config.get("productName") != "DroneDream"
        or base_config.get("identifier") != "io.dronedream.desktop"
    ):
        raise SimInstallerContractError("desktop base config is no longer Universal")

    overlay_path = _resolve(repo_root, overlay["path"], "surface.overlay.path")
    if sha256_file(overlay_path) != overlay["sha256"]:
        raise SimInstallerContractError("Sim desktop overlay SHA-256 drifted")
    overlay_config = validate_sim_tauri_overlay_config(
        load_json(overlay_path), repo_root=repo_root
    )
    if not _contains_icon_override(overlay_config):
        raise SimInstallerContractError("Sim canonical icon override is absent")

    brand = _exact_keys(contract["brandDonor"], SURFACE_BRAND_KEYS, "surface.brandDonor")
    if brand != {
        "approvedConceptHandoffSha256": (
            "9fc52dea2edab1b65aa8c814fbf05ff1ad4fea0de4980403bec84dab8a1d9657"
        ),
        "intakePath": "distribution/sim/brand/donor-intake.v1.json",
        "intakeSha256": "a68d02430de5c1aebc42faed6f9e087731b6d94e6f0a7fa15c558b44e5b93297",
        "approvedEditionAssetManifestPath": (
            "distribution/sim/brand/approved-edition-assets.v1.json"
        ),
        "approvedEditionAssetManifestSha256": (
            "e2e61b676dadd8f8f37e370aa14382e2bff2a52307a820f82e42381498814296"
        ),
        "approvedEditionAssetState": "vendored-exact-bytes",
        "approvedEditionAssetHashesVerified": True,
        "approvedEditionApplicationSourceWired": True,
        "canonicalDonorState": "adopted-canonical-large-label-v1.1.0",
        "canonicalDonorReceiptPath": (
            "distribution/sim/brand/canonical-large-label-adoption-receipt.v1.json"
        ),
        "canonicalDonorReceiptSha256": (
            "2c5230750a98d184304b102de491623190cf738e13985e14e4c0b331ab92fb65"
        ),
        "canonicalDonorManifestPath": "brand/generated/brand-assets.v1.json",
        "canonicalDonorManifestSha256": (
            "cd56361d20c90c1447085da908bb8617924310b31f4b7a8883ae29ef0bf12471"
        ),
        "canonicalDonorCommit": "b8e0d0c7093abe9f54fe36f01022deb95852fa39",
        "commonCoreCommit": "4024e546fe6eaf298a37375924315a9816f6bf41",
        "commonCoreHash": (
            "c7e7da4cbd0dfca633e930e944e0ad240c908090c76800c7cb4a3d923aafcea8"
        ),
        "commonCoreUpdated": False,
        "commonCoreBindingVerified": True,
        "assetHashesVerified": True,
        "iconOverridePresent": True,
        "iconPath": "distribution/sim/desktop/icons/dronedream-sim.ico",
        "iconSha256": (
            "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c"
        ),
        "iconBytes": 54431,
        "iconFrameSizesPx": [16, 20, 24, 32, 40, 48, 64, 128, 256],
        "masterRedrawAllowed": False,
    }:
        raise SimInstallerContractError("Sim canonical brand donor state drifted")
    intake_path = _resolve(repo_root, brand["intakePath"], "surface.brandDonor.intakePath")
    if sha256_file(intake_path) != _sha(
        brand["intakeSha256"], "surface.brandDonor.intakeSha256"
    ):
        raise SimInstallerContractError("Sim brand donor intake SHA-256 drifted")
    brand_module = _load_brand_donor_module()
    large_label_module = _load_large_label_module()
    try:
        brand_module.validate_donor_intake(
            brand_module.load_json(intake_path), repo_root=repo_root
        )
        approved_manifest_path = _resolve(
            repo_root,
            brand["approvedEditionAssetManifestPath"],
            "surface.brandDonor.approvedEditionAssetManifestPath",
        )
        if sha256_file(approved_manifest_path) != _sha(
            brand["approvedEditionAssetManifestSha256"],
            "surface.brandDonor.approvedEditionAssetManifestSha256",
        ):
            raise SimInstallerContractError(
                "approved SIM edition asset manifest SHA-256 drifted"
            )
        brand_module.validate_approved_edition_assets(
            brand_module.load_json(approved_manifest_path),
            repo_root=repo_root,
        )
        adoption_path = _resolve(
            repo_root,
            brand["canonicalDonorReceiptPath"],
            "surface.brandDonor.canonicalDonorReceiptPath",
        )
        if sha256_file(adoption_path) != brand["canonicalDonorReceiptSha256"]:
            raise SimInstallerContractError("canonical donor adoption receipt drifted")
        adoption = large_label_module.validate_adoption(
            load_json(adoption_path), repo_root
        )
        if (
            adoption["source"]["productDonorCommit"] != brand["canonicalDonorCommit"]
            or adoption["source"]["commonCoreCommit"] != brand["commonCoreCommit"]
            or adoption["source"]["commonCoreHash"] != brand["commonCoreHash"]
            or adoption["source"]["brandManifestPath"]
            != brand["canonicalDonorManifestPath"]
            or adoption["source"]["brandManifestSha256"]
            != brand["canonicalDonorManifestSha256"]
        ):
            raise SimInstallerContractError("canonical donor adoption binding drifted")
    except (brand_module.SimBrandDonorError, large_label_module.LargeLabelAdoptionError) as exc:
        raise SimInstallerContractError(f"Sim brand donor verification failed: {exc}") from exc
    if donor_manifest is not None:
        raise SimInstallerContractError(
            "external donor input cannot override the adopted canonical receipt"
        )

    _validate_surface_source_refs(contract["staticSourceRefs"], repo_root=repo_root)

    website_ref = _exact_keys(
        contract["websiteHandoff"],
        SURFACE_WEBSITE_HANDOFF_KEYS,
        "surface.websiteHandoff",
    )
    if website_ref != {
        "path": "distribution/sim/release/website-exact-exe-handoff.v1.json",
        "sha256": "a0c8e2252d0a82b5b8918e467907a27fd94953ce3cfbd60546f91b8f4ed765cc",
        "state": "awaiting-exact-yellow2-and-lifecycle-handoff",
    }:
        raise SimInstallerContractError("Website handoff ref drifted")
    website_path = _resolve(repo_root, website_ref["path"], "surface.websiteHandoff.path")
    if sha256_file(website_path) != website_ref["sha256"]:
        raise SimInstallerContractError("Website handoff SHA-256 drifted")
    website = validate_website_handoff_contract(load_json(website_path))
    if website["state"] != website_ref["state"]:
        raise SimInstallerContractError("Website handoff state drifted")

    installer_ui = _exact_keys(contract["installerUi"], SURFACE_UI_KEYS, "surface.installerUi")
    if (
        installer_ui["locales"] != ["en", "zh-CN"]
        or tuple(installer_ui["requiredSurfaces"]) != SURFACE_UI_SURFACES
        or installer_ui["editionStateDisclosure"]
        != "internal-preview-not-promotion-ready"
        or installer_ui["unsignedDisclosureRequired"] is not True
        or installer_ui["externalDependencies"] != ["runtime-base", "engine-pack"]
        or installer_ui["forbiddenSurfaceTerms"]
        != [
            SIM_DISPLAY_NAME.replace("SIM", "LAB"),
            SIM_DISPLAY_NAME.replace("SIM", "FIELD"),
            "HITL mode",
            "hardware control",
        ]
    ):
        raise SimInstallerContractError("Sim installer UI contract drifted")

    shortcuts = _exact_keys(contract["shortcuts"], SURFACE_SHORTCUT_KEYS, "surface.shortcuts")
    if shortcuts != {
        "startMenuName": SIM_DISPLAY_NAME,
        "desktopShortcutName": SIM_DISPLAY_NAME,
        "desktopShortcutDefault": "interactive-opt-in",
        "uninstallMustRemoveOwnedShortcuts": True,
    }:
        raise SimInstallerContractError("Sim shortcut contract drifted")

    lifecycle_ref = _exact_keys(
        contract["lifecycleReadiness"], SURFACE_LIFECYCLE_KEYS, "surface.lifecycleReadiness"
    )
    if tuple(lifecycle_ref["requiredPlannedScenarios"]) != SURFACE_LIFECYCLE_SCENARIOS:
        raise SimInstallerContractError("Sim lifecycle scenario contract drifted")
    lifecycle_path = _resolve(repo_root, lifecycle_ref["path"], "surface.lifecycleReadiness.path")
    if sha256_file(lifecycle_path) != _sha(
        lifecycle_ref["sha256"], "surface.lifecycleReadiness.sha256"
    ):
        raise SimInstallerContractError("Sim lifecycle readiness SHA-256 drifted")
    lifecycle = validate_install_readiness_audit(
        load_json(lifecycle_path),
        profile=profile,
        profile_path=profile_path,
        repo_root=repo_root,
    )["lifecyclePlan"]
    if any(
        lifecycle[name]["status"] != "planned-not-executed"
        for name in SURFACE_LIFECYCLE_SCENARIOS
    ):
        raise SimInstallerContractError("Sim lifecycle scenarios must remain planned-not-executed")

    fence = _exact_keys(contract["capabilityFence"], SURFACE_FENCE_KEYS, "surface.capabilityFence")
    if fence != {
        "validatedVehiclePackCount": 0,
        "allowedTargetKinds": ["simulation"],
        "forbiddenTargetKinds": ["hitl", "real-hardware"],
        "frontendIsAuthority": False,
    }:
        raise SimInstallerContractError("Sim installer capability fence drifted")

    non_claims = _exact_keys(contract["nonClaims"], SURFACE_NONCLAIM_KEYS, "surface.nonClaims")
    if any(value is not False for value in non_claims.values()):
        raise SimInstallerContractError("Sim installer surface non-claims must remain false")
    return contract


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
    readiness_parser = subparsers.add_parser("verify-readiness")
    readiness_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    readiness_parser.add_argument(
        "--profile", type=Path, default=Path("distribution/sim/build-profile.v1.json")
    )
    readiness_parser.add_argument("--artifact", type=Path)
    readiness_parser.add_argument("audit", type=Path)
    surface_parser = subparsers.add_parser("verify-surface")
    surface_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    surface_parser.add_argument(
        "--profile", type=Path, default=Path("distribution/sim/build-profile.v1.json")
    )
    surface_parser.add_argument("--donor-manifest", type=Path)
    surface_parser.add_argument(
        "contract",
        type=Path,
        nargs="?",
        default=Path("distribution/sim/desktop/installer-surface-contract.v1.json"),
    )
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
        elif args.command == "verify-readiness":
            profile = validate_build_profile(
                load_json(args.profile), repo_root=args.repo_root.resolve()
            )
            validate_install_readiness_audit(
                load_json(args.audit),
                profile=profile,
                profile_path=args.profile,
                repo_root=args.repo_root.resolve(),
                artifact_path=args.artifact,
            )
        elif args.command == "verify-surface":
            profile = validate_build_profile(
                load_json(args.profile), repo_root=args.repo_root.resolve()
            )
            validate_installer_surface_contract(
                load_json(args.contract),
                profile=profile,
                profile_path=args.profile,
                repo_root=args.repo_root.resolve(),
                donor_manifest=(
                    load_json(args.donor_manifest) if args.donor_manifest is not None else None
                ),
            )
        else:
            raise SimInstallerContractError(f"unsupported command: {args.command}")
    except SimInstallerContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
