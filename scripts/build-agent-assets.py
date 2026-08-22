from __future__ import annotations

import argparse
import hashlib
import importlib.util
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
BRAND_BUILDER_PATH = REPO / "scripts" / "build-brand-assets.py"
_builder_spec = importlib.util.spec_from_file_location(
    "dronedream_brand_builder", BRAND_BUILDER_PATH
)
if _builder_spec is None or _builder_spec.loader is None:
    raise RuntimeError("could not load the canonical brand builder")
_brand_builder = importlib.util.module_from_spec(_builder_spec)
_builder_spec.loader.exec_module(_brand_builder)

convert_font = _brand_builder.convert_font
fit = _brand_builder.fit
gradient_text = _brand_builder.gradient_text
png_bytes = _brand_builder.png_bytes
recolor_mark = _brand_builder.recolor_mark

STANDARD_MARK_PATH = REPO / "brand" / "source" / "approved" / "field-mark-1024.png"
STANDARD_LOCKUP_PATH = (
    REPO / "brand" / "source" / "approved" / "field-large-label-centered-lockup.png"
)
MARK_OUTPUT_PATH = REPO / "brand" / "source" / "approved" / "agent-mark-1024.png"
LOCKUP_OUTPUT_PATH = (
    REPO / "brand" / "source" / "approved" / "agent-large-label-centered-lockup.png"
)
STANDARD_MARK_SHA256 = "751372c87bc9630afc2482f5510fa51f8f52d0702a72f58307fc5ed23f9ba7f5"
STANDARD_LOCKUP_SHA256 = "e3e88cf4c14b9afdb31f1d9152fd7795f0eaec8ef63e8fd4ae52171eae09b0fa"
PALETTE = ("#FF5B74", "#EC214F", "#97153B")
CANVAS_HEIGHT = 218
WORDMARK_END_X = 1748
SEPARATOR_START_X = 1807
SEPARATOR_END_X = 1858
LABEL_START_X = 1917
LABEL_HEIGHT = 190


class AgentBrandError(RuntimeError):
    """Raised when the deterministic AGENT brand contract drifts."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def verified_image(path: Path, expected_sha256: str, expected_size: tuple[int, int]) -> Image.Image:
    payload = path.read_bytes()
    if sha256(payload) != expected_sha256:
        raise AgentBrandError(f"standard brand donor hash drifted: {path.name}")
    with Image.open(path) as source:
        image = source.convert("RGBA")
    if image.size != expected_size:
        raise AgentBrandError(f"standard brand donor dimensions drifted: {path.name}")
    return image


def build_mark() -> Image.Image:
    standard_mark = verified_image(STANDARD_MARK_PATH, STANDARD_MARK_SHA256, (1024, 1024))
    return recolor_mark(standard_mark, PALETTE)


def build_lockup() -> Image.Image:
    standard = verified_image(STANDARD_LOCKUP_PATH, STANDARD_LOCKUP_SHA256, (2581, 218))
    prefix = recolor_mark(
        standard.crop((0, 0, WORDMARK_END_X + 1, CANVAS_HEIGHT)),
        PALETTE,
    )
    separator = recolor_mark(
        standard.crop((SEPARATOR_START_X, 0, SEPARATOR_END_X + 1, CANVAS_HEIGHT)),
        PALETTE,
    )
    with tempfile.TemporaryDirectory(prefix="dronedream-agent-assets-") as temp:
        font_path = convert_font(Path(temp) / "space-grotesk-variable.ttf")
        label = gradient_text(
            font_path,
            word="AGENT",
            colors=PALETTE,
            weight=700,
            size=225,
            tracking=0,
            notch=False,
        )
    label = fit(label, 1170, LABEL_HEIGHT)
    canvas = Image.new(
        "RGBA",
        (LABEL_START_X + label.width, CANVAS_HEIGHT),
        (0, 0, 0, 0),
    )
    canvas.alpha_composite(prefix, (0, 0))
    canvas.alpha_composite(separator, (SEPARATOR_START_X, 0))
    canvas.alpha_composite(label, (LABEL_START_X, (CANVAS_HEIGHT - label.height) // 2))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {
        MARK_OUTPUT_PATH: png_bytes(build_mark()),
        LOCKUP_OUTPUT_PATH: png_bytes(build_lockup()),
    }
    if args.check:
        drifted = [
            path
            for path, payload in outputs.items()
            if not path.is_file() or path.read_bytes() != payload
        ]
        if drifted:
            raise AgentBrandError(
                "checked-in AGENT assets are stale: " + ", ".join(path.name for path in drifted)
            )
        for path, payload in outputs.items():
            print(f"Verified {path.relative_to(REPO).as_posix()} ({sha256(payload)})")
        return
    for path, payload in outputs.items():
        path.write_bytes(payload)
        print(
            f"Wrote {path.relative_to(REPO).as_posix()} ({len(payload)} bytes, {sha256(payload)})"
        )


if __name__ == "__main__":
    main()
