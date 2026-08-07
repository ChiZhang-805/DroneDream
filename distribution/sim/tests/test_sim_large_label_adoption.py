from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "distribution" / "sim" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sim_large_label_adoption import (  # noqa: E402
    LargeLabelAdoptionError,
    validate_adoption,
)

RECEIPT = (
    ROOT
    / "distribution"
    / "sim"
    / "brand"
    / "canonical-large-label-adoption-receipt.v1.json"
)
CENTERED_RECEIPT = (
    ROOT
    / "distribution"
    / "sim"
    / "brand"
    / "centered-separator-adoption-receipt.v1.json"
)


def load_receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


class SimLargeLabelAdoptionTests(unittest.TestCase):
    def test_exact_donor_asset_and_all_surface_mappings_validate(self) -> None:
        receipt = validate_adoption(load_receipt(), ROOT)
        self.assertEqual(
            receipt["assetBinding"]["sha256"],
            "d11e727f4024f356a3850271aa3349d7286e2da85f647d145388c5d1eec20233",
        )
        self.assertEqual(len(receipt["surfaceMappings"]), 9)
        self.assertFalse(receipt["execution"]["releaseAsset"])

    def test_evidence_commit_cannot_be_relabelled(self) -> None:
        receipt = load_receipt()
        receipt["source"]["evidenceCommitIsProductSource"] = True
        with self.assertRaisesRegex(LargeLabelAdoptionError, "evidence relabeled"):
            validate_adoption(receipt, ROOT)

    def test_asset_hash_or_geometry_drift_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["assetBinding"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(LargeLabelAdoptionError, "asset SHA"):
            validate_adoption(receipt, ROOT)

        receipt = load_receipt()
        receipt["assetBinding"]["naturalEditionLabelWidth"] = False
        with self.assertRaisesRegex(LargeLabelAdoptionError, "natural width"):
            validate_adoption(receipt, ROOT)

    def test_common_core_or_hardware_overclaim_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["source"]["commonCoreUpdated"] = True
        with self.assertRaisesRegex(LargeLabelAdoptionError, "common core"):
            validate_adoption(receipt, ROOT)

        receipt = load_receipt()
        receipt["pathLimitedSync"]["hardwareAuthorityGranted"] = True
        with self.assertRaisesRegex(LargeLabelAdoptionError, "hardwareAuthorityGranted"):
            validate_adoption(receipt, ROOT)

    def test_pending_auth_or_website_surface_cannot_be_claimed_wired(self) -> None:
        receipt = load_receipt()
        mapping = copy.deepcopy(receipt["surfaceMappings"])
        callback = next(
            row for row in mapping if row["surface"] == "browser-callback"
        )
        callback["status"] = "source-wired"
        receipt["surfaceMappings"] = mapping
        with self.assertRaisesRegex(LargeLabelAdoptionError, "surface mapping"):
            validate_adoption(receipt, ROOT)

    def test_build_or_release_claim_is_rejected(self) -> None:
        receipt = load_receipt()
        receipt["execution"]["frontendBuildExecuted"] = True
        with self.assertRaisesRegex(LargeLabelAdoptionError, "execution"):
            validate_adoption(receipt, ROOT)

    def test_centered_separator_v2_is_exact_on_every_sim_runtime_mirror(self) -> None:
        receipt = json.loads(CENTERED_RECEIPT.read_text(encoding="utf-8"))
        binding = receipt["assetBinding"]
        expected_sha = "f3dd34d3e1a546e4299370d6cbe21d9f03b07a5910dcae061a322ba6c548fd6e"
        self.assertEqual(binding["sha256"], expected_sha)
        paths = (
            binding["approvedSourcePath"],
            binding["generatedPrimaryPath"],
            binding["generatedCompactPath"],
            binding["sharedFrontendPrimaryPath"],
            binding["sharedFrontendCompactPath"],
            binding["simEditionPath"],
        )
        for relative_path in paths:
            payload = (ROOT / relative_path).read_bytes()
            self.assertEqual(len(payload), binding["bytes"], relative_path)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha, relative_path)

        with Image.open(ROOT / binding["simEditionPath"]) as image:
            self.assertEqual(image.size, (binding["width"], binding["height"]))
            alpha = image.getchannel("A")
            geometry = binding["separatorGeometry"]
            left = geometry["separatorStartX"] - geometry["wordmarkEndX"] - 1
            right = geometry["editionLabelStartX"] - geometry["separatorEndX"] - 1
            self.assertEqual((left, right), (53, 53))
            self.assertEqual(geometry["tolerancePx"], 0)
            self.assertIsNone(
                alpha.crop(
                    (
                        geometry["wordmarkEndX"] + 1,
                        0,
                        geometry["separatorStartX"],
                        image.height,
                    )
                ).getbbox()
            )
            self.assertIsNone(
                alpha.crop(
                    (
                        geometry["separatorEndX"] + 1,
                        0,
                        geometry["editionLabelStartX"],
                        image.height,
                    )
                ).getbbox()
            )

    def test_centered_separator_v2_replaces_product_inputs_without_rewriting_history(self) -> None:
        receipt = json.loads(CENTERED_RECEIPT.read_text(encoding="utf-8"))
        component = (
            ROOT / "frontend/src/editions/sim/SimEditionExperience.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("dronedream-sim-centered-separator-lockup.png", component)
        self.assertNotIn('from "./assets/dronedream-sim-large-label-lockup.png"', component)
        historical = receipt["historicalPreservation"]
        old_payload = (ROOT / historical["supersededLargeLabelPath"]).read_bytes()
        self.assertEqual(
            hashlib.sha256(old_payload).hexdigest(),
            historical["supersededLargeLabelSha256"],
        )
        self.assertFalse(historical["historicalBytesDeletedOrOverwritten"])
        supersession = receipt["priorArtifactSupersession"]
        self.assertFalse(supersession["artifactContainsCenteredSeparatorV2"])
        self.assertFalse(supersession["currentWebsiteDeploymentAllowed"])
        self.assertTrue(supersession["newExactSourceBuildRequired"])
        self.assertTrue(receipt["authority"]["presentationOnly"])
        self.assertFalse(receipt["authority"]["grantsHardwareAuthority"])


if __name__ == "__main__":
    unittest.main()
