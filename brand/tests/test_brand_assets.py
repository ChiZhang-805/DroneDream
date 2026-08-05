from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "brand" / "brand-editions.v1.json"
SCHEMA_PATH = ROOT / "brand" / "brand-editions.schema.json"
MANIFEST_PATH = ROOT / "brand" / "generated" / "brand-assets.v1.json"
EDITION_IDS = ("universal", "sim", "lab", "field")
APPROVED_HASHES = {
    "sim": {
        "markPath": "brand/source/approved/sim-mark-1024.png",
        "dotLockupPath": "brand/source/approved/sim-dot-lockup.png",
        "markSha256": "5b35f8eeccb2742d53888d222e9b6c12b449e03af927a1b7631175e8ac510dfa",
        "dotLockupSha256": ("8cd55f8008bf1c634c9c1b72a59c4ca21a625413bc71a6c421899e347b650548"),
    },
    "lab": {
        "markPath": "brand/source/approved/lab-mark-1024.png",
        "dotLockupPath": "brand/source/approved/lab-dot-lockup.png",
        "markSha256": "63d87e2ba200fb6d728a8b8bba96f7f593f216890a376e31b0796596405d0806",
        "dotLockupSha256": ("b01b87ce92199b7781453aade99c5428fe2bd4b8c141f0aacdd05346e683bc91"),
    },
    "field": {
        "markPath": "brand/source/approved/field-mark-1024.png",
        "dotLockupPath": "brand/source/approved/field-dot-lockup.png",
        "markSha256": "751372c87bc9630afc2482f5510fa51f8f52d0702a72f58307fc5ed23f9ba7f5",
        "dotLockupSha256": ("def3920c2fd355e9ef5a6d4f95d4334e03d02dc2c94eb764e41af154eb03f192"),
    },
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_brand_contract_freezes_approved_names_palettes_and_safety_boundary() -> None:
    contract = load_json(CONTRACT_PATH)
    schema = load_json(SCHEMA_PATH)

    assert contract["separator"] == "·"
    assert schema["properties"]["separator"]["const"] == "·"
    assert contract["safety"] == {
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
    }
    assert contract["approval"] == {
        "handoffSha256": ("9fc52dea2edab1b65aa8c814fbf05ff1ad4fea0de4980403bec84dab8a1d9657"),
        "conceptAssetsAreReleaseAssets": False,
    }
    for edition_id, expected_hashes in APPROVED_HASHES.items():
        descriptor = contract["approvedEditionAssets"][edition_id]
        assert descriptor["markPath"] == expected_hashes["markPath"]
        assert descriptor["dotLockupPath"] == expected_hashes["dotLockupPath"]
        assert descriptor["markSha256"] == expected_hashes["markSha256"]
        assert descriptor["dotLockupSha256"] == expected_hashes["dotLockupSha256"]
        assert sha256(ROOT / descriptor["markPath"]) == expected_hashes["markSha256"]
        assert sha256(ROOT / descriptor["dotLockupPath"]) == expected_hashes["dotLockupSha256"]
    assert {
        edition_id: {
            "productName": contract["editions"][edition_id]["productName"],
            "gradientStops": contract["editions"][edition_id]["gradientStops"],
        }
        for edition_id in EDITION_IDS
    } == {
        "universal": {
            "productName": "DroneDream",
            "gradientStops": ["#FF5574", "#6A4CFF", "#E657D1"],
        },
        "sim": {
            "productName": "DroneDream · SIM",
            "gradientStops": ["#00D9FF", "#2671FF", "#744CFF"],
        },
        "lab": {
            "productName": "DroneDream · LAB",
            "gradientStops": ["#A7E84A", "#20C77A", "#087E69"],
        },
        "field": {
            "productName": "DroneDream · FIELD",
            "gradientStops": ["#FFC247", "#FF754B", "#D746A5"],
        },
    }


def test_manifest_binds_every_generated_byte_dimension_and_ico_frame() -> None:
    contract = load_json(CONTRACT_PATH)
    manifest = load_json(MANIFEST_PATH)
    asset_paths = [asset["path"] for asset in manifest["assets"]]

    assert asset_paths == sorted(asset_paths)
    assert len(asset_paths) == len(set(asset_paths)) == 68
    assert manifest["universalIsCanonical"] is True
    assert manifest["presentationOnly"] is True
    assert manifest["grantsHardwareAuthority"] is False
    assert manifest["conceptAssetsAreReleaseAssets"] is False
    assert manifest["contractSha256"] == sha256(CONTRACT_PATH)
    assert manifest["schemaSha256"] == sha256(SCHEMA_PATH)
    assert manifest["lockedRequirements"]["sha256"] == sha256(ROOT / "brand/requirements.lock.txt")
    for edition_id, expected_hashes in APPROVED_HASHES.items():
        assert (
            manifest["approvedEditionAssets"][edition_id]["mark"]["sha256"]
            == (expected_hashes["markSha256"])
        )
        assert (
            manifest["approvedEditionAssets"][edition_id]["dotLockup"]["sha256"]
            == (expected_hashes["dotLockupSha256"])
        )

    for asset in manifest["assets"]:
        path = ROOT / asset["path"]
        assert path.is_file(), asset["path"]
        assert path.stat().st_size == asset["bytes"], asset["path"]
        assert sha256(path) == asset["sha256"], asset["path"]
        if asset["format"] == "PNG":
            with Image.open(path) as image:
                assert image.size == (asset["width"], asset["height"])
        if asset["format"] == "ICO":
            with Image.open(path) as image:
                assert sorted(image.ico.sizes()) == [(size, size) for size in asset["frameSizesPx"]]
                assert (
                    asset["frameSizesPx"] == contract["artifactContract"]["windowsIcoFrameSizesPx"]
                )


def test_all_editions_preserve_shared_white_flight_path_and_exact_mirrors() -> None:
    for edition_id in EDITION_IDS:
        canonical = ROOT / f"brand/generated/{edition_id}/mark-1024.png"
        frontend = ROOT / f"frontend/src/assets/brand/{edition_id}-mark.png"
        assert canonical.read_bytes() == frontend.read_bytes()
        with Image.open(canonical).convert("RGBA") as image:
            white_detail_pixels = sum(
                1
                for red, green, blue, alpha in image.get_flattened_data()
                if alpha > 200 and min(red, green, blue) > 230
            )
        assert white_detail_pixels > 500

    contract = load_json(CONTRACT_PATH)
    for edition_id in EDITION_IDS[1:]:
        descriptor = contract["approvedEditionAssets"][edition_id]
        assert (ROOT / descriptor["markPath"]).read_bytes() == (
            ROOT / f"brand/generated/{edition_id}/mark-1024.png"
        ).read_bytes()
        approved_lockup = (ROOT / descriptor["dotLockupPath"]).read_bytes()
        assert (
            approved_lockup
            == (ROOT / f"brand/generated/{edition_id}/lockup-primary.png").read_bytes()
        )
        assert (
            approved_lockup
            == (ROOT / f"brand/generated/{edition_id}/lockup-compact.png").read_bytes()
        )

    universal_mirrors = (
        ROOT / "docs/assets/drone-dream-icon.png",
        ROOT / "frontend/src/assets/drone-dream-mark.png",
        ROOT / "desktop/src-tauri/app-icon.png",
    )
    expected = (ROOT / "brand/generated/universal/mark-1024.png").read_bytes()
    assert all(path.read_bytes() == expected for path in universal_mirrors)
    assert (ROOT / "desktop/src-tauri/icons/icon.ico").read_bytes() == (
        ROOT / "brand/generated/universal/windows/icon.ico"
    ).read_bytes()


def test_brand_generation_is_reproducible_from_repository_owned_inputs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build-brand-assets.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "verified"
    assert receipt["assetCount"] == 68
    assert receipt["presentationOnly"] is True
    assert receipt["universalIsCanonical"] is True

    production_inputs = (
        CONTRACT_PATH,
        SCHEMA_PATH,
        ROOT / "scripts/build-brand-assets.py",
        ROOT / "frontend/src/brand/edition-brand.generated.ts",
        ROOT / "frontend/src/brand/edition-brand.generated.css",
    )
    assert all("work/" not in path.read_text(encoding="utf-8") for path in production_inputs)
