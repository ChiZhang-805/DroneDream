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
WEBSITE_OBSERVATION_PATH = (
    ROOT
    / "distribution"
    / "sim"
    / "quality"
    / "website-availability-observation.v1.json"
)
TOOL_PATH = ROOT / "distribution" / "sim" / "tools" / "sim_yellow_lifecycle.py"
YELLOW1_RECORD_PATH = (
    ROOT / "distribution" / "sim" / "frontend" / "yellow-1-evidence-record.v1.json"
)
YELLOW1_TOOL_PATH = (
    ROOT / "distribution" / "sim" / "tools" / "sim_yellow1_evidence.py"
)
YELLOW1_RUN_ROOT = (
    ROOT
    / "frontend"
    / "artifacts"
    / "test-runs"
    / "sim-yellow-1-20260805T141813Z-1af8952"
)

SPEC = importlib.util.spec_from_file_location("sim_yellow_lifecycle", TOOL_PATH)
assert SPEC and SPEC.loader
sim_yellow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sim_yellow
SPEC.loader.exec_module(sim_yellow)

YELLOW1_SPEC = importlib.util.spec_from_file_location(
    "sim_yellow1_evidence", YELLOW1_TOOL_PATH
)
assert YELLOW1_SPEC and YELLOW1_SPEC.loader
sim_yellow1 = importlib.util.module_from_spec(YELLOW1_SPEC)
sys.modules[YELLOW1_SPEC.name] = sim_yellow1
YELLOW1_SPEC.loader.exec_module(sim_yellow1)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class SimYellowLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = sim_yellow.validate_execution_plan(load_json(PLAN_PATH), repo_root=ROOT)

    def validate(self, document: object) -> dict[str, Any]:
        return sim_yellow.validate_execution_plan(document, repo_root=ROOT)

    def validate_observation(self, document: object) -> dict[str, Any]:
        return sim_yellow.validate_cross_line_test_observation(
            document, repo_root=ROOT
        )

    def validate_yellow1(
        self, document: object, *, require_local_artifacts: bool = False
    ) -> dict[str, Any]:
        return sim_yellow1.validate_yellow1_evidence_record(
            document,
            repo_root=ROOT,
            require_local_artifacts=require_local_artifacts,
        )

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
        self.assertTrue(self.contract["authorization"]["yellow1Approved"])
        self.assertFalse(self.contract["authorization"]["yellow2Approved"])
        self.assertFalse(self.contract["authorization"]["yellow3Approved"])
        asset_gate = self.contract["approvedEditionAssetGate"]
        self.assertEqual(
            asset_gate["requiredAssetRoles"],
            ["sim-mark-png", "sim-dot-lockup-png"],
        )
        self.assertTrue(asset_gate["applicationSourceWired"])
        self.assertTrue(asset_gate["installerDerivativeReady"])
        self.assertTrue(asset_gate["canonicalUniversalDonorIntegrated"])
        sync_gate = self.contract["canonicalSyncGate"]
        self.assertEqual(
            sync_gate["state"],
            "canonical-brand-adopted-path-limited",
        )
        self.assertEqual(
            sync_gate["recordedCommonCoreCommit"],
            "e374d3f8d96b1265fcdb06864208b676566e94d9",
        )
        self.assertFalse(sync_gate["brandDonorCommitIsCommonCore"])
        self.assertTrue(sync_gate["formalHandoffReceived"])
        self.assertTrue(sync_gate["installerIcoConsumed"])
        self.assertFalse(sync_gate["releaseAsset"])
        self.assertFalse(sync_gate["yellow2Ready"])
        self.assertFalse(
            self.contract["artifactGate"][
                "yellow2BlockedUntilInstallerDerivativeContract"
            ]
        )
        self.assertFalse(self.contract["artifactGate"]["yellow2StaticReady"])
        self.assertEqual(
            self.contract["buildEnvironment"],
            {
                "DRONEDREAM_DESKTOP_EDITION_ID": "sim",
                "DRONEDREAM_EDITION_PROFILE": "sim-only",
                "VITE_DRONEDREAM_EDITION": "sim",
                "DRONEDREAM_OAUTH_CLIENT_ID": "0c2ad943-a0cb-4a2f-9eda-eba44b7f58df",
                "oauthClientIdSource": "user-confirmed-public-client-id",
                "oauthClientIdSha256": (
                    "10598a5c1712b32e2bfe8d5cb4bf97f563ceb3a9eabb5846445e3ab593eac08f"
                ),
                "oauthTokenEndpointAuthMethod": "none",
                "oauthRedirectUri": (
                    "http://127.0.0.1:49211/desktop-auth/sim/callback"
                ),
                "singleProcessInjectionRequired": True,
                "providerNetworkUseAllowed": False,
                "secretReadAllowed": False,
            },
        )

    def test_stage_plans_expand_only_owned_run_paths_without_execution(self) -> None:
        yellow2 = sim_yellow.create_stage_plan(
            self.contract,
            stage="yellow-2",
            run_id="sim-y2-20260805T120000Z-1234abcd",
        )
        self.assertIn("sim-y2-20260805T120000Z-1234abcd", yellow2["paths"]["runRootTemplate"])
        self.assertFalse(yellow2["executionAuthorized"])
        self.assertTrue(all(value is False for value in yellow2["nonClaims"].values()))
        self.assertTrue(yellow2["approvedEditionAssetGate"]["installerDerivativeReady"])
        self.assertTrue(yellow2["canonicalSyncGate"]["formalHandoffReceived"])
        self.assertTrue(yellow2["canonicalSyncGate"]["installerIcoConsumed"])

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

    def test_rejects_public_oauth_build_input_drift(self) -> None:
        for key, value in (
            ("DRONEDREAM_OAUTH_CLIENT_ID", "dronedream-desktop-sim"),
            ("oauthClientIdSha256", "0" * 64),
            ("oauthTokenEndpointAuthMethod", "client_secret_post"),
            ("oauthRedirectUri", "http://127.0.0.1:49210/desktop-auth/sim/callback"),
            ("secretReadAllowed", True),
        ):
            with self.subTest(key=key):
                invalid = deepcopy(load_json(PLAN_PATH))
                invalid["buildEnvironment"][key] = value
                with self.assertRaisesRegex(
                    sim_yellow.SimYellowLifecycleError,
                    "build environment identity",
                ):
                    self.validate(invalid)

    def test_rejects_visual_contract_hash_or_matrix_status_drift(self) -> None:
        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["yellow1VisualBinding"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "visual contract"):
            self.validate(invalid)

        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["approvedEditionAssetGate"]["manifestSha256"] = "0" * 64
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "asset manifest SHA-256"
        ):
            self.validate(invalid)

        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["yellow3Matrix"][0]["status"] = "passed"
        with self.assertRaisesRegex(sim_yellow.SimYellowLifecycleError, "matrix case"):
            self.validate(invalid)

    def test_rejects_canonical_sync_rollback_or_release_overclaim(self) -> None:
        for key, value in (
            ("formalHandoffReceived", False),
            ("semanticIntegrationExecuted", False),
            ("canonicalBrandManifestConsumed", False),
            ("installerIcoConsumed", False),
            ("releaseAsset", True),
            ("yellow2Ready", True),
            ("brandDonorCommitIsCommonCore", True),
            ("adoptionReceiptSha256", "0" * 64),
        ):
            with self.subTest(key=key):
                invalid = deepcopy(load_json(PLAN_PATH))
                invalid["canonicalSyncGate"][key] = value
                with self.assertRaisesRegex(
                    sim_yellow.SimYellowLifecycleError, "overclaims readiness"
                ):
                    self.validate(invalid)

        invalid = deepcopy(load_json(PLAN_PATH))
        invalid["canonicalSyncGate"]["auditSha256"] = "0" * 64
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "overclaims readiness"
        ):
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

    def test_website_availability_failure_is_nonblocking_cross_line_observation(self) -> None:
        observation = self.validate_observation(load_json(WEBSITE_OBSERVATION_PATH))
        self.assertEqual(
            observation["ownershipClassification"]["classification"],
            "website-owned-newer-site-evolution-absent-from-sim-snapshot",
        )
        self.assertFalse(
            observation["ownershipClassification"]["blocksSimOwnedGates"]
        )
        self.assertEqual(
            observation["testObservation"]["simLocalOwnedGate"]["passed"], 13
        )
        self.assertEqual(
            observation["testObservation"]["websiteHandoffPublicSite"]["passed"],
            20,
        )
        self.assertFalse(
            observation["testObservation"]["websiteHandoffPublicSite"][
                "locallyReexecutedBySim"
            ]
        )

    def test_rejects_cross_line_blob_patch_or_source_relabel(self) -> None:
        invalid = deepcopy(load_json(WEBSITE_OBSERVATION_PATH))
        invalid["pathObservation"]["relevantPathEvidence"][0]["simBlob"] = "0" * 40
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "blob or patch evidence"
        ):
            self.validate_observation(invalid)

        invalid = deepcopy(load_json(WEBSITE_OBSERVATION_PATH))
        invalid["pathObservation"]["relevantPathEvidence"][1][
            "websiteSourceToEvidencePatch"
        ]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "blob or patch evidence"
        ):
            self.validate_observation(invalid)

        invalid = deepcopy(load_json(WEBSITE_OBSERVATION_PATH))
        invalid["source"]["evidenceHeadIsProductSource"] = True
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "source/evidence classification"
        ):
            self.validate_observation(invalid)

    def test_rejects_cross_line_gate_block_or_copy_claim(self) -> None:
        invalid = deepcopy(load_json(WEBSITE_OBSERVATION_PATH))
        invalid["ownershipClassification"]["blocksSimOwnedGates"] = True
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "ownership classification"
        ):
            self.validate_observation(invalid)

        invalid = deepcopy(load_json(WEBSITE_OBSERVATION_PATH))
        invalid["testObservation"]["websiteHandoffPublicSite"][
            "locallyReexecutedBySim"
        ] = True
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "test result classification"
        ):
            self.validate_observation(invalid)

        invalid = deepcopy(load_json(WEBSITE_OBSERVATION_PATH))
        invalid["execution"]["websiteChangesCopied"] = True
        with self.assertRaisesRegex(
            sim_yellow.SimYellowLifecycleError, "must remain false"
        ):
            self.validate_observation(invalid)

    def test_yellow1_record_is_metadata_verifiable_without_host_artifacts(self) -> None:
        record = self.validate_yellow1(load_json(YELLOW1_RECORD_PATH))
        self.assertEqual(
            record["source"]["productSourceCommit"],
            "1af895287c2c8249acfa581919446e24ec16f575",
        )
        self.assertFalse(record["source"]["evidenceRecordCommitIsProductSource"])
        self.assertFalse(record["releaseBoundary"]["promotionReady"])

    @unittest.skipUnless(
        YELLOW1_RUN_ROOT.is_dir(), "host-local YELLOW-1 evidence is not mounted"
    )
    def test_yellow1_record_rehashes_all_local_build_and_visual_artifacts(self) -> None:
        record = self.validate_yellow1(
            load_json(YELLOW1_RECORD_PATH), require_local_artifacts=True
        )
        self.assertEqual(record["results"]["buildFileCount"], 54)
        self.assertEqual(record["results"]["screenshotCount"], 18)
        self.assertEqual(record["results"]["screenshotTotalBytes"], 5460376)

    def test_yellow1_rejects_source_relabel_or_readiness_overclaim(self) -> None:
        invalid = deepcopy(load_json(YELLOW1_RECORD_PATH))
        invalid["source"]["evidenceRecordCommitIsProductSource"] = True
        with self.assertRaisesRegex(
            sim_yellow1.SimYellow1EvidenceError, "source/evidence binding"
        ):
            self.validate_yellow1(invalid)

        for section, key in (
            ("authorization", "yellow2Authorized"),
            ("releaseBoundary", "releaseAssetClaimed"),
            ("releaseBoundary", "promotionReady"),
        ):
            with self.subTest(section=section, key=key):
                invalid = deepcopy(load_json(YELLOW1_RECORD_PATH))
                invalid[section][key] = True
                with self.assertRaises(sim_yellow1.SimYellow1EvidenceError):
                    self.validate_yellow1(invalid)

    def test_yellow1_rejects_tracked_or_artifact_hash_drift(self) -> None:
        invalid = deepcopy(load_json(YELLOW1_RECORD_PATH))
        invalid["bindings"]["contract"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            sim_yellow1.SimYellow1EvidenceError, "contract SHA-256 drifted"
        ):
            self.validate_yellow1(invalid)

        invalid = deepcopy(load_json(YELLOW1_RECORD_PATH))
        invalid["artifactEvidence"]["completionReceipt"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            sim_yellow1.SimYellow1EvidenceError, "completionReceipt binding drifted"
        ):
            self.validate_yellow1(invalid)


if __name__ == "__main__":
    unittest.main()
