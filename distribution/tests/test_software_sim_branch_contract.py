from __future__ import annotations

import hashlib
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
SIM_TOOLS = DISTRIBUTION / "sim" / "tools"
if str(SIM_TOOLS) not in sys.path:
    sys.path.insert(0, str(SIM_TOOLS))

import distribution_contract as distribution  # noqa: E402
import edition_build_planner as planner  # noqa: E402
from sim_universal_handoff import exact_synchronized_paths  # noqa: E402

CONTRACT_PATH = DISTRIBUTION / "branch-contracts" / "software-sim.v1.json"
SIM_MANIFEST_PATH = DISTRIBUTION / "editions" / "sim.v1.json"
ADOPTION_RECEIPT_PATH = (
    DISTRIBUTION
    / "sim"
    / "adoptions"
    / "sim-preview-1.0.0-2aec69e.adoption-receipt.v1.json"
)
CAPABILITY_POLICY_PATH = DISTRIBUTION / "capabilities" / "core-capabilities.v1.json"
E4_REQUEST_PATH = DISTRIBUTION / "build-planning" / "e4-request.v1.json"
READINESS_PATH = (
    DISTRIBUTION / "sim" / "readiness" / "sim-only-common-core-sync.v1.json"
)
FAILED_YELLOW2_PATH = (
    DISTRIBUTION / "sim" / "desktop" / "yellow-2-build-evidence-record.v1.json"
)
REPLACEMENT_YELLOW2_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-2-replacement-build-evidence-record.v1.json"
)
COEXISTENCE_SYNC_PATH = (
    DISTRIBUTION / "sim" / "readiness" / "coexistence-common-core-sync.v1.json"
)
LIFECYCLE_CONTRACT_PATH = (
    ROOT / "desktop" / "scripts" / "edition-installer-lifecycle-contract.ps1"
)
YELLOW_ATTEMPT_3_APPLICATION_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-3-b51fcd4-application.v1.json"
)


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


def run_lifecycle_contract(expression: str) -> subprocess.CompletedProcess[str]:
    command = (
        f". '{LIFECYCLE_CONTRACT_PATH}'; "
        "$ErrorActionPreference='Stop'; "
        f"{expression}"
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class SoftwareSimBranchContractTests(unittest.TestCase):
    def test_yellow_attempt_3_application_separates_product_source_and_evidence(self) -> None:
        application = load_json(YELLOW_ATTEMPT_3_APPLICATION_PATH)
        source = application["sourceSeparation"]
        self.assertEqual(
            source["productSourceCommit"],
            "b51fcd41d69b9019dee6cf23c39d4a5f7e6a5b47",
        )
        self.assertEqual(
            git("show", "-s", "--format=%T", source["productSourceCommit"]),
            source["productSourceTree"],
        )
        self.assertFalse(source["applicationEvidenceIsProductSource"])
        self.assertFalse(
            application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"]
        )
        self.assertFalse(
            application["authorization"]["yellowBuildRequestSubmitted"]
        )
        self.assertTrue(application["pendingProductGate"]["exactDonorReceived"])
        self.assertTrue(application["pendingProductGate"]["thisApplicationSuperseded"])
        self.assertEqual(
            application["state"],
            "superseded-by-common-ui-theme-product-source",
        )
        self.assertFalse(
            application["pendingProductGate"]["currentSourceMayBeUsedForExeBuild"]
        )
        self.assertFalse(
            application["pendingProductGate"]["yellowRequestSubmissionAllowed"]
        )
        self.assertTrue(
            all(value == 0 for value in application["executedCounts"].values())
        )

    def test_yellow_attempt_3_is_single_sim_only_build_request(self) -> None:
        application = load_json(YELLOW_ATTEMPT_3_APPLICATION_PATH)
        attempt = application["attemptAccounting"]
        self.assertEqual(attempt["globalBuildAttemptOrdinal"], 3)
        self.assertEqual(attempt["sourceBuildAttemptOrdinal"], 1)
        self.assertEqual(attempt["sourceBuildAttemptMaximum"], 1)
        self.assertEqual(attempt["maximumBuildInvocations"], 1)
        self.assertFalse(attempt["automaticRetryAllowed"])
        self.assertEqual(application["buildIdentity"]["runtimeProfileId"], "sim-only")
        self.assertFalse(
            application["buildIdentity"]["hardwareHitlLabFieldPayloadAllowed"]
        )
        self.assertEqual(
            application["buildIdentity"]["fileName"],
            "DroneDream-Sim-1.0.0.exe",
        )

    def test_yellow_attempt_3_preserves_frozen_artifact_and_product_key(self) -> None:
        application = load_json(YELLOW_ATTEMPT_3_APPLICATION_PATH)
        frozen = application["permanentlyFrozenPriorArtifact"]
        self.assertEqual(
            frozen["sha256"],
            "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece",
        )
        for key in (
            "reuseAllowed",
            "relabelAllowed",
            "furtherLifecycleExecutionAllowed",
            "websiteHandoffAllowed",
        ):
            self.assertFalse(frozen[key], key)
        residue = application["historicalSimProductKeyResidue"]
        self.assertTrue(residue["observedPresentDuringApplicationPreparation"])
        self.assertFalse(residue["buildReadsOrMutatesResidue"])
        self.assertFalse(residue["cleanupAuthorizedByThisApplication"])
        self.assertFalse(residue["cleanupExecuted"])

    def test_shared_lifecycle_contract_normalizes_sim_registration(self) -> None:
        result = run_lifecycle_contract(
            "$e=[ordered]@{DisplayName='DroneDream · SIM';DisplayVersion='1.0.0';"
            "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
            "MainBinaryName='drone-dream-desktop.exe'};"
            "$a=[ordered]@{DisplayName='DroneDream · SIM';DisplayVersion='1.0.0';"
            "InstallLocation='\"c:\\users\\example\\appdata\\local\\dronedream-sim\\\"';"
            "MainBinaryName='drone-dream-desktop.exe'};"
            "$r=Compare-DroneDreamUninstallRegistration -Expected $e -Actual $a;"
            "if(-not $r.passed -or $r.mismatches.Count -ne 0){exit 9}"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_lifecycle_contract_captures_fields_before_failure(self) -> None:
        mismatch = run_lifecycle_contract(
            "$e=[ordered]@{DisplayName='DroneDream · SIM';DisplayVersion='1.0.0';"
            "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
            "MainBinaryName='drone-dream-desktop.exe'};"
            "$a=[ordered]@{DisplayName='DroneDream-Sim';DisplayVersion='1.0.0';"
            "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
            "MainBinaryName='drone-dream-desktop.exe'};"
            "$r=Compare-DroneDreamUninstallRegistration -Expected $e -Actual $a;"
            "if($r.passed -or $r.mismatches.Count -ne 1 "
            "-or $r.mismatches[0] -cne 'DisplayName'){exit 9}"
        )
        self.assertEqual(mismatch.returncode, 0, mismatch.stderr)

        unknown = run_lifecycle_contract(
            "$e=[ordered]@{DisplayName='DroneDream · SIM';DisplayVersion='1.0.0';"
            "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
            "MainBinaryName='drone-dream-desktop.exe';Unexpected='value'};"
            "$a=[ordered]@{DisplayName='DroneDream · SIM';DisplayVersion='1.0.0';"
            "InstallLocation='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
            "MainBinaryName='drone-dream-desktop.exe'};"
            "Compare-DroneDreamUninstallRegistration -Expected $e -Actual $a"
        )
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("fields drifted", unknown.stderr)

    def test_shared_lifecycle_contract_rejects_unowned_sim_residue(self) -> None:
        accepted = run_lifecycle_contract(
            "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
            "'DroneDreamRuntimeInstallMode'='install-app-only';"
            "'DroneDreamRuntimeDrive'='';'DroneDreamRuntimeOperationProtocol'=2};"
            "$r=Get-DroneDreamProductRegistrationDisposition -Values $v "
            "-ExpectedInstallDirectory 'c:\\users\\example\\appdata\\local\\dronedream-sim' "
            "-PreflightProductKeyAbsent $true;"
            "if($r.state -cne 'retained-by-standard-uninstaller' "
            "-or -not $r.testHarnessRemovalAllowed){exit 9}"
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

        cases = (
            (
                "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim';"
                "'ForeignValue'='do-not-delete'};"
                "Get-DroneDreamProductRegistrationDisposition -Values $v "
                "-ExpectedInstallDirectory 'C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim' "
                "-PreflightProductKeyAbsent $true",
                "unowned values",
            ),
            (
                "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Lab';"
                "'DroneDreamRuntimeInstallMode'='install-app-only'};"
                "Get-DroneDreamProductRegistrationDisposition -Values $v "
                "-ExpectedInstallDirectory 'C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim' "
                "-PreflightProductKeyAbsent $true",
                "different install directory",
            ),
            (
                "$v=[ordered]@{'(default)'='C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim'};"
                "Get-DroneDreamProductRegistrationDisposition -Values $v "
                "-ExpectedInstallDirectory 'C:\\Users\\Example\\AppData\\Local\\DroneDream-Sim' "
                "-PreflightProductKeyAbsent $false",
                "existed at preflight",
            ),
        )
        for expression, message in cases:
            with self.subTest(message=message):
                rejected = run_lifecycle_contract(expression)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(message, rejected.stderr)

    def test_replacement_yellow2_preserves_product_source_and_failure_genealogy(self) -> None:
        evidence = load_json(REPLACEMENT_YELLOW2_PATH)

        self.assertEqual(evidence["editionId"], "sim")
        self.assertEqual(
            evidence["source"]["productSourceCommit"],
            "bd4ad3820f957e8f0ce5686e5dc06d636e4e4af1",
        )
        self.assertFalse(evidence["source"]["evidenceCommitIsProductSource"])
        self.assertEqual(evidence["attempt"]["globalAttemptOrdinal"], 2)
        self.assertEqual(evidence["attempt"]["sourceAttemptOrdinal"], 1)
        self.assertEqual(evidence["attempt"]["sourceAttemptMaximum"], 1)
        self.assertFalse(evidence["attempt"]["secondBuildAttempted"])
        self.assertEqual(evidence["artifact"]["fileName"], "DroneDream-Sim-1.0.0.exe")
        self.assertEqual(len(evidence["artifact"]["sha256"]), 64)
        self.assertEqual(evidence["artifact"]["authenticodeState"], "NotSigned")
        self.assertEqual(evidence["artifact"]["peCertificateTableSize"], 0)
        self.assertIsNone(evidence["artifact"]["updaterSignaturePath"])
        self.assertEqual(evidence["payloadAudit"]["enginePackProfileId"], "sim-only")
        self.assertTrue(evidence["payloadAudit"]["simPayloadContractPassed"])
        self.assertEqual(evidence["payloadAudit"]["forbiddenFindingCount"], 0)
        self.assertEqual(evidence["payloadAudit"]["validatedVehiclePackCount"], 0)
        self.assertFalse(evidence["payloadAudit"]["runtimeBaseEmbedded"])
        self.assertTrue(evidence["priorFailedAttempt"]["preserved"])
        self.assertFalse(evidence["priorFailedAttempt"]["reuseAllowed"])
        self.assertTrue(evidence["lifecycle"]["eligible"])
        self.assertFalse(evidence["lifecycle"]["validated"])
        self.assertFalse(evidence["nonClaims"]["releaseReady"])
        self.assertFalse(evidence["websiteHandoff"]["exactExeReceived"])

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

        evidence = contract["syncEvidence"]
        self.assertEqual(evidence["universalSourceCommit"], baseline["commonCoreCommit"])
        self.assertFalse(evidence["receiptHeadIsProductSource"])
        self.assertFalse(evidence["wholeCommitCherryPicked"])
        self.assertFalse(evidence["unrelatedParentChainAdopted"])
        self.assertEqual(evidence["validatedVehiclePackCount"], 0)
        self.assertEqual(
            evidence["installerState"],
            "prior-yellow2-failed-new-source-awaiting-authorization",
        )

    def test_path_limited_sync_matches_every_authoritative_donor_blob(self) -> None:
        baseline = self.contract["syncBaseline"]
        evidence = self.contract["syncEvidence"]
        source = baseline["commonCoreCommit"]
        direct_paths = git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", source
        ).splitlines()
        self.assertEqual(direct_paths, self.contract["synchronizedPaths"])
        self.assertEqual(len(direct_paths), evidence["synchronizedPathCount"])
        blob_rows: list[dict[str, str]] = []
        for path in direct_paths:
            donor_blob = git("rev-parse", f"{source}:{path}")
            self.assertEqual(git("hash-object", "--", path), donor_blob, path)
            blob_rows.append({"path": path, "blob": donor_blob})
        canonical = (
            json.dumps(blob_rows, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            evidence["synchronizedBlobSetSha256"],
        )
        self.assertEqual(
            git("merge-base", "HEAD", source),
            baseline["commonAncestorCommit"],
        )

    def test_common_core_sync_does_not_relabel_the_adopted_preview(self) -> None:
        adoption = load_json(ADOPTION_RECEIPT_PATH)
        historical_core = adoption["source"]["commonCoreCommit"]
        self.assertEqual(
            historical_core,
            "db7592fbfc39c5489bdbcc7d2373d1480a69897b",
        )
        self.assertNotEqual(
            historical_core,
            self.contract["syncBaseline"]["commonCoreCommit"],
        )

    def test_current_branch_diff_is_limited_to_sim_edition_contract_paths(self) -> None:
        baseline = self.contract["syncBaseline"]["previousCommonCoreCommit"]
        committed_or_modified = git("diff", "--name-only", baseline).splitlines()
        untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
        changed_paths = sorted({path for path in committed_or_modified + untracked if path})
        prefixes = tuple(self.contract["editionSpecificPathPrefixes"])
        synchronized_paths = set(self.contract["synchronizedPaths"])
        coexistence = load_json(COEXISTENCE_SYNC_PATH)
        supplemental_paths = {
            row["path"] for row in coexistence["synchronizedRuntimePaths"]
        }
        supplemental_paths.update(exact_synchronized_paths(ROOT))
        supplemental_paths.add("frontend/src/pages/DesktopSetup.tsx")
        self.assertTrue(changed_paths)
        self.assertTrue(
            all(
                path in synchronized_paths
                or path in supplemental_paths
                or path.startswith(prefixes)
                for path in changed_paths
            ),
            changed_paths,
        )

    def test_coexistence_sync_does_not_relabel_partial_donor_as_common_core(self) -> None:
        coexistence = load_json(COEXISTENCE_SYNC_PATH)
        classification = coexistence["commonCoreClassification"]
        self.assertEqual(
            classification["recordedCommonCoreCommit"],
            self.contract["syncBaseline"]["commonCoreCommit"],
        )
        self.assertFalse(classification["baselineUpdated"])
        self.assertFalse(classification["candidateHashClaimedAsCurrent"])
        self.assertFalse(coexistence["nonClaims"]["donorPytestExecuted"])

    def test_new_readiness_receipt_blocks_failed_exe_reuse_and_execution(self) -> None:
        readiness = load_json(READINESS_PATH)
        baseline = self.contract["syncBaseline"]
        evidence = self.contract["syncEvidence"]
        self.assertEqual(readiness["kind"], "dronedream-sim-common-core-sync-readiness")
        self.assertEqual(readiness["state"], "green-ready-awaiting-yellow-authorization")
        self.assertEqual(readiness["source"]["commonCoreCommit"], baseline["commonCoreCommit"])
        self.assertEqual(readiness["source"]["commonCoreHash"], baseline["commonCoreHash"])
        self.assertEqual(
            readiness["source"]["synchronizedBlobSetSha256"],
            evidence["synchronizedBlobSetSha256"],
        )
        self.assertEqual(
            readiness["source"]["synchronizedPaths"],
            self.contract["synchronizedPaths"],
        )
        self.assertEqual(
            readiness["universalEvidence"]["sha256"],
            evidence["universalReceiptSha256"],
        )
        self.assertEqual(
            distribution.sha256_file(FAILED_YELLOW2_PATH),
            readiness["priorFailedArtifact"]["evidenceRecordSha256"],
        )
        self.assertFalse(readiness["priorFailedArtifact"]["reuseAllowed"])
        self.assertFalse(readiness["priorFailedArtifact"]["relabelAllowed"])
        self.assertFalse(readiness["nextYellow"]["executionAuthorized"])
        self.assertFalse(readiness["nextYellow"]["buildStarted"])
        self.assertEqual(readiness["nextYellow"]["enginePackProfileId"], "sim-only")
        self.assertEqual(
            readiness["nextYellow"]["enginePackProfileEnvironmentVariable"],
            "DRONEDREAM_EDITION_PROFILE",
        )
        build_script = (ROOT / "desktop" / "src-tauri" / "build.rs").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'std::env::var("DRONEDREAM_EDITION_PROFILE")',
            build_script,
        )
        self.assertNotIn(
            'std::env::var("DRONEDREAM_ENGINE_PACK_EDITION_PROFILE")',
            build_script,
        )
        self.assertEqual(
            readiness["nextYellow"]["enginePackProfileEnvironmentValue"],
            "sim-only",
        )
        self.assertEqual(readiness["nextYellow"]["plannedGlobalBuildAttemptOrdinal"], 2)
        self.assertEqual(readiness["boundaries"]["validatedVehiclePackCount"], 0)
        self.assertFalse(readiness["boundaries"]["formalEnginePackBuilt"])
        self.assertFalse(readiness["boundaries"]["installerBuilt"])

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
