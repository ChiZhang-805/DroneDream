#!/usr/bin/env python3
"""Verify Lab identity, coexistence, auth, and donor ownership contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "distribution/editions/lab/coexistence-and-auth.v1.json"
DONOR_PATH = ROOT / "distribution/editions/lab/universal-donor-requests.v1.json"
OVERLAY_PATH = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
BUILD_SCRIPT_PATH = ROOT / "desktop/scripts/build-lab-preview.ps1"
PROFILE_PATH = ROOT / "distribution/build-profiles/lab-preview.v1.json"
COMMON_CONTRACT_PATH = ROOT / "distribution/desktop/edition-coexistence.v1.json"
COMMON_SCHEMA_PATH = ROOT / "distribution/schemas/desktop-edition-coexistence.schema.json"
BUILD_RECEIPT_PATH = (
    ROOT
    / "distribution/build-receipts"
    / "lab-preview-1.0.0-978b902-yellow-attempt3.exact-artifact-blocked.json"
)
HANDOFF_PATH = ROOT / "distribution/editions/lab/website-exact-exe-handoff.awaiting.v1.json"


class LabCoexistenceContractError(ValueError):
    """Raised when Lab can collide with another Edition or overstate readiness."""


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LabCoexistenceContractError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LabCoexistenceContractError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise LabCoexistenceContractError(f"{label} must be an array")
    return value


def validate_contract(
    contract: dict[str, object],
    donor: dict[str, object],
    overlay: dict[str, object],
    profile: dict[str, object],
    build_script: str,
    build_receipt: dict[str, object],
    handoff: dict[str, object],
) -> dict[str, object]:
    if (
        contract.get("kind") != "dronedream-lab-four-edition-coexistence-and-auth"
        or contract.get("editionId") != "lab"
        or contract.get("auditMode") != "green-source-only"
        or contract.get("contractReady") is not True
        or contract.get("releaseReady") is not False
    ):
        raise LabCoexistenceContractError("Lab coexistence contract identity or readiness drifted")

    identities = _sequence(contract.get("identities"), "identities")
    if len(identities) != 4 or any(not isinstance(item, dict) for item in identities):
        raise LabCoexistenceContractError("exactly four Edition identities are required")
    by_edition = {item.get("editionId"): item for item in identities}
    if set(by_edition) != {"universal", "sim", "lab", "field"}:
        raise LabCoexistenceContractError("four Edition identity set drifted")
    for key in ("productName", "installerProductName", "identifier", "artifactFileName"):
        values = [item.get(key) for item in identities]
        if any(not isinstance(value, str) or not value for value in values):
            raise LabCoexistenceContractError(f"Edition {key} is missing")
        if len(set(values)) != 4:
            raise LabCoexistenceContractError(f"Edition {key} values must be unique")

    common_document = _load_json(COMMON_CONTRACT_PATH)
    common_editions = _sequence(common_document.get("editions"), "common editions")
    common_by_edition = {
        item.get("editionId"): item for item in common_editions if isinstance(item, dict)
    }
    if set(common_by_edition) != set(by_edition):
        raise LabCoexistenceContractError("common desktop Edition identity set drifted")
    common_identity_fields = {
        "productName": "displayName",
        "installerProductName": "installerProductName",
        "identifier": "bundleIdentifier",
        "artifactFileName": "artifactFileName",
    }
    for edition_id, local_identity in by_edition.items():
        common_identity = common_by_edition[edition_id]
        for local_field, common_field in common_identity_fields.items():
            if local_identity.get(local_field) != common_identity.get(common_field):
                raise LabCoexistenceContractError(
                    f"{edition_id} {local_field} drifted from common coexistence contract"
                )

    lab = by_edition["lab"]
    expected_lab = {
        "productName": "DroneDream · LAB",
        "installerProductName": "DroneDream-Lab",
        "identifier": "io.dronedream.desktop.lab",
        "artifactFileName": "DroneDream-Lab-1.0.0.exe",
        "updaterManifest": "lab-latest.json",
        "enginePackEditionProfile": "unified-sim-lab",
    }
    for key, expected in expected_lab.items():
        if lab.get(key) != expected:
            raise LabCoexistenceContractError(f"Lab {key} drifted")
    if lab["updaterManifest"] in {
        by_edition["universal"].get("updaterManifest"),
        by_edition["sim"].get("updaterManifest"),
        by_edition["field"].get("updaterManifest"),
    }:
        raise LabCoexistenceContractError("Lab updater channel collides with another Edition")

    derivation = _mapping(contract.get("identityDerivation"), "identityDerivation")
    expected_derivation = {
        "defaultInstallRoot": "%LOCALAPPDATA%\\{installerProductName}",
        "uninstallKey": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{installerProductName}",
        "manufacturerProductKey": "HKCU\\Software\\DroneDream\\{installerProductName}",
        "desktopShortcut": "%USERPROFILE%\\Desktop\\{productName}.lnk",
        "startMenuShortcut": "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{productName}.lnk",
        "appUserModelId": "{identifier}",
        "roamingAppData": "%APPDATA%\\{identifier}",
        "localAppData": "%LOCALAPPDATA%\\{identifier}",
    }
    for key, expected in expected_derivation.items():
        if derivation.get(key) != expected:
            raise LabCoexistenceContractError(f"identity derivation drifted: {key}")
    deletion_scope = _sequence(derivation.get("uninstallDeletionScope"), "uninstallDeletionScope")
    if not any("exact identifier" in str(item) for item in deletion_scope):
        raise LabCoexistenceContractError("Lab uninstall app-data deletion is not identifier scoped")

    common_contract = _mapping(
        contract.get("commonCoexistenceContract"),
        "commonCoexistenceContract",
    )
    common_manifest = _mapping(common_contract.get("manifest"), "common contract manifest")
    common_schema = _mapping(common_contract.get("schema"), "common contract schema")
    if (
        common_contract.get("prerequisiteCommit")
        != "2d19b045c11f5e78ae1a0b6554aee0d0ad382335"
        or common_contract.get("productDonorCommit")
        != "8a8ad6ce0ea619a52ec087b7f55142c24311165a"
        or common_contract.get("unknownProductDecision") != "deny"
        or common_contract.get("lifecycleExecutionEvidenceRequired") is not True
        or common_manifest.get("path")
        != "distribution/desktop/edition-coexistence.v1.json"
        or common_manifest.get("bytes") != COMMON_CONTRACT_PATH.stat().st_size
        or common_manifest.get("sha256") != _sha256(COMMON_CONTRACT_PATH)
        or common_schema.get("path")
        != "distribution/schemas/desktop-edition-coexistence.schema.json"
        or common_schema.get("bytes") != COMMON_SCHEMA_PATH.stat().st_size
        or common_schema.get("sha256") != _sha256(COMMON_SCHEMA_PATH)
    ):
        raise LabCoexistenceContractError("common desktop coexistence donor drifted")

    runtime = _mapping(contract.get("sharedRuntimeCoordination"), "sharedRuntimeCoordination")
    if (
        runtime.get("runtimeProductId") != "DroneDreamRuntime"
        or runtime.get("coordinatorNamespace") != "%LOCALAPPDATA%\\io.dronedream.desktop"
        or runtime.get("isAccountSessionStorage") is not False
        or runtime.get("isEditionProfileStorage") is not False
        or runtime.get("mayBeDeletedByLabUninstall") is not False
    ):
        raise LabCoexistenceContractError("shared Runtime coordination boundary drifted")

    brand = _mapping(contract.get("brandContinuity"), "brandContinuity")
    if (
        brand.get("displayName") != "DroneDream · LAB"
        or brand.get("separatorCodePoint") != "U+00B7"
        or brand.get("dotLockupState") != "canonical-large-label-donor-consumed"
        or brand.get("approvedEditionSuffixCapHeightRatio") != 0.9
        or brand.get("preserveNaturalEditionLabelWidth") is not True
        or brand.get("futureReleaseMustUsePendingDonor") is not False
        or brand.get("copyPolicy")
        != "exact canonical bytes and tokens; no redraw or concept-directory dependency"
        or brand.get("grantsHardwareAuthority") is not False
    ):
        raise LabCoexistenceContractError("Lab canonical brand policy drifted")
    expected_brand_files = {
        "markPath": "63d87e2ba200fb6d728a8b8bba96f7f593f216890a376e31b0796596405d0806",
        "dotLockupPath": "5abee1b88d50d0443fe47da0e4866257487856a2ee5269a213a1320585b6adea",
    }
    for path_key, expected_hash in expected_brand_files.items():
        relative = brand.get(path_key)
        if not isinstance(relative, str) or _sha256(ROOT / relative) != expected_hash:
            raise LabCoexistenceContractError(f"canonical Lab brand bytes drifted: {path_key}")
    canonical_donor = _mapping(brand.get("canonicalDonor"), "brandContinuity.canonicalDonor")
    if (
        canonical_donor.get("productCommit")
        != "b8e0d0c7093abe9f54fe36f01022deb95852fa39"
        or canonical_donor.get("productParentCommit")
        != "2d19b045c11f5e78ae1a0b6554aee0d0ad382335"
        or canonical_donor.get("evidenceCommit")
        != "7482647f1c2fcb92f58aaef009efc99764792297"
        or canonical_donor.get("receiptSha256")
        != "9f2e054cc9ce7ff612919e60b51894ab0bea54b58cb7140aa002bf058f174c94"
        or canonical_donor.get("evidenceCommitIsProductSource") is not False
    ):
        raise LabCoexistenceContractError("Lab canonical brand donor provenance drifted")
    tokens = _mapping(brand.get("tokens"), "brandContinuity.tokens")
    if (
        tokens.get("gradient") != ["#A7E84A", "#20C77A", "#087E69"]
        or tokens.get("light") != "#F3FCEF"
        or tokens.get("dark") != "#092019"
    ):
        raise LabCoexistenceContractError("Lab canonical green tokens drifted")
    surfaces = set(_sequence(brand.get("requiredSurfaces"), "requiredSurfaces"))
    if not {"executable", "taskbar", "login", "browser-callback", "website-download-metadata"} <= surfaces:
        raise LabCoexistenceContractError("Lab brand surface coverage is incomplete")

    authentication = _mapping(contract.get("authentication"), "authentication")
    requirements = _mapping(authentication.get("requirements"), "authentication.requirements")
    required_true = {
        "explicitLabLoginGestureEveryLocalSession",
        "browserSessionMayAvoidPasswordEntry",
        "callbackMustBindAppIdentity",
        "pkceVerifierMustBePerAttempt",
        "stateMustBePerAttemptAndBindAppIdentity",
        "nonceMustBePerAttemptAndBindAppIdentity",
        "credentialVaultMustBeEditionScoped",
        "localSessionMustBeEditionScoped",
    }
    required_false = {
        "browserSessionMaySilentlyAuthenticateLabWithoutGesture",
        "otherEditionSessionMayBeAdopted",
        "frontendMayAssertEditionIdentity",
    }
    if any(requirements.get(key) is not True for key in required_true) or any(
        requirements.get(key) is not False for key in required_false
    ):
        raise LabCoexistenceContractError("Lab authentication isolation requirements drifted")
    if (
        authentication.get("requiredLabAppIdentity") != "io.dronedream.desktop.lab"
        or authentication.get("requiredFlow") != "authorization-code-pkce-s256"
        or authentication.get("requiredCredentialVaultNamespace")
        != "io.dronedream.desktop.lab/auth"
        or authentication.get("requiredLocalSessionNamespace")
        != "io.dronedream.desktop.lab/session"
    ):
        raise LabCoexistenceContractError("Lab auth namespace or flow drifted")
    observation = _mapping(
        authentication.get("currentCommonCoreObservation"),
        "authentication.currentCommonCoreObservation",
    )
    if (
        observation.get("readyAsCanonicalAuthDonor") is not False
        or observation.get("editionBoundCallback") is not False
        or observation.get("pkceS256") is not False
        or observation.get("osCredentialVault") is not False
        or observation.get("crossEditionSilentAdoptionDenied") != "not-proven"
    ):
        raise LabCoexistenceContractError("current auth gaps must remain fail-closed")

    safety = _mapping(contract.get("safetyBoundary"), "safetyBoundary")
    if (
        safety.get("validatedVehiclePackCount") != 0
        or safety.get("workspaceOrThemeGrantsHardwareAuthority") is not False
        or safety.get("hardwareWriteArmHitlFlightDecision") != "deny"
        or safety.get("requiredAuthorityLayers") != ["native", "backend", "runtime"]
    ):
        raise LabCoexistenceContractError("zero-pack hardware safety boundary drifted")

    frozen = _mapping(contract.get("frozenArtifact"), "frozenArtifact")
    receipt_artifact = _mapping(build_receipt.get("artifact"), "build receipt artifact")
    handoff_artifact = _mapping(handoff.get("artifact"), "handoff artifact")
    for key in ("fileName", "bytes", "sha256"):
        if frozen.get(key) != receipt_artifact.get(key) or frozen.get(key) != handoff_artifact.get(key):
            raise LabCoexistenceContractError(f"frozen Lab artifact {key} was relabeled")
    if (
        frozen.get("sourceCommit") != "978b902fbe3038a526ab4970f55ea6eb37685c64"
        or frozen.get("overlayInstall") != "failed-exit-2"
        or frozen.get("mayBeRelabeledForThisContract") is not False
        or frozen.get("releaseReady") is not False
        or handoff.get("releaseReady") is not False
    ):
        raise LabCoexistenceContractError("frozen Lab failure evidence or readiness drifted")

    windows = overlay.get("app", {}).get("windows", [])
    if (
        overlay.get("productName") != expected_lab["installerProductName"]
        or overlay.get("identifier") != expected_lab["identifier"]
        or not isinstance(windows, list)
        or not windows
        or windows[0].get("title") != expected_lab["productName"]
    ):
        raise LabCoexistenceContractError("Lab Tauri product identity drifted")
    plugins = _mapping(overlay.get("plugins"), "Lab overlay plugins")
    updater = _mapping(plugins.get("updater"), "Lab updater")
    if updater.get("endpoints") != [
        "https://github.com/ChiZhang-805/DroneDream/releases/latest/download/lab-latest.json"
    ]:
        raise LabCoexistenceContractError("Lab updater endpoint is not edition scoped")
    resources = _mapping(_mapping(overlay.get("bundle"), "Lab bundle").get("resources"), "Lab resources")
    for source in (
        "../../distribution/desktop/edition-coexistence.v1.json",
        "../../distribution/schemas/desktop-edition-coexistence.schema.json",
        "../../distribution/editions/lab/coexistence-and-auth.v1.json",
        "../../distribution/editions/lab/universal-donor-requests.v1.json",
    ):
        if source not in resources:
            raise LabCoexistenceContractError("Lab coexistence resources are not bundled")
    if profile.get("editionPayload", {}).get("enginePackEditionProfile") != "unified-sim-lab":
        raise LabCoexistenceContractError("Lab Engine Pack profile is not explicit")
    if '$env:DRONEDREAM_EDITION_PROFILE = "unified-sim-lab"' not in build_script:
        raise LabCoexistenceContractError("Lab build does not pin its Engine Pack profile")

    if (
        donor.get("kind") != "dronedream-lab-universal-donor-requests"
        or donor.get("requestingEdition") != "lab"
    ):
        raise LabCoexistenceContractError("Universal donor request identity drifted")
    authority = _mapping(donor.get("authority"), "donor authority")
    if (
        authority.get("branch") != "codex/software"
        or authority.get("observedHead")
        != "8a8ad6ce0ea619a52ec087b7f55142c24311165a"
        or authority.get("observedProductSource")
        != "8a8ad6ce0ea619a52ec087b7f55142c24311165a"
        or authority.get("canonicalBrandProductSource")
        != "b8e0d0c7093abe9f54fe36f01022deb95852fa39"
        or authority.get("labMayCarrySharedFixLongTerm") is not False
        or "without hand-copying or blindly cherry-picking" not in str(authority.get("integrationRule"))
    ):
        raise LabCoexistenceContractError("shared fixes are not owned by Universal")
    requests = _sequence(donor.get("requests"), "donor requests")
    request_ids = {item.get("requestId") for item in requests if isinstance(item, dict)}
    if request_ids != {
        "universal-nsis-existing-install-quiesce-v1",
        "universal-edition-auth-isolation-v1",
        "universal-large-edition-lockup-brand-v1",
        "universal-edition-safety-fixture-binding-v1",
    }:
        raise LabCoexistenceContractError("required Universal donor requests are incomplete")
    for request in requests:
        item = _mapping(request, "donor request")
        if item.get("ownership") != "Universal/Core" or item.get("state") not in {
            "delivered-exact-donor-forward-synced",
            "awaiting-exact-donor",
            "requested-not-delivered",
        }:
            raise LabCoexistenceContractError("donor request overstates delivery")
        paths = _sequence(item.get("candidatePaths"), "donor candidate paths")
        if any(str(path).startswith("distribution/editions/lab/") for path in paths):
            raise LabCoexistenceContractError("shared donor request points into Lab ownership")
        if item.get("requestId") == "universal-nsis-existing-install-quiesce-v1":
            exact_donor = _mapping(item.get("exactDonor"), "NSIS exact donor")
            coexistence_donor = _mapping(
                item.get("coexistenceContractDonor"),
                "coexistence contract donor",
            )
            identity_donor = _mapping(
                item.get("installerIdentityDonor"),
                "installer identity donor",
            )
            if (
                exact_donor.get("commit") != "b099ed00923e9f2b833f812ad79f1614529038de"
                or exact_donor.get("parent") != "39d19414e4ac6649288726195f74afaf6dc58123"
                or exact_donor.get("integration") != "merge-parent-preserved"
                or coexistence_donor.get("commit")
                != "2d19b045c11f5e78ae1a0b6554aee0d0ad382335"
                or identity_donor.get("commit")
                != "8a8ad6ce0ea619a52ec087b7f55142c24311165a"
                or identity_donor.get("unknownProductDecision") != "deny"
                or identity_donor.get("labInstallerProductName") != "DroneDream-Lab"
                or identity_donor.get("labDisplayName") != "DroneDream · LAB"
            ):
                raise LabCoexistenceContractError("NSIS donor provenance drifted")
        if item.get("requestId") == "universal-large-edition-lockup-brand-v1":
            exact_donor = _mapping(item.get("exactDonor"), "brand exact donor")
            evidence = _mapping(item.get("evidence"), "brand donor evidence")
            receipt = _mapping(evidence.get("receipt"), "brand donor receipt")
            if (
                item.get("state") != "delivered-exact-donor-forward-synced"
                or exact_donor.get("commit")
                != "b8e0d0c7093abe9f54fe36f01022deb95852fa39"
                or exact_donor.get("parent")
                != "2d19b045c11f5e78ae1a0b6554aee0d0ad382335"
                or evidence.get("canonicalDotLockupSha256")
                != "5abee1b88d50d0443fe47da0e4866257487856a2ee5269a213a1320585b6adea"
                or evidence.get("canonicalDotLockupDimensions") != [2386, 218]
                or evidence.get("preserveNaturalEditionLabelWidth") is not True
                or receipt.get("commit")
                != "7482647f1c2fcb92f58aaef009efc99764792297"
                or receipt.get("isProductSource") is not False
            ):
                raise LabCoexistenceContractError("brand donor provenance drifted")
    recovery = _mapping(donor.get("labRecovery"), "labRecovery")
    if (
        recovery.get("rebuildAuthorizedByThisRequest") is not False
        or recovery.get("installAuthorizedByThisRequest") is not False
        or recovery.get("frozenArtifactMayBecomeFinalWithoutRebuild") is not False
    ):
        raise LabCoexistenceContractError("donor request improperly authorizes release work")

    blockers = _sequence(contract.get("crossEditionBlockers"), "crossEditionBlockers")
    blocker_text = " ".join(str(item) for item in blockers)
    for required in (
        "same latest.json",
        "authentication donor",
        "existing-install/quiesce",
        "large LAB suffix",
        "edition-safety allow-fixture",
        "predates this contract",
    ):
        if required not in blocker_text:
            raise LabCoexistenceContractError(f"cross-Edition blocker is missing: {required}")

    return {
        "contractReady": True,
        "releaseReady": False,
        "labIdentity": expected_lab,
        "frozenArtifactSha256": frozen["sha256"],
        "universalDonorRequestCount": len(requests),
        "remainingBlockerCount": len(blockers),
    }


def verify_lab_coexistence_contract() -> dict[str, object]:
    return validate_contract(
        _load_json(CONTRACT_PATH),
        _load_json(DONOR_PATH),
        _load_json(OVERLAY_PATH),
        _load_json(PROFILE_PATH),
        BUILD_SCRIPT_PATH.read_text(encoding="utf-8"),
        _load_json(BUILD_RECEIPT_PATH),
        _load_json(HANDOFF_PATH),
    )


if __name__ == "__main__":
    print(json.dumps(verify_lab_coexistence_contract(), indent=2, sort_keys=True))
