from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = ROOT / "frontend" / "public" / "docs" / "downloads"
LOCKUP = DOWNLOADS / "manual-assets" / "brand" / "dronedream-lockup-primary.png"

WIDTH = 910
HEIGHT = 1287
CONTENT_LEFT = 78
INK = "#171225"
MUTED = "#615D6C"
PURPLE = "#7047FF"
CYAN = "#48D5E8"
PINK = "#ED3CB7"

WINDOWS_FONTS = Path("C:/Windows/Fonts")
ARIAL = WINDOWS_FONTS / "arial.ttf"
ARIAL_BOLD = WINDOWS_FONTS / "arialbd.ttf"
NOTO_SC = WINDOWS_FONTS / "NotoSansSC-VF.ttf"

MANUALS = {
    "en": {
        "source": DOWNLOADS / "DroneDream-Manual-en.md",
        "output": DOWNLOADS / "DroneDream-Manual-en-cover.png",
    },
    "zh-CN": {
        "source": DOWNLOADS / "DroneDream-Manual-zh-CN.md",
        "output": DOWNLOADS / "DroneDream-Manual-zh-CN-cover.png",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.match(r"\A---\n(?P<header>.*?)\n---(?:\n|\Z)", text, re.DOTALL)
    if match is None:
        raise RuntimeError(f"Manual metadata block is missing: {path}")

    metadata: dict[str, str] = {}
    for line in match.group("header").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw_value = line.partition(":")
        if not separator:
            raise RuntimeError(f"Unsupported manual metadata line in {path}: {line}")
        value = raw_value.strip()
        if value.startswith(('"', "'")):
            if value.startswith('"'):
                value = json.loads(value)
            else:
                value = value[1:-1]
        metadata[key.strip()] = value

    required = {
        "title",
        "author",
        "version",
        "coverkicker",
        "authorlabel",
        "versionlabel",
        "editionlabel",
        "edition",
        "covercopyright",
    }
    missing = sorted(required - metadata.keys())
    if missing:
        raise RuntimeError(f"Manual metadata is incomplete in {path}: {missing}")
    return metadata


def font(path: Path, size: int, *, weight: int | None = None) -> ImageFont.FreeTypeFont:
    if not path.is_file():
        raise RuntimeError(f"Required cover font is missing: {path}")
    loaded = ImageFont.truetype(str(path), size=size)
    if weight is not None and hasattr(loaded, "set_variation_by_axes"):
        loaded.set_variation_by_axes([weight])
    return loaded


def locale_fonts(locale: str) -> dict[str, ImageFont.FreeTypeFont]:
    if locale == "zh-CN":
        return {
            "kicker": font(NOTO_SC, 15, weight=700),
            "title": font(NOTO_SC, 43, weight=760),
            "label": font(NOTO_SC, 18, weight=700),
            "value": font(NOTO_SC, 18, weight=430),
            "copyright": font(NOTO_SC, 15, weight=430),
        }
    return {
        "kicker": font(ARIAL_BOLD, 15),
        "title": font(ARIAL_BOLD, 43),
        "label": font(ARIAL_BOLD, 18),
        "value": font(ARIAL, 18),
        "copyright": font(ARIAL, 15),
    }


def fit(image: Image.Image, width: int) -> Image.Image:
    scale = width / image.width
    return image.resize(
        (width, max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )


def draw_tracking_text(
    canvas: Image.Image,
    xy: tuple[int, int],
    text: str,
    *,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    tracking: int,
) -> None:
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    for character in text:
        draw.text((x, y), character, font=text_font, fill=fill)
        left, _, right, _ = draw.textbbox((0, 0), character, font=text_font)
        x += right - left + tracking


def gradient_rule(width: int, height: int) -> Image.Image:
    colors = ((72, 213, 232), (112, 71, 255), (237, 60, 183))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    for x in range(width):
        position = x / max(1, width - 1)
        if position <= 0.52:
            amount = position / 0.52
            start, end = colors[0], colors[1]
        else:
            amount = (position - 0.52) / 0.48
            start, end = colors[1], colors[2]
        color = tuple(
            round(start[channel] + (end[channel] - start[channel]) * amount)
            for channel in range(3)
        )
        for y in range(height):
            pixels[x, y] = (*color, 255)

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=height // 2,
        fill=255,
    )
    image.putalpha(mask)
    return image


def render_cover(locale: str, metadata: dict[str, str]) -> Image.Image:
    fonts = locale_fonts(locale)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(canvas)

    lockup = fit(Image.open(LOCKUP).convert("RGBA"), 420)
    canvas.paste(lockup, (CONTENT_LEFT, 102), lockup)

    draw_tracking_text(
        canvas,
        (CONTENT_LEFT, 395),
        metadata["coverkicker"],
        text_font=fonts["kicker"],
        fill=PURPLE,
        tracking=1,
    )
    draw.text(
        (CONTENT_LEFT, 440),
        metadata["title"],
        font=fonts["title"],
        fill=INK,
    )
    rule = gradient_rule(455, 7)
    canvas.paste(rule, (CONTENT_LEFT, 512), rule)

    labels = (
        (metadata["authorlabel"], metadata["author"]),
        (metadata["versionlabel"], metadata["version"]),
        (metadata["editionlabel"], metadata["edition"]),
    )
    label_x = CONTENT_LEFT
    value_x = 250 if locale == "zh-CN" else 245
    for row, (label, value) in enumerate(labels):
        y = 565 + row * 42
        draw.text((label_x, y), label, font=fonts["label"], fill=INK)
        draw.text((value_x, y), value, font=fonts["value"], fill=MUTED)

    draw.text(
        (CONTENT_LEFT, 1185),
        metadata["covercopyright"],
        font=fonts["copyright"],
        fill=MUTED,
    )
    return canvas


def build_covers(locales: list[str]) -> dict[str, tuple[Path, str]]:
    if not LOCKUP.is_file():
        raise RuntimeError(f"Cover brand lockup is missing: {LOCKUP}")
    results: dict[str, tuple[Path, str]] = {}
    for locale in locales:
        config = MANUALS[locale]
        metadata = read_front_matter(config["source"])
        cover = render_cover(locale, metadata)
        output = Path(config["output"])
        cover.save(output, format="PNG", optimize=True, compress_level=9)
        results[locale] = (output, sha256(output))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the English and Simplified Chinese manual cover PNGs."
    )
    parser.add_argument("--locale", choices=["en", "zh-CN", "all"], default="all")
    args = parser.parse_args()
    locales = list(MANUALS) if args.locale == "all" else [args.locale]
    for locale, (path, digest) in build_covers(locales).items():
        print(f"{locale}: {path} | sha256={digest}")


if __name__ == "__main__":
    main()
