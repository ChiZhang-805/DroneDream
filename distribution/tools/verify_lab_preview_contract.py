#!/usr/bin/env python3
"""Verify the source-level Lab preview build contract."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "distribution/build-profiles/lab-preview.v1.json"
TAURI_OVERLAY = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
BUILD_SCRIPT = ROOT / "desktop/scripts/build-lab-preview.ps1"
SHARED_LLVM_BUILD_SCRIPT = ROOT / "desktop/scripts/build-windows-llvm.ps1"
WEBSITE_HANDOFF = (
    ROOT
    / "distribution"
    / "editions"
    / "lab"
    / "website-exact-exe-handoff.awaiting.v1.json"
)


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
    website_handoff = _load_json(WEBSITE_HANDOFF)
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    shared_llvm_script = SHARED_LLVM_BUILD_SCRIPT.read_text(encoding="utf-8")

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
        or authority.get("websiteExactExeHandoff")
        != "distribution/editions/lab/website-exact-exe-handoff.awaiting.v1.json"
    ):
        raise LabPreviewContractError("Lab preview source or Website handoff authority is missing")

    receiver = website_handoff.get("receiver")
    edition = website_handoff.get("edition")
    if (
        website_handoff.get("state") != "awaiting-exact-handoff"
        or website_handoff.get("releaseReady") is not False
        or not isinstance(receiver, dict)
        or receiver.get("websiteSourceCommit")
        != "afdcdee5b60883290c9d1cc0c036141920066659"
        or receiver.get("websiteEvidenceCommit")
        != "1a82e36b362c95983473c4a0d0d967d8c7415f92"
        or receiver.get("mode") != "read-only-receiver"
        or receiver.get("rebuildAllowed") is not False
        or receiver.get("renameAllowed") is not False
        or not isinstance(edition, dict)
        or edition.get("editionId") != "lab"
        or edition.get("fileName") != "DroneDream-Lab-1.0.0.exe"
    ):
        raise LabPreviewContractError("Website exact EXE receiving contract drifted")

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

    portable_patch = profile.get("portableCommonCorePatch")
    if (
        not isinstance(portable_patch, dict)
        or portable_patch.get("path") != "desktop/scripts/build-windows-llvm.ps1"
        or portable_patch.get("universalDefaultsPreserved") is not True
        or portable_patch.get("mustReturnToUniversal") is not True
        or portable_patch.get("mayRemainAsLabFork") is not False
    ):
        raise LabPreviewContractError("Lab shared LLVM parameterization is not portable to Universal")

    if tuple(profile.get("labDeltaPaths", ())) != (
        "desktop/scripts/build-lab-preview.ps1",
        "desktop/src-tauri/tauri.lab-preview.conf.json",
        "distribution/build-profiles/lab-preview.v1.json",
        "distribution/editions/lab.v1.json",
        "distribution/editions/lab",
        "distribution/schemas/lab-preview-artifact-receipt.schema.json",
        "distribution/schemas/lab-website-exact-exe-handoff.schema.json",
        "distribution/tests/test_lab_brand_assets.py",
        "distribution/tests/test_lab_preview_contract.py",
        "distribution/tests/test_lab_website_handoff.py",
        "distribution/tools/lab_yellow_readiness_audit.py",
        "distribution/tools/lab_preinstall_acceptance.py",
        "distribution/tools/verify_lab_preview_artifact.py",
        "distribution/tools/verify_lab_preview_contract.py",
        "distribution/tools/verify_lab_website_handoff.py",
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
        or payload.get("websiteHandoffContract")
        != "distribution/editions/lab/website-exact-exe-handoff.awaiting.v1.json"
        or payload.get("websiteHandoffSchema")
        != "distribution/schemas/lab-website-exact-exe-handoff.schema.json"
        or payload.get("websiteHandoffVerifier")
        != "distribution/tools/verify_lab_website_handoff.py"
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

    toolchain = profile.get("toolchainPolicy")
    if not isinstance(toolchain, dict):
        raise LabPreviewContractError("Lab pinned gnullvm toolchain policy is missing")
    rust = toolchain.get("rust")
    llvm = toolchain.get("llvmMingw")
    loader = toolchain.get("webView2Loader")
    tauri_cli = toolchain.get("tauriCli")
    nsis = toolchain.get("nsis")
    environment = toolchain.get("environment")
    if (
        toolchain.get("selection") != "strict-pinned-gnullvm"
        or toolchain.get("targetTriple") != "x86_64-pc-windows-gnullvm"
        or toolchain.get("requiresMsvcLinkExe") is not False
        or toolchain.get("sharedBuildScript") != "desktop/scripts/build-windows-llvm.ps1"
        or not isinstance(rust, dict)
        or rust.get("rustupToolchain") != "1.97.0-x86_64-pc-windows-gnullvm"
        or rust.get("rustcCommitHash")
        != "2d8144b7880597b6e6d3dfd63a9a9efae3f533d3"
        or rust.get("cargoCommitHash")
        != "c980f4866141969fab6254a680546a277789d6f0"
        or not isinstance(llvm, dict)
        or llvm.get("wingetPackageId") != "MartinStorsjo.LLVM-MinGW.UCRT"
        or llvm.get("packageDirectoryName") != "llvm-mingw-20260616-ucrt-x86_64"
        or llvm.get("clangVersion") != "22.1.8"
        or llvm.get("clangTarget") != "x86_64-w64-windows-gnu"
        or not isinstance(loader, dict)
        or loader.get("cargoPackage") != "webview2-com-sys"
        or loader.get("cargoPackageVersion") != "0.38.2"
        or loader.get("sha256")
        != "8427b1fc58ec707813e5c0a51eb5d69397bb333250a7b891be4d3b123f1e0f1c"
        or not isinstance(tauri_cli, dict)
        or tauri_cli.get("version") != "2.11.4"
        or not isinstance(nsis, dict)
        or nsis.get("executableSha256")
        != "42850802704ecb11163f7e0329d35ee54bd288953200d4966e226d572848cfc5"
        or nsis.get("invocationForbiddenDuringGreenAudit") is not True
        or not isinstance(environment, dict)
        or environment.get("cargoTargetDir")
        != "C:\\Users\\zju20\\AppData\\Local\\DroneDream\\codex-cache\\lab-cargo-target"
        or environment.get("cargoBuildJobsMaximum") != 4
        or environment.get("rustflags") != "-C target-feature=+crt-static"
        or environment.get("additionalConfigTransport") != "TAURI_CONFIG"
        or environment.get("preserveBundleHistory") is not True
        or environment.get("allowUnsignedUpdater") is not True
    ):
        raise LabPreviewContractError("Lab pinned gnullvm toolchain policy drifted")
    expected_llvm_tools = {
        "x86_64-w64-mingw32-clang.exe": (
            16896,
            "a8b7a614eeadd9105f814be3701a7f312cda4cea51751b75b408c16100c94e85",
        ),
        "llvm-dlltool.exe": (
            67072,
            "9aa88ccb0a10c4d6c6f922e73cb9445ea83be29c52614726aea92b25f2c86093",
        ),
        "llvm-rc.exe": (
            156672,
            "255fc12528b80cade02a4f8393065221dbd1f3a7fdf930a4e21c3076399750f5",
        ),
        "llvm-readobj.exe": (
            1611776,
            "3088728b4588ca185687dac94aed3aca1d379b31433053d824b89b0d4d28d246",
        ),
        "ld.lld.exe": (
            5219840,
            "ebc594a240cd325f1ea8b865ee88da0d004e94ea31eb1fc3f7f8f0ff8d93f58f",
        ),
    }
    observed_llvm_tools = {
        entry.get("name"): (entry.get("bytes"), entry.get("sha256"))
        for entry in llvm.get("requiredTools", ())
        if isinstance(entry, dict)
    }
    if observed_llvm_tools != expected_llvm_tools:
        raise LabPreviewContractError("Lab pinned LLVM-MinGW tool inventory drifted")

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
        "websiteReceiverReadOnly",
        "forbidWebsiteRebuild",
        "forbidWebsiteRename",
        "requiresStrictPinnedGnullvm",
        "forbidMsvcLinkerDependency",
        "requireUnsignedUpdaterSlotEmpty",
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
        'websiteHandoffContract = New-RepoFileRef "distribution\\editions\\lab\\website-exact-exe-handoff.awaiting.v1.json"',
        'grantsHardwareAuthority = $false',
        '[ValidateSet("gnullvm")]',
        '$readiness.toolchain.selectedToolchain',
        '$gnullvm.strictlyPinnedReady',
        'build-windows-llvm.ps1',
        '-AdditionalConfigPath',
        '-CargoTargetDir $cargoTargetFull',
        '-LlvmRoot $gnullvm.llvmRoot',
        '-AllowUnsignedUpdater',
        '-PreserveBundleHistory',
        'x86_64-pc-windows-gnullvm\\release\\bundle\\nsis',
        'unexpectedly has an updater signature',
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
        "npm.cmd --prefix",
    )
    for fragment in forbidden_script_fragments:
        if fragment in script:
            raise LabPreviewContractError(f"Lab build script contains forbidden text: {fragment}")

    required_shared_fragments = (
        '[string]$AdditionalConfigPath',
        '[string]$CargoTargetDir',
        '[string]$LlvmRoot',
        '[string]$ExpectedProductName = "DroneDream"',
        '[switch]$AllowUnsignedUpdater',
        '[switch]$PreserveBundleHistory',
        '$env:TAURI_CONFIG = $additionalConfigText',
        '$env:CARGO_TARGET_DIR = $cargoTargetRoot',
        'invoke-tauri-updater-signer.ps1',
        'if (-not $AllowUnsignedUpdater)',
        'if (-not $PreserveBundleHistory)',
    )
    for fragment in required_shared_fragments:
        if fragment not in shared_llvm_script:
            raise LabPreviewContractError(
                f"Shared LLVM build parameterization is missing: {fragment}"
            )

    return {
        "profile": PROFILE.relative_to(ROOT).as_posix(),
        "overlay": TAURI_OVERLAY.relative_to(ROOT).as_posix(),
        "script": BUILD_SCRIPT.relative_to(ROOT).as_posix(),
        "artifactFileName": payload["artifactFileName"],
    }


if __name__ == "__main__":
    result = verify_lab_preview_contract()
    print(json.dumps(result, indent=2, sort_keys=True))
