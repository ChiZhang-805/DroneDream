from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_coexistence_contract as coexistence  # noqa: E402

SYNC_RECEIPT_PATH = (
    ROOT / "distribution/build-receipts" / "lab-universal-coexistence-sync-1.0.0-74418e1.green.json"
)


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
        self.assertEqual(
            result["labIdentity"]["installerProductName"],
            "DroneDream-Lab",
        )
        self.assertEqual(result["universalDonorRequestCount"], 8)
        contract = coexistence._load_json(coexistence.CONTRACT_PATH)
        self.assertEqual(
            contract["brandContinuity"]["dotLockupState"],
            "canonical-centered-separator-donor-consumed",
        )
        self.assertEqual(
            contract["brandContinuity"]["approvedEditionSuffixCapHeightRatio"],
            0.9,
        )
        self.assertTrue(contract["brandContinuity"]["preserveNaturalEditionLabelWidth"])
        self.assertFalse(
            contract["brandContinuity"]["canonicalDonor"][
                "supersededLargeLabelEvidence"
            ]["isCurrentProductSource"]
        )

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

        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["identities"][2]["installerProductName"] = "DroneDream-Field"
        inputs[0] = contract
        with self.assertRaisesRegex(
            coexistence.LabCoexistenceContractError,
            "installerProductName",
        ):
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

    def test_rejects_runtime_profile_or_compiled_edition_drift(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["runtimeUpdateIsolation"]["labRuntimeProfile"] = "sim-only"
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "Runtime/update"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        inputs[4] = inputs[4].replace(
            '$env:DRONEDREAM_DESKTOP_EDITION_ID = "lab"',
            '$env:DRONEDREAM_DESKTOP_EDITION_ID = "universal"',
        )
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "compiled Edition"):
            coexistence.validate_contract(*inputs)

    def test_rejects_auth_donor_or_canonical_single_path_drift(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["authentication"]["currentCommonCoreObservation"][
            "crossEditionSilentAdoptionDenied"
        ] = False
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "auth donor"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        auth_request = next(
            item
            for item in donor["requests"]
            if item["requestId"] == "universal-edition-auth-isolation-v1"
        )
        auth_request["canonicalSinglePathDonor"]["blob"] = "0" * 40
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "auth donor"):
            coexistence.validate_contract(*inputs)

    def test_rejects_runtime_mode_atomic_path_drift(self) -> None:
        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        nsis_request = next(
            item
            for item in donor["requests"]
            if item["requestId"] == "universal-nsis-existing-install-quiesce-v1"
        )
        nsis_request["exactDonor"]["pathByteAudit"][1]["sha256"] = "0" * 64
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "runtime-mode bytes"):
            coexistence.validate_contract(*inputs)

    def test_rejects_safety_fixture_donor_downgrade_or_result_drift(self) -> None:
        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        safety_request = next(
            item
            for item in donor["requests"]
            if item["requestId"] == "universal-edition-safety-fixture-binding-v1"
        )
        safety_request["state"] = "requested-not-delivered"
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "fixture donor"):
            coexistence.validate_contract(*inputs)

        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        safety_request = next(
            item
            for item in donor["requests"]
            if item["requestId"] == "universal-edition-safety-fixture-binding-v1"
        )
        safety_request["evidence"]["labSafetyAndCoexistenceTestResult"] = "60-passed"
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "fixture donor"):
            coexistence.validate_contract(*inputs)

    def test_rejects_nsis_duplicate_label_donor_downgrade(self) -> None:
        inputs = list(load_inputs())
        donor = copy.deepcopy(inputs[1])
        nsis_request = next(
            item
            for item in donor["requests"]
            if item["requestId"] == "universal-nsis-duplicate-label-v1"
        )
        nsis_request["state"] = "requested-not-delivered"
        inputs[1] = donor
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "duplicate-label"):
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

    def test_rejects_brand_evidence_head_as_product_source(self) -> None:
        inputs = list(load_inputs())
        contract = copy.deepcopy(inputs[0])
        contract["brandContinuity"]["canonicalDonor"]["productCommit"] = (
            "7482647f1c2fcb92f58aaef009efc99764792297"
        )
        inputs[0] = contract
        with self.assertRaisesRegex(coexistence.LabCoexistenceContractError, "brand donor"):
            coexistence.validate_contract(*inputs)

    def test_contract_files_are_utf8_json_with_u00b7_name(self) -> None:
        raw = coexistence.CONTRACT_PATH.read_bytes()
        self.assertNotIn(b"\xef\xbb\xbf", raw[:3])
        parsed = json.loads(raw.decode("utf-8"))
        self.assertEqual(parsed["brandContinuity"]["displayName"], "DroneDream · LAB")

    def test_sync_receipt_binds_exact_donors_without_claiming_lifecycle(self) -> None:
        receipt = coexistence._load_json(SYNC_RECEIPT_PATH)
        self.assertEqual(
            receipt["universalDonors"]["installerIdentityProduct"]["commit"],
            "8a8ad6ce0ea619a52ec087b7f55142c24311165a",
        )
        self.assertEqual(
            receipt["universalDonors"]["coexistenceContractPrerequisite"]["labIntegrationCommit"],
            "3c108a60fb00292cede529127cbb8890d687af2a",
        )
        self.assertEqual(
            receipt["universalDonors"]["installerIdentityProduct"]["labIntegrationCommit"],
            "28db5928371aa58eb918e1554a87c0ae4b14444c",
        )
        self.assertTrue(
            receipt["universalDonors"]["installerIdentityProduct"]["changedPathsExactAtSource"]
        )
        self.assertEqual(receipt["labIdentity"]["installerProductName"], "DroneDream-Lab")
        self.assertEqual(receipt["labIdentity"]["displayName"], "DroneDream · LAB")
        coexistence_source = receipt["source"]["commit"]
        for key in ("manifest", "schema", "validator", "tests"):
            reference = receipt["commonCoexistenceContract"][key]
            payload = subprocess.check_output(
                ["git", "show", f"{coexistence_source}:{reference['path']}"],
                cwd=ROOT,
            )
            self.assertEqual(len(payload), reference["bytes"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), reference["sha256"])
        self.assertTrue(
            receipt["verification"]["cleanSourceUiLayout"]["hostLocalGreenEvidenceOnly"]
        )
        self.assertFalse(receipt["verification"]["cleanSourceUiLayout"]["releaseLifecycleEvidence"])
        self.assertTrue(all(value is False for value in receipt["sideEffects"].values()))
        self.assertFalse(receipt["releaseReady"])


if __name__ == "__main__":
    unittest.main()
