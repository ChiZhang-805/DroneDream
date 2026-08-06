from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_coexistence_contract as coexistence  # noqa: E402


def load_inputs() -> tuple[dict[str, object], ...]:
    return (
        coexistence._load_json(coexistence.CONTRACT_PATH),
        coexistence._load_json(coexistence.DONOR_PATH),
        coexistence._load_json(coexistence.OVERLAY_PATH),
        coexistence._load_json(coexistence.PROFILE_PATH),
        coexistence.BUILD_SCRIPT_PATH.read_text(encoding="utf-8"),
        coexistence._load_json(coexistence.BUILD_RECEIPT_PATH),
        coexistence._load_json(coexistence.HANDOFF_PATH),
    )


class LabCoexistenceContractTests(unittest.TestCase):
    def test_real_contract_is_green_valid_but_not_release_ready(self) -> None:
        result = coexistence.verify_lab_coexistence_contract()
        self.assertTrue(result["contractReady"])
        self.assertFalse(result["releaseReady"])
        self.assertEqual(result["labIdentity"]["productName"], "DroneDream · LAB")
        self.assertEqual(result["universalDonorRequestCount"], 2)

    def test_rejects_product_and_app_identity_collision(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["identities"][2]["identifier"] = "io.dronedream.desktop"
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "identifier"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["identities"][2]["productName"] = "DroneDream · FIELD"
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "productName"):
            coexistence.validate_contract(*inputs)

    def test_rejects_cross_edition_updater_channel(self) -> None:
        inputs = list(load_inputs())
        overlay = copy.deepcopy(inputs[2])
        overlay["plugins"]["updater"]["endpoints"] = [
            "https://github.com/ChiZhang-805/DroneDream/releases/latest/download/latest.json"
        ]
        inputs[2] = overlay
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "updater"):
            coexistence.validate_contract(*inputs)

    def test_rejects_silent_cross_edition_auth_or_frontend_identity(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        requirements = contract["authentication"]["requirements"]
        requirements["browserSessionMaySilentlyAuthenticateLabWithoutGesture"] = True
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "authentication"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["authentication"]["requirements"]["frontendMayAssertEditionIdentity"] = True
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "authentication"):
            coexistence.validate_contract(*inputs)

    def test_rejects_missing_pkce_and_edition_vault_requirements(self) -> None:
        for key in ("pkceVerifierMustBePerAttempt", "credentialVaultMustBeEditionScoped"):
            inputs = list(load_inputs())
            contract = copy.deepcopy(inputs[0])
            contract["authentication"]["requirements"][key] = False
            inputs[0] = contract
            with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "authentication"):
                coexistence.validate_contract(*inputs)

    def test_rejects_brand_byte_token_or_separator_drift(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["brandContinuity"]["separatorCodePoint"] = "U+8DEF"
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "brand"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["brandContinuity"]["tokens"]["gradient"][0] = "#00D9FF"
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "green tokens"):
            coexistence.validate_contract(*inputs)

    def test_rejects_frozen_artifact_relabel_or_release_claim(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["frozenArtifact"]["sha256"] = "0" * 64
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "relabeled"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["releaseReady"] = True
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "readiness"):
            coexistence.validate_contract(*inputs)

    def test_donor_requests_stay_in_universal_and_authorize_no_rebuild(self) -> None:
        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        donor["requests"][0]["candidatePaths"].append(
            "distribution/editions/lab/private-nsis-fork.nsh"
        )
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "Lab ownership"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        donor["labRecovery"]["rebuildAuthorizedByThisRequest"] = True
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "authorizes"):
            coexistence.validate_contract(*inputs)

    def test_contract_files_are_utf8_json_with_u00b7_name(self) -> None:
        raw = coexistence.CONTRACT_PATH.read_bytes()
        self.assertNotIn(b"\xef\xbb\xbf", raw[:3])
        parsed = json.loads(raw.decode("utf-8"))
        self.assertEqual(parsed["brandContinuity"]["displayName"], "DroneDream · LAB")


if __name__ == "__main__":
    unittest.main()
