#!/usr/bin/env python3
"""Build and verify the application-facing commercial brand manifest.

The four established edition pairs remain frozen commercial masters.  The
fifth edition keeps its stable internal ``autonomy`` asset key while sourcing
the user-visible DroneDream · AGENT lockup from the approved brand contract.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
COMMERCIAL_DIR = ROOT / "brand" / "commercial"
MANIFEST_PATH = COMMERCIAL_DIR / "manifest.json"
MANAGED_SOURCES = {
    "autonomy-lockup.png": ROOT
    / "brand"
    / "source"
    / "approved"
    / "agent-large-label-centered-lockup.png",
    "autonomy-mark.png": ROOT / "brand" / "source" / "approved" / "agent-mark-1024.png",
}
ASSET_NAMES = (
    "autonomy-lockup.png",
    "autonomy-mark.png",
    "field-lockup.png",
    "field-mark.png",
    "lab-lockup.png",
    "lab-mark.png",
    "sim-lockup.png",
    "sim-mark.png",
    "universal-lockup-white.png",
    "universal-lockup.png",
    "universal-mark-white.png",
    "universal-mark.png",
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def asset_entry(name: str, payload: bytes) -> dict[str, object]:
    with Image.open(io.BytesIO(payload)) as image:
        width, height = image.size
    return {
        "path": name,
        "width": width,
        "height": height,
        "sha256": sha256(payload),
        "background": "white" if name.endswith("-white.png") else "transparent",
    }


def expected_outputs() -> tuple[dict[str, bytes], bytes]:
    payloads: dict[str, bytes] = {}
    for name in ASSET_NAMES:
        source = MANAGED_SOURCES.get(name, COMMERCIAL_DIR / name)
        if not source.is_file():
            raise FileNotFoundError(f"commercial brand source is missing: {source}")
        payloads[name] = source.read_bytes()
    manifest = {
        "kind": "dronedream-commercial-brand-assets",
        "assetCount": len(payloads),
        "naturalWidthLockups": True,
        "compactLockupsAllowed": False,
        "assets": [asset_entry(name, payloads[name]) for name in sorted(payloads)],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return payloads, manifest_bytes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payloads, manifest_bytes = expected_outputs()
    expected = {COMMERCIAL_DIR / name: payload for name, payload in payloads.items()}
    expected[MANIFEST_PATH] = manifest_bytes
    if args.check:
        drifted = [path for path, payload in expected.items() if not path.is_file() or path.read_bytes() != payload]
        if drifted:
            for path in drifted:
                print(f"DRIFT: {path.relative_to(ROOT)}")
            return 1
        print(f"Verified {len(payloads)} commercial brand assets")
        return 0
    for path, payload in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    print(f"Generated {len(payloads)} commercial brand assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
