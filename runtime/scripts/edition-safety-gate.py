#!/usr/bin/env python3
"""Runtime-owned, decision-only E5 edition safety gate.

This module never opens a device, writes a parameter, arms a vehicle, starts a
simulator, or applies an installation.  It independently verifies the active
Engine Pack/Runtime inventory and the observed device target before returning a
canonical Runtime layer decision receipt.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

RUNTIME_CONTRACT_REGISTRY_PATH = "distribution/runtime-contract-registry.v1.json"
SIM_EDITION_PROFILE = "sim-only"
AUTONOMY_EDITION_PROFILE = "autonomy-full"
KNOWN_EDITION_PROFILES = {
    "field-lightweight",
    SIM_EDITION_PROFILE,
    "unified-sim-lab",
    AUTONOMY_EDITION_PROFILE,
}
BASE_EDITION_PROFILE_KEYS = {
    "profileId",
    "includesLargeSimulator",
    "excludedSourcePaths",
}
SIM_PROFILE_MANIFEST_KEYS = {
    "profileId",
    "profileVersion",
    "profileManifestPath",
    "profileManifestSha256",
    "includesLargeSimulator",
    "excludedSourcePaths",
}
RUNTIME_DISTRIBUTION_BASE_PATHS = (
    "LICENSE",
    "runtime/THIRD_PARTY_NOTICES.md",
    RUNTIME_CONTRACT_REGISTRY_PATH,
    "distribution/capabilities/core-capabilities.v1.json",
    "distribution/editions/field.v1.json",
    "distribution/editions/lab.v1.json",
    "distribution/editions/sim.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/upstream-sources.v1.json",
    "distribution/vehicle-packs/amovlab-mfp450-pixhawk6c.v1.json",
    "distribution/vehicle-packs/amovlab-p450-px4.v1.json",
    "distribution/vehicle-packs/bitcraze-crazyflie-2-1-plus.v1.json",
    "distribution/vehicle-packs/holybro-qav250-pixhawk6c-mini.v1.json",
    "distribution/vehicle-packs/holybro-s500-v2-pixhawk6c.v1.json",
    "distribution/vehicle-packs/holybro-x500-v2-pixhawk6.v1.json",
    "distribution/vehicle-packs/holybro-x650-pixhawk6.v1.json",
    "distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json",
    "distribution/vehicle-packs/registry.v1.json",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RuntimeEditionSafetyError(RuntimeError):
    """Raised when no trustworthy Runtime decision can be produced."""


def _load_profile_contract(active_engine_root: Path) -> ModuleType:
    path = active_engine_root / "distribution/tools/engine_pack_profile_contract.py"
    name = "dronedream_runtime_engine_pack_profile_contract"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeEditionSafetyError("Runtime Engine Pack profile contract is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sim_profile_from_manifest(
    active_engine_root: Path,
    engine_manifest: Mapping[str, Any],
) -> tuple[ModuleType, dict[str, Any]] | None:
    edition_profile = engine_manifest.get("editionProfile")
    if not isinstance(edition_profile, dict):
        return None
    profile_id = edition_profile.get("profileId")
    if profile_id not in KNOWN_EDITION_PROFILES:
        raise RuntimeEditionSafetyError("Engine Pack profile is unsupported")
    if profile_id != SIM_EDITION_PROFILE:
        return None
    if set(edition_profile) != SIM_PROFILE_MANIFEST_KEYS:
        raise RuntimeEditionSafetyError("Sim-only Engine Pack profile fields are invalid")
    contract = _load_profile_contract(active_engine_root)
    try:
        profile = contract.load_profile(active_engine_root)
        contract.verify_profile_files(active_engine_root, profile, active_payload=True)
        binding = contract.profile_manifest_binding(profile, active_engine_root)
    except contract.EnginePackProfileError as error:
        raise RuntimeEditionSafetyError("Sim-only Engine Pack profile failed closed") from error
    if edition_profile != binding:
        raise RuntimeEditionSafetyError("Sim-only Engine Pack profile binding drifted")
    return contract, profile


def _validate_engine_profile_identity(
    active_engine_root: Path,
    engine_manifest: Mapping[str, Any],
) -> None:
    profile = engine_manifest.get("editionProfile")
    if not isinstance(profile, dict):
        raise RuntimeEditionSafetyError("Engine Pack edition profile is unavailable")
    profile_id = profile.get("profileId")
    if profile_id == SIM_EDITION_PROFILE:
        if _sim_profile_from_manifest(active_engine_root, engine_manifest) is None:
            raise RuntimeEditionSafetyError("Sim-only Engine Pack profile is unavailable")
        return
    if set(profile) != BASE_EDITION_PROFILE_KEYS:
        raise RuntimeEditionSafetyError("Engine Pack edition profile fields are invalid")
    expected = {
        "field-lightweight": {
            "profileId": "field-lightweight",
            "includesLargeSimulator": False,
            "excludedSourcePaths": ["backend/app/simulator", "scripts/simulators"],
        },
        "unified-sim-lab": {
            "profileId": "unified-sim-lab",
            "includesLargeSimulator": True,
            "excludedSourcePaths": [],
        },
        AUTONOMY_EDITION_PROFILE: {
            "profileId": AUTONOMY_EDITION_PROFILE,
            "includesLargeSimulator": True,
            "excludedSourcePaths": [],
        },
    }.get(profile_id)
    if expected is None or profile != expected:
        raise RuntimeEditionSafetyError("Engine Pack edition profile is unsupported")


def _validate_sim_payload_paths(
    contract: ModuleType,
    profile: Mapping[str, Any],
    paths: list[str],
) -> None:
    try:
        contract.validate_payload_paths(profile, paths)
    except contract.EnginePackProfileError as error:
        raise RuntimeEditionSafetyError("Sim-only payload inventory failed closed") from error


def runtime_distribution_paths(
    active_engine_root: Path,
    *,
    engine_manifest: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    registry_path = active_engine_root / RUNTIME_CONTRACT_REGISTRY_PATH
    if registry_path.is_symlink() or not registry_path.is_file():
        raise RuntimeEditionSafetyError("Runtime contract registry must be an ordinary file")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeEditionSafetyError("Runtime contract registry could not be read") from error
    if not isinstance(registry, dict) or set(registry) != {
        "schemaVersion",
        "kind",
        "contractPaths",
    }:
        raise RuntimeEditionSafetyError("Runtime contract registry fields are invalid")
    if registry["schemaVersion"] != 1 or registry["kind"] != "dronedream-runtime-contract-registry":
        raise RuntimeEditionSafetyError("Runtime contract registry identity is unsupported")
    paths = registry["contractPaths"]
    if (
        not isinstance(paths, list)
        or not paths
        or any(not isinstance(path, str) for path in paths)
        or paths != sorted(set(paths))
    ):
        raise RuntimeEditionSafetyError("Runtime contract registry paths must be unique and sorted")
    allowed = re.compile(
        r"^distribution/(?:schemas/[a-z0-9][a-z0-9.-]*\.schema\.json|tools/[a-z][a-z0-9_]*\.py)$"
    )
    root = active_engine_root.resolve()
    for relative in paths:
        if not allowed.fullmatch(relative):
            raise RuntimeEditionSafetyError(
                f"Runtime contract path is outside the allowlist: {relative}"
            )
        candidate = active_engine_root / relative
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or not candidate.resolve().is_relative_to(root)
        ):
            raise RuntimeEditionSafetyError(f"Runtime contract path is unavailable: {relative}")
    if engine_manifest is not None:
        sim_profile = _sim_profile_from_manifest(active_engine_root, engine_manifest)
        if sim_profile is not None:
            _profile_contract, profile = sim_profile
            profile_paths = sorted(
                {
                    *profile["directPayloadPaths"],
                    *(mapping["payloadPath"] for mapping in profile["sourceMappings"]),
                }
            )
            if not set(paths) <= set(profile_paths):
                raise RuntimeEditionSafetyError(
                    "Sim-only runtime registry exceeds its profile allowlist"
                )
            return tuple(profile_paths)
    combined = (*RUNTIME_DISTRIBUTION_BASE_PATHS, *paths)
    if len(combined) != len(set(combined)):
        raise RuntimeEditionSafetyError("Runtime distribution path registry contains duplicates")
    return combined


def _load_contract(active_engine_root: Path) -> ModuleType:
    path = active_engine_root / "distribution" / "tools" / "edition_safety_contract.py"
    name = "dronedream_runtime_edition_safety_contract"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeEditionSafetyError("Runtime edition safety contract is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_distribution_contract(active_engine_root: Path) -> ModuleType:
    path = active_engine_root / "distribution" / "tools" / "distribution_contract.py"
    name = "dronedream_runtime_distribution_contract"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeEditionSafetyError("Runtime distribution contract is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeEditionSafetyError(f"unable to load {label}") from error
    if not isinstance(value, dict):
        raise RuntimeEditionSafetyError(f"{label} is not an object")
    return value


def _isoformat(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise RuntimeEditionSafetyError("Runtime observation time must be timezone-aware")
    return value.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_controller(value: str) -> str:
    return value.replace(" ", "").lower()


@dataclass(frozen=True)
class RuntimeTrustedObservation:
    """Runtime-local state measured from the active payload and target."""

    active_engine_root: Path
    active_engine_pack_manifest_path: Path
    active_runtime_base_manifest_path: Path
    engine_pack_signature_verified: bool
    composite_inventory_hash: str
    actual_device_id: str
    actual_device_hardware_identity_hash: str
    actual_vehicle_id: str
    actual_controller_id: str
    actual_firmware_family: str
    actual_firmware_version: str
    actual_firmware_identity_hash: str
    actual_parameter_candidate_hash: str
    actual_target_kind: str
    locally_verified_evidence_hashes: Mapping[str, str]
    observed_at: dt.datetime
    consumed_authorization_ids: frozenset[str] = field(default_factory=frozenset)
    consumed_nonces: frozenset[str] = field(default_factory=frozenset)
    minimum_sequence: int = 1
    app_env: str = "production"
    test_catalog_override: bool = False
    pack_validation_status_override: str | None = None
    pack_validation_tier_override: str | None = None
    pack_signature_state_override: str | None = None
    controller_status_override: str | None = None


@dataclass(frozen=True)
class RuntimeLayerDecision:
    decision: str
    reason_codes: tuple[str, ...]
    receipt: Mapping[str, Any]


def _manifest_records(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = document.get("files")
    if not isinstance(raw, list):
        return {}
    records: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"path", "sizeBytes", "sha256"}:
            return {}
        path = item.get("path")
        size = item.get("sizeBytes")
        digest = item.get("sha256")
        if not isinstance(path, str) or path in records:
            return {}
        inner = PurePosixPath(path)
        if inner.is_absolute() or not inner.parts or ".." in inner.parts:
            return {}
        if not isinstance(size, int) or size < 0:
            return {}
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            return {}
        records[path] = item
    return records


def _active_inventory_reasons(
    contract: ModuleType,
    request: Mapping[str, Any],
    observed: RuntimeTrustedObservation,
) -> list[str]:
    reasons: list[str] = []
    try:
        engine_manifest = _load_object(
            observed.active_engine_pack_manifest_path, "active Engine Pack manifest"
        )
        runtime_manifest = _load_object(
            observed.active_runtime_base_manifest_path, "active Runtime Base manifest"
        )
    except RuntimeEditionSafetyError:
        return ["runtime.inventory.unreadable"]

    if (
        contract.sha256_file(observed.active_engine_pack_manifest_path)
        != request["source"]["enginePackManifestSha256"]
    ):
        reasons.append("runtime.engine-pack.manifest-hash-mismatch")
    if (
        contract.sha256_file(observed.active_runtime_base_manifest_path)
        != request["source"]["runtimeBaseManifestSha256"]
    ):
        reasons.append("runtime.runtime-base.manifest-hash-mismatch")
    if not observed.engine_pack_signature_verified:
        reasons.append("runtime.engine-pack.signature-unverified")
    if engine_manifest.get("kind") != "dronedream-engine-pack":
        reasons.append("runtime.engine-pack.kind-unsupported")
    if engine_manifest.get("schemaVersion") != 2:
        reasons.append("runtime.engine-pack.schema-unsupported")
    profile_valid = True
    try:
        _validate_engine_profile_identity(observed.active_engine_root, engine_manifest)
    except RuntimeEditionSafetyError:
        profile_valid = False
        reasons.append("runtime.engine-pack.edition-profile-unsupported")
    source = engine_manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("gitCommit") != request["source"]["repositoryCommit"]
    ):
        reasons.append("runtime.engine-pack.source-mismatch")
    runtime_source = runtime_manifest.get("source")
    if (
        not isinstance(runtime_source, dict)
        or runtime_source.get("droneDreamCommit") != request["source"]["repositoryCommit"]
    ):
        reasons.append("runtime.runtime-base.source-mismatch")

    records = _manifest_records(engine_manifest)
    if not records:
        reasons.append("runtime.engine-pack.file-inventory-invalid")
        return reasons
    forbidden_prefixes = (
        "distribution/build-planning/",
        "distribution/build-plans/",
        "distribution/tests/",
    )
    if any(path.startswith(forbidden_prefixes) for path in records):
        reasons.append("runtime.engine-pack.planned-artifact-present")
    if not profile_valid:
        return reasons
    try:
        sim_profile = _sim_profile_from_manifest(observed.active_engine_root, engine_manifest)
        if sim_profile is not None:
            profile_contract, profile = sim_profile
            _validate_sim_payload_paths(profile_contract, profile, sorted(records))
        distribution_paths = runtime_distribution_paths(
            observed.active_engine_root,
            engine_manifest=engine_manifest,
        )
    except RuntimeEditionSafetyError:
        reasons.append("runtime.engine-pack.contract-registry-invalid")
        return reasons
    for relative in distribution_paths:
        record = records.get(relative)
        path = observed.active_engine_root / Path(relative)
        if (
            record is None
            or not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(observed.active_engine_root.resolve())
        ):
            reasons.append("runtime.engine-pack.contract-file-missing")
            continue
        if path.stat().st_size != record["sizeBytes"]:
            reasons.append("runtime.engine-pack.contract-file-size-mismatch")
        if contract.sha256_file(path) != record["sha256"]:
            reasons.append("runtime.engine-pack.contract-file-hash-mismatch")
    return reasons


def _evidence_hashes(request: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(receipt["receiptType"]): str(receipt["evidenceHash"])
        for receipt in request["evidenceReceipts"]
    }


def _validate_active_catalog(
    contract: ModuleType,
    active_root: Path,
    request: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    distribution_contract = _load_distribution_contract(active_root)
    try:
        upstream = distribution_contract.validate_upstream_source_inventory(
            _load_object(
                active_root / "distribution/upstream-sources.v1.json",
                "active upstream source inventory",
            )
        )
        capability_path = active_root / "distribution/capabilities/core-capabilities.v1.json"
        capability = distribution_contract.validate_capability_policy(
            _load_object(capability_path, "active capability policy")
        )
        pack_directory = active_root / "distribution/vehicle-packs"
        packs_by_path: dict[str, dict[str, Any]] = {}
        pack_hashes: dict[str, str] = {}
        for path in sorted(pack_directory.glob("*.v1.json")):
            if path.name.startswith("registry."):
                continue
            relative = path.relative_to(active_root).as_posix()
            packs_by_path[relative] = distribution_contract.validate_vehicle_pack_manifest(
                _load_object(path, "active Vehicle Pack"),
                upstream_inventory=upstream,
                capability_policy_sha256=contract.sha256_file(capability_path),
            )
            pack_hashes[relative] = contract.sha256_file(path)
        distribution_contract.validate_vehicle_pack_registry(
            _load_object(pack_directory / "registry.v1.json", "active Vehicle Pack registry"),
            vehicle_packs_by_path=packs_by_path,
            vehicle_pack_manifest_sha256=pack_hashes,
        )
        edition = distribution_contract.validate_edition_manifest(
            _load_object(
                active_root / f"distribution/editions/{request['editionId']}.v1.json",
                "active edition manifest",
            ),
            policy=capability,
            policy_sha256=contract.sha256_file(capability_path),
        )
    except (
        RuntimeEditionSafetyError,
        distribution_contract.DistributionContractError,
    ) as error:
        raise RuntimeEditionSafetyError("active distribution catalog failed closed") from error
    selected_path = f"distribution/vehicle-packs/{request['vehicle']['packId']}.v1.json"
    selected = packs_by_path.get(selected_path)
    if selected is None:
        raise RuntimeEditionSafetyError("active Vehicle Pack is not registered")
    return edition, selected


def _local_target_reasons(
    request: Mapping[str, Any], observed: RuntimeTrustedObservation
) -> list[str]:
    reasons: list[str] = []
    comparisons = (
        (
            observed.composite_inventory_hash,
            request["compositeInventoryHash"],
            "runtime.composite-inventory.mismatch",
        ),
        (
            observed.actual_device_id,
            request["deviceHardwareIdentity"]["deviceId"],
            "runtime.device.id-mismatch",
        ),
        (
            observed.actual_device_hardware_identity_hash,
            request["deviceHardwareIdentity"]["hardwareIdentityHash"],
            "runtime.device.identity-mismatch",
        ),
        (observed.actual_vehicle_id, request["vehicle"]["vehicleId"], "runtime.vehicle.mismatch"),
        (
            _normalize_controller(observed.actual_controller_id),
            _normalize_controller(str(request["vehicle"]["controllerId"])),
            "runtime.controller.mismatch",
        ),
        (
            observed.actual_firmware_family,
            request["vehicle"]["firmwareFamily"],
            "runtime.firmware.family-mismatch",
        ),
        (
            observed.actual_firmware_version,
            request["vehicle"]["firmwareVersion"],
            "runtime.firmware.version-mismatch",
        ),
        (
            observed.actual_firmware_identity_hash,
            request["vehicle"]["firmwareIdentityHash"],
            "runtime.firmware.identity-mismatch",
        ),
        (
            observed.actual_parameter_candidate_hash,
            request["parameterCandidateHash"],
            "runtime.parameter-candidate.mismatch",
        ),
        (observed.actual_target_kind, request["targetKind"], "runtime.target.mismatch"),
    )
    reasons.extend(reason for actual, expected, reason in comparisons if actual != expected)
    if dict(observed.locally_verified_evidence_hashes) != _evidence_hashes(request):
        reasons.append("runtime.evidence.local-state-mismatch")
    if request["authorizationRequestId"] in observed.consumed_authorization_ids:
        reasons.append("runtime.request.replayed")
    if request["nonce"] in observed.consumed_nonces:
        reasons.append("runtime.nonce.replayed")
    if request["sequence"] < observed.minimum_sequence:
        reasons.append("runtime.sequence.stale")
    return reasons


def _catalog_reasons(
    contract: ModuleType,
    request: Mapping[str, Any],
    observed: RuntimeTrustedObservation,
    *,
    capability_policy: Mapping[str, Any],
    pack: Mapping[str, Any],
) -> list[str]:
    root = observed.active_engine_root
    reasons: list[str] = []
    paths = {
        "capability": root / "distribution/capabilities/core-capabilities.v1.json",
        "gate": root / "distribution/safety/edition-execution-gate.v1.json",
        "edition": root / f"distribution/editions/{request['editionId']}.v1.json",
        "pack": root / f"distribution/vehicle-packs/{request['vehicle']['packId']}.v1.json",
    }
    expected_hashes = {
        "capability": request["policy"]["capabilityPolicySha256"],
        "gate": request["policy"]["executionGatePolicySha256"],
        "edition": request["policy"]["editionManifestSha256"],
        "pack": request["vehicle"]["packManifestSha256"],
    }
    for name, path in paths.items():
        if not path.is_file() or contract.sha256_file(path) != expected_hashes[name]:
            reasons.append(f"runtime.{name}.hash-mismatch")

    capability = next(
        (
            item
            for item in capability_policy.get("capabilities", [])
            if item.get("id") == request["action"]
        ),
        None,
    )
    if capability is None:
        reasons.append("runtime.action.unknown")
    else:
        if request["targetKind"] not in capability["targetKinds"]:
            reasons.append("runtime.target.incompatible")
        if capability["decisions"][request["editionId"]]["decision"] == "deny":
            reasons.append("runtime.edition.action-denied")
    if request["editionId"] not in pack["supportedEditions"]:
        reasons.append("runtime.pack.edition-incompatible")
    if request["vehicle"]["firmwareFamily"] != pack["autopilot"]["family"]:
        reasons.append("runtime.firmware.family-incompatible")
    if request["vehicle"]["firmwareVersion"] not in pack["autopilot"]["supportedFirmwareVersions"]:
        reasons.append("runtime.firmware.version-incompatible")

    requested_controller = _normalize_controller(str(request["vehicle"]["controllerId"]))
    controller_status = next(
        (
            str(controller["status"])
            for controller in pack["controllers"]
            if _normalize_controller(f"{controller['vendor']}:{controller['model']}")
            == requested_controller
        ),
        None,
    )
    validation_status = str(pack["validationStatus"])
    validation_tier = str(pack["validationTier"])
    signature_state = str(pack["integrity"]["signature"]["state"])
    if observed.test_catalog_override:
        if observed.app_env != "test" or request["testOnly"] is not True:
            reasons.append("runtime.test-override.production-forbidden")
        else:
            validation_status = observed.pack_validation_status_override or validation_status
            validation_tier = observed.pack_validation_tier_override or validation_tier
            signature_state = observed.pack_signature_state_override or signature_state
            controller_status = observed.controller_status_override or controller_status
    if str(request["action"]).startswith("hardware."):
        if validation_status != "validated" or validation_tier != "hardware-validated":
            reasons.append("runtime.pack.unvalidated")
        if signature_state != "verified":
            reasons.append("runtime.pack.signature-unverified")
        if controller_status != "validated":
            reasons.append("runtime.controller.unvalidated")
    return reasons


def _build_receipt(
    contract: ModuleType,
    request: Mapping[str, Any],
    observed: RuntimeTrustedObservation,
    *,
    decision: str,
    reason_codes: tuple[str, ...],
) -> dict[str, Any]:
    request_expires = dt.datetime.fromisoformat(
        str(request["expiresAt"]).removesuffix("Z") + "+00:00"
    )
    expires_at = min(request_expires, observed.observed_at + dt.timedelta(seconds=120))
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "dronedream-edition-layer-decision-receipt",
        "authorizationRequestId": request["authorizationRequestId"],
        "authorizationRequestHash": contract.authorization_request_hash(request),
        "contextHash": contract.authorization_context_hash(request),
        "layer": "runtime",
        "decision": decision,
        "reasonCodes": list(reason_codes),
        "canonicalDecisionHash": "",
        "issuedAt": _isoformat(observed.observed_at),
        "expiresAt": _isoformat(expires_at),
        "nonce": f"runtime:{request['nonce']}:{request['sequence']}",
        "sequence": request["sequence"],
        "issuer": (
            "test-fixture:e5-runtime" if request["testOnly"] else "runtime:edition-safety-v1"
        ),
        "testOnly": request["testOnly"],
        "consumptionState": "unconsumed",
    }
    unhashed = dict(receipt)
    unhashed.pop("canonicalDecisionHash")
    receipt["canonicalDecisionHash"] = contract.sha256_canonical(unhashed)
    return receipt


def evaluate_runtime_authorization(
    request: Mapping[str, Any], observed: RuntimeTrustedObservation
) -> RuntimeLayerDecision:
    """Return one Runtime decision receipt without performing an action."""

    contract = _load_contract(observed.active_engine_root)
    capability_path = (
        observed.active_engine_root / "distribution/capabilities/core-capabilities.v1.json"
    )
    gate_path = observed.active_engine_root / "distribution/safety/edition-execution-gate.v1.json"
    capability_policy = _load_object(capability_path, "active capability policy")
    gate_policy = contract.validate_gate_policy(
        _load_object(gate_path, "active execution gate policy"),
        capability_policy_sha256=contract.sha256_file(capability_path),
    )
    try:
        validated = contract.validate_authorization_request(
            request,
            policy=gate_policy,
            execution_gate_policy_sha256=contract.sha256_file(gate_path),
            capability_policy_sha256=contract.sha256_file(capability_path),
            app_env=observed.app_env,
            now=observed.observed_at,
        )
    except contract.EditionSafetyContractError as error:
        raise RuntimeEditionSafetyError("authorization request failed closed") from error
    _edition, pack = _validate_active_catalog(contract, observed.active_engine_root, validated)
    reasons = _active_inventory_reasons(contract, validated, observed)
    reasons.extend(_local_target_reasons(validated, observed))
    reasons.extend(
        _catalog_reasons(
            contract,
            validated,
            observed,
            capability_policy=capability_policy,
            pack=pack,
        )
    )
    reason_codes = tuple(sorted(set(reasons))) or ("runtime.contract.allow",)
    decision = "deny" if reasons else "allow"
    receipt = _build_receipt(
        contract,
        validated,
        observed,
        decision=decision,
        reason_codes=reason_codes,
    )
    contract.validate_layer_decision_receipt(
        receipt,
        request=validated,
        policy=gate_policy,
        app_env=observed.app_env,
        now=observed.observed_at,
    )
    return RuntimeLayerDecision(decision, reason_codes, receipt)


__all__ = [
    "RUNTIME_CONTRACT_REGISTRY_PATH",
    "RUNTIME_DISTRIBUTION_BASE_PATHS",
    "RuntimeEditionSafetyError",
    "RuntimeLayerDecision",
    "RuntimeTrustedObservation",
    "evaluate_runtime_authorization",
    "runtime_distribution_paths",
]
