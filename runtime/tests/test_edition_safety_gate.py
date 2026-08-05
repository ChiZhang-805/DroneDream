from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_GATE_PATH = ROOT / "runtime/scripts/edition-safety-gate.py"
CONTRACT_PATH = ROOT / "distribution/tools/edition_safety_contract.py"
FIXTURE_PATH = ROOT / "distribution/tests/fixtures/edition-safety-cases.v1.json"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = load_module("runtime_edition_safety_gate_tests", RUNTIME_GATE_PATH)
contract = load_module("runtime_edition_safety_contract_tests", CONTRACT_PATH)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def request_fixture() -> dict[str, object]:
    return deepcopy(FIXTURE["baseRequest"])


def refresh_context_hashes(request: dict[str, object]) -> None:
    context_hash = contract.authorization_context_hash(request)
    receipts = request["evidenceReceipts"]
    assert isinstance(receipts, list)
    for receipt in receipts:
        receipt["contextHash"] = context_hash


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def active_observation(
    tmp_path: Path, request: dict[str, object]
) -> gate.RuntimeTrustedObservation:
    active_root = tmp_path / "active-engine"
    records: list[dict[str, object]] = []
    for relative in gate.runtime_distribution_paths(ROOT):
        source = ROOT / relative
        destination = active_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append(
            {
                "path": relative,
                "sizeBytes": destination.stat().st_size,
                "sha256": contract.sha256_file(destination),
            }
        )
    source = request["source"]
    assert isinstance(source, dict)
    engine_manifest_path = tmp_path / "engine-pack-manifest.json"
    write_json(
        engine_manifest_path,
        {
            "schemaVersion": 1,
            "kind": "dronedream-engine-pack",
            "source": {"gitCommit": source["repositoryCommit"]},
            "files": records,
        },
    )
    runtime_manifest_path = tmp_path / "runtime-manifest.json"
    write_json(
        runtime_manifest_path,
        {
            "schemaVersion": 1,
            "source": {"droneDreamCommit": source["repositoryCommit"]},
        },
    )
    source["enginePackManifestSha256"] = contract.sha256_file(engine_manifest_path)
    source["runtimeBaseManifestSha256"] = contract.sha256_file(runtime_manifest_path)
    refresh_context_hashes(request)

    device = request["deviceHardwareIdentity"]
    vehicle = request["vehicle"]
    receipts = request["evidenceReceipts"]
    assert isinstance(device, dict)
    assert isinstance(vehicle, dict)
    assert isinstance(receipts, list)
    return gate.RuntimeTrustedObservation(
        active_engine_root=active_root,
        active_engine_pack_manifest_path=engine_manifest_path,
        active_runtime_base_manifest_path=runtime_manifest_path,
        engine_pack_signature_verified=True,
        composite_inventory_hash=str(request["compositeInventoryHash"]),
        actual_device_id=str(device["deviceId"]),
        actual_device_hardware_identity_hash=str(device["hardwareIdentityHash"]),
        actual_vehicle_id=str(vehicle["vehicleId"]),
        actual_controller_id=str(vehicle["controllerId"]),
        actual_firmware_family=str(vehicle["firmwareFamily"]),
        actual_firmware_version=str(vehicle["firmwareVersion"]),
        actual_firmware_identity_hash=str(vehicle["firmwareIdentityHash"]),
        actual_parameter_candidate_hash=str(request["parameterCandidateHash"]),
        actual_target_kind=str(request["targetKind"]),
        locally_verified_evidence_hashes={
            str(receipt["receiptType"]): str(receipt["evidenceHash"]) for receipt in receipts
        },
        observed_at=dt.datetime(2026, 8, 5, 0, 1, 0, tzinfo=dt.UTC),
        app_env="test",
    )


def allow_override(
    observation: gate.RuntimeTrustedObservation,
) -> gate.RuntimeTrustedObservation:
    return replace(
        observation,
        test_catalog_override=True,
        pack_validation_status_override="validated",
        pack_validation_tier_override="hardware-validated",
        pack_signature_state_override="verified",
        controller_status_override="validated",
    )


def test_runtime_independently_denies_current_unvalidated_catalog(tmp_path: Path) -> None:
    request = request_fixture()
    result = gate.evaluate_runtime_authorization(request, active_observation(tmp_path, request))
    assert result.decision == "deny"
    assert {
        "runtime.pack.unvalidated",
        "runtime.pack.signature-unverified",
        "runtime.controller.unvalidated",
    } <= set(result.reason_codes)
    assert result.receipt["layer"] == "runtime"


def test_test_only_validated_fixture_can_reach_runtime_allow(tmp_path: Path) -> None:
    request = request_fixture()
    observation = allow_override(active_observation(tmp_path, request))
    result = gate.evaluate_runtime_authorization(request, observation)
    assert result.decision == "allow"
    assert result.reason_codes == ("runtime.contract.allow",)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            {"actual_device_id": "device:other"},
            "runtime.device.id-mismatch",
        ),
        (
            {"actual_device_hardware_identity_hash": "0" * 64},
            "runtime.device.identity-mismatch",
        ),
        ({"actual_parameter_candidate_hash": "0" * 64}, "runtime.parameter-candidate.mismatch"),
        ({"actual_target_kind": "hitl"}, "runtime.target.mismatch"),
        ({"minimum_sequence": 2}, "runtime.sequence.stale"),
    ],
)
def test_runtime_uses_actual_target_not_backend_claims(
    tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    request = request_fixture()
    observation = replace(allow_override(active_observation(tmp_path, request)), **change)
    result = gate.evaluate_runtime_authorization(request, observation)
    assert result.decision == "deny"
    assert reason in result.reason_codes


def test_active_engine_signature_and_contract_file_tamper_are_denied(tmp_path: Path) -> None:
    request = request_fixture()
    observation = allow_override(active_observation(tmp_path, request))

    unsigned = replace(observation, engine_pack_signature_verified=False)
    result = gate.evaluate_runtime_authorization(request, unsigned)
    assert result.decision == "deny"
    assert "runtime.engine-pack.signature-unverified" in result.reason_codes

    (observation.active_engine_root / "LICENSE").write_text("tampered", encoding="utf-8")
    result = gate.evaluate_runtime_authorization(request, observation)
    assert result.decision == "deny"
    assert {
        "runtime.engine-pack.contract-file-size-mismatch",
        "runtime.engine-pack.contract-file-hash-mismatch",
    } <= set(result.reason_codes)


def test_runtime_contract_registry_drift_is_a_structured_deny(tmp_path: Path) -> None:
    request = request_fixture()
    observation = allow_override(active_observation(tmp_path, request))
    registry_path = observation.active_engine_root / gate.RUNTIME_CONTRACT_REGISTRY_PATH
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["contractPaths"] = ["distribution/tests/test_fake.py"]
    write_json(registry_path, registry)

    result = gate.evaluate_runtime_authorization(request, observation)

    assert result.decision == "deny"
    assert "runtime.engine-pack.contract-registry-invalid" in result.reason_codes


def test_runtime_reverifies_engine_and_runtime_source_binding(tmp_path: Path) -> None:
    request = request_fixture()
    observation = allow_override(active_observation(tmp_path, request))
    engine_manifest = json.loads(
        observation.active_engine_pack_manifest_path.read_text(encoding="utf-8")
    )
    engine_manifest["source"]["gitCommit"] = "f" * 40
    write_json(observation.active_engine_pack_manifest_path, engine_manifest)
    source = request["source"]
    assert isinstance(source, dict)
    source["enginePackManifestSha256"] = contract.sha256_file(
        observation.active_engine_pack_manifest_path
    )
    refresh_context_hashes(request)
    result = gate.evaluate_runtime_authorization(request, observation)
    assert result.decision == "deny"
    assert "runtime.engine-pack.source-mismatch" in result.reason_codes


def test_replay_local_evidence_disagreement_and_clock_boundary_are_closed(
    tmp_path: Path,
) -> None:
    request = request_fixture()
    observation = allow_override(active_observation(tmp_path, request))
    replay = replace(
        observation,
        consumed_authorization_ids=frozenset({str(request["authorizationRequestId"])}),
        consumed_nonces=frozenset({str(request["nonce"])}),
    )
    result = gate.evaluate_runtime_authorization(request, replay)
    assert {"runtime.request.replayed", "runtime.nonce.replayed"} <= set(result.reason_codes)

    result = gate.evaluate_runtime_authorization(
        request, replace(observation, locally_verified_evidence_hashes={})
    )
    assert "runtime.evidence.local-state-mismatch" in result.reason_codes

    expired = replace(observation, observed_at=dt.datetime(2026, 8, 5, 0, 5, 0, tzinfo=dt.UTC))
    with pytest.raises(gate.RuntimeEditionSafetyError, match="failed closed"):
        gate.evaluate_runtime_authorization(request, expired)

    future = replace(observation, observed_at=dt.datetime(2026, 8, 4, 23, 59, 59, tzinfo=dt.UTC))
    with pytest.raises(gate.RuntimeEditionSafetyError, match="failed closed"):
        gate.evaluate_runtime_authorization(request, future)


def test_unknown_schema_and_fake_issuer_in_production_fail_closed(tmp_path: Path) -> None:
    request = request_fixture()
    observation = allow_override(active_observation(tmp_path, request))
    unknown = deepcopy(request)
    unknown["unexpected"] = True
    with pytest.raises(gate.RuntimeEditionSafetyError, match="failed closed"):
        gate.evaluate_runtime_authorization(unknown, observation)
    with pytest.raises(gate.RuntimeEditionSafetyError, match="failed closed"):
        gate.evaluate_runtime_authorization(request, replace(observation, app_env="production"))


def test_backend_allow_runtime_deny_cannot_become_joint_allow(tmp_path: Path) -> None:
    backend = load_module(
        "backend_distribution_safety_differential_tests",
        ROOT / "backend/app/distribution_safety.py",
    )
    request = request_fixture()
    runtime_observation = allow_override(active_observation(tmp_path, request))
    actor = request["actor"]
    device = request["deviceHardwareIdentity"]
    vehicle = request["vehicle"]
    policy = request["policy"]
    source = request["source"]
    receipts = request["evidenceReceipts"]
    assert all(isinstance(value, dict) for value in (actor, device, vehicle, policy, source))
    assert isinstance(receipts, list)
    backend_context = backend.BackendTrustedContext(
        account_id=str(actor["accountId"]),
        actor_id=str(actor["actorId"]),
        registered_device_id=str(device["deviceId"]),
        registered_device_hardware_identity_hash=str(device["hardwareIdentityHash"]),
        repository_commit=str(source["repositoryCommit"]),
        engine_pack_manifest_sha256=str(source["enginePackManifestSha256"]),
        runtime_base_manifest_sha256=str(source["runtimeBaseManifestSha256"]),
        composite_inventory_hash=str(request["compositeInventoryHash"]),
        edition_manifest_sha256=str(policy["editionManifestSha256"]),
        vehicle_pack_manifest_sha256=str(vehicle["packManifestSha256"]),
        vehicle_id=str(vehicle["vehicleId"]),
        controller_id=str(vehicle["controllerId"]),
        firmware_family=str(vehicle["firmwareFamily"]),
        firmware_version=str(vehicle["firmwareVersion"]),
        firmware_identity_hash=str(vehicle["firmwareIdentityHash"]),
        parameter_candidate_hash=str(request["parameterCandidateHash"]),
        trusted_evidence_hashes={
            str(receipt["receiptType"]): str(receipt["evidenceHash"]) for receipt in receipts
        },
        observed_at=runtime_observation.observed_at,
        app_env="test",
        test_catalog_override=True,
        pack_validation_status_override="validated",
        pack_validation_tier_override="hardware-validated",
        pack_signature_state_override="verified",
        controller_status_override="validated",
    )
    backend_result = backend.evaluate_backend_authorization(request, backend_context)
    runtime_result = gate.evaluate_runtime_authorization(
        request,
        replace(runtime_observation, actual_device_hardware_identity_hash="0" * 64),
    )
    assert backend_result.decision == "allow"
    assert runtime_result.decision == "deny"
    native: dict[str, object] = {
        "schemaVersion": 1,
        "kind": "dronedream-edition-layer-decision-receipt",
        "authorizationRequestId": request["authorizationRequestId"],
        "authorizationRequestHash": contract.authorization_request_hash(request),
        "contextHash": contract.authorization_context_hash(request),
        "layer": "native",
        "decision": "allow",
        "reasonCodes": ["native.contract.allow"],
        "canonicalDecisionHash": "",
        "issuedAt": "2026-08-05T00:01:00Z",
        "expiresAt": "2026-08-05T00:03:00Z",
        "nonce": "native:nonce:e5-request-001:1",
        "sequence": 1,
        "issuer": "test-fixture:e5-native",
        "testOnly": True,
        "consumptionState": "unconsumed",
    }
    native_without_hash = dict(native)
    native_without_hash.pop("canonicalDecisionHash")
    native["canonicalDecisionHash"] = contract.sha256_canonical(native_without_hash)
    layers = [native, dict(backend_result.receipt), dict(runtime_result.receipt)]
    quorum = {
        "schemaVersion": 1,
        "kind": "dronedream-edition-authorization-quorum-receipt",
        "authorizationRequestId": request["authorizationRequestId"],
        "authorizationRequestHash": contract.authorization_request_hash(request),
        "contextHash": contract.authorization_context_hash(request),
        "layerDecisionHashes": {
            str(receipt["layer"]): receipt["canonicalDecisionHash"] for receipt in layers
        },
        "decision": "deny",
        "reasonCodes": list(runtime_result.reason_codes),
        "issuedAt": "2026-08-05T00:01:00Z",
        "expiresAt": "2026-08-05T00:03:00Z",
        "nonce": "quorum:nonce:e5-request-001:1",
        "sequence": 1,
        "oneTime": True,
        "consumptionState": "unconsumed",
        "appendOnlyAudit": True,
    }
    capability_path = (
        runtime_observation.active_engine_root
        / "distribution/capabilities/core-capabilities.v1.json"
    )
    gate_path = (
        runtime_observation.active_engine_root
        / "distribution/safety/edition-execution-gate.v1.json"
    )
    policy_document = json.loads(gate_path.read_text(encoding="utf-8"))
    policy_contract = contract.validate_gate_policy(
        policy_document,
        capability_policy_sha256=contract.sha256_file(capability_path),
    )
    validated = contract.validate_quorum_receipt(
        quorum,
        request=request,
        layer_receipts=layers,
        policy=policy_contract,
        app_env="test",
        now=runtime_observation.observed_at,
    )
    assert validated["decision"] == "deny"

    backend_denied = backend.evaluate_backend_authorization(
        request, replace(backend_context, actor_id="actor:other")
    )
    runtime_allowed = gate.evaluate_runtime_authorization(request, runtime_observation)
    assert backend_denied.decision == "deny"
    assert runtime_allowed.decision == "allow"

    reverse_layers = [native, dict(backend_denied.receipt), dict(runtime_allowed.receipt)]
    reverse_quorum = deepcopy(quorum)
    reverse_quorum["layerDecisionHashes"] = {
        str(receipt["layer"]): receipt["canonicalDecisionHash"]
        for receipt in reverse_layers
    }
    reverse_quorum["reasonCodes"] = list(backend_denied.reason_codes)
    validated_reverse = contract.validate_quorum_receipt(
        reverse_quorum,
        request=request,
        layer_receipts=reverse_layers,
        policy=policy_contract,
        app_env="test",
        now=runtime_observation.observed_at,
    )
    assert validated_reverse["decision"] == "deny"


def test_runtime_module_exposes_no_action_or_device_handler() -> None:
    assert not any(
        token in name.lower()
        for name in gate.__all__
        for token in ("route", "write", "arm", "flight", "install", "device_handler")
    )
