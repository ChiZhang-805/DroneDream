#!/usr/bin/env python3
"""Verify Lab safety-fixture, OAuth, and next-build source readiness offline."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import edition_safety_contract as safety_contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "distribution/editions/lab/safety-oauth-source-readiness.v1.json"
FIXTURE_PATH = ROOT / "distribution/tests/fixtures/edition-safety-cases.v1.json"
LAB_MANIFEST_PATH = ROOT / "distribution/editions/lab.v1.json"
AUTH_CONTRACT_PATH = ROOT / "distribution/desktop/edition-browser-auth.v1.json"
BUILD_SCRIPT_PATH = ROOT / "desktop/scripts/build-lab-preview.ps1"
AUTH_CONFIG_VERIFIER_PATH = ROOT / "desktop/scripts/verify-browser-auth-config.mjs"


class LabSafetyOauthReadinessError(ValueError):
    """Raised when Lab source readiness is missing or overstated."""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LabSafetyOauthReadinessError(f"{path} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LabSafetyOauthReadinessError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise LabSafetyOauthReadinessError(f"{label} must be an array")
    return value


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("kind") != "dronedream-lab-safety-oauth-source-readiness"
        or contract.get("editionId") != "lab"
        or contract.get("auditMode") != "green-offline-only"
        or contract.get("releaseReady") is not False
    ):
        raise LabSafetyOauthReadinessError("Lab source-readiness identity drifted")

    authority = _mapping(contract.get("universalAuthority"), "universalAuthority")
    if (
        authority.get("branch") != "codex/software"
        or authority.get("verificationSourceCommit") != "6f25bb5051794842a8dfc6d02d199c5f93afce7c"
        or authority.get("verificationSourceTree") != "d5d6acb39fec0af65bac4fbd4f964b6aeab73b3d"
        or authority.get("wholeCommitConsumptionAuthorized") is not False
    ):
        raise LabSafetyOauthReadinessError("Universal read-only authority drifted")

    fixture_contract = _mapping(
        contract.get("editionSafetyFixture"),
        "editionSafetyFixture",
    )
    fixture = _load_json(FIXTURE_PATH)
    request = _mapping(fixture.get("baseRequest"), "fixture baseRequest")
    policy = _mapping(request.get("policy"), "fixture policy")
    active_lab_sha = _sha256(LAB_MANIFEST_PATH)
    fixture_edition_sha = str(policy.get("editionManifestSha256"))
    if (
        fixture_contract.get("sourceCommit") != "b6b3659e112d9bf43b0b01c54dfc32755a12f90c"
        or fixture_contract.get("path")
        != "distribution/tests/fixtures/edition-safety-cases.v1.json"
        or fixture_contract.get("blob") != _git_blob(FIXTURE_PATH)
        or fixture_contract.get("sha256") != _sha256(FIXTURE_PATH)
        or fixture_contract.get("fixtureEditionId") != request.get("editionId")
        or fixture_contract.get("fixtureEditionManifestSha256") != fixture_edition_sha
        or _mapping(fixture_contract.get("activeLabManifest"), "activeLabManifest").get("sha256")
        != active_lab_sha
        or fixture_contract.get("activeManifestMatchesFixture")
        is not (active_lab_sha == fixture_edition_sha)
        or fixture_contract.get("parameterizedCanonicalDonorState") != "requested-not-delivered"
        or fixture_contract.get("inMemoryRewriteCountsAsCanonicalEvidence") is not False
        or fixture_contract.get("mismatchedManifestMustDeny") is not True
        or fixture_contract.get("productionPolicyMayBeRelaxed") is not False
    ):
        raise LabSafetyOauthReadinessError("edition-safety fixture readiness drifted")
    if active_lab_sha == fixture_edition_sha:
        raise LabSafetyOauthReadinessError(
            "fixture unexpectedly matches Lab without a canonical donor update"
        )

    original_context_hash = safety_contract.authorization_context_hash(request)
    receipts = _sequence(request.get("evidenceReceipts"), "fixture evidenceReceipts")
    if not receipts or any(
        not isinstance(receipt, dict) or receipt.get("contextHash") != original_context_hash
        for receipt in receipts
    ):
        raise LabSafetyOauthReadinessError("fixture context hashes are internally inconsistent")
    rebound_request = copy.deepcopy(request)
    _mapping(rebound_request.get("policy"), "rebound fixture policy")["editionManifestSha256"] = (
        active_lab_sha
    )
    rebound_context_hash = safety_contract.authorization_context_hash(rebound_request)
    if rebound_context_hash == original_context_hash:
        raise LabSafetyOauthReadinessError("edition fixture rebind did not change context hash")
    dependent_fields = fixture_contract.get("dependentFieldsThatMustBeRefreshed")
    if dependent_fields != ["evidenceReceipts[*].contextHash"]:
        raise LabSafetyOauthReadinessError("fixture dependent hash inventory drifted")

    oauth = _mapping(contract.get("oauthSourceContract"), "oauthSourceContract")
    auth_contract = _load_json(AUTH_CONTRACT_PATH)
    auth_editions = _sequence(auth_contract.get("editions"), "auth editions")
    lab_auth = [entry for entry in auth_editions if entry.get("editionId") == "lab"]
    protocol = _mapping(auth_contract.get("authorizationProtocol"), "authorizationProtocol")
    if len(lab_auth) != 1:
        raise LabSafetyOauthReadinessError("Lab OAuth identity is unavailable or ambiguous")
    lab_auth_entry = lab_auth[0]
    if (
        oauth.get("path") != "distribution/desktop/edition-browser-auth.v1.json"
        or oauth.get("blob") != _git_blob(AUTH_CONTRACT_PATH)
        or oauth.get("sha256") != _sha256(AUTH_CONTRACT_PATH)
        or oauth.get("editionId") != lab_auth_entry.get("editionId")
        or oauth.get("authClientId") != lab_auth_entry.get("authClientId")
        or oauth.get("bundleIdentifier") != lab_auth_entry.get("bundleIdentifier")
        or oauth.get("redirectUri") != lab_auth_entry.get("redirectUri")
        or oauth.get("credentialVaultNamespace") != lab_auth_entry.get("credentialVaultNamespace")
        or oauth.get("flow") != protocol.get("flow")
        or oauth.get("pkceMethod") != protocol.get("pkceMethod")
        or oauth.get("explicitUserGestureRequired") is not True
        or oauth.get("crossEditionSessionAdoptionAllowed") is not False
        or oauth.get("providerExecutionEvidenceCollected") is not False
    ):
        raise LabSafetyOauthReadinessError("Lab OAuth source contract drifted")

    inputs = _mapping(contract.get("nextYellowBuildInputs"), "nextYellowBuildInputs")
    public_inputs = _sequence(inputs.get("publicInputs"), "publicInputs")
    by_name = {entry.get("name"): entry for entry in public_inputs if isinstance(entry, dict)}
    if set(by_name) != {
        "VITE_SUPABASE_URL",
        "VITE_SUPABASE_PUBLISHABLE_KEY",
        "DRONEDREAM_OAUTH_CLIENT_ID",
    }:
        raise LabSafetyOauthReadinessError("public YELLOW input inventory drifted")
    if any(
        entry.get("approvedValueSourceRequired") is not True
        or entry.get("valueRecordedByThisContract") is not False
        for entry in by_name.values()
    ):
        raise LabSafetyOauthReadinessError("public YELLOW input policy drifted")
    if (
        by_name["VITE_SUPABASE_PUBLISHABLE_KEY"].get("serviceRoleForbidden") is not True
        or by_name["DRONEDREAM_OAUTH_CLIENT_ID"].get("registeredLabCallbackRequired") is not True
        or inputs.get("actualEnvironmentReadByGreenAudit") is not False
        or inputs.get("providerCalledByGreenAudit") is not False
    ):
        raise LabSafetyOauthReadinessError("OAuth input safety boundary drifted")
    fixed = _mapping(inputs.get("fixedInputs"), "fixedInputs")
    if (
        fixed.get("DRONEDREAM_DESKTOP_EDITION_ID") != "lab"
        or fixed.get("DRONEDREAM_EDITION_PROFILE") != "unified-sim-lab"
        or fixed.get("VITE_DRONEDREAM_EDITION") != "lab"
        or fixed.get("CARGO_BUILD_JOBS") != "2"
        or fixed.get("cargoTargetDir")
        != "C:\\Users\\zju20\\AppData\\Local\\DroneDream\\codex-cache\\lab-cargo-target"
        or fixed.get("toolchain") != "1.97.0-x86_64-pc-windows-gnullvm"
        or fixed.get("artifactFileName") != "DroneDream-Lab-1.0.0.exe"
        or fixed.get("sharedScriptJobsMaximum") != 4
    ):
        raise LabSafetyOauthReadinessError("fixed YELLOW input identity drifted")
    forbidden = set(_sequence(inputs.get("forbiddenInputs"), "forbiddenInputs"))
    if (
        not {
            "SUPABASE_SERVICE_ROLE_KEY",
            "OPENAI_API_KEY",
            "account-password",
            "TAURI_SIGNING_PRIVATE_KEY_PATH",
            "TAURI_SIGNING_PRIVATE_KEY_PASSWORD",
        }
        <= forbidden
    ):
        raise LabSafetyOauthReadinessError("forbidden build input inventory is incomplete")

    build_script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    auth_verifier = AUTH_CONFIG_VERIFIER_PATH.read_text(encoding="utf-8")
    for required in (
        'DRONEDREAM_DESKTOP_EDITION_ID = "lab"',
        'DRONEDREAM_EDITION_PROFILE = "unified-sim-lab"',
        'VITE_DRONEDREAM_EDITION = "lab"',
        "DRONEDREAM_OAUTH_CLIENT_ID",
    ):
        if required not in build_script:
            raise LabSafetyOauthReadinessError(f"Lab build input guard is missing: {required}")
    if "service_role" not in auth_verifier or "sb_secret_" not in auth_verifier:
        raise LabSafetyOauthReadinessError("desktop auth verifier does not reject private keys")

    signature_gates = _mapping(contract.get("signatureGates"), "signatureGates")
    preview_signature = _mapping(
        signature_gates.get("unsignedInternalPreview"),
        "unsignedInternalPreview",
    )
    release_signature = _mapping(signature_gates.get("release"), "release signatures")
    if (
        preview_signature.get("authenticodeState") != "NotSigned"
        or preview_signature.get("updaterSignatureState") != "not-issued"
        or preview_signature.get("allowedOnlyWithExactYellowAuthorization") is not True
        or preview_signature.get("releaseReady") is not False
        or release_signature.get("authenticodeRequired") is not True
        or release_signature.get("updaterSignatureRequired") is not True
        or release_signature.get("privateKeyMayBeReadByGreenAudit") is not False
        or release_signature.get("signatureUrlFamilyMustMatchLabArtifact") is not True
    ):
        raise LabSafetyOauthReadinessError("preview or release signature gate drifted")

    required_lifecycle_gates = {
        "fresh-install-owned-root",
        "same-version-overlay-update",
        "upgrade-source-and-build-number",
        "uninstall-preserves-runtime-and-other-editions",
        "desktop-and-start-menu-shortcuts",
        "webview2-health",
        "en-zh",
        "rollback-recorded-previous-version",
        "owned-residue-only",
        "website-exact-four-file-handoff",
    }
    lifecycle_gates = set(_sequence(contract.get("installLifecycleGates"), "installLifecycleGates"))
    if lifecycle_gates != required_lifecycle_gates:
        raise LabSafetyOauthReadinessError("install lifecycle gate inventory drifted")

    readiness = _mapping(contract.get("sourceReadiness"), "sourceReadiness")
    blockers = _sequence(readiness.get("blockers"), "sourceReadiness blockers")
    if (
        readiness.get("editionSafetyFixtureReady") is not False
        or readiness.get("oauthOfflineContractReady") is not True
        or readiness.get("installerSourceReady") is not True
        or readiness.get("yellowBuildSourceReady") is not False
        or len(blockers) != 3
    ):
        raise LabSafetyOauthReadinessError("YELLOW source readiness is overstated")

    safety = _mapping(contract.get("safety"), "safety")
    if (
        safety.get("validatedVehiclePackCount") != 0
        or safety.get("hardwareWriteArmHitlFlightDecision") != "deny"
        or safety.get("requiredAuthorityLayers") != ["native", "backend", "runtime"]
        or safety.get("frontendOrWorkspaceCountsAsAuthority") is not False
    ):
        raise LabSafetyOauthReadinessError("zero-pack safety boundary drifted")

    return {
        "sourceReady": False,
        "releaseReady": False,
        "fixture": {
            "activeLabManifestSha256": active_lab_sha,
            "fixtureEditionManifestSha256": fixture_edition_sha,
            "canonicalParameterizationDelivered": False,
            "reboundContextHashWouldChange": True,
        },
        "oauth": {
            "editionId": "lab",
            "offlineContractValid": True,
            "providerExecutionEvidenceCollected": False,
            "actualEnvironmentRead": False,
        },
        "yellowBuildInputs": inputs,
        "signatureGates": signature_gates,
        "installLifecycleGates": sorted(lifecycle_gates),
        "blockers": blockers,
    }


def verify_lab_safety_oauth_readiness() -> dict[str, Any]:
    return validate_contract(_load_json(CONTRACT_PATH))


if __name__ == "__main__":
    print(json.dumps(verify_lab_safety_oauth_readiness(), indent=2, sort_keys=True))
