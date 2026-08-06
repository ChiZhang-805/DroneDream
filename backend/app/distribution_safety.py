"""Backend-owned E5 edition execution authorization decision.

The frontend cannot call an action through this module.  It validates one
closed authorization request against server-derived identity, source, catalog,
and evidence state, then returns only a signed-hash-ready decision envelope.
No device, parameter, arm, flight, simulator, or installation handler exists
here.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any


class BackendDistributionSafetyError(RuntimeError):
    """Raised when a request cannot produce a trusted backend receipt."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_contract(repository_root: Path) -> ModuleType:
    path = repository_root / "distribution" / "tools" / "edition_safety_contract.py"
    name = "dronedream_backend_edition_safety_contract"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BackendDistributionSafetyError("edition safety contract is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_distribution_contract(repository_root: Path) -> ModuleType:
    path = repository_root / "distribution" / "tools" / "distribution_contract.py"
    name = "dronedream_backend_distribution_contract"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BackendDistributionSafetyError("distribution contract is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BackendDistributionSafetyError(f"unable to load {label}") from error
    if not isinstance(value, dict):
        raise BackendDistributionSafetyError(f"{label} is not an object")
    return value


def _sha256_file(contract: ModuleType, path: Path) -> str:
    return str(contract.sha256_file(path))


def _normalize_controller(vendor: str, model: str) -> str:
    return f"{vendor}:{model}".replace(" ", "").lower()


def _request_controller(value: str) -> str:
    return value.replace(" ", "").lower()


def _isoformat(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise BackendDistributionSafetyError("decision time must be timezone-aware")
    return value.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class BackendTrustedContext:
    """Server-derived state; none of these values are accepted from the UI."""

    account_id: str
    actor_id: str
    registered_device_id: str
    registered_device_hardware_identity_hash: str
    repository_commit: str
    engine_pack_manifest_sha256: str
    runtime_base_manifest_sha256: str
    composite_inventory_hash: str
    edition_manifest_sha256: str
    vehicle_pack_manifest_sha256: str
    vehicle_id: str
    controller_id: str
    firmware_family: str
    firmware_version: str
    firmware_identity_hash: str
    parameter_candidate_hash: str
    trusted_evidence_hashes: Mapping[str, str]
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
class BackendLayerDecision:
    decision: str
    reason_codes: tuple[str, ...]
    receipt: Mapping[str, Any]


def _catalog(repository_root: Path, pack_id: str) -> tuple[
    dict[str, Any],
    Path,
    dict[str, Any],
    Path,
    dict[str, Any],
    Path,
]:
    distribution = repository_root / "distribution"
    distribution_contract = _load_distribution_contract(repository_root)
    capability_path = distribution / "capabilities" / "core-capabilities.v1.json"
    gate_path = distribution / "safety" / "edition-execution-gate.v1.json"
    pack_path = distribution / "vehicle-packs" / f"{pack_id}.v1.json"
    if not pack_path.is_file():
        raise BackendDistributionSafetyError("Vehicle Pack is absent from the active catalog")
    capability = distribution_contract.validate_capability_policy(
        _load_object(capability_path, "capability policy")
    )
    upstream = distribution_contract.validate_upstream_source_inventory(
        _load_object(distribution / "upstream-sources.v1.json", "upstream source inventory")
    )
    packs_by_path: dict[str, dict[str, Any]] = {}
    pack_hashes: dict[str, str] = {}
    for candidate in sorted((distribution / "vehicle-packs").glob("*.v1.json")):
        if candidate.name.startswith("registry."):
            continue
        relative = candidate.relative_to(repository_root).as_posix()
        packs_by_path[relative] = distribution_contract.validate_vehicle_pack_manifest(
            _load_object(candidate, "Vehicle Pack manifest"),
            upstream_inventory=upstream,
            capability_policy_sha256=distribution_contract.sha256_file(capability_path),
        )
        pack_hashes[relative] = distribution_contract.sha256_file(candidate)
    distribution_contract.validate_vehicle_pack_registry(
        _load_object(distribution / "vehicle-packs/registry.v1.json", "Vehicle Pack registry"),
        vehicle_packs_by_path=packs_by_path,
        vehicle_pack_manifest_sha256=pack_hashes,
    )
    pack_relative = pack_path.relative_to(repository_root).as_posix()
    return (
        capability,
        capability_path,
        _load_object(gate_path, "execution gate policy"),
        gate_path,
        packs_by_path[pack_relative],
        pack_path,
    )


def _edition_path(repository_root: Path, edition_id: str) -> Path:
    path = repository_root / "distribution" / "editions" / f"{edition_id}.v1.json"
    if not path.is_file():
        raise BackendDistributionSafetyError("edition is absent from the active catalog")
    return path


def _evidence_hashes(request: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(receipt["receiptType"]): str(receipt["evidenceHash"])
        for receipt in request["evidenceReceipts"]
    }


def _capability(
    capability_policy: Mapping[str, Any], action: str
) -> Mapping[str, Any] | None:
    return next(
        (
            capability
            for capability in capability_policy["capabilities"]
            if capability["id"] == action
        ),
        None,
    )


def _controller_status(pack: Mapping[str, Any], requested: str) -> str | None:
    normalized = _request_controller(requested)
    for controller in pack["controllers"]:
        if _normalize_controller(controller["vendor"], controller["model"]) == normalized:
            return str(controller["status"])
    return None


def _append_mismatch(
    reasons: list[str],
    observed: Any,
    expected: Any,
    reason: str,
) -> None:
    if observed != expected:
        reasons.append(reason)


def _trusted_context_reasons(
    request: Mapping[str, Any], trusted: BackendTrustedContext
) -> list[str]:
    reasons: list[str] = []
    _append_mismatch(
        reasons,
        trusted.account_id,
        request["actor"]["accountId"],
        "backend.actor.account-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.actor_id,
        request["actor"]["actorId"],
        "backend.actor.identity-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.registered_device_id,
        request["deviceHardwareIdentity"]["deviceId"],
        "backend.device.id-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.registered_device_hardware_identity_hash,
        request["deviceHardwareIdentity"]["hardwareIdentityHash"],
        "backend.device.identity-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.repository_commit,
        request["source"]["repositoryCommit"],
        "backend.source.repository-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.engine_pack_manifest_sha256,
        request["source"]["enginePackManifestSha256"],
        "backend.source.engine-pack-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.runtime_base_manifest_sha256,
        request["source"]["runtimeBaseManifestSha256"],
        "backend.source.runtime-base-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.composite_inventory_hash,
        request["compositeInventoryHash"],
        "backend.source.composite-inventory-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.edition_manifest_sha256,
        request["policy"]["editionManifestSha256"],
        "backend.edition.manifest-mismatch",
    )
    _append_mismatch(
        reasons,
        trusted.vehicle_pack_manifest_sha256,
        request["vehicle"]["packManifestSha256"],
        "backend.pack.manifest-mismatch",
    )
    for field_name, observed, expected in (
        ("vehicle", trusted.vehicle_id, request["vehicle"]["vehicleId"]),
        ("controller", trusted.controller_id, request["vehicle"]["controllerId"]),
        ("firmware-family", trusted.firmware_family, request["vehicle"]["firmwareFamily"]),
        ("firmware-version", trusted.firmware_version, request["vehicle"]["firmwareVersion"]),
        (
            "firmware-identity",
            trusted.firmware_identity_hash,
            request["vehicle"]["firmwareIdentityHash"],
        ),
        (
            "parameter-candidate",
            trusted.parameter_candidate_hash,
            request["parameterCandidateHash"],
        ),
    ):
        _append_mismatch(reasons, observed, expected, f"backend.{field_name}.mismatch")
    if dict(trusted.trusted_evidence_hashes) != _evidence_hashes(request):
        reasons.append("backend.evidence.server-state-mismatch")
    if request["authorizationRequestId"] in trusted.consumed_authorization_ids:
        reasons.append("backend.request.replayed")
    if request["nonce"] in trusted.consumed_nonces:
        reasons.append("backend.nonce.replayed")
    if request["sequence"] < trusted.minimum_sequence:
        reasons.append("backend.sequence.stale")
    return reasons


def _catalog_reasons(
    request: Mapping[str, Any],
    trusted: BackendTrustedContext,
    *,
    capability_policy: Mapping[str, Any],
    capability_policy_sha256: str,
    gate_policy_sha256: str,
    edition: Mapping[str, Any],
    edition_sha256: str,
    pack: Mapping[str, Any],
    pack_sha256: str,
) -> list[str]:
    reasons: list[str] = []
    if request["policy"]["capabilityPolicySha256"] != capability_policy_sha256:
        reasons.append("backend.policy.capability-hash-mismatch")
    if request["policy"]["executionGatePolicySha256"] != gate_policy_sha256:
        reasons.append("backend.policy.execution-gate-hash-mismatch")
    if request["policy"]["editionManifestSha256"] != edition_sha256:
        reasons.append("backend.edition.hash-mismatch")
    if request["vehicle"]["packManifestSha256"] != pack_sha256:
        reasons.append("backend.pack.hash-mismatch")
    if edition["capabilityPolicy"]["sha256"] != capability_policy_sha256:
        reasons.append("backend.edition.policy-binding-mismatch")
    if pack["safety"]["capabilityPolicySha256"] != capability_policy_sha256:
        reasons.append("backend.pack.policy-binding-mismatch")
    if request["editionId"] not in pack["supportedEditions"]:
        reasons.append("backend.pack.edition-incompatible")
    if request["vehicle"]["firmwareFamily"] != pack["autopilot"]["family"]:
        reasons.append("backend.firmware.family-incompatible")
    if request["vehicle"]["firmwareVersion"] not in pack["autopilot"][
        "supportedFirmwareVersions"
    ]:
        reasons.append("backend.firmware.version-incompatible")

    capability = _capability(capability_policy, str(request["action"]))
    if capability is None:
        reasons.append("backend.action.unknown")
    else:
        if request["targetKind"] not in capability["targetKinds"]:
            reasons.append("backend.target.incompatible")
        edition_decision = capability["decisions"][request["editionId"]]
        if edition_decision["decision"] == "deny":
            reasons.append("backend.edition.action-denied")

    validation_status = str(pack["validationStatus"])
    validation_tier = str(pack["validationTier"])
    signature_state = str(pack["integrity"]["signature"]["state"])
    controller_status = _controller_status(pack, str(request["vehicle"]["controllerId"]))
    if trusted.test_catalog_override:
        if trusted.app_env != "test" or request["testOnly"] is not True:
            reasons.append("backend.test-override.production-forbidden")
        else:
            validation_status = trusted.pack_validation_status_override or validation_status
            validation_tier = trusted.pack_validation_tier_override or validation_tier
            signature_state = trusted.pack_signature_state_override or signature_state
            controller_status = trusted.controller_status_override or controller_status
    if str(request["action"]).startswith("hardware."):
        if validation_status != "validated" or validation_tier != "hardware-validated":
            reasons.append("backend.pack.unvalidated")
        if signature_state != "verified":
            reasons.append("backend.pack.signature-unverified")
        if controller_status != "validated":
            reasons.append("backend.controller.unvalidated")
    return reasons


def _build_receipt(
    contract: ModuleType,
    request: Mapping[str, Any],
    *,
    decision: str,
    reason_codes: tuple[str, ...],
    trusted: BackendTrustedContext,
) -> dict[str, Any]:
    request_expires = dt.datetime.fromisoformat(
        str(request["expiresAt"]).removesuffix("Z") + "+00:00"
    )
    expires_at = min(request_expires, trusted.observed_at + dt.timedelta(seconds=120))
    issuer = (
        "test-fixture:e5-backend"
        if request["testOnly"]
        else "backend:edition-safety-v1"
    )
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": "dronedream-edition-layer-decision-receipt",
        "authorizationRequestId": request["authorizationRequestId"],
        "authorizationRequestHash": contract.authorization_request_hash(request),
        "contextHash": contract.authorization_context_hash(request),
        "layer": "backend",
        "decision": decision,
        "reasonCodes": list(reason_codes),
        "canonicalDecisionHash": "",
        "issuedAt": _isoformat(trusted.observed_at),
        "expiresAt": _isoformat(expires_at),
        "nonce": f"backend:{request['nonce']}:{request['sequence']}",
        "sequence": request["sequence"],
        "issuer": issuer,
        "testOnly": request["testOnly"],
        "consumptionState": "unconsumed",
    }
    unhashed = dict(receipt)
    unhashed.pop("canonicalDecisionHash")
    receipt["canonicalDecisionHash"] = contract.sha256_canonical(unhashed)
    return receipt


def evaluate_backend_authorization(
    request: Mapping[str, Any],
    trusted: BackendTrustedContext,
    *,
    repository_root: Path | None = None,
) -> BackendLayerDecision:
    """Return only a backend decision receipt; never perform the requested action."""

    root = repository_root or _repository_root()
    contract = _load_contract(root)
    distribution_contract = _load_distribution_contract(root)
    distribution = root / "distribution"
    capability_path = distribution / "capabilities/core-capabilities.v1.json"
    gate_path = distribution / "safety/edition-execution-gate.v1.json"
    try:
        initial_capability = distribution_contract.validate_capability_policy(
            _load_object(capability_path, "capability policy")
        )
        capability_sha256 = _sha256_file(contract, capability_path)
        gate_sha256 = _sha256_file(contract, gate_path)
        initial_gate = contract.validate_gate_policy(
            _load_object(gate_path, "execution gate policy"),
            capability_policy_sha256=capability_sha256,
        )
        validated = contract.validate_authorization_request(
            request,
            policy=initial_gate,
            execution_gate_policy_sha256=gate_sha256,
            capability_policy_sha256=capability_sha256,
            app_env=trusted.app_env,
            now=trusted.observed_at,
        )
    except (
        BackendDistributionSafetyError,
        contract.EditionSafetyContractError,
        distribution_contract.DistributionContractError,
    ) as error:
        raise BackendDistributionSafetyError("authorization request failed closed") from error
    try:
        (
            capability_policy,
            capability_path,
            gate_policy_document,
            gate_path,
            pack,
            pack_path,
        ) = _catalog(root, str(validated["vehicle"]["packId"]))
    except (
        BackendDistributionSafetyError,
        distribution_contract.DistributionContractError,
    ) as error:
        raise BackendDistributionSafetyError("active backend catalog failed closed") from error
    if capability_policy != initial_capability:
        raise BackendDistributionSafetyError("capability policy changed during evaluation")
    gate_policy = contract.validate_gate_policy(
        gate_policy_document,
        capability_policy_sha256=capability_sha256,
    )
    if gate_policy != initial_gate:
        raise BackendDistributionSafetyError("execution gate policy changed during evaluation")
    edition_path = _edition_path(root, str(validated["editionId"]))
    try:
        edition = distribution_contract.validate_edition_manifest(
            _load_object(edition_path, "edition manifest"),
            policy=capability_policy,
            policy_sha256=capability_sha256,
        )
    except (
        BackendDistributionSafetyError,
        distribution_contract.DistributionContractError,
    ) as error:
        raise BackendDistributionSafetyError("active edition catalog failed closed") from error
    reasons = _trusted_context_reasons(validated, trusted)
    reasons.extend(
        _catalog_reasons(
            validated,
            trusted,
            capability_policy=capability_policy,
            capability_policy_sha256=capability_sha256,
            gate_policy_sha256=gate_sha256,
            edition=edition,
            edition_sha256=_sha256_file(contract, edition_path),
            pack=pack,
            pack_sha256=_sha256_file(contract, pack_path),
        )
    )
    reason_codes = tuple(sorted(set(reasons))) or ("backend.contract.allow",)
    decision = "deny" if reasons else "allow"
    receipt = _build_receipt(
        contract,
        validated,
        decision=decision,
        reason_codes=reason_codes,
        trusted=trusted,
    )
    contract.validate_layer_decision_receipt(
        receipt,
        request=validated,
        policy=gate_policy,
        app_env=trusted.app_env,
        now=trusted.observed_at,
    )
    return BackendLayerDecision(
        decision=decision,
        reason_codes=reason_codes,
        receipt=receipt,
    )


__all__ = [
    "BackendDistributionSafetyError",
    "BackendLayerDecision",
    "BackendTrustedContext",
    "evaluate_backend_authorization",
]
