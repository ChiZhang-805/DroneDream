from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / "distribution/sim/lifecycle/red-app-only-lifecycle-plan.v1.json"
RECEIPT_PATH = (
    ROOT
    / "distribution/sim/lifecycle/red-f23987ba-app-only-readiness.v1.json"
)
TOOL_PATH = ROOT / "distribution/sim/tools/sim_red_lifecycle_readiness.py"

SPEC = importlib.util.spec_from_file_location("sim_red_lifecycle_readiness", TOOL_PATH)
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SimRedLifecycleReadinessTests(unittest.TestCase):
    def test_exact_plan_and_receipt_validate_without_execution(self) -> None:
        plan = readiness.validate_plan(load(PLAN_PATH), ROOT)
        receipt = readiness.validate_receipt(
            load(RECEIPT_PATH), plan, PLAN_PATH.relative_to(ROOT)
        )
        self.assertEqual(receipt["installationCount"], 0)
        self.assertFalse(plan["authorization"]["redExecutionAuthorizedByThisRecord"])

    def test_stale_display_name_uninstall_key_is_rejected(self) -> None:
        plan = load(PLAN_PATH)
        plan["identity"]["uninstallRegistryKey"] = (
            "HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/"
            "DroneDream · SIM"
        )
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "compiled SIM identity"):
            readiness.validate_plan(plan, ROOT)

    def test_stale_main_binary_is_rejected(self) -> None:
        plan = load(PLAN_PATH)
        plan["identity"]["mainBinaryName"] = "DroneDream.exe"
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "compiled SIM identity"):
            readiness.validate_plan(plan, ROOT)

    def test_expected_and_compiled_identity_mismatch_is_rejected(self) -> None:
        plan = load(PLAN_PATH)
        plan["expectedVsArtifact"]["mainBinaryName"][
            "artifactCompiledActual"
        ] = "DroneDream.exe"
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "identity mismatch"):
            readiness.validate_plan(plan, ROOT)

    def test_cross_edition_owned_surface_is_rejected(self) -> None:
        plan = load(PLAN_PATH)
        plan["ownedWriteSurface"]["paths"].append("%LOCALAPPDATA%/DroneDream-Lab")
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "owned/protected overlap"):
            readiness.validate_plan(plan, ROOT)

    def test_manifest_alias_variance_cannot_be_hidden(self) -> None:
        plan = load(PLAN_PATH)
        plan["manifestComparison"]["artifactBundleIdentifier"] = (
            "io.dronedream.desktop.sim"
        )
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "manifest comparison"):
            readiness.validate_plan(plan, ROOT)

    def test_build_runtime_or_hardware_count_is_rejected(self) -> None:
        for key in ("artifactBuilds", "runtimeStarts", "hardwareActions"):
            with self.subTest(key=key):
                plan = load(PLAN_PATH)
                plan["exactCounts"][key] = 1
                with self.assertRaisesRegex(readiness.SimRedReadinessError, "exact RED counts"):
                    readiness.validate_plan(plan, ROOT)

    def test_receipt_execution_claim_is_rejected(self) -> None:
        plan = readiness.validate_plan(load(PLAN_PATH), ROOT)
        receipt = deepcopy(load(RECEIPT_PATH))
        receipt["executedExactCounts"]["freshInstallerInvocations"] = 1
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "execution count"):
            readiness.validate_receipt(
                receipt, plan, PLAN_PATH.relative_to(ROOT)
            )

    def test_red_authorization_cannot_be_self_granted(self) -> None:
        plan = load(PLAN_PATH)
        plan["authorization"]["redExecutionAuthorizedByThisRecord"] = True
        with self.assertRaisesRegex(readiness.SimRedReadinessError, "authorization"):
            readiness.validate_plan(plan, ROOT)


if __name__ == "__main__":
    unittest.main()
