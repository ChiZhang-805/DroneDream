from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "distribution" / "schemas" / "vehicle-pack-draft-envelope.schema.json"
CONTRACT_PATH = ROOT / "distribution" / "universal" / "vehicle-studio.v1.json"


class VehicleStudioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_schema_is_closed_and_versioned(self) -> None:
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(self.schema["additionalProperties"])
        payload = self.schema["properties"]["payload"]
        self.assertFalse(payload["additionalProperties"])
        self.assertEqual(payload["properties"]["schemaVersion"]["const"], 1)
        self.assertEqual(
            payload["properties"]["kind"]["const"],
            "dronedream-vehicle-pack-draft-envelope",
        )
        model = self.schema["$defs"]["model"]["properties"]
        self.assertEqual(model["sensors"]["maxItems"], 32)
        self.assertEqual(model["body"]["properties"]["massKg"]["maximum"], 1000)
        self.assertEqual(
            model["propulsion"]["properties"]["maximumThrustPerMotorN"]["maximum"],
            100000,
        )
        self.assertEqual(
            model["controlTarget"]["properties"]["parameterFamilies"]["maxItems"],
            64,
        )
        self.assertTrue(
            model["controlTarget"]["properties"]["parameterFamilies"]["uniqueItems"]
        )

    def test_authority_is_fail_closed(self) -> None:
        authority = self.schema["properties"]["payload"]["properties"]["authority"]["properties"]
        self.assertTrue(authority["draftOnly"]["const"])
        for field in (
            "signed",
            "validated",
            "frontendIsAuthority",
            "grantsSimulationExecution",
            "grantsHardwareAuthority",
        ):
            self.assertFalse(authority[field]["const"])
        self.assertTrue(
            self.contract["authority"]["hardwareUseRequiresSignedValidationEvidence"]
        )

    def test_contract_routes_to_exactly_three_professional_editions(self) -> None:
        self.assertEqual(self.contract["ownerEdition"], "universal")
        self.assertEqual(self.contract["receivers"], ["sim", "lab", "field", "autonomy"])
        self.assertEqual(
            self.contract["transport"]["schemaPath"],
            "distribution/schemas/vehicle-pack-draft-envelope.schema.json",
        )
        self.assertEqual(
            self.contract["requiredReceiverSequence"][-1],
            "promote-through-signed-vehicle-pack-pipeline",
        )
        inspection = self.contract["commonCoreReceiverInspection"]
        self.assertTrue(inspection["implemented"])
        self.assertFalse(inspection["receiverInspectionIsAuthority"])
        self.assertEqual(inspection["decision"], "verified-draft-only")

    def test_contract_does_not_overstate_current_delivery(self) -> None:
        boundary = self.contract["currentBoundary"]
        self.assertTrue(boundary["localRevisionLibrary"])
        self.assertTrue(boundary["fileExportImport"])
        self.assertTrue(boundary["generatedGazeboGeometrySdf"])
        self.assertFalse(boundary["generatedGeometryIsExecutionReady"])
        self.assertFalse(boundary["cloudPackRegistryPublish"])
        self.assertFalse(boundary["automaticEditionInstallation"])
        self.assertEqual(boundary["validatedVehiclePacks"], 0)


if __name__ == "__main__":
    unittest.main()
