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
EDITION_PATHS = [
    DISTRIBUTION / "editions" / "sim.v1.json",
    DISTRIBUTION / "editions" / "lab.v1.json",
    DISTRIBUTION / "editions" / "field.v1.json",
]
SCHEMA_PATHS = [
    DISTRIBUTION / "schemas" / "capability-policy.schema.json",
    DISTRIBUTION / "schemas" / "edition-manifest.schema.json",
]

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "distribution_contract_editions",
    DISTRIBUTION / "tools" / "distribution_contract.py",
)
assert CONTRACT_SPEC and CONTRACT_SPEC.loader
distribution_contract = importlib.util.module_from_spec(CONTRACT_SPEC)
sys.modules[CONTRACT_SPEC.name] = distribution_contract
CONTRACT_SPEC.loader.exec_module(distribution_contract)


class EditionCapabilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = distribution_contract.load_capability_policy(POLICY_PATH)
        cls.editions = distribution_contract.load_edition_manifests(
            EDITION_PATHS,
            policy_path=POLICY_PATH,
        )
        cls.capabilities = {
            capability["id"]: capability for capability in cls.policy["capabilities"]
        }

    def test_schemas_are_closed_versioned_draft_2020_contracts(self) -> None:
        for path in SCHEMA_PATHS:
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                schema["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)

    def test_all_editions_bind_the_exact_capability_policy_bytes(self) -> None:
        digest = distribution_contract.sha256_file(POLICY_PATH)
        self.assertEqual(
            digest,
            "d2b880e2ea85ef91980f5f1909485ca2634e68fa763ca885b49b125ec3874903",
        )
        for edition in self.editions.values():
            self.assertEqual(edition["capabilityPolicy"]["sha256"], digest)

    def test_simulated_and_physical_arm_are_separate_capabilities(self) -> None:
        simulated = self.capabilities["simulation.vehicle.arm"]
        physical = self.capabilities["hardware.arm"]
        self.assertEqual(simulated["decisions"]["sim"]["decision"], "conditioned")
        self.assertEqual(physical["decisions"]["sim"]["decision"], "deny")
        self.assertEqual(
            set(physical["requiredEnforcementLayers"]),
            {"backend", "runtime", "native"},
        )

    def test_every_hardware_capability_is_denied_in_sim(self) -> None:
        hardware = [
            capability
            for capability in self.policy["capabilities"]
            if capability["id"].startswith("hardware.")
        ]
        self.assertGreaterEqual(len(hardware), 1)
        self.assertTrue(
            all(capability["decisions"]["sim"]["decision"] == "deny" for capability in hardware)
        )

    def test_real_hardware_actions_are_never_unconditional(self) -> None:
        for capability in self.policy["capabilities"]:
            if "real-hardware" not in capability["targetKinds"]:
                continue
            for edition_id in ("lab", "field"):
                self.assertNotEqual(
                    capability["decisions"][edition_id]["decision"],
                    "allow",
                    capability["id"],
                )

    def test_parameter_write_requires_identity_qualification_rollback_and_human(self) -> None:
        capability = self.capabilities["hardware.parameter.write"]
        required = {
            "hardware-identity-verified",
            "vehicle-pack-compatible",
            "firmware-compatible",
            "trusted-qualification-receipt",
            "rollback-point-valid",
            "operator-confirmed",
        }
        for edition_id in ("lab", "field"):
            self.assertEqual(
                set(capability["decisions"][edition_id]["conditions"]),
                required,
            )

    def test_field_forbids_large_simulator_and_consumes_qualification(self) -> None:
        field = self.editions["field"]
        self.assertIn("runtime-simulation", field["modules"]["forbidden"])
        self.assertIn("simulator-gazebo-harmonic", field["modules"]["forbidden"])
        self.assertFalse(field["runtimeProfile"]["includesLargeSimulator"])
        self.assertTrue(field["qualification"]["mayConsumeTrustedReceipt"])
        self.assertFalse(field["qualification"]["mayIssueSimulationReceipt"])
        self.assertIn("hardware.hitl.execute", field["capabilities"]["forbidden"])
        self.assertEqual(
            self.capabilities["hardware.hitl.execute"]["decisions"]["field"]["decision"],
            "deny",
        )

    def test_hardware_editions_remain_contract_only(self) -> None:
        for edition_id in ("lab", "field"):
            edition = self.editions[edition_id]
            self.assertEqual(edition["implementationStatus"], "contract-only")
            self.assertEqual(edition["validationTier"], "contract-only")
            self.assertGreaterEqual(len(edition["knownGaps"]), 1)

    def test_release_channels_are_planned_not_created_by_contract_commit(self) -> None:
        for edition_id, edition in self.editions.items():
            channel = edition["releaseChannel"]
            self.assertEqual(channel["branch"], f"codex/release-{edition_id}")
            self.assertEqual(channel["creationState"], "planned-not-created")
            self.assertFalse(channel["forcePushAllowed"])

    def test_validator_rejects_frontend_authority(self) -> None:
        invalid = deepcopy(self.policy)
        invalid["frontendIsAuthority"] = True
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "below the frontend",
        ):
            distribution_contract.validate_capability_policy(invalid)

    def test_validator_rejects_missing_native_hardware_fence(self) -> None:
        invalid = deepcopy(self.policy)
        capability = next(
            item for item in invalid["capabilities"] if item["id"] == "hardware.flight"
        )
        capability["requiredEnforcementLayers"].remove("native")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "backend, runtime, and native",
        ):
            distribution_contract.validate_capability_policy(invalid)

    def test_validator_rejects_hardware_permission_in_sim(self) -> None:
        invalid = deepcopy(self.policy)
        capability = next(
            item for item in invalid["capabilities"] if item["id"] == "hardware.arm"
        )
        capability["decisions"]["sim"] = {
            "decision": "conditioned",
            "conditions": ["hardware-identity-verified"],
            "reason": "unsafe test mutation",
        }
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "must be denied by the Sim edition",
        ):
            distribution_contract.validate_capability_policy(invalid)

    def test_validator_rejects_hitl_execution_in_field(self) -> None:
        invalid = deepcopy(self.policy)
        capability = next(
            item
            for item in invalid["capabilities"]
            if item["id"] == "hardware.hitl.execute"
        )
        capability["decisions"]["field"] = {
            "decision": "conditioned",
            "conditions": ["trusted-qualification-receipt"],
            "reason": "unsafe test mutation",
        }
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "must be denied by the Field edition",
        ):
            distribution_contract.validate_capability_policy(invalid)

    def test_validator_rejects_null_decision_conditions(self) -> None:
        invalid = deepcopy(self.policy)
        invalid["capabilities"][0]["decisions"]["sim"]["conditions"] = None
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "conditions must be a list",
        ):
            distribution_contract.validate_capability_policy(invalid)

    def test_validator_rejects_edition_capability_drift(self) -> None:
        invalid = deepcopy(self.editions["sim"])
        invalid["capabilities"]["forbidden"].remove("hardware.arm")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "drifted from policy decisions",
        ):
            distribution_contract.validate_edition_manifest(
                invalid,
                policy=self.policy,
                policy_sha256=distribution_contract.sha256_file(POLICY_PATH),
            )

    def test_validator_rejects_field_simulator_install(self) -> None:
        invalid = deepcopy(self.editions["field"])
        invalid["modules"]["forbidden"].remove("runtime-simulation")
        invalid["modules"]["required"].append("runtime-simulation")
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "Field must remain lightweight",
        ):
            distribution_contract.validate_edition_manifest(
                invalid,
                policy=self.policy,
                policy_sha256=distribution_contract.sha256_file(POLICY_PATH),
            )

    def test_validator_rejects_null_optional_modules(self) -> None:
        invalid = deepcopy(self.editions["sim"])
        invalid["modules"]["optional"] = None
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "edition.modules.optional must be a list",
        ):
            distribution_contract.validate_edition_manifest(
                invalid,
                policy=self.policy,
                policy_sha256=distribution_contract.sha256_file(POLICY_PATH),
            )

    def test_validator_rejects_policy_byte_drift(self) -> None:
        invalid = deepcopy(self.editions["sim"])
        invalid["capabilityPolicy"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            distribution_contract.DistributionContractError,
            "hash or version drifted",
        ):
            distribution_contract.validate_edition_manifest(
                invalid,
                policy=self.policy,
                policy_sha256=distribution_contract.sha256_file(POLICY_PATH),
            )


if __name__ == "__main__":
    unittest.main()
