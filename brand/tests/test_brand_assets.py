from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "brand" / "editions.json"
ICON_DIR = ROOT / "brand" / "icons"
EDITION_IDS = ("universal", "sim", "lab", "field", "autonomy")
EXPECTED_NAMES = {
    "universal-lockup.png",
    "universal-mark.png",
    "sim-lockup.png",
    "sim-mark.png",
    "lab-lockup.png",
    "lab-mark.png",
    "field-lockup.png",
    "field-mark.png",
    "agent-lockup.png",
    "agent-mark.png",
    "website-favicon-64.png",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract() -> dict[str, object]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_contract_binds_the_single_canonical_brand_source_inventory() -> None:
    contract = _contract()

    assert contract["schemaVersion"] == 1
    assert contract["kind"] == "dronedream-edition-brand-system"
    assert contract["separator"] == "·"
    assert contract["safety"] == {
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
    }
    editions = contract["editions"]
    assert isinstance(editions, dict)
    assert tuple(editions) == EDITION_IDS
    assert {path.name for path in ICON_DIR.glob("*.png")} == EXPECTED_NAMES

    for edition_id in EDITION_IDS:
        edition = editions[edition_id]
        assert isinstance(edition, dict)
        for role in ("mark", "lockup"):
            descriptor = edition[role]
            assert isinstance(descriptor, dict)
            path = ROOT / str(descriptor["path"])
            assert path.parent == ICON_DIR
            assert _sha256(path) == descriptor["sha256"]
            with Image.open(path) as image:
                assert image.format == "PNG"
                assert image.mode == "RGBA"
                assert image.size == (descriptor["width"], descriptor["height"])


def test_edition_lockups_preserve_centered_separator_geometry() -> None:
    editions = _contract()["editions"]
    assert isinstance(editions, dict)

    for edition_id in EDITION_IDS[1:]:
        edition = editions[edition_id]
        assert isinstance(edition, dict)
        lockup = ROOT / str(edition["lockup"]["path"])
        with Image.open(lockup).convert("RGBA") as image:
            alpha = image.getchannel("A")
            wordmark_end = int(edition["wordmarkEndX"])
            separator_start = int(edition["separatorStartX"])
            separator_end = int(edition["separatorEndX"])
            label_start = int(edition["editionLabelStartX"])
            assert separator_start - wordmark_end - 1 == label_start - separator_end - 1
            assert (
                alpha.crop((wordmark_end + 1, 0, separator_start, image.height)).getbbox() is None
            )
            assert alpha.crop((separator_end + 1, 0, label_start, image.height)).getbbox() is None


def test_all_marks_preserve_the_white_flight_path_detail() -> None:
    editions = _contract()["editions"]
    assert isinstance(editions, dict)

    for edition_id in EDITION_IDS:
        edition = editions[edition_id]
        assert isinstance(edition, dict)
        mark = ROOT / str(edition["mark"]["path"])
        with Image.open(mark).convert("RGBA") as image:
            white_detail_pixels = sum(
                1
                for red, green, blue, alpha in image.get_flattened_data()
                if alpha > 200 and min(red, green, blue) > 230
            )
        assert white_detail_pixels > 500


def test_brand_generation_is_reproducible_from_repository_owned_inputs() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build-brand-assets.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "verified",
        "canonicalIconCount": 10,
    }


def test_windows_derivatives_are_generated_only_in_temporary_output(tmp_path: Path) -> None:
    derivative_root = tmp_path / "brand"
    favicon = tmp_path / "drone-favicon.png"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build-brand-assets.py",
            "--edition",
            "all",
            "--derivative-root",
            str(derivative_root),
            "--favicon-path",
            str(favicon),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "generated"
    assert tuple(receipt["editionIds"]) == EDITION_IDS
    assert receipt["derivativeCount"] == 21

    for edition_id in EDITION_IDS:
        windows = derivative_root / edition_id / "windows"
        for name, size in {
            "32x32.png": (32, 32),
            "128x128.png": (128, 128),
            "128x128@2x.png": (256, 256),
        }.items():
            with Image.open(windows / name) as image:
                assert image.format == "PNG"
                assert image.mode == "RGBA"
                assert image.size == size
        with Image.open(windows / "icon.ico") as image:
            assert sorted(image.ico.sizes()) == [
                (size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)
            ]
    assert favicon.read_bytes() == (ICON_DIR / "website-favicon-64.png").read_bytes()


def test_no_tracked_retired_brand_image_roots() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    banned_prefixes = (
        "brand/commercial/",
        "brand/generated/",
        "brand/source/",
        "frontend/src/assets/brand/",
        "frontend/src/assets/drone-dream-",
        "desktop/src-tauri/icons/",
    )
    banned_exact = {
        "desktop/src-tauri/app-icon.png",
        "desktop/src-tauri/icon-source.svg",
        "frontend/public/drone-favicon.svg",
        "docs/assets/drone-dream-icon.png",
        "docs/assets/drone-dream-logo-source.png",
        "docs/assets/brand/drone-dream-lockup-compact.png",
        "docs/assets/brand/drone-dream-lockup-primary.png",
        "docs/assets/brand/drone-dream-logo-horizontal-white.png",
        "docs/assets/brand/drone-dream-wordmark-compact.png",
        "docs/assets/brand/drone-dream-wordmark-primary.png",
        "scripts/build-agent-assets.py",
        "scripts/build-commercial-brand-assets.py",
    }

    duplicates = [
        path
        for path in tracked
        if (ROOT / path).exists() and (path in banned_exact or path.startswith(banned_prefixes))
    ]
    assert duplicates == []
