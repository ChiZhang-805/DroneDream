from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
POLICY_PATH = DISTRIBUTION / "capabilities" / "core-capabilities.v1.json"
INVENTORY_PATH = DISTRIBUTION / "upstream-sources.v1.json"
EDITION_PATH = DISTRIBUTION / "editions" / "sim.v1.json"
VEHICLE_PACK_PATH = (
    DISTRIBUTION / "tests" / "fixtures" / "vehicle-pack-contract-only.v1.json"
)
FIXTURE_PATH = DISTRIBUTION / "tests" / "fixtures" / "composite-sim-planned.v1.json"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "composite-installation-manifest.schema.json"
SOURCE_COMMIT = "6b50f86ed80c190b816f19d06de143a328bda7e2"

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "distribution_contract_composite",
    DISTRIBUTION / "tools" / "distribution_contract.py",
)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
distribution_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = distribution_contract
CONTRACT_SPEC.loader.exec_module(distribution_contract)


class CompositeInstallationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        policy = distribution_contract.load_capability_policy(POLICY_PATH)
        cls.edition = distribution_contract.validate_edition_manifest(
            json.loads(EDITION_PATH.read_text(encoding="utf-8")),
            policy=policy,
            policy_sha256=distribution_contract.sha256_file(POLICY_PATH),
        )
        cls.edition_sha256 = distribution_contract.sha256_file(EDITION_PATH)
        cls.vehicle_packs = distribution_contract.load_vehicle_pack_manifests(
            [VEHICLE_PACK_PATH],
            upstream_inventory_path=INVENTORY_PATH,
            capability_policy_path=POLICY_PATH,
        )
        cls.vehicle_pack_shas = {
            "fixture-x500-contract": distribution_contract.sha256_file(VEHICLE_PACK_PATH)
        }
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def validate(self, document: object) -> dict[str, object]:
        return distribution_contract.validate_composite_installation_manifest(
            document,
            edition=self.edition,
            edition_manifest_sha256=self.edition_sha256,
            vehicle_packs=self.vehicle_packs,
            vehicle_pack_manifest_sha256=self.vehicle_pack_shas,
            expected_source_commit=SOURCE_COMMIT,
        )

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)

    def test_planned_fixture_binds_all_layers_but_is_not_installable(self) -> None:
        validated = self.validate(deepcopy(self.fixture))
        self.assertEqual(validated["sourceCommit"], SOURCE_COMMIT)
        self.assertEqual(validated["edition"]["editionId"], "sim")
        self.assertEqual(validated["installability"]["state"], "planned")
        self.assertEqual(
            validated["vehiclePacks"][0]["validationTier"],
            "contract-only",
        )

    def test_validator_rejects_source_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["sourceCommit"] = "0" * 40
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "drifted from expected source",
        ):
            self.validate(invalid)

    def test_validator_rejects_edition_manifest_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["edition"]["manifestSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "edition reference drifted",
        ):
            self.validate(invalid)

    def test_validator_rejects_desktop_or_engine_source_drift(self) -> None:
        for component_id in ("desktop", "enginePack"):
            with self.subTest(component_id=component_id):
                invalid = deepcopy(self.fixture)
                invalid["components"][component_id]["sourceCommit"] = "0" * 40
                with self.assertRaisesRegex(
                    distribution_contract.DistributionContractError,
                    "must bind the common sourceCommit",
                ):
                    self.validate(invalid)

    def test_validator_allows_explicitly_versioned_runtime_base_source(self) -> None:
        valid = deepcopy(self.fixture)
        valid["components"]["runtimeBase"]["sourceCommit"] = "9" * 40
        self.validate(valid)

    def test_validator_rejects_missing_required_module(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["selectedModules"].remove("simulator-px4-sitl")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "selectedModules violate edition policy",
        ):
            self.validate(invalid)

    def test_validator_rejects_forbidden_module(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["selectedModules"].append("hardware-bridge")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "selectedModules violate edition policy",
        ):
            self.validate(invalid)

    def test_validator_rejects_capability_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["capabilities"].remove("simulation.vehicle.arm")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "capabilities drifted from edition",
        ):
            self.validate(invalid)

    def test_validator_rejects_vehicle_manifest_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["vehiclePacks"][0]["manifestSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "drifted from Vehicle Pack manifest",
        ):
            self.validate(invalid)

    def test_validator_rejects_download_size_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["resourceEstimate"]["downloadBytes"] += 1
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "downloadBytes do not match artifacts",
        ):
            self.validate(invalid)

    def test_validator_rejects_planned_state_without_blockers(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["installability"]["blockers"] = []
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "planned composite must explain its blockers",
        ):
            self.validate(invalid)

    def test_validator_rejects_installable_claim_for_contract_only_pack(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["installability"]["state"] = "installable"
        invalid["installability"]["blockers"] = []
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "requires validated signed Vehicle Packs",
        ):
            self.validate(invalid)

    def test_validator_rejects_physical_capability_in_sim(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["installability"]["physicalCapabilityStatus"] = "contract-only"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "Sim physical capabilities must be disabled",
        ):
            self.validate(invalid)

    def test_validator_rejects_license_path_traversal(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["licenseNotice"]["path"] = "../NOTICE.md"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "license notice path is unsafe",
        ):
            self.validate(invalid)


if __name__ == "__main__":
    unittest.main()
