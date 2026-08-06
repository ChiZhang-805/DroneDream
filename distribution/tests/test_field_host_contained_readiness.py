from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "distribution" / "tools" / "field_host_contained_readiness.py"
SCHEMA_PATH = (
    ROOT
    / "distribution"
    / "schemas"
    / "field-host-contained-install-evidence.schema.json"
)
CONTRACT_PATH = (
    ROOT
    / "distribution"
    / "editions"
    / "field"
    / "host-contained-install-validation.v1.json"
)
SNAPSHOT_TOOL_PATH = (
    ROOT / "distribution" / "tools" / "capture_field_host_snapshot.ps1"
)
PREVIOUS_EVIDENCE = (
    ROOT / "artifacts" / "test-runs" / "field-install-acceptance-readiness-0f86ba8"
)
CURRENT_EVIDENCE = (
    ROOT / "artifacts" / "test-runs" / "field-host-contained-readiness-8a767e0"
)

SPEC = importlib.util.spec_from_file_location("field_host_contained_readiness_tests", TOOL_PATH)
assert SPEC and SPEC.loader
host_readiness: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = host_readiness
SPEC.loader.exec_module(host_readiness)


class FieldHostContainedReadinessTests(unittest.TestCase):
    def contract(self) -> dict[str, object]:
        return host_readiness.load_json(CONTRACT_PATH)

    def digest(self, exists: bool) -> dict[str, object]:
        return {
            "exists": exists,
            "fileCount": 1 if exists else 0,
            "bytes": 1 if exists else 0,
            "sha256": "a" * 64 if exists else None,
        }

    def registry(self, exists: bool, values: dict[str, object] | None = None) -> dict[str, object]:
        return {"exists": exists, "values": values or {}}

    def shortcut(self, exists: bool) -> dict[str, object]:
        return {
            "exists": exists,
            "target": r"C:\fixture\drone-dream-desktop.exe" if exists else None,
            "sha256": "b" * 64 if exists else None,
        }

    def snapshot(self) -> dict[str, object]:
        path = lambda exists: {"path": r"C:\fixture", "digest": self.digest(exists)}
        return {
            "schemaVersion": 1,
            "kind": "dronedream-field-host-contained-host-snapshot",
            "capturedAtUtc": "2026-08-06T00:00:00Z",
            "host": {
                "computerName": "fixture",
                "userName": "fixture",
                "os": "Windows 11",
                "build": "10.0.26200.0",
            },
            "paths": {
                "universalInstall": path(True),
                "labDefaultInstall": path(False),
                "fieldDefaultInstall": path(False),
                "ownedRoot": path(False),
                "sharedHandoff": {
                    **path(True),
                    "controls": {
                        "receipt": {"exists": False, "bytes": None, "sha256": None},
                        "terminal": {"exists": False, "bytes": None, "sha256": None},
                        "quiesce": {"exists": True, "bytes": 1, "sha256": "c" * 64},
                        "legacyLock": {"exists": True, "bytes": 1, "sha256": "d" * 64},
                    },
                },
                "fieldBundleRoaming": path(False),
                "fieldBundleLocal": path(False),
            },
            "registry": {
                "universalUninstall": self.registry(True, {"DisplayName": "DroneDream"}),
                "labUninstall": self.registry(False),
                "fieldUninstall": self.registry(False),
                "fieldProduct": self.registry(False),
                "fieldAutorun": self.registry(True),
            },
            "shortcuts": {
                "universalStartMenu": self.shortcut(True),
                "universalDesktop": self.shortcut(True),
                "labStartMenu": self.shortcut(False),
                "labDesktop": self.shortcut(False),
                "fieldStartMenu": self.shortcut(False),
                "fieldDesktop": self.shortcut(False),
            },
            "runtime": {"root": r"E:\DroneDream", "exists": True, "topLevel": []},
            "webView2": {
                "healthy": True,
                "registryKey": "fixture",
                "version": "151.0.0.0",
                "binary": r"C:\fixture\msedgewebview2.exe",
                "binarySha256": "e" * 64,
            },
            "universalRuntimeStatus": {
                "operation": {"available": True, "exitCode": 0},
                "handoff": {"available": True, "exitCode": 0},
            },
            "processes": [],
        }

    def plan(self, snapshot: dict[str, object] | None = None) -> dict[str, object]:
        return host_readiness.create_plan(
            contract=self.contract(),
            snapshot=snapshot or self.snapshot(),
            evidence_head="f" * 40,
            artifact_absolute_path=r"C:\evidence\DroneDream-Field-1.0.0.exe",
            snapshot_sha256="1" * 64,
        )

    def test_contract_freezes_unique_universal_lab_and_field_identities(self) -> None:
        contract = host_readiness.validate_contract(self.contract())
        identities = contract["productIdentities"]
        for key in (
            "productName",
            "bundleId",
            "defaultInstallRoot",
            "uninstallRegistryKey",
            "manufacturerRegistryKey",
            "startMenuShortcut",
            "desktopShortcut",
        ):
            values = [item[key].casefold() for item in identities]
            self.assertEqual(len(values), len(set(values)), key)
        self.assertEqual(identities[2]["productName"], "DroneDream · FIELD")
        self.assertEqual(identities[2]["bundleId"], "io.dronedream.desktop.field")

    def test_source_audit_enumerates_writes_and_absent_system_surfaces(self) -> None:
        audit = host_readiness.audit_source(self.contract())
        self.assertTrue(audit["passed"], audit["checks"])
        checks = {item["checkId"]: item["passed"] for item in audit["checks"]}
        self.assertTrue(checks["nsis-product-scoped-writes"])
        self.assertTrue(checks["no-service-task-autorun-create"])
        self.assertTrue(checks["shared-handoff-identified"])
        self.assertTrue(checks["field-ui-no-device-api"])

    def test_requestable_plan_preserves_vm_evidence_and_claims_no_vm_isolation(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["state"], "yellow-host-contained-requestable")
        self.assertFalse(plan["environment"]["claimsVmLevelIsolation"])
        self.assertEqual(plan["previousVmEvidence"]["decision"], "deny-before-yellow")
        self.assertFalse(plan["authorization"]["executionPerformed"])
        self.assertFalse(plan["websiteGate"]["websiteReady"])
        self.assertEqual(plan["safetyBoundary"]["validatedHardwarePackCount"], 0)
        receipt = host_readiness.create_readiness_receipt(plan)
        self.assertEqual(receipt["decision"], "request-yellow-host-contained")
        self.assertFalse(receipt["executionPerformed"])

    def test_preexisting_field_state_and_shared_busy_state_fail_closed(self) -> None:
        snapshot = self.snapshot()
        snapshot["paths"]["fieldDefaultInstall"]["digest"] = self.digest(True)
        snapshot["registry"]["fieldUninstall"] = self.registry(True)
        snapshot["shortcuts"]["fieldDesktop"] = self.shortcut(True)
        snapshot["universalRuntimeStatus"]["operation"]["exitCode"] = 75
        plan = self.plan(snapshot)
        self.assertEqual(plan["state"], "blocked")
        self.assertIn("field.host.preexisting-path:fieldDefaultInstall", plan["blockers"])
        self.assertIn("field.host.preexisting-registry:fieldUninstall", plan["blockers"])
        self.assertIn("field.host.preexisting-shortcut:fieldDesktop", plan["blockers"])
        self.assertIn("field.host.shared-runtime-operation-not-idle", plan["blockers"])

    def test_unhealthy_webview_cannot_fall_through_to_shared_repair(self) -> None:
        snapshot = self.snapshot()
        snapshot["webView2"]["healthy"] = False
        plan = self.plan(snapshot)
        self.assertEqual(plan["state"], "blocked")
        self.assertIn("field.host.webview2-not-healthy-repair-forbidden", plan["blockers"])
        self.assertFalse(plan["preconditions"]["webView2RepairAllowed"])

    def test_invocation_network_hardware_and_rebuild_budgets_are_fail_closed(self) -> None:
        contract = self.contract()
        self.assertEqual(
            contract["invocationBudget"],
            {
                "installerExe": 2,
                "uninstaller": 1,
                "applicationLaunch": 2,
                "rebuild": 0,
                "networkRequest": 0,
                "deviceEnumeration": 0,
                "hardwareAction": 0,
                "simulation": 0,
            },
        )
        self.assertEqual(contract["processEnvironment"]["HTTP_PROXY"], "http://127.0.0.1:9")
        self.assertFalse(contract["preconditions"]["hardwareAndDeviceAccessAllowed"])

    def test_old_vm_evidence_is_byte_preserved(self) -> None:
        self.assertEqual(
            host_readiness.file_sha256(PREVIOUS_EVIDENCE / "plan.json"),
            host_readiness.PREVIOUS_VM_PLAN_SHA256,
        )
        self.assertEqual(
            host_readiness.file_sha256(PREVIOUS_EVIDENCE / "green-readiness-receipt.json"),
            host_readiness.PREVIOUS_VM_RECEIPT_SHA256,
        )

    def test_current_evidence_binds_tool_schema_contract_snapshot_and_artifact(self) -> None:
        plan = host_readiness.load_json(CURRENT_EVIDENCE / "plan.json")
        receipt = host_readiness.load_json(CURRENT_EVIDENCE / "green-readiness-receipt.json")
        host_readiness.validate_plan(plan)
        self.assertEqual(plan["state"], "yellow-host-contained-requestable")
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["artifact"]["sha256"], host_readiness.ARTIFACT_SHA256)
        self.assertEqual(plan["source"]["toolSha256"], host_readiness.file_sha256(TOOL_PATH))
        self.assertEqual(plan["source"]["schemaSha256"], host_readiness.file_sha256(SCHEMA_PATH))
        self.assertEqual(plan["source"]["contractSha256"], host_readiness.file_sha256(CONTRACT_PATH))
        self.assertEqual(
            plan["source"]["hostSnapshotSha256"],
            host_readiness.file_sha256(CURRENT_EVIDENCE / "host-snapshot.json"),
        )
        self.assertEqual(receipt["planSha256"], plan["planSha256"])
        self.assertEqual(receipt["decision"], "request-yellow-host-contained")
        self.assertFalse(receipt["executionPerformed"])

    def test_snapshot_tool_is_read_only_outside_its_explicit_output(self) -> None:
        source = SNAPSHOT_TOOL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("Set-ItemProperty", source)
        self.assertNotIn("New-ItemProperty", source)
        self.assertNotIn("Start-Service", source)
        self.assertIn("--runtime-operation-status", source)
        self.assertIn("--installer-handoff-status", source)

    def test_schema_is_closed_and_covers_plan_readiness_and_execution(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        for name in ("plan", "readinessReceipt", "executionReceipt"):
            self.assertFalse(schema["$defs"][name]["additionalProperties"])
        self.assertEqual(
            schema["$defs"]["artifact"]["properties"]["sha256"]["const"],
            host_readiness.ARTIFACT_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
