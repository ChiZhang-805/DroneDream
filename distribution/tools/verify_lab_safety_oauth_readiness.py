#!/usr/bin/env python3
"""Verify Lab safety-fixture, OAuth, and next-build source readiness offline."""

from __future__ import annotations

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
OAUTH_RECEIPT_RELATIVE_PATH = (
    "distribution/build-receipts/"
    "lab-oauth-public-registration-1.0.0-fb3afee.controller-confirmed.json"
)
OAUTH_RECEIPT_PATH = ROOT / OAUTH_RECEIPT_RELATIVE_PATH
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
        or authority.get("verificationSourceCommit") != "57b74f59ed4164ebefde623fa7f5102e5c24363f"
        or authority.get("verificationSourceTree") != "5d9b060d14e758ba558bb7d4c7a1c04822bde28d"
        or authority.get("consumedExactPublicDonors")
        != [
            "a11fe7d09fceafaecf102a0cbfba49abb066a557",
            "8d60d3d15ca4d454acf5d92196deb63b0dd1314b",
            "57b74f59ed4164ebefde623fa7f5102e5c24363f",
        ]
        or authority.get("unrelatedCommitConsumptionAuthorized") is not False
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
    binding = _mapping(fixture_contract.get("parameterizationDonor"), "parameterizationDonor")
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
        or fixture_contract.get("rawBaseManifestMatchesActiveLabManifest")
        is not (active_lab_sha == fixture_edition_sha)
        or binding.get("commit") != "8d60d3d15ca4d454acf5d92196deb63b0dd1314b"
        or binding.get("parent") != "a11fe7d09fceafaecf102a0cbfba49abb066a557"
        or binding.get("integrationCommit") != "057fc89f460fedaafcef1fcb5bae141121b755ec"
        or binding.get("state") != "delivered-exact-donor-forward-synced"
        or binding.get("testOnly") is not True
        or fixture_contract.get("boundManifestMatchesActiveLabManifest") is not True
        or fixture_contract.get("canonicalTestBindingEvidenceReady") is not True
        or fixture_contract.get("mismatchedManifestMustDeny") is not True
        or fixture_contract.get("productionPolicyMayBeRelaxed") is not False
    ):
        raise LabSafetyOauthReadinessError("edition-safety fixture readiness drifted")
    if active_lab_sha == fixture_edition_sha:
        raise LabSafetyOauthReadinessError(
            "raw fixture unexpectedly matches Lab instead of using the test-only donor binding"
        )

    original_context_hash = safety_contract.authorization_context_hash(request)
    receipts = _sequence(request.get("evidenceReceipts"), "fixture evidenceReceipts")
    if not receipts or any(
        not isinstance(receipt, dict) or receipt.get("contextHash") != original_context_hash
        for receipt in receipts
    ):
        raise LabSafetyOauthReadinessError("fixture context hashes are internally inconsistent")
    bound_fixture = safety_contract.bind_test_fixture_to_edition_manifest(
        fixture,
        LAB_MANIFEST_PATH,
    )
    bound_request = _mapping(bound_fixture.get("baseRequest"), "bound fixture baseRequest")
    bound_policy = _mapping(bound_request.get("policy"), "bound fixture policy")
    bound_context_hash = safety_contract.authorization_context_hash(bound_request)
    bound_receipts = _sequence(bound_request.get("evidenceReceipts"), "bound evidenceReceipts")
    if (
        bound_request.get("editionId") != "lab"
        or bound_policy.get("editionManifestSha256") != active_lab_sha
        or not bound_receipts
        or any(
            not isinstance(receipt, dict) or receipt.get("contextHash") != bound_context_hash
            for receipt in bound_receipts
        )
    ):
        raise LabSafetyOauthReadinessError("canonical test-only fixture binding drifted")
    if bound_context_hash == original_context_hash:
        raise LabSafetyOauthReadinessError("edition fixture rebind did not change context hash")
    dependent_fields = fixture_contract.get("dependentFieldsThatMustBeRefreshed")
    if dependent_fields != ["evidenceReceipts[*].contextHash"]:
        raise LabSafetyOauthReadinessError("fixture dependent hash inventory drifted")

    nsis = _mapping(contract.get("nsisDuplicateLabelDonor"), "nsisDuplicateLabelDonor")
    if (
        nsis.get("commit") != "a11fe7d09fceafaecf102a0cbfba49abb066a557"
        or nsis.get("parent") != "6f25bb5051794842a8dfc6d02d199c5f93afce7c"
        or nsis.get("integrationCommit") != "575469366a6ba194397f14ccd42637801422d364"
        or nsis.get("state") != "delivered-exact-donor-forward-synced"
        or nsis.get("callSiteLabelPrefixRequired") is not True
        or nsis.get("nestedShortcutSuffixRequired") is not True
        or nsis.get("unknownProductMustFailClosed") is not True
        or nsis.get("repeatedExpansionCompileVerified") is not True
    ):
        raise LabSafetyOauthReadinessError("NSIS duplicate-label donor drifted")

    lifecycle = _mapping(
        contract.get("lifecycleRegistrationValidatorDonor"),
        "lifecycleRegistrationValidatorDonor",
    )
    if (
        lifecycle.get("commit") != "57b74f59ed4164ebefde623fa7f5102e5c24363f"
        or lifecycle.get("parent") != "8d60d3d15ca4d454acf5d92196deb63b0dd1314b"
        or lifecycle.get("integrationCommit") != "e9f6a4232d350d2dcc70deeffe62cef3dfad37bc"
        or lifecycle.get("state") != "delivered-public-donor-forward-synced"
        or lifecycle.get("productPayloadChanged") is not False
        or lifecycle.get("internalProductIdentityDistinctFromDisplayName") is not True
        or lifecycle.get("uninstallRegistrationFieldsVerified")
        != ["DisplayName", "DisplayVersion", "InstallLocation", "MainBinaryName"]
        or lifecycle.get("legacyDisplayShortcutCollisionProtected") is not True
        or lifecycle.get("unknownProductMustFailClosed") is not True
    ):
        raise LabSafetyOauthReadinessError(
            "lifecycle registration validator donor drifted"
        )

    oauth = _mapping(contract.get("oauthSourceContract"), "oauthSourceContract")
    auth_contract = _load_json(AUTH_CONTRACT_PATH)
    auth_editions = _sequence(auth_contract.get("editions"), "auth editions")
    lab_auth = [entry for entry in auth_editions if entry.get("editionId") == "lab"]
    protocol = _mapping(auth_contract.get("authorizationProtocol"), "authorizationProtocol")
    if len(lab_auth) != 1:
        raise LabSafetyOauthReadinessError("Lab OAuth identity is unavailable or ambiguous")
    lab_auth_entry = lab_auth[0]
    registration = _mapping(oauth.get("registrationReceipt"), "registrationReceipt")
    receipt = _load_json(OAUTH_RECEIPT_PATH)
    receipt_registration = _mapping(receipt.get("registration"), "OAuth receipt registration")
    callback_sha = hashlib.sha256(
        str(lab_auth_entry.get("redirectUri")).encode("utf-8")
    ).hexdigest()
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
        or registration.get("path")
        != OAUTH_RECEIPT_RELATIVE_PATH
        or registration.get("sha256") != _sha256(OAUTH_RECEIPT_PATH)
        or registration.get("clientIdSha256") != receipt_registration.get("clientIdSha256")
        or registration.get("callbackSha256") != callback_sha
        or registration.get("callbackSha256") != receipt_registration.get("callbackSha256")
        or registration.get("publicClient") is not True
        or registration.get("tokenEndpointAuthMethod") != "none"
        or registration.get("clientSecretPresent") is not False
        or registration.get("providerCalled") is not False
        or receipt_registration.get("clientIdValueRecorded") is not False
        or receipt_registration.get("providerCalled") is not False
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
        or by_name["DRONEDREAM_OAUTH_CLIENT_ID"].get("registrationReceiptVerified") is not True
        or by_name["DRONEDREAM_OAUTH_CLIENT_ID"].get("valueSha256")
        != registration.get("clientIdSha256")
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
            "production-naming-private-key",
        }
        <= forbidden
    ):
        raise LabSafetyOauthReadinessError("forbidden build input inventory is incomplete")
    signer = _mapping(inputs.get("approvedUpdaterSigner"), "approvedUpdaterSigner")
    if (
        signer.get("keyId") != "BA3FDCAF71CE2FF5"
        or signer.get("privateKeyPathRecordedByThisContract") is not False
        or signer.get("privateKeyValueRecordedByThisContract") is not False
        or signer.get("passwordMode") != "empty"
        or signer.get("greenAuditMayReadPrivateKey") is not False
        or signer.get("yellowBuildProcessMayReadApprovedExternalPath") is not True
        or signer.get("productionNamingKeyMayBeUsed") is not False
    ):
        raise LabSafetyOauthReadinessError("approved updater signer boundary drifted")

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
        or preview_signature.get("updaterSignatureState") != "required-for-yellow-attempt"
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
        readiness.get("editionSafetyFixtureReady") is not True
        or readiness.get("oauthOfflineContractReady") is not True
        or readiness.get("installerSourceReady") is not True
        or readiness.get("yellowBuildSourceReady") is not True
        or blockers
    ):
        raise LabSafetyOauthReadinessError("YELLOW source readiness drifted")

    safety = _mapping(contract.get("safety"), "safety")
    if (
        safety.get("validatedVehiclePackCount") != 0
        or safety.get("hardwareWriteArmHitlFlightDecision") != "deny"
        or safety.get("requiredAuthorityLayers") != ["native", "backend", "runtime"]
        or safety.get("frontendOrWorkspaceCountsAsAuthority") is not False
    ):
        raise LabSafetyOauthReadinessError("zero-pack safety boundary drifted")

    return {
        "sourceReady": True,
        "releaseReady": False,
        "fixture": {
            "activeLabManifestSha256": active_lab_sha,
            "fixtureEditionManifestSha256": fixture_edition_sha,
            "canonicalParameterizationDelivered": True,
            "reboundContextHashWouldChange": True,
        },
        "oauth": {
            "editionId": "lab",
            "offlineContractValid": True,
            "registrationReceiptVerified": True,
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
