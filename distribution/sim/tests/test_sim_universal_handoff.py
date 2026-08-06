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
        self.assertEqual(receipt["pathSync"]["exactCommonPathCount"], 45)
        self.assertFalse(receipt["execution"]["buildAuthorized"])

    def test_evidence_head_cannot_be_relabelled_product_source(self) -> None:
        receipt = load_receipt()
        receipt["source"]["evidenceCommitUsedAsProductSource"] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "evidence overclaim"):
            validate_handoff(receipt, ROOT)

    def test_auth_binding_blocker_cannot_be_hidden(self) -> None:
        receipt = load_receipt()
        receipt["verification"]["authContractBindingPassed"] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "verification claim"):
            validate_handoff(receipt, ROOT)

    def test_nsis_parent_chain_blocker_cannot_be_hidden(self) -> None:
        receipt = load_receipt()
        receipt["verification"]["nsisTemplateGatePassed"] = True
        with self.assertRaisesRegex(SimUniversalHandoffError, "verification claim"):
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
