#!/usr/bin/env python3
"""Validate Lab preview artifact receipts without touching hardware or simulators."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "distribution/build-profiles/lab-preview.v1.json"
EDITION_PATH = ROOT / "distribution/editions/lab.v1.json"
BRAND_MANIFEST_PATH = ROOT / "distribution/editions/lab/brand-source-manifest.v1.json"
BRAND_DONOR_PATH = ROOT / "brand/brand-editions.v1.json"
BRAND_MARK_PATH = ROOT / "distribution/editions/lab/assets/dronedream-lab-mark-v2.png"
BRAND_LOCKUP_PATH = ROOT / "distribution/editions/lab/assets/dronedream-lab-dot-lockup-v2.png"
BRAND_ICON_PATH = ROOT / "brand/generated/lab/windows/icon.ico"
VEHICLE_PACK_PATH = ROOT / "distribution/vehicle-packs/holybro-s500-v2-pixhawk6c.v1.json"
LICENSE_NOTICE_PATH = ROOT / "runtime/THIRD_PARTY_NOTICES.md"
PAYLOAD_PATH = ROOT / "desktop/src-tauri/tauri.lab-preview.conf.json"
SCHEMA_PATH = ROOT / "distribution/schemas/lab-preview-artifact-receipt.schema.json"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_PATH_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"
)
HARDWARE_ACTIONS = (
    "hardware.parameter.write",
    "hardware.arm",
    "hardware.flight",
    "hardware.hitl.execute",
)
SIMULATION_MODULES = (
    "runtime-simulation",
    "simulator-gazebo-harmonic",
    "simulator-px4-sitl",
    "vehicle-pack-sim",
)
GATED_HARDWARE_MODULES = (
    "hardware-bridge",
    "vehicle-pack-hardware",
    "vehicle-pack-validation",
)
FIELD_ONLY_MODULES = (
    "runtime-base-field-lightweight",
    "field-lightweight-runtime",
)
UNIVERSAL_BOOTSTRAPPER_MODULES = (
    "universal-bootstrapper",
    "mode-switch-bootstrapper",
)
COMMON_CORE_PRODUCT_SOURCE_COMMIT = "e374d3f8d96b1265fcdb06864208b676566e94d9"
EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT = "e097b9ea057468bf1602ad1f1c4c5c5e88a65571"


class LabPreviewArtifactError(ValueError):
    """Raised when a Lab preview receipt can overstate artifact readiness."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabPreviewArtifactError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LabPreviewArtifactError(f"{path} must contain a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SAFE_PATH_RE.fullmatch(value):
        raise LabPreviewArtifactError(f"{label} is not a safe repository-relative path")
    candidate = (ROOT / value).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise LabPreviewArtifactError(f"{label} escapes the repository root") from exc
    return value


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabPreviewArtifactError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise LabPreviewArtifactError(
            f"{label} keys drifted (missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)})"
        )
    return value


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise LabPreviewArtifactError(detail)
    return completed.stdout.strip()


def common_core_hash(common_core_commit: str) -> str:
    profile = _load_json(PROFILE_PATH)
    common_core = profile.get("commonCore")
    if not isinstance(common_core, dict):
        raise LabPreviewArtifactError("Lab profile commonCore is missing")
    paths = common_core.get("paths")
    if tuple(paths or ()) != (
        "backend",
        "desktop",
        "engine-pack",
        "frontend",
        "runtime",
        "worker",
    ):
        raise LabPreviewArtifactError("Lab profile common-core path set drifted")
    listing = _git("ls-tree", "-r", "--full-tree", common_core_commit, "--", *paths)
    if not listing:
        raise LabPreviewArtifactError("common-core inventory is empty")
    return _sha256_text(listing)


def _file_ref(path: Path) -> dict[str, str]:
    return {"path": _repo_path(path), "sha256": _sha256_file(path)}


def fake_lab_preview_receipt(
    *,
    source_commit: str = "a" * 40,
    common_core_commit: str = "b" * 40,
    common_core_hash_value: str | None = None,
) -> dict[str, Any]:
    """Create a fake, non-installable receipt for negative/contract tests."""

    if common_core_hash_value is None:
        common_core_hash_value = "c" * 64
    return {
        "schemaVersion": 1,
        "kind": "dronedream-lab-preview-artifact-receipt",
        "receiptVersion": "1.0.0",
        "testOnly": True,
        "editionId": "lab",
        "productDisplayVersion": "1.0.0",
        "sourceCommit": source_commit,
        "branch": "codex/software-lab",
        "commonCoreCommit": common_core_commit,
        "commonCoreHash": common_core_hash_value,
        "editionManifest": _file_ref(EDITION_PATH),
        "profile": _file_ref(PROFILE_PATH),
        "brand": {
            "displayName": "DroneDream · LAB",
            "canonicalDonor": _file_ref(BRAND_DONOR_PATH),
            "sourceManifest": _file_ref(BRAND_MANIFEST_PATH),
            "mark": _file_ref(BRAND_MARK_PATH),
            "dotLockup": _file_ref(BRAND_LOCKUP_PATH),
            "installerIcon": _file_ref(BRAND_ICON_PATH),
            "grantsHardwareAuthority": False,
        },
        "workspaces": {
            "simulation": {
                "workspaceId": "simulation",
                "authority": "ui-workflow-only",
                "allowedActions": [
                    "qualification.simulation.issue",
                    "simulation.execute",
                    "simulation.parameter.write",
                    "simulation.vehicle.arm",
                ],
                "deniedHardwareActions": list(HARDWARE_ACTIONS),
            },
            "hardwareLab": {
                "workspaceId": "hardware-lab",
                "authority": "ui-workflow-only",
                "allowedActions": [
                    "hardware.discover",
                    "hardware.parameter.read",
                    "hardware.preflight.execute",
                    "hardware.emergency-stop",
                ],
                "deniedHardwareActions": list(HARDWARE_ACTIONS),
            },
        },
        "moduleGraph": {
            "simulationPayload": list(SIMULATION_MODULES),
            "gatedHardwareAdapter": list(GATED_HARDWARE_MODULES),
            "vehiclePack": _file_ref(VEHICLE_PACK_PATH),
            "controllerModel": "Pixhawk 6C",
            "firmwareFamily": "px4",
            "qualificationReceiptRequired": True,
        },
        "payload": _file_ref(PAYLOAD_PATH),
        "licenseNotice": _file_ref(LICENSE_NOTICE_PATH),
        "rollback": {
            "policy": "previous-verified-promotion",
            "targetArtifactSha256": None,
            "targetPromotionId": None,
        },
        "upgrade": {
            "requiresSameCommonCore": True,
            "requiresManifestMatch": True,
            "requiresRollback": True,
        },
        "safety": {
            "validatedVehiclePackCount": 0,
            "uiSwitchCountsAsAuthority": False,
            "hardwareActionDecision": "deny",
            "requiredDecisionLayers": ["native", "backend", "runtime"],
        },
        "artifact": {
            "fileName": "DroneDream-Lab-1.0.0.exe",
            "path": "artifacts/test-fixtures/not-built/DroneDream-Lab-1.0.0.exe",
            "sha256": "d" * 64,
            "bytes": 0,
            "authenticode": {
                "expected": "not-signed",
                "observedStatus": "test-fixture:not-built",
            },
            "tauriUpdaterSignature": "not-issued",
        },
    }


def validate_receipt(receipt: Any, *, verify_artifact_file: bool = True) -> dict[str, Any]:
    document = _exact_keys(
        receipt,
        {
            "schemaVersion",
            "kind",
            "receiptVersion",
            "testOnly",
            "editionId",
            "productDisplayVersion",
            "sourceCommit",
            "branch",
            "commonCoreCommit",
            "commonCoreHash",
            "editionManifest",
            "profile",
            "brand",
            "workspaces",
            "moduleGraph",
            "payload",
            "licenseNotice",
            "rollback",
            "upgrade",
            "safety",
            "artifact",
        },
        "Lab receipt",
    )
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-lab-preview-artifact-receipt"
        or document["receiptVersion"] != "1.0.0"
        or document["editionId"] != "lab"
        or document["productDisplayVersion"] != "1.0.0"
        or document["branch"] != "codex/software-lab"
    ):
        raise LabPreviewArtifactError("Lab receipt identity is unsupported")
    if not isinstance(document["testOnly"], bool):
        raise LabPreviewArtifactError("Lab receipt testOnly must be boolean")
    for label in ("sourceCommit", "commonCoreCommit"):
        if not isinstance(document[label], str) or not COMMIT_RE.fullmatch(document[label]):
            raise LabPreviewArtifactError(f"{label} must be a full commit")
    if not document["testOnly"]:
        if document["commonCoreCommit"] != COMMON_CORE_PRODUCT_SOURCE_COMMIT:
            raise LabPreviewArtifactError("commonCoreCommit must bind the Universal/Core product source")
        if document["commonCoreCommit"] == EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT:
            raise LabPreviewArtifactError("Sim preview evidence commit cannot be the common-core product source")
    if not isinstance(document["commonCoreHash"], str) or not SHA256_RE.fullmatch(
        document["commonCoreHash"]
    ):
        raise LabPreviewArtifactError("commonCoreHash must be a SHA-256")

    for label, path in (
        ("editionManifest", EDITION_PATH),
        ("profile", PROFILE_PATH),
        ("payload", PAYLOAD_PATH),
        ("licenseNotice", LICENSE_NOTICE_PATH),
    ):
        ref = _exact_keys(document[label], {"path", "sha256"}, label)
        if ref["path"] != _repo_path(path) or ref["sha256"] != _sha256_file(path):
            raise LabPreviewArtifactError(f"{label} does not match the active Lab contract")

    brand = _exact_keys(
        document["brand"],
        {
            "displayName",
            "canonicalDonor",
            "sourceManifest",
            "mark",
            "dotLockup",
            "installerIcon",
            "grantsHardwareAuthority",
        },
        "brand",
    )
    if brand["displayName"] != "DroneDream · LAB":
        raise LabPreviewArtifactError("Lab brand display name drifted")
    if brand["grantsHardwareAuthority"] is not False:
        raise LabPreviewArtifactError("Lab visual brand cannot grant hardware authority")
    for label, path in (
        ("canonicalDonor", BRAND_DONOR_PATH),
        ("sourceManifest", BRAND_MANIFEST_PATH),
        ("mark", BRAND_MARK_PATH),
        ("dotLockup", BRAND_LOCKUP_PATH),
        ("installerIcon", BRAND_ICON_PATH),
    ):
        ref = _exact_keys(brand[label], {"path", "sha256"}, f"brand.{label}")
        if ref != _file_ref(path):
            raise LabPreviewArtifactError(f"brand.{label} does not match approved Lab assets")

    try:
        computed_core_hash = common_core_hash(document["commonCoreCommit"])
    except LabPreviewArtifactError:
        if document["testOnly"]:
            computed_core_hash = document["commonCoreHash"]
        else:
            raise
    if document["commonCoreHash"] != computed_core_hash:
        raise LabPreviewArtifactError("commonCoreHash does not match commonCoreCommit")

    workspaces = _exact_keys(document["workspaces"], {"simulation", "hardwareLab"}, "workspaces")
    for label, expected_id in (("simulation", "simulation"), ("hardwareLab", "hardware-lab")):
        workspace = _exact_keys(
            workspaces[label],
            {"workspaceId", "authority", "allowedActions", "deniedHardwareActions"},
            f"workspaces.{label}",
        )
        if workspace["workspaceId"] != expected_id or workspace["authority"] != "ui-workflow-only":
            raise LabPreviewArtifactError(f"{label} workspace authority drifted")
        if tuple(workspace["deniedHardwareActions"]) != HARDWARE_ACTIONS:
            raise LabPreviewArtifactError(f"{label} workspace must deny hardware actions")
        if any(action in HARDWARE_ACTIONS for action in workspace["allowedActions"]):
            raise LabPreviewArtifactError(f"{label} workspace cannot allow hardware actions")

    graph = _exact_keys(
        document["moduleGraph"],
        {
            "simulationPayload",
            "gatedHardwareAdapter",
            "vehiclePack",
            "controllerModel",
            "firmwareFamily",
            "qualificationReceiptRequired",
        },
        "moduleGraph",
    )
    mixed_modules = set(graph["simulationPayload"]) | set(graph["gatedHardwareAdapter"])
    if mixed_modules.intersection(FIELD_ONLY_MODULES) or mixed_modules.intersection(
        UNIVERSAL_BOOTSTRAPPER_MODULES
    ):
        raise LabPreviewArtifactError("Lab module graph mixes Field-only or Universal bootstrapper content")
    if tuple(graph["simulationPayload"]) != SIMULATION_MODULES:
        raise LabPreviewArtifactError("simulation payload module set drifted")
    if tuple(graph["gatedHardwareAdapter"]) != GATED_HARDWARE_MODULES:
        raise LabPreviewArtifactError("gated hardware adapter module set drifted")
    vehicle_pack_ref = _exact_keys(graph["vehiclePack"], {"path", "sha256"}, "moduleGraph.vehiclePack")
    if vehicle_pack_ref != _file_ref(VEHICLE_PACK_PATH):
        raise LabPreviewArtifactError("Lab vehicle-pack binding drifted")
    if (
        graph["controllerModel"] != "Pixhawk 6C"
        or graph["firmwareFamily"] != "px4"
        or graph["qualificationReceiptRequired"] is not True
    ):
        raise LabPreviewArtifactError("Lab controller, firmware, or receipt dependency drifted")

    rollback = _exact_keys(
        document["rollback"],
        {"policy", "targetArtifactSha256", "targetPromotionId"},
        "rollback",
    )
    if rollback["policy"] != "previous-verified-promotion":
        raise LabPreviewArtifactError("rollback policy drifted")
    upgrade = _exact_keys(
        document["upgrade"],
        {"requiresSameCommonCore", "requiresManifestMatch", "requiresRollback"},
        "upgrade",
    )
    if any(upgrade[key] is not True for key in upgrade):
        raise LabPreviewArtifactError("upgrade contract is incomplete")

    safety = _exact_keys(
        document["safety"],
        {
            "validatedVehiclePackCount",
            "uiSwitchCountsAsAuthority",
            "hardwareActionDecision",
            "requiredDecisionLayers",
        },
        "safety",
    )
    if (
        safety["validatedVehiclePackCount"] != 0
        or safety["uiSwitchCountsAsAuthority"] is not False
        or safety["hardwareActionDecision"] != "deny"
        or tuple(safety["requiredDecisionLayers"]) != ("native", "backend", "runtime")
    ):
        raise LabPreviewArtifactError("Lab safety contract overstates authority")

    artifact = _exact_keys(
        document["artifact"],
        {"fileName", "path", "sha256", "bytes", "authenticode", "tauriUpdaterSignature"},
        "artifact",
    )
    if (
        artifact["fileName"] != "DroneDream-Lab-1.0.0.exe"
        or not isinstance(artifact["sha256"], str)
        or not SHA256_RE.fullmatch(artifact["sha256"])
        or not isinstance(artifact["bytes"], int)
        or artifact["bytes"] < 0
        or artifact["tauriUpdaterSignature"] != "not-issued"
    ):
        raise LabPreviewArtifactError("artifact identity or signature state drifted")
    _safe_relative(artifact["path"], "artifact.path")
    authenticode = _exact_keys(
        artifact["authenticode"], {"expected", "observedStatus"}, "artifact.authenticode"
    )
    if authenticode["expected"] != "not-signed":
        raise LabPreviewArtifactError("Lab preview must not claim Authenticode signing")
    if verify_artifact_file and not document["testOnly"]:
        path = ROOT / artifact["path"]
        if not path.is_file():
            raise LabPreviewArtifactError("artifact file is missing")
        if path.stat().st_size != artifact["bytes"] or _sha256_file(path) != artifact["sha256"]:
            raise LabPreviewArtifactError("artifact file bytes do not match the receipt")
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--skip-artifact-file", action="store_true")
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        validate_receipt(
            _load_json(args.receipt.resolve()),
            verify_artifact_file=not args.skip_artifact_file,
        )
    except LabPreviewArtifactError as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "schema": SCHEMA_PATH.relative_to(ROOT).as_posix(),
                "receipt": args.receipt.as_posix(),
                "validated": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
