from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRANDING_ROOT = ROOT / "distribution" / "editions" / "field" / "branding"
MANIFEST_PATH = BRANDING_ROOT / "source-manifest.v1.json"
FIELD_APP = ROOT / "frontend" / "src" / "field" / "FieldApp.tsx"
FIELD_VITE = ROOT / "frontend" / "vite.field.config.ts"
FIELD_CONFIG = ROOT / "desktop" / "src-tauri" / "tauri.field.conf.json"
CANONICAL_MANIFEST = ROOT / "brand" / "generated" / "brand-assets.v1.json"
CANONICAL_CONTRACT = ROOT / "brand" / "brand-editions.v1.json"
CANONICAL_VISUAL_RECEIPT = ROOT / "brand" / "generated" / "brand-visual-receipt.v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG with an IHDR header: {path}")
    return struct.unpack(">II", data[16:24])


class FieldBrandAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_binds_the_authorized_field_donor(self) -> None:
        self.assertEqual(self.manifest["kind"], "dronedream-edition-brand-assets-source")
        self.assertEqual(self.manifest["editionId"], "field")
        self.assertEqual(self.manifest["displayName"], "DroneDream · FIELD")
        self.assertEqual(self.manifest["copyPolicy"], "byte-for-byte-no-transcode")
        self.assertEqual(
            self.manifest["commonCoreCommit"],
            "6de4f1343c0239a916949f0486fa63d3f460d6a8",
        )
        donor = self.manifest["canonicalDonor"]
        self.assertEqual(donor["commit"], self.manifest["commonCoreCommit"])
        self.assertEqual(
            donor["baseLargeLabelCommit"],
            "b8e0d0c7093abe9f54fe36f01022deb95852fa39",
        )
        self.assertEqual(donor["contractSha256"], sha256(CANONICAL_CONTRACT))
        self.assertEqual(donor["manifestSha256"], sha256(CANONICAL_MANIFEST))
        self.assertEqual(donor["visualReceiptSha256"], sha256(CANONICAL_VISUAL_RECEIPT))
        self.assertEqual(
            self.manifest["source"]["receiptSha256"],
            "9f2e054cc9ce7ff612919e60b51894ab0bea54b58cb7140aa002bf058f174c94",
        )
        self.assertFalse(self.manifest["source"]["evidenceCommitConsumed"])
        visual_receipt = json.loads(CANONICAL_VISUAL_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(visual_receipt["editionLabelHeightRatio"], 0.9)
        self.assertTrue(visual_receipt["naturalEditionLabelWidths"])
        self.assertTrue(visual_receipt["presentationOnly"])
        self.assertEqual(
            donor["separatorGeometry"],
            {"leftGapPx": 58, "rightGapPx": 58, "tolerancePx": 0},
        )
        self.assertEqual(
            donor["supersededDotLockupSha256"],
            "588c5aca42b09fa3396efc63a7423bbf1e182379e1a41427f716a1b9f73fbd27",
        )

    def test_formal_assets_match_source_hash_size_and_dimensions(self) -> None:
        expected_ids = {"field-mark", "field-large-label-lockup"}
        self.assertEqual({asset["assetId"] for asset in self.manifest["assets"]}, expected_ids)

        for asset in self.manifest["assets"]:
            target = ROOT / asset["targetPath"]
            self.assertEqual(target.parent.resolve(), BRANDING_ROOT.resolve())
            self.assertEqual(target.name, asset["targetFilename"])
            self.assertEqual(asset["sourceSha256"], asset["targetSha256"])
            self.assertEqual(asset["transformations"], [])
            self.assertEqual(sha256(target), asset["targetSha256"])
            self.assertEqual(target.stat().st_size, asset["sizeBytes"])
            self.assertEqual(png_dimensions(target), (asset["width"], asset["height"]))
            donor_path = ROOT / self.manifest["canonicalDonor"][
                "markPath" if asset["assetId"] == "field-mark" else "dotLockupPath"
            ]
            self.assertEqual(sha256(donor_path), asset["sourceSha256"])
            self.assertEqual(target.read_bytes(), donor_path.read_bytes())

    def test_all_field_lockup_surfaces_use_the_exact_large_label_bytes(self) -> None:
        expected = "e3e88cf4c14b9afdb31f1d9152fd7795f0eaec8ef63e8fd4ae52171eae09b0fa"
        paths = (
            BRANDING_ROOT / "dronedream-field-dot-lockup.png",
            ROOT / "brand" / "generated" / "field" / "lockup-primary.png",
            ROOT / "brand" / "generated" / "field" / "lockup-compact.png",
            ROOT / "frontend" / "src" / "assets" / "brand" / "field-lockup-primary.png",
            ROOT / "frontend" / "src" / "assets" / "brand" / "field-lockup-compact.png",
        )
        self.assertEqual({sha256(path) for path in paths}, {expected})
        self.assertEqual({png_dimensions(path) for path in paths}, {(2581, 218)})

    def test_frontend_and_desktop_consume_only_field_owned_assets(self) -> None:
        app_source = FIELD_APP.read_text(encoding="utf-8")
        vite_source = FIELD_VITE.read_text(encoding="utf-8")
        desktop_config = json.loads(FIELD_CONFIG.read_text(encoding="utf-8"))

        self.assertIn("FieldBrandLockup", app_source)
        self.assertNotIn("../distribution/editions/field/branding", vite_source)
        self.assertIn('data-authority="false"', app_source)
        self.assertEqual(
            desktop_config["bundle"]["icon"],
            [
                "../../brand/generated/field/windows/32x32.png",
                "../../brand/generated/field/windows/128x128.png",
                "../../brand/generated/field/windows/128x128@2x.png",
                "../../brand/generated/field/windows/icon.ico",
            ],
        )
        self.assertEqual(
            desktop_config["bundle"]["windows"]["nsis"],
            {
                "installerIcon": "../../brand/generated/field/windows/icon.ico",
                "uninstallerIcon": "../../brand/generated/field/windows/icon.ico",
            },
        )


if __name__ == "__main__":
    unittest.main()
