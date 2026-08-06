from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELD_CONFIG = ROOT / "desktop" / "src-tauri" / "tauri.field.conf.json"
DESKTOP_PACKAGE = ROOT / "desktop" / "package.json"
BUILD_GATE = ROOT / "desktop" / "scripts" / "verify-field-preview-build-authorization.ps1"
COEXISTENCE_CONTRACT = ROOT / "distribution" / "desktop" / "edition-coexistence.v1.json"


class FieldDesktopProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(FIELD_CONFIG.read_text(encoding="utf-8"))
        cls.package = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
        coexistence = json.loads(COEXISTENCE_CONTRACT.read_text(encoding="utf-8"))
        cls.field_identity = next(
            edition
            for edition in coexistence["editions"]
            if edition["editionId"] == "field"
        )

    def test_field_overlay_uses_the_independent_frontend_and_identity(self) -> None:
        self.assertEqual(
            self.config["productName"],
            self.field_identity["installerProductName"],
        )
        self.assertEqual(self.config["version"], "1.0.0")
        self.assertEqual(self.config["identifier"], self.field_identity["bundleIdentifier"])
        self.assertEqual(
            self.config["app"]["windows"][0]["title"],
            self.field_identity["displayName"],
        )
        self.assertEqual(self.config["build"], {
            "beforeDevCommand": "npm run frontend:field-dev",
            "beforeBuildCommand": "npm run frontend:field-build-gated",
            "devUrl": "http://127.0.0.1:5174/field.html",
            "frontendDist": "../../frontend/field-dist",
        })

    def test_window_and_updater_are_field_specific(self) -> None:
        window = self.config["app"]["windows"][0]
        self.assertEqual(window["title"], "DroneDream · FIELD")
        self.assertEqual((window["width"], window["height"]), (1440, 900))
        self.assertEqual((window["minWidth"], window["minHeight"]), (390, 620))
        endpoints = self.config["plugins"]["updater"]["endpoints"]
        self.assertEqual(len(endpoints), 1)
        self.assertTrue(endpoints[0].endswith("/field-latest.json"))
        self.assertFalse(self.config["bundle"]["createUpdaterArtifacts"])

    def test_overlay_binds_the_authorized_field_brand_assets(self) -> None:
        self.assertEqual(self.config["bundle"]["icon"], [
            "../../brand/generated/field/windows/32x32.png",
            "../../brand/generated/field/windows/128x128.png",
            "../../brand/generated/field/windows/128x128@2x.png",
            "../../brand/generated/field/windows/icon.ico",
        ])
        self.assertEqual(self.config["bundle"]["resources"], {
            "icons/icon.ico": None,
            "../../distribution/editions/field/branding/dronedream-field-mark.png":
                "branding/dronedream-field-mark.png",
            "../../distribution/editions/field/branding/dronedream-field-dot-lockup.png":
                "branding/dronedream-field-dot-lockup.png",
            "../../distribution/editions/field/branding/source-manifest.v1.json":
                "branding/source-manifest.v1.json",
            "../../brand/generated/brand-assets.v1.json":
                "branding/canonical-brand-assets.v1.json",
            "../../brand/generated/brand-visual-receipt.v1.json":
                "branding/canonical-brand-visual-receipt.v1.json",
            "../../brand/generated/field/windows/icon.ico":
                "icons/DroneDream.ico",
        })
        self.assertNotIn("windows", self.config["bundle"])

    def test_desktop_package_has_no_direct_field_executable_build_command(self) -> None:
        scripts = self.package["scripts"]
        self.assertNotIn("build:field", scripts)
        self.assertEqual(
            scripts["frontend:field-build-gated"],
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            "scripts/verify-field-preview-build-authorization.ps1 && "
            "npm run frontend:field-build",
        )

    def test_zero_validated_pack_registry_denies_before_any_build(self) -> None:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(BUILD_GATE),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("zero hardware-validated Vehicle Packs", output)
        self.assertNotIn("frontend:field-build", output)


if __name__ == "__main__":
    unittest.main()
