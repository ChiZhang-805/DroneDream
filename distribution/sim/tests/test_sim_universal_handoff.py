from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "distribution" / "sim" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sim_universal_handoff import (  # noqa: E402
    SimUniversalHandoffError,
    validate_handoff,
)

RECEIPT = ROOT / "distribution/sim/readiness/universal-common-core-handoff.v1.json"


def load_receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


class SimUniversalHandoffTests(unittest.TestCase):
    def test_exact_handoff_and_sim_adapter_validate(self) -> None:
        receipt = validate_handoff(load_receipt(), ROOT)
        self.assertEqual(receipt["pathSync"]["canonicalBrandPathCount"], 94)
        self.assertEqual(receipt["pathSync"]["exactCommonPathCount"], 53)
        self.assertFalse(receipt["execution"]["buildAuthorized"])

    def test_observed_head_cannot_be_relabelled_whole_product_source(self) -> None:
        receipt = load_receipt()
        receipt["source"]["observedHeadUsedAsWholeProductSource"] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "whole Universal head"):
            validate_handoff(receipt, ROOT)

    def test_auth_binding_correction_cannot_be_hidden(self) -> None:
        receipt = load_receipt()
        receipt["verification"]["authContractBindingPassed"] = False
        with self.assertRaisesRegex(SimUniversalHandoffError, "verification claim"):
            validate_handoff(receipt, ROOT)

    def test_nsis_runtime_correction_cannot_be_hidden(self) -> None:
        receipt = load_receipt()
        receipt["verification"]["nsisTemplateGatePassed"] = False
        with self.assertRaisesRegex(SimUniversalHandoffError, "verification claim"):
            validate_handoff(receipt, ROOT)

    def test_nsis_identity_fix_cannot_be_relabelled(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["nsisIdentityFix"]["sourceCommit"] = "0" * 40
        with self.assertRaisesRegex(SimUniversalHandoffError, "NSIS identity fix"):
            validate_handoff(receipt, ROOT)

    def test_lifecycle_validator_fix_cannot_be_relabelled(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["lifecycleRegistrationValidator"][
            "productNsisChanged"
        ] = True
        with self.assertRaisesRegex(
            SimUniversalHandoffError,
            "lifecycle registration verifier",
        ):
            validate_handoff(receipt, ROOT)

    def test_release_build_driver_path_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["releaseBuildDriver"]["paths"][0]["blob"] = "0" * 40
        with self.assertRaisesRegex(SimUniversalHandoffError, "release build driver blob"):
            validate_handoff(receipt, ROOT)

    def test_frontend_dist_resolution_path_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["frontendDistResolution"]["paths"][0]["blob"] = (
            "0" * 40
        )
        with self.assertRaisesRegex(
            SimUniversalHandoffError,
            "frontendDist resolution blob",
        ):
            validate_handoff(receipt, ROOT)

    def test_frontend_dist_overlay_location_overclaim_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["frontendDistResolution"][
            "overlayLocationChangesResolution"
        ] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "overlay location"):
            validate_handoff(receipt, ROOT)

    def test_lifecycle_preference_residue_path_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["lifecyclePreferenceResidue"]["simConsumedPaths"][0][
            "blob"
        ] = "0" * 40
        with self.assertRaisesRegex(
            SimUniversalHandoffError,
            "lifecycle preference residue blob",
        ):
            validate_handoff(receipt, ROOT)

    def test_universal_only_lifecycle_test_cannot_be_reintroduced(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["lifecyclePreferenceResidue"][
            "universalOnlyTestRestored"
        ] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "Universal-only"):
            validate_handoff(receipt, ROOT)

    def test_auth_verifier_migration_order_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["authVerifierAtomicSync"]["paths"].reverse()
        with self.assertRaisesRegex(SimUniversalHandoffError, "migration order"):
            validate_handoff(receipt, ROOT)

    def test_runtime_atomic_path_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["corrections"]["runtimeModeAtomicReview"]["paths"][0]["blob"] = "0" * 40
        with self.assertRaisesRegex(SimUniversalHandoffError, "runtime correction blob"):
            validate_handoff(receipt, ROOT)

    def test_common_core_candidate_cannot_be_claimed_validated(self) -> None:
        receipt = load_receipt()
        receipt["commonCoreClassification"]["baselineUpdated"] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "commonCore update"):
            validate_handoff(receipt, ROOT)

    def test_build_or_release_claim_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["execution"]["buildExecuted"] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "execution overclaim"):
            validate_handoff(receipt, ROOT)


if __name__ == "__main__":
    unittest.main()
