from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    ROOT / "distribution" / "shared" / "external-asset-qualification.v1.json"
)


class ExternalAssetQualificationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_is_shared_and_versioned(self) -> None:
        self.assertEqual(self.contract["schemaVersion"], 1)
        self.assertEqual(
            self.contract["kind"],
            "dronedream-shared-external-asset-qualification-contract",
        )
        self.assertEqual(self.contract["ownerEdition"], "autonomy")
        self.assertEqual(
            self.contract["receivers"],
            ["universal", "sim", "lab", "field", "autonomy"],
        )

    def test_connectors_and_targets_are_not_a_single_fixture(self) -> None:
        self.assertEqual(
            self.contract["sourceKinds"],
            ["file", "directory", "direct_url", "git"],
        )
        self.assertIn("Blender", self.contract["sourceApplications"])
        self.assertIn("Unreal Engine", self.contract["sourceApplications"])
        self.assertEqual(
            self.contract["qualificationTargets"],
            ["ROS 2 Jazzy", "Gazebo Harmonic", "PX4 SITL"],
        )

    def test_modeling_is_external_and_authority_is_fail_closed(self) -> None:
        authority = self.contract["authority"]
        self.assertFalse(authority["builtInModeling"])
        self.assertFalse(authority["frontendIsAuthority"])
        self.assertFalse(authority["importExecutesSourceContent"])
        self.assertFalse(authority["automaticReceiverInstallation"])
        self.assertFalse(authority["modelHarnessStartsOnImport"])
        self.assertFalse(authority["unqualifiedAssetCanExecute"])
        self.assertFalse(authority["grantsSimulationExecution"])
        self.assertFalse(authority["grantsHardwareAuthority"])
        self.assertTrue(authority["hardwareUseRequiresSeparateSignedValidationEvidence"])

    def test_delivery_declares_real_import_and_qualification_surfaces(self) -> None:
        delivery = self.contract["currentDelivery"]
        self.assertTrue(delivery["agentCoreReceiverImplemented"])
        self.assertTrue(delivery["assetVersionRegistryImplemented"])
        self.assertTrue(delivery["qualificationJobLifecycleImplemented"])
        self.assertTrue(delivery["issueAndEvidenceInspectionImplemented"])
        self.assertTrue(delivery["qualifiedPairBindingImplemented"])
        self.assertEqual(delivery["defaultQualifiedMap"], "School Map")
        self.assertEqual(delivery["defaultQualifiedAircraft"], "My Drone")


if __name__ == "__main__":
    unittest.main()
