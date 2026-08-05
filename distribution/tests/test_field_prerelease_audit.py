from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "distribution"
SCHEMA_PATH = DISTRIBUTION / "schemas" / "field-prerelease-audit.schema.json"
TOOL_PATH = DISTRIBUTION / "tools" / "field_prerelease_audit.py"
ENGINE_PACK_TOOL = ROOT / "engine-pack" / "tools" / "engine_pack.py"

SPEC = importlib.util.spec_from_file_location("field_prerelease_audit_tests", TOOL_PATH)
assert SPEC and SPEC.loader
field_audit: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = field_audit
SPEC.loader.exec_module(field_audit)

ENGINE_SPEC = importlib.util.spec_from_file_location("field_audit_engine_pack_tests", ENGINE_PACK_TOOL)
assert ENGINE_SPEC and ENGINE_SPEC.loader
engine_pack: ModuleType = importlib.util.module_from_spec(ENGINE_SPEC)
sys.modules[ENGINE_SPEC.name] = engine_pack
ENGINE_SPEC.loader.exec_module(engine_pack)


class FieldPrereleaseAuditTests(unittest.TestCase):
    common_core_commit = "3" * 40
    common_core_hash = "4" * 64

    def build_engine_pack(self, output: Path, *, edition_profile: str) -> None:
        previous = engine_pack.source_date_epoch
        engine_pack.source_date_epoch = lambda _root, _commit: 1_722_000_000
        try:
            result = engine_pack.build(
                type(
                    "Args",
                    (),
                    {
                        "repository_root": str(ROOT),
                        "output_directory": str(output),
                        "source_commit": self.common_core_commit,
                        "edition_profile": edition_profile,
                    },
                )()
            )
        finally:
            engine_pack.source_date_epoch = previous
        self.assertEqual(result, 0)

    def field_payload_audit(self) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build_engine_pack(output, edition_profile=engine_pack.FIELD_EDITION_PROFILE)
            return field_audit.audit_engine_pack_payload(
                descriptor_path=output / engine_pack.DESCRIPTOR_FILENAME,
                archive_path=output / engine_pack.ARCHIVE_FILENAME,
                common_core_commit=self.common_core_commit,
                common_core_hash=self.common_core_hash,
            )

    def observation(
        self,
        *,
        pack_id: str = "amovlab-p450-px4",
        firmware_version: str = "v1.16.0-contract-target",
        controller_model: str = "Allspark V6C",
    ) -> dict[str, object]:
        return field_audit.fake_readonly_observation(
            observation_id="obs:field-fake-001",
            device_id="fake-device:field-001",
            hardware_identity_hash="5" * 64,
            controller_model=controller_model,
            firmware_family="px4",
            firmware_version=firmware_version,
            firmware_identity_hash="6" * 64,
            pack_id=pack_id,
            common_core_commit=self.common_core_commit,
            common_core_hash=self.common_core_hash,
            field_manifest_sha256=field_audit.sha256_file(
                ROOT / "distribution" / "editions" / "field.v1.json"
            ),
        )

    def install_plan(self) -> dict[str, object]:
        return {
            "planId": "field-install-plan-contract-only",
            "state": "planned-not-installable",
            "executed": False,
            "hash": "7" * 64,
        }

    def rollback_plan(self) -> dict[str, object]:
        return {
            "planId": "field-rollback-plan-contract-only",
            "state": "rollback-contract-only",
            "executed": False,
            "hash": "8" * 64,
        }

    def receipt(
        self,
        *,
        observation: dict[str, object] | None = None,
        quorum_receipt: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return field_audit.create_field_prerelease_receipt(
            payload_audit=self.field_payload_audit(),
            observation=observation or self.observation(),
            install_plan=self.install_plan(),
            rollback_plan=self.rollback_plan(),
            quorum_receipt=quorum_receipt,
        )

    def test_schema_is_closed_versioned_draft_2020_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["unevaluatedProperties"])
        self.assertFalse(
            schema["$defs"]["fieldPrereleaseAuditReceipt"]["additionalProperties"]
        )
        self.assertFalse(
            schema["$defs"]["readonlyDeviceObservation"]["additionalProperties"]
        )
        self.assertEqual(
            schema["$defs"]["readonlyTransport"]["properties"]["openedDevice"]["const"],
            False,
        )

    def test_field_engine_pack_payload_has_no_large_simulator_payload_and_keeps_safety(self) -> None:
        audit = self.field_payload_audit()
        self.assertEqual(audit["profileId"], engine_pack.FIELD_EDITION_PROFILE)
        self.assertFalse(audit["includesLargeSimulator"])
        self.assertEqual(audit["forbiddenPayloads"], [])
        retained = {resource["path"] for resource in audit["requiredResources"]}
        self.assertIn("distribution/safety/edition-execution-gate.v1.json", retained)
        self.assertIn("distribution/tools/field_prerelease_audit.py", retained)
        self.assertIn("distribution/schemas/field-prerelease-audit.schema.json", retained)
        self.assertIn("runtime/THIRD_PARTY_NOTICES.md", retained)
        receipts = set(audit["retainedSafetyResources"]["requiredReceiptTypes"])
        self.assertIn("transaction-rollback", receipts)
        self.assertIn("emergency-stop", receipts)
        self.assertEqual(audit["registrySummary"]["validatedHardwarePackCount"], 0)

    def test_unified_sim_lab_pack_is_not_a_field_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build_engine_pack(output, edition_profile=engine_pack.DEFAULT_EDITION_PROFILE)
            with self.assertRaisesRegex(
                field_audit.FieldPrereleaseAuditError,
                "not bound to Field lightweight profile",
            ):
                field_audit.audit_engine_pack_payload(
                    descriptor_path=output / engine_pack.DESCRIPTOR_FILENAME,
                    archive_path=output / engine_pack.ARCHIVE_FILENAME,
                    common_core_commit=self.common_core_commit,
                    common_core_hash=self.common_core_hash,
                )

    def test_fake_readonly_observation_rejects_device_open_and_writes(self) -> None:
        valid = field_audit.validate_readonly_observation(self.observation())
        self.assertEqual(valid["transport"]["kind"], "fake")
        self.assertFalse(valid["transport"]["openedDevice"])
        self.assertEqual(valid["vehiclePack"]["validationStatus"], "planned")

        opened = deepcopy(self.observation())
        opened["transport"]["openedDevice"] = True
        with self.assertRaisesRegex(field_audit.FieldPrereleaseAuditError, "must not open"):
            field_audit.validate_readonly_observation(opened)

        write_attempt = deepcopy(self.observation())
        write_attempt["transport"]["writeAttempted"] = True
        with self.assertRaisesRegex(field_audit.FieldPrereleaseAuditError, "must not write"):
            field_audit.validate_readonly_observation(write_attempt)

        operation = deepcopy(self.observation())
        operation["transport"]["writeOperations"] = ["mavlink.param-set"]
        with self.assertRaisesRegex(field_audit.FieldPrereleaseAuditError, "must not write"):
            field_audit.validate_readonly_observation(operation)

    def test_discovery_is_not_authorization_even_for_known_contract_pack(self) -> None:
        receipt = self.receipt()
        self.assertEqual(receipt["decision"], "deny")
        self.assertIn("discovery.not-authorization", receipt["reasonCodes"])
        self.assertFalse(receipt["deviceObservation"]["discoveryIsAuthorization"])
        self.assertEqual(receipt["source"]["commonCoreCommit"], self.common_core_commit)
        self.assertEqual(receipt["source"]["commonCoreHash"], self.common_core_hash)
        self.assertEqual(
            receipt["validation"]["registryValidatedHardwarePackCount"],
            0,
        )

    def test_zero_validated_packs_unknown_device_firmware_drift_and_missing_quorum_deny(self) -> None:
        zero_validated = self.receipt()
        self.assertIn("field.registry.zero-validated-packs", zero_validated["reasonCodes"])
        self.assertIn("field.quorum.missing-three-layer", zero_validated["reasonCodes"])

        unknown = self.receipt(observation=self.observation(pack_id="unknown-device-pack"))
        self.assertIn("field.device.unknown-pack", unknown["reasonCodes"])

        drift = self.receipt(observation=self.observation(firmware_version="v1.17.99"))
        self.assertIn("field.firmware.version-drift", drift["reasonCodes"])

        missing_layer_quorum = {
            "decision": "allow",
            "layerDecisionHashes": {
                "native": "9" * 64,
                "backend": "a" * 64,
            },
        }
        missing_quorum = self.receipt(quorum_receipt=missing_layer_quorum)
        self.assertIn("field.quorum.missing-three-layer", missing_quorum["reasonCodes"])

    def test_signature_validation_tier_license_notice_install_and_rollback_are_bound(self) -> None:
        receipt = self.receipt()
        bindings = receipt["bindings"]
        self.assertRegex(bindings["fieldManifestSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(bindings["controllerFirmwareRegistrySha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(bindings["licenseSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(bindings["noticeSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(bindings["installPlanSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(bindings["rollbackPlanSha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt["validation"]["validationStatus"], "planned")
        self.assertEqual(receipt["validation"]["validationTier"], "planned")
        self.assertEqual(receipt["validation"]["signatureState"], "not-issued")
        self.assertFalse(receipt["installPlan"]["executed"])
        self.assertFalse(receipt["rollbackPlan"]["executed"])


if __name__ == "__main__":
    unittest.main()
