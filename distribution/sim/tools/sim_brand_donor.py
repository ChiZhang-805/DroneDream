#!/usr/bin/env python3
"""Fail-closed validation for approved and future canonical SIM brand assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_PATH_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"
)
COMMON_CORE_PATHS = ("backend", "desktop", "engine-pack", "frontend", "runtime", "worker")
CONCEPT_HANDOFF_SHA256 = "9fc52dea2edab1b65aa8c814fbf05ff1ad4fea0de4980403bec84dab8a1d9657"
MINIMUM_COMMON_CORE_ANCESTOR = "e374d3f8d96b1265fcdb06864208b676566e94d9"
SIM_IDENTITY = {
    "masterName": "DroneDream",
    "displayName": "DroneDream · SIM",
    "separator": " · ",
}
SIM_PALETTE = {"start": "#00D9FF", "middle": "#2671FF", "end": "#744CFF"}
ASSET_REQUIREMENTS = {
    "master-mark-svg": ("image/svg+xml", None),
    "sim-mark-svg": ("image/svg+xml", None),
    "sim-lockup-svg": ("image/svg+xml", None),
    "sim-icon-png-32": ("image/png", 32),
    "sim-icon-png-128": ("image/png", 128),
    "sim-icon-png-256": ("image/png", 256),
    "sim-icon-png-512": ("image/png", 512),
    "sim-windows-ico": ("image/x-icon", None),
}

INTAKE_KEYS = {
    "schemaVersion",
    "kind",
    "contractVersion",
    "editionId",
    "state",
    "approvedConceptHandoffSha256",
    "expectedSource",
    "expectedIdentity",
    "expectedPalette",
    "requiredAssetRoles",
    "manifestSchema",
    "integrationRequirements",
    "nonClaims",
}
INTAKE_SOURCE_KEYS = {
    "branch",
    "minimumCommonCoreAncestor",
    "commonCorePaths",
    "donorAndCommonCoreCommitMustMatch",
    "sourceAndEvidenceCommitMustDiffer",
}
FILE_REF_KEYS = {"path", "sha256"}
MANIFEST_KEYS = {
    "schemaVersion",
    "kind",
    "manifestVersion",
    "editionId",
    "source",
    "identity",
    "palette",
    "assets",
    "preservation",
    "review",
}
MANIFEST_SOURCE_KEYS = {
    "branch",
    "donorCommit",
    "evidenceCommit",
    "commonCoreCommit",
    "commonCoreHash",
    "commonCorePaths",
    "approvedConceptHandoffSha256",
}
ASSET_KEYS = {"role", "path", "sha256", "bytes", "mimeType", "width", "height"}
PRESERVATION_KEYS = {
    "sourceMasterPath",
    "sourceMasterSha256",
    "originalWingShapePreserved",
    "whiteFlightPathPreserved",
    "masterWordmarkPreserved",
    "masterRedrawn",
}
REVIEW_KEYS = {"status", "releaseUseAuthorized", "conceptOnly", "approvalReference"}

APPROVED_MANIFEST_KEYS = {
    "schemaVersion",
    "kind",
    "manifestVersion",
    "editionId",
    "schema",
    "authorization",
    "identity",
    "palette",
    "commonCoreBinding",
    "sourceHandoff",
    "assets",
    "integrationState",
}
APPROVED_AUTHORIZATION_KEYS = {
    "status",
    "sourceThreadId",
    "authorizationDate",
    "allowedUse",
    "byteForByteCopyRequired",
    "derivativeExportAuthorized",
}
APPROVED_BINDING_KEYS = {
    "branchContract",
    "commonCoreCommit",
    "commonCoreHash",
    "commonCorePaths",
    "bindingScope",
    "canonicalUniversalDonorIntegrated",
}
APPROVED_HANDOFF_KEYS = {"path", "sha256", "statusAtHandoff"}
APPROVED_ASSET_KEYS = {"role", "source", "destination", "exactByteCopy", "approved"}
APPROVED_LOCATION_KEYS = {
    "path",
    "fileName",
    "sha256",
    "bytes",
    "mimeType",
    "width",
    "height",
}
APPROVED_INTEGRATION_KEYS = {
    "assetBytesVendored",
    "applicationSourceWired",
    "installerIconOverridePresent",
    "windowsIcoGenerated",
    "browserAcceptanceExecuted",
    "productionBuildExecuted",
    "installerBuilt",
    "canonicalUniversalDonorIntegrated",
    "promotionReady",
}
APPROVED_SOURCE_THREAD_ID = "019fa6ec-e8e6-7222-8c4c-1a064d17a0a9"
APPROVED_SCHEMA_PATH = "distribution/sim/brand/approved-edition-assets.schema.json"
APPROVED_HANDOFF_PATH = (
    "Z:/DroneDream/work/brand-edition-concepts-v1/BRAND_EDITION_HANDOFF_V2.md"
)
APPROVED_ASSET_REQUIREMENTS = {
    "sim-mark-png": {
        "sourcePath": (
            "Z:/DroneDream/work/brand-edition-concepts-v1/"
            "dronedream-sim-mark-concept-v1.png"
        ),
        "sourceFileName": "dronedream-sim-mark-concept-v1.png",
        "destinationPath": "frontend/src/editions/sim/assets/dronedream-sim-mark.png",
        "destinationFileName": "dronedream-sim-mark.png",
        "sha256": "5b35f8eeccb2742d53888d222e9b6c12b449e03af927a1b7631175e8ac510dfa",
        "bytes": 162699,
        "width": 1024,
        "height": 1024,
    },
    "sim-dot-lockup-png": {
        "sourcePath": (
            "Z:/DroneDream/work/brand-edition-concepts-v1/"
            "dronedream-sim-dot-lockup-concept-v2.png"
        ),
        "sourceFileName": "dronedream-sim-dot-lockup-concept-v2.png",
        "destinationPath": (
            "frontend/src/editions/sim/assets/dronedream-sim-dot-lockup.png"
        ),
        "destinationFileName": "dronedream-sim-dot-lockup.png",
        "sha256": "8cd55f8008bf1c634c9c1b72a59c4ca21a625413bc71a6c421899e347b650548",
        "bytes": 77713,
        "width": 1840,
        "height": 340,
    },
}


class SimBrandDonorError(ValueError):
    """Raised when canonical donor evidence is incomplete or inconsistent."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimBrandDonorError(f"could not read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SimBrandDonorError(f"JSON document must be an object: {path}")
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SimBrandDonorError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise SimBrandDonorError(
            f"{label} keys drifted (missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)})"
        )
    return value


def _safe_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_PATH_RE.fullmatch(value):
        raise SimBrandDonorError(f"{label} is not a safe repository-relative path")
    return value


def _resolve(repo_root: Path, value: Any, label: str) -> Path:
    relative = _safe_path(value, label)
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SimBrandDonorError(f"{label} escapes repository root") from exc
    if not candidate.is_file():
        raise SimBrandDonorError(f"{label} does not exist: {relative}")
    return candidate


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SimBrandDonorError(f"{label} is not a SHA-256 digest")
    return value


def _commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise SimBrandDonorError(f"{label} is not a Git commit")
    return value


def _run_git(repo_root: Path, *args: str, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    if completed.returncode != 0:
        error = completed.stderr if binary else completed.stderr.strip()
        if isinstance(error, bytes):
            detail = error.decode("utf-8", errors="replace").strip()
        else:
            detail = error
        raise SimBrandDonorError(detail or f"git {' '.join(args)} failed")
    return completed.stdout


def _git_asset_reader(repo_root: Path, commit: str, relative_path: str) -> bytes:
    output = _run_git(repo_root, "show", f"{commit}:{relative_path}", binary=True)
    if not isinstance(output, bytes):
        raise SimBrandDonorError("git asset reader returned text unexpectedly")
    return output


def _git_common_core_hash(repo_root: Path, commit: str, paths: tuple[str, ...]) -> str:
    output = _run_git(
        repo_root,
        "ls-tree",
        "-r",
        "--full-tree",
        commit,
        "--",
        *paths,
    )
    if not isinstance(output, str) or not output.strip():
        raise SimBrandDonorError("common-core inventory is empty")
    return sha256_bytes(output.encode("utf-8"))


def _git_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
        capture_output=True,
    )
    if completed.returncode not in {0, 1}:
        raise SimBrandDonorError("could not verify donor Git ancestry")
    return completed.returncode == 0


def _validate_asset_signature(payload: bytes, mime_type: str, label: str) -> None:
    if mime_type == "image/svg+xml" and b"<svg" not in payload[:1024].lower():
        raise SimBrandDonorError(f"{label} is not recognizable SVG content")
    if mime_type == "image/png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SimBrandDonorError(f"{label} is not recognizable PNG content")
    if mime_type == "image/x-icon" and not payload.startswith(b"\x00\x00\x01\x00"):
        raise SimBrandDonorError(f"{label} is not recognizable ICO content")


def validate_donor_intake(document: Any, *, repo_root: Path) -> dict[str, Any]:
    intake = _exact_keys(document, INTAKE_KEYS, "Sim brand donor intake")
    if (
        intake["schemaVersion"] != 1
        or intake["kind"] != "dronedream-sim-brand-donor-intake-contract"
        or intake["contractVersion"] != "1.0.0"
        or intake["editionId"] != "sim"
        or intake["state"] != "awaiting-canonical-donor"
        or intake["approvedConceptHandoffSha256"] != CONCEPT_HANDOFF_SHA256
    ):
        raise SimBrandDonorError("Sim brand donor intake identity drifted")

    source = _exact_keys(intake["expectedSource"], INTAKE_SOURCE_KEYS, "intake.expectedSource")
    if source != {
        "branch": "codex/software",
        "minimumCommonCoreAncestor": MINIMUM_COMMON_CORE_ANCESTOR,
        "commonCorePaths": list(COMMON_CORE_PATHS),
        "donorAndCommonCoreCommitMustMatch": True,
        "sourceAndEvidenceCommitMustDiffer": True,
    }:
        raise SimBrandDonorError("Sim donor source requirements drifted")
    if intake["expectedIdentity"] != SIM_IDENTITY or intake["expectedPalette"] != SIM_PALETTE:
        raise SimBrandDonorError("Sim donor identity or palette drifted")
    if intake["requiredAssetRoles"] != list(ASSET_REQUIREMENTS):
        raise SimBrandDonorError("Sim donor required asset roles drifted")

    schema_ref = _exact_keys(intake["manifestSchema"], FILE_REF_KEYS, "intake.manifestSchema")
    schema_path = _resolve(repo_root, schema_ref["path"], "intake.manifestSchema.path")
    if sha256_file(schema_path) != _sha(schema_ref["sha256"], "intake.manifestSchema.sha256"):
        raise SimBrandDonorError("Sim donor manifest schema SHA-256 drifted")
    schema = load_json(schema_path)
    if schema.get("additionalProperties") is not False:
        raise SimBrandDonorError("Sim donor manifest schema must remain closed")

    requirements = intake["integrationRequirements"]
    if (
        not isinstance(requirements, list)
        or len(requirements) != 10
        or len(set(requirements)) != 10
    ):
        raise SimBrandDonorError("Sim donor integration requirements drifted")
    non_claims = intake["nonClaims"]
    if not isinstance(non_claims, dict) or not non_claims:
        raise SimBrandDonorError("Sim donor non-claims are missing")
    if any(value is not False for value in non_claims.values()):
        raise SimBrandDonorError("pending Sim donor non-claims must remain false")
    return intake


def validate_canonical_donor_manifest(
    document: Any,
    *,
    intake: dict[str, Any],
    repo_root: Path,
    asset_reader: Callable[[Path, str, str], bytes] = _git_asset_reader,
    common_core_hash_observer: Callable[[Path, str, tuple[str, ...]], str] = _git_common_core_hash,
    ancestry_observer: Callable[[Path, str, str], bool] = _git_is_ancestor,
    require_working_tree_assets: bool = False,
) -> dict[str, Any]:
    manifest = _exact_keys(document, MANIFEST_KEYS, "Sim canonical donor manifest")
    if (
        manifest["schemaVersion"] != 1
        or manifest["kind"] != "dronedream-canonical-brand-donor-manifest"
        or manifest["manifestVersion"] != "1.0.0"
        or manifest["editionId"] != "sim"
    ):
        raise SimBrandDonorError("Sim canonical donor manifest identity drifted")

    source = _exact_keys(manifest["source"], MANIFEST_SOURCE_KEYS, "donor.source")
    donor_commit = _commit(source["donorCommit"], "donor.source.donorCommit")
    evidence_commit = _commit(source["evidenceCommit"], "donor.source.evidenceCommit")
    common_core_commit = _commit(source["commonCoreCommit"], "donor.source.commonCoreCommit")
    declared_hash = _sha(source["commonCoreHash"], "donor.source.commonCoreHash")
    if (
        source["branch"] != intake["expectedSource"]["branch"]
        or source["commonCorePaths"] != list(COMMON_CORE_PATHS)
        or source["approvedConceptHandoffSha256"] != CONCEPT_HANDOFF_SHA256
        or donor_commit != common_core_commit
        or donor_commit == evidence_commit
    ):
        raise SimBrandDonorError("Sim donor source/commonCore binding drifted")
    if not ancestry_observer(repo_root, MINIMUM_COMMON_CORE_ANCESTOR, donor_commit):
        raise SimBrandDonorError("Sim donor predates the minimum commonCore ancestor")
    if not ancestry_observer(repo_root, donor_commit, evidence_commit):
        raise SimBrandDonorError("Sim donor evidence does not descend from donor source")
    if not ancestry_observer(repo_root, donor_commit, "origin/codex/software"):
        raise SimBrandDonorError("Sim donor source is not present on origin/codex/software")
    observed_hash = common_core_hash_observer(repo_root, donor_commit, COMMON_CORE_PATHS)
    if observed_hash != declared_hash:
        raise SimBrandDonorError("Sim donor commonCoreHash drifted")

    if manifest["identity"] != intake["expectedIdentity"]:
        raise SimBrandDonorError("Sim donor identity drifted")
    if manifest["palette"] != intake["expectedPalette"]:
        raise SimBrandDonorError("Sim donor palette drifted")

    raw_assets = manifest["assets"]
    if not isinstance(raw_assets, list) or len(raw_assets) != len(ASSET_REQUIREMENTS):
        raise SimBrandDonorError("Sim donor asset inventory is incomplete")
    assets: dict[str, dict[str, Any]] = {}
    observed_paths: set[str] = set()
    for index, raw_asset in enumerate(raw_assets):
        asset = _exact_keys(raw_asset, ASSET_KEYS, f"donor.assets[{index}]")
        role = asset["role"]
        if role not in ASSET_REQUIREMENTS or role in assets:
            raise SimBrandDonorError("Sim donor asset roles are missing or duplicated")
        relative_path = _safe_path(asset["path"], f"donor.assets[{index}].path")
        if relative_path in observed_paths:
            raise SimBrandDonorError("Sim donor asset paths must be unique")
        if role != "master-mark-svg" and "sim" not in relative_path.casefold():
            raise SimBrandDonorError(f"{role} path is not visibly scoped to SIM")
        observed_paths.add(relative_path)
        expected_mime, expected_size = ASSET_REQUIREMENTS[role]
        if asset["mimeType"] != expected_mime:
            raise SimBrandDonorError(f"{role} MIME type drifted")
        if expected_size is None:
            if asset["width"] is not None or asset["height"] is not None:
                raise SimBrandDonorError(f"{role} dimensions must be null")
        elif asset["width"] != expected_size or asset["height"] != expected_size:
            raise SimBrandDonorError(f"{role} dimensions drifted")
        if not isinstance(asset["bytes"], int) or asset["bytes"] <= 0:
            raise SimBrandDonorError(f"{role} byte count is invalid")
        declared_asset_sha = _sha(asset["sha256"], f"{role}.sha256")
        payload = asset_reader(repo_root, donor_commit, relative_path)
        if len(payload) != asset["bytes"] or sha256_bytes(payload) != declared_asset_sha:
            raise SimBrandDonorError(f"{role} donor bytes or SHA-256 drifted")
        _validate_asset_signature(payload, expected_mime, role)
        if require_working_tree_assets:
            working_path = _resolve(repo_root, relative_path, f"{role} working-tree path")
            if working_path.read_bytes() != payload:
                raise SimBrandDonorError(f"{role} working-tree bytes drifted from donor")
        assets[role] = asset
    if tuple(assets) != tuple(ASSET_REQUIREMENTS):
        raise SimBrandDonorError("Sim donor asset role ordering drifted")

    preservation = _exact_keys(manifest["preservation"], PRESERVATION_KEYS, "donor.preservation")
    master = assets["master-mark-svg"]
    if preservation != {
        "sourceMasterPath": master["path"],
        "sourceMasterSha256": master["sha256"],
        "originalWingShapePreserved": True,
        "whiteFlightPathPreserved": True,
        "masterWordmarkPreserved": True,
        "masterRedrawn": False,
    }:
        raise SimBrandDonorError("Sim donor master preservation facts drifted")
    review = _exact_keys(manifest["review"], REVIEW_KEYS, "donor.review")
    if (
        review["status"] != "reviewed-canonical"
        or review["releaseUseAuthorized"] is not True
        or review["conceptOnly"] is not False
        or not isinstance(review["approvalReference"], str)
        or not review["approvalReference"].strip()
    ):
        raise SimBrandDonorError("Sim donor canonical review evidence is incomplete")
    return manifest


def _png_dimensions(payload: bytes, label: str) -> tuple[int, int]:
    _validate_asset_signature(payload, "image/png", label)
    if len(payload) < 24 or payload[12:16] != b"IHDR":
        raise SimBrandDonorError(f"{label} has no valid PNG IHDR")
    return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")


def _validate_approved_location(
    value: Any,
    *,
    expected: dict[str, Any],
    source: bool,
    label: str,
) -> dict[str, Any]:
    location = _exact_keys(value, APPROVED_LOCATION_KEYS, label)
    expected_location = {
        "path": expected["sourcePath" if source else "destinationPath"],
        "fileName": expected["sourceFileName" if source else "destinationFileName"],
        "sha256": expected["sha256"],
        "bytes": expected["bytes"],
        "mimeType": "image/png",
        "width": expected["width"],
        "height": expected["height"],
    }
    if location != expected_location:
        raise SimBrandDonorError(f"{label} provenance drifted")
    return location


def validate_approved_edition_assets(
    document: Any,
    *,
    repo_root: Path,
    require_source_assets: bool = False,
) -> dict[str, Any]:
    manifest = _exact_keys(document, APPROVED_MANIFEST_KEYS, "approved SIM asset manifest")
    if (
        manifest["schemaVersion"] != 1
        or manifest["kind"] != "dronedream-approved-edition-brand-assets"
        or manifest["manifestVersion"] != "1.0.0"
        or manifest["editionId"] != "sim"
    ):
        raise SimBrandDonorError("approved SIM asset manifest identity drifted")

    schema_ref = _exact_keys(manifest["schema"], FILE_REF_KEYS, "approved.schema")
    if schema_ref["path"] != APPROVED_SCHEMA_PATH:
        raise SimBrandDonorError("approved SIM asset schema path drifted")
    schema_path = _resolve(repo_root, schema_ref["path"], "approved.schema.path")
    if sha256_file(schema_path) != _sha(schema_ref["sha256"], "approved.schema.sha256"):
        raise SimBrandDonorError("approved SIM asset schema SHA-256 drifted")
    schema = load_json(schema_path)
    if schema.get("additionalProperties") is not False:
        raise SimBrandDonorError("approved SIM asset schema must remain closed")

    authorization = _exact_keys(
        manifest["authorization"], APPROVED_AUTHORIZATION_KEYS, "approved.authorization"
    )
    if authorization != {
        "status": "chief-control-approved-byte-for-byte",
        "sourceThreadId": APPROVED_SOURCE_THREAD_ID,
        "authorizationDate": "2026-08-05",
        "allowedUse": [
            "application",
            "installer-input",
            "shortcut-input",
            "sim-edition-surface",
        ],
        "byteForByteCopyRequired": True,
        "derivativeExportAuthorized": False,
    }:
        raise SimBrandDonorError("approved SIM asset authorization drifted")
    if manifest["identity"] != SIM_IDENTITY or manifest["palette"] != SIM_PALETTE:
        raise SimBrandDonorError("approved SIM asset identity or palette drifted")

    binding = _exact_keys(
        manifest["commonCoreBinding"], APPROVED_BINDING_KEYS, "approved.commonCoreBinding"
    )
    branch_ref = _exact_keys(
        binding["branchContract"], FILE_REF_KEYS, "approved.commonCoreBinding.branchContract"
    )
    if branch_ref["path"] != "distribution/branch-contracts/software-sim.v1.json":
        raise SimBrandDonorError("approved SIM branch contract path drifted")
    branch_path = _resolve(repo_root, branch_ref["path"], "approved branch contract path")
    if sha256_file(branch_path) != _sha(branch_ref["sha256"], "approved branch contract SHA"):
        raise SimBrandDonorError("approved SIM branch contract SHA-256 drifted")
    branch_contract = load_json(branch_path)
    baseline = branch_contract.get("syncBaseline")
    if not isinstance(baseline, dict):
        raise SimBrandDonorError("approved SIM branch contract baseline is missing")
    if binding != {
        "branchContract": branch_ref,
        "commonCoreCommit": baseline.get("commonCoreCommit"),
        "commonCoreHash": baseline.get("commonCoreHash"),
        "commonCorePaths": branch_contract.get("commonCorePaths"),
        "bindingScope": "sim-edition-integration-baseline",
        "canonicalUniversalDonorIntegrated": False,
    }:
        raise SimBrandDonorError("approved SIM commonCore binding drifted")
    common_core_commit = _commit(binding["commonCoreCommit"], "approved commonCore commit")
    common_core_paths = tuple(binding["commonCorePaths"])
    observed_common_core_hash = _git_common_core_hash(
        repo_root, common_core_commit, common_core_paths
    )
    if observed_common_core_hash != _sha(
        binding["commonCoreHash"], "approved commonCore hash"
    ):
        raise SimBrandDonorError("approved SIM commonCoreHash drifted")

    handoff = _exact_keys(
        manifest["sourceHandoff"], APPROVED_HANDOFF_KEYS, "approved.sourceHandoff"
    )
    if handoff != {
        "path": APPROVED_HANDOFF_PATH,
        "sha256": CONCEPT_HANDOFF_SHA256,
        "statusAtHandoff": "user-approved-visual-direction-concept-assets",
    }:
        raise SimBrandDonorError("approved SIM source handoff drifted")

    raw_assets = manifest["assets"]
    if not isinstance(raw_assets, list) or len(raw_assets) != len(APPROVED_ASSET_REQUIREMENTS):
        raise SimBrandDonorError("approved SIM asset inventory is incomplete")
    observed_roles: list[str] = []
    for index, raw_asset in enumerate(raw_assets):
        asset = _exact_keys(raw_asset, APPROVED_ASSET_KEYS, f"approved.assets[{index}]")
        role = asset["role"]
        if role not in APPROVED_ASSET_REQUIREMENTS or role in observed_roles:
            raise SimBrandDonorError("approved SIM asset roles are missing or duplicated")
        expected = APPROVED_ASSET_REQUIREMENTS[role]
        source = _validate_approved_location(
            asset["source"], expected=expected, source=True, label=f"{role}.source"
        )
        destination = _validate_approved_location(
            asset["destination"], expected=expected, source=False, label=f"{role}.destination"
        )
        if asset["exactByteCopy"] is not True or asset["approved"] is not True:
            raise SimBrandDonorError(f"{role} approval or exact-copy requirement drifted")
        destination_path = _resolve(repo_root, destination["path"], f"{role} destination")
        destination_payload = destination_path.read_bytes()
        if (
            len(destination_payload) != destination["bytes"]
            or sha256_bytes(destination_payload) != destination["sha256"]
            or _png_dimensions(destination_payload, role)
            != (destination["width"], destination["height"])
        ):
            raise SimBrandDonorError(f"{role} destination bytes, SHA-256, or dimensions drifted")
        if require_source_assets:
            source_path = Path(source["path"])
            if not source_path.is_file():
                raise SimBrandDonorError(f"{role} approved source file is unavailable")
            source_payload = source_path.read_bytes()
            if source_payload != destination_payload:
                raise SimBrandDonorError(f"{role} destination is not an exact source byte copy")
        observed_roles.append(role)
    if tuple(observed_roles) != tuple(APPROVED_ASSET_REQUIREMENTS):
        raise SimBrandDonorError("approved SIM asset role ordering drifted")

    integration = _exact_keys(
        manifest["integrationState"], APPROVED_INTEGRATION_KEYS, "approved.integrationState"
    )
    if integration != {
        "assetBytesVendored": True,
        "applicationSourceWired": True,
        "installerIconOverridePresent": False,
        "windowsIcoGenerated": False,
        "browserAcceptanceExecuted": False,
        "productionBuildExecuted": False,
        "installerBuilt": False,
        "canonicalUniversalDonorIntegrated": False,
        "promotionReady": False,
    }:
        raise SimBrandDonorError("approved SIM asset integration state overclaims execution")
    if require_source_assets:
        handoff_path = Path(handoff["path"])
        if not handoff_path.is_file() or sha256_file(handoff_path) != handoff["sha256"]:
            raise SimBrandDonorError("approved SIM source handoff bytes or SHA-256 drifted")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    intake_parser = subparsers.add_parser("verify-intake")
    intake_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    intake_parser.add_argument(
        "intake",
        type=Path,
        nargs="?",
        default=Path("distribution/sim/brand/donor-intake.v1.json"),
    )
    donor_parser = subparsers.add_parser("verify-donor")
    donor_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    donor_parser.add_argument(
        "--intake", type=Path, default=Path("distribution/sim/brand/donor-intake.v1.json")
    )
    donor_parser.add_argument("--require-working-tree-assets", action="store_true")
    donor_parser.add_argument("manifest", type=Path)
    approved_parser = subparsers.add_parser("verify-approved-assets")
    approved_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    approved_parser.add_argument("--require-source-assets", action="store_true")
    approved_parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=Path("distribution/sim/brand/approved-edition-assets.v1.json"),
    )
    args = parser.parse_args()
    try:
        repo_root = args.repo_root.resolve()
        if args.command == "verify-intake":
            validate_donor_intake(load_json(args.intake), repo_root=repo_root)
        elif args.command == "verify-donor":
            intake = validate_donor_intake(load_json(args.intake), repo_root=repo_root)
            validate_canonical_donor_manifest(
                load_json(args.manifest),
                intake=intake,
                repo_root=repo_root,
                require_working_tree_assets=args.require_working_tree_assets,
            )
        elif args.command == "verify-approved-assets":
            validate_approved_edition_assets(
                load_json(args.manifest),
                repo_root=repo_root,
                require_source_assets=args.require_source_assets,
            )
        else:
            raise SimBrandDonorError(f"unsupported command: {args.command}")
    except SimBrandDonorError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
