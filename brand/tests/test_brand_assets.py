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
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract() -> dict[str, object]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["kind"] == "dronedream-edition-brand-system"
    assert payload["separator"] == "·"
    assert payload["safety"] == {
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
    }
    assert tuple(payload["editions"]) == EDITION_IDS
    return payload


def test_exactly_ten_transparent_canonical_icons() -> None:
    contract = load_contract()
    files = {path.name for path in ICON_DIR.iterdir() if path.is_file()}
    assert files == EXPECTED_NAMES
    assert len(files) == 10

    declared_paths = set()
    for edition in contract["editions"].values():
        for kind in ("mark", "lockup"):
            descriptor = edition[kind]
            path = ROOT / descriptor["path"]
            declared_paths.add(path.resolve())
            assert path.parent == ICON_DIR
            assert sha256(path) == descriptor["sha256"]
            with Image.open(path) as image:
                assert image.format == "PNG"
                assert image.mode == "RGBA"
                assert image.size == (descriptor["width"], descriptor["height"])
                assert image.getchannel("A").getextrema() == (0, 255)
    assert declared_paths == {path.resolve() for path in ICON_DIR.iterdir()}


def test_visible_names_and_wordmark_geometry_are_locked() -> None:
    contract = load_contract()
    assert {
        edition_id: edition["productName"]
        for edition_id, edition in contract["editions"].items()
    } == {
        "universal": "DroneDream",
        "sim": "DroneDream · SIM",
        "lab": "DroneDream · LAB",
        "field": "DroneDream · FIELD",
        "autonomy": "DroneDream · AGENT",
    }

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


def test_windows_derivatives_are_generated_only_in_temporary_output(
    tmp_path: Path,
) -> None:
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
        expected_sizes = {
            "32x32.png": (32, 32),
            "128x128.png": (128, 128),
            "128x128@2x.png": (256, 256),
        }
        for name, size in expected_sizes.items():
            with Image.open(windows / name) as image:
                assert image.format == "PNG"
                assert image.mode == "RGBA"
                assert image.size == size
        with Image.open(windows / "icon.ico") as image:
            assert sorted(image.ico.sizes()) == [
                (size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)
            ]
    with Image.open(favicon) as image:
        assert image.size == (64, 64)
        assert image.mode == "RGBA"


def test_no_tracked_duplicate_brand_image_roots() -> None:
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
        "frontend/public/drone-favicon.png",
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
        if path in banned_exact or path.startswith(banned_prefixes)
    ]
    assert duplicates == []
