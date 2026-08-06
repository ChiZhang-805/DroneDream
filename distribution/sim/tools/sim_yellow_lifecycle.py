#!/usr/bin/env python3
"""Validate and render Sim YELLOW staging/rollback plans without changing the host."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40}$")
FILE_REF_KEYS = {"path", "sha256"}
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
    "replacementReadiness",
    "yellow1VisualBinding",
    "approvedEditionAssetGate",
    "canonicalSyncGate",
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
REPLACEMENT_READINESS_KEYS = {
    "path",
    "sha256",
    "commonCoreCommit",
    "commonCoreHash",
    "priorAttemptEvidencePath",
    "priorAttemptEvidenceSha256",
    "nextAttemptOrdinal",
    "executionAuthorized",
    "buildStarted",
}
VISUAL_BINDING_KEYS = {
    "path",
    "sha256",
    "requiredCaseIds",
    "browserStarted",
    "productionBuildExecuted",
    "productSourceCommit",
    "evidenceCommit",
    "evidenceRecordPath",
    "evidenceRecordSha256",
}
APPROVED_ASSET_GATE_KEYS = {
    "manifestPath",
    "manifestSha256",
    "requiredAssetRoles",
    "requiredAssetSha256",
    "applicationSourceWired",
    "installerDerivativeReady",
    "canonicalUniversalDonorIntegrated",
    "adoptionReceiptPath",
    "adoptionReceiptSha256",
    "installerIcoPath",
    "installerIcoSha256",
    "installerIcoBytes",
    "installerIcoFrameSizesPx",
}
CANONICAL_SYNC_GATE_KEYS = {
    "auditPath",
    "auditSha256",
    "historicalAuditState",
    "state",
    "baseCommit",
    "simOverlayCheckpoint",
    "donorCommit",
    "recordedCommonCoreCommit",
    "recordedCommonCoreHash",
    "brandDonorCommitIsCommonCore",
    "adoptionReceiptPath",
    "adoptionReceiptSha256",
    "formalHandoffReceived",
    "semanticIntegrationExecuted",
    "canonicalBrandManifestConsumed",
    "installerIcoConsumed",
    "releaseAsset",
    "yellow2Ready",
}
ARTIFACT_GATE_KEYS = {
    "yellow2OutputFileName",
    "yellow2ReceiptKind",
    "yellow3RequiresExactYellow2Receipt",
    "yellow2BlockedUntilInstallerDerivativeContract",
    "yellow2StaticReady",
    "installerSurfaceContract",
    "websiteHandoffContract",
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
CROSS_LINE_KEYS = {
    "schemaVersion",
    "kind",
    "observationVersion",
    "editionId",
    "state",
    "source",
    "pathObservation",
    "testObservation",
    "ownershipClassification",
    "execution",
}
CROSS_LINE_SOURCE_KEYS = {
    "simObservationCommit",
    "websiteBranch",
    "websiteProductSourceCommit",
    "websiteEvidenceHead",
    "evidenceHeadIsProductSource",
    "sourceAncestorOfEvidenceHead",
}
CROSS_LINE_PATH_KEYS = {
    "simToWebsiteSourceChangedPathCount",
    "simToWebsiteSourceChangedPaths",
    "relevantPathEvidence",
    "websiteEvidenceStaticRefs",
}
CROSS_LINE_EVIDENCE_KEYS = {
    "path",
    "simBlob",
    "websiteProductSourceBlob",
    "websiteEvidenceBlob",
    "simToWebsiteSourcePatch",
    "websiteSourceToEvidencePatch",
}
CROSS_LINE_PATCH_KEYS = {"sha256", "bytes"}
CROSS_LINE_REF_KEYS = {"path", "blob"}
CROSS_LINE_TEST_KEYS = {
    "simLocalPublicSite",
    "simLocalOwnedGate",
    "websiteHandoffPublicSite",
}
CROSS_LINE_CLASSIFICATION_KEYS = {
    "classification",
    "ownerBranch",
    "blocksSimOwnedGates",
    "commonCoreFixRequiredOnSim",
    "allowedDisposition",
    "forbiddenActions",
}
CROSS_LINE_EXECUTION_KEYS = {
    "websiteFilesModified",
    "websiteChangesCopied",
    "commonCoreBaselineUpdated",
    "mergeExecuted",
    "cherryPickExecuted",
    "browserStarted",
    "productionBuildExecuted",
    "installerBuilt",
    "releaseAssetClaimed",
}
CROSS_LINE_SIM_COMMIT = "1a7f1dce1f4e8ebf2872ebf1b0e2307498465f20"
CROSS_LINE_WEBSITE_SOURCE = "e3135fb482bc8dec60e45c91a5f2b4d94bf773c9"
CROSS_LINE_WEBSITE_EVIDENCE = "ad4bb392482094bdbee29ace3ec1bf8cc83ccd29"
CROSS_LINE_CHANGED_PATHS = (
    "frontend/src/__tests__/PublicSite.test.tsx",
    "frontend/src/site/CommunityPage.tsx",
    "frontend/src/site/PricingPage.tsx",
    "frontend/src/site/SiteApp.tsx",
    "frontend/src/site/site.css",
)
CROSS_LINE_RELEVANT_PATHS = (
    "frontend/src/__tests__/PublicSite.test.tsx",
    "frontend/src/site/PricingPage.tsx",
)
CROSS_LINE_STATIC_REFS = (
    "frontend/src/site/SiteApp.tsx",
    "frontend/src/features/settings/cloudModelAccess.ts",
)


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


def _run_git(repo_root: Path, *args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    if completed.returncode != 0:
        error = completed.stderr
        if isinstance(error, bytes):
            detail = error.decode("utf-8", errors="replace").strip()
        else:
            detail = error.strip()
        raise SimYellowLifecycleError(detail or f"git {' '.join(args)} failed")
    return completed.stdout


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
    )
    if completed.returncode not in {0, 1}:
        raise SimYellowLifecycleError("could not verify cross-line Git ancestry")
    return completed.returncode == 0


def _git_blob(repo_root: Path, commit: str, relative_path: str) -> str:
    output = _run_git(repo_root, "rev-parse", f"{commit}:{relative_path}")
    if not isinstance(output, str) or not GIT_OBJECT_RE.fullmatch(output.strip()):
        raise SimYellowLifecycleError(f"could not resolve cross-line blob: {relative_path}")
    return output.strip()


def _git_patch(
    repo_root: Path, base: str, target: str, relative_path: str
) -> dict[str, Any]:
    output = _run_git(
        repo_root,
        "diff",
        "--no-ext-diff",
        "--binary",
        base,
        target,
        "--",
        relative_path,
        binary=True,
    )
    if not isinstance(output, bytes) or not output:
        raise SimYellowLifecycleError(f"cross-line patch is empty: {relative_path}")
    return {"sha256": hashlib.sha256(output).hexdigest(), "bytes": len(output)}


def _git_file(repo_root: Path, commit: str, relative_path: str) -> bytes:
    output = _run_git(repo_root, "show", f"{commit}:{relative_path}", binary=True)
    if not isinstance(output, bytes):
        raise SimYellowLifecycleError("cross-line Git file reader returned text")
    return output


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
        or plan["executionClass"]
        != "GREEN-static-ready-replacement-yellow2-not-authorized"
        or plan["state"]
        != "yellow1-complete-yellow2-attempt1-failed-new-source-ready-awaiting-authorization"
    ):
        raise SimYellowLifecycleError("Sim YELLOW execution plan identity drifted")

    authorization = _exact_keys(plan["authorization"], AUTHORIZATION_KEYS, "authorization")
    if authorization != {
        "yellow1Approved": True,
        "yellow2Approved": False,
        "yellow3Approved": False,
        "separateApprovalRequiredForEachStage": True,
        "redRuntimeOrSimulatorApproved": False,
    }:
        raise SimYellowLifecycleError("YELLOW/RED authorization state drifted")

    replacement = _exact_keys(
        plan["replacementReadiness"],
        REPLACEMENT_READINESS_KEYS,
        "replacementReadiness",
    )
    replacement_path = _repo_file(
        repo_root, replacement["path"], "replacement readiness receipt"
    )
    prior_attempt_path = _repo_file(
        repo_root,
        replacement["priorAttemptEvidencePath"],
        "prior YELLOW-2 evidence record",
    )
    if (
        sha256_file(replacement_path)
        != _sha(replacement["sha256"], "replacement readiness SHA-256")
        or sha256_file(prior_attempt_path)
        != _sha(
            replacement["priorAttemptEvidenceSha256"],
            "prior YELLOW-2 evidence SHA-256",
        )
        or replacement["commonCoreCommit"]
        != "4024e546fe6eaf298a37375924315a9816f6bf41"
        or replacement["commonCoreHash"]
        != "c7e7da4cbd0dfca633e930e944e0ad240c908090c76800c7cb4a3d923aafcea8"
        or replacement["nextAttemptOrdinal"] != 2
        or replacement["executionAuthorized"] is not False
        or replacement["buildStarted"] is not False
    ):
        raise SimYellowLifecycleError("replacement YELLOW-2 readiness drifted")
    replacement_receipt = load_json(replacement_path)
    prior_attempt = load_json(prior_attempt_path)
    if (
        replacement_receipt.get("state")
        != "green-ready-awaiting-yellow-authorization"
        or replacement_receipt.get("nextYellow", {}).get("enginePackProfileId")
        != "sim-only"
        or replacement_receipt.get("priorFailedArtifact", {}).get("reuseAllowed")
        is not False
        or prior_attempt.get("payloadAudit", {}).get("simPayloadContractPassed")
        is not False
        or prior_attempt.get("nonClaims", {}).get("releaseReady") is not False
    ):
        raise SimYellowLifecycleError("replacement YELLOW-2 evidence overclaims readiness")

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
        or visual["browserStarted"] is not True
        or visual["productionBuildExecuted"] is not True
        or visual["productSourceCommit"]
        != "1af895287c2c8249acfa581919446e24ec16f575"
        or visual["evidenceCommit"]
        != "b3180803db89de0dab7f01dca374cb47f8021031"
    ):
        raise SimYellowLifecycleError("YELLOW-1 six-case evidence binding drifted")
    evidence_path = _repo_file(
        repo_root, visual["evidenceRecordPath"], "YELLOW-1 evidence record"
    )
    if sha256_file(evidence_path) != _sha(
        visual["evidenceRecordSha256"], "YELLOW-1 evidence record SHA-256"
    ):
        raise SimYellowLifecycleError("YELLOW-1 evidence record SHA-256 drifted")
    evidence = load_json(evidence_path)
    if (
        evidence.get("source", {}).get("productSourceCommit")
        != visual["productSourceCommit"]
        or evidence.get("source", {}).get("evidenceRecordCommitIsProductSource")
        is not False
        or evidence.get("results", {}).get("edgeCaseCount") != 6
        or evidence.get("results", {}).get("screenshotCount") != 18
        or evidence.get("releaseBoundary", {}).get("promotionReady") is not False
    ):
        raise SimYellowLifecycleError("YELLOW-1 evidence content drifted")

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
        or approved_assets["installerDerivativeReady"] is not True
        or approved_assets["canonicalUniversalDonorIntegrated"] is not True
        or approved_manifest.get("integrationState", {}).get("applicationSourceWired") is not True
        or approved_manifest.get("integrationState", {}).get("windowsIcoGenerated") is not False
    ):
        raise SimYellowLifecycleError("approved edition asset gate drifted")
    adoption_path = _repo_file(
        repo_root, approved_assets["adoptionReceiptPath"], "canonical adoption receipt"
    )
    if sha256_file(adoption_path) != _sha(
        approved_assets["adoptionReceiptSha256"], "canonical adoption receipt SHA-256"
    ):
        raise SimYellowLifecycleError("canonical adoption receipt SHA-256 drifted")
    adoption = load_json(adoption_path)
    ico_path = _repo_file(repo_root, approved_assets["installerIcoPath"], "Sim ICO")
    if (
        approved_assets["installerIcoSha256"]
        != "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c"
        or sha256_file(ico_path) != approved_assets["installerIcoSha256"]
        or ico_path.stat().st_size != approved_assets["installerIcoBytes"]
        or approved_assets["installerIcoBytes"] != 54431
        or approved_assets["installerIcoFrameSizesPx"]
        != [16, 20, 24, 32, 40, 48, 64, 128, 256]
        or adoption.get("source", {}).get("commonCoreCommit")
        != "e374d3f8d96b1265fcdb06864208b676566e94d9"
        or adoption.get("source", {}).get("commonCoreUpdated") is not False
        or adoption.get("nonClaims", {}).get("releaseAsset") is not False
    ):
        raise SimYellowLifecycleError("canonical adoption or Sim ICO gate drifted")

    sync_gate = _exact_keys(
        plan["canonicalSyncGate"], CANONICAL_SYNC_GATE_KEYS, "canonicalSyncGate"
    )
    expected_sync_gate = {
        "auditPath": "distribution/sim/brand/canonical-sync-conflict-audit.v1.json",
        "auditSha256": (
            "9e38977b9f29bcc32ccb4ae399784462771954ad50dfb1eaef52e35661fbcd2d"
        ),
        "historicalAuditState": "observed-not-merged-awaiting-authoritative-handoff",
        "state": "canonical-brand-adopted-path-limited",
        "baseCommit": "e374d3f8d96b1265fcdb06864208b676566e94d9",
        "simOverlayCheckpoint": "4086ff3134847b5bbe049cc1f43b17141e984f8c",
        "donorCommit": "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
        "recordedCommonCoreCommit": "e374d3f8d96b1265fcdb06864208b676566e94d9",
        "recordedCommonCoreHash": (
            "8e0e0507f4d9fb3c5567af464df7586520c66c3650457b19724a974f9e7ff82b"
        ),
        "brandDonorCommitIsCommonCore": False,
        "adoptionReceiptPath": (
            "distribution/sim/brand/canonical-donor-adoption-receipt.v1.json"
        ),
        "adoptionReceiptSha256": (
            "81decef72e0028baecfee0e130d521cd2b7de34e9224883358ac1ebcdff27026"
        ),
        "formalHandoffReceived": True,
        "semanticIntegrationExecuted": True,
        "canonicalBrandManifestConsumed": True,
        "installerIcoConsumed": True,
        "releaseAsset": False,
        "yellow2Ready": True,
    }
    if sync_gate != expected_sync_gate:
        raise SimYellowLifecycleError("canonical sync gate overclaims readiness")
    sync_audit_path = _repo_file(
        repo_root, sync_gate["auditPath"], "canonical sync conflict audit"
    )
    if sha256_file(sync_audit_path) != _sha(
        sync_gate["auditSha256"], "canonical sync conflict audit SHA-256"
    ):
        raise SimYellowLifecycleError("canonical sync conflict audit SHA-256 drifted")
    sync_audit = load_json(sync_audit_path)
    sync_source = sync_audit.get("source")
    if not isinstance(sync_source, dict) or any(
        sync_source.get(audit_key) != sync_gate[gate_key]
        for audit_key, gate_key in (
            ("baseCommit", "baseCommit"),
            ("simOverlayCheckpoint", "simOverlayCheckpoint"),
            ("donorCommit", "donorCommit"),
        )
    ):
        raise SimYellowLifecycleError("canonical sync source binding drifted")
    if (
        sync_audit.get("state") != sync_gate["historicalAuditState"]
        or any(value is not False for value in sync_audit.get("execution", {}).values())
        or sync_audit.get("syncPolicy", {}).get("wholeCommitCherryPickAllowed") is not False
        or sync_audit.get("syncPolicy", {}).get("backendCommonCoreAutoAdoptionAllowed")
        is not False
        or sync_audit.get("syncPolicy", {}).get("brandAssetsRequireCanonicalManifestSha256")
        is not True
    ):
        raise SimYellowLifecycleError("canonical sync audit execution boundary drifted")
    if (
        sync_gate["adoptionReceiptPath"] != approved_assets["adoptionReceiptPath"]
        or sync_gate["adoptionReceiptSha256"]
        != approved_assets["adoptionReceiptSha256"]
        or adoption.get("source", {}).get("brandDonorCommit")
        != sync_gate["donorCommit"]
        or adoption.get("semanticSync", {}).get("wholeCommitCherryPicked") is not False
        or adoption.get("semanticSync", {}).get("benchmarkOrBackendPathsAdopted")
        is not False
    ):
        raise SimYellowLifecycleError("canonical path-limited adoption binding drifted")
    branch_contract = load_json(
        _repo_file(
            repo_root,
            "distribution/branch-contracts/software-sim.v1.json",
            "Sim branch contract",
        )
    )
    branch_baseline = branch_contract.get("syncBaseline")
    if not isinstance(branch_baseline, dict) or (
        branch_baseline.get("previousCommonCoreCommit")
        != sync_gate["recordedCommonCoreCommit"]
        or branch_baseline.get("commonCoreCommit")
        != "4024e546fe6eaf298a37375924315a9816f6bf41"
        or branch_baseline.get("commonCoreHash")
        != "c7e7da4cbd0dfca633e930e944e0ad240c908090c76800c7cb4a3d923aafcea8"
        or branch_baseline.get("syncMode") != "path-limited-semantic-product-source"
    ):
        raise SimYellowLifecycleError("canonical sync recorded commonCore binding drifted")
    candidate_ref = sync_source.get("reconciliationCandidate")
    if not isinstance(candidate_ref, dict):
        raise SimYellowLifecycleError("canonical reconciliation candidate ref is missing")
    candidate_path = _repo_file(
        repo_root,
        candidate_ref.get("path"),
        "canonical reconciliation candidate",
    )
    if sha256_file(candidate_path) != _sha(
        candidate_ref.get("sha256"), "canonical reconciliation candidate SHA-256"
    ):
        raise SimYellowLifecycleError("canonical reconciliation candidate SHA-256 drifted")
    candidate = load_json(candidate_path)
    if (
        candidate.get("observedSource", {}).get("authoritativeHandoffReceived") is not False
        or candidate.get("observedSource", {}).get("sourceEvidenceHead") is not None
        or any(value is not False for value in candidate.get("adoptionGates", {}).values())
    ):
        raise SimYellowLifecycleError("canonical reconciliation candidate overclaims adoption")

    artifact = _exact_keys(plan["artifactGate"], ARTIFACT_GATE_KEYS, "artifactGate")
    if (
        artifact["yellow2OutputFileName"] != "DroneDream-Sim-1.0.0.exe"
        or artifact["yellow2ReceiptKind"] != "dronedream-sim-yellow-build-receipt"
        or artifact["yellow3RequiresExactYellow2Receipt"] is not True
        or artifact["yellow2BlockedUntilInstallerDerivativeContract"] is not False
        or artifact["yellow2StaticReady"] is not True
        or artifact["unsignedAllowedWithDisclosure"] is not True
        or artifact["validatedVehiclePackCount"] != 0
    ):
        raise SimYellowLifecycleError("YELLOW artifact gate drifted")
    for key, expected_path, expected_sha in (
        (
            "installerSurfaceContract",
            "distribution/sim/desktop/installer-surface-contract.v1.json",
            "3a251736d9018c24275da1725a42f66852efd43ecaf5a71e23e569833a2fd89d",
        ),
        (
            "websiteHandoffContract",
            "distribution/sim/release/website-exact-exe-handoff.v1.json",
            "a0c8e2252d0a82b5b8918e467907a27fd94953ce3cfbd60546f91b8f4ed765cc",
        ),
    ):
        ref = _exact_keys(artifact[key], FILE_REF_KEYS, f"artifactGate.{key}")
        path = _repo_file(repo_root, ref["path"], f"artifactGate.{key}.path")
        if (
            ref != {"path": expected_path, "sha256": expected_sha}
            or sha256_file(path) != ref["sha256"]
        ):
            raise SimYellowLifecycleError(f"YELLOW artifact {key} binding drifted")
    installer_surface = load_json(
        _repo_file(
            repo_root,
            artifact["installerSurfaceContract"]["path"],
            "installer surface contract",
        )
    )
    website_handoff = load_json(
        _repo_file(
            repo_root,
            artifact["websiteHandoffContract"]["path"],
            "Website handoff contract",
        )
    )
    if (
        installer_surface.get("brandDonor", {}).get("iconOverridePresent") is not True
        or installer_surface.get("nonClaims", {}).get("installerBuiltFromOverlay")
        is not False
        or website_handoff.get("artifactIdentity", {}).get("fileName")
        != artifact["yellow2OutputFileName"]
        or website_handoff.get("current", {}).get("exactExeReceived") is not False
        or website_handoff.get("current", {}).get("releaseReady") is not False
    ):
        raise SimYellowLifecycleError("YELLOW artifact static readiness overclaims release")
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
        "canonicalSyncGate": contract["canonicalSyncGate"],
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


def validate_cross_line_test_observation(
    document: Any, *, repo_root: Path
) -> dict[str, Any]:
    observation = _exact_keys(
        document, CROSS_LINE_KEYS, "Sim cross-line test observation"
    )
    if (
        observation["schemaVersion"] != 1
        or observation["kind"] != "dronedream-sim-cross-line-test-observation"
        or observation["observationVersion"] != "1.0.0"
        or observation["editionId"] != "sim"
        or observation["state"] != "observed-nonblocking-not-adopted"
    ):
        raise SimYellowLifecycleError("cross-line observation identity drifted")

    source = _exact_keys(
        observation["source"], CROSS_LINE_SOURCE_KEYS, "cross-line source"
    )
    if source != {
        "simObservationCommit": CROSS_LINE_SIM_COMMIT,
        "websiteBranch": "origin/codex/website",
        "websiteProductSourceCommit": CROSS_LINE_WEBSITE_SOURCE,
        "websiteEvidenceHead": CROSS_LINE_WEBSITE_EVIDENCE,
        "evidenceHeadIsProductSource": False,
        "sourceAncestorOfEvidenceHead": True,
    }:
        raise SimYellowLifecycleError("cross-line source/evidence classification drifted")
    if (
        not _git_is_ancestor(repo_root, CROSS_LINE_SIM_COMMIT, "HEAD")
        or not _git_is_ancestor(
            repo_root, CROSS_LINE_WEBSITE_SOURCE, CROSS_LINE_WEBSITE_EVIDENCE
        )
        or not _git_is_ancestor(
            repo_root, CROSS_LINE_WEBSITE_EVIDENCE, source["websiteBranch"]
        )
    ):
        raise SimYellowLifecycleError("cross-line source/evidence ancestry is unproven")

    path_observation = _exact_keys(
        observation["pathObservation"],
        CROSS_LINE_PATH_KEYS,
        "cross-line path observation",
    )
    changed_output = _run_git(
        repo_root,
        "diff",
        "--name-only",
        CROSS_LINE_SIM_COMMIT,
        CROSS_LINE_WEBSITE_SOURCE,
        "--",
        "frontend/src/site",
        "frontend/src/__tests__/PublicSite.test.tsx",
    )
    if not isinstance(changed_output, str):
        raise SimYellowLifecycleError("cross-line changed-path observer returned bytes")
    changed_paths = tuple(path for path in changed_output.splitlines() if path)
    if (
        changed_paths != CROSS_LINE_CHANGED_PATHS
        or path_observation["simToWebsiteSourceChangedPathCount"] != len(changed_paths)
        or path_observation["simToWebsiteSourceChangedPaths"] != list(changed_paths)
    ):
        raise SimYellowLifecycleError("cross-line changed-path inventory drifted")

    raw_evidence = path_observation["relevantPathEvidence"]
    if not isinstance(raw_evidence, list) or len(raw_evidence) != len(
        CROSS_LINE_RELEVANT_PATHS
    ):
        raise SimYellowLifecycleError("cross-line relevant evidence is incomplete")
    observed_paths: list[str] = []
    for index, raw_entry in enumerate(raw_evidence):
        entry = _exact_keys(
            raw_entry, CROSS_LINE_EVIDENCE_KEYS, f"cross-line path evidence {index}"
        )
        relative_path = entry["path"]
        if (
            relative_path not in CROSS_LINE_RELEVANT_PATHS
            or relative_path in observed_paths
        ):
            raise SimYellowLifecycleError("cross-line relevant paths drifted")
        _exact_keys(
            entry["simToWebsiteSourcePatch"],
            CROSS_LINE_PATCH_KEYS,
            f"Sim-to-Website patch {relative_path}",
        )
        _exact_keys(
            entry["websiteSourceToEvidencePatch"],
            CROSS_LINE_PATCH_KEYS,
            f"Website source-to-evidence patch {relative_path}",
        )
        expected_entry = {
            "path": relative_path,
            "simBlob": _git_blob(repo_root, CROSS_LINE_SIM_COMMIT, relative_path),
            "websiteProductSourceBlob": _git_blob(
                repo_root, CROSS_LINE_WEBSITE_SOURCE, relative_path
            ),
            "websiteEvidenceBlob": _git_blob(
                repo_root, CROSS_LINE_WEBSITE_EVIDENCE, relative_path
            ),
            "simToWebsiteSourcePatch": _git_patch(
                repo_root,
                CROSS_LINE_SIM_COMMIT,
                CROSS_LINE_WEBSITE_SOURCE,
                relative_path,
            ),
            "websiteSourceToEvidencePatch": _git_patch(
                repo_root,
                CROSS_LINE_WEBSITE_SOURCE,
                CROSS_LINE_WEBSITE_EVIDENCE,
                relative_path,
            ),
        }
        if entry != expected_entry:
            raise SimYellowLifecycleError(
                f"cross-line blob or patch evidence drifted: {relative_path}"
            )
        observed_paths.append(relative_path)
    if tuple(observed_paths) != CROSS_LINE_RELEVANT_PATHS:
        raise SimYellowLifecycleError("cross-line relevant evidence ordering drifted")

    raw_refs = path_observation["websiteEvidenceStaticRefs"]
    if not isinstance(raw_refs, list) or len(raw_refs) != len(CROSS_LINE_STATIC_REFS):
        raise SimYellowLifecycleError("Website static refs are incomplete")
    static_payloads: dict[str, bytes] = {}
    for index, raw_ref in enumerate(raw_refs):
        ref = _exact_keys(raw_ref, CROSS_LINE_REF_KEYS, f"Website static ref {index}")
        relative_path = ref["path"]
        if relative_path != CROSS_LINE_STATIC_REFS[index]:
            raise SimYellowLifecycleError("Website static ref ordering drifted")
        if ref["blob"] != _git_blob(
            repo_root, CROSS_LINE_WEBSITE_EVIDENCE, relative_path
        ):
            raise SimYellowLifecycleError("Website static ref blob drifted")
        static_payloads[relative_path] = _git_file(
            repo_root, CROSS_LINE_WEBSITE_EVIDENCE, relative_path
        )
    public_test = _git_file(
        repo_root,
        CROSS_LINE_WEBSITE_EVIDENCE,
        "frontend/src/__tests__/PublicSite.test.tsx",
    )
    pricing = _git_file(
        repo_root,
        CROSS_LINE_WEBSITE_EVIDENCE,
        "frontend/src/site/PricingPage.tsx",
    )
    site_app = static_payloads["frontend/src/site/SiteApp.tsx"]
    cloud_access = static_payloads[
        "frontend/src/features/settings/cloudModelAccess.ts"
    ]
    if (
        b"/billing-checkout/availability" not in public_test
        or b"getBillingAvailability" not in pricing
        or b"sensitiveCloudActionsEnabled" not in pricing
        or b"sensitiveCloudActionsEnabled" not in site_app
        or b"getBillingAvailability" not in cloud_access
        or b'"billing-checkout"' not in cloud_access
        or b'"/availability"' not in cloud_access
    ):
        raise SimYellowLifecycleError("Website availability static contract drifted")

    branch_contract = load_json(
        _repo_file(
            repo_root,
            "distribution/branch-contracts/software-sim.v1.json",
            "Sim branch contract",
        )
    )
    sim_prefixes = branch_contract.get("editionSpecificPathPrefixes")
    if not isinstance(sim_prefixes, list) or any(
        changed_path.startswith(prefix)
        for changed_path in changed_paths
        for prefix in sim_prefixes
        if isinstance(prefix, str)
    ):
        raise SimYellowLifecycleError("Website observation overlaps Sim-owned paths")

    tests = _exact_keys(
        observation["testObservation"], CROSS_LINE_TEST_KEYS, "cross-line tests"
    )
    if tests != {
        "simLocalPublicSite": {
            "command": "npx --no-install vitest run src/__tests__/PublicSite.test.tsx",
            "sourceCommit": CROSS_LINE_SIM_COMMIT,
            "testFiles": 1,
            "tests": 13,
            "passed": 12,
            "failed": 1,
            "failure": "expected-billing-availability-fetch-observed-download-manifest-only",
            "executedBySim": True,
        },
        "simLocalOwnedGate": {
            "command": (
                "npx --no-install vitest run "
                "src/__tests__/DistributionSetupPanel.test.tsx "
                "src/__tests__/SimEditionExperience.test.tsx "
                "src/__tests__/SimEditionProfile.test.ts"
            ),
            "sourceCommit": CROSS_LINE_SIM_COMMIT,
            "testFiles": 3,
            "tests": 13,
            "passed": 13,
            "failed": 0,
            "executedBySim": True,
        },
        "websiteHandoffPublicSite": {
            "command": "npx vitest run src/__tests__/PublicSite.test.tsx",
            "productSourceCommit": CROSS_LINE_WEBSITE_SOURCE,
            "evidenceHead": CROSS_LINE_WEBSITE_EVIDENCE,
            "tests": 20,
            "passed": 20,
            "failed": 0,
            "handedOffByChiefControl": True,
            "locallyReexecutedBySim": False,
        },
    }:
        raise SimYellowLifecycleError("cross-line test result classification drifted")

    classification = _exact_keys(
        observation["ownershipClassification"],
        CROSS_LINE_CLASSIFICATION_KEYS,
        "cross-line ownership classification",
    )
    if classification != {
        "classification": "website-owned-newer-site-evolution-absent-from-sim-snapshot",
        "ownerBranch": "codex/website",
        "blocksSimOwnedGates": False,
        "commonCoreFixRequiredOnSim": False,
        "allowedDisposition": "observe-and-defer-to-website-or-formal-common-core-sync",
        "forbiddenActions": [
            "modify-frontend-src-site",
            "modify-public-site-test",
            "copy-website-evolution-into-sim",
            "relabel-website-evidence-head-as-product-source",
            "fail-sim-owned-gate-from-cross-line-observation",
        ],
    }:
        raise SimYellowLifecycleError("cross-line ownership classification drifted")
    execution = _exact_keys(
        observation["execution"], CROSS_LINE_EXECUTION_KEYS, "cross-line execution"
    )
    if any(value is not False for value in execution.values()):
        raise SimYellowLifecycleError("cross-line adoption or execution claims must remain false")
    return observation


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
    cross_line_parser = subparsers.add_parser("verify-cross-line-observation")
    cross_line_parser.add_argument(
        "observation",
        type=Path,
        nargs="?",
        default=Path(
            "distribution/sim/quality/website-availability-observation.v1.json"
        ),
    )
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
        if args.command == "verify-cross-line-observation":
            validate_cross_line_test_observation(
                load_json(args.observation), repo_root=repo_root
            )
            return 0
        raise SimYellowLifecycleError(f"unsupported command: {args.command}")
    except SimYellowLifecycleError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
