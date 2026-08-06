from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
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

    def test_drift_audit_identifies_field_only_paths_after_common_core_backflow(self) -> None:
        audit = audit_tool.validate_common_core_drift_audit(self.audit)
        self.assertEqual(
            audit["source"]["baseRef"],
            "cabcde3903ccceaf19119824af227bebeb7dd5be",
        )
        subjects = [commit["subject"] for commit in audit["commits"]]
        for required_subject in (
            "feat(field): add lightweight engine pack profile",
            "test(field): bind build plans to common core commit",
            "test(field): add prerelease audit contract",
            "test(field): add lifecycle refusal contract",
            "test(field): audit common drift readiness",
        ):
            self.assertIn(required_subject, subjects)
        by_path = {item["path"]: item for item in audit["changedPaths"]}
        self.assertNotIn("distribution/tools/edition_build_planner.py", by_path)
        self.assertNotIn("engine-pack/tools/engine_pack.py", by_path)
        self.assertEqual(
            by_path["distribution/tools/field_prerelease_audit.py"]["classification"],
            "field-specific-contract",
        )
        self.assertEqual(
            by_path["distribution/runtime-contract-registry.v1.json"]["classification"],
            "field-specific-contract",
        )
        self.assertEqual(audit["summary"]["universalCommonCorePathCount"], 0)
        self.assertEqual(audit["summary"]["protectedEvidenceDriftCount"], 0)
        field_evidence = [
            item
            for item in audit["changedPaths"]
            if item["path"].startswith("artifacts/test-runs/field-")
        ]
        self.assertTrue(field_evidence)
        self.assertTrue(
            all(item["classification"] == "field-specific-contract" for item in field_evidence)
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

    def test_protected_evidence_no_longer_differs_from_universal(self) -> None:
        audit = audit_tool.validate_common_core_drift_audit(self.audit)
        protected = audit["protectedEvidencePlan"]
        self.assertEqual(protected["backflowAction"], "none")
        self.assertEqual(protected["paths"], [])

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
        self.assertNotIn("field.common-core-backflow.pending", receipt["blockers"])
        self.assertIn("build DroneDream-Field-1.0.0.exe", receipt["prohibitedOperations"])
        self.assertIn("read OPENAI_API_KEY or provider credentials", receipt["prohibitedOperations"])

    def test_desktop_preview_structure_binds_exact_brand_and_installer_inputs(self) -> None:
        receipt = audit_tool.validate_field_preview_readiness_receipt(self.receipt)
        structure = receipt["desktopPreviewStructure"]
        self.assertTrue(structure["verified"])
        self.assertEqual(structure["artifactBaseName"], "DroneDream-Field-1.0.0.exe")
        self.assertEqual(structure["frontendDist"], "../../frontend/field-dist")
        self.assertEqual(structure["updaterManifestFilename"], "field-latest.json")
        self.assertEqual(
            structure["canonicalDonor"]["commit"],
            "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
        )
        self.assertEqual(structure["simulatorReferences"], [])
        self.assertEqual(structure["verificationErrors"], [])
        self.assertTrue(all(structure["consumerChecks"].values()))
        self.assertLessEqual(
            structure["effectiveResourceBytes"],
            structure["resourceUpperBoundBytes"],
        )
        self.assertNotIn(
            "field.installer-shortcut-icon.common-core-hook-pending",
            receipt["blockers"],
        )
        self.assertEqual(
            structure["installerShortcutHook"]["proposalStatus"],
            "resolved-by-field-overlay-merge-patch",
        )
        self.assertEqual(
            {asset["assetId"]: asset["sha256"] for asset in structure["assets"]},
            {
                "field-mark":
                    "751372c87bc9630afc2482f5510fa51f8f52d0702a72f58307fc5ed23f9ba7f5",
                "field-dot-lockup":
                    "def3920c2fd355e9ef5a6d4f95d4334e03d02dc2c94eb764e41af154eb03f192",
            },
        )

    def test_desktop_preview_structure_drift_is_rejected(self) -> None:
        drifted = deepcopy(self.receipt)
        drifted["desktopPreviewStructure"]["assets"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            audit_tool.FieldDriftReadinessAuditError,
            "receipt hash drifted",
        ):
            audit_tool.validate_field_preview_readiness_receipt(drifted)

    def test_shortcut_icon_common_core_proposal_retains_resolved_history(self) -> None:
        path = ROOT / (
            "distribution/editions/field/"
            "installer-shortcut-icon-common-core-proposal.v1.json"
        )
        proposal = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            proposal["status"],
            "resolved-by-field-overlay-merge-patch",
        )
        self.assertEqual(proposal["blockedUntilAccepted"], [])
        self.assertFalse(proposal["fieldResolution"]["sharedHookModified"])
        self.assertEqual(proposal["commonCoreBaseCommit"], audit_tool._run_git(
            ROOT,
            "merge-base",
            proposal["fieldSourceCommit"],
            "origin/codex/software",
        ).stdout.strip())
        self.assertEqual(proposal["minimumUniversalPatch"]["paths"], [
            "desktop/src-tauri/nsis/webview2-health.nsh",
            "desktop/scripts/verify-nsis-template.ps1",
        ])
        self.assertFalse(proposal["minimumUniversalPatch"]["historyRewriteAllowed"])
        self.assertFalse(proposal["minimumUniversalPatch"]["forcePushAllowed"])

    def test_tauri_json_merge_patch_removes_universal_icon_source(self) -> None:
        effective = audit_tool.apply_json_merge_patch(
            {"bundle": {"resources": {"icons/icon.ico": "icons/DroneDream.ico"}}},
            {
                "bundle": {
                    "resources": {
                        "icons/icon.ico": None,
                        "field.ico": "icons/DroneDream.ico",
                    }
                }
            },
        )
        self.assertEqual(
            effective,
            {"bundle": {"resources": {"field.ico": "icons/DroneDream.ico"}}},
        )

    def test_release_field_branch_is_observed_but_not_created(self) -> None:
        receipt = audit_tool.validate_field_preview_readiness_receipt(self.receipt)
        self.assertEqual(
            set(receipt["releaseBranch"]),
            {"localPresent", "originPresent"},
        )
        self.assertFalse(receipt["releaseBranchAllowed"])


if __name__ == "__main__":
    unittest.main()
