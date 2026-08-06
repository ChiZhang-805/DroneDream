from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
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
YELLOW_ATTEMPT_5_APPLICATION_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-5-2bffcb0-application.v1.json"
)
YELLOW_ATTEMPT_3_FAILURE_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-3-2bffcb0-preflight-failed.v1.json"
)
YELLOW_ATTEMPT_4_PREFLIGHT_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-4-2bffcb0-preflight-ready.v1.json"
)
YELLOW_ATTEMPT_4_FAILURE_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-4-2bffcb0-checkout-failed.v1.json"
)
YELLOW_ATTEMPT_5_PREFLIGHT_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-5-2bffcb0-preflight-ready.v1.json"
)
YELLOW_ATTEMPT_5_FAILURE_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-5-2bffcb0-common-core-prebuild-failed.v1.json"
)
YELLOW_ATTEMPT_6_APPLICATION_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-6-a99f5e8-application.v1.json"
)
YELLOW_ATTEMPT_6_PLAN_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-6-a99f5e8-plan-ready.v1.json"
)
YELLOW_ATTEMPT_6_FAILURE_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-6-a99f5e8-tauri-cli-missing-failed.v1.json"
)
YELLOW_ATTEMPT_7_APPLICATION_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-7-e181d02-application.v1.json"
)
YELLOW_ATTEMPT_7_PLAN_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-7-e181d02-plan-ready.v1.json"
)
YELLOW_ATTEMPT_7_FAILURE_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-7-e181d02-cache-drift-preflight-failed.v1.json"
)
YELLOW_ATTEMPT_8_APPLICATION_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-8-f4a0562-application.v1.json"
)
YELLOW_ATTEMPT_8_PLAN_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-8-f4a0562-plan-ready.v1.json"
)
YELLOW_ATTEMPT_8_FAILURE_PATH = (
    DISTRIBUTION
    / "sim"
    / "desktop"
    / "yellow-build-attempt-8-f4a0562-public-config-preflight-failed.v1.json"
)
DETACHED_NODE_DEPENDENCY_GAP_PATH = (
    DISTRIBUTION
    / "sim"
    / "readiness"
    / "detached-node-dependency-common-core-gap.v1.json"
)
DETACHED_NODE_DEPENDENCY_SYNC_PATH = (
    DISTRIBUTION
    / "sim"
    / "readiness"
    / "detached-node-dependency-common-core-sync.v1.json"
)
STABLE_OFFLINE_CACHE_CONTRACT_PATH = (
    DISTRIBUTION / "sim" / "readiness" / "stable-offline-cache-contract.v1.json"
)
YELLOW_APPLICATION_PATH = YELLOW_ATTEMPT_8_APPLICATION_PATH
LOCKFILE_OFFLINE_CACHE_TOOL = (
    DISTRIBUTION / "sim" / "desktop" / "lockfile-offline-cache.mjs"
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


def write_offline_cache_fixture(root: Path) -> tuple[Path, Path, str, Path, Path]:
    repo = root / "repo"
    cache = root / "global-cache"
    resolved = "https://registry.npmjs.org/example/-/example-1.0.0.tgz"
    tarball = b"fixture-tarball-content"
    digest = hashlib.sha512(tarball).digest()
    integrity = f"sha512-{base64.b64encode(digest).decode()}"
    lock = {
        "name": "fixture",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": "fixture", "version": "1.0.0"},
            "node_modules/example": {
                "version": "1.0.0",
                "resolved": resolved,
                "integrity": integrity,
            },
        },
    }
    for workspace in ("desktop", "frontend"):
        workspace_root = repo / workspace
        workspace_root.mkdir(parents=True)
        (workspace_root / "package.json").write_text(
            json.dumps({"name": f"fixture-{workspace}", "version": "1.0.0"}),
            encoding="utf-8",
        )
        (workspace_root / "package-lock.json").write_text(
            json.dumps(lock),
            encoding="utf-8",
        )

    content_hex = digest.hex()
    content = (
        cache
        / "_cacache"
        / "content-v2"
        / "sha512"
        / content_hex[:2]
        / content_hex[2:4]
        / content_hex[4:]
    )
    content.parent.mkdir(parents=True)
    content.write_bytes(tarball)
    key = f"make-fetch-happen:request-cache:{resolved}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    index = cache / "_cacache" / "index-v5" / key_hash[:2] / key_hash[2:4] / key_hash[4:]
    index.parent.mkdir(parents=True)
    value = json.dumps(
        {"key": key, "integrity": integrity, "time": 1, "size": len(tarball)},
        separators=(",", ":"),
    )
    index.write_text(f"{hashlib.sha1(value.encode()).hexdigest()}\t{value}\n", encoding="utf-8")
    content_sha256 = hashlib.sha256(tarball).hexdigest()
    semantic_lines = (
        f"content\t{integrity}\t{len(tarball)}\t{content_sha256}\n"
        f"index\t{key}\t{integrity}"
    )
    fingerprint = hashlib.sha256(semantic_lines.encode()).hexdigest()
    return repo, cache, fingerprint, content, index


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
    def test_yellow_attempt_5_freezes_exact_commands_without_execution(self) -> None:
        application = load_json(YELLOW_ATTEMPT_5_APPLICATION_PATH)
        plan = application["executionPlan"]
        script = ROOT / plan["entryScript"]["path"]
        self.assertEqual(script.stat().st_size, plan["entryScript"]["bytes"])
        self.assertEqual(
            hashlib.sha256(script.read_bytes()).hexdigest(),
            plan["entryScript"]["sha256"],
        )
        self.assertEqual(plan["entryScript"]["checkoutEol"], "lf")
        attributes = git(
            "check-attr",
            "eol",
            "--",
            plan["entryScript"]["path"],
        )
        self.assertTrue(attributes.endswith(": eol: lf"), attributes)
        self.assertEqual(plan["entryScript"]["defaultMode"], "Plan")
        self.assertTrue(plan["entryScript"]["executeRequiresExplicitMode"])
        self.assertTrue(plan["exactCommands"]["preflight"].endswith("-Mode Preflight"))
        self.assertTrue(plan["exactCommands"]["build"].endswith("-Mode Execute"))
        self.assertIn("worktree add --detach", plan["sourceCheckout"]["exactCommand"])
        self.assertIn("-c core.longpaths=true", plan["sourceCheckout"]["exactCommand"])
        self.assertEqual(
            application["ownedBuildSurface"]["sourceRoot"],
            "C:/Users/zju20/dds5",
        )
        self.assertTrue(plan["sourceCheckout"]["postCheckoutStatusMustBeClean"])
        self.assertEqual(plan["singleBuildInvocation"]["frontendMaximum"], 1)
        self.assertEqual(plan["singleBuildInvocation"]["tauriMaximum"], 1)
        self.assertEqual(plan["singleBuildInvocation"]["cargoMaximum"], 1)
        self.assertEqual(plan["singleBuildInvocation"]["nsisMaximum"], 1)
        self.assertEqual(plan["singleBuildInvocation"]["retryMaximum"], 0)
        self.assertFalse(plan["preflightExecutedDuringThisGreenAtom"])
        self.assertFalse(plan["buildExecutedDuringThisGreenAtom"])
        self.assertFalse(
            application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"]
        )

    def test_yellow_attempt_5_application_separates_product_source_and_evidence(self) -> None:
        application = load_json(YELLOW_ATTEMPT_5_APPLICATION_PATH)
        source = application["sourceSeparation"]
        self.assertEqual(
            source["productSourceCommit"],
            "2bffcb0d26d080107144441f1c356f45dc4320ec",
        )
        self.assertEqual(
            git("show", "-s", "--format=%T", source["productSourceCommit"]),
            source["productSourceTree"],
        )
        self.assertFalse(source["applicationEvidenceIsProductSource"])
        self.assertFalse(
            application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"]
        )
        self.assertTrue(
            application["authorization"]["yellowBuildRequestSubmitted"]
        )
        self.assertTrue(application["pendingProductGate"]["exactDonorReceived"])
        self.assertFalse(application["pendingProductGate"]["thisApplicationSuperseded"])
        self.assertEqual(
            application["state"],
            "green-readiness-frozen-awaiting-new-yellow-authorization",
        )
        self.assertTrue(
            application["pendingProductGate"]["currentSourceMayBeUsedForExeBuild"]
        )
        self.assertTrue(
            application["pendingProductGate"]["yellowRequestSubmissionAllowed"]
        )
        self.assertTrue(
            all(value == 0 for value in application["executedCounts"].values())
        )

    def test_yellow_attempt_5_is_single_sim_only_build_request(self) -> None:
        application = load_json(YELLOW_ATTEMPT_5_APPLICATION_PATH)
        attempt = application["attemptAccounting"]
        self.assertEqual(attempt["globalAuthorizedCommandOrdinal"], 5)
        self.assertEqual(attempt["sourceApplicationPreflightOrdinal"], 3)
        self.assertEqual(attempt["priorSourceBuildInvocationCount"], 0)
        self.assertEqual(attempt["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(attempt["sourceBuildInvocationMaximum"], 1)
        self.assertNotIn("sourceBuildAttemptOrdinal", attempt)
        self.assertNotIn("sourceBuildAttemptMaximum", attempt)
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

    def test_yellow_attempt_5_preserves_frozen_artifact_and_product_key(self) -> None:
        application = load_json(YELLOW_ATTEMPT_5_APPLICATION_PATH)
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

    def test_yellow_attempt_3_preflight_failure_is_frozen_before_build(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_3_FAILURE_PATH)
        self.assertEqual(receipt["state"], "failed-frozen-no-retry")
        binding = receipt["authorizationBinding"]
        self.assertEqual(binding["globalAuthorizedCommandOrdinal"], 3)
        self.assertEqual(binding["sourceApplicationPreflightOrdinal"], 1)
        self.assertFalse(binding["sourceBuildInvocationConsumed"])
        self.assertEqual(binding["sourceBuildInvocationCount"], 0)
        self.assertEqual(binding["sourceBuildInvocationMaximum"], 1)
        self.assertFalse(receipt["failure"]["sameAuthorizationMayBeReused"])
        for key in (
            "runRootsCreated",
            "sourceRootsCreated",
            "detachedCheckouts",
            "buildDriverInvocations",
            "frontendBuilds",
            "tauriBuilds",
            "cargoBuilds",
            "nsisBuilds",
            "artifactBuilds",
        ):
            self.assertEqual(receipt["execution"][key], 0, key)
        self.assertFalse(receipt["protectedState"]["runRootExistsAfterFailure"])
        self.assertFalse(receipt["protectedState"]["sourceRootExistsAfterFailure"])
        self.assertFalse(receipt["protectedState"]["cleanupExecuted"])

    def test_yellow_attempt_4_preflight_is_ready_without_execution(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_4_PREFLIGHT_PATH)
        application = ROOT / receipt["application"]["path"]
        entry_script = ROOT / receipt["entryScript"]["path"]
        self.assertEqual(application.stat().st_size, receipt["application"]["bytes"])
        self.assertEqual(
            hashlib.sha256(application.read_bytes()).hexdigest(),
            receipt["application"]["sha256"],
        )
        self.assertEqual(entry_script.stat().st_size, receipt["entryScript"]["bytes"])
        self.assertEqual(
            hashlib.sha256(entry_script.read_bytes()).hexdigest(),
            receipt["entryScript"]["sha256"],
        )
        prior_failure = ROOT / receipt["priorAttempt"]["failureReceiptPath"]
        self.assertEqual(
            hashlib.sha256(prior_failure.read_bytes()).hexdigest(),
            receipt["priorAttempt"]["failureReceiptSha256"],
        )
        self.assertEqual(receipt["preflight"]["status"], "pass")
        self.assertEqual(receipt["application"]["globalAuthorizedCommandOrdinal"], 4)
        self.assertEqual(receipt["application"]["sourceApplicationPreflightOrdinal"], 2)
        self.assertEqual(receipt["application"]["priorSourceBuildInvocationCount"], 0)
        self.assertEqual(receipt["application"]["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(receipt["application"]["sourceBuildInvocationMaximum"], 1)
        self.assertTrue(receipt["preflight"]["runRootAbsent"])
        self.assertTrue(receipt["preflight"]["sourceRootAbsent"])
        self.assertFalse(receipt["preflight"]["publicSupabaseValuesRecorded"])
        self.assertFalse(receipt["authorization"]["yellowBuildExecutionAuthorizedByThisReceipt"])
        self.assertTrue(all(value == 0 for value in receipt["executedCounts"].values()))

    def test_yellow_attempt_4_checkout_failure_is_frozen_before_build(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_4_FAILURE_PATH)
        binding = receipt["authorizationBinding"]
        self.assertEqual(binding["globalAuthorizedCommandOrdinal"], 4)
        self.assertEqual(binding["sourceApplicationPreflightOrdinal"], 2)
        self.assertFalse(binding["sourceBuildInvocationConsumed"])
        self.assertEqual(binding["sourceBuildInvocationCount"], 0)
        self.assertEqual(receipt["failure"]["failedAbsolutePathChars"], 264)
        self.assertFalse(receipt["failure"]["sameAuthorizationMayBeReused"])
        self.assertTrue(receipt["ownedEvidence"]["runRootPreserved"])
        self.assertFalse(receipt["ownedEvidence"]["cleanupExecuted"])
        for key in (
            "buildDriverInvocations",
            "frontendBuilds",
            "tauriBuilds",
            "cargoBuilds",
            "nsisBuilds",
            "artifactBuilds",
        ):
            self.assertEqual(receipt["execution"][key], 0, key)

    def test_yellow_attempt_5_preflight_is_ready_without_execution(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_5_PREFLIGHT_PATH)
        application = ROOT / receipt["application"]["path"]
        entry_script = ROOT / receipt["entryScript"]["path"]
        prior_failure = ROOT / receipt["priorCheckoutFailure"]["receiptPath"]
        self.assertEqual(
            hashlib.sha256(application.read_bytes()).hexdigest(),
            receipt["application"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(entry_script.read_bytes()).hexdigest(),
            receipt["entryScript"]["sha256"],
        )
        self.assertEqual(
            hashlib.sha256(prior_failure.read_bytes()).hexdigest(),
            receipt["priorCheckoutFailure"]["receiptSha256"],
        )
        self.assertEqual(receipt["application"]["priorSourceBuildInvocationCount"], 0)
        self.assertEqual(receipt["application"]["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(receipt["application"]["sourceBuildInvocationMaximum"], 1)
        self.assertEqual(receipt["checkout"]["longestCandidateAbsolutePathChars"], 175)
        self.assertFalse(receipt["checkout"]["globalGitConfigModified"])
        self.assertTrue(receipt["preflight"]["runRootAbsent"])
        self.assertTrue(receipt["preflight"]["sourceRootAbsent"])
        self.assertFalse(receipt["authorization"]["yellowBuildExecutionAuthorizedByThisReceipt"])
        self.assertTrue(all(value == 0 for value in receipt["executedCounts"].values()))

    def test_yellow_attempt_5_common_core_failure_consumes_only_build_invocation(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_5_FAILURE_PATH)
        binding = receipt["authorizationBinding"]
        execution = receipt["execution"]
        self.assertEqual(receipt["state"], "failed-frozen-no-retry")
        self.assertEqual(binding["globalAuthorizedCommandOrdinal"], 5)
        self.assertEqual(binding["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(binding["sourceBuildInvocationMaximum"], 1)
        self.assertTrue(binding["sourceBuildInvocationConsumed"])
        self.assertFalse(binding["retryAllowed"])
        self.assertEqual(execution["buildDriverInvocations"], 1)
        for key in (
            "frontendBuilds",
            "tauriBuilds",
            "cargoBuilds",
            "nsisBuilds",
            "artifactBuilds",
            "installations",
            "runtimeStarts",
            "px4Starts",
            "gazeboStarts",
            "hardwareActions",
            "deployments",
            "automaticRetries",
        ):
            self.assertEqual(execution[key], 0, key)
        self.assertEqual(receipt["ownedEvidence"]["bundleFileCount"], 0)
        self.assertTrue(receipt["ownedEvidence"]["runRootPreserved"])
        self.assertTrue(receipt["ownedEvidence"]["sourceRootPreserved"])
        self.assertFalse(receipt["ownedEvidence"]["cleanupExecuted"])

    def test_yellow_attempt_5_failure_is_owned_by_common_core_and_fail_closed(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_5_FAILURE_PATH)
        failure = receipt["failure"]
        self.assertEqual(
            failure["commonCorePath"],
            "desktop/scripts/verify-updater-signing-contract.ps1",
        )
        self.assertEqual(
            failure["commonCoreSha256"],
            "7a8b480f3fa268fd474c992b1a4d812f3221f4deb76ee06d37692aab3d785117",
        )
        self.assertEqual(failure["failingLine"], 149)
        self.assertFalse(failure["simLocalVerifierPatchAllowed"])
        self.assertFalse(failure["automaticRetryAttempted"])
        self.assertFalse(failure["sameAuthorizationMayBeReused"])
        self.assertTrue(receipt["nextGate"]["requiresUniversalCommonCoreDonor"])
        self.assertTrue(receipt["nextGate"]["requiresNewProductSource"])
        self.assertTrue(receipt["nextGate"]["requiresFreshYellowAuthorization"])
        self.assertFalse(receipt["nextGate"]["buildMayProceedFromThisReceipt"])
        self.assertFalse(receipt["nonClaims"]["artifactCreated"])
        self.assertFalse(receipt["nonClaims"]["releaseReady"])

    def test_yellow_attempt_5_failure_preserves_prior_artifact_and_registry(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_5_FAILURE_PATH)
        protected = receipt["protectedState"]
        self.assertEqual(
            protected["frozenArtifactSha256AfterFailure"],
            "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece",
        )
        self.assertFalse(protected["frozenArtifactMutated"])
        self.assertTrue(protected["historicalSimRegistryPresentAfterFailure"])
        self.assertFalse(protected["historicalSimRegistryMutated"])
        self.assertFalse(protected["updaterKeyContentReadOrPrinted"])
        self.assertFalse(protected["publicSupabaseValuesPrintedOrPersisted"])

    def test_yellow_attempt_6_binds_new_product_source_and_updater_donor(self) -> None:
        application = load_json(YELLOW_ATTEMPT_6_APPLICATION_PATH)
        source = application["sourceSeparation"]
        donor = application["commonCoreAndDonor"]
        self.assertEqual(
            source["productSourceCommit"],
            "a99f5e81893f5001ebd571d09e95b72d8afa070a",
        )
        self.assertEqual(
            git("show", "-s", "--format=%T", source["productSourceCommit"]),
            source["productSourceTree"],
        )
        self.assertEqual(
            donor["updaterSigningStrictModeDonorCommit"],
            "7ce7542991a1edf53105b31588da64b953603c41",
        )
        self.assertEqual(
            git("rev-parse", "HEAD:desktop/scripts/verify-updater-signing-contract.ps1"),
            donor["updaterSigningStrictModeDonorBlob"],
        )
        donor_path = ROOT / donor["updaterSigningStrictModeDonorPath"]
        self.assertEqual(donor_path.stat().st_size, donor["updaterSigningStrictModeDonorBytes"])
        self.assertEqual(
            hashlib.sha256(donor_path.read_bytes()).hexdigest(),
            donor["updaterSigningStrictModeDonorSha256"],
        )

    def test_yellow_attempt_6_freezes_unique_roots_and_single_invocation(self) -> None:
        application = load_json(YELLOW_ATTEMPT_6_APPLICATION_PATH)
        attempt = application["attemptAccounting"]
        owned = application["ownedBuildSurface"]
        maximums = application["executionPlan"]["singleBuildInvocation"]
        self.assertEqual(attempt["globalCommandApplicationOrdinal"], 6)
        self.assertEqual(attempt["sourceApplicationPreflightOrdinal"], 1)
        self.assertEqual(attempt["priorSourceBuildInvocationCount"], 0)
        self.assertEqual(attempt["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(attempt["sourceBuildInvocationMaximum"], 1)
        self.assertFalse(attempt["automaticRetryAllowed"])
        self.assertEqual(owned["sourceRoot"], "C:/Users/zju20/dds6")
        self.assertIn("sim-cargo-target-a99f5e8-ordinal6", owned["cargoTargetDir"])
        self.assertIn("sim-y2-ordinal6-a99f5e8", owned["runRoot"])
        for key in (
            "sourceRootExistsAtPlanFreeze",
            "cargoTargetDirExistsAtPlanFreeze",
            "runRootExistsAtPlanFreeze",
            "bundleRootExistsAtPlanFreeze",
        ):
            self.assertFalse(owned[key], key)
        for key in (
            "buildScriptMaximum",
            "frontendMaximum",
            "tauriMaximum",
            "cargoMaximum",
            "nsisMaximum",
            "artifactMaximum",
        ):
            self.assertEqual(maximums[key], 1, key)
        self.assertEqual(maximums["retryMaximum"], 0)

    def test_yellow_attempt_6_plan_is_non_mutating_and_hash_bound(self) -> None:
        application = load_json(YELLOW_ATTEMPT_6_APPLICATION_PATH)
        plan_receipt = load_json(YELLOW_ATTEMPT_6_PLAN_PATH)
        entry = ROOT / application["executionPlan"]["entryScript"]["path"]
        self.assertEqual(
            hashlib.sha256(YELLOW_ATTEMPT_6_APPLICATION_PATH.read_bytes()).hexdigest(),
            plan_receipt["application"]["sha256"],
        )
        self.assertEqual(
            YELLOW_ATTEMPT_6_APPLICATION_PATH.stat().st_size,
            plan_receipt["application"]["bytes"],
        )
        self.assertEqual(entry.stat().st_size, plan_receipt["entryScript"]["bytes"])
        self.assertEqual(
            hashlib.sha256(entry.read_bytes()).hexdigest(),
            plan_receipt["entryScript"]["sha256"],
        )
        entry_text = entry.read_text(encoding="utf-8")
        self.assertIn(
            "Assert-True (-not (Test-Path -LiteralPath $CargoTargetDir))",
            entry_text,
        )
        self.assertIn(
            "Assert-True (-not (Test-Path -LiteralPath $BundleRoot))",
            entry_text,
        )
        attributes = git(
            "check-attr",
            "eol",
            "--",
            application["executionPlan"]["entryScript"]["path"],
        )
        self.assertTrue(attributes.endswith(": eol: lf"), attributes)
        root_state_before = {
            key: Path(plan_receipt["ownedRoots"][key]).exists()
            for key in ("sourceRoot", "cargoTargetDir", "runRoot", "outputRoot")
        }
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(entry),
                "-Mode",
                "Plan",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["mode"], "Plan")
        self.assertFalse(plan["mutationsPlanned"])
        for key in ("buildScript", "frontend", "tauri", "cargo", "nsis", "artifact"):
            self.assertEqual(plan["invocationMaximums"][key], 1, key)
        self.assertEqual(plan["invocationMaximums"]["retry"], 0)
        for key in ("sourceRoot", "cargoTargetDir", "runRoot", "outputRoot"):
            self.assertTrue(plan_receipt["ownedRoots"][f"{key}AbsentAfterPlan"], key)
            self.assertEqual(
                Path(plan_receipt["ownedRoots"][key]).exists(),
                root_state_before[key],
                key,
            )

    def test_yellow_attempt_6_requires_fresh_authorization_and_preserves_history(self) -> None:
        application = load_json(YELLOW_ATTEMPT_6_APPLICATION_PATH)
        plan = load_json(YELLOW_ATTEMPT_6_PLAN_PATH)
        self.assertFalse(
            application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"]
        )
        self.assertFalse(plan["authorization"]["yellowBuildExecutionAuthorizedByThisReceipt"])
        self.assertTrue(plan["authorization"]["exactChiefControlStartSignalRequired"])
        self.assertTrue(all(value == 0 for value in plan["executedCounts"].values()))
        prior = application["priorCommonCorePrebuildFailure"]
        self.assertEqual(prior["buildDriverInvocations"], 1)
        for key in (
            "frontendBuilds",
            "tauriBuilds",
            "cargoBuilds",
            "nsisBuilds",
            "artifactBuilds",
        ):
            self.assertEqual(prior[key], 0, key)
        self.assertFalse(prior["sameAuthorizationReusable"])
        protected = application["protectedPriorEvidence"]
        self.assertEqual(protected["detachedSourceRoot"], "C:/Users/zju20/dds5")
        self.assertTrue(protected["detachedSourceMustRemainReadOnly"])
        self.assertTrue(protected["ordinalFiveRunRootMustRemainReadOnly"])
        self.assertFalse(protected["reuseAllowed"])
        self.assertFalse(protected["cleanupAllowed"])

    def test_yellow_attempt_6_dependency_failure_consumes_the_only_build_invocation(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_6_FAILURE_PATH)
        binding = receipt["authorizationBinding"]
        execution = receipt["execution"]
        self.assertEqual(receipt["state"], "failed-frozen-no-retry")
        self.assertEqual(binding["globalCommandApplicationOrdinal"], 6)
        self.assertEqual(binding["sourceApplicationPreflightOrdinal"], 1)
        self.assertEqual(binding["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(binding["sourceBuildInvocationMaximum"], 1)
        self.assertTrue(binding["sourceBuildInvocationConsumed"])
        self.assertFalse(binding["retryAllowed"])
        self.assertEqual(execution["buildScriptInvocations"], 1)
        self.assertEqual(execution["npmBuildScriptInvocations"], 1)
        for key in (
            "frontendBuilds",
            "tauriCliProcessInvocations",
            "tauriBuilds",
            "cargoBuilds",
            "nsisBuilds",
            "artifactBuilds",
            "signatureArtifactsCreated",
            "checksumArtifactsCreated",
            "installations",
            "runtimeStarts",
            "px4Starts",
            "gazeboStarts",
            "sitlStarts",
            "hitlStarts",
            "providerActions",
            "hardwareActions",
            "deployments",
            "automaticRetries",
        ):
            self.assertEqual(execution[key], 0, key)

    def test_yellow_attempt_6_failure_is_exactly_bound_and_fail_closed(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_6_FAILURE_PATH)
        binding = receipt["authorizationBinding"]
        for path_key, bytes_key, sha_key in (
            ("applicationPath", "applicationBytes", "applicationSha256"),
            ("entryScriptPath", "entryScriptBytes", "entryScriptSha256"),
            ("planReceiptPath", "planReceiptBytes", "planReceiptSha256"),
        ):
            path = ROOT / binding[path_key]
            self.assertEqual(path.stat().st_size, binding[bytes_key], path_key)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                binding[sha_key],
                path_key,
            )
        failure = receipt["failure"]
        self.assertEqual(
            failure["classification"],
            "detached-source-dependency-provisioning-gap",
        )
        self.assertEqual(failure["lockedTauriCliVersion"], "2.11.4")
        self.assertFalse(failure["desktopNodeModulesPresent"])
        self.assertFalse(failure["desktopTauriCommandPresent"])
        self.assertFalse(failure["simLocalDependencyInstallOrDriverPatchAllowed"])
        self.assertFalse(failure["automaticRetryAttempted"])
        self.assertFalse(failure["sameAuthorizationMayBeReused"])
        self.assertTrue(receipt["nextGate"]["requiresCommonCoreOwnershipDecision"])
        self.assertTrue(receipt["nextGate"]["requiresFreshYellowAuthorization"])
        self.assertFalse(receipt["nextGate"]["buildMayProceedFromThisReceipt"])

    def test_yellow_attempt_6_failure_preserves_owned_and_historical_evidence(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_6_FAILURE_PATH)
        owned = receipt["ownedEvidence"]
        protected = receipt["protectedState"]
        self.assertEqual(owned["bundleFileCount"], 0)
        self.assertFalse(owned["cargoTargetDirExistsAfterFailure"])
        self.assertTrue(owned["sourceCleanAfterFailure"])
        self.assertTrue(owned["sourceWorktreeRegisteredAfterFailure"])
        self.assertTrue(owned["runRootPreserved"])
        self.assertTrue(owned["sourceRootPreserved"])
        self.assertFalse(owned["cleanupExecuted"])
        self.assertEqual(
            protected["frozenArtifactSha256AfterFailure"],
            "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece",
        )
        self.assertFalse(protected["ordinalFiveEvidenceMutated"])
        self.assertFalse(protected["frozenArtifactMutated"])
        self.assertFalse(protected["historicalSimRegistryMutated"])
        self.assertFalse(protected["updaterKeyContentReadOrPrinted"])
        self.assertFalse(protected["publicSupabaseValuesPrintedOrPersisted"])
        self.assertFalse(receipt["nonClaims"]["artifactCreated"])
        self.assertFalse(receipt["nonClaims"]["releaseReady"])

    def test_detached_node_dependency_gap_binds_exact_source_inputs(self) -> None:
        contract = load_json(DETACHED_NODE_DEPENDENCY_GAP_PATH)
        source = contract["failureBinding"]["productSourceCommit"]
        self.assertEqual(source, "a99f5e81893f5001ebd571d09e95b72d8afa070a")
        for item in contract["exactSourceDependencyInputs"].values():
            path = ROOT / item["path"]
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["sha256"],
                item["path"],
            )
            self.assertEqual(
                git("rev-parse", f"{source}:{item['path']}"),
                item["gitBlob"],
                item["path"],
            )
        self.assertEqual(
            contract["exactSourceDependencyInputs"]["desktopPackageLock"][
                "tauriCliVersion"
            ],
            "2.11.4",
        )
        self.assertEqual(
            contract["exactSourceDependencyInputs"]["frontendPackageLock"][
                "viteVersion"
            ],
            "7.3.6",
        )

    def test_detached_node_dependency_gap_selects_attested_external_bundle(self) -> None:
        contract = load_json(DETACHED_NODE_DEPENDENCY_GAP_PATH)
        options = {item["optionId"]: item for item in contract["optionAnalysis"]}
        self.assertEqual(
            options["reuse-canonical-node-modules-by-direct-junction"]["disposition"],
            "rejected-as-default",
        )
        self.assertEqual(
            options["explicit-dependency-root-via-path-or-direct-cli-only"][
                "disposition"
            ],
            "insufficient-alone",
        )
        self.assertEqual(
            options["npm-ci-offline-inside-detached-source"]["disposition"],
            "not-preferred-for-release-build",
        )
        recommended = options["attested-external-bundle-with-two-allowlisted-junctions"]
        self.assertEqual(recommended["disposition"], "recommended")
        self.assertEqual(
            [item["linkRelativeToDetachedSource"] for item in recommended["requiredJunctions"]],
            ["desktop/node_modules", "frontend/node_modules"],
        )
        invariants = contract["invariants"]
        self.assertTrue(invariants["dependencyRootMustBeOutsideEveryGitWorktree"])
        self.assertFalse(invariants["systemOrGlobalInstallationAllowed"])
        self.assertFalse(invariants["networkDuringBuildAllowed"])
        self.assertFalse(invariants["arbitraryJunctionAllowed"])
        self.assertFalse(invariants["reparsePointEscapeAllowed"])
        self.assertFalse(invariants["dependencyTreeIsProductSource"])

    def test_detached_node_dependency_gap_requests_common_core_fail_closed_donor(self) -> None:
        contract = load_json(DETACHED_NODE_DEPENDENCY_GAP_PATH)
        requested = {item["path"] for item in contract["requestedCommonCorePaths"]}
        self.assertEqual(
            requested,
            {
                "distribution/schemas/desktop-node-dependency-bundle.schema.json",
                "desktop/scripts/verify-detached-node-dependencies.ps1",
                "desktop/scripts/build-windows-llvm.ps1",
                "desktop/scripts/release-build-driver.psm1",
                "distribution/tests/test_shared_windows_build_contract.py",
            },
        )
        negative = set(contract["requiredNegativeTests"])
        for required in (
            "product-source-commit-mismatch",
            "desktop-package-lock-hash-mismatch",
            "frontend-package-lock-hash-mismatch",
            "tauri-cli-version-mismatch",
            "dependency-root-inside-any-git-worktree",
            "junction-target-escapes-bundle-root",
            "nested-reparse-point-escapes-bundle-root",
            "dependency-tree-mutates-during-build",
            "system-or-global-tauri-resolves",
            "network-fallback-requested",
            "unknown-edition",
            "node-modules-or-dependency-manifest-enters-installer-bundle",
        ):
            self.assertIn(required, negative)
        self.assertFalse(contract["ownership"]["editionBranchMayImplementBuildSemantics"])
        self.assertEqual(contract["ownership"]["commonCoreBranch"], "codex/software")

    def test_detached_node_dependency_gap_is_green_only_and_cannot_rebuild(self) -> None:
        contract = load_json(DETACHED_NODE_DEPENDENCY_GAP_PATH)
        self.assertTrue(all(value == 0 for value in contract["currentAtomExecution"].values()))
        gate = contract["nextGate"]
        self.assertTrue(gate["exactCommonCoreDonorRequired"])
        self.assertTrue(gate["newExactApplicationRequiredAfterDonorSync"])
        self.assertTrue(gate["freshYellowAuthorizationRequired"])
        self.assertTrue(gate["currentProductSourceMayNotBeRebuiltFromThisRequest"])

    def test_detached_node_dependency_common_core_sync_is_exact_and_green_only(self) -> None:
        receipt = load_json(DETACHED_NODE_DEPENDENCY_SYNC_PATH)
        self.assertEqual(
            receipt["donor"]["productCommit"],
            "b02d593c6c2fc6481bf5b8078b9cf143eb7965d3",
        )
        self.assertEqual(receipt["donor"]["pathCount"], 5)
        self.assertTrue(receipt["donor"]["wholeCommitPathLimited"])
        self.assertFalse(receipt["donor"]["unrelatedHistoryAdopted"])
        self.assertEqual(len(receipt["synchronizedPaths"]), 5)
        for item in receipt["synchronizedPaths"]:
            path = ROOT / item["path"]
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["sha256"],
                item["path"],
            )
            self.assertEqual(
                git("rev-parse", f"HEAD:{item['path']}"),
                item["gitBlob"],
                item["path"],
            )
        self.assertTrue(all(value == 0 for value in receipt["execution"].values()))
        self.assertFalse(receipt["nextGate"]["createDependencyBundleAllowed"])
        self.assertFalse(receipt["nextGate"]["createJunctionsAllowed"])
        self.assertFalse(receipt["nextGate"]["buildAllowed"])

    def test_yellow_attempt_7_binds_exact_product_donor_and_dependency_identity(self) -> None:
        application = load_json(YELLOW_ATTEMPT_7_APPLICATION_PATH)
        source = application["sourceSeparation"]
        self.assertEqual(
            source["productSourceCommit"],
            "e181d029278e50788afe8460ec0cafd9c78a6623",
        )
        self.assertEqual(
            git("show", "-s", "--format=%T", source["productSourceCommit"]),
            source["productSourceTree"],
        )
        donor = application["commonCoreDonor"]
        self.assertEqual(
            donor["productCommit"],
            "b02d593c6c2fc6481bf5b8078b9cf143eb7965d3",
        )
        self.assertEqual(donor["pathCount"], 5)
        for item in donor["paths"]:
            path = ROOT / item["path"]
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["sha256"],
                item["path"],
            )
            self.assertEqual(
                git("rev-parse", f"{source['productSourceCommit']}:{item['path']}"),
                item["gitBlob"],
                item["path"],
            )

        bundle = application["dependencyBundle"]
        identity = "\n".join(bundle["identityInputsInOrder"]).encode()
        expected_id = f"npm-win32-x64-{hashlib.sha256(identity).hexdigest()[:16]}"
        self.assertEqual(bundle["bundleId"], expected_id)
        self.assertEqual(
            bundle["completeTree"]["treeFingerprint"],
            "7f4dc4d394ca98a8458f84f7cc5dfe40603f9fe662e1610d910651d04fbe6aea",
        )
        self.assertEqual(bundle["completeTree"]["entryCount"], 18851)
        self.assertEqual(bundle["completeTree"]["fileCount"], 17339)
        self.assertEqual(bundle["completeTree"]["totalFileBytes"], 263384543)

    def test_yellow_attempt_7_binds_source_locks_tools_and_exact_two_mounts(self) -> None:
        application = load_json(YELLOW_ATTEMPT_7_APPLICATION_PATH)
        bundle = application["dependencyBundle"]
        product = application["sourceSeparation"]["productSourceCommit"]
        for item in bundle["sourceInputs"]:
            path = ROOT / item["path"]
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["sha256"],
                item["path"],
            )
            self.assertEqual(
                git("rev-parse", f"{product}:{item['path']}"),
                item["gitBlob"],
                item["path"],
            )
        tools = bundle["toolchain"]
        self.assertEqual(tools["tauriCliVersion"], "2.11.4")
        self.assertEqual(tools["viteVersion"], "7.3.6")
        self.assertEqual(tools["platformPackageName"], "@tauri-apps/cli-win32-x64-msvc")
        self.assertEqual(tools["platformBinaryBytes"], 15235584)
        self.assertEqual(len(bundle["mounts"]), 2)
        self.assertEqual(
            [mount["linkPath"] for mount in bundle["mounts"]],
            ["desktop/node_modules", "frontend/node_modules"],
        )
        self.assertTrue(all(mount["linkType"] == "junction" for mount in bundle["mounts"]))
        self.assertFalse(bundle["arbitraryJunctionAllowed"])
        self.assertFalse(bundle["dependencyPayloadAllowed"])

    def test_yellow_attempt_7_plan_is_hash_bound_non_mutating_and_unauthorized(self) -> None:
        application = load_json(YELLOW_ATTEMPT_7_APPLICATION_PATH)
        plan = load_json(YELLOW_ATTEMPT_7_PLAN_PATH)
        entry = ROOT / application["executionPlan"]["entryScript"]["path"]
        self.assertEqual(
            YELLOW_ATTEMPT_7_APPLICATION_PATH.stat().st_size,
            plan["application"]["bytes"],
        )
        self.assertEqual(
            hashlib.sha256(YELLOW_ATTEMPT_7_APPLICATION_PATH.read_bytes()).hexdigest(),
            plan["application"]["sha256"],
        )
        self.assertEqual(entry.stat().st_size, plan["entryScript"]["bytes"])
        self.assertEqual(
            hashlib.sha256(entry.read_bytes()).hexdigest(),
            plan["entryScript"]["sha256"],
        )
        attributes = git(
            "check-attr",
            "eol",
            "--",
            application["executionPlan"]["entryScript"]["path"],
        )
        self.assertTrue(attributes.endswith(": eol: lf"), attributes)
        self.assertFalse(
            application["authorization"]["dependencyBundlePreparationAuthorizedByThisApplication"]
        )
        self.assertFalse(
            application["authorization"]["yellowBuildExecutionAuthorizedByThisApplication"]
        )
        self.assertFalse(
            plan["authorization"]["dependencyPreparationAuthorizedByThisReceipt"]
        )
        self.assertFalse(plan["authorization"]["yellowBuildExecutionAuthorizedByThisReceipt"])
        self.assertTrue(all(value == 0 for value in application["executedCounts"].values()))
        self.assertTrue(all(value == 0 for value in plan["executedCounts"].values()))

        roots = application["ownedBuildSurface"]
        before = {
            "source": Path(roots["sourceRoot"]).exists(),
            "run": Path(roots["runRoot"]).exists(),
            "cargo": Path(roots["cargoTargetDir"]).exists(),
            "dependency": Path(application["dependencyBundle"]["dependencyRoot"]).exists(),
        }
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(entry),
                "-Mode",
                "Plan",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["state"], "green-plan-only-no-mutation")
        after = {
            "source": Path(roots["sourceRoot"]).exists(),
            "run": Path(roots["runRoot"]).exists(),
            "cargo": Path(roots["cargoTargetDir"]).exists(),
            "dependency": Path(application["dependencyBundle"]["dependencyRoot"]).exists(),
        }
        self.assertEqual(before, after)
        self.assertTrue(all(not value for value in after.values()))

    def test_yellow_attempt_7_future_commands_are_fail_closed_and_counted(self) -> None:
        application = load_json(YELLOW_ATTEMPT_7_APPLICATION_PATH)
        attempt = application["attemptAccounting"]
        maximums = application["executionPlan"]["maximums"]
        self.assertEqual(attempt["globalCommandApplicationOrdinal"], 7)
        self.assertEqual(attempt["sourceApplicationPreflightOrdinal"], 1)
        self.assertEqual(attempt["dependencyPreparationOrdinal"], 1)
        self.assertEqual(attempt["dependencyPreparationMaximum"], 1)
        self.assertEqual(attempt["npmCiInvocationMaximum"], 2)
        self.assertEqual(attempt["sourceBuildInvocationOrdinal"], 1)
        self.assertEqual(attempt["sourceBuildInvocationMaximum"], 1)
        self.assertFalse(attempt["automaticRetryAllowed"])
        for key in (
            "preflight",
            "dependencyPreparation",
            "buildScript",
            "frontend",
            "tauri",
            "cargo",
            "nsis",
            "artifact",
        ):
            self.assertEqual(maximums[key], 1, key)
        self.assertEqual(maximums["npmCi"], 2)
        self.assertEqual(maximums["junctionCreation"], 2)
        self.assertEqual(maximums["retry"], 0)

        entry = (ROOT / application["executionPlan"]["entryScript"]["path"]).read_text(
            encoding="utf-8"
        )
        self.assertEqual(entry.count("New-Item -ItemType Junction"), 2)
        self.assertIn("-DetachedNodeDependencyManifest $DependencyManifest", entry)
        self.assertIn("npm.cmd --prefix", entry)
        self.assertIn("ci --offline --no-audit --no-fund", entry)
        self.assertIn("Remove-ExactJunction", entry)
        self.assertNotIn("Remove-Item -LiteralPath $DependencyRoot -Recurse", entry)
        self.assertNotIn("git config --global", entry)
        self.assertNotIn("npm install", entry)

    def test_yellow_attempt_7_preserves_ordinal_six_and_frozen_artifact(self) -> None:
        application = load_json(YELLOW_ATTEMPT_7_APPLICATION_PATH)
        protected = application["protectedHistory"]
        self.assertEqual(
            protected["ordinalSixFailureReceiptSha256"],
            "6d223eb0d2d7996b3afba4b0621d95ef9998a499c098ffbe40b1210dcd2a7224",
        )
        failure = ROOT / protected["ordinalSixFailureReceiptPath"]
        self.assertEqual(
            hashlib.sha256(failure.read_bytes()).hexdigest(),
            protected["ordinalSixFailureReceiptSha256"],
        )
        self.assertTrue(protected["priorRootsReadOnly"])
        self.assertFalse(protected["reuseAllowed"])
        self.assertFalse(protected["cleanupAllowed"])
        self.assertEqual(
            protected["frozenArtifact"]["sha256"],
            "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece",
        )
        self.assertFalse(protected["frozenArtifact"]["websiteHandoffAllowed"])

    def test_yellow_attempt_7_cache_drift_failure_is_frozen_before_mutation(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_7_FAILURE_PATH)
        self.assertEqual(receipt["state"], "failed-frozen-no-retry")
        binding = receipt["authorizationBinding"]
        self.assertEqual(binding["globalCommandApplicationOrdinal"], 7)
        self.assertFalse(binding["sameAuthorizationReusable"])
        self.assertFalse(binding["retryAllowed"])
        for path_key, bytes_key, sha_key in (
            ("applicationPath", "applicationBytes", "applicationSha256"),
            ("entryScriptPath", "entryScriptBytes", "entryScriptSha256"),
            ("planReceiptPath", "planReceiptBytes", "planReceiptSha256"),
        ):
            path = ROOT / binding[path_key]
            self.assertEqual(path.stat().st_size, binding[bytes_key], path_key)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                binding[sha_key],
                path_key,
            )

        drift = receipt["cacheDrift"]
        self.assertEqual(drift["fileCountDelta"], -2)
        self.assertEqual(drift["totalBytesDelta"], -4416)
        self.assertNotEqual(drift["expectedFingerprint"], drift["observedFingerprint"])
        self.assertFalse(drift["matchesExpected"])
        self.assertFalse(drift["cacheWriteBySimObserved"])
        self.assertFalse(drift["cacheCleanupBySimObserved"])

        counts = receipt["executionCounts"]
        self.assertEqual(counts["preflightInvocations"], 1)
        for key, value in counts.items():
            if key != "preflightInvocations":
                self.assertEqual(value, 0, key)
        roots = receipt["ownedRootsAfterFailure"]
        self.assertEqual(roots["newOwnedRootCount"], 0)
        self.assertFalse(roots["sourceRootExists"])
        self.assertFalse(roots["dependencyRootExists"])
        self.assertFalse(roots["runRootExists"])
        self.assertFalse(roots["cargoTargetDirExists"])
        self.assertFalse(roots["cleanupExecuted"])

        protected = receipt["protectedHistory"]
        self.assertFalse(protected["priorRootsOrReceiptsMutated"])
        self.assertFalse(protected["frozenArtifactMutated"])
        self.assertEqual(
            protected["frozenArtifactSha256AfterFailure"],
            "f23987bac2af03fd085f981ecd730948e0fe0e831acf639e2bffcb7c31ffbece",
        )
        gate = receipt["nextGate"]
        self.assertFalse(gate["prepareMayProceedFromThisReceipt"])
        self.assertFalse(gate["executeMayProceedFromThisReceipt"])
        self.assertTrue(gate["newExactApplicationRequired"])
        self.assertTrue(gate["newExactYellowAuthorizationRequired"])

    def test_lockfile_offline_cache_contract_ignores_mutable_global_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, cache, fingerprint, _, _ = write_offline_cache_fixture(root)

            def verify() -> dict[str, Any]:
                completed = subprocess.run(
                    [
                        "node",
                        str(LOCKFILE_OFFLINE_CACHE_TOOL),
                        "--mode",
                        "verify-global",
                        "--repo-root",
                        str(repo),
                        "--cache-root",
                        str(cache),
                        "--expected-semantic-fingerprint",
                        fingerprint,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)

            before = verify()
            logs = cache / "_logs"
            logs.mkdir()
            (logs / "mutable-debug.log").write_text("not-a-build-input", encoding="utf-8")
            unrelated = cache / "_cacache" / "content-v2" / "sha512" / "ff" / "ff" / "unused"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_bytes(b"unreferenced")
            after = verify()
            self.assertEqual(before["semanticFingerprint"], after["semanticFingerprint"])
            self.assertEqual(before["contentObjectCount"], 1)
            self.assertEqual(before["indexKeyCount"], 1)
            self.assertIn("_logs", after["ignoredGlobalCacheSurfaces"])
            self.assertEqual(after["networkInvocations"], 0)
            self.assertEqual(after["npmInvocations"], 0)

    def test_lockfile_offline_cache_contract_creates_minimal_owned_fixture_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, cache, fingerprint, _, _ = write_offline_cache_fixture(root)
            owned = root / "owned"
            snapshot = owned / "attempt-cache"
            completed = subprocess.run(
                [
                    "node",
                    str(LOCKFILE_OFFLINE_CACHE_TOOL),
                    "--mode",
                    "create-snapshot",
                    "--repo-root",
                    str(repo),
                    "--cache-root",
                    str(cache),
                    "--expected-semantic-fingerprint",
                    fingerprint,
                    "--owned-base",
                    str(owned),
                    "--snapshot-root",
                    str(snapshot),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(completed.stdout)
            self.assertEqual(receipt["snapshot"]["fileCount"], 2)
            self.assertTrue(snapshot.is_dir())
            self.assertFalse((snapshot / "_logs").exists())
            self.assertFalse((snapshot / "_npx").exists())

            verify = subprocess.run(
                [
                    "node",
                    str(LOCKFILE_OFFLINE_CACHE_TOOL),
                    "--mode",
                    "verify-snapshot",
                    "--repo-root",
                    str(repo),
                    "--cache-root",
                    str(snapshot),
                    "--expected-semantic-fingerprint",
                    fingerprint,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            verified = json.loads(verify.stdout)
            self.assertEqual(
                verified["snapshot"]["fingerprint"],
                receipt["snapshot"]["fingerprint"],
            )

    def test_lockfile_offline_cache_contract_fails_closed_on_required_object_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, cache, fingerprint, content, index = write_offline_cache_fixture(root)
            content.write_bytes(b"tampered")
            tampered = subprocess.run(
                [
                    "node",
                    str(LOCKFILE_OFFLINE_CACHE_TOOL),
                    "--mode",
                    "verify-global",
                    "--repo-root",
                    str(repo),
                    "--cache-root",
                    str(cache),
                    "--expected-semantic-fingerprint",
                    fingerprint,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("integrity drifted", tampered.stderr)

            repo, cache, fingerprint, _, index = write_offline_cache_fixture(root / "second")
            index.write_text("invalid-index-line\n", encoding="utf-8")
            invalid_index = subprocess.run(
                [
                    "node",
                    str(LOCKFILE_OFFLINE_CACHE_TOOL),
                    "--mode",
                    "verify-global",
                    "--repo-root",
                    str(repo),
                    "--cache-root",
                    str(cache),
                    "--expected-semantic-fingerprint",
                    fingerprint,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid_index.returncode, 0)
            self.assertIn("index mapping is invalid", invalid_index.stderr)

    def test_lockfile_offline_cache_tool_has_no_network_or_npm_execution(self) -> None:
        text = LOCKFILE_OFFLINE_CACHE_TOOL.read_text(encoding="utf-8")
        for forbidden in (
            "npm ci",
            "npm install",
            "child_process",
            "fetch(",
            "http.get",
            "https.get",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("COPYFILE_EXCL", text)
        self.assertIn("Snapshot root already exists; retry is forbidden.", text)

    def test_stable_offline_cache_contract_excludes_mutable_global_surfaces(self) -> None:
        contract = load_json(STABLE_OFFLINE_CACHE_CONTRACT_PATH)
        self.assertEqual(contract["state"], "green-contract-verified-no-snapshot-created")
        drift = contract["driftClassification"]
        self.assertEqual(drift["classification"], "whole-cache-nonsemantic-churn")
        self.assertTrue(drift["failureWindowContainsNpmLogCreationOrRotation"])
        self.assertFalse(drift["claimingExactRemovedFilesAllowed"])
        self.assertFalse(drift["productLockOrRequiredTarballDriftObserved"])
        selection = contract["stableSelection"]
        self.assertEqual(selection["compatibleLockRows"], 330)
        self.assertEqual(selection["uniqueResolvedTarballs"], 323)
        self.assertEqual(selection["contentAddressedObjectCount"], 323)
        self.assertEqual(selection["indexKeyCount"], 323)
        self.assertEqual(selection["missingContentObjects"], 0)
        self.assertEqual(selection["missingIndexMappings"], 0)
        self.assertEqual(
            selection["semanticFingerprint"],
            "fa7523cb1a93b4b3626a3b9132139fea8ed7e2c165097a03545b2e58eaf68a91",
        )
        self.assertIn("_logs", selection["excludedFromSelection"])
        self.assertFalse(selection["globalCacheWholeTreeHashRequired"])
        snapshot = contract["attemptOwnedSnapshot"]
        self.assertEqual(snapshot["maximumContentFiles"], 323)
        self.assertEqual(snapshot["maximumIndexFiles"], 323)
        self.assertFalse(snapshot["copyAllGlobalCacheAllowed"])
        self.assertTrue(snapshot["snapshotWholeTreeFingerprintFrozenAfterCopy"])
        self.assertTrue(snapshot["npmLogsMustBeRedirectedOutsideSnapshot"])
        self.assertTrue(all(value == 0 for value in contract["execution"].values()))
        self.assertFalse(contract["nextGate"]["ordinalSevenApplicationReusable"])

    def test_yellow_attempt_8_binds_new_product_and_stable_cache_tool(self) -> None:
        application = load_json(YELLOW_ATTEMPT_8_APPLICATION_PATH)
        source = application["sourceSeparation"]
        self.assertEqual(
            source["productSourceCommit"],
            "f4a0562b0883fadeb662881a6ac593073ed2f99f",
        )
        self.assertEqual(
            git("show", "-s", "--format=%T", source["productSourceCommit"]),
            source["productSourceTree"],
        )
        stable = application["stableCacheContract"]
        for item in (stable["tool"], stable["contract"]):
            path = ROOT / item["path"]
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                item["sha256"],
                item["path"],
            )
            self.assertEqual(
                git("rev-parse", f"{source['productSourceCommit']}:{item['path']}"),
                item["gitBlob"],
                item["path"],
            )
        self.assertEqual(stable["compatibleLockRows"], 330)
        self.assertEqual(stable["contentObjectCount"], 323)
        self.assertEqual(stable["indexKeyCount"], 323)
        self.assertFalse(stable["globalWholeCacheFingerprintRequired"])
        self.assertIn("_logs", stable["ignoredMutableSurfaces"])

    def test_yellow_attempt_8_plan_is_hash_bound_and_non_mutating(self) -> None:
        application = load_json(YELLOW_ATTEMPT_8_APPLICATION_PATH)
        plan = load_json(YELLOW_ATTEMPT_8_PLAN_PATH)
        entry = ROOT / application["executionPlan"]["entryScript"]["path"]
        self.assertEqual(
            YELLOW_ATTEMPT_8_APPLICATION_PATH.stat().st_size,
            plan["application"]["bytes"],
        )
        self.assertEqual(
            hashlib.sha256(YELLOW_ATTEMPT_8_APPLICATION_PATH.read_bytes()).hexdigest(),
            plan["application"]["sha256"],
        )
        self.assertEqual(entry.stat().st_size, plan["entryScript"]["bytes"])
        self.assertEqual(
            hashlib.sha256(entry.read_bytes()).hexdigest(),
            plan["entryScript"]["sha256"],
        )
        attributes = git(
            "check-attr",
            "eol",
            "--",
            application["executionPlan"]["entryScript"]["path"],
        )
        self.assertTrue(attributes.endswith(": eol: lf"), attributes)
        roots = application["ownedBuildSurface"]
        before = {
            "source": Path(roots["sourceRoot"]).exists(),
            "run": Path(roots["runRoot"]).exists(),
            "cargo": Path(roots["cargoTargetDir"]).exists(),
            "snapshot": Path(application["attemptOwnedCacheSnapshot"]["snapshotRoot"]).exists(),
            "dependency": Path(application["dependencyBundle"]["dependencyRoot"]).exists(),
        }
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(entry),
                "-Mode",
                "Plan",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "green-plan-only-no-mutation")
        after = {
            "source": Path(roots["sourceRoot"]).exists(),
            "run": Path(roots["runRoot"]).exists(),
            "cargo": Path(roots["cargoTargetDir"]).exists(),
            "snapshot": Path(application["attemptOwnedCacheSnapshot"]["snapshotRoot"]).exists(),
            "dependency": Path(application["dependencyBundle"]["dependencyRoot"]).exists(),
        }
        self.assertEqual(before, after)
        self.assertTrue(all(not value for value in after.values()))

    def test_yellow_attempt_8_freezes_snapshot_before_build_and_fails_closed(self) -> None:
        application = load_json(YELLOW_ATTEMPT_8_APPLICATION_PATH)
        snapshot = application["attemptOwnedCacheSnapshot"]
        self.assertEqual(snapshot["copyMaximumFiles"], 646)
        self.assertFalse(snapshot["copyEntireGlobalCacheAllowed"])
        self.assertTrue(snapshot["snapshotWholeTreeFingerprintKnownAfterPrepare"])
        self.assertTrue(snapshot["snapshotWholeTreeFingerprintMustMatchBeforeAndAfterNpmCi"])
        self.assertTrue(snapshot["snapshotWholeTreeFingerprintMustMatchBeforeAndAfterBuild"])
        self.assertFalse(snapshot["npmLogsInsideSnapshotAllowed"])
        maximums = application["executionPlan"]["maximums"]
        self.assertEqual(maximums["preflight"], 1)
        self.assertEqual(maximums["snapshotPreparation"], 1)
        self.assertEqual(maximums["selectedCacheFileCopies"], 646)
        self.assertEqual(maximums["npmCi"], 2)
        self.assertEqual(maximums["junctionCreation"], 2)
        for key in ("buildScript", "frontend", "tauri", "cargo", "nsis", "artifact"):
            self.assertEqual(maximums[key], 1, key)
        self.assertEqual(maximums["retry"], 0)
        self.assertTrue(all(value == 0 for value in application["executedCounts"].values()))
        authorization = application["authorization"]
        self.assertFalse(authorization["preflightAuthorizedByThisApplication"])
        self.assertFalse(authorization["prepareAuthorizedByThisApplication"])
        self.assertFalse(authorization["executeAuthorizedByThisApplication"])

        entry = (
            ROOT / application["executionPlan"]["entryScript"]["path"]
        ).read_text(encoding="utf-8")
        self.assertIn("-CacheMode create-snapshot", entry)
        self.assertIn("$env:npm_config_logs_dir = $NpmLogsRoot", entry)
        self.assertIn("-CacheMode verify-snapshot", entry)
        self.assertEqual(entry.count("New-Item -ItemType Junction"), 2)
        self.assertNotIn("Get-FileTreeFingerprint", entry)
        self.assertNotIn("Remove-Item -LiteralPath $SnapshotRoot -Recurse", entry)
        self.assertNotIn("npm install", entry)

    def test_yellow_attempt_8_permanently_rejects_ordinal_7_reuse(self) -> None:
        application = load_json(YELLOW_ATTEMPT_8_APPLICATION_PATH)
        self.assertTrue(application["attemptAccounting"]["ordinalSevenPermanentlyConsumed"])
        protected = application["protectedHistory"]
        self.assertEqual(
            protected["ordinalSevenFailureReceiptSha256"],
            "1c8a47be33a394e3282d33c2871a8284969d60ea977d1fe18a24f0cccfb2cd90",
        )
        self.assertTrue(protected["dds5Dds6AndAllPriorRootsReadOnly"])
        self.assertFalse(protected["reuseRelabelOrWebsiteHandoffAllowed"])
        plan = load_json(YELLOW_ATTEMPT_8_PLAN_PATH)
        self.assertTrue(plan["protectedHistory"]["ordinalSevenPermanentlyConsumed"])
        self.assertFalse(plan["authorization"]["preflightAuthorizedByThisReceipt"])
        self.assertFalse(plan["authorization"]["prepareAuthorizedByThisReceipt"])
        self.assertFalse(plan["authorization"]["executeAuthorizedByThisReceipt"])

    def test_yellow_attempt_8_public_config_failure_stops_before_owned_mutation(self) -> None:
        receipt = load_json(YELLOW_ATTEMPT_8_FAILURE_PATH)
        self.assertEqual(receipt["state"], "failed-frozen-no-retry")
        binding = receipt["authorizationBinding"]
        self.assertEqual(binding["globalCommandApplicationOrdinal"], 8)
        self.assertFalse(binding["sameAuthorizationReusable"])
        self.assertFalse(binding["retryAllowed"])
        for path_key, bytes_key, sha_key in (
            ("applicationPath", "applicationBytes", "applicationSha256"),
            ("entryScriptPath", "entryScriptBytes", "entryScriptSha256"),
            ("planReceiptPath", "planReceiptBytes", "planReceiptSha256"),
        ):
            path = ROOT / binding[path_key]
            self.assertEqual(path.stat().st_size, binding[bytes_key], path_key)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                binding[sha_key],
                path_key,
            )
        public = receipt["publicConfigurationObservation"]
        self.assertFalse(public["viteSupabaseUrlPresentInLaunchingProcess"])
        self.assertFalse(public["viteSupabasePublishableKeyPresentInLaunchingProcess"])
        self.assertFalse(public["valuesRead"])
        self.assertFalse(public["valuesPrinted"])
        self.assertFalse(public["valuesPersisted"])
        stable = receipt["stableCacheObservation"]
        self.assertTrue(stable["stableCacheVerificationCompletedBeforeFailure"])
        self.assertFalse(stable["cacheDriftObserved"])
        counts = receipt["executionCounts"]
        self.assertEqual(counts["preflightInvocations"], 1)
        for key, value in counts.items():
            if key != "preflightInvocations":
                self.assertEqual(value, 0, key)
        roots = receipt["ownedRootsAfterFailure"]
        self.assertEqual(roots["newOwnedRootCount"], 0)
        self.assertFalse(roots["sourceRootExists"])
        self.assertFalse(roots["runRootExists"])
        self.assertFalse(roots["cargoTargetDirExists"])
        self.assertFalse(roots["snapshotRootExists"])
        self.assertFalse(roots["dependencyRootExists"])
        self.assertFalse(roots["cleanupExecuted"])
        self.assertFalse(receipt["protectedHistory"]["frozenArtifactMutated"])
        gate = receipt["nextGate"]
        self.assertFalse(gate["prepareMayProceedFromThisReceipt"])
        self.assertFalse(gate["executeMayProceedFromThisReceipt"])
        self.assertTrue(gate["newExactApplicationRequired"])
        self.assertTrue(gate["newExactYellowAuthorizationRequired"])

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
        dependency_sync = load_json(DETACHED_NODE_DEPENDENCY_SYNC_PATH)
        supplemental_paths.update(
            row["path"] for row in dependency_sync["synchronizedPaths"]
        )
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
