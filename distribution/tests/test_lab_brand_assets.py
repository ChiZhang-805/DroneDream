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


def png_dimensions(payload: bytes) -> tuple[int, int]:
    if payload[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise AssertionError("asset is not a PNG with an IHDR header")
    return struct.unpack(">II", payload[16:24])


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
            path.name for path in (MANIFEST_PATH.parent / "assets").iterdir()
        }
        self.assertEqual(
            formal_asset_names,
            {expected["filename"] for expected in EXPECTED_ASSETS.values()},
        )
        self.assertEqual(
            self.manifest["theme"]["supersededPalette"],
            ["#16D6A3", "#19BBD3", "#5268F2"],
        )

    def test_integration_state_does_not_overstate_application(self) -> None:
        self.assertEqual(
            self.manifest["integration"]["application"],
            "applied-compile-time-lab-only",
        )
        self.assertEqual(
            self.manifest["integration"]["installer"],
            "source-ready-not-applied",
        )
        self.assertEqual(
            self.manifest["integration"]["shortcut"],
            "source-ready-not-applied",
        )


if __name__ == "__main__":
    unittest.main()
