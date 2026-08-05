from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "field-common-drift-readiness-audit.schema.json"
TOOL_PATH = DISTRIBUTION / "tools" / "field_common_drift_readiness_audit.py"

SPEC = importlib.util.spec_from_file_location("field_common_drift_readiness_tests", TOOL_PATH)
assert SPEC and SPEC.loader
audit_tool: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit_tool
SPEC.loader.exec_module(audit_tool)


class FieldCommonDriftReadinessAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = audit_tool.common_core_drift_audit(repo_root=ROOT)
        cls.receipt = audit_tool.field_preview_readiness_receipt(repo_root=ROOT)

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        self.assertFalse(schema["$defs"]["commonCoreDriftAudit"]["additionalProperties"])
        self.assertFalse(
            schema["$defs"]["fieldPreviewReadinessReceipt"]["additionalProperties"]
        )
        self.assertEqual(
            schema["$defs"]["fieldPreviewReadinessReceipt"]["properties"]["decision"]["const"],
            "deny",
        )

    def test_drift_audit_identifies_commits_paths_and_common_core_backflow(self) -> None:
        audit = audit_tool.validate_common_core_drift_audit(self.audit)
        subjects = [commit["subject"] for commit in audit["commits"]]
        self.assertEqual(
            subjects,
            [
                "feat(field): add lightweight engine pack profile",
                "test(field): bind build plans to common core commit",
                "test(field): add prerelease audit contract",
                "test(field): add lifecycle refusal contract",
            ],
        )
        by_path = {item["path"]: item for item in audit["changedPaths"]}
        self.assertEqual(
            by_path["distribution/tools/edition_build_planner.py"]["classification"],
            "universal-common-core-backflow",
        )
        self.assertEqual(
            by_path["engine-pack/tools/engine_pack.py"]["classification"],
            "universal-common-core-backflow",
        )
        self.assertEqual(
            by_path["distribution/tools/field_prerelease_audit.py"]["classification"],
            "field-specific-contract",
        )
        self.assertEqual(
            by_path[
                "artifacts/test-runs/sim-preview-1.0.0-2aec69e/release-receipt.json"
            ]["classification"],
            "protected-evidence-drift",
        )

    def test_backflow_plan_excludes_field_specific_contract_implementations(self) -> None:
        audit = audit_tool.validate_common_core_drift_audit(self.audit)
        field_paths = {
            item["path"]
            for item in audit["changedPaths"]
            if item["classification"] == "field-specific-contract"
        }
        self.assertIn("distribution/tools/field_prerelease_audit.py", field_paths)
        self.assertIn("distribution/tools/field_lifecycle_contract.py", field_paths)
        for plan in audit["minimumForwardBackflowPlan"]:
            self.assertFalse(field_paths.intersection(plan["paths"]))
        plan_ids = {plan["planId"] for plan in audit["minimumForwardBackflowPlan"]}
        self.assertIn("universal-core-common-core-commit-binding", plan_ids)
        self.assertIn("universal-core-engine-pack-edition-profile", plan_ids)
        self.assertIn("universal-core-field-contract-retention-hook", plan_ids)

    def test_protected_evidence_deletions_are_not_backflowed(self) -> None:
        audit = audit_tool.validate_common_core_drift_audit(self.audit)
        protected = audit["protectedEvidencePlan"]
        self.assertEqual(protected["backflowAction"], "none")
        self.assertGreaterEqual(len(protected["paths"]), 1)
        self.assertTrue(
            all(path["path"].startswith("artifacts/test-runs/") for path in protected["paths"])
        )

    def test_preview_build_readiness_is_fail_closed_and_non_executing(self) -> None:
        receipt = audit_tool.validate_field_preview_readiness_receipt(self.receipt)
        self.assertEqual(receipt["decision"], "deny")
        self.assertFalse(receipt["buildAllowed"])
        self.assertFalse(receipt["installAllowed"])
        self.assertFalse(receipt["releaseBranchAllowed"])
        self.assertFalse(receipt["hardwareActionsAllowed"])
        self.assertFalse(receipt["deviceEnumerationAllowed"])
        self.assertFalse(receipt["simulationAllowed"])
        self.assertEqual(receipt["registry"]["validatedHardwarePackCount"], 0)
        self.assertEqual(receipt["registry"]["validatedHardwarePackIds"], [])
        self.assertIn("field.registry.zero-validated-packs", receipt["blockers"])
        self.assertIn("field.common-core-backflow.pending", receipt["blockers"])
        self.assertIn("build DroneDream-Field-1.0.0.exe", receipt["prohibitedOperations"])
        self.assertIn("read OPENAI_API_KEY or provider credentials", receipt["prohibitedOperations"])

    def test_release_field_branch_is_observed_but_not_created(self) -> None:
        receipt = audit_tool.validate_field_preview_readiness_receipt(self.receipt)
        self.assertEqual(
            set(receipt["releaseBranch"]),
            {"localPresent", "originPresent"},
        )
        self.assertFalse(receipt["releaseBranchAllowed"])


if __name__ == "__main__":
    unittest.main()
