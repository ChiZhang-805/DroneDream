from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "distribution" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import verify_lab_preview_contract as lab_preview  # noqa: E402
import verify_lab_preview_artifact as lab_artifact  # noqa: E402
import lab_preinstall_acceptance as lab_preinstall  # noqa: E402


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

        common_core_commit = lab_artifact._git("rev-parse", "--verify", "origin/codex/software")
        receipt = lab_artifact.fake_lab_preview_receipt()
        receipt["commonCoreCommit"] = common_core_commit
        receipt["commonCoreHash"] = lab_artifact.common_core_hash(common_core_commit)
        receipt["testOnly"] = False
        with self.assertRaisesRegex(lab_artifact.LabPreviewArtifactError, "artifact file is missing"):
            lab_artifact.validate_receipt(receipt)

    def test_lab_artifact_receipt_schema_is_closed_and_versioned(self) -> None:
        schema = lab_artifact._load_json(lab_artifact.SCHEMA_PATH)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["kind"]["const"], "dronedream-lab-preview-artifact-receipt")

    def test_lab_preinstall_acceptance_is_read_only_and_blocked_without_real_receipt(self) -> None:
        result = lab_preinstall.evaluate_preinstall()
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("No Lab artifact receipt was supplied.", result["blockers"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))

        result = lab_preinstall.evaluate_preinstall(lab_artifact.fake_lab_preview_receipt())
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("Only a fake test fixture receipt was supplied.", result["blockers"])
        self.assertTrue(all(value is False for value in result["sideEffects"].values()))


if __name__ == "__main__":
    unittest.main()
