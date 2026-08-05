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
SCHEMA_PATH = DISTRIBUTION / "schemas" / "field-lifecycle-contract.schema.json"
TOOL_PATH = DISTRIBUTION / "tools" / "field_lifecycle_contract.py"

SPEC = importlib.util.spec_from_file_location("field_lifecycle_contract_tests", TOOL_PATH)
assert SPEC and SPEC.loader
contract: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


class FieldLifecycleContractTests(unittest.TestCase):
    def make_contract(self) -> dict[str, object]:
        return contract.create_lifecycle_contract(
            common_core_commit="9" * 40,
            common_core_hash="a" * 64,
            field_manifest_sha256=contract.sha256_file(
                ROOT / "distribution" / "editions" / "field.v1.json"
            ),
            capability_policy_sha256=contract.sha256_file(
                ROOT / "distribution" / "capabilities" / "core-capabilities.v1.json"
            ),
            execution_gate_policy_sha256=contract.sha256_file(
                ROOT / "distribution" / "safety" / "edition-execution-gate.v1.json"
            ),
        )

    def rehash(self, document: dict[str, object]) -> dict[str, object]:
        updated = deepcopy(document)
        updated.pop("contractSha256")
        updated["contractSha256"] = contract.sha256_canonical(updated)
        return updated

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        self.assertFalse(schema["$defs"]["lifecycleContract"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["lifecycleReceipt"]["additionalProperties"])
        self.assertEqual(
            schema["$defs"]["artifactPolicy"]["properties"]["expectedBaseName"]["const"],
            "DroneDream-Field-1.0.0.exe",
        )

    def test_lifecycle_paths_are_plan_only_and_never_install_or_build_exe(self) -> None:
        document = contract.validate_lifecycle_contract(self.make_contract())
        self.assertEqual(document["artifactPolicy"]["expectedBaseName"], "DroneDream-Field-1.0.0.exe")
        self.assertFalse(document["artifactPolicy"]["exeBuilt"])
        self.assertFalse(document["artifactPolicy"]["exeInstalled"])
        self.assertFalse(document["artifactPolicy"]["signatureMayBeClaimed"])
        self.assertEqual(
            [scenario["scenarioId"] for scenario in document["lifecycleScenarios"]],
            ["fresh-install", "upgrade", "uninstall", "rollback"],
        )
        for scenario in document["lifecycleScenarios"]:
            self.assertEqual(scenario["decision"], "deny")
            self.assertFalse(scenario["installerBuilt"])
            self.assertFalse(scenario["installerInstalled"])
            self.assertFalse(scenario["writesFilesystemOutsidePlan"])
            self.assertIn("field.lifecycle.plan-only", scenario["reasonCodes"])

    def test_dangerous_actions_offline_and_missing_device_all_deny(self) -> None:
        document = contract.validate_lifecycle_contract(self.make_contract())
        refusals = {scenario["scenarioId"]: scenario for scenario in document["refusalScenarios"]}
        for action in contract.DANGEROUS_ACTIONS:
            scenario = refusals[f"dangerous-{action}"]
            self.assertEqual(scenario["decision"], "deny")
            self.assertFalse(scenario["frontendIsAuthority"])
            self.assertTrue(scenario["requiresValidatedSignedPack"])
            self.assertTrue(scenario["requiresThreeLayerQuorum"])
            self.assertIn("field.hardware-action.fail-closed", scenario["reasonCodes"])
        for scenario_id in ("offline-no-network", "device-missing"):
            scenario = refusals[scenario_id]
            self.assertEqual(scenario["decision"], "deny")
            self.assertIn("field.offline-or-device-missing", scenario["reasonCodes"])
            self.assertIn("field.discovery.not-authorization", scenario["reasonCodes"])

    def test_en_zh_and_accessibility_messages_are_required(self) -> None:
        document = contract.validate_lifecycle_contract(self.make_contract())
        self.assertEqual(document["accessibilityPolicy"]["localizedLanguages"], ["en", "zh-CN"])
        self.assertTrue(document["accessibilityPolicy"]["screenReaderSummaryRequired"])
        self.assertTrue(document["accessibilityPolicy"]["keyboardAccessibleReviewActionRequired"])
        for collection in ("lifecycleScenarios", "refusalScenarios"):
            for scenario in document[collection]:
                message = scenario["localizedMessage"]
                for locale in ("en", "zh-CN"):
                    self.assertTrue(message[locale]["title"].strip())
                    self.assertTrue(message[locale]["body"].strip())
                    self.assertTrue(message[locale]["primaryActionLabel"].strip())
                    self.assertTrue(message[locale]["screenReaderSummary"].strip())

    def test_contract_rejects_execution_signature_claims_and_frontend_authority(self) -> None:
        executed = deepcopy(self.make_contract())
        executed["artifactPolicy"]["exeBuilt"] = True
        executed = self.rehash(executed)
        with self.assertRaisesRegex(
            contract.FieldLifecycleContractError,
            "artifact policy",
        ):
            contract.validate_lifecycle_contract(executed)

        signed = deepcopy(self.make_contract())
        signed["artifactPolicy"]["signatureMayBeClaimed"] = True
        signed = self.rehash(signed)
        with self.assertRaisesRegex(
            contract.FieldLifecycleContractError,
            "artifact policy",
        ):
            contract.validate_lifecycle_contract(signed)

        frontend = deepcopy(self.make_contract())
        frontend["refusalScenarios"][0]["frontendIsAuthority"] = True
        frontend = self.rehash(frontend)
        with self.assertRaisesRegex(
            contract.FieldLifecycleContractError,
            "frontend cannot authorize",
        ):
            contract.validate_lifecycle_contract(frontend)

    def test_receipt_binds_source_artifact_policy_and_scenario_counts(self) -> None:
        document = self.make_contract()
        receipt = contract.create_lifecycle_receipt(document)
        self.assertEqual(receipt["decision"], "deny")
        self.assertEqual(receipt["contractSha256"], document["contractSha256"])
        self.assertEqual(receipt["source"]["commonCoreCommit"], "9" * 40)
        self.assertFalse(receipt["artifactPolicy"]["exeBuilt"])
        self.assertEqual(receipt["scenarioCounts"], {"lifecycle": 4, "refusal": 6})
        self.assertIn("field.lifecycle.plan-only", receipt["reasonCodes"])
        self.assertRegex(receipt["receiptSha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
