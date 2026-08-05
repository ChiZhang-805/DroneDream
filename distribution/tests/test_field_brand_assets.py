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
            "26d69562c9cea6557f30b3b21b3d6d39ac89e294",
        )
        self.assertEqual(
            self.manifest["source"]["handoffSha256"],
            "9fc52dea2edab1b65aa8c814fbf05ff1ad4fea0de4980403bec84dab8a1d9657",
        )

    def test_formal_assets_match_source_hash_size_and_dimensions(self) -> None:
        expected_ids = {"field-mark", "field-dot-lockup"}
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

    def test_frontend_and_desktop_consume_only_field_owned_assets(self) -> None:
        app_source = FIELD_APP.read_text(encoding="utf-8")
        vite_source = FIELD_VITE.read_text(encoding="utf-8")
        desktop_config = json.loads(FIELD_CONFIG.read_text(encoding="utf-8"))

        self.assertIn('src="/dronedream-field-dot-lockup.png"', app_source)
        self.assertNotIn("BrandLockup", app_source)
        self.assertIn("../distribution/editions/field/branding", vite_source)
        self.assertIn('data-authority="false"', app_source)
        self.assertEqual(
            desktop_config["bundle"]["icon"],
            ["../../distribution/editions/field/branding/dronedream-field-mark.png"],
        )


if __name__ == "__main__":
    unittest.main()
