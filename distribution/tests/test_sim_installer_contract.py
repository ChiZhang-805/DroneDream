from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "distribution" / "sim" / "build-profile.v1.json"
SCHEMA_PATH = ROOT / "distribution" / "sim" / "schemas" / "sim-installer-receipt.schema.json"
TOOL_PATH = ROOT / "distribution" / "sim" / "tools" / "sim_installer_contract.py"

SPEC = importlib.util.spec_from_file_location("sim_installer_contract", TOOL_PATH)
assert SPEC and SPEC.loader
sim_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sim_contract
SPEC.loader.exec_module(sim_contract)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class SimInstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = sim_contract.validate_build_profile(
            load_json(PROFILE_PATH),
            repo_root=ROOT,
        )
        cls.profile_sha256 = sim_contract.sha256_file(PROFILE_PATH)

    def receipt(self, artifact_bytes: bytes = b"MZ DroneDream Sim fixture\n") -> dict[str, Any]:
        payload = self.profile["deterministicPayload"]
        return {
            "schemaVersion": 1,
            "kind": "dronedream-sim-installer-adoption-receipt",
            "receiptVersion": "1.0.0",
            "editionId": "sim",
            "profile": {
                "path": "distribution/sim/build-profile.v1.json",
                "sha256": self.profile_sha256,
            },
            "source": {
                "sourceCommit": "1eb697510d57d5565617e3cb54ef1754daedfebb",
                "sourceTreeState": "clean",
                "commonCoreCommit": self.profile["source"]["commonCoreCommit"],
                "commonCoreHash": self.profile["source"]["commonCoreHash"],
            },
            "artifact": {
                "fileName": "DroneDream-Sim-1.0.0.exe",
                "sha256": sha256_bytes(artifact_bytes),
                "bytes": len(artifact_bytes),
                "authenticodeState": "not-signed",
                "unsignedDisclosure": True,
                "updaterSignatureState": "not-issued",
            },
            "payload": {
                "modules": payload["allowedModules"],
                "capabilities": payload["allowedCapabilities"],
                "vehiclePacks": payload["allowedVehiclePacks"],
                "commandAudit": {
                    "scannedCommandCount": 2,
                    "observedCommands": [
                        "install runtime-simulation simulator-px4-sitl",
                        "install vehicle-pack-sim px4-gazebo-x500-reference",
                    ],
                    "forbiddenFindings": [],
                },
            },
            "licenseNotice": deepcopy(self.profile["manifests"]["licenseNotice"]),
            "installLifecycle": {
                "upgradePlan": self.profile["installerPlan"]["upgradePolicy"],
                "rollbackPlan": self.profile["installerPlan"]["rollbackPolicy"],
                "uninstallPlan": self.profile["installerPlan"]["uninstallPolicy"],
            },
            "handoff": {
                "universalReceiptSha256": "a" * 64,
                "universalArtifactSha256": "b" * 64,
                "universalSourceCommit": "db7592fbfc39c5489bdbcc7d2373d1480a69897b",
                "acceptedBy": "codex/software-sim",
            },
        }

    def validate(self, receipt: object, artifact_bytes: bytes | None = None) -> dict[str, Any]:
        if artifact_bytes is None:
            return sim_contract.validate_adoption_receipt(
                receipt,
                profile=self.profile,
                profile_path=PROFILE_PATH,
            )
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "DroneDream-Sim-1.0.0.exe"
            artifact.write_bytes(artifact_bytes)
            return sim_contract.validate_adoption_receipt(
                receipt,
                profile=self.profile,
                profile_path=PROFILE_PATH,
                artifact_path=artifact,
            )

    def test_receipt_schema_is_closed_and_sim_only(self) -> None:
        schema = load_json(SCHEMA_PATH)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["editionId"]["const"], "sim")
        self.assertEqual(
            schema["properties"]["artifact"]["properties"]["fileName"]["const"],
            "DroneDream-Sim-1.0.0.exe",
        )

    def test_build_profile_is_deterministic_sim_only_and_read_only(self) -> None:
        payload = self.profile["deterministicPayload"]
        self.assertEqual(payload["allowedVehiclePacks"], ["px4-gazebo-x500-reference"])
        self.assertEqual(set(payload["forbiddenEditionIds"]), {"lab", "field"})
        self.assertNotIn("hardware-bridge", payload["allowedModules"])
        self.assertIn("hardware-bridge", payload["forbiddenModules"])
        self.assertIn("hardware.arm", payload["forbiddenCapabilities"])
        self.assertFalse(self.profile["resourceProtocol"]["buildAllowed"])
        self.assertFalse(self.profile["resourceProtocol"]["apiKeyUseAllowed"])

    def test_valid_receipt_binds_exact_artifact_bytes_and_source(self) -> None:
        artifact = b"MZ DroneDream Sim fixture\n"
        validated = self.validate(self.receipt(artifact), artifact)
        self.assertEqual(validated["editionId"], "sim")
        self.assertEqual(validated["artifact"]["bytes"], len(artifact))

    def test_rejects_wrong_edition_or_filename(self) -> None:
        invalid = self.receipt()
        invalid["editionId"] = "lab"
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "identity"):
            self.validate(invalid)
        invalid = self.receipt()
        invalid["artifact"]["fileName"] = "DroneDream-Lab-1.0.0.exe"
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "filename"):
            self.validate(invalid)

    def test_rejects_missing_sha_bytes_or_source(self) -> None:
        for section, field, message in (
            ("artifact", "sha256", "keys drifted"),
            ("artifact", "bytes", "keys drifted"),
            ("source", "sourceCommit", "keys drifted"),
        ):
            with self.subTest(section=section, field=field):
                invalid = self.receipt()
                del invalid[section][field]
                with self.assertRaisesRegex(sim_contract.SimInstallerContractError, message):
                    self.validate(invalid)

    def test_rejects_artifact_file_mismatch(self) -> None:
        invalid = self.receipt(b"declared bytes")
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "mismatch"):
            self.validate(invalid, b"different bytes")

    def test_rejects_hardware_module_capability_or_command(self) -> None:
        invalid = self.receipt()
        invalid["payload"]["modules"] = invalid["payload"]["modules"] + ["hardware-bridge"]
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "modules"):
            self.validate(invalid)

        invalid = self.receipt()
        invalid["payload"]["capabilities"] = invalid["payload"]["capabilities"] + [
            "hardware.arm"
        ]
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "capabilities"):
            self.validate(invalid)

        invalid = self.receipt()
        invalid["payload"]["commandAudit"]["observedCommands"].append(
            "hardware.flight arm real target"
        )
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "hardware or HITL"):
            self.validate(invalid)

    def test_rejects_unsigned_artifact_without_disclosure(self) -> None:
        invalid = self.receipt()
        invalid["artifact"]["unsignedDisclosure"] = False
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "unsigned"):
            self.validate(invalid)

    def test_rejects_license_or_lifecycle_drift(self) -> None:
        invalid = self.receipt()
        invalid["licenseNotice"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "license"):
            self.validate(invalid)

        invalid = self.receipt()
        invalid["installLifecycle"]["rollbackPlan"] = "none"
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "lifecycle"):
            self.validate(invalid)


if __name__ == "__main__":
    unittest.main()
