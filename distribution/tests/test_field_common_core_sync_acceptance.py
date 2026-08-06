from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "field-common-core-sync-acceptance.schema.json"
TOOL_PATH = DISTRIBUTION / "tools" / "field_common_core_sync_acceptance.py"
DRIFT_TOOL_PATH = DISTRIBUTION / "tools" / "field_common_drift_readiness_audit.py"

SPEC = importlib.util.spec_from_file_location("field_common_core_sync_acceptance_tests", TOOL_PATH)
assert SPEC and SPEC.loader
acceptance: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)

DRIFT_SPEC = importlib.util.spec_from_file_location(
    "field_sync_acceptance_drift_tests", DRIFT_TOOL_PATH
)
assert DRIFT_SPEC and DRIFT_SPEC.loader
drift_tool: ModuleType = importlib.util.module_from_spec(DRIFT_SPEC)
sys.modules[DRIFT_SPEC.name] = drift_tool
DRIFT_SPEC.loader.exec_module(drift_tool)


class FieldCommonCoreSyncAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.field_head = acceptance.current_head(ROOT)
        cls.drift_audit = drift_tool.common_core_drift_audit(repo_root=ROOT)
        cls.field_hashes = acceptance.field_path_hashes(ROOT)
        cls.protected_hashes = acceptance.protected_evidence_base_hashes(repo_root=ROOT)

    def theoretical_pass_fixture(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "kind": acceptance.REQUEST_KIND,
            "universalSource": {
                "branch": "codex/software",
                "commit": "a" * 40,
                "commonCoreHash": "b" * 64,
            },
            "fieldSource": {
                "branch": "codex/software-field",
                "commit": self.field_head,
                "driftAuditSha256": self.drift_audit["auditSha256"],
            },
            "backflowGroups": [
                {
                    "path": group_id,
                    "universalStatus": "present",
                    "pathObservations": [
                        {
                            "path": path,
                            "fieldSha256": self.field_hashes[path],
                            "universalSha256": self.field_hashes[path],
                            "universalStatus": "present",
                        }
                        for path in paths
                    ],
                }
                for group_id, paths in acceptance.BACKFLOW_GROUPS.items()
            ],
            "fieldSpecificIsolation": [
                {
                    "path": path,
                    "fieldSha256": self.field_hashes[path],
                    "universalStatus": "absent",
                }
                for path in acceptance.FIELD_SPECIFIC_PATHS
            ],
            "protectedEvidence": [
                {
                    "path": path,
                    "baseSha256": self.protected_hashes[path],
                    "universalSha256": self.protected_hashes[path],
                    "universalStatus": "present",
                }
                for path in acceptance.PROTECTED_EVIDENCE_PATHS
            ],
            "safetyGates": {
                "validatedHardwarePackCount": 0,
                "threeLayerQuorum": "missing",
                "buildAllowed": False,
                "installAllowed": False,
                "deviceEnumerationAllowed": False,
                "hardwareActionsAllowed": False,
            },
        }

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        self.assertFalse(schema["$defs"]["syncAcceptanceRequest"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["syncAcceptanceReceipt"]["additionalProperties"])
        self.assertEqual(
            schema["$defs"]["syncAcceptanceRequest"]["properties"]["fieldSpecificIsolation"][
                "minItems"
            ],
            9,
        )
        self.assertEqual(
            schema["$defs"]["syncAcceptanceRequest"]["properties"]["protectedEvidence"][
                "minItems"
            ],
            5,
        )

    def test_theoretical_pass_clears_only_common_core_backflow_pending(self) -> None:
        request = self.theoretical_pass_fixture()
        acceptance.validate_acceptance_request(request, repo_root=ROOT)
        receipt = acceptance.evaluate_sync_acceptance(request, repo_root=ROOT)
        self.assertEqual(receipt["acceptanceDecision"], "accept")
        self.assertFalse(receipt["commonCoreBackflowPending"])
        self.assertNotIn("field.common-core-backflow.pending", receipt["blockers"])
        self.assertFalse(receipt["buildAllowed"])
        self.assertFalse(receipt["installAllowed"])
        self.assertFalse(receipt["deviceEnumerationAllowed"])
        self.assertFalse(receipt["hardwareActionsAllowed"])
        self.assertFalse(receipt["simulationAllowed"])
        self.assertEqual(receipt["validatedHardwarePackCount"], 0)
        self.assertEqual(receipt["threeLayerQuorum"], "missing")
        self.assertIn("field.registry.zero-validated-packs", receipt["blockers"])
        self.assertIn("field.quorum.missing-three-layer", receipt["blockers"])
        self.assertEqual(
            set(receipt["acceptedBackflowGroups"]),
            set(acceptance.BACKFLOW_GROUPS),
        )

    def test_current_universal_product_source_is_accepted(self) -> None:
        request = acceptance.build_repository_acceptance_request(
            universal_commit="a918113282b94cf5ebb0b6af3354c5cf2e2ad51d",
            universal_common_core_hash=(
                "79f421b8ec81a746b7b7ae4df7702d18d3df08e76e89ccbf9e6937e22306ce32"
            ),
            field_commit=self.field_head,
            drift_audit_sha256=self.drift_audit["auditSha256"],
            repo_root=ROOT,
        )
        receipt = acceptance.evaluate_sync_acceptance(request, repo_root=ROOT)

        self.assertEqual(receipt["acceptanceDecision"], "accept")
        self.assertFalse(receipt["commonCoreBackflowPending"])
        self.assertEqual(
            receipt["source"]["universalCommit"],
            "a918113282b94cf5ebb0b6af3354c5cf2e2ad51d",
        )
        self.assertNotIn("field.common-core-backflow.pending", receipt["blockers"])
        self.assertFalse(receipt["buildAllowed"])
        self.assertEqual(receipt["validatedHardwarePackCount"], 0)

    def test_public_patch_drift_keeps_common_core_backflow_pending(self) -> None:
        request = self.theoretical_pass_fixture()
        request["backflowGroups"][0]["pathObservations"][0]["universalSha256"] = "0" * 64
        receipt = acceptance.evaluate_sync_acceptance(request, repo_root=ROOT)
        self.assertEqual(receipt["acceptanceDecision"], "deny")
        self.assertTrue(receipt["commonCoreBackflowPending"])
        self.assertIn("field.common-core-backflow.pending", receipt["blockers"])
        self.assertRegex(receipt["errors"][0], "Universal hash does not match Field")
        self.assertFalse(receipt["buildAllowed"])

    def test_field_specific_leak_is_rejected(self) -> None:
        request = self.theoretical_pass_fixture()
        request["fieldSpecificIsolation"][0]["universalStatus"] = "present"
        receipt = acceptance.evaluate_sync_acceptance(request, repo_root=ROOT)
        self.assertEqual(receipt["acceptanceDecision"], "deny")
        self.assertTrue(receipt["commonCoreBackflowPending"])
        self.assertRegex(receipt["errors"][0], "leaked into Universal")

    def test_protected_evidence_delete_or_tamper_is_rejected(self) -> None:
        deleted = self.theoretical_pass_fixture()
        deleted["protectedEvidence"][0]["universalStatus"] = "absent"
        deleted_receipt = acceptance.evaluate_sync_acceptance(deleted, repo_root=ROOT)
        self.assertEqual(deleted_receipt["acceptanceDecision"], "deny")
        self.assertRegex(deleted_receipt["errors"][0], "deleted from Universal")

        tampered = self.theoretical_pass_fixture()
        tampered["protectedEvidence"][0]["universalSha256"] = "1" * 64
        tampered_receipt = acceptance.evaluate_sync_acceptance(tampered, repo_root=ROOT)
        self.assertEqual(tampered_receipt["acceptanceDecision"], "deny")
        self.assertRegex(tampered_receipt["errors"][0], "tampered in Universal")

    def test_safety_gate_drift_is_rejected_even_after_sync(self) -> None:
        request = self.theoretical_pass_fixture()
        request["safetyGates"]["buildAllowed"] = True
        receipt = acceptance.evaluate_sync_acceptance(request, repo_root=ROOT)
        self.assertEqual(receipt["acceptanceDecision"], "deny")
        self.assertTrue(receipt["commonCoreBackflowPending"])
        self.assertRegex(receipt["errors"][0], "safety gates")

    def test_exact_path_sets_are_the_previous_acceptance_scope(self) -> None:
        self.assertEqual(len(acceptance.FIELD_SPECIFIC_PATHS), 9)
        self.assertEqual(len(acceptance.PROTECTED_EVIDENCE_PATHS), 5)
        self.assertEqual(
            set(acceptance.BACKFLOW_GROUPS),
            {
                "universal-core-common-core-commit-binding",
                "universal-core-engine-pack-edition-profile",
                "universal-core-field-contract-retention-hook",
            },
        )


if __name__ == "__main__":
    unittest.main()
