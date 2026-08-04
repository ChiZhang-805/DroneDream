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
SCHEMA_PATH = DISTRIBUTION / "schemas" / "vehicle-pack-manifest.schema.json"
FIXTURE_PATH = DISTRIBUTION / "tests" / "fixtures" / "vehicle-pack-contract-only.v1.json"

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "distribution_contract_vehicle_pack",
    DISTRIBUTION / "tools" / "distribution_contract.py",
)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
distribution_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = distribution_contract
CONTRACT_SPEC.loader.exec_module(distribution_contract)


class VehiclePackContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy_sha256 = distribution_contract.sha256_file(POLICY_PATH)
        cls.inventory = distribution_contract.load_upstream_source_inventory(INVENTORY_PATH)
        cls.fixture = distribution_contract.load_vehicle_pack_manifests(
            [FIXTURE_PATH],
            upstream_inventory_path=INVENTORY_PATH,
            capability_policy_path=POLICY_PATH,
        )["fixture-x500-contract"]

    def validate(
        self,
        document: object,
        *,
        verified_signature_payload_sha256: str | None = None,
    ) -> dict[str, object]:
        return distribution_contract.validate_vehicle_pack_manifest(
            document,
            upstream_inventory=self.inventory,
            capability_policy_sha256=self.policy_sha256,
            verified_signature_payload_sha256=verified_signature_payload_sha256,
        )

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
        self.assertEqual(schema["properties"]["kind"]["const"], "dronedream-vehicle-pack")

    def test_fixture_is_explicitly_contract_only_and_unsigned(self) -> None:
        self.assertEqual(self.fixture["validationStatus"], "contract-only")
        self.assertEqual(self.fixture["validationTier"], "contract-only")
        self.assertEqual(self.fixture["integrity"]["signature"]["state"], "not-issued")
        self.assertIn("Synthetic contract fixture", self.fixture["knownGaps"][0])

    def test_validator_rejects_unknown_upstream_source(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["sourceBindings"][0]["sourceId"] = "unreviewed-source"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "unknown or duplicated",
        ):
            self.validate(invalid)

    def test_validator_rejects_unbound_component_source(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["components"]["sim"]["sourceIds"].append("gazebo-harmonic")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "unbound source",
        ):
            self.validate(invalid)

    def test_validator_rejects_reviewed_source_pin_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["sourceBindings"][0]["pinSha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "drifted from upstream inventory",
        ):
            self.validate(invalid)

    def test_validator_rejects_validated_claim_without_signature_or_evidence(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["validationStatus"] = "validated"
        invalid["validationTier"] = "sim-validated"
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "requires signed payload and validation artifacts",
        ):
            self.validate(invalid)

    def test_validator_rejects_hardware_validated_claim_without_hardware(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["validationStatus"] = "validated"
        invalid["validationTier"] = "hardware-validated"
        invalid["integrity"]["signature"] = {
            "state": "verified",
            "algorithm": "Ed25519",
            "keyId": "ed25519:" + "3" * 64,
            "detachedSignatureSha256": "4" * 64,
        }
        invalid["components"]["validation"]["artifacts"] = [
            {
                "path": "validation/receipt.json",
                "sizeBytes": 128,
                "sha256": "5" * 64,
                "licenseIds": ["px4-bsd-3-clause"],
            }
        ]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "requires hardware artifacts and controllers",
        ):
            self.validate(
                invalid,
                verified_signature_payload_sha256=invalid["integrity"]["payloadSha256"],
            )

    def test_validator_rejects_self_asserted_signature_without_verifier(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["validationStatus"] = "validated"
        invalid["validationTier"] = "sim-validated"
        invalid["integrity"]["signature"] = {
            "state": "verified",
            "algorithm": "Ed25519",
            "keyId": "ed25519:" + "3" * 64,
            "detachedSignatureSha256": "4" * 64,
        }
        invalid["components"]["validation"]["artifacts"] = [
            {
                "path": "validation/receipt.json",
                "sizeBytes": 128,
                "sha256": "5" * 64,
                "licenseIds": ["px4-bsd-3-clause"],
            }
        ]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "external cryptographic signature verification",
        ):
            self.validate(invalid)

    def test_validator_rejects_frontend_safety_authority(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["safety"]["frontendIsAuthority"] = True
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "safety authority drifted",
        ):
            self.validate(invalid)

    def test_validator_rejects_capability_policy_drift(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["safety"]["capabilityPolicySha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "safety authority drifted",
        ):
            self.validate(invalid)

    def test_validator_rejects_inverted_parameter_bounds(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["safety"]["parameterBounds"][0]["minimum"] = 2.0
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "invalid bounds",
        ):
            self.validate(invalid)

    def test_validator_rejects_null_artifact_list(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["components"]["sim"]["artifacts"] = None
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "artifacts must be a list",
        ):
            self.validate(invalid)

    def test_validator_rejects_path_traversal(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["components"]["validation"]["artifacts"] = [
            {
                "path": "../outside.bin",
                "sizeBytes": 1,
                "sha256": "6" * 64,
                "licenseIds": ["px4-bsd-3-clause"],
            }
        ]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "unsafe or duplicated",
        ):
            self.validate(invalid)

    def test_validator_rejects_unknown_artifact_license(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["components"]["validation"]["artifacts"] = [
            {
                "path": "validation/receipt.json",
                "sizeBytes": 1,
                "sha256": "7" * 64,
                "licenseIds": ["undeclared-license"],
            }
        ]
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "unknown license",
        ):
            self.validate(invalid)

    def test_validator_rejects_false_signature_metadata(self) -> None:
        invalid = deepcopy(self.fixture)
        invalid["integrity"]["signature"]["keyId"] = "ed25519:" + "8" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "must not imply trust",
        ):
            self.validate(invalid)


if __name__ == "__main__":
    unittest.main()
