from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = (
    ROOT / "distribution" / "sim" / "lifecycle" / "yellow-execution-plan.v1.json"
)
TOOL_PATH = ROOT / "distribution" / "sim" / "tools" / "sim_yellow_lifecycle.py"

SPEC = importlib.util.spec_from_file_location("sim_yellow_lifecycle", TOOL_PATH)
assert SPEC and SPEC.loader
sim_yellow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sim_yellow
SPEC.loader.exec_module(sim_yellow)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class SimYellowLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = sim_yellow.validate_execution_plan(load_json(PLAN_PATH), repo_root=ROOT)

    def validate(self, document: object) -> dict[str, Any]:
        return sim_yellow.validate_execution_plan(document, repo_root=ROOT)

    def inventory(self, *, stage: str = "yellow-3") -> dict[str, Any]:
        if stage == "yellow-2":
            run_id = "sim-y2-20260805T120000Z-1234abcd"
            staging = self.contract["staging"]["yellow2"]
        else:
            run_id = "sim-y3-20260805T120000Z-1234abcd"
            staging = self.contract["staging"]["yellow3"]
        run_root = staging["runRootTemplate"].replace("{runId}", run_id)
        entries: list[dict[str, Any]] = [
            {
                "kind": "run-root",
                "path": run_root,
                "observed": False,
                "sha256": None,
                "expectedTarget": None,
                "expectedRegistryValues": None,
                "disposition": "candidate-after-reverification",
            },
            {
                "kind": "file",
                "path": f"{run_root}/evidence/planned-receipt.json",
                "observed": False,
                "sha256": None,
                "expectedTarget": None,
                "expectedRegistryValues": None,
                "disposition": "preserve",
            },
        ]
        if stage == "yellow-3":
            install_root = staging["installRootTemplate"].replace("{runId}", run_id)
            shortcut_target = self.contract["ownedResiduePolicy"][
                "expectedShortcutTargetTemplate"
            ].replace("{runId}", run_id)
            entries.extend(
                [
                    {
                        "kind": "install-root",
                        "path": install_root,
                        "observed": False,
                        "sha256": None,
                        "expectedTarget": None,
                        "expectedRegistryValues": None,
                        "disposition": "candidate-after-reverification",
                    },
                    {
                        "kind": "shortcut",
                        "path": (
                            "%APPDATA%/Microsoft/Windows/Start Menu/Programs/"
                            "DroneDream · SIM.lnk"
                        ),
                        "observed": False,
                        "sha256": None,
                        "expectedTarget": shortcut_target,
                        "expectedRegistryValues": None,
                        "disposition": "candidate-after-reverification",
                    },
                    {
                        "kind": "registry-key",
                        "path": (
                            "HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/"
                            "DroneDream · SIM"
                        ),
                        "observed": False,
                        "sha256": None,
                        "expectedTarget": None,
                        "expectedRegistryValues": {
                            "DisplayName": "DroneDream · SIM",
                            "DisplayVersion": "1.0.0",
                            "InstallLocation": install_root,
                            "UninstallString": f"{install_root}/uninstall.exe",
                        },
                        "disposition": "candidate-after-reverification",
                    },
                ]
            )
        return {
            "schemaVersion": 1,
            "kind": "dronedream-sim-owned-residue-inventory",
            "inventoryVersion": "1.0.0",
            "editionId": "sim",
            "stage": stage,
            "runId": run_id,
            "runRoot": run_root,
            "sourceReceiptSha256": "a" * 64,
            "entries": entries,
            "protectedObservations": {
                "historicalEvidenceTouched": False,
                "cargoCacheDeleted": False,
                "runtimeRootTouched": False,
                "runtimeDistributionTouched": False,
                "webView2Removed": False,
            },
            "nonClaims": {
                "buildExecuted": False,
                "installerExecuted": False,
                "uninstallerExecuted": False,
                "rollbackExecuted": False,
            },
        }

    def test_plan_registers_six_visual_and_twelve_lifecycle_cases(self) -> None:
        self.assertEqual(len(self.contract["yellow1VisualBinding"]["requiredCaseIds"]), 6)
        self.assertEqual(len(self.contract["yellow3Matrix"]), 12)
        self.assertEqual(
            len(self.contract["ownedResiduePolicy"]["expectedYellow2Entries"]), 4
        )
        self.assertEqual(
            len(self.contract["ownedResiduePolicy"]["expectedYellow3Entries"]), 9
        )
        self.assertTrue(
            all(case["status"] == "planned-not-executed" for case in self.contract["yellow3Matrix"])
        )
        self.assertFalse(self.contract["authorization"]["yellow1Approved"])
        self.assertFalse(self.contract["authorization"]["yellow2Approved"])
        self.assertFalse(self.contract["authorization"]["yellow3Approved"])

    def test_stage_plans_expand_only_owned_run_paths_without_execution(self) -> None:
        yellow2 = sim_yellow.create_stage_plan(
            self.contract,
            stage="yellow-2",
            run_id="sim-y2-20260805T120000Z-1234abcd",
        )
        self.assertIn("sim-y2-20260805T120000Z-1234abcd", yellow2["paths"]["runRootTemplate"])
        self.assertFalse(yellow2["executionAuthorized"])
        self.assertTrue(all(value is False for value in yellow2["nonClaims"].values()))

        yellow3 = sim_yellow.create_stage_plan(
            self.contract,
            stage="yellow-3",
            run_id="sim-y3-20260805T120000Z-1234abcd",
        )
        self.assertEqual(len(yellow3["yellow3Matrix"]), 12)
        self.assertFalse(yellow3["paths"]["runtimeStartAllowed"])

    def test_rejects_wrong_stage_run_id(self) -> None:
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "runId"):
            sim_yellow.create_stage_plan(
                self.contract,
                stage="yellow-3",
                run_id="sim-y2-20260805T120000Z-1234abcd",
            )

    def test_rejects_authorization_cache_cleanup_or_runtime_start_claims(self) -> None:
        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["authorization"]["yellow2Approved"] = True
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "authorization"):
            self.validate(invalid)

        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["staging"]["yellow2"]["cleanupCargoTargetAllowed"] = True
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "YELLOW-2"):
            self.validate(invalid)

        for key in ("runtimeStartAllowed", "px4StartAllowed", "gazeboStartAllowed"):
            with self.subTest(key=key):
                invalid = deepcopy(load_json(PLAN_PATH))
                invalid["staging"]["yellow3"][key] = True
                with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "YELLOW-3"):
                    self.validate(invalid)

    def test_rejects_visual_contract_hash_or_matrix_status_drift(self) -> None:
        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["yellow1VisualBinding"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "visual contract"):
            self.validate(invalid)

        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["yellow3Matrix"][0]["status"] = "passed"
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "matrix case"):
            self.validate(invalid)

    def test_owned_inventory_renders_non_executing_rollback_plan(self) -> None:
        inventory = self.inventory()
        validated, operations = sim_yellow.validate_owned_inventory(
            inventory, contract=self.contract
        )
        self.assertEqual(validated["stage"], "yellow-3")
        self.assertTrue(operations)
        self.assertTrue(all(operation["executed"] is False for operation in operations))
        self.assertIn("preserve", {operation["action"] for operation in operations})

    def test_rejects_protected_evidence_shortcut_or_registry_overreach(self) -> None:
        invalid = self.inventory(stage="yellow-2")
        invalid["entries"][1]["path"] = (
            "Z:/DroneDream-worktrees/aurora-20260728/artifacts/test-runs/evidence.json"
        )
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "protected|historical"):
            sim_yellow.validate_owned_inventory(invalid, contract=self.contract)

        invalid = self.inventory()
        shortcut = next(entry for entry in invalid["entries"] if entry["kind"] == "shortcut")
        shortcut["expectedTarget"] = "%LOCALAPPDATA%/Programs/DroneDream-LAB/app.exe"
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "shortcut"):
            sim_yellow.validate_owned_inventory(invalid, contract=self.contract)

        invalid = self.inventory()
        registry = next(entry for entry in invalid["entries"] if entry["kind"] == "registry-key")
        registry["path"] = "HKCU/Software/DroneDream/DroneDream · FIELD"
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "registry"):
            sim_yellow.validate_owned_inventory(invalid, contract=self.contract)


if __name__ == "__main__":
    unittest.main()
