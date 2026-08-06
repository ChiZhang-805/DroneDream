from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_safety_oauth_readiness as readiness  # noqa: E402


def inputs() -> dict[str, object]:
    return readiness._load_json(readiness.CONTRACT_PATH)


def test_real_source_readiness_is_offline_valid_and_ready() -> None:
    result = readiness.verify_lab_safety_oauth_readiness()
    assert result["sourceReady"] is True
    assert result["releaseReady"] is False
    assert result["fixture"]["canonicalParameterizationDelivered"] is True
    assert result["fixture"]["reboundContextHashWouldChange"] is True
    assert result["oauth"]["offlineContractValid"] is True
    assert result["oauth"]["registrationReceiptVerified"] is True
    assert result["oauth"]["providerExecutionEvidenceCollected"] is False
    assert result["oauth"]["actualEnvironmentRead"] is False
    assert result["blockers"] == []
    assert all(
        item["valueRecordedByThisContract"] is False
        for item in result["yellowBuildInputs"]["publicInputs"]
    )


def test_rejects_fixture_match_or_canonical_donor_downgrade() -> None:
    contract = copy.deepcopy(inputs())
    contract["editionSafetyFixture"]["rawBaseManifestMatchesActiveLabManifest"] = True
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="fixture readiness"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    contract["editionSafetyFixture"]["parameterizationDonor"]["state"] = (
        "requested-not-delivered"
    )
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="fixture readiness"):
        readiness.validate_contract(contract)


def test_rejects_cross_edition_oauth_or_provider_evidence_claim() -> None:
    contract = copy.deepcopy(inputs())
    contract["oauthSourceContract"]["authClientId"] = "dronedream-desktop-field"
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="OAuth source"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    contract["oauthSourceContract"]["registrationReceipt"]["clientIdSha256"] = "0" * 64
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="OAuth source"):
        readiness.validate_contract(contract)


def test_rejects_nsis_duplicate_label_donor_downgrade() -> None:
    contract = copy.deepcopy(inputs())
    contract["nsisDuplicateLabelDonor"]["state"] = "requested-not-delivered"
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="NSIS duplicate-label"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    contract["oauthSourceContract"]["providerExecutionEvidenceCollected"] = True
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="OAuth source"):
        readiness.validate_contract(contract)


def test_rejects_private_key_or_unregistered_oauth_input_policy() -> None:
    contract = copy.deepcopy(inputs())
    publishable = next(
        item
        for item in contract["nextYellowBuildInputs"]["publicInputs"]
        if item["name"] == "VITE_SUPABASE_PUBLISHABLE_KEY"
    )
    publishable["serviceRoleForbidden"] = False
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="OAuth input"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    oauth_client = next(
        item
        for item in contract["nextYellowBuildInputs"]["publicInputs"]
        if item["name"] == "DRONEDREAM_OAUTH_CLIENT_ID"
    )
    oauth_client["registeredLabCallbackRequired"] = False
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="OAuth input"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    contract["nextYellowBuildInputs"]["approvedUpdaterSigner"][
        "productionNamingKeyMayBeUsed"
    ] = True
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="updater signer"):
        readiness.validate_contract(contract)


def test_rejects_yellow_build_resource_or_toolchain_drift() -> None:
    contract = copy.deepcopy(inputs())
    contract["nextYellowBuildInputs"]["fixedInputs"]["CARGO_BUILD_JOBS"] = "4"
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="fixed YELLOW input"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    contract["nextYellowBuildInputs"]["fixedInputs"]["toolchain"] = "stable-msvc"
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="fixed YELLOW input"):
        readiness.validate_contract(contract)


def test_rejects_signature_or_lifecycle_gate_downgrade() -> None:
    contract = copy.deepcopy(inputs())
    contract["signatureGates"]["release"]["updaterSignatureRequired"] = False
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="signature gate"):
        readiness.validate_contract(contract)

    contract = copy.deepcopy(inputs())
    contract["installLifecycleGates"].remove("uninstall-preserves-runtime-and-other-editions")
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="lifecycle"):
        readiness.validate_contract(contract)


def test_rejects_zero_pack_hardware_authority_drift() -> None:
    contract = copy.deepcopy(inputs())
    contract["safety"]["frontendOrWorkspaceCountsAsAuthority"] = True
    with pytest.raises(readiness.LabSafetyOauthReadinessError, match="zero-pack"):
        readiness.validate_contract(contract)
