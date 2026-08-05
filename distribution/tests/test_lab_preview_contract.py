from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB_EDITION = ROOT / "distribution" / "editions" / "lab.v1.json"
VEHICLE_PACK_REGISTRY = ROOT / "distribution" / "vehicle-packs" / "registry.v1.json"
LAB_UI_ADAPTER = ROOT / "frontend" / "src" / "lab" / "vehicle-pack-adapter.v1.json"
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_preview_contract as lab_preview  # noqa: E402
import verify_lab_preview_artifact as lab_artifact  # noqa: E402
import lab_preinstall_acceptance as lab_preinstall  # noqa: E402
import lab_yellow_readiness_audit as lab_readiness  # noqa: E402


class LabPreviewContractTests(unittest.TestCase):
    def test_lab_preview_profile_is_unsigned_source_bound_and_fail_closed(self) -> None:
        result = lab_preview.verify_lab_preview_contract()
        self.assertEqual(result["artifactFileName"], "DroneDream-Lab-1.0.0.exe")
        self.assertEqual(result["profile"], "distribution/build-profiles/lab-preview.v1.json")

    def test_fake_lab_artifact_receipt_binds_workspace_module_and_artifact_contracts(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        validated = lab_artifact.validate_receipt(receipt)
        self.assertTrue(validated["testOnly"])
        self.assertEqual(validated["safety"]["hardwareActionDecision"], "deny")
        self.assertFalse(validated["safety"]["uiSwitchCountsAsAuthority"])
        self.assertEqual(
            validated["workspaces"]["hardwareLab"]["deniedHardwareActions"],
            [
                "hardware.parameter.write",
                "hardware.arm",
                "hardware.flight",
                "hardware.hitl.execute",
            ],
        )

    def test_lab_artifact_receipt_rejects_ui_authority_and_hardware_actions(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["workspaces"]["hardwareLab"]["allowedActions"].append("hardware.arm")
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "hardware actions"):
            lab_artifact.validate_receipt(receipt)

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["safety"]["uiSwitchCountsAsAuthority"] = True
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "authority"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_field_or_universal_bootstrapper_mixing(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["moduleGraph"]["gatedHardwareAdapter"].append("runtime-base-field-lightweight")
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "Field-only"):
            lab_artifact.validate_receipt(receipt)

        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["moduleGraph"]["simulationPayload"].append("universal-bootstrapper")
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "Universal bootstrapper"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_notice_drift_and_missing_real_artifact(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["licenseNotice"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "licenseNotice"):
            lab_artifact.validate_receipt(receipt)

        common_core_commit = lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["commonCoreCommit"] = common_core_commit
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(common_core_commit)
        receipt["testOnly"] = False
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "artifact file is missing"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_rejects_sim_preview_evidence_as_product_source(self) -> None:
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["testOnly"] = False
        receipt["commonCoreCommit"] = lab_artifact.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(
            lab_artifact.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT,
        )
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "product source"):
            lab_artifact.validate_receipt(receipt, verify_artifact_file=False)

    def test_lab_artifact_receipt_schema_is_closed_and_versioned(self) -> None:
        schema = lab_artifact._load_json(lab_artifact.SCHEMA_PATH)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["kind"]["const"], "dronedream-lab-preview-artifact-receipt")

    def test_lab_manifest_has_independent_chinese_copy(self) -> None:
        manifest = json.loads(LAB_EDITION.read_text(encoding="utf-8"))
        self.assertEqual(manifest["displayName"]["zh-CN"], "DroneDream 实验室版")
        self.assertEqual(
            manifest["description"]["zh-CN"],
            "统一提供仿真、HITL 与真机实验，但所有真机能力都必须通过 native、Runtime 与后端三层安全门。",
        )
        self.assertNotEqual(manifest["displayName"]["zh-CN"], manifest["displayName"]["en"])
        self.assertNotEqual(manifest["description"]["zh-CN"], manifest["description"]["en"])

    def test_lab_ui_vehicle_adapter_matches_authoritative_registry(self) -> None:
        registry = json.loads(VEHICLE_PACK_REGISTRY.read_text(encoding="utf-8"))
        adapter = json.loads(LAB_UI_ADAPTER.read_text(encoding="utf-8"))
        self.assertEqual(adapter["kind"], "dronedream-lab-vehicle-pack-ui-adapter")
        self.assertEqual(adapter["source"]["registryVersion"], registry["registryVersion"])
        self.assertEqual(adapter["source"]["auditDate"], registry["auditDate"])
        self.assertEqual(adapter["policy"]["validatedPackCount"], 0)
        self.assertFalse(adapter["policy"]["frontendIsAuthority"])
        self.assertEqual(adapter["policy"]["zeroValidatedPackDecision"], "deny")

        registry_packs = {entry["packId"]: entry for entry in registry["packs"]}
        adapter_packs = {entry["packId"]: entry for entry in adapter["packs"]}
        self.assertEqual(set(adapter_packs), set(registry_packs))
        self.assertEqual(len(adapter_packs), 8)
        for pack_id, registry_entry in registry_packs.items():
            manifest_path = ROOT / registry_entry["manifestPath"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            adapted = adapter_packs[pack_id]
            self.assertEqual(adapted["manifestPath"], registry_entry["manifestPath"])
            self.assertEqual(adapted["manifestSha256"], registry_entry["manifestSha256"])
            self.assertEqual(adapted["displayName"], manifest["displayName"])
            self.assertEqual(adapted["validationStatus"], manifest["validationStatus"])
            self.assertEqual(adapted["validationTier"], manifest["validationTier"])
            self.assertEqual(adapted["supportedEditions"], manifest["supportedEditions"])
            self.assertEqual(adapted["autopilotFamily"], manifest["autopilot"]["family"])
            expected_controllers = [
                {
                    "vendor": controller["vendor"],
                    "model": controller["model"],
                    "status": controller["status"],
                }
                for controller in manifest["controllers"]
            ]
            self.assertEqual(adapted["controllers"], expected_controllers)
            self.assertEqual(
                adapted["firmwareVersions"],
                manifest["autopilot"]["supportedFirmwareVersions"],
            )

    def test_lab_preinstall_acceptance_is_read_only_and_blocked_without_real_receipt(self) -> None:
        result = lab_preinstall.evaluate_preinstall()
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("No Lab artifact receipt was supplied.", result["blockers"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))

        result = lab_preinstall.evaluate_preinstall(lab_artifact.fake_lab_preview_receipt())
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("Only a fake test fixture receipt was supplied.", result["blockers"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))

    def test_lab_yellow_readiness_audit_is_read_only_and_requestable(self) -> None:
        result = lab_readiness.evaluate_readiness(require_clean=False)
        self.assertEqual(result["kind"], "dronedream-lab-yellow-readiness-audit")
        self.assertTrue(result["yellowBuildRequest"]["requestable"])
        self.assertEqual(
            result["commonCore"]["productSourceCommit"],
            lab_artifact.COMMON_CORE_PRODUCT_SOURCE_COMMIT,
        )
        self.assertEqual(
            result["commonCore"]["excludedSimPreviewEvidenceCommit"],
            lab_artifact.EXCLUDED_SIM_PREVIEW_EVIDENCE_COMMIT,
        )
        self.assertFalse(result["commonCore"]["observedOriginHeadIsProductSource"])
        self.assertTrue(result["publicSupabaseClientConfigSource"]["sourceUsesVitePublicEnv"])
        self.assertTrue(result["publicSupabaseClientConfigSource"]["desktopVerifierRejectsServiceRole"])
        self.assertFalse(result["publicSupabaseClientConfigSource"]["actualEnvironmentRead"])
        self.assertEqual(result["vehiclePacks"]["validatedPackCount"], 0)
        self.assertEqual(result["safety"]["hardwareActionDecisionAtZeroValidatedPacks"], "deny")
        self.assertFalse(result["postBuildAcceptance"]["installableNow"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))


if __name__ == "__main__":
    unittest.main()
