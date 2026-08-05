from __future__ import annotations

import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
TOOLS = DISTRIBUTION / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import edition_build_planner as planner  # noqa: E402

REQUEST_PATH = DISTRIBUTION / "build-planning" / "e4-request.v1.json"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "edition-build-plan.schema.json"


class EditionBuildPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.request = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
        cls.source_commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        cls.core_hash = planner.common_core_hash(
            ROOT, cls.source_commit, cls.request["commonCorePaths"]
        )
        cls.release_heads = {edition_id: None for edition_id in planner.EDITION_IDS}

    def create(self, request: object | None = None) -> dict[str, object]:
        return planner.create_build_plan(
            deepcopy(self.request if request is None else request),
            repo_root=ROOT,
            source_commit=self.source_commit,
            source_tree_clean=True,
            observed_common_core_hash=self.core_hash,
            observed_release_heads=deepcopy(self.release_heads),
        )

    def validate(self, document: object) -> dict[str, object]:
        return planner.validate_build_plan(
            document,
            deepcopy(self.request),
            repo_root=ROOT,
            observed_source_commit=self.source_commit,
            source_tree_clean=True,
            observed_common_core_hash=self.core_hash,
            observed_release_heads=deepcopy(self.release_heads),
        )

    def test_schema_is_closed_versioned_plan_only_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
        execution = schema["properties"]["execution"]["properties"]
        self.assertTrue(all(item["const"] is False for item in execution.values()))

    def test_plan_has_one_common_source_and_three_unbuilt_editions(self) -> None:
        plan = self.create()
        self.assertEqual(plan["state"], "plan-only")
        self.assertEqual(plan["source"]["commit"], self.source_commit)
        self.assertEqual(plan["source"]["commonCoreCommit"], self.source_commit)
        self.assertEqual(plan["source"]["commonCoreHash"], self.core_hash)
        self.assertEqual(
            {item["editionId"] for item in plan["editions"]},
            {"sim", "lab", "field"},
        )
        self.assertTrue(
            all(
                item["commonCoreCommit"] == self.source_commit
                and item["commonCoreHash"] == self.core_hash
                and item["promotion"]["commonCoreCommit"] == self.source_commit
                and item["promotion"]["commonCoreHash"] == self.core_hash
                for item in plan["editions"]
            )
        )
        self.assertTrue(
            all(item["artifact"]["state"] == "planned-not-built" for item in plan["editions"])
        )
        self.assertTrue(all(item["artifact"]["sha256"] is None for item in plan["editions"]))

    def test_execution_flags_never_authorize_build_install_or_promotion(self) -> None:
        plan = self.create()
        self.assertTrue(all(value is False for value in plan["execution"].values()))
        self.assertTrue(
            all(
                item["promotion"]["creationState"] == "planned-not-created"
                and item["promotion"]["observedBranchHead"] is None
                and item["promotion"]["prOnly"] is True
                and item["promotion"]["forcePushAllowed"] is False
                for item in plan["editions"]
            )
        )

    def test_exact_runtime_reference_does_not_overstate_unbuilt_components(self) -> None:
        plan = self.create()
        components = {item["componentId"]: item for item in plan["components"]}
        runtime = components["runtime-base-full-simulation"]
        self.assertEqual(runtime["sourceCommit"], "755c511539fe561207ca38ff5079f471a4110896")
        self.assertEqual(runtime["artifactState"], "verified-existing-reference")
        self.assertEqual(
            runtime["artifactSha256"],
            "936be3c4fed9f5f28e621872d0a2708e3212524323ba08eaf94ee563da3115f9",
        )
        for component_id in (
            "desktop-core",
            "engine-pack",
            "runtime-base-field-lightweight",
        ):
            self.assertEqual(components[component_id]["artifactState"], "planned-not-built")
            self.assertIsNone(components[component_id]["artifactSha256"])

    def test_resource_estimates_are_arithmetic_planning_bounds(self) -> None:
        plan = self.create()
        components = {item["componentId"]: item for item in plan["components"]}
        request_editions = {item["editionId"]: item for item in self.request["editions"]}
        for edition in plan["editions"]:
            request = request_editions[edition["editionId"]]
            expected_download = request["vehiclePackDownloadEstimateBytes"] + sum(
                components[component_id]["planningDownloadBytes"]
                for component_id in request["componentIds"]
            )
            expected_installed = request["vehiclePackInstalledEstimateBytes"] + sum(
                components[component_id]["planningInstalledBytes"]
                for component_id in request["componentIds"]
            )
            self.assertEqual(edition["resourceEstimate"]["downloadBytes"], expected_download)
            self.assertEqual(edition["resourceEstimate"]["installedBytes"], expected_installed)
            self.assertGreaterEqual(expected_installed, expected_download)

    def test_precombined_bundles_are_alias_plans_not_source_forks(self) -> None:
        plan = self.create()
        editions = {item["editionId"]: item for item in plan["editions"]}
        self.assertEqual(len(plan["precombinedBundles"]), 3)
        for bundle in plan["precombinedBundles"]:
            edition = editions[bundle["editionId"]]
            self.assertEqual(bundle["editionBuildId"], edition["artifact"]["buildId"])
            self.assertEqual(bundle["vehiclePackId"], edition["vehiclePack"]["packId"])
            self.assertEqual(bundle["resourceEstimate"], edition["resourceEstimate"])
            self.assertEqual(bundle["state"], "plan-only")

    def test_notice_and_pack_license_ids_are_bound_but_incomplete(self) -> None:
        plan = self.create()
        closure = plan["licenseClosure"]
        self.assertEqual(closure["state"], "plan-only-incomplete-artifact-closure")
        self.assertGreater(closure["notice"]["bytes"], 0)
        expected_ids = {
            license_id
            for edition in plan["editions"]
            for license_id in edition["licenseIds"]
        }
        self.assertEqual(set(closure["licenseIds"]), expected_ids)
        self.assertTrue(closure["blockers"])

    def test_dirty_source_fails_closed(self) -> None:
        with self.assertRaisesRegex(planner.BuildPlanError, "clean source tree"):
            planner.create_build_plan(
                deepcopy(self.request),
                repo_root=ROOT,
                source_commit=self.source_commit,
                source_tree_clean=False,
                observed_common_core_hash=self.core_hash,
                observed_release_heads=deepcopy(self.release_heads),
            )

    def test_existing_release_branch_fails_closed(self) -> None:
        heads = deepcopy(self.release_heads)
        heads["sim"] = "a" * 40
        with self.assertRaisesRegex(planner.BuildPlanError, "already has a remote head"):
            planner.create_build_plan(
                deepcopy(self.request),
                repo_root=ROOT,
                source_commit=self.source_commit,
                source_tree_clean=True,
                observed_common_core_hash=self.core_hash,
                observed_release_heads=heads,
            )

    def test_common_core_source_or_policy_drift_is_rejected(self) -> None:
        for field, mutate, message in (
            (
                "source",
                lambda plan: plan["source"].update({"commit": "a" * 40}),
                "source",
            ),
            (
                "common-core",
                lambda plan: plan["source"].update({"commonCoreHash": "0" * 64}),
                "source",
            ),
            (
                "common-core-commit",
                lambda plan: plan["editions"][0].update({"commonCoreCommit": "a" * 40}),
                "editions",
            ),
            (
                "policy",
                lambda plan: plan["policyBindings"]["capabilityPolicy"].update(
                    {"sha256": "0" * 64}
                ),
                "policyBindings",
            ),
        ):
            with self.subTest(field=field):
                invalid = self.create()
                mutate(invalid)
                with self.assertRaisesRegex(planner.BuildPlanError, message):
                    self.validate(invalid)

    def test_component_pack_edition_and_notice_drift_are_rejected(self) -> None:
        mutations = (
            (
                "components",
                lambda plan: plan["components"][0].update(
                    {"contract": {"path": "x", "sha256": "0" * 64}}
                ),
            ),
            (
                "editions",
                lambda plan: plan["editions"][0]["vehiclePack"]["manifest"].update(
                    {"sha256": "0" * 64}
                ),
            ),
            (
                "licenseClosure",
                lambda plan: plan["licenseClosure"]["notice"].update({"sha256": "0" * 64}),
            ),
        )
        for key, mutate in mutations:
            with self.subTest(key=key):
                invalid = self.create()
                mutate(invalid)
                with self.assertRaisesRegex(planner.BuildPlanError, key):
                    self.validate(invalid)

    def test_request_rejects_unbuilt_component_claiming_artifact_bytes(self) -> None:
        invalid = deepcopy(self.request)
        invalid["components"][0].update(
            {
                "artifactManifestSha256": "1" * 64,
                "artifactSha256": "2" * 64,
                "artifactBytes": 1,
            }
        )
        with self.assertRaisesRegex(planner.BuildPlanError, "cannot claim artifact bytes"):
            self.create(invalid)

    def test_request_rejects_controller_or_bundle_drift(self) -> None:
        invalid = deepcopy(self.request)
        invalid["editions"][1]["controllerModel"] = "Unknown Controller"
        with self.assertRaisesRegex(planner.BuildPlanError, "controller"):
            self.create(invalid)
        invalid = deepcopy(self.request)
        invalid["precombinedBundles"][1]["vehiclePackId"] = "amovlab-p450-px4"
        with self.assertRaisesRegex(planner.BuildPlanError, "bundle drifted"):
            self.create(invalid)

    def test_request_rejects_artifact_name_or_runtime_profile_drift(self) -> None:
        invalid = deepcopy(self.request)
        invalid["editions"][0]["artifactFileName"] = "DroneDream-Sim-1.0.1.exe"
        with self.assertRaisesRegex(planner.BuildPlanError, "filename drifted"):
            self.create(invalid)
        invalid = deepcopy(self.request)
        invalid["editions"][0]["componentIds"][-1] = "runtime-base-field-lightweight"
        with self.assertRaisesRegex(planner.BuildPlanError, "Runtime Base selection drifted"):
            self.create(invalid)

    def test_plan_generation_is_byte_deterministic_for_equal_observations(self) -> None:
        first = json.dumps(self.create(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        second = json.dumps(
            self.create(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
