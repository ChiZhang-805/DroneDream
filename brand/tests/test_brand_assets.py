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
EDITION_IDS = ("universal", "sim", "lab", "field", "autonomy")
APPROVED_HASHES = {
    "sim": {
        "markPath": "brand/source/approved/sim-mark-1024.png",
        "dotLockupPath": "brand/source/approved/sim-large-label-centered-lockup.png",
        "markSha256": "5b35f8eeccb2742d53888d222e9b6c12b449e03af927a1b7631175e8ac510dfa",
        "dotLockupSha256": ("f3dd34d3e1a546e4299370d6cbe21d9f03b07a5910dcae061a322ba6c548fd6e"),
        "dotLockupDimensions": {"width": 2337, "height": 218},
        "separatorGeometry": {
            "wordmarkEndX": 1748,
            "separatorStartX": 1802,
            "separatorEndX": 1851,
            "editionLabelStartX": 1905,
            "leftGapPx": 53,
            "rightGapPx": 53,
        },
        "supersededLargeLabelPath": "brand/source/approved/sim-large-label-lockup.png",
        "supersededLargeLabelSha256": (
            "d11e727f4024f356a3850271aa3349d7286e2da85f647d145388c5d1eec20233"
        ),
    },
    "lab": {
        "markPath": "brand/source/approved/lab-mark-1024.png",
        "dotLockupPath": "brand/source/approved/lab-large-label-centered-lockup.png",
        "markSha256": "63d87e2ba200fb6d728a8b8bba96f7f593f216890a376e31b0796596405d0806",
        "dotLockupSha256": ("c82b6580a3f2d22018a99cbadbb90179838f3ec9f481e273466320f1aa021c94"),
        "dotLockupDimensions": {"width": 2386, "height": 218},
        "separatorGeometry": {
            "wordmarkEndX": 1748,
            "separatorStartX": 1807,
            "separatorEndX": 1858,
            "editionLabelStartX": 1917,
            "leftGapPx": 58,
            "rightGapPx": 58,
        },
        "supersededLargeLabelPath": "brand/source/approved/lab-large-label-lockup.png",
        "supersededLargeLabelSha256": (
            "5abee1b88d50d0443fe47da0e4866257487856a2ee5269a213a1320585b6adea"
        ),
    },
    "field": {
        "markPath": "brand/source/approved/field-mark-1024.png",
        "dotLockupPath": "brand/source/approved/field-large-label-centered-lockup.png",
        "markSha256": "751372c87bc9630afc2482f5510fa51f8f52d0702a72f58307fc5ed23f9ba7f5",
        "dotLockupSha256": ("e3e88cf4c14b9afdb31f1d9152fd7795f0eaec8ef63e8fd4ae52171eae09b0fa"),
        "dotLockupDimensions": {"width": 2581, "height": 218},
        "separatorGeometry": {
            "wordmarkEndX": 1748,
            "separatorStartX": 1807,
            "separatorEndX": 1858,
            "editionLabelStartX": 1917,
            "leftGapPx": 58,
            "rightGapPx": 58,
        },
        "supersededLargeLabelPath": "brand/source/approved/field-large-label-lockup.png",
        "supersededLargeLabelSha256": (
            "588c5aca42b09fa3396efc63a7423bbf1e182379e1a41427f716a1b9f73fbd27"
        ),
    },
    "autonomy": {
        "markPath": "brand/source/approved/autonomy-mark-1024.png",
        "dotLockupPath": "brand/source/approved/autonomy-large-label-centered-lockup.png",
        "markSha256": "a67fe1fb2558471806fe19c3eb9423d041a1a5de58a30bfb9893353c00a9f651",
        "dotLockupSha256": (
            "8f8ce7bc4a8cf1782fe006c05f4798201ac063625bb8d9c98070f61491b84b2b"
        ),
        "dotLockupDimensions": {"width": 3090, "height": 340},
        "dotLockupStyle": "autonomy-approved-lockup-v1",
        "separatorTolerancePx": 9,
        "separatorGeometry": {
            "wordmarkEndX": 1718,
            "separatorStartX": 1789,
            "separatorEndX": 1853,
            "editionLabelStartX": 1915,
            "leftGapPx": 70,
            "rightGapPx": 61,
        },
    },
}

CANONICAL_ICO_HASHES = {
    "universal": "88223fab6c2b0d493aaedab932c04d40def4da58e28f6d670adbfd745a6ca8ba",
    "sim": "9683781a32b9292aecfdc5044c2841089c9f2b4e8a04e0a24ebefcc799c2982c",
    "lab": "67b5747de298ffcf64d062294829306bd9b66df4ee52cfa8a8e3498cb94d5fa1",
    "field": "b90e188679d209009e5eda859665a3582efe1e9129e5f8ecce3c08783b794559",
    "autonomy": "a8a1eb24801bf3ab07503e0c669f0ef6b6c5cf71af1fd160c8e3806324c0a138",
}
WEBSITE_FAVICON = {
    "sourcePath": "brand/source/approved/website-favicon-64.png",
    "sourceSha256": "39f1c9e1bec804cb5834b12514408c9673b3a954d5c75544a5f92802387f2ea7",
    "dimensions": {"width": 64, "height": 64},
    "canonicalOutputPath": "frontend/public/drone-favicon.png",
    "approvalBasis": "mainland-preview-approved-v1",
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

    assert contract["brandVersion"] == "1.2.0"
    assert contract["separator"] == "\u00b7"
    assert schema["properties"]["separator"]["const"] == "\u00b7"
    assert contract["safety"] == {
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
    }
    assert contract["websiteFavicon"] == WEBSITE_FAVICON
    approved_favicon = ROOT / WEBSITE_FAVICON["sourcePath"]
    assert sha256(approved_favicon) == WEBSITE_FAVICON["sourceSha256"]
    with Image.open(approved_favicon) as image:
        assert image.size == (64, 64)
        assert image.mode == "RGBA"
    assert contract["approval"] == {
        "handoffSha256": ("9fc52dea2edab1b65aa8c814fbf05ff1ad4fea0de4980403bec84dab8a1d9657"),
        "conceptAssetsAreReleaseAssets": False,
        "largeLabelLockupsAreCanonicalSources": True,
        "largeLabelReviewPreviewPath": (
            "brand/source/approved/edition-brand-centered-separator-approved-preview.png"
        ),
        "largeLabelReviewPreviewSha256": (
            "77d5326be1155528d9585a56de99c80364640ed7f4d488222c7f581ef70da02e"
        ),
        "largeLabelReviewPreviewDimensions": {"width": 5200, "height": 1680},
        "largeLabelReviewStudySha256": (
            "9b3e9a274ef51393ffbf8ba3cf5d41224a0cafc9990deddeafcef1a92122353a"
        ),
        "editionLabelHeightRatio": 0.9,
        "preserveNaturalLabelWidth": True,
        "separatorCentering": {
            "method": "equal-alpha-edge-gaps",
            "tolerancePx": 0,
        },
    }
    approved_preview = ROOT / contract["approval"]["largeLabelReviewPreviewPath"]
    assert sha256(approved_preview) == contract["approval"]["largeLabelReviewPreviewSha256"]
    with Image.open(approved_preview) as image:
        assert image.size == (5200, 1680)
        assert image.mode == "RGB"
    for edition_id, expected_hashes in APPROVED_HASHES.items():
        descriptor = contract["approvedEditionAssets"][edition_id]
        assert descriptor["markPath"] == expected_hashes["markPath"]
        assert descriptor["dotLockupPath"] == expected_hashes["dotLockupPath"]
        assert descriptor["markSha256"] == expected_hashes["markSha256"]
        assert descriptor["dotLockupSha256"] == expected_hashes["dotLockupSha256"]
        assert descriptor["dotLockupDimensions"] == expected_hashes["dotLockupDimensions"]
        assert descriptor["dotLockupStyle"] == expected_hashes.get(
            "dotLockupStyle",
            "large-edition-label-centered-separator-v2",
        )
        assert descriptor["separatorGeometry"] == expected_hashes["separatorGeometry"]
        if "separatorTolerancePx" in expected_hashes:
            assert descriptor["separatorTolerancePx"] == expected_hashes["separatorTolerancePx"]
            assert "supersededLargeLabelLockup" not in descriptor
        else:
            assert descriptor["supersededLargeLabelLockup"] == {
                "path": expected_hashes["supersededLargeLabelPath"],
                "sha256": expected_hashes["supersededLargeLabelSha256"],
                "status": "superseded-by-centered-separator-v2",
            }
        assert sha256(ROOT / descriptor["markPath"]) == expected_hashes["markSha256"]
        assert sha256(ROOT / descriptor["dotLockupPath"]) == expected_hashes["dotLockupSha256"]
        if "supersededLargeLabelPath" in expected_hashes:
            assert sha256(ROOT / expected_hashes["supersededLargeLabelPath"]) == expected_hashes[
                "supersededLargeLabelSha256"
            ]
        with Image.open(ROOT / descriptor["dotLockupPath"]) as lockup:
            assert lockup.size == (
                expected_hashes["dotLockupDimensions"]["width"],
                expected_hashes["dotLockupDimensions"]["height"],
            )
            assert lockup.mode == "RGBA"
            alpha = lockup.getchannel("A")
            geometry = expected_hashes["separatorGeometry"]
            left_gap = geometry["separatorStartX"] - geometry["wordmarkEndX"] - 1
            right_gap = geometry["editionLabelStartX"] - geometry["separatorEndX"] - 1
            tolerance = expected_hashes.get("separatorTolerancePx", 0)
            assert abs(left_gap - right_gap) <= tolerance
            assert left_gap == geometry["leftGapPx"]
            assert right_gap == geometry["rightGapPx"]
            assert alpha.crop(
                (
                    geometry["wordmarkEndX"] + 1,
                    0,
                    geometry["separatorStartX"],
                    lockup.height,
                )
            ).getbbox() is None
            assert alpha.crop(
                (
                    geometry["separatorEndX"] + 1,
                    0,
                    geometry["editionLabelStartX"],
                    lockup.height,
                )
            ).getbbox() is None
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
        "autonomy": {
            "productName": "DroneDream · AUTONOMY",
            "gradientStops": ["#FF5B74", "#EC214F", "#97153B"],
        },
    }
    for edition_id in EDITION_IDS[1:]:
        assert contract["editions"][edition_id]["productName"].split()[1] == "\u00b7"


def test_manifest_binds_every_generated_byte_dimension_and_ico_frame() -> None:
    contract = load_json(CONTRACT_PATH)
    manifest = load_json(MANIFEST_PATH)
    asset_paths = [asset["path"] for asset in manifest["assets"]]

    assert asset_paths == sorted(asset_paths)
    assert len(asset_paths) == len(set(asset_paths)) == 81
    assert manifest["universalIsCanonical"] is True
    assert manifest["presentationOnly"] is True
    assert manifest["grantsHardwareAuthority"] is False
    assert manifest["conceptAssetsAreReleaseAssets"] is False
    assert manifest["brandVersion"] == "1.2.0"
    assert manifest["websiteFavicon"] == {
        "sourcePath": WEBSITE_FAVICON["sourcePath"],
        "bytes": (ROOT / WEBSITE_FAVICON["sourcePath"]).stat().st_size,
        "sha256": WEBSITE_FAVICON["sourceSha256"],
        "dimensions": WEBSITE_FAVICON["dimensions"],
        "canonicalOutputPath": WEBSITE_FAVICON["canonicalOutputPath"],
        "approvalBasis": WEBSITE_FAVICON["approvalBasis"],
    }
    assert manifest["largeLabelApproval"] == {
        "canonicalSources": True,
        "reviewPreviewPath": (
            "brand/source/approved/edition-brand-centered-separator-approved-preview.png"
        ),
        "reviewPreviewSha256": (
            "77d5326be1155528d9585a56de99c80364640ed7f4d488222c7f581ef70da02e"
        ),
        "reviewStudySha256": (
            "9b3e9a274ef51393ffbf8ba3cf5d41224a0cafc9990deddeafcef1a92122353a"
        ),
        "editionLabelHeightRatio": 0.9,
        "preserveNaturalLabelWidth": True,
        "separatorCentering": {
            "method": "equal-alpha-edge-gaps",
            "tolerancePx": 0,
        },
    }
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
        assert (
            manifest["approvedEditionAssets"][edition_id]["dotLockup"]["dimensions"]
            == expected_hashes["dotLockupDimensions"]
        )
        assert (
            manifest["approvedEditionAssets"][edition_id]["dotLockup"]["separatorGeometry"]
            == expected_hashes["separatorGeometry"]
        )
        if "supersededLargeLabelPath" in expected_hashes:
            assert manifest["approvedEditionAssets"][edition_id][
                "supersededLargeLabelLockup"
            ] == {
                "path": expected_hashes["supersededLargeLabelPath"],
                "sha256": expected_hashes["supersededLargeLabelSha256"],
                "status": "superseded-by-centered-separator-v2",
            }
        else:
            assert "supersededLargeLabelLockup" not in manifest["approvedEditionAssets"][
                edition_id
            ]

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
    for edition_id, expected_hash in CANONICAL_ICO_HASHES.items():
        assert sha256(ROOT / f"brand/generated/{edition_id}/windows/icon.ico") == expected_hash


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
    assert (ROOT / WEBSITE_FAVICON["canonicalOutputPath"]).read_bytes() == (
        ROOT / WEBSITE_FAVICON["sourcePath"]
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
    assert receipt["assetCount"] == 81
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
