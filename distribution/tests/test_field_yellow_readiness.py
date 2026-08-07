from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution" / "tools" / "field_yellow_readiness.py"
SCHEMA_PATH = ROOT / "distribution" / "schemas" / "field-yellow-readiness.schema.json"

SPEC = importlib.util.spec_from_file_location("field_yellow_readiness_tests", TOOL_PATH)
assert SPEC and SPEC.loader
readiness: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)


class FieldYellowReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        synced_common_core = readiness._git(
            ROOT, "merge-base", "HEAD", readiness.COMMON_CORE_REF
        )
        cls.receipt = readiness.create_yellow_readiness_receipt(
            repo_root=ROOT,
            source_tree_clean=True,
            upstream_ahead=0,
            upstream_behind=0,
            common_core_ref=synced_common_core,
        )

    def test_schema_is_versioned_and_closes_receipt_and_candidate(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        self.assertFalse(schema["$defs"]["receipt"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["candidate"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["source"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["safety"]["additionalProperties"])

    def test_static_candidate_is_ready_to_request_but_not_authorized(self) -> None:
        receipt = readiness.validate_yellow_readiness_receipt(self.receipt)
        self.assertEqual(receipt["decision"], "ready-to-request-yellow")
        self.assertEqual(receipt["blockers"], [])
        for field in (
            "yellowBuildAuthorized",
            "buildExecuted",
            "installExecuted",
            "deviceEnumerationExecuted",
            "hardwareActionsAllowed",
            "simulationExecuted",
            "apiKeyRead",
            "releaseBranchCreated",
        ):
            self.assertFalse(receipt[field])

    def test_payload_freeze_excludes_executable_simulator_content(self) -> None:
        payload = self.receipt["candidate"]["payload"]
        self.assertEqual(payload["profileId"], "field-lightweight")
        self.assertFalse(payload["includesLargeSimulator"])
        self.assertEqual(
            payload["excludedSourcePaths"],
            ["backend/app/simulator", "scripts/simulators"],
        )
        self.assertEqual(payload["forbiddenSimulatorPayloads"], [])
        self.assertEqual(payload["missingRequiredResources"], [])
        self.assertLessEqual(payload["sourceBytes"], payload["sourceUpperBoundBytes"])
        self.assertEqual(
            payload["controlPlaneSimulatorMetadata"],
            ["distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json"],
        )
        self.assertTrue(payload["artifactPayloadScanPending"])

    def test_field_branding_nsis_license_and_notice_are_bound(self) -> None:
        desktop = self.receipt["candidate"]["desktop"]
        resources = {
            item["source"]: item["destination"] for item in desktop["effectiveResources"]
        }
        self.assertTrue(desktop["verified"])
        self.assertNotIn("icons/icon.ico", resources)
        self.assertEqual(
            resources["../../brand/generated/field/windows/icon.ico"],
            "icons/DroneDream.ico",
        )
        self.assertIn("../../LICENSE", resources)
        self.assertIn("../../runtime/THIRD_PARTY_NOTICES.md", resources)
        self.assertIn("../../runtime/licenses/valkey-COPYING", resources)
        self.assertEqual(
            resources["../../distribution/editions/field/adapters/THIRD_PARTY_NOTICES.md"],
            "licenses/Field-Adapter-THIRD-PARTY-NOTICES.md",
        )
        self.assertEqual(
            desktop["canonicalDonor"]["commit"],
            "6de4f1343c0239a916949f0486fa63d3f460d6a8",
        )
        self.assertEqual(
            next(item for item in resources if item.endswith("field/windows/icon.ico")),
            "../../brand/generated/field/windows/icon.ico",
        )

    def test_zero_validated_pack_and_all_three_layers_deny_hardware(self) -> None:
        safety = self.receipt["candidate"]["safety"]
        self.assertEqual(safety["validatedHardwarePackCount"], 0)
        self.assertFalse(safety["frontendIsAuthority"])
        self.assertFalse(safety["hardwareActionHandlersImplemented"])
        self.assertEqual(safety["requiredLayers"], ["native", "backend", "runtime"])
        self.assertEqual([item["layer"] for item in safety["layers"]], safety["requiredLayers"])
        self.assertTrue(all(item["decisionWithCurrentCatalog"] == "deny" for item in safety["layers"]))
        self.assertTrue(all(item["sourceContractPresent"] for item in safety["layers"]))
        self.assertTrue(all(item["testContractPresent"] for item in safety["layers"]))
        self.assertEqual(
            safety["actionDecisions"],
            {action: "deny" for action in readiness.DENIED_ACTIONS},
        )
        discovery = safety["readonlyDiscovery"]
        self.assertFalse(discovery["discoveryIsAuthorization"])
        self.assertEqual(discovery["decision"], "deny")
        self.assertEqual(discovery["transport"]["kind"], "fake")
        self.assertFalse(discovery["transport"]["openedDevice"])
        self.assertFalse(discovery["transport"]["writeAttempted"])

    def test_lifecycle_remains_plan_only_and_accessible(self) -> None:
        lifecycle = self.receipt["candidate"]["lifecycle"]
        self.assertEqual(
            [item["scenarioId"] for item in lifecycle["scenarios"]],
            ["fresh-install", "upgrade", "uninstall", "rollback"],
        )
        self.assertTrue(all(item["decision"] == "deny" for item in lifecycle["scenarios"]))
        self.assertTrue(all(not item["executed"] for item in lifecycle["scenarios"]))
        self.assertEqual(lifecycle["localizedLanguages"], ["en", "zh-CN"])
        self.assertTrue(lifecycle["screenReaderSummaryRequired"])
        self.assertTrue(lifecycle["keyboardAccessibleReviewActionRequired"])

    def test_all_wrong_package_cases_are_denied_for_the_expected_reason(self) -> None:
        cases = self.receipt["negativePackageCases"]
        self.assertEqual(len(cases), 7)
        self.assertTrue(all(case["decision"] == "deny" for case in cases))
        self.assertTrue(all(case["verified"] for case in cases))
        self.assertTrue(
            all(case["expectedBlocker"] in case["observedBlockers"] for case in cases)
        )

    def test_final_website_handoff_remains_exact_and_unissued(self) -> None:
        handoff = self.receipt["finalWebsiteHandoff"]
        self.assertEqual(handoff["state"], "awaiting-exact-handoff")
        self.assertEqual(handoff["filename"], "DroneDream-Field-1.0.0.exe")
        self.assertEqual(handoff["version"], "1.0.0")
        self.assertEqual(handoff["buildCount"], 0)
        self.assertIsNone(handoff["uniqueExeAbsolutePath"])
        self.assertIsNone(handoff["bytes"])
        self.assertIsNone(handoff["sha256"])
        self.assertEqual(handoff["signatureState"], "not-issued")
        self.assertFalse(handoff["previewSubstitutionAllowed"])
        self.assertFalse(handoff["crossEditionAttachmentAllowed"])
        self.assertFalse(handoff["duplicateShaUrlOrTagAllowed"])
        self.assertFalse(handoff["releaseReady"])

    def test_hardware_allow_mutation_is_rejected_without_trusting_receipt_hash(self) -> None:
        candidate = deepcopy(self.receipt["candidate"])
        candidate["safety"]["actionDecisions"]["hardware.flight"] = "allow"
        blockers = readiness.evaluate_candidate(
            candidate,
            expected_common_core=self.receipt["candidate"]["source"]["commonCoreCommit"],
        )
        self.assertIn("field.hardware.action-allow", blockers)

    def test_receipt_hash_drift_is_rejected(self) -> None:
        drifted = deepcopy(self.receipt)
        drifted["yellowBuildAuthorized"] = True
        with self.assertRaisesRegex(readiness.FieldYellowReadinessError, "hash drifted"):
            readiness.validate_yellow_readiness_receipt(drifted)


if __name__ == "__main__":
    unittest.main()
