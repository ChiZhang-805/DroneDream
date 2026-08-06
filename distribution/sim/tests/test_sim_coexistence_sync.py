from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "distribution" / "sim" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sim_coexistence_sync import SimCoexistenceSyncError, validate_sync  # noqa: E402

RECEIPT = ROOT / "distribution" / "sim" / "readiness" / "coexistence-common-core-sync.v1.json"


def load_receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


class SimCoexistenceSyncTests(unittest.TestCase):
    def test_exact_runtime_blobs_and_sim_identity_validate(self) -> None:
        receipt = validate_sync(load_receipt(), ROOT)
        self.assertEqual(len(receipt["synchronizedRuntimePaths"]), 7)
        self.assertEqual(receipt["simOverlay"]["installerProductName"], "DroneDream-Sim")
        self.assertFalse(receipt["execution"]["releaseAsset"])

    def test_runtime_blob_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["synchronizedRuntimePaths"][0]["blob"] = "0" * 40
        with self.assertRaisesRegex(SimCoexistenceSyncError, "runtime blob"):
            validate_sync(receipt, ROOT)

    def test_candidate_common_core_cannot_be_relabelled_current(self) -> None:
        receipt = load_receipt()
        receipt["commonCoreClassification"]["baselineUpdated"] = True
        with self.assertRaisesRegex(SimCoexistenceSyncError, "baseline update"):
            validate_sync(receipt, ROOT)

    def test_unhanded_test_cannot_be_claimed_adopted(self) -> None:
        receipt = load_receipt()
        receipt["observedNotAdoptedTest"]["path"] = "distribution/tests/fake.py"
        with self.assertRaisesRegex(SimCoexistenceSyncError, "observed test path"):
            validate_sync(receipt, ROOT)

    def test_inherited_runtime_prerequisite_cannot_be_claimed_synced(self) -> None:
        receipt = load_receipt()
        runtime = receipt["pendingPrerequisitePaths"][-1]
        runtime["currentBlob"] = runtime["donorBlob"]
        with self.assertRaisesRegex(SimCoexistenceSyncError, "current prerequisite blob"):
            validate_sync(receipt, ROOT)

    def test_incomplete_vendored_verifier_cannot_be_claimed_passed(self) -> None:
        receipt = load_receipt()
        receipt["verification"]["donorVendoredNsisVerifierPassed"] = True
        with self.assertRaisesRegex(SimCoexistenceSyncError, "vendored verifier overclaim"):
            validate_sync(receipt, ROOT)

    def test_display_name_cannot_replace_internal_installer_identity(self) -> None:
        receipt = load_receipt()
        receipt["simOverlay"]["installerProductName"] = "DroneDream \u00b7 SIM"
        with self.assertRaisesRegex(SimCoexistenceSyncError, "internal name"):
            validate_sync(receipt, ROOT)

    def test_execution_or_release_claim_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["execution"]["installerExecuted"] = True
        with self.assertRaisesRegex(SimCoexistenceSyncError, "execution"):
            validate_sync(receipt, ROOT)


if __name__ == "__main__":
    unittest.main()
