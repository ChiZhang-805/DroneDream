from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
POLICY_PATH = DISTRIBUTION / "capabilities" / "core-capabilities.v1.json"
INVENTORY_PATH = DISTRIBUTION / "upstream-sources.v1.json"
EDITION_PATH = DISTRIBUTION / "editions" / "sim.v1.json"
VEHICLE_PACK_PATH = (
    DISTRIBUTION / "tests" / "fixtures" / "vehicle-pack-contract-only.v1.json"
)
COMPOSITE_PATH = (
    DISTRIBUTION / "tests" / "fixtures" / "composite-sim-planned.v1.json"
)
FIXTURE_PATH = (
    DISTRIBUTION / "tests" / "fixtures" / "release-promotion-sim-planned.v1.json"
)
SCHEMA_PATH = DISTRIBUTION / "schemas" / "release-promotion-manifest.schema.json"
SOURCE_COMMIT = "6b50f86ed80c190b816f19d06de143a328bda7e2"

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "distribution_contract_promotion",
    DISTRIBUTION / "tools" / "distribution_contract.py",
)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
distribution_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = distribution_contract
CONTRACT_SPEC.loader.exec_module(distribution_contract)


class ReleasePromotionContractTests(unittest.TestCase):
    edition: ClassVar[dict[str, Any]]
    composite: ClassVar[dict[str, Any]]
    fixture: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        policy = distribution_contract.load_capability_policy(POLICY_PATH)
        cls.edition = distribution_contract.validate_edition_manifest(
            json.loads(EDITION_PATH.read_text(encoding="utf-8")),
            policy=policy,
            policy_sha256=distribution_contract.sha256_file(POLICY_PATH),
        )
        vehicle_packs = distribution_contract.load_vehicle_pack_manifests(
            [VEHICLE_PACK_PATH],
            upstream_inventory_path=INVENTORY_PATH,
            capability_policy_path=POLICY_PATH,
        )
        cls.composite = distribution_contract.validate_composite_installation_manifest(
            json.loads(COMPOSITE_PATH.read_text(encoding="utf-8")),
            edition=cls.edition,
            edition_manifest_sha256=distribution_contract.sha256_file(EDITION_PATH),
            vehicle_packs=vehicle_packs,
            vehicle_pack_manifest_sha256={
                "fixture-x500-contract": distribution_contract.sha256_file(VEHICLE_PACK_PATH)
            },
            expected_source_commit=SOURCE_COMMIT,
        )
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def validate(
        self,
        document: object,
        *,
        observed_branch_head: str | None = SOURCE_COMMIT,
        observed_metadata_only_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        return distribution_contract.validate_release_promotion_manifest(
            document,
            edition=self.edition,
            edition_manifest_sha256=distribution_contract.sha256_file(EDITION_PATH),
            composite=self.composite,
            composite_manifest_sha256=distribution_contract.sha256_file(COMPOSITE_PATH),
            observed_branch_head=observed_branch_head,
            observed_metadata_only_paths=observed_metadata_only_paths,
        )

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
        self.assertTrue(schema["properties"]["branchPolicy"]["properties"]["prOnly"]["const"])
        self.assertFalse(
            schema["properties"]["branchPolicy"]["properties"]["forcePushAllowed"]["const"]
        )

    def test_planned_fixture_binds_source_without_claiming_a_release(self) -> None:
        validated = self.validate(deepcopy(self.fixture))
        self.assertEqual(validated["state"], "planned")
        self.assertEqual(validated["sourceCommit"], SOURCE_COMMIT)
        self.assertEqual(validated["branchPolicy"]["creationState"], "long-lived-product-branch")
        self.assertEqual(validated["artifact"]["bytes"], 0)

    def test_validator_rejects_source_or_common_core_drift(self) -> None:
        for field, message in (
            ("sourceCommit", "source drifted"),
            ("commonCoreHash", "common core drifted"),
        ):
            with self.subTest(field=field):
                invalid = deepcopy(self.fixture)
                invalid[field] = "0" * (40 if field == "sourceCommit" else 64)
                with self.assertRaisesRegex(
                    distribution_contract.DistributionContractError, message
                ):
                    self.validate(invalid)

    def test_validator_rejects_edition_or_artifact_name_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["edition"]["editionManifestSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "edition binding drifted"
        ):
            self.validate(invalid)
        invalid = deepcopy(self.fixture)
        invalid["artifact"]["fileName"] = "DroneDream-Lab-1.0.0.exe"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "filename drifted"
        ):
            self.validate(invalid)

    def test_validator_rejects_unsafe_branch_policy(self) -> None:
        for field, value in (("prOnly", False), ("forcePushAllowed", True)):
            with self.subTest(field=field):
                invalid = deepcopy(self.fixture)
                invalid["branchPolicy"][field] = value
                with self.assertRaisesRegex(
                    distribution_contract.DistributionContractError,
                    "PR-only and forbid force-push",
                ):
                    self.validate(invalid)

    def test_exact_source_rejects_changed_paths_or_different_head(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["branchPolicy"]["metadataOnlyChangedPaths"] = [
            "distribution/promotions/sim.v1.json"
        ]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "no changed paths"
        ):
            self.validate(invalid)
        invalid = deepcopy(self.fixture)
        invalid["branchPolicy"]["proposedHeadCommit"] = "a" * 40
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "must use sourceCommit"
        ):
            self.validate(invalid)

    def test_metadata_only_requires_observed_allowlisted_exact_diff(self) -> None:
        document = deepcopy(self.fixture)
        document["branchPolicy"].update(
            {
                "proposedHeadCommit": "a" * 40,
                "headClassification": "edition-metadata-only",
                "metadataOnlyChangedPaths": ["distribution/promotions/sim.v1.json"],
            }
        )
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "requires observed Git"
        ):
            self.validate(document)
        self.validate(
            document,
            observed_branch_head="a" * 40,
            observed_metadata_only_paths=["distribution/promotions/sim.v1.json"],
        )
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "drifted from observed Git diff"
        ):
            self.validate(
                document,
                observed_branch_head="a" * 40,
                observed_metadata_only_paths=["distribution/promotions/other.v1.json"],
            )
        invalid = deepcopy(document)
        invalid["branchPolicy"]["metadataOnlyChangedPaths"] = ["backend/app/main.py"]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "outside the allowlist"
        ):
            self.validate(
                invalid,
                observed_branch_head="a" * 40,
                observed_metadata_only_paths=["backend/app/main.py"],
            )

    def test_long_lived_branch_requires_matching_observed_head(self) -> None:
        document = deepcopy(self.fixture)
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "requires an independently observed"
        ):
            self.validate(document, observed_branch_head=None)
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "branch head drifted"
        ):
            self.validate(document, observed_branch_head="a" * 40)
        self.validate(document, observed_branch_head=SOURCE_COMMIT)

    def test_component_vehicle_capability_and_notice_drift_fail_closed(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["runtimeBase"]["artifactSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "runtimeBase drifted"
        ):
            self.validate(invalid)
        invalid = deepcopy(self.fixture)
        invalid["vehiclePacks"][0]["manifestSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "Vehicle Packs drifted"
        ):
            self.validate(invalid)
        invalid = deepcopy(self.fixture)
        invalid["capabilities"] = []
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "capabilities must be a non-empty list",
        ):
            self.validate(invalid)
        invalid = deepcopy(self.fixture)
        invalid["licenseNotice"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "license notice drifted"
        ):
            self.validate(invalid)

    def test_planned_and_promotable_states_fail_closed(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["blockers"] = []
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "must explain blockers"
        ):
            self.validate(invalid)
        invalid = deepcopy(self.fixture)
        invalid["state"] = "promotable"
        invalid["blockers"] = []
        invalid["branchPolicy"]["creationState"] = "long-lived-product-branch"
        invalid["artifact"]["bytes"] = 1
        invalid["artifact"]["updaterSignatureState"] = "verified"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "installable composite"
        ):
            self.validate(invalid, observed_branch_head=SOURCE_COMMIT)

    def test_rollback_must_reference_a_superseded_promotion(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["rollback"]["targetPromotionId"] = "old-sim"
        invalid["rollback"]["targetArtifactSha256"] = "a" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "first promotion cannot"
        ):
            self.validate(invalid)
        valid = deepcopy(self.fixture)
        valid["supersedes"] = [
            {"promotionId": "old-sim", "artifactSha256": "a" * 64}
        ]
        valid["rollback"]["targetPromotionId"] = "old-sim"
        valid["rollback"]["targetArtifactSha256"] = "a" * 64
        self.validate(valid)

    def test_four_product_edition_set_requires_one_source_and_common_core(self) -> None:
        promotions = []
        for edition_id in sorted(distribution_contract.EDITION_IDS):
            promotion = deepcopy(self.fixture)
            promotion["edition"]["editionId"] = edition_id
            promotions.append(promotion)
        distribution_contract.validate_release_promotion_set(promotions)
        invalid = deepcopy(promotions)
        invalid[1]["sourceCommit"] = "a" * 40
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "source commits diverged"
        ):
            distribution_contract.validate_release_promotion_set(invalid)
        invalid = deepcopy(promotions)
        invalid[2]["commonCoreHash"] = "c" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError, "common core hashes diverged"
        ):
            distribution_contract.validate_release_promotion_set(invalid)


if __name__ == "__main__":
    unittest.main()
