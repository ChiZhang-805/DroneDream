#!/usr/bin/env python3
"""Verify the source-level Lab preview build contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "distribution/build-profiles/lab-preview.v1.json"
TAURI_OVERLAY = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
BUILD_SCRIPT = ROOT / "desktop/scripts/build-lab-preview.ps1"


class LabPreviewContractError(ValueError):
    """Raised when the Lab preview profile can overstate release readiness."""


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LabPreviewContractError(f"{path} must contain a JSON object")
    return value


def verify_lab_preview_contract() -> dict[str, object]:
    profile = _load_json(PROFILE)
    overlay = _load_json(TAURI_OVERLAY)
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    if profile.get("kind") != "dronedream-lab-preview-build-profile":
        raise LabPreviewContractError("Lab preview profile identity is unsupported")
    if profile.get("editionId") != "lab" or profile.get("state") != "source-contract-only":
        raise LabPreviewContractError("Lab preview profile overstates implementation state")
    authority = profile.get("authority")
    if (
        not isinstance(authority, dict)
        or authority.get("brandSourceManifest")
        != "brand/brand-editions.v1.json"
        or authority.get("labBrandSourceManifest")
        != "distribution/editions/lab/brand-source-manifest.v1.json"
    ):
        raise LabPreviewContractError("Lab preview brand source authority is missing")

    common_core = profile.get("commonCore")
    if not isinstance(common_core, dict):
        raise LabPreviewContractError("Lab preview common-core contract is missing")
    if (
        common_core.get("authorityName") != "Universal/Core"
        or common_core.get("authorityBranch") != "codex/software"
        or common_core.get("simIsCommonAuthority") is not False
        or common_core.get("productSourceCommit") != "e374d3f8d96b1265fcdb06864208b676566e94d9"
        or common_core.get("productSourceHash")
        != "b2a1d8479dd06616430e8eea9ec720f831ccaec5f5408032bc85eb3d9a0825e9"
        or common_core.get("excludedPreviewEvidenceCommit")
        != "e097b9ea057468bf1602ad1f1c4c5c5e88a65571"
        or common_core.get("hashSource")
        != "fixed Universal/Core product source commit, not origin/codex/software moving head"
    ):
        raise LabPreviewContractError("Lab preview common-core authority drifted")
    if common_core.get("reuseOnly") is not True or common_core.get("forkOrCopyAllowed") is not False:
        raise LabPreviewContractError("Lab preview must reuse the common core without source forks")
    if tuple(common_core.get("paths", ())) != (
        "backend",
        "desktop",
        "engine-pack",
        "frontend",
        "runtime",
        "worker",
    ):
        raise LabPreviewContractError("Lab preview common-core path set drifted")
    if tuple(common_core.get("receiptFields", ())) != ("commonCoreCommit", "commonCoreHash"):
        raise LabPreviewContractError("Lab preview receipts must bind the common core commit and hash")

    if tuple(profile.get("labDeltaPaths", ())) != (
        "desktop/scripts/build-lab-preview.ps1",
        "desktop/src-tauri/tauri.lab-preview.conf.json",
        "distribution/build-profiles/lab-preview.v1.json",
        "distribution/editions/lab.v1.json",
        "distribution/editions/lab",
        "distribution/schemas/lab-preview-artifact-receipt.schema.json",
        "distribution/tests/test_lab_brand_assets.py",
        "distribution/tests/test_lab_preview_contract.py",
        "distribution/tools/lab_yellow_readiness_audit.py",
        "distribution/tools/lab_preinstall_acceptance.py",
        "distribution/tools/verify_lab_preview_artifact.py",
        "distribution/tools/verify_lab_preview_contract.py",
        "frontend/package.json",
        "frontend/scripts/verify-lab-ui.mjs",
        "frontend/src/AppShell.tsx",
        "frontend/src/__tests__/edition.test.ts",
        "frontend/src/__tests__/router.test.ts",
        "frontend/src/edition.ts",
        "frontend/src/features/distribution/catalog.v1.json",
        "frontend/src/i18n/I18nProvider.tsx",
        "frontend/src/lab",
        "frontend/src/router.tsx",
        "frontend/src/vite-env.d.ts",
    ):
        raise LabPreviewContractError("Lab preview delta paths drifted")

    workspaces = profile.get("workspaces")
    if not isinstance(workspaces, dict) or set(workspaces) != {"simulation", "hardwareLab"}:
        raise LabPreviewContractError("Lab preview workspaces are missing")
    for name, workspace_id in (("simulation", "simulation"), ("hardwareLab", "hardware-lab")):
        workspace = workspaces[name]
        if not isinstance(workspace, dict):
            raise LabPreviewContractError(f"{name} workspace must be an object")
        if (
            workspace.get("workspaceId") != workspace_id
            or workspace.get("authority") != "ui-workflow-only"
            or workspace.get("switchEffect") != "changes interface and workflow only"
            or workspace.get("countsTowardNativeBackendRuntimeAuthority") is not False
        ):
            raise LabPreviewContractError(f"{name} workspace authority drifted")
        if tuple(workspace.get("deniedHardwareActions", ())) != (
            "hardware.parameter.write",
            "hardware.arm",
            "hardware.flight",
            "hardware.hitl.execute",
        ):
            raise LabPreviewContractError(f"{name} workspace must deny hardware actions")

    payload = profile.get("editionPayload")
    if not isinstance(payload, dict):
        raise LabPreviewContractError("Lab preview payload contract is missing")
    if payload.get("artifactFileName") != "DroneDream-Lab-1.0.0.exe":
        raise LabPreviewContractError("Lab preview artifact filename drifted")
    if payload.get("tauriConfigOverlay") != "desktop/src-tauri/tauri.lab-preview.conf.json":
        raise LabPreviewContractError("Lab preview Tauri overlay path drifted")
    brand = payload.get("brand")
    if (
        not isinstance(brand, dict)
        or brand.get("displayName") != "DroneDream · LAB"
        or brand.get("canonicalDonorCommit")
        != "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235"
        or brand.get("canonicalDonorManifest") != "brand/brand-editions.v1.json"
        or brand.get("labSourceManifest")
        != "distribution/editions/lab/brand-source-manifest.v1.json"
        or brand.get("applicationLockup")
        != "brand/generated/lab/lockup-compact.png"
        or brand.get("windowsIcon")
        != "brand/generated/lab/windows/icon.ico"
        or brand.get("grantsHardwareAuthority") is not False
    ):
        raise LabPreviewContractError("Lab preview brand payload drifted or grants authority")
    if (
        payload.get("artifactReceiptSchema")
        != "distribution/schemas/lab-preview-artifact-receipt.schema.json"
        or payload.get("artifactVerifier") != "distribution/tools/verify_lab_preview_artifact.py"
        or payload.get("preinstallAcceptanceTool")
        != "distribution/tools/lab_preinstall_acceptance.py"
        or payload.get("yellowReadinessAuditTool")
        != "distribution/tools/lab_yellow_readiness_audit.py"
        or payload.get("firmwareFamily") != "px4"
        or payload.get("qualificationReceiptRequired") is not True
        or tuple(payload.get("simulationPayload", ()))
        != (
            "runtime-simulation",
            "simulator-gazebo-harmonic",
            "simulator-px4-sitl",
            "vehicle-pack-sim",
        )
        or tuple(payload.get("gatedHardwareAdapter", ()))
        != ("hardware-bridge", "vehicle-pack-hardware", "vehicle-pack-validation")
    ):
        raise LabPreviewContractError("Lab preview payload dependency graph drifted")

    guards = profile.get("buildGuards")
    signature = profile.get("signaturePolicy")
    safety = profile.get("safetyPolicy")
    if not isinstance(guards, dict) or not isinstance(signature, dict) or not isinstance(safety, dict):
        raise LabPreviewContractError("Lab preview guard, signature, or safety policy is missing")
    for key in (
        "requiresExactCleanSource",
        "requiresUniversalCoreAncestor",
        "requiresOriginSoftwareAncestor",
        "rejectFieldOnlyContent",
        "rejectUniversalBootstrapperContent",
        "forbidRepositoryTargetDirectory",
        "forbidReleaseBranchCreation",
        "forbidForcePush",
        "forbidSigningSecretRead",
        "doNotOverwritePublicAssets",
    ):
        if guards.get(key) is not True:
            raise LabPreviewContractError(f"Lab preview guard is not enforced: {key}")
    if (
        signature.get("authenticode") != "not-signed"
        or signature.get("tauriUpdaterSignature") != "not-issued"
        or signature.get("mustNotClaimSigned") is not True
    ):
        raise LabPreviewContractError("Lab preview signature policy overstates signing")
    if safety.get("validatedVehiclePackCount") != 0:
        raise LabPreviewContractError("Lab preview must retain the zero-validated-pack state")
    if safety.get("uiCanAuthorizeHardwareAction") is not False:
        raise LabPreviewContractError("Lab preview UI must not authorize hardware actions")
    if tuple(safety.get("requiredDecisionLayers", ())) != ("native", "backend", "runtime"):
        raise LabPreviewContractError("Lab preview hardware actions must require the three-layer quorum")

    frontend = profile.get("frontend")
    if not isinstance(frontend, dict):
        raise LabPreviewContractError("Lab preview frontend contract is missing")
    if (
        frontend.get("implementationState") != "green-source-implemented"
        or frontend.get("buildEnvironmentVariable") != "VITE_DRONEDREAM_EDITION"
        or frontend.get("buildEnvironmentValue") != "lab"
        or frontend.get("route") != "/lab/setup"
        or frontend.get("sourceRoot") != "frontend/src/lab"
        or frontend.get("vehiclePackAdapter")
        != "frontend/src/lab/vehicle-pack-adapter.v1.json"
        or frontend.get("workspaceSwitchCountsAsAuthority") is not False
        or frontend.get("hardwareActionDecisionAtZeroValidatedPacks") != "deny"
    ):
        raise LabPreviewContractError("Lab preview frontend boundary drifted")

    if overlay.get("productName") != "DroneDream · LAB":
        raise LabPreviewContractError("Lab Tauri overlay must create a distinct product name")
    if overlay.get("identifier") == "io.dronedream.desktop":
        raise LabPreviewContractError("Lab Tauri overlay must not reuse the base app identifier")
    resources = overlay.get("bundle", {}).get("resources", {}) if isinstance(overlay.get("bundle"), dict) else {}
    if not isinstance(resources, dict) or "../../distribution/build-profiles/lab-preview.v1.json" not in resources:
        raise LabPreviewContractError("Lab Tauri overlay must bundle the source Lab profile")
    bundle = overlay.get("bundle")
    if not isinstance(bundle, dict) or tuple(bundle.get("icon", ())) != (
        "../../brand/generated/lab/windows/32x32.png",
        "../../brand/generated/lab/windows/128x128.png",
        "../../brand/generated/lab/windows/128x128@2x.png",
        "../../brand/generated/lab/windows/icon.ico",
    ):
        raise LabPreviewContractError("Lab Tauri overlay icon set drifted")
    for required_brand_resource in (
        "../../distribution/editions/lab/brand-source-manifest.v1.json",
        "../../distribution/editions/lab/assets/dronedream-lab-mark-v2.png",
        "../../distribution/editions/lab/assets/dronedream-lab-dot-lockup-v2.png",
        "../../brand/brand-editions.v1.json",
        "../../brand/generated/brand-assets.v1.json",
        "../../brand/generated/brand-visual-receipt.v1.json",
    ):
        if required_brand_resource not in resources:
            raise LabPreviewContractError("Lab Tauri overlay brand resources are incomplete")
    windows = overlay.get("app", {}).get("windows", []) if isinstance(overlay.get("app"), dict) else []
    if not isinstance(windows, list) or not windows or windows[0].get("title") != "DroneDream · LAB":
        raise LabPreviewContractError("Lab Tauri window title drifted")

    required_script_fragments = (
        'param(',
        '[switch]$Build',
        'status", "--porcelain=v1", "--untracked-files=all',
        '$commonCoreCommit = "e374d3f8d96b1265fcdb06864208b676566e94d9"',
        '$excludedPreviewEvidenceCommit = "e097b9ea057468bf1602ad1f1c4c5c5e88a65571"',
        'merge-base --is-ancestor $commonCoreCommit HEAD',
        'TAURI_SIGNING_PRIVATE_KEY_PATH',
        'TAURI_SIGNING_PRIVATE_KEY_PASSWORD',
        'DroneDream\\codex-cache\\lab-cargo-target',
        'desktop\\src-tauri\\target',
        'Lab preview contract verified',
        'Pass -Build to create the unsigned internal preview',
        'commonCoreCommit = $commonCoreCommit',
        'kind = "dronedream-lab-preview-artifact-receipt"',
        'uiSwitchCountsAsAuthority = $false',
        'hardwareActionDecision = "deny"',
        'authenticode',
        'tauriUpdaterSignature = "not-issued"',
        'VITE_DRONEDREAM_EDITION = "lab"',
        'Get-Sha256Text $coreListing.Trim()',
        '$tauriProductName = "DroneDream · LAB"',
        'brand-source-manifest.v1.json',
        'canonicalDonor = New-RepoFileRef "brand\\brand-editions.v1.json"',
        'grantsHardwareAuthority = $false',
    )
    for fragment in required_script_fragments:
        if fragment not in script:
            raise LabPreviewContractError(f"Lab build script is missing: {fragment}")
    forbidden_script_fragments = (
        "TAURI_SIGNING_PRIVATE_KEY_PATH |",
        "invoke-tauri-updater-signer.ps1",
        "git push",
        "codex/release-lab",
        "--force",
    )
    for fragment in forbidden_script_fragments:
        if fragment in script:
            raise LabPreviewContractError(f"Lab build script contains forbidden text: {fragment}")

    return {
        "profile": PROFILE.relative_to(ROOT).as_posix(),
        "overlay": TAURI_OVERLAY.relative_to(ROOT).as_posix(),
        "script": BUILD_SCRIPT.relative_to(ROOT).as_posix(),
        "artifactFileName": payload["artifactFileName"],
    }


if __name__ == "__main__":
    result = verify_lab_preview_contract()
    print(json.dumps(result, indent=2, sort_keys=True))
