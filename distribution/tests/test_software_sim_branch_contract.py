from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
TOOLS = DISTRIBUTION / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import distribution_contract as distribution  # noqa: E402
import edition_build_planner as planner  # noqa: E402

CONTRACT_PATH = DISTRIBUTION / "branch-contracts" / "software-sim.v1.json"
SIM_MANIFEST_PATH = DISTRIBUTION / "editions" / "sim.v1.json"
CAPABILITY_POLICY_PATH = DISTRIBUTION / "capabilities" / "core-capabilities.v1.json"
E4_REQUEST_PATH = DISTRIBUTION / "build-planning" / "e4-request.v1.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


class SoftwareSimBranchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.policy = distribution.load_capability_policy(CAPABILITY_POLICY_PATH)
        cls.policy_sha256 = distribution.sha256_file(CAPABILITY_POLICY_PATH)
        cls.sim = distribution.validate_edition_manifest(
            load_json(SIM_MANIFEST_PATH),
            policy=cls.policy,
            policy_sha256=cls.policy_sha256,
        )
        cls.e4_request = planner.validate_request(load_json(E4_REQUEST_PATH))

    def test_contract_binds_sim_branch_to_common_core_baseline(self) -> None:
        contract = self.contract
        self.assertEqual(contract["kind"], "dronedream-edition-branch-sync-contract")
        self.assertEqual(contract["editionId"], "sim")
        self.assertEqual(contract["editionBranch"], "codex/software-sim")
        self.assertEqual(contract["commonCoreBranch"], "codex/software")
        self.assertFalse(contract["commonCoreChangePolicy"]["forcePushAllowed"])
        self.assertTrue(
            contract["commonCoreChangePolicy"]["simBranchMayCarryOnlyEditionSpecificDiffs"]
        )

        baseline = contract["syncBaseline"]
        git("cat-file", "-e", f"{baseline['commonCoreCommit']}^{{commit}}")
        observed_hash = planner.common_core_hash(
            ROOT,
            baseline["commonCoreCommit"],
            contract["commonCorePaths"],
        )
        self.assertEqual(observed_hash, baseline["commonCoreHash"])
        self.assertEqual(tuple(contract["commonCorePaths"]), planner.CORE_PATHS)

    def test_current_branch_diff_is_limited_to_sim_edition_contract_paths(self) -> None:
        baseline = self.contract["syncBaseline"]["commonCoreCommit"]
        committed_or_modified = git("diff", "--name-only", baseline).splitlines()
        untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
        changed_paths = sorted({path for path in committed_or_modified + untracked if path})
        prefixes = tuple(self.contract["editionSpecificPathPrefixes"])
        self.assertTrue(changed_paths)
        self.assertTrue(
            all(path.startswith(prefixes) for path in changed_paths),
            changed_paths,
        )

    def test_sim_manifest_and_capability_policy_deny_hardware_below_frontend(self) -> None:
        boundary = self.contract["simEditionBoundary"]
        self.assertEqual(boundary["allowedTargetKinds"], ["simulation"])
        self.assertEqual(boundary["forbiddenTargetKinds"], ["hitl", "real-hardware"])
        self.assertFalse(boundary["frontendMaySwitchToLabOrField"])
        self.assertEqual(
            set(boundary["forbiddenCapabilities"]),
            set(self.sim["capabilities"]["forbidden"]),
        )

        capabilities = {item["id"]: item for item in self.policy["capabilities"]}
        for capability_id in boundary["forbiddenCapabilities"]:
            self.assertEqual(
                capabilities[capability_id]["decisions"]["sim"]["decision"],
                "deny",
                capability_id,
            )
        self.assertNotIn("hardware-bridge", self.sim["modules"]["required"])
        self.assertIn("hardware-bridge", self.sim["modules"]["forbidden"])

    def test_e4_planner_remains_plan_only_for_sim_release_work(self) -> None:
        release = self.contract["releaseBoundary"]
        self.assertEqual(release["artifactFileName"], self.sim["artifactBaseName"])
        self.assertEqual(release["releaseBranch"], "codex/release-sim")
        self.assertEqual(release["releaseBranchState"], "planned-not-created")
        self.assertTrue(release["waitForUniversalYellowBuildHandoff"])

        sim_request = next(
            item for item in self.e4_request["editions"] if item["editionId"] == "sim"
        )
        self.assertEqual(sim_request["artifactFileName"], release["artifactFileName"])
        source_commit = git("rev-parse", "HEAD")
        common_core_hash = planner.common_core_hash(
            ROOT,
            source_commit,
            self.e4_request["commonCorePaths"],
        )
        plan = planner.create_build_plan(
            self.e4_request,
            repo_root=ROOT,
            source_commit=source_commit,
            source_tree_clean=True,
            observed_common_core_hash=common_core_hash,
            observed_release_heads={edition_id: None for edition_id in planner.EDITION_IDS},
        )
        self.assertEqual(plan["state"], "plan-only")
        self.assertTrue(all(value is False for value in plan["execution"].values()))

    def test_resource_protocol_keeps_this_stage_green_and_blocks_secret_use(self) -> None:
        protocol = self.contract["resourceProtocol"]
        self.assertEqual(protocol["currentWorkClass"], "GREEN")
        self.assertEqual(protocol["ordinaryCompileClass"], "YELLOW")
        self.assertEqual(protocol["realPx4GazeboStabilityClass"], "RED")
        self.assertFalse(protocol["apiKeyUseAllowed"])
        self.assertFalse(protocol["deployAllowed"])
        self.assertFalse(protocol["runtimeMigrationAllowed"])
        self.assertEqual(
            protocol["cargoTargetDir"],
            "C:/Users/zju20/AppData/Local/DroneDream/codex-cache/sim-cargo-target",
        )


if __name__ == "__main__":
    unittest.main()
