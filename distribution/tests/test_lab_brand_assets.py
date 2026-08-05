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
    "desktop-32": ("32x32.png", 2046, "fca69d87a8f7a68618eae06a791158ce47a2abc665b34be3d2ab111e1001ddd5"),
    "desktop-128": ("128x128.png", 11316, "0dcf0ae7449d21dcd27c5985a279ac17abd359aaa204b113e6ab45e6a02ad4f7"),
    "desktop-256": ("128x128@2x.png", 25495, "ebede2b419aff90be66ab607f3de52f8e98b7c2c37986408035b38f4aee3a36b"),
    "windows-ico": ("icon.ico", 52067, "4dcdd9792a810226cf898a0f85a67ee4d45dd2a1424eb46d8b1c5caae007424d"),
}


def png_dimensions(payload: bytes) -> tuple[int, int]:
    if payload[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise AssertionError("asset is not a PNG with an IHDR header")
    return struct.unpack(">II", payload[16:24])


def ico_dimensions(payload: bytes) -> set[tuple[int, int]]:
    reserved, image_type, count = struct.unpack("<HHH", payload[:6])
    if (reserved, image_type, count) != (0, 1, 7):
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
            self.assertEqual(entry["sourceBytes"], len(payload))
            self.assertEqual(entry["repositoryBytes"], len(payload))
            self.assertEqual(entry["sourceSha256"], digest)
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
        self.assertEqual(derivation["operation"], "rgba-lanczos-resize-and-ico-container-only")
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
            {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)},
        )

    def test_integration_state_does_not_overstate_build_or_authority(self) -> None:
        self.assertEqual(
            self.manifest["integration"]["application"],
            "applied-compile-time-lab-only",
        )
        self.assertEqual(
            self.manifest["integration"]["installer"],
            "applied-lab-overlay-not-built",
        )
        self.assertEqual(
            self.manifest["integration"]["shortcut"],
            "applied-through-lab-executable-icon-not-built",
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
            "e2b4f1ac3e48f6e49e78c86e4a805ed4cfdb15f9f0bfff458c41e5fbe2c26a53",
        )
        self.assertNotEqual(
            hashlib.sha256(base_icon.read_bytes()).hexdigest(),
            expected_by_path["distribution/editions/lab/assets/desktop/icon.ico"],
        )


if __name__ == "__main__":
    unittest.main()
