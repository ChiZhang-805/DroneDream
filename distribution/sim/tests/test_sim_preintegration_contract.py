from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SIM_TOOLS = ROOT / "distribution" / "sim" / "tools"
if str(SIM_TOOLS) not in sys.path:
    sys.path.insert(0, str(SIM_TOOLS))

from sim_preintegration_contract import (  # noqa: E402
    PreintegrationContractError,
    validate_contract,
)

CONTRACT_PATH = (
    ROOT / "distribution" / "sim" / "readiness" / "final-surface-preintegration.v1.json"
)


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


class SimPreintegrationContractTests(unittest.TestCase):
    def test_frozen_inventory_matches_every_baseline_blob_and_sha(self) -> None:
        contract = validate_contract(load_contract(), ROOT)
        self.assertEqual(len(contract["localSourceSurfaces"]), 72)
        self.assertEqual(len(contract["externalSurfaces"]), 4)
        self.assertEqual(len(contract["negativeAcceptanceChecks"]), 18)

    def test_ownership_boundary_is_explicit(self) -> None:
        contract = validate_contract(load_contract(), ROOT, verify_files=False)
        owners = {row["owner"] for row in contract["localSourceSurfaces"]}
        self.assertEqual(owners, {"universal-common-core", "sim-owned-overlay"})
        self.assertTrue(
            all(
                row["integrationMode"] == "donor-required"
                for row in contract["localSourceSurfaces"]
                if row["owner"] == "universal-common-core"
            )
        )

    def test_pending_donor_cannot_be_claimed_without_exact_identity(self) -> None:
        contract = load_contract()
        contract["baseline"]["canonicalDonorReceived"] = True
        with self.assertRaisesRegex(PreintegrationContractError, "donor must remain pending"):
            validate_contract(contract, ROOT, verify_files=False)

    def test_universal_surface_cannot_be_reclassified_as_sim_overlay(self) -> None:
        contract = load_contract()
        contract["localSourceSurfaces"][0]["owner"] = "sim-owned-overlay"
        with self.assertRaisesRegex(PreintegrationContractError, "both ownership classes|bad mode"):
            validate_contract(contract, ROOT, verify_files=False)

    def test_duplicate_surface_path_is_rejected(self) -> None:
        contract = load_contract()
        duplicate = copy.deepcopy(contract["localSourceSurfaces"][0])
        duplicate["id"] = "duplicate-desktop-config"
        contract["localSourceSurfaces"].append(duplicate)
        with self.assertRaisesRegex(PreintegrationContractError, "duplicate surface path"):
            validate_contract(contract, ROOT, verify_files=False)

    def test_missing_negative_gate_is_rejected(self) -> None:
        contract = load_contract()
        contract["negativeAcceptanceChecks"].pop()
        with self.assertRaisesRegex(PreintegrationContractError, "negative gate list"):
            validate_contract(contract, ROOT, verify_files=False)

    def test_release_or_execution_claim_is_rejected(self) -> None:
        contract = load_contract()
        contract["execution"]["releaseAsset"] = True
        with self.assertRaisesRegex(PreintegrationContractError, "execution flags"):
            validate_contract(contract, ROOT, verify_files=False)

    def test_mutated_sha_is_rejected(self) -> None:
        contract = load_contract()
        contract["localSourceSurfaces"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(PreintegrationContractError, "baseline SHA mismatch"):
            validate_contract(contract, ROOT)


if __name__ == "__main__":
    unittest.main()
