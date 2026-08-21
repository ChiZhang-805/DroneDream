from __future__ import annotations

import datetime as dt
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.distribution_safety import (
    BackendDistributionSafetyError,
    BackendTrustedContext,
    evaluate_backend_authorization,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "distribution/tests/fixtures/edition-safety-cases.v1.json").read_text(
        encoding="utf-8"
    )
)


def request_fixture() -> dict[str, object]:
    return deepcopy(FIXTURE["baseRequest"])


def trusted_context(request: dict[str, object]) -> BackendTrustedContext:
    actor = request["actor"]
    device = request["deviceHardwareIdentity"]
    vehicle = request["vehicle"]
    policy = request["policy"]
    source = request["source"]
    receipts = request["evidenceReceipts"]
    assert isinstance(actor, dict)
    assert isinstance(device, dict)
    assert isinstance(vehicle, dict)
    assert isinstance(policy, dict)
    assert isinstance(source, dict)
    assert isinstance(receipts, list)
    return BackendTrustedContext(
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
            str(receipt["receiptType"]): str(receipt["evidenceHash"])
            for receipt in receipts
        },
        observed_at=dt.datetime(2026, 8, 5, 0, 1, 0, tzinfo=dt.UTC),
        app_env="test",
    )


def allow_override(context: BackendTrustedContext) -> BackendTrustedContext:
    return replace(
        context,
        test_catalog_override=True,
        pack_validation_status_override="validated",
        pack_validation_tier_override="hardware-validated",
        pack_signature_state_override="verified",
        controller_status_override="validated",
    )


def test_current_catalog_fails_closed_with_zero_validated_packs() -> None:
    request = request_fixture()
    result = evaluate_backend_authorization(request, trusted_context(request))
    assert result.decision == "deny"
    assert {
        "backend.pack.unvalidated",
        "backend.pack.signature-unverified",
        "backend.controller.unvalidated",
    } <= set(result.reason_codes)
    assert result.receipt["layer"] == "backend"


def test_test_only_validated_fixture_can_reach_backend_allow() -> None:
    request = request_fixture()
    result = evaluate_backend_authorization(request, allow_override(trusted_context(request)))
    assert result.decision == "allow"
    assert result.reason_codes == ("backend.contract.allow",)
    assert result.receipt["testOnly"] is True


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"actor_id": "actor:other"}, "backend.actor.identity-mismatch"),
        ({"registered_device_id": "device:other"}, "backend.device.id-mismatch"),
        (
            {"registered_device_hardware_identity_hash": "0" * 64},
            "backend.device.identity-mismatch",
        ),
        ({"parameter_candidate_hash": "0" * 64}, "backend.parameter-candidate.mismatch"),
        ({"minimum_sequence": 2}, "backend.sequence.stale"),
    ],
)
def test_server_derived_context_cannot_be_replaced_by_frontend_values(
    change: dict[str, object], reason: str
) -> None:
    request = request_fixture()
    context = replace(allow_override(trusted_context(request)), **change)
    result = evaluate_backend_authorization(request, context)
    assert result.decision == "deny"
    assert reason in result.reason_codes


def test_replay_and_trusted_evidence_disagreement_are_denied() -> None:
    request = request_fixture()
    context = allow_override(trusted_context(request))
    replayed = replace(
        context,
        consumed_authorization_ids=frozenset({str(request["authorizationRequestId"])}),
        consumed_nonces=frozenset({str(request["nonce"])}),
    )
    result = evaluate_backend_authorization(request, replayed)
    assert result.decision == "deny"
    assert {"backend.request.replayed", "backend.nonce.replayed"} <= set(
        result.reason_codes
    )

    untrusted = replace(context, trusted_evidence_hashes={})
    result = evaluate_backend_authorization(request, untrusted)
    assert result.decision == "deny"
    assert "backend.evidence.server-state-mismatch" in result.reason_codes


def test_unknown_schema_expiry_and_fake_production_issuer_fail_closed() -> None:
    request = request_fixture()
    context = allow_override(trusted_context(request))

    unknown = deepcopy(request)
    unknown["unexpected"] = True
    with pytest.raises(BackendDistributionSafetyError, match="failed closed"):
        evaluate_backend_authorization(unknown, context)

    malformed = deepcopy(request)
    malformed["vehicle"] = []
    with pytest.raises(BackendDistributionSafetyError, match="failed closed"):
        evaluate_backend_authorization(malformed, context)

    expired_context = replace(
        context, observed_at=dt.datetime(2026, 8, 5, 0, 5, 0, tzinfo=dt.UTC)
    )
    with pytest.raises(BackendDistributionSafetyError, match="failed closed"):
        evaluate_backend_authorization(request, expired_context)

    production_context = replace(context, app_env="production")
    with pytest.raises(BackendDistributionSafetyError, match="failed closed"):
        evaluate_backend_authorization(request, production_context)

    future_context = replace(
        context, observed_at=dt.datetime(2026, 8, 4, 23, 59, 59, tzinfo=dt.UTC)
    )
    with pytest.raises(BackendDistributionSafetyError, match="failed closed"):
        evaluate_backend_authorization(request, future_context)


def test_backend_module_exposes_no_action_or_device_handler() -> None:
    import app.distribution_safety as module

    exported = set(module.__all__)
    assert not any(
        token in name.lower()
        for name in exported
        for token in ("route", "write", "arm", "flight", "install", "device_handler")
    )
