from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    ROOT / "distribution" / "editions" / "lab" / "brand-source-manifest.v1.json"
)
TAURI_OVERLAY_PATH = ROOT / "desktop" / "src-tauri" / "tauri.lab-preview.conf.json"
GREEN_RECEIPT_PATH = (
    ROOT / "distribution" / "build-receipts" / "lab-brand-1.0.0-f33af86.green.json"
)
CANONICAL_GREEN_RECEIPT_PATH = (
    ROOT
    / "distribution"
    / "build-receipts"
    / "lab-brand-1.0.0-e975223.canonical-green.json"
)

EXPECTED_ASSETS = {
    "mark": {
        "filename": "dronedream-lab-mark-v2.png",
        "bytes": 98418,
        "sha256": "63d87e2ba200fb6d728a8b8bba96f7f593f216890a376e31b0796596405d0806",
        "dimensions": (1024, 1024),
    },
    "dot-lockup": {
        "filename": "dronedream-lab-dot-lockup-v2.png",
        "bytes": 98556,
        "sha256": "b01b87ce92199b7781453aade99c5428fe2bd4b8c141f0aacdd05346e683bc91",
        "dimensions": (1840, 340),
    },
}

EXPECTED_DERIVATIVES = {
    "desktop-32": ("32x32.png", 2040, "e8d22185013bb6e15bdabb2a03fd82a8f6b5d7db690d336f8067ff6e0a7dcfcc"),
    "desktop-128": ("128x128.png", 11272, "4dc38efa82202dc8674b1e4ed782447a041e2e8793c7615ff164501248a3b485"),
    "desktop-256": ("128x128@2x.png", 25420, "b0a38390f2f58f6f873847e6a52ab07fe26945705a9940957a746970faabb0b1"),
    "windows-ico": ("icon.ico", 55959, "67b5747de298ffcf64d062294829306bd9b66df4ee52cfa8a8e3498cb94d5fa1"),
}


def png_dimensions(payload: bytes) -> tuple[int, int]:
    if payload[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise AssertionError("asset is not a PNG with an IHDR header")
    return struct.unpack(">II", payload[16:24])


def ico_dimensions(payload: bytes) -> set[tuple[int, int]]:
    reserved, image_type, count = struct.unpack("<HHH", payload[:6])
    if (reserved, image_type, count) != (0, 1, 9):
        raise AssertionError("Lab Windows icon container header drifted")
    dimensions = set()
    for index in range(count):
        width, height = struct.unpack_from("BB", payload, 6 + index * 16)
        dimensions.add((width or 256, height or 256))
    return dimensions


class LabBrandAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_binds_approved_lab_v2_identity(self) -> None:
        self.assertEqual(self.manifest["editionId"], "lab")
        self.assertEqual(self.manifest["displayName"], "DroneDream · LAB")
        self.assertEqual(
            self.manifest["theme"]["palette"],
            ["#A7E84A", "#20C77A", "#087E69"],
        )
        self.assertFalse(self.manifest["theme"]["grantsHardwareAuthority"])
        self.assertTrue(self.manifest["theme"]["presentationOnly"])
        self.assertEqual(
            self.manifest["sourceAuthority"]["donorCommit"],
            "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
        )
        donor_path = ROOT / self.manifest["sourceAuthority"]["canonicalContract"]["path"]
        self.assertEqual(
            hashlib.sha256(donor_path.read_bytes()).hexdigest(),
            self.manifest["sourceAuthority"]["canonicalContract"]["sha256"],
        )
        self.assertEqual(
            self.manifest["commonCore"]["productSourceCommit"],
            "e374d3f8d96b1265fcdb06864208b676566e94d9",
        )
        self.assertEqual(
            self.manifest["commonCore"]["commonCoreHash"],
            "b2a1d8479dd06616430e8eea9ec720f831ccaec5f5408032bc85eb3d9a0825e9",
        )

    def test_repository_assets_match_authorized_bytes(self) -> None:
        assets = {entry["role"]: entry for entry in self.manifest["assets"]}
        self.assertEqual(set(assets), set(EXPECTED_ASSETS))

        for role, expected in EXPECTED_ASSETS.items():
            entry = assets[role]
            path = ROOT / entry["repositoryPath"]
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()

            self.assertEqual(path.name, expected["filename"])
            self.assertEqual(len(payload), expected["bytes"])
            self.assertEqual(digest, expected["sha256"])
            self.assertEqual(png_dimensions(payload), expected["dimensions"])
            canonical_source = ROOT / entry["canonicalSourcePath"]
            self.assertEqual(canonical_source.read_bytes(), payload)
            self.assertEqual(entry["canonicalSourceBytes"], len(payload))
            self.assertEqual(entry["repositoryBytes"], len(payload))
            self.assertEqual(entry["canonicalSourceSha256"], digest)
            self.assertEqual(entry["repositorySha256"], digest)
            self.assertEqual(entry["copyMode"], "exact-bytes")

    def test_old_lab_palette_and_v1_assets_are_not_formal_assets(self) -> None:
        formal_asset_names = {
            path.name
            for path in (MANIFEST_PATH.parent / "assets").iterdir()
            if path.is_file()
        }
        self.assertEqual(
            formal_asset_names,
            {expected["filename"] for expected in EXPECTED_ASSETS.values()},
        )
        self.assertEqual(
            self.manifest["theme"]["supersededPalette"],
            ["#16D6A3", "#19BBD3", "#5268F2"],
        )

    def test_desktop_derivatives_are_traceable_resizes_of_the_approved_mark(self) -> None:
        derivation = self.manifest["derivation"]
        generator = ROOT / derivation["generatorPath"]
        self.assertEqual(
            hashlib.sha256(generator.read_bytes()).hexdigest(),
            derivation["generatorSha256"],
        )
        self.assertEqual(derivation["sourceRole"], "mark")
        self.assertEqual(derivation["sourceSha256"], EXPECTED_ASSETS["mark"]["sha256"])
        self.assertEqual(derivation["operation"], "universal-canonical-generator-v1")
        self.assertFalse(derivation["designChanges"])

        assets = {entry["role"]: entry for entry in derivation["assets"]}
        self.assertEqual(set(assets), set(EXPECTED_DERIVATIVES))
        for role, (filename, expected_bytes, expected_sha256) in EXPECTED_DERIVATIVES.items():
            entry = assets[role]
            path = ROOT / entry["repositoryPath"]
            payload = path.read_bytes()
            self.assertEqual(path.name, filename)
            self.assertEqual(len(payload), expected_bytes)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha256)
            self.assertEqual(entry["bytes"], expected_bytes)
            self.assertEqual(entry["sha256"], expected_sha256)

        self.assertEqual(png_dimensions((ROOT / assets["desktop-32"]["repositoryPath"]).read_bytes()), (32, 32))
        self.assertEqual(png_dimensions((ROOT / assets["desktop-128"]["repositoryPath"]).read_bytes()), (128, 128))
        self.assertEqual(png_dimensions((ROOT / assets["desktop-256"]["repositoryPath"]).read_bytes()), (256, 256))
        self.assertEqual(
            ico_dimensions((ROOT / assets["windows-ico"]["repositoryPath"]).read_bytes()),
            {
                (16, 16),
                (20, 20),
                (24, 24),
                (32, 32),
                (40, 40),
                (48, 48),
                (64, 64),
                (128, 128),
                (256, 256),
            },
        )

    def test_integration_state_does_not_overstate_build_or_authority(self) -> None:
        self.assertEqual(
            self.manifest["integration"]["application"],
            "canonical-lockup-selected-by-lab-gate",
        )
        self.assertEqual(
            self.manifest["integration"]["installer"],
            "canonical-lab-icon-bound-in-overlay-not-built",
        )
        self.assertEqual(
            self.manifest["integration"]["shortcut"],
            "canonical-lab-executable-icon-bound-not-built",
        )

    def test_tauri_overlay_binds_lab_installer_and_shortcut_identity(self) -> None:
        overlay = json.loads(TAURI_OVERLAY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(overlay["productName"], "DroneDream · LAB")
        self.assertEqual(overlay["app"]["windows"][0]["title"], "DroneDream · LAB")

        expected_by_path = {
            entry["repositoryPath"]: entry["sha256"]
            for entry in self.manifest["derivation"]["assets"]
        }
        resolved_icons = []
        for value in overlay["bundle"]["icon"]:
            path = (TAURI_OVERLAY_PATH.parent / value).resolve()
            repository_path = path.relative_to(ROOT).as_posix()
            resolved_icons.append(repository_path)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                expected_by_path[repository_path],
            )
        self.assertEqual(set(resolved_icons), set(expected_by_path))

        resources = overlay["bundle"]["resources"]
        self.assertIn(
            "../../distribution/editions/lab/brand-source-manifest.v1.json",
            resources,
        )
        base_icon = ROOT / "desktop" / "src-tauri" / "icons" / "icon.ico"
        self.assertEqual(
            hashlib.sha256(base_icon.read_bytes()).hexdigest(),
            "88223fab6c2b0d493aaedab932c04d40def4da58e28f6d670adbfd745a6ca8ba",
        )
        self.assertNotEqual(
            hashlib.sha256(base_icon.read_bytes()).hexdigest(),
            expected_by_path["brand/generated/lab/windows/icon.ico"],
        )

    def test_green_receipt_binds_branded_source_without_claiming_an_exe(self) -> None:
        receipt = json.loads(GREEN_RECEIPT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "branded-source-and-static-installer")
        self.assertEqual(
            receipt["source"]["commit"],
            "f33af86751c3e7c52234471617723171f7103e1c",
        )
        self.assertEqual(receipt["brand"]["displayName"], "DroneDream · LAB")
        self.assertFalse(receipt["brand"]["grantsHardwareAuthority"])
        self.assertIsNone(receipt["brand"]["donorBinding"]["gitCommit"])
        self.assertEqual(
            receipt["brand"]["donorBinding"]["kind"],
            "controller-approved-exact-byte-source-directory",
        )

        report_path = ROOT / receipt["visualVerification"]["report"]["path"]
        report_bytes = report_path.read_bytes()
        self.assertEqual(len(report_bytes), receipt["visualVerification"]["report"]["bytes"])
        self.assertEqual(
            hashlib.sha256(report_bytes).hexdigest(),
            receipt["visualVerification"]["report"]["sha256"],
        )
        report = json.loads(report_bytes.decode("utf-8"))
        self.assertEqual(report["sourceCommit"], receipt["source"]["commit"])
        self.assertEqual(report["sourceStatus"], "clean")
        self.assertEqual(len(report["screenshots"]), 24)
        self.assertTrue(report["brand"]["applicationLockupLoaded"])
        self.assertFalse(report["brand"]["grantsHardwareAuthority"])

        self.assertFalse(receipt["installerStructure"]["generatedNsiVerified"])
        self.assertFalse(receipt["installerStructure"]["executableExists"])
        self.assertEqual(receipt["safety"]["validatedVehiclePackCount"], 0)
        self.assertFalse(receipt["safety"]["frontendIsAuthority"])
        self.assertFalse(receipt["safety"]["visualThemeIsAuthority"])
        self.assertEqual(receipt["safety"]["hardwareActionDecision"], "deny")
        self.assertTrue(all(value is False for value in receipt["sideEffects"].values()))

    def test_canonical_green_receipt_keeps_product_and_brand_sources_distinct(self) -> None:
        receipt = json.loads(CANONICAL_GREEN_RECEIPT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            receipt["source"]["commit"],
            "e9752238cee9123705f896a6e4ebc519c50135dc",
        )
        self.assertEqual(
            receipt["commonCore"]["productSourceCommit"],
            "e374d3f8d96b1265fcdb06864208b676566e94d9",
        )
        self.assertEqual(
            receipt["canonicalBrandDonor"]["commit"],
            "d1f0fef4e04fb5c2fbee0a4ca80b5bc59df94235",
        )
        self.assertFalse(receipt["commonCore"]["brandDonorIsProductSource"])
        self.assertFalse(receipt["canonicalBrandDonor"]["grantsHardwareAuthority"])

        for key, expected_path in (
            ("contract", "brand/brand-editions.v1.json"),
            ("assetManifest", "brand/generated/brand-assets.v1.json"),
            ("visualReceipt", "brand/generated/brand-visual-receipt.v1.json"),
        ):
            reference = receipt["canonicalBrandDonor"][key]
            self.assertEqual(reference["path"], expected_path)
            payload = (ROOT / expected_path).read_bytes()
            self.assertEqual(len(payload), reference["bytes"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), reference["sha256"])

        report_reference = receipt["visualVerification"]["acceptedReport"]
        report_payload = (ROOT / report_reference["path"]).read_bytes()
        self.assertEqual(len(report_payload), report_reference["bytes"])
        self.assertEqual(
            hashlib.sha256(report_payload).hexdigest(),
            report_reference["sha256"],
        )
        report = json.loads(report_payload.decode("utf-8"))
        self.assertEqual(report["sourceCommit"], receipt["source"]["commit"])
        self.assertEqual(report["sourceStatus"], "clean")
        self.assertEqual(report["brand"]["canonicalDonor"]["commit"], receipt["canonicalBrandDonor"]["commit"])
        self.assertEqual(len(report["screenshots"]), receipt["visualVerification"]["screenshotCount"])

        self.assertEqual(receipt["safety"]["validatedVehiclePackCount"], 0)
        self.assertEqual(receipt["safety"]["hardwareActionDecision"], "deny")
        self.assertFalse(receipt["installerStructure"]["generatedNsiVerified"])
        self.assertFalse(receipt["installerStructure"]["executableExists"])
        self.assertFalse(receipt["installerStructure"]["updaterSignatureExists"])
        self.assertTrue(all(value is False for value in receipt["sideEffects"].values()))


if __name__ == "__main__":
    unittest.main()
