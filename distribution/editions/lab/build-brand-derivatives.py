#!/usr/bin/env python3
"""Build deterministic desktop icon derivatives from the approved Lab V2 mark."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "assets" / "dronedream-lab-mark-v2.png"
OUTPUT = ROOT / "assets" / "desktop"
SOURCE_SHA256 = "63d87e2ba200fb6d728a8b8bba96f7f593f216890a376e31b0796596405d0806"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resized(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def build() -> None:
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Lab desktop icons require the exact approved Lab V2 mark bytes")

    with Image.open(SOURCE) as opened:
        source = opened.convert("RGBA")
    if source.size != (1024, 1024):
        raise ValueError("Lab V2 mark dimensions drifted")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for size, filename in (
        (32, "32x32.png"),
        (128, "128x128.png"),
        (256, "128x128@2x.png"),
    ):
        resized(source, size).save(OUTPUT / filename, format="PNG", optimize=True)

    source.save(
        OUTPUT / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    build()
