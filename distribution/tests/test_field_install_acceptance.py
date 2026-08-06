from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution" / "tools" / "field_install_acceptance.py"
SCHEMA_PATH = (
    ROOT / "distribution" / "schemas" / "field-install-acceptance-evidence.schema.json"
)
CURRENT_EVIDENCE = (
    ROOT / "artifacts" / "test-runs" / "field-install-acceptance-readiness-0f86ba8"
)
BUILD_EVIDENCE = ROOT / "artifacts" / "test-runs" / "field-preview-1.0.0-c7e25b3"

SPEC = importlib.util.spec_from_file_location("field_install_acceptance_tests", TOOL_PATH)
assert SPEC and SPEC.loader
acceptance: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


class FieldInstallAcceptanceTests(unittest.TestCase):
    def artifact_manifest(self, *, signature: str = "NotSigned") -> dict[str, object]:
        return {
            "editionId": "field",
            "version": "1.0.0",
            "productSource": {
                "commit": "1" * 40,
                "commonCoreCommit": "2" * 40,
                "commonCoreHash": "3" * 64,
            },
            "artifact": {
                "absolutePath": r"C:\evidence\DroneDream-Field-1.0.0.exe",
                "filename": acceptance.FIELD_ARTIFACT,
                "bytes": 11267482,
                "sha256": "4" * 64,
                "fileVersion": "1.0.0",
                "productVersion": "1.0.0",
                "cargoBuildCount": 1,
                "nsisInvocationCount": 1,
            },
            "signature": {
                "authenticodeStatus": signature,
                "peCertificateTableBytes": 0 if signature == "NotSigned" else 4096,
            },
            "installerStructure": {"webView2BootstrapperSha256": "5" * 64},
        }

    def build_receipt(self) -> dict[str, object]:
        manifest = self.artifact_manifest()
        return {
            "editionId": "field",
            "productSourceHead": "1" * 40,
            "previewReady": True,
            "releaseReady": False,
            "artifact": deepcopy(manifest["artifact"]),
        }

    def host_probe(self, *, available: bool = False) -> dict[str, object]:
        providers = []
        for provider_id in acceptance.PROVIDER_IDS:
            selected = available and provider_id == "windows-sandbox"
            providers.append(
                {
                    "providerId": provider_id,
                    "available": selected,
                    "path": r"C:\Windows\System32\WindowsSandbox.exe" if selected else None,
                    "version": "10.0.26200.1" if selected else None,
                    "sha256": "6" * 64 if selected else None,
                }
            )
        return {
            "host": {
                "osCaption": "Windows 11 test",
                "osVersion": "10.0.26200",
                "osBuild": "26200",
                "osArchitecture": "64-bit",
                "totalPhysicalMemoryBytes": 16 * 1024**3,
            },
            "providers": providers,
        }

    def plan(self, *, available: bool = False, signature: str = "NotSigned") -> dict[str, object]:
        manifest = self.artifact_manifest(signature=signature)
        receipt = self.build_receipt()
        receipt["artifact"] = deepcopy(manifest["artifact"])
        return acceptance.create_plan(
            artifact_manifest=manifest,
            build_receipt=receipt,
            artifact_manifest_sha256="7" * 64,
            build_receipt_sha256="8" * 64,
            evidence_head="9" * 40,
            host_probe=self.host_probe(available=available),
        )

    def rehash(self, plan: dict[str, object]) -> dict[str, object]:
        updated = deepcopy(plan)
        updated.pop("planSha256")
        updated["planSha256"] = acceptance.sha256_canonical(updated)
        return updated

    def execution_fixture(self, plan: dict[str, object], *, signed: bool) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "kind": acceptance.EXECUTION_KIND,
            "editionId": "field",
            "planSha256": plan["planSha256"],
            "artifactSha256": plan["artifact"]["sha256"],
            "environment": {
                "providerId": "windows-sandbox",
                "providerPath": r"C:\Windows\System32\WindowsSandbox.exe",
                "providerVersion": "10.0.26200.1",
                "providerSha256": "6" * 64,
                "hostOsBuild": "26200",
                "guestOsBuild": "26200",
                "guestSnapshotId": "fixture-clean-guest",
                "networkMode": "disabled",
                "deviceRedirection": "disabled",
            },
            "invocationCounts": deepcopy(acceptance.INVOCATION_BUDGET),
            "phases": [
                {"phaseId": phase_id, "result": "pass", "evidenceSha256": "a" * 64}
                for phase_id in acceptance.PHASE_IDS
            ],
            "signatureEvidence": {
                "authenticodeStatus": "Valid" if signed else "NotSigned",
                "signerThumbprint": "c" * 40 if signed else None,
                "peCertificateTableBytes": 4096 if signed else 0,
            },
            "shortcutEvidence": {
                "result": "pass",
                "startMenuTargetMatched": True,
                "desktopTargetMatched": True,
                "iconMatched": True,
                "appUserModelIdPresent": True,
                "evidenceSha256": "d" * 64,
            },
            "webView2Evidence": {
                "result": "pass",
                "runtimeVersion": "fixture",
                "runtimeExecutableHealthy": True,
                "repairExecuted": False,
                "networkRequests": 0,
                "evidenceSha256": "e" * 64,
            },
            "localizationEvidence": {
                "result": "pass",
                "englishInstallerPassed": True,
                "chineseInstallerPassed": True,
                "englishApplicationPassed": True,
                "chineseApplicationPassed": True,
                "keyboardPassed": True,
                "screenReaderNamesPassed": True,
                "evidenceSha256": "f" * 64,
            },
            "residueEvidence": {
                "result": "pass",
                "unexpectedResidue": [],
                "allowedResidue": ["shared-microsoft-webview2-runtime", "hostEvidenceRoot"],
                "evidenceSha256": "a" * 64,
            },
            "rollbackEvidence": {
                "result": "pass",
                "guestDiscarded": True,
                "evidencePreserved": True,
                "hostProductStateUnchanged": True,
                "evidenceSha256": "b" * 64,
            },
            "safetyEvidence": {
                "deviceEnumerationExecuted": False,
                "usbSerialOpened": False,
                "hardwareActionExecuted": False,
                "simulationExecuted": False,
            },
            "websiteMetadata": {
                "urlFamilyFrozen": True,
                "redownloadSha256Matched": True,
            },
            "websiteHandoffPrecheck": {},
            "receiptSha256": "b" * 64,
        }

    def test_schema_is_closed_and_covers_plan_readiness_and_execution(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        self.assertFalse(schema["$defs"]["plan"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["readinessReceipt"]["additionalProperties"])
        self.assertFalse(schema["$defs"]["executionReceipt"]["additionalProperties"])
        for name, definition in schema["$defs"].items():
            if definition.get("type") == "object":
                self.assertFalse(
                    definition.get("additionalProperties"),
                    f"schema object definition is not closed: {name}",
                )
        self.assertEqual(
            schema["$defs"]["artifact"]["properties"]["filename"]["const"],
            acceptance.FIELD_ARTIFACT,
        )

    def test_current_host_without_provider_stops_before_yellow(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["state"], "blocked-no-isolated-provider")
        self.assertFalse(plan["environment"]["available"])
        self.assertFalse(plan["authorization"]["installationAuthorized"])
        receipt = acceptance.create_readiness_receipt(plan)
        self.assertEqual(receipt["decision"], "deny-before-yellow")
        self.assertIn("field.install.environment.unavailable", receipt["blockers"])
        self.assertFalse(receipt["executionPerformed"])
        self.assertFalse(receipt["websiteHandoffPrecheck"]["websiteReady"])

    def test_current_exact_evidence_binds_product_artifact_tool_schema_and_host_probe(self) -> None:
        plan = acceptance.load_json(CURRENT_EVIDENCE / "plan.json")
        receipt = acceptance.load_json(CURRENT_EVIDENCE / "green-readiness-receipt.json")
        acceptance.validate_plan(plan)
        acceptance.validate_readiness_receipt(receipt, plan=plan)
        self.assertEqual(
            plan["source"]["productSourceCommit"],
            "c7e25b3862fdd491de99f4a0b02cf0f348b94ea3",
        )
        self.assertEqual(
            plan["source"]["evidenceHead"],
            "0f86ba8f6e125aa95ff3bb0a4a5357843786fad8",
        )
        self.assertEqual(
            plan["artifact"]["sha256"],
            "ce3937440e85655d9532097904286eae783f6ed6b25eb0eb94ee113049139317",
        )
        self.assertEqual(
            plan["source"]["toolSha256"],
            "a6e2ad4868db254ebec148811dec7fdfb32ae0d787ec26db5008ae39b3152356",
        )
        self.assertNotEqual(
            plan["source"]["toolSha256"],
            acceptance.sha256_file(TOOL_PATH),
        )
        self.assertEqual(plan["source"]["schemaSha256"], acceptance.sha256_file(SCHEMA_PATH))
        self.assertEqual(
            plan["source"]["artifactManifestSha256"],
            acceptance.sha256_file(BUILD_EVIDENCE / "artifact-manifest.json"),
        )
        self.assertEqual(
            plan["source"]["buildReceiptSha256"],
            acceptance.sha256_file(BUILD_EVIDENCE / "build-receipt.json"),
        )
        host_probe = acceptance.load_json(CURRENT_EVIDENCE / "host-probe.json")
        self.assertEqual(
            plan["environment"]["probeSha256"], acceptance.sha256_canonical(host_probe)
        )

    def test_available_provider_requests_yellow_but_does_not_authorize_install(self) -> None:
        plan = self.plan(available=True)
        self.assertEqual(plan["state"], "yellow-approval-required")
        self.assertEqual(plan["environment"]["selectedProvider"], "windows-sandbox")
        self.assertFalse(plan["authorization"]["installationAuthorized"])
        receipt = acceptance.create_readiness_receipt(plan)
        self.assertEqual(receipt["decision"], "request-yellow-approval")
        self.assertEqual(
            receipt["executionCounts"],
            {key: 0 for key in acceptance.INVOCATION_BUDGET},
        )

    def test_exact_owned_paths_invocation_budget_and_rollback_are_frozen(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["invocationBudget"], acceptance.INVOCATION_BUDGET)
        self.assertEqual(
            [item["phaseId"] for item in plan["phases"]], list(acceptance.PHASE_IDS)
        )
        self.assertEqual(plan["environment"]["networkMode"], "disabled")
        self.assertFalse(plan["ownedPaths"]["writesOutsideDisposableGuestAllowed"])
        self.assertEqual(plan["rollbackGate"]["method"], "discard-entire-guest")
        self.assertFalse(plan["rollbackGate"]["evidenceDeletionAllowed"])
        self.assertEqual(plan["residueGate"]["unexpectedProductResidueDecision"], "fail")
        self.assertFalse(plan["upgradeSemantics"]["semanticVersionUpgradeClaimAllowed"])

    def test_network_host_write_budget_and_hardware_drift_are_rejected(self) -> None:
        mutations = (
            ("environment", "networkMode", "enabled", "isolated environment"),
            ("ownedPaths", "writesOutsideDisposableGuestAllowed", True, "host write"),
            ("invocationBudget", "installerExe", 3, "invocation budget"),
            ("safetyBoundary", "deviceEnumerationAllowed", True, "hardware safety"),
            ("rollbackGate", "evidenceDeletionAllowed", True, "evidence deletion"),
        )
        for section, key, value, error in mutations:
            with self.subTest(section=section, key=key):
                plan = self.plan()
                plan[section][key] = value
                plan = self.rehash(plan)
                with self.assertRaisesRegex(acceptance.FieldInstallAcceptanceError, error):
                    acceptance.validate_plan(plan)

    def test_artifact_manifest_receipt_mismatch_is_rejected(self) -> None:
        manifest = self.artifact_manifest()
        receipt = self.build_receipt()
        receipt["artifact"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(acceptance.FieldInstallAcceptanceError, "mismatch: sha256"):
            acceptance.create_plan(
                artifact_manifest=manifest,
                build_receipt=receipt,
                artifact_manifest_sha256="7" * 64,
                build_receipt_sha256="8" * 64,
                evidence_head="9" * 40,
                host_probe=self.host_probe(),
            )

    def test_authorized_unsigned_can_handoff_only_after_dynamic_checks(self) -> None:
        plan = self.plan(available=True)
        result = acceptance.evaluate_execution_for_website(
            self.execution_fixture(plan, signed=False), plan=plan
        )
        self.assertTrue(result["websiteReady"])
        self.assertEqual(result["signatureState"], "NotSigned")
        self.assertTrue(result["unsignedInternalDistributionAuthorized"])

    def test_theoretical_signed_exact_execution_can_clear_website_precheck(self) -> None:
        plan = self.plan(available=True, signature="Valid")
        result = acceptance.evaluate_execution_for_website(
            self.execution_fixture(plan, signed=True), plan=plan
        )
        self.assertTrue(result["websiteReady"])
        self.assertEqual(result["state"], "ready-for-exact-handoff")
        self.assertEqual(result["blockers"], [])

    def test_device_or_simulation_execution_is_rejected(self) -> None:
        plan = self.plan(available=True)
        for key in (
            "deviceEnumerationExecuted",
            "usbSerialOpened",
            "hardwareActionExecuted",
            "simulationExecuted",
        ):
            with self.subTest(key=key):
                execution = self.execution_fixture(plan, signed=False)
                execution["safetyEvidence"][key] = True
                with self.assertRaisesRegex(
                    acceptance.FieldInstallAcceptanceError,
                    "hardware/simulation boundary",
                ):
                    acceptance.evaluate_execution_for_website(execution, plan=plan)


if __name__ == "__main__":
    unittest.main()
