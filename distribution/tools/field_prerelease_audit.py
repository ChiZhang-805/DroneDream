from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
ENGINE_PACK_TOOL = ROOT / "engine-pack" / "tools" / "engine_pack.py"

FIELD_EDITION_ID = "field"
FIELD_ENGINE_PROFILE = "field-lightweight"
FIELD_RECEIPT_KIND = "dronedream-field-prerelease-audit-receipt"
READONLY_OBSERVATION_KIND = "dronedream-field-readonly-device-observation"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_PAYLOAD_RESOURCES = (
    "LICENSE",
    "runtime/THIRD_PARTY_NOTICES.md",
    "distribution/editions/field.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/schemas/edition-execution-authorization.schema.json",
    "distribution/schemas/field-lifecycle-contract.schema.json",
    "distribution/schemas/field-prerelease-audit.schema.json",
    "distribution/tools/edition_safety_contract.py",
    "distribution/tools/field_lifecycle_contract.py",
    "distribution/tools/field_prerelease_audit.py",
    "distribution/vehicle-packs/registry.v1.json",
)

FORBIDDEN_PAYLOAD_PREFIXES = (
    "scripts/simulators/",
    "runtime/build/",
    "runtime/out/",
    "runtime/rootfs/",
    "runtime/px4/",
    "runtime/gazebo/",
    "px4/",
    "gazebo/",
)
FORBIDDEN_SCRIPT_SUFFIXES = (".bat", ".cmd", ".ps1", ".py", ".sh")
FORBIDDEN_EXECUTABLE_SUFFIXES = (
    ".7z",
    ".dll",
    ".dylib",
    ".elf",
    ".exe",
    ".msi",
    ".so",
    ".tar",
    ".tgz",
    ".zip",
)
FORBIDDEN_SIM_TOKENS = ("gazebo", "hitl", "sitl", "simulator")
FORBIDDEN_DEVICE_ACTIONS = (
    "serial.write",
    "usb.control-transfer-out",
    "usb.bulk-write",
    "mavlink.param-set",
    "mavlink.command-arm",
    "mavlink.command-unlock",
    "hardware.parameter.write",
    "hardware.arm",
    "hardware.flight",
)
REQUIRED_QUORUM_LAYERS = ("native", "backend", "runtime")


class FieldPrereleaseAuditError(ValueError):
    pass


def _load_engine_pack() -> Any:
    spec = importlib.util.spec_from_file_location("field_audit_engine_pack", ENGINE_PACK_TOOL)
    if spec is None or spec.loader is None:
        raise FieldPrereleaseAuditError("Engine Pack verifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def canonical_bytes(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_canonical(document: object) -> str:
    return sha256_bytes(canonical_bytes(document))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise FieldPrereleaseAuditError(f"expected JSON object: {path}")
    return document


def _require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FieldPrereleaseAuditError(f"{name} must be a lowercase SHA-256")
    return value


def _require_commit(value: object, name: str) -> str:
    if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
        raise FieldPrereleaseAuditError(f"{name} must be a full lowercase Git SHA")
    return value


def _payload_violation(path: str) -> str | None:
    lowered = path.lower()
    if lowered.startswith(FORBIDDEN_PAYLOAD_PREFIXES):
        return "forbidden-prefix"
    if lowered.endswith(FORBIDDEN_EXECUTABLE_SUFFIXES) and any(
        token in lowered for token in FORBIDDEN_SIM_TOKENS
    ):
        return "forbidden-simulator-binary"
    if lowered.endswith(FORBIDDEN_SCRIPT_SUFFIXES) and any(
        token in lowered for token in FORBIDDEN_SIM_TOKENS
    ):
        return "forbidden-simulator-script"
    return None


def _path_record(records: dict[str, dict[str, Any]], path: str) -> dict[str, Any]:
    record = records.get(path)
    if record is None:
        raise FieldPrereleaseAuditError(f"required Field payload resource is missing: {path}")
    return {
        "path": path,
        "sizeBytes": record["sizeBytes"],
        "sha256": record["sha256"],
    }


def _field_pack_entries(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in registry.get("packs", [])
        if isinstance(entry, dict)
        and entry.get("currentValidationStatus") == "validated"
        and entry.get("currentValidationTier") == "hardware-validated"
    ]


def audit_engine_pack_payload(
    *,
    descriptor_path: Path,
    archive_path: Path,
    common_core_commit: str,
    common_core_hash: str,
) -> dict[str, Any]:
    engine_pack = _load_engine_pack()
    descriptor, manifest = engine_pack.verified_bundle(descriptor_path, archive_path)
    _require_commit(common_core_commit, "commonCoreCommit")
    _require_sha256(common_core_hash, "commonCoreHash")

    profile = manifest["editionProfile"]
    if profile.get("profileId") != FIELD_ENGINE_PROFILE:
        raise FieldPrereleaseAuditError("Engine Pack is not bound to Field lightweight profile")
    if profile.get("includesLargeSimulator") is not False:
        raise FieldPrereleaseAuditError("Field Engine Pack must declare no large simulator payload")
    if "scripts/simulators" not in profile.get("excludedSourcePaths", []):
        raise FieldPrereleaseAuditError("Field Engine Pack must exclude simulator scripts")

    records = {record["path"]: record for record in manifest["files"]}
    violations = [
        {"path": path, "reason": reason}
        for path in records
        for reason in [_payload_violation(path)]
        if reason is not None
    ]
    if violations:
        raise FieldPrereleaseAuditError("Field Engine Pack contains forbidden simulator payload")

    required_resources = [_path_record(records, path) for path in REQUIRED_PAYLOAD_RESOURCES]
    field_manifest = load_json(ROOT / "distribution" / "editions" / "field.v1.json")
    gate_policy = load_json(ROOT / "distribution" / "safety" / "edition-execution-gate.v1.json")
    registry = load_json(ROOT / "distribution" / "vehicle-packs" / "registry.v1.json")
    required_receipts = set(gate_policy["structuredEvidence"]["requiredReceiptTypes"])
    for receipt_type in (
        "transaction-rollback",
        "emergency-stop",
        "control-takeover",
        "parameter-snapshot",
    ):
        if receipt_type not in required_receipts:
            raise FieldPrereleaseAuditError(f"safety gate lost required receipt: {receipt_type}")

    validated_packs = _field_pack_entries(registry)
    return {
        "profileId": profile["profileId"],
        "includesLargeSimulator": profile["includesLargeSimulator"],
        "excludedSourcePaths": profile["excludedSourcePaths"],
        "enginePack": {
            "packId": manifest["packId"],
            "descriptorSha256": sha256_file(descriptor_path),
            "archiveFilename": descriptor["archive"]["filename"],
            "archiveSha256": descriptor["archive"]["sha256"],
            "archiveSizeBytes": descriptor["archive"]["sizeBytes"],
            "manifestSha256": descriptor["manifest"]["sha256"],
            "manifestSizeBytes": descriptor["manifest"]["sizeBytes"],
        },
        "source": {
            "enginePackSourceCommit": manifest["source"]["gitCommit"],
            "commonCoreCommit": common_core_commit,
            "commonCoreHash": common_core_hash,
        },
        "forbiddenPayloads": violations,
        "requiredResources": required_resources,
        "bindings": {
            "fieldManifestSha256": sha256_file(ROOT / "distribution" / "editions" / "field.v1.json"),
            "executionGatePolicySha256": sha256_file(
                ROOT / "distribution" / "safety" / "edition-execution-gate.v1.json"
            ),
            "controllerFirmwareRegistrySha256": sha256_file(
                ROOT / "distribution" / "vehicle-packs" / "registry.v1.json"
            ),
            "licenseSha256": sha256_file(ROOT / "LICENSE"),
            "noticeSha256": sha256_file(ROOT / "runtime" / "THIRD_PARTY_NOTICES.md"),
        },
        "retainedSafetyResources": {
            "requiredReceiptTypes": sorted(required_receipts),
            "hardwareActionsRequireValidatedSignedPack": gate_policy["editionBoundaries"][
                "hardwareActionsRequireValidatedSignedPack"
            ],
            "zeroValidatedPackDecision": gate_policy["editionBoundaries"][
                "zeroValidatedPackDecision"
            ],
        },
        "registrySummary": {
            "packCount": len(registry["packs"]),
            "validatedHardwarePackCount": len(validated_packs),
            "validatedPackIds": [entry["packId"] for entry in validated_packs],
        },
        "fieldManifest": {
            "editionId": field_manifest["editionId"],
            "artifactBaseName": field_manifest["artifactBaseName"],
            "validationTier": field_manifest["validationTier"],
            "includesLargeSimulator": field_manifest["runtimeProfile"]["includesLargeSimulator"],
        },
    }


def fake_readonly_observation(
    *,
    observation_id: str,
    device_id: str,
    hardware_identity_hash: str,
    controller_model: str,
    firmware_family: str,
    firmware_version: str,
    firmware_identity_hash: str,
    pack_id: str,
    common_core_commit: str,
    common_core_hash: str,
    field_manifest_sha256: str,
    observed_at: str = "2026-08-05T00:00:00Z",
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "kind": READONLY_OBSERVATION_KIND,
        "observationId": observation_id,
        "observedAt": observed_at,
        "transport": {
            "kind": "fake",
            "mode": "read-only",
            "openedDevice": False,
            "writeAttempted": False,
            "writeOperations": [],
        },
        "device": {
            "deviceId": device_id,
            "hardwareIdentityHash": _require_sha256(
                hardware_identity_hash, "hardwareIdentityHash"
            ),
            "controllerModel": controller_model,
            "firmwareFamily": firmware_family,
            "firmwareVersion": firmware_version,
            "firmwareIdentityHash": _require_sha256(
                firmware_identity_hash, "firmwareIdentityHash"
            ),
        },
        "vehiclePack": {
            "packId": pack_id,
            "manifestSha256": "",
            "registrySha256": "",
            "validationStatus": "unknown",
            "validationTier": "unknown",
            "signatureState": "unknown",
        },
        "source": {
            "commonCoreCommit": _require_commit(common_core_commit, "commonCoreCommit"),
            "commonCoreHash": _require_sha256(common_core_hash, "commonCoreHash"),
            "fieldManifestSha256": _require_sha256(
                field_manifest_sha256, "fieldManifestSha256"
            ),
        },
        "authorization": {
            "discoveryIsAuthorization": False,
            "decision": "deny",
            "reasonCodes": ["discovery.not-authorization"],
        },
    }


def _pack_lookup(registry: dict[str, Any], pack_id: str) -> dict[str, Any] | None:
    return next((entry for entry in registry["packs"] if entry["packId"] == pack_id), None)


def _quorum_layers(quorum_receipt: dict[str, Any] | None) -> set[str]:
    if quorum_receipt is None:
        return set()
    layer_hashes = quorum_receipt.get("layerDecisionHashes")
    if not isinstance(layer_hashes, dict):
        return set()
    return {str(layer) for layer in layer_hashes}


def validate_readonly_observation(
    observation: dict[str, Any],
    *,
    registry_path: Path = DISTRIBUTION / "vehicle-packs" / "registry.v1.json",
) -> dict[str, Any]:
    expected_top = {
        "schemaVersion",
        "kind",
        "observationId",
        "observedAt",
        "transport",
        "device",
        "vehiclePack",
        "source",
        "authorization",
    }
    if set(observation) != expected_top:
        raise FieldPrereleaseAuditError("readonly observation fields drifted")
    if observation["schemaVersion"] != 1 or observation["kind"] != READONLY_OBSERVATION_KIND:
        raise FieldPrereleaseAuditError("readonly observation identity is invalid")

    transport = observation["transport"]
    if set(transport) != {"kind", "mode", "openedDevice", "writeAttempted", "writeOperations"}:
        raise FieldPrereleaseAuditError("readonly transport fields drifted")
    if transport["kind"] != "fake" or transport["mode"] != "read-only":
        raise FieldPrereleaseAuditError("Field discovery contract only accepts fake read-only transport")
    if transport["openedDevice"] is not False:
        raise FieldPrereleaseAuditError("readonly discovery must not open a serial or USB device")
    if transport["writeAttempted"] is not False or transport["writeOperations"] != []:
        raise FieldPrereleaseAuditError("readonly discovery must not write to serial, USB, params, arm, or flight")

    device = observation["device"]
    if set(device) != {
        "deviceId",
        "hardwareIdentityHash",
        "controllerModel",
        "firmwareFamily",
        "firmwareVersion",
        "firmwareIdentityHash",
    }:
        raise FieldPrereleaseAuditError("readonly device fields drifted")
    _require_sha256(device["hardwareIdentityHash"], "hardwareIdentityHash")
    _require_sha256(device["firmwareIdentityHash"], "firmwareIdentityHash")

    authorization = observation["authorization"]
    if authorization != {
        "discoveryIsAuthorization": False,
        "decision": "deny",
        "reasonCodes": ["discovery.not-authorization"],
    }:
        raise FieldPrereleaseAuditError("device discovery must not authorize hardware actions")

    registry = load_json(registry_path)
    pack = _pack_lookup(registry, observation["vehiclePack"]["packId"])
    filled = deepcopy(observation)
    filled["vehiclePack"]["registrySha256"] = sha256_file(registry_path)
    if pack is None:
        filled["vehiclePack"]["validationStatus"] = "unknown"
        filled["vehiclePack"]["validationTier"] = "unknown"
        filled["vehiclePack"]["signatureState"] = "unknown"
        return filled

    manifest = load_json(ROOT / pack["manifestPath"])
    filled["vehiclePack"].update(
        {
            "manifestSha256": pack["manifestSha256"],
            "validationStatus": pack["currentValidationStatus"],
            "validationTier": pack["currentValidationTier"],
            "signatureState": manifest["integrity"]["signature"]["state"],
        }
    )
    return filled


def _controller_matches(manifest: dict[str, Any], controller_model: str) -> bool:
    return any(controller["model"] == controller_model for controller in manifest["controllers"])


def create_field_prerelease_receipt(
    *,
    payload_audit: dict[str, Any],
    observation: dict[str, Any],
    install_plan: dict[str, Any],
    rollback_plan: dict[str, Any],
    quorum_receipt: dict[str, Any] | None = None,
    registry_path: Path = DISTRIBUTION / "vehicle-packs" / "registry.v1.json",
    issued_at: str = "2026-08-05T00:00:00Z",
) -> dict[str, Any]:
    validated_observation = validate_readonly_observation(observation, registry_path=registry_path)
    registry = load_json(registry_path)
    pack_entry = _pack_lookup(registry, validated_observation["vehiclePack"]["packId"])

    reason_codes = ["discovery.not-authorization"]
    if payload_audit["registrySummary"]["validatedHardwarePackCount"] == 0:
        reason_codes.append("field.registry.zero-validated-packs")
    if pack_entry is None:
        reason_codes.append("field.device.unknown-pack")
        pack_manifest = None
    else:
        pack_manifest = load_json(ROOT / pack_entry["manifestPath"])
        if pack_entry["currentValidationStatus"] != "validated":
            reason_codes.append("field.pack.not-validated")
        if pack_entry["currentValidationTier"] != "hardware-validated":
            reason_codes.append("field.pack.not-hardware-validated")
        if pack_manifest["integrity"]["signature"]["state"] != "verified":
            reason_codes.append("field.pack.signature-not-verified")
        if validated_observation["device"]["firmwareFamily"] != pack_manifest["autopilot"]["family"]:
            reason_codes.append("field.firmware.family-drift")
        if (
            validated_observation["device"]["firmwareVersion"]
            not in pack_manifest["autopilot"]["supportedFirmwareVersions"]
        ):
            reason_codes.append("field.firmware.version-drift")
        if not _controller_matches(
            pack_manifest, validated_observation["device"]["controllerModel"]
        ):
            reason_codes.append("field.controller.unknown")

    missing_layers = sorted(set(REQUIRED_QUORUM_LAYERS) - _quorum_layers(quorum_receipt))
    if missing_layers:
        reason_codes.append("field.quorum.missing-three-layer")
    elif quorum_receipt is not None and quorum_receipt.get("decision") != "allow":
        reason_codes.append("field.quorum.not-allow")

    receipt = {
        "schemaVersion": 1,
        "kind": FIELD_RECEIPT_KIND,
        "editionId": FIELD_EDITION_ID,
        "issuedAt": issued_at,
        "decision": "deny" if reason_codes else "allow",
        "reasonCodes": sorted(set(reason_codes)),
        "source": {
            "commonCoreCommit": payload_audit["source"]["commonCoreCommit"],
            "commonCoreHash": payload_audit["source"]["commonCoreHash"],
            "enginePackSourceCommit": payload_audit["source"]["enginePackSourceCommit"],
            "enginePackManifestSha256": payload_audit["enginePack"]["manifestSha256"],
        },
        "bindings": {
            "fieldManifestSha256": payload_audit["bindings"]["fieldManifestSha256"],
            "controllerFirmwareRegistrySha256": payload_audit["bindings"][
                "controllerFirmwareRegistrySha256"
            ],
            "executionGatePolicySha256": payload_audit["bindings"]["executionGatePolicySha256"],
            "licenseSha256": payload_audit["bindings"]["licenseSha256"],
            "noticeSha256": payload_audit["bindings"]["noticeSha256"],
            "installPlanSha256": sha256_canonical(install_plan),
            "rollbackPlanSha256": sha256_canonical(rollback_plan),
        },
        "payloadAudit": {
            "profileId": payload_audit["profileId"],
            "includesLargeSimulator": payload_audit["includesLargeSimulator"],
            "forbiddenPayloads": payload_audit["forbiddenPayloads"],
            "requiredResources": payload_audit["requiredResources"],
        },
        "deviceObservation": {
            "observationHash": sha256_canonical(validated_observation),
            "discoveryIsAuthorization": False,
            "transport": validated_observation["transport"],
            "device": validated_observation["device"],
            "vehiclePack": validated_observation["vehiclePack"],
        },
        "validation": {
            "registryValidatedHardwarePackCount": payload_audit["registrySummary"][
                "validatedHardwarePackCount"
            ],
            "signatureState": validated_observation["vehiclePack"]["signatureState"],
            "validationStatus": validated_observation["vehiclePack"]["validationStatus"],
            "validationTier": validated_observation["vehiclePack"]["validationTier"],
            "requiredQuorumLayers": list(REQUIRED_QUORUM_LAYERS),
            "observedQuorumLayers": sorted(_quorum_layers(quorum_receipt)),
        },
        "installPlan": install_plan,
        "rollbackPlan": rollback_plan,
    }
    receipt["receiptSha256"] = sha256_canonical(receipt)
    return receipt
