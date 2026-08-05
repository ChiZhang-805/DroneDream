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
READINESS_SCHEMA_PATH = (
    ROOT / "distribution" / "sim" / "schemas" / "sim-install-readiness-audit.schema.json"
)
READINESS_AUDIT_PATH = (
    ROOT
    / "distribution"
    / "sim"
    / "lifecycle"
    / "sim-preview-1.0.0-2aec69e.install-readiness-audit.v1.json"
)
SURFACE_CONTRACT_PATH = (
    ROOT / "distribution" / "sim" / "desktop" / "installer-surface-contract.v1.json"
)
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

    def readiness_audit(self) -> dict[str, Any]:
        return load_json(READINESS_AUDIT_PATH)

    def validate_readiness(self, audit: object) -> dict[str, Any]:
        return sim_contract.validate_install_readiness_audit(
            audit,
            profile=self.profile,
            profile_path=PROFILE_PATH,
            repo_root=ROOT,
        )

    def installer_surface(self) -> dict[str, Any]:
        return load_json(SURFACE_CONTRACT_PATH)

    def validate_surface(self, contract: object) -> dict[str, Any]:
        return sim_contract.validate_installer_surface_contract(
            contract,
            profile=self.profile,
            profile_path=PROFILE_PATH,
            repo_root=ROOT,
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

    def test_readiness_schema_is_closed_and_sim_only(self) -> None:
        schema = load_json(READINESS_SCHEMA_PATH)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["editionId"]["const"], "sim")
        self.assertEqual(schema["properties"]["executionClass"]["const"], "GREEN-static-only")
        self.assertEqual(
            schema["properties"]["artifact"]["properties"]["fileName"]["const"],
            "DroneDream-Sim-1.0.0.exe",
        )
        self.assertEqual(
            schema["properties"]["vehiclePackAndCapabilityFence"]["properties"][
                "validatedVehiclePackCount"
            ]["const"],
            0,
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

    def test_build_profile_rejects_sim_manifest_drift(self) -> None:
        invalid = deepcopy(load_json(PROFILE_PATH))
        invalid["deterministicPayload"]["allowedModules"].remove("simulator-px4-sitl")
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "allowed modules"):
            sim_contract.validate_build_profile(invalid, repo_root=ROOT)

        invalid = deepcopy(load_json(PROFILE_PATH))
        invalid["artifact"]["fileName"] = "DroneDream-Field-1.0.0.exe"
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "artifact identity"):
            sim_contract.validate_build_profile(invalid, repo_root=ROOT)

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

    def test_valid_readiness_audit_stays_green_static_and_planned(self) -> None:
        validated = self.validate_readiness(self.readiness_audit())
        self.assertEqual(validated["executionClass"], "GREEN-static-only")
        self.assertFalse(validated["negativeAssertions"]["installed"])
        self.assertFalse(validated["negativeAssertions"]["rebuilt"])
        self.assertFalse(validated["negativeAssertions"]["releaseBranchCreated"])
        self.assertEqual(
            validated["artifact"]["productSubjectCommit"],
            "2aec69e88ee8844cff759a025f109e5b938d18c0",
        )
        self.assertEqual(
            validated["artifact"]["postAdoptionEvidenceHead"],
            "e097b9ea057468bf1602ad1f1c4c5c5e88a65571",
        )
        self.assertEqual(
            validated["vehiclePackAndCapabilityFence"]["validatedVehiclePackCount"],
            0,
        )

    def test_readiness_rejects_claimed_lifecycle_execution(self) -> None:
        invalid = self.readiness_audit()
        invalid["lifecyclePlan"]["freshInstall"]["status"] = "passed"
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "planned-not-executed"):
            self.validate_readiness(invalid)

    def test_readiness_rejects_embedded_runtime_or_engine_pack(self) -> None:
        invalid = self.readiness_audit()
        invalid["externalDependencies"]["runtimeBase"]["embedded"] = True
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "runtimeBase"):
            self.validate_readiness(invalid)

        invalid = self.readiness_audit()
        invalid["externalDependencies"]["enginePack"]["mode"] = "embedded"
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "enginePack"):
            self.validate_readiness(invalid)

    def test_readiness_rejects_hardware_hitl_or_lab_field_authority(self) -> None:
        invalid = self.readiness_audit()
        invalid["vehiclePackAndCapabilityFence"]["allowedCapabilities"].append("hardware.arm")
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "allowed capabilities"):
            self.validate_readiness(invalid)

        invalid = self.readiness_audit()
        invalid["vehiclePackAndCapabilityFence"]["forbiddenEditionIds"] = ["lab"]
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "Lab and Field"):
            self.validate_readiness(invalid)

    def test_readiness_rejects_validation_or_promotion_claims(self) -> None:
        invalid = self.readiness_audit()
        invalid["vehiclePackAndCapabilityFence"]["validatedVehiclePackCount"] = 1
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "zero validated packs"):
            self.validate_readiness(invalid)

        invalid = self.readiness_audit()
        invalid["negativeAssertions"]["promotionReady"] = True
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "must all remain false"):
            self.validate_readiness(invalid)

    def test_valid_installer_surface_binds_sim_identity_and_planned_lifecycle(self) -> None:
        validated = self.validate_surface(self.installer_surface())
        self.assertEqual(validated["identity"]["displayName"], "DroneDream \u00b7 SIM")
        self.assertEqual(validated["installerUi"]["locales"], ["en", "zh-CN"])
        self.assertFalse(validated["brandDonor"]["iconOverridePresent"])
        self.assertFalse(validated["brandDonor"]["commonCoreBindingVerified"])
        self.assertFalse(validated["brandDonor"]["assetHashesVerified"])
        self.assertEqual(validated["capabilityFence"]["validatedVehiclePackCount"], 0)
        self.assertTrue(sim_contract._contains_icon_override({"bundle": {"icon": []}}))

    def test_installer_surface_rejects_lab_or_field_identity(self) -> None:
        for display_name in ("DroneDream \u00b7 LAB", "DroneDream \u00b7 FIELD"):
            with self.subTest(display_name=display_name):
                invalid = self.installer_surface()
                invalid["identity"]["displayName"] = display_name
                with self.assertRaisesRegex(
                    sim_contract.SimInstallerContractError, "surface identity"
                ):
                    self.validate_surface(invalid)

    def test_installer_surface_rejects_canonical_icon_claim_before_donor(self) -> None:
        invalid = self.installer_surface()
        invalid["brandDonor"]["canonicalDonorCommit"] = "e374d3f8d96b1265fcdb06864208b676566e94d9"
        invalid["brandDonor"]["iconOverridePresent"] = True
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "brand donor state"):
            self.validate_surface(invalid)

    def test_installer_surface_rejects_invalid_donor_input_while_pending(self) -> None:
        with self.assertRaisesRegex(
            sim_contract.SimInstallerContractError, "brand donor verification failed"
        ):
            sim_contract.validate_installer_surface_contract(
                self.installer_surface(),
                profile=self.profile,
                profile_path=PROFILE_PATH,
                repo_root=ROOT,
                donor_manifest={},
            )

    def test_installer_surface_rejects_source_hash_drift(self) -> None:
        invalid = self.installer_surface()
        invalid["staticSourceRefs"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "SHA-256 drifted"):
            self.validate_surface(invalid)

    def test_installer_surface_rejects_observed_or_promotion_claims(self) -> None:
        for claim in ("installerExecuted", "rollbackObserved", "promotionReady"):
            with self.subTest(claim=claim):
                invalid = self.installer_surface()
                invalid["nonClaims"][claim] = True
                with self.assertRaisesRegex(sim_contract.SimInstallerContractError, "non-claims"):
                    self.validate_surface(invalid)


if __name__ == "__main__":
    unittest.main()
