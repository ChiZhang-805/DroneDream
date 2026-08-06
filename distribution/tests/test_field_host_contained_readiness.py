from __future__ import annotations

import importlib.util
import json
import subprocess
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
EXECUTOR_PATH = (
    ROOT / "distribution" / "tools" / "execute_field_host_contained_acceptance.ps1"
)
PHASE_SERIALIZATION_FIXTURE = (
    ROOT / "distribution" / "tools" / "test_field_phase_evidence_serialization.ps1"
)
PREVIOUS_EVIDENCE = (
    ROOT / "artifacts" / "test-runs" / "field-install-acceptance-readiness-0f86ba8"
)
LAST_REQUESTABLE_EVIDENCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-contained-readiness-6afa14a-wait"
)
CURRENT_BLOCKED_EVIDENCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-contained-readiness-18ccfa9-blocked"
)
FIRST_PREFLIGHT_FAILURE_EVIDENCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-contained-preflight-failure-5d62660"
)
SECOND_PREFLIGHT_FAILURE_EVIDENCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-contained-preflight-failure-90a2a3c"
)
EXECUTION_FAILURE_EVIDENCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-contained-execution-failure-452eed9"
)
REPEATED_EXECUTION_FAILURE_EVIDENCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-contained-execution-failure-fb741b0"
)
PHASE_SERIALIZATION_CLEARANCE = (
    ROOT
    / "artifacts"
    / "test-runs"
    / "field-host-phase-serialization-clearance-d5d38cd"
    / "clearance-receipt.json"
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
                "simDefaultInstall": path(False),
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
                "simUninstall": self.registry(False),
                "labUninstall": self.registry(False),
                "fieldUninstall": self.registry(False),
                "fieldProduct": self.registry(False),
                "fieldAutorun": self.registry(True),
            },
            "shortcuts": {
                "universalStartMenu": self.shortcut(True),
                "universalDesktop": self.shortcut(True),
                "simStartMenu": self.shortcut(False),
                "simDesktop": self.shortcut(False),
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
        self.assertEqual([item["editionId"] for item in identities], ["universal", "sim", "lab", "field"])
        self.assertEqual(identities[-1]["productName"], "DroneDream-Field")
        self.assertEqual(identities[-1]["bundleId"], "io.dronedream.desktop.field")
        self.assertEqual(
            contract["fieldNamespaces"]["windowAndDisplayName"],
            "DroneDream · FIELD",
        )
        self.assertEqual(contract["fieldNamespaces"]["appUserModelId"], "io.dronedream.desktop.field")
        self.assertEqual(
            contract["fieldNamespaces"]["updaterEndpoint"],
            "https://github.com/ChiZhang-805/DroneDream/releases/download/"
            "desktop-field-channel/latest-field.json",
        )
        self.assertEqual(contract["fieldNamespaces"]["enginePackProfileId"], "field-lightweight")

    def test_source_audit_enumerates_writes_and_absent_system_surfaces(self) -> None:
        audit = host_readiness.audit_source(self.contract())
        self.assertTrue(audit["passed"], audit["checks"])
        checks = {item["checkId"]: item["passed"] for item in audit["checks"]}
        self.assertTrue(checks["nsis-product-scoped-writes"])
        self.assertTrue(checks["no-service-task-autorun-create"])
        self.assertTrue(checks["shared-handoff-identified"])
        self.assertTrue(checks["field-ui-no-device-api"])
        self.assertTrue(checks["field-updater-endpoint"])
        self.assertTrue(checks["field-profile-and-icon"])
        self.assertTrue(checks["executor-owned-environment"])
        self.assertTrue(checks["executor-budget-and-rollback"])

    def test_requestable_plan_preserves_vm_evidence_and_claims_no_vm_isolation(self) -> None:
        contract = self.contract()
        contract["knownExecutionBlockers"] = []
        plan = host_readiness.create_plan(
            contract=contract,
            snapshot=self.snapshot(),
            evidence_head="f" * 40,
            artifact_absolute_path=r"C:\evidence\DroneDream-Field-1.0.0.exe",
            snapshot_sha256="1" * 64,
        )
        self.assertEqual(plan["state"], "yellow-host-contained-requestable")
        self.assertFalse(plan["environment"]["claimsVmLevelIsolation"])
        self.assertEqual(plan["previousVmEvidence"]["decision"], "deny-before-yellow")
        self.assertFalse(plan["authorization"]["executionPerformed"])
        self.assertFalse(plan["websiteGate"]["websiteReady"])
        self.assertEqual(plan["safetyBoundary"]["validatedHardwarePackCount"], 0)
        receipt = host_readiness.create_readiness_receipt(plan)
        self.assertEqual(receipt["decision"], "request-yellow-host-contained")
        self.assertFalse(receipt["executionPerformed"])

    def test_superseded_artifact_denies_another_yellow_attempt(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["state"], "blocked")
        self.assertIn(
            "field.host.frozen-artifact-superseded-by-brand-auth-contract",
            plan["blockers"],
        )
        self.assertNotIn("field.host.executor-post-install-runaway", plan["blockers"])
        receipt = host_readiness.create_readiness_receipt(plan)
        self.assertEqual(receipt["decision"], "deny")

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
        self.assertIn(
            "--disable-background-networking",
            contract["processEnvironment"]["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"],
        )
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

    def test_last_requestable_evidence_is_preserved_as_historical(self) -> None:
        plan = host_readiness.load_json(LAST_REQUESTABLE_EVIDENCE / "plan.json")
        receipt = host_readiness.load_json(LAST_REQUESTABLE_EVIDENCE / "green-readiness-receipt.json")
        host_readiness.validate_plan(plan)
        self.assertEqual(plan["state"], "yellow-host-contained-requestable")
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["artifact"]["sha256"], host_readiness.ARTIFACT_SHA256)
        self.assertNotEqual(
            plan["fieldNamespaces"],
            host_readiness.validate_contract(host_readiness.load_json(CONTRACT_PATH))[
                "fieldNamespaces"
            ],
        )
        self.assertEqual(
            plan["source"]["toolSha256"],
            "4cbb192a6be11e6fba8dc09fc6d8a898a6f4aa57483bc6be4bbf509bb7964e41",
        )
        self.assertEqual(
            plan["source"]["schemaSha256"],
            "55093c74b1e64690f4b1870ce7e88728b3f563b6bc5bc426046b63644f7265b1",
        )
        self.assertNotEqual(
            plan["source"]["schemaSha256"],
            host_readiness.file_sha256(SCHEMA_PATH),
        )
        self.assertEqual(
            plan["source"]["contractSha256"],
            "6eb54675df60796c36bd4e8676e93f352c40e85d5d672435123847aa66299442",
        )
        self.assertEqual(
            plan["source"]["hostSnapshotSha256"],
            host_readiness.file_sha256(LAST_REQUESTABLE_EVIDENCE / "host-snapshot.json"),
        )
        self.assertEqual(receipt["planSha256"], plan["planSha256"])
        self.assertEqual(receipt["decision"], "request-yellow-host-contained")
        self.assertFalse(receipt["executionPerformed"])

    def test_current_exact_evidence_denies_dynamic_retry(self) -> None:
        plan = host_readiness.load_json(CURRENT_BLOCKED_EVIDENCE / "plan.json")
        receipt = host_readiness.load_json(
            CURRENT_BLOCKED_EVIDENCE / "green-readiness-receipt.json"
        )
        host_readiness.validate_plan(plan)
        self.assertEqual(plan["state"], "blocked")
        self.assertEqual(plan["blockers"], ["field.host.executor-post-install-runaway"])
        self.assertEqual(plan["source"]["evidenceHead"], "18ccfa997a05665a7bea6cb95da0d416da9c86bc")
        self.assertEqual(
            plan["source"]["toolSha256"],
            "d941777a57b16356abb5608bce5bfa562824c02cb632ea58a0aca93576480a95",
        )
        self.assertEqual(
            plan["source"]["contractSha256"],
            "9723160032095835582c56fbd03d855f085f952a00418c0a359b8ab27abb850d",
        )
        self.assertNotEqual(plan["source"]["toolSha256"], host_readiness.file_sha256(TOOL_PATH))
        self.assertNotEqual(
            plan["source"]["contractSha256"],
            host_readiness.file_sha256(CONTRACT_PATH),
        )
        self.assertEqual(
            plan["source"]["hostSnapshotSha256"],
            host_readiness.file_sha256(CURRENT_BLOCKED_EVIDENCE / "host-snapshot.json"),
        )
        self.assertEqual(receipt["decision"], "deny")
        self.assertFalse(receipt["executionPerformed"])

    def test_first_yellow_attempt_is_preserved_as_preflight_only_failure(self) -> None:
        failure = host_readiness.load_json(
            FIRST_PREFLIGHT_FAILURE_EVIDENCE / "preflight-failure-receipt.json"
        )
        self.assertEqual(failure["result"], "fail-before-owned-write")
        self.assertEqual(failure["attempt"]["sourceHead"], "5d6266088b457f5c5dfe82e8d6f7be1df2b7831f")
        self.assertEqual(failure["attempt"]["errorCode"], "field.host.snapshot.utf8-codepage-parse")
        self.assertFalse(failure["attempt"]["productFailure"])
        self.assertEqual(
            failure["remediation"]["fixedExecutorCommit"],
            "d54c66e2e9e34184b9aa230e8740ac4f05bc9d7a",
        )
        self.assertEqual(set(failure["executionCounts"].values()), {0})
        self.assertFalse(any(failure["postFailureState"].values()))
        self.assertFalse(failure["releaseState"]["releaseReady"])
        self.assertFalse(failure["releaseState"]["websiteReady"])

    def test_second_yellow_attempt_is_preserved_as_preflight_only_failure(self) -> None:
        failure = host_readiness.load_json(
            SECOND_PREFLIGHT_FAILURE_EVIDENCE / "preflight-failure-receipt.json"
        )
        self.assertEqual(failure["result"], "fail-before-owned-write")
        self.assertEqual(failure["attempt"]["sourceHead"], "90a2a3ce1edfa6092579a0ded7f36ffa49f7d384")
        self.assertEqual(failure["attempt"]["errorCode"], "field.host.plan.empty-array-powershell51")
        self.assertFalse(failure["attempt"]["productFailure"])
        self.assertEqual(
            failure["remediation"]["fixedExecutorCommit"],
            "07c9262a132b9d53167952df69f608637297f8b2",
        )
        self.assertEqual(set(failure["executionCounts"].values()), {0})
        self.assertFalse(any(failure["postFailureState"].values()))

    def test_resource_abort_preserves_complete_owned_rollback(self) -> None:
        failure = host_readiness.load_json(
            EXECUTION_FAILURE_EVIDENCE / "execution-failure-receipt.json"
        )
        self.assertEqual(failure["result"], "fail-resource-abort-with-complete-rollback")
        self.assertTrue(failure["attempt"]["forcedExecutorTermination"])
        self.assertFalse(failure["attempt"]["productFailure"])
        self.assertEqual(failure["executionCounts"]["installerExe"], 1)
        self.assertEqual(failure["executionCounts"]["uninstaller"], 1)
        self.assertEqual(failure["executionCounts"]["applicationLaunch"], 0)
        self.assertTrue(failure["rollback"]["protectedStateMatched"])
        self.assertEqual(failure["rollback"]["protectedChecksPassed"], 16)
        self.assertEqual(failure["rollback"]["protectedChecksTotal"], 16)
        self.assertTrue(failure["rollback"]["ownedRootAbsent"])
        self.assertFalse(failure["releaseState"]["releaseReady"])

    def test_repeated_runaway_blocks_retry_after_complete_rollback(self) -> None:
        failure = host_readiness.load_json(
            REPEATED_EXECUTION_FAILURE_EVIDENCE / "execution-failure-receipt.json"
        )
        self.assertEqual(
            failure["result"],
            "fail-repeated-post-install-runaway-with-complete-rollback",
        )
        self.assertEqual(failure["executionGate"]["status"], "open")
        self.assertFalse(failure["executionGate"]["retryAllowed"])
        self.assertTrue(failure["rollback"]["protectedStateMatched"])
        self.assertEqual(failure["rollback"]["protectedChecksPassed"], 16)
        self.assertTrue(failure["rollback"]["ownedRootAbsent"])

    def test_snapshot_tool_is_read_only_outside_its_explicit_output(self) -> None:
        source = SNAPSHOT_TOOL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("Set-ItemProperty", source)
        self.assertNotIn("New-ItemProperty", source)
        self.assertNotIn("Start-Service", source)
        self.assertIn("--runtime-operation-status", source)
        self.assertIn("--installer-handoff-status", source)

    def test_executor_has_exact_budget_cleanup_and_protected_state_gates(self) -> None:
        source = EXECUTOR_PATH.read_text(encoding="utf-8")
        self.assertIn("installer invocation budget exhausted", source)
        self.assertIn("application launch budget exhausted", source)
        self.assertIn("Assert-ProtectedState", source)
        self.assertIn("Remove-ProvenNewPath", source)
        self.assertIn("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", source)
        self.assertIn("System.AppUserModel.ID", source)
        self.assertIn("$FieldIconSha256", source)
        self.assertIn("[IO.File]::ReadAllText", source)
        self.assertNotIn("text = Get-Content", source)
        self.assertIn("@($Snapshot.processes).Count", source)
        self.assertIn("@($plan.blockers).Count", source)
        self.assertIn("@(git status --porcelain).Count", source)
        self.assertIn("Invoke-BoundedOwnedProcess", source)
        self.assertIn("WaitForExit(120000)", source)
        self.assertIn("refusing unapproved process path", source)
        self.assertNotIn("Get-Content -LiteralPath $PlanPath -Raw", source)
        self.assertNotIn("$plan.blockers.Count", source)
        self.assertNotIn("$Snapshot.processes.Count", source)
        self.assertNotIn("-Wait -PassThru", source)
        self.assertNotIn("New-NetFirewallRule", source)
        self.assertNotIn("Start-Service", source)
        self.assertNotIn("Get-PnpDevice", source)

    def test_phase_evidence_serializes_plain_text_with_bounded_memory(self) -> None:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PHASE_SERIALIZATION_FIXTURE),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        evidence = json.loads(result.stdout.lstrip("\ufeff"))
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["textType"], "System.String")
        self.assertFalse(evidence["hasPsPath"])
        self.assertLess(evidence["jsonLength"], 4096)
        self.assertLess(evidence["privateMemoryGrowthBytes"], 16 * 1024 * 1024)
        self.assertEqual(evidence["installerInvocations"], 0)
        self.assertEqual(evidence["deviceEnumerations"], 0)
        self.assertEqual(evidence["networkRequests"], 0)

    def test_phase_serialization_clearance_preserves_history_and_denies_release(self) -> None:
        clearance = host_readiness.load_json(PHASE_SERIALIZATION_CLEARANCE)
        self.assertEqual(
            clearance["rootCause"]["clearedBlockerId"],
            "field.host.executor-post-install-runaway",
        )
        self.assertTrue(clearance["offlineFixture"]["passed"])
        self.assertEqual(clearance["offlineFixture"]["installerInvocations"], 0)
        self.assertEqual(clearance["offlineFixture"]["deviceEnumerations"], 0)
        self.assertEqual(clearance["offlineFixture"]["networkRequests"], 0)
        self.assertFalse(clearance["clearance"]["yellowRetryPerformed"])
        self.assertFalse(clearance["clearance"]["dynamicLifecycleAccepted"])
        self.assertEqual(
            clearance["remainingGate"]["blockerId"],
            "field.host.frozen-artifact-superseded-by-brand-auth-contract",
        )
        self.assertFalse(clearance["remainingGate"]["releaseReady"])
        self.assertFalse(clearance["remainingGate"]["websiteReady"])
        for historical in clearance["historicalEvidence"]:
            path = ROOT / historical["path"]
            self.assertEqual(host_readiness.file_sha256(path), historical["sha256"])

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
