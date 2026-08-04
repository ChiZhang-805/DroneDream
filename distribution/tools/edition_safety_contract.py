#!/usr/bin/env python3
"""Validate the closed, plan-only E5 multi-layer authorization contract.

This module performs no installation, simulator, network, device, parameter,
arm, or flight action.  It validates canonical request and receipt envelopes so
native, backend, and Runtime implementations can fail closed on the same bytes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
DOTTED_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$"
)

POLICY_KEYS = {
    "schemaVersion",
    "kind",
    "policyId",
    "policyVersion",
    "defaultDecision",
    "frontendIsAuthority",
    "hardwareActionHandlersImplemented",
    "capabilityPolicy",
    "requiredDecisionLayers",
    "contextBinding",
    "receiptPolicy",
    "qualificationPolicy",
    "structuredEvidence",
    "editionBoundaries",
    "compatibilityBindings",
    "quorum",
    "fakeIssuerPolicy",
    "auditPolicy",
}
REQUEST_KEYS = {
    "schemaVersion",
    "kind",
    "authorizationRequestId",
    "actor",
    "deviceHardwareIdentity",
    "vehicle",
    "parameterCandidateHash",
    "compositeInventoryHash",
    "policy",
    "source",
    "editionId",
    "action",
    "targetKind",
    "issuedAt",
    "expiresAt",
    "nonce",
    "sequence",
    "evidenceReceipts",
    "issuer",
    "testOnly",
}
ACTOR_KEYS = {"accountId", "actorId"}
DEVICE_KEYS = {"deviceId", "hardwareIdentityHash"}
VEHICLE_KEYS = {
    "vehicleId",
    "packId",
    "packManifestSha256",
    "controllerId",
    "firmwareFamily",
    "firmwareVersion",
    "firmwareIdentityHash",
    "dynamicsConfigHash",
    "sensorConfigHash",
    "payloadConfigHash",
}
POLICY_BINDING_KEYS = {
    "capabilityPolicyId",
    "capabilityPolicyVersion",
    "capabilityPolicySha256",
    "executionGatePolicyId",
    "executionGatePolicyVersion",
    "executionGatePolicySha256",
    "editionManifestSha256",
}
SOURCE_KEYS = {
    "repositoryCommit",
    "enginePackManifestSha256",
    "runtimeBaseManifestSha256",
}
EVIDENCE_KEYS = {
    "schemaVersion",
    "kind",
    "receiptType",
    "receiptId",
    "authorizationRequestId",
    "contextHash",
    "issuer",
    "issuerLayer",
    "status",
    "issuedAt",
    "expiresAt",
    "nonce",
    "sequence",
    "evidenceHash",
    "qualificationLevel",
    "bindings",
    "oneTime",
    "consumptionState",
}
BINDING_KEYS = {"name", "sha256"}
LAYER_DECISION_KEYS = {
    "schemaVersion",
    "kind",
    "authorizationRequestId",
    "authorizationRequestHash",
    "contextHash",
    "layer",
    "decision",
    "reasonCodes",
    "canonicalDecisionHash",
    "issuedAt",
    "expiresAt",
    "nonce",
    "sequence",
    "issuer",
    "testOnly",
    "consumptionState",
}
QUORUM_KEYS = {
    "schemaVersion",
    "kind",
    "authorizationRequestId",
    "authorizationRequestHash",
    "contextHash",
    "layerDecisionHashes",
    "decision",
    "reasonCodes",
    "issuedAt",
    "expiresAt",
    "nonce",
    "sequence",
    "oneTime",
    "consumptionState",
    "appendOnlyAudit",
}
RECEIPT_TYPES = {
    "trusted-qualification",
    "parameter-snapshot",
    "transaction-rollback",
    "operator-confirmation",
    "preflight",
    "safety-zone",
    "control-takeover",
    "emergency-stop",
}
BINDING_NAMES = {
    "parameterCandidateHash",
    "scenarioContractHash",
    "vehicleDynamicsConfigHash",
    "sensorConfigHash",
    "payloadConfigHash",
    "holdoutContractHash",
    "snapshotHash",
    "rollbackTargetHash",
    "challengeHash",
    "preflightHash",
    "safetyZoneHash",
    "takeoverPathHash",
    "emergencyStopPathHash",
}
QUALIFICATION_BINDINGS = {
    "parameterCandidateHash",
    "scenarioContractHash",
    "vehicleDynamicsConfigHash",
    "sensorConfigHash",
    "payloadConfigHash",
    "holdoutContractHash",
}
HARDWARE_SAFETY_ACTIONS = {
    "hardware.arm",
    "hardware.flight",
    "hardware.hitl.execute",
    "hardware.parameter.write",
}
FORBIDDEN_FIELD_NAMES = {
    "password",
    "apiKey",
    "rawChat",
    "rawPrompt",
    "providerRequestId",
}


class EditionSafetyContractError(ValueError):
    """Raised when an E5 request or receipt must fail closed."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EditionSafetyContractError(f"unable to read JSON contract: {path}") from error
    if not isinstance(value, dict):
        raise EditionSafetyContractError(f"JSON contract is not an object: {path}")
    return value


def canonical_json(value: Any) -> bytes:
    """Return the repository's deterministic UTF-8 canonical envelope bytes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_canonical(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EditionSafetyContractError(f"{label} must be an object")
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing or extra:
        raise EditionSafetyContractError(
            f"{label} fields drifted; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return value


def _require_identifier(value: Any, label: str, *, dotted: bool = False) -> str:
    expression = DOTTED_IDENTIFIER_RE if dotted else IDENTIFIER_RE
    if not isinstance(value, str) or not expression.fullmatch(value):
        raise EditionSafetyContractError(f"{label} is invalid")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise EditionSafetyContractError(f"{label} must be a lowercase SHA-256")
    return value


def _timestamp(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise EditionSafetyContractError(f"{label} must be a UTC RFC3339 timestamp")
    return dt.datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _validate_window(
    issued: Any,
    expires: Any,
    label: str,
    *,
    maximum_seconds: int,
    now: dt.datetime | None = None,
) -> tuple[dt.datetime, dt.datetime]:
    issued_at = _timestamp(issued, f"{label}.issuedAt")
    expires_at = _timestamp(expires, f"{label}.expiresAt")
    seconds = (expires_at - issued_at).total_seconds()
    if seconds <= 0 or seconds > maximum_seconds:
        raise EditionSafetyContractError(f"{label} validity window exceeds its hard cap")
    if now is not None and (now < issued_at or now >= expires_at):
        raise EditionSafetyContractError(f"{label} is not currently valid")
    return issued_at, expires_at


def _validate_no_secret_fields(value: Any, label: str = "document") -> None:
    if isinstance(value, Mapping):
        forbidden = FORBIDDEN_FIELD_NAMES & value.keys()
        if forbidden:
            raise EditionSafetyContractError(
                f"{label} contains forbidden sensitive fields: {sorted(forbidden)}"
            )
        for key, item in value.items():
            _validate_no_secret_fields(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_secret_fields(item, f"{label}[{index}]")


def _validate_fake_issuer(
    issuer: str,
    test_only: bool,
    *,
    app_env: str,
    policy: Mapping[str, Any],
) -> None:
    prefix = policy["fakeIssuerPolicy"]["issuerPrefix"]
    is_fake = issuer.startswith(prefix)
    if is_fake and (not test_only or app_env != policy["fakeIssuerPolicy"]["allowedEnvironment"]):
        raise EditionSafetyContractError("fake issuer is forbidden outside APP_ENV=test")
    if test_only and not is_fake:
        raise EditionSafetyContractError("testOnly receipts require the registered fake issuer")


def validate_gate_policy(
    document: Any,
    *,
    capability_policy_sha256: str,
) -> dict[str, Any]:
    policy = _require_exact_keys(document, POLICY_KEYS, "execution gate policy")
    if (
        policy["schemaVersion"] != 1
        or policy["kind"] != "dronedream-edition-execution-gate-policy"
        or policy["policyId"] != "edition-execution-gate"
        or policy["policyVersion"] != "1.0.0"
    ):
        raise EditionSafetyContractError("execution gate policy identity is unsupported")
    if (
        policy["defaultDecision"] != "deny"
        or policy["frontendIsAuthority"] is not False
        or policy["hardwareActionHandlersImplemented"] is not False
    ):
        raise EditionSafetyContractError("E5 must remain deny-first and decision-only")
    capability = _require_exact_keys(
        policy["capabilityPolicy"],
        {"policyId", "policyVersion", "sha256"},
        "execution gate capabilityPolicy",
    )
    if capability != {
        "policyId": "core-capabilities",
        "policyVersion": "1.0.0",
        "sha256": capability_policy_sha256,
    }:
        raise EditionSafetyContractError("execution gate capability policy binding drifted")
    if policy["requiredDecisionLayers"] != ["native", "backend", "runtime"]:
        raise EditionSafetyContractError("three independent decision layers are required")
    if policy["contextBinding"]["canonicalization"] != "RFC8785-JCS":
        raise EditionSafetyContractError("authorization context canonicalization drifted")
    if policy["contextBinding"]["hashAlgorithm"] != "SHA-256":
        raise EditionSafetyContractError("authorization context hash algorithm drifted")
    if policy["contextBinding"]["unknownFieldsDecision"] != "deny":
        raise EditionSafetyContractError("unknown authorization fields must fail closed")
    receipt_policy = policy["receiptPolicy"]
    if (
        receipt_policy["appendOnlyAudit"] is not True
        or receipt_policy["oneTimeConsumption"] is not True
        or receipt_policy["attemptRecordedBeforeDecision"] is not True
        or receipt_policy["denyPrecedence"]
        != ["failed", "deny", "indeterminate", "missing", "allow"]
        or receipt_policy["maximumRequestTtlSeconds"] > 300
        or receipt_policy["maximumOperatorChallengeTtlSeconds"] > 120
    ):
        raise EditionSafetyContractError("receipt lifetime or precedence weakened")
    qualification = policy["qualificationPolicy"]
    if (
        qualification["optimizationCandidateReceiptIsHardwareAuthority"] is not False
        or qualification["requiresIndependentHoldout"] is not True
        or qualification["acceptedLevels"] != ["sim", "hitl"]
    ):
        raise EditionSafetyContractError("qualification cannot be promoted to hardware authority")
    evidence = policy["structuredEvidence"]
    if set(evidence["requiredReceiptTypes"]) != RECEIPT_TYPES:
        raise EditionSafetyContractError("structured safety receipt set is incomplete")
    if (
        evidence["operatorConfirmationMode"] != "short-lived-challenge"
        or evidence["booleanConfirmationForbidden"] is not True
        or evidence["allReceiptsBindAuthorizationRequest"] is not True
    ):
        raise EditionSafetyContractError("operator and evidence binding was weakened")
    boundaries = policy["editionBoundaries"]
    required_sim_denies = {
        "hardware.discover",
        "hardware.parameter.write",
        "hardware.arm",
        "hardware.flight",
        "hardware.hitl.execute",
    }
    required_field_denies = {
        "simulation.execute",
        "simulation.parameter.write",
        "simulation.vehicle.arm",
        "hardware.hitl.execute",
    }
    if not required_sim_denies <= set(boundaries["simDeniedActions"]):
        raise EditionSafetyContractError("Sim physical authority boundary is incomplete")
    if not required_field_denies <= set(boundaries["fieldDeniedActions"]):
        raise EditionSafetyContractError("Field simulation authority boundary is incomplete")
    if (
        boundaries["hardwareActionsRequireValidatedSignedPack"] is not True
        or boundaries["zeroValidatedPackDecision"] != "deny"
    ):
        raise EditionSafetyContractError("unvalidated Vehicle Packs must remain denied")
    quorum = policy["quorum"]
    if quorum != {
        "requiredLayers": ["native", "backend", "runtime"],
        "allLayersMustAllow": True,
        "canonicalContextHashMustMatch": True,
        "canonicalDecisionHashesRequired": True,
        "lateAllowCannotOverrideTerminalNonAllow": True,
        "frontendReceiptAccepted": False,
    }:
        raise EditionSafetyContractError("three-layer quorum policy drifted")
    if policy["fakeIssuerPolicy"] != {
        "allowedEnvironment": "test",
        "issuerPrefix": "test-fixture:",
        "productionDecision": "deny",
    }:
        raise EditionSafetyContractError("fake issuer policy drifted")
    _validate_no_secret_fields(policy)
    return policy


def authorization_context_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return only immutable fields that every layer must compare byte-for-byte."""

    return {
        "authorizationRequestId": request["authorizationRequestId"],
        "actor": request["actor"],
        "deviceHardwareIdentity": request["deviceHardwareIdentity"],
        "vehicle": request["vehicle"],
        "parameterCandidateHash": request["parameterCandidateHash"],
        "compositeInventoryHash": request["compositeInventoryHash"],
        "policy": request["policy"],
        "source": request["source"],
        "editionId": request["editionId"],
        "action": request["action"],
        "targetKind": request["targetKind"],
        "issuedAt": request["issuedAt"],
        "expiresAt": request["expiresAt"],
        "nonce": request["nonce"],
        "sequence": request["sequence"],
    }


def authorization_context_hash(request: Mapping[str, Any]) -> str:
    return sha256_canonical(authorization_context_payload(request))


def authorization_request_hash(request: Mapping[str, Any]) -> str:
    return sha256_canonical(request)


def _validate_bindings(receipt: Mapping[str, Any], label: str) -> dict[str, str]:
    raw = receipt["bindings"]
    if not isinstance(raw, list):
        raise EditionSafetyContractError(f"{label}.bindings must be a list")
    bindings: dict[str, str] = {}
    for index, item in enumerate(raw):
        binding = _require_exact_keys(item, BINDING_KEYS, f"{label}.bindings[{index}]")
        name = binding["name"]
        if name not in BINDING_NAMES or name in bindings:
            raise EditionSafetyContractError(f"{label} contains an invalid duplicate binding")
        bindings[name] = _require_sha256(binding["sha256"], f"{label}.{name}")
    return bindings


def validate_evidence_receipt(
    document: Any,
    *,
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    app_env: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    receipt = _require_exact_keys(document, EVIDENCE_KEYS, "evidence receipt")
    if (
        receipt["schemaVersion"] != 1
        or receipt["kind"] != "dronedream-structured-safety-evidence-receipt"
        or receipt["receiptType"] not in RECEIPT_TYPES
    ):
        raise EditionSafetyContractError("evidence receipt identity is unsupported")
    _require_identifier(receipt["receiptId"], "evidence receipt id")
    if receipt["authorizationRequestId"] != request["authorizationRequestId"]:
        raise EditionSafetyContractError("evidence receipt crossed authorization requests")
    if receipt["contextHash"] != authorization_context_hash(request):
        raise EditionSafetyContractError("evidence receipt context hash drifted")
    issuer = _require_identifier(receipt["issuer"], "evidence receipt issuer")
    _validate_fake_issuer(issuer, bool(request["testOnly"]), app_env=app_env, policy=policy)
    if receipt["issuerLayer"] not in {"native", "backend", "runtime", "operator"}:
        raise EditionSafetyContractError("evidence receipt issuer layer is unsupported")
    if receipt["status"] != "pass":
        raise EditionSafetyContractError("non-passing safety evidence cannot authorize")
    maximum_seconds = policy["receiptPolicy"]["maximumRequestTtlSeconds"]
    if receipt["receiptType"] == "operator-confirmation":
        maximum_seconds = policy["receiptPolicy"]["maximumOperatorChallengeTtlSeconds"]
    issued_at, expires_at = _validate_window(
        receipt["issuedAt"],
        receipt["expiresAt"],
        "evidence receipt",
        maximum_seconds=maximum_seconds,
        now=now,
    )
    request_issued = _timestamp(request["issuedAt"], "request.issuedAt")
    request_expires = _timestamp(request["expiresAt"], "request.expiresAt")
    if issued_at < request_issued or expires_at > request_expires:
        raise EditionSafetyContractError("evidence receipt escaped the request validity window")
    _require_identifier(receipt["nonce"], "evidence receipt nonce")
    if not isinstance(receipt["sequence"], int) or receipt["sequence"] < 1:
        raise EditionSafetyContractError("evidence receipt sequence is invalid")
    _require_sha256(receipt["evidenceHash"], "evidence receipt evidenceHash")
    if receipt["qualificationLevel"] not in {"none", "sim", "hitl"}:
        raise EditionSafetyContractError("evidence receipt qualification level is invalid")
    bindings = _validate_bindings(receipt, "evidence receipt")
    if receipt["oneTime"] is not True or receipt["consumptionState"] != "unconsumed":
        raise EditionSafetyContractError("safety evidence must be one-time and unconsumed")
    if receipt["receiptType"] == "trusted-qualification":
        if receipt["qualificationLevel"] not in {"sim", "hitl"}:
            raise EditionSafetyContractError("trusted qualification level is unsupported")
        if not bindings.keys() >= QUALIFICATION_BINDINGS:
            raise EditionSafetyContractError("trusted qualification bindings are incomplete")
        expected = {
            "parameterCandidateHash": request["parameterCandidateHash"],
            "vehicleDynamicsConfigHash": request["vehicle"]["dynamicsConfigHash"],
            "sensorConfigHash": request["vehicle"]["sensorConfigHash"],
            "payloadConfigHash": request["vehicle"]["payloadConfigHash"],
        }
        if any(bindings[name] != value for name, value in expected.items()):
            raise EditionSafetyContractError("trusted qualification crossed candidate or vehicle")
    elif receipt["qualificationLevel"] != "none":
        raise EditionSafetyContractError("non-qualification evidence cannot claim a level")
    required_binding_by_type = {
        "parameter-snapshot": "snapshotHash",
        "transaction-rollback": "rollbackTargetHash",
        "operator-confirmation": "challengeHash",
        "preflight": "preflightHash",
        "safety-zone": "safetyZoneHash",
        "control-takeover": "takeoverPathHash",
        "emergency-stop": "emergencyStopPathHash",
    }
    binding_name = required_binding_by_type.get(receipt["receiptType"])
    if binding_name and binding_name not in bindings:
        raise EditionSafetyContractError(
            f"{receipt['receiptType']} receipt lacks {binding_name}"
        )
    _validate_no_secret_fields(receipt, "evidence receipt")
    return receipt


def validate_authorization_request(
    document: Any,
    *,
    policy: Mapping[str, Any],
    execution_gate_policy_sha256: str,
    capability_policy_sha256: str,
    app_env: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    request = _require_exact_keys(document, REQUEST_KEYS, "authorization request")
    if (
        request["schemaVersion"] != 1
        or request["kind"] != "dronedream-edition-authorization-request"
    ):
        raise EditionSafetyContractError("authorization request identity is unsupported")
    _validate_no_secret_fields(request, "authorization request")
    _require_identifier(request["authorizationRequestId"], "authorizationRequestId")
    actor = _require_exact_keys(request["actor"], ACTOR_KEYS, "request.actor")
    _require_identifier(actor["accountId"], "request.actor.accountId")
    _require_identifier(actor["actorId"], "request.actor.actorId")
    device = _require_exact_keys(
        request["deviceHardwareIdentity"], DEVICE_KEYS, "request.deviceHardwareIdentity"
    )
    _require_identifier(device["deviceId"], "request.deviceHardwareIdentity.deviceId")
    _require_sha256(
        device["hardwareIdentityHash"],
        "request.deviceHardwareIdentity.hardwareIdentityHash",
    )
    vehicle = _require_exact_keys(request["vehicle"], VEHICLE_KEYS, "request.vehicle")
    for key in ("vehicleId", "packId", "controllerId", "firmwareVersion"):
        _require_identifier(vehicle[key], f"request.vehicle.{key}")
    if vehicle["firmwareFamily"] not in {"px4", "ardupilot", "crazyflie"}:
        raise EditionSafetyContractError("request.vehicle.firmwareFamily is unsupported")
    for key in (
        "packManifestSha256",
        "firmwareIdentityHash",
        "dynamicsConfigHash",
        "sensorConfigHash",
        "payloadConfigHash",
    ):
        _require_sha256(vehicle[key], f"request.vehicle.{key}")
    _require_sha256(request["parameterCandidateHash"], "request.parameterCandidateHash")
    _require_sha256(request["compositeInventoryHash"], "request.compositeInventoryHash")
    policy_binding = _require_exact_keys(
        request["policy"], POLICY_BINDING_KEYS, "request.policy"
    )
    expected_policy = {
        "capabilityPolicyId": "core-capabilities",
        "capabilityPolicyVersion": "1.0.0",
        "capabilityPolicySha256": capability_policy_sha256,
        "executionGatePolicyId": "edition-execution-gate",
        "executionGatePolicyVersion": "1.0.0",
        "executionGatePolicySha256": execution_gate_policy_sha256,
    }
    if any(policy_binding[key] != value for key, value in expected_policy.items()):
        raise EditionSafetyContractError("authorization policy binding drifted")
    _require_sha256(policy_binding["editionManifestSha256"], "request edition manifest hash")
    source = _require_exact_keys(request["source"], SOURCE_KEYS, "request.source")
    if not isinstance(source["repositoryCommit"], str) or not COMMIT_RE.fullmatch(
        source["repositoryCommit"]
    ):
        raise EditionSafetyContractError("request source commit is invalid")
    _require_sha256(source["enginePackManifestSha256"], "request Engine Pack hash")
    _require_sha256(source["runtimeBaseManifestSha256"], "request Runtime Base hash")
    if request["editionId"] not in {"sim", "lab", "field"}:
        raise EditionSafetyContractError("request edition is unsupported")
    _require_identifier(request["action"], "request action", dotted=True)
    if request["targetKind"] not in {"installation", "simulation", "hitl", "real-hardware"}:
        raise EditionSafetyContractError("request target kind is unsupported")
    _validate_window(
        request["issuedAt"],
        request["expiresAt"],
        "authorization request",
        maximum_seconds=policy["receiptPolicy"]["maximumRequestTtlSeconds"],
        now=now,
    )
    _require_identifier(request["nonce"], "request nonce")
    if not isinstance(request["sequence"], int) or request["sequence"] < 1:
        raise EditionSafetyContractError("request sequence is invalid")
    issuer = _require_identifier(request["issuer"], "request issuer")
    if not isinstance(request["testOnly"], bool):
        raise EditionSafetyContractError("request testOnly must be boolean")
    resolved_env = app_env if app_env is not None else os.environ.get("APP_ENV", "production")
    _validate_fake_issuer(
        issuer,
        request["testOnly"],
        app_env=resolved_env,
        policy=policy,
    )
    if not isinstance(request["evidenceReceipts"], list):
        raise EditionSafetyContractError("request evidenceReceipts must be a list")
    receipt_ids: set[str] = set()
    receipt_types: set[str] = set()
    receipt_nonces: set[str] = set()
    for receipt in request["evidenceReceipts"]:
        validated = validate_evidence_receipt(
            receipt,
            request=request,
            policy=policy,
            app_env=resolved_env,
            now=now,
        )
        if validated["receiptId"] in receipt_ids or validated["receiptType"] in receipt_types:
            raise EditionSafetyContractError("safety evidence cannot be duplicated or substituted")
        if validated["nonce"] in receipt_nonces:
            raise EditionSafetyContractError("safety evidence nonce replayed within the request")
        receipt_ids.add(validated["receiptId"])
        receipt_types.add(validated["receiptType"])
        receipt_nonces.add(validated["nonce"])
    if request["action"] in HARDWARE_SAFETY_ACTIONS:
        required = set(policy["structuredEvidence"]["requiredReceiptTypes"])
        if receipt_types != required:
            raise EditionSafetyContractError("hardware safety evidence set is incomplete")
    return request


def validate_layer_decision_receipt(
    document: Any,
    *,
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
    app_env: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    receipt = _require_exact_keys(document, LAYER_DECISION_KEYS, "layer decision receipt")
    if (
        receipt["schemaVersion"] != 1
        or receipt["kind"] != "dronedream-edition-layer-decision-receipt"
        or receipt["layer"] not in {"native", "backend", "runtime"}
        or receipt["decision"] not in {"allow", "deny", "failed", "indeterminate"}
    ):
        raise EditionSafetyContractError("layer decision receipt identity is unsupported")
    if receipt["authorizationRequestId"] != request["authorizationRequestId"]:
        raise EditionSafetyContractError("layer decision crossed authorization requests")
    if receipt["authorizationRequestHash"] != authorization_request_hash(request):
        raise EditionSafetyContractError("layer decision request hash drifted")
    if receipt["contextHash"] != authorization_context_hash(request):
        raise EditionSafetyContractError("layer decision context hash drifted")
    if not isinstance(receipt["reasonCodes"], list) or not receipt["reasonCodes"]:
        raise EditionSafetyContractError("layer decision must record reason codes")
    if len(set(receipt["reasonCodes"])) != len(receipt["reasonCodes"]):
        raise EditionSafetyContractError("layer decision reason codes are duplicated")
    for reason in receipt["reasonCodes"]:
        _require_identifier(reason, "layer decision reason code", dotted=True)
    unhashed = dict(receipt)
    unhashed.pop("canonicalDecisionHash")
    if receipt["canonicalDecisionHash"] != sha256_canonical(unhashed):
        raise EditionSafetyContractError("canonical layer decision hash drifted")
    _validate_window(
        receipt["issuedAt"],
        receipt["expiresAt"],
        "layer decision receipt",
        maximum_seconds=policy["receiptPolicy"]["maximumRequestTtlSeconds"],
        now=now,
    )
    if receipt["issuedAt"] < request["issuedAt"] or receipt["expiresAt"] > request["expiresAt"]:
        raise EditionSafetyContractError("layer decision escaped the request validity window")
    _require_identifier(receipt["nonce"], "layer decision nonce")
    if not isinstance(receipt["sequence"], int) or receipt["sequence"] < 1:
        raise EditionSafetyContractError("layer decision sequence is invalid")
    issuer = _require_identifier(receipt["issuer"], "layer decision issuer")
    _validate_fake_issuer(
        issuer,
        bool(receipt["testOnly"]),
        app_env=app_env,
        policy=policy,
    )
    if receipt["testOnly"] != request["testOnly"]:
        raise EditionSafetyContractError("layer decision changed the test-only boundary")
    if receipt["consumptionState"] != "unconsumed":
        raise EditionSafetyContractError("layer decision is already consumed or revoked")
    _validate_no_secret_fields(receipt, "layer decision receipt")
    return receipt


def _quorum_outcome(receipts: Iterable[Mapping[str, Any]]) -> tuple[str, list[str]]:
    values = list(receipts)
    layers = {receipt["layer"] for receipt in values}
    if layers != {"native", "backend", "runtime"}:
        return "missing", ["quorum.layer.missing"]
    precedence = ("failed", "deny", "indeterminate")
    for decision in precedence:
        matching = [receipt for receipt in values if receipt["decision"] == decision]
        if matching:
            reasons = sorted({reason for receipt in matching for reason in receipt["reasonCodes"]})
            return decision, reasons
    if all(receipt["decision"] == "allow" for receipt in values):
        return "allow", ["quorum.all-layers-allow"]
    return "deny", ["quorum.invalid-decision-set"]


def validate_quorum_receipt(
    document: Any,
    *,
    request: Mapping[str, Any],
    layer_receipts: Iterable[Mapping[str, Any]],
    policy: Mapping[str, Any],
    app_env: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    quorum = _require_exact_keys(document, QUORUM_KEYS, "quorum receipt")
    if quorum["schemaVersion"] != 1 or quorum["kind"] != (
        "dronedream-edition-authorization-quorum-receipt"
    ):
        raise EditionSafetyContractError("quorum receipt identity is unsupported")
    receipts = [
        validate_layer_decision_receipt(
            receipt,
            request=request,
            policy=policy,
            app_env=app_env,
            now=now,
        )
        for receipt in layer_receipts
    ]
    if len(receipts) != 3 or len({receipt["layer"] for receipt in receipts}) != 3:
        raise EditionSafetyContractError("quorum requires one receipt from every layer")
    if len({receipt["contextHash"] for receipt in receipts}) != 1:
        raise EditionSafetyContractError("layer decisions do not share one canonical context")
    if quorum["authorizationRequestId"] != request["authorizationRequestId"]:
        raise EditionSafetyContractError("quorum crossed authorization requests")
    if quorum["authorizationRequestHash"] != authorization_request_hash(request):
        raise EditionSafetyContractError("quorum request hash drifted")
    if quorum["contextHash"] != authorization_context_hash(request):
        raise EditionSafetyContractError("quorum context hash drifted")
    hashes = _require_exact_keys(
        quorum["layerDecisionHashes"],
        {"native", "backend", "runtime"},
        "quorum layerDecisionHashes",
    )
    expected_hashes = {receipt["layer"]: receipt["canonicalDecisionHash"] for receipt in receipts}
    if hashes != expected_hashes:
        raise EditionSafetyContractError("quorum assembled mismatched or stale decisions")
    expected_decision, expected_reasons = _quorum_outcome(receipts)
    if quorum["decision"] != expected_decision or quorum["reasonCodes"] != expected_reasons:
        raise EditionSafetyContractError("quorum precedence or reason codes drifted")
    _validate_window(
        quorum["issuedAt"],
        quorum["expiresAt"],
        "quorum receipt",
        maximum_seconds=policy["receiptPolicy"]["maximumRequestTtlSeconds"],
        now=now,
    )
    if quorum["issuedAt"] < request["issuedAt"] or quorum["expiresAt"] > request["expiresAt"]:
        raise EditionSafetyContractError("quorum escaped the request validity window")
    _require_identifier(quorum["nonce"], "quorum nonce")
    if not isinstance(quorum["sequence"], int) or quorum["sequence"] < 1:
        raise EditionSafetyContractError("quorum sequence is invalid")
    if (
        quorum["oneTime"] is not True
        or quorum["consumptionState"] != "unconsumed"
        or quorum["appendOnlyAudit"] is not True
    ):
        raise EditionSafetyContractError("quorum must be append-only and one-time")
    _validate_no_secret_fields(quorum, "quorum receipt")
    return quorum


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability-policy", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--app-env", default=os.environ.get("APP_ENV", "production"))
    args = parser.parse_args()
    capability_sha256 = sha256_file(args.capability_policy)
    gate_policy = validate_gate_policy(
        load_json(args.gate_policy),
        capability_policy_sha256=capability_sha256,
    )
    if args.request is not None:
        validate_authorization_request(
            load_json(args.request),
            policy=gate_policy,
            execution_gate_policy_sha256=sha256_file(args.gate_policy),
            capability_policy_sha256=capability_sha256,
            app_env=args.app_env,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
