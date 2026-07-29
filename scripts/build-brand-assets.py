from __future__ import annotations

import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "docs" / "assets" / "drone-dream-logo-source.png"
DOCS_ASSETS = REPO / "docs" / "assets"
BRAND_ASSETS = DOCS_ASSETS / "brand"
FRONTEND_ASSETS = REPO / "frontend" / "src" / "assets"
FRONTEND_PUBLIC = REPO / "frontend" / "public"
TAURI_SOURCE = REPO / "desktop" / "src-tauri" / "app-icon.png"
SPACE_GROTESK_WOFF2 = (
    REPO
    / "frontend"
    / "node_modules"
    / "@fontsource-variable"
    / "space-grotesk"
    / "files"
    / "space-grotesk-latin-wght-normal.woff2"
)

BRAND_VIOLET = "#684BFF"
BRAND_LAVENDER = "#9B72FF"
BRAND_MAGENTA = "#F166D8"
BRAND_WHITE = "#FFFFFF"
BRAND_INK = "#171225"


def require_inputs() -> None:
    missing = [path for path in (SOURCE, SPACE_GROTESK_WOFF2) if not path.is_file()]
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Required brand inputs are missing:\n{joined}")


def crop_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"{SOURCE} contains no visible pixels.")
    return rgba.crop(bbox)


def square_mark(source: Image.Image, size: int, padding_ratio: float) -> Image.Image:
    visible = crop_alpha(source)
    content_extent = round(size * (1 - 2 * padding_ratio))
    scale = min(content_extent / visible.width, content_extent / visible.height)
    resized = visible.resize(
        (max(1, round(visible.width * scale)), max(1, round(visible.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
    )
    return canvas


def convert_space_grotesk(output: Path) -> Path:
    font = TTFont(SPACE_GROTESK_WOFF2)
    font.flavor = None
    font.save(output)
    return output


def font_at(path: Path, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size=size)
    if hasattr(font, "set_variation_by_axes"):
        font.set_variation_by_axes([weight])
    return font


def measured_letters(
    word: str,
    font: ImageFont.FreeTypeFont,
    tracking: int,
) -> tuple[list[tuple[str, int, int]], int]:
    letters: list[tuple[str, int, int]] = []
    cursor = 0
    for character in word:
        left, _, right, _ = font.getbbox(character)
        width = max(1, right - left)
        letters.append((character, cursor - left, width))
        cursor += width + tracking
    return letters, max(1, cursor - tracking)


def horizontal_gradient(
    size: tuple[int, int],
    colors: tuple[str, str, str] = (
        BRAND_VIOLET,
        BRAND_LAVENDER,
        BRAND_MAGENTA,
    ),
) -> Image.Image:
    anchors = [
        tuple(int(color.removeprefix("#")[index : index + 2], 16) for index in (0, 2, 4))
        for color in colors
    ]
    width, height = size
    row = Image.new("RGB", (width, 1))
    pixels = row.load()
    for x in range(width):
        position = x / max(1, width - 1)
        if position <= 0.52:
            local = position / 0.52
            start, end = anchors[0], anchors[1]
        else:
            local = (position - 0.52) / 0.48
            start, end = anchors[1], anchors[2]
        pixels[x, 0] = tuple(
            round(channel_start + (channel_end - channel_start) * local)
            for channel_start, channel_end in zip(start, end, strict=True)
        )
    return row.resize((width, height))


def wordmark(
    font_path: Path,
    *,
    word: str,
    weight: int,
    size: int,
    tracking: int,
    notch: bool = True,
) -> Image.Image:
    font = font_at(font_path, size, weight)
    letters, width = measured_letters(word, font, tracking)
    ascent, descent = font.getmetrics()
    height = ascent + descent + 28
    mask = Image.new("L", (width + 28, height), 0)
    draw = ImageDraw.Draw(mask)
    capital_d_origins: list[tuple[int, int]] = []
    for character, letter_x, letter_width in letters:
        draw.text((letter_x + 14, 8), character, fill=255, font=font)
        if character == "D":
            capital_d_origins.append((letter_x + 14, letter_width))

    if notch:
        for letter_x, letter_width in capital_d_origins:
            cut_y = 8 + round(size * 0.18)
            cut_x = letter_x + round(letter_width * 0.61)
            draw.polygon(
                (
                    (cut_x, cut_y),
                    (cut_x + round(size * 0.14), cut_y),
                    (cut_x + round(size * 0.075), cut_y + round(size * 0.082)),
                ),
                fill=0,
            )

    fill = horizontal_gradient(mask.size).convert("RGBA")
    fill.putalpha(mask)
    return crop_alpha(fill)


def fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    visible = crop_alpha(image)
    scale = min(max_width / visible.width, max_height / visible.height)
    return visible.resize(
        (max(1, round(visible.width * scale)), max(1, round(visible.height * scale))),
        Image.Resampling.LANCZOS,
    )


def lockup(mark: Image.Image, text: Image.Image) -> Image.Image:
    # Keep the animal mark only slightly taller than the wordmark. This mirrors
    # the compact, optically aligned relationship used by strong horizontal
    # brand lockups instead of making the symbol feel like a separate poster.
    mark_fit = fit(mark, 220, 220)
    text_fit = fit(text, 1500, 210)
    gap = 46
    width = mark_fit.width + gap + text_fit.width
    height = max(mark_fit.height, text_fit.height)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    # The bat's upper wing carries more visual mass, so lowering it by two
    # pixels produces a truer optical centre against the cap/x-height.
    mark_y = min(height - mark_fit.height, (height - mark_fit.height) // 2 + 2)
    canvas.alpha_composite(mark_fit, (0, mark_y))
    canvas.alpha_composite(
        text_fit,
        (mark_fit.width + gap, (height - text_fit.height) // 2),
    )
    return canvas


def white_background_logo(source: Image.Image) -> Image.Image:
    horizontal_padding = 72
    vertical_padding = 48
    canvas = Image.new(
        "RGBA",
        (
            source.width + horizontal_padding * 2,
            source.height + vertical_padding * 2,
        ),
        BRAND_WHITE,
    )
    canvas.alpha_composite(source, (horizontal_padding, vertical_padding))
    return canvas


def preview(
    primary_lockup: Image.Image,
    compact_lockup: Image.Image,
) -> Image.Image:
    width, height = 2400, 1200
    canvas = Image.new("RGBA", (width, height), BRAND_WHITE)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((width // 2, 0, width, height), fill=BRAND_INK)
    draw.line((0, height // 2, width, height // 2), fill="#E9E5EE", width=2)

    for row, source in enumerate((primary_lockup, compact_lockup)):
        item = fit(source, 980, 360)
        cell_y = row * (height // 2)
        x = (width // 2 - item.width) // 2
        y = cell_y + (height // 2 - item.height) // 2
        canvas.alpha_composite(item, (x, y))

        light_variant = item.copy()
        alpha = light_variant.getchannel("A")
        white_fill = Image.new("RGBA", item.size, BRAND_WHITE)
        white_fill.putalpha(alpha)
        canvas.alpha_composite(
            white_fill,
            (width // 2 + x, y),
        )

    return canvas


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def build() -> None:
    require_inputs()
    source = Image.open(SOURCE).convert("RGBA")
    mark = square_mark(source, 1024, 0.09)
    favicon = square_mark(source, 64, 0.025)

    save_png(mark, DOCS_ASSETS / "drone-dream-icon.png")
    save_png(mark, FRONTEND_ASSETS / "drone-dream-mark.png")
    save_png(favicon, FRONTEND_PUBLIC / "drone-favicon.png")
    save_png(mark, TAURI_SOURCE)

    with tempfile.TemporaryDirectory(prefix="dronedream-brand-") as temp:
        font_path = convert_space_grotesk(Path(temp) / "space-grotesk-variable.ttf")
        primary = wordmark(
            font_path,
            word="DroneDream",
            weight=620,
            size=250,
            tracking=-3,
        )
        compact = wordmark(
            font_path,
            word="DRONEDREAM",
            weight=690,
            size=218,
            tracking=8,
        )

    primary_lockup = lockup(mark, primary)
    compact_lockup = lockup(mark, compact)
    save_png(primary, BRAND_ASSETS / "drone-dream-wordmark-primary.png")
    save_png(compact, BRAND_ASSETS / "drone-dream-wordmark-compact.png")
    save_png(primary_lockup, BRAND_ASSETS / "drone-dream-lockup-primary.png")
    save_png(compact_lockup, BRAND_ASSETS / "drone-dream-lockup-compact.png")
    save_png(primary_lockup, FRONTEND_ASSETS / "drone-dream-lockup-primary.png")
    save_png(compact_lockup, FRONTEND_ASSETS / "drone-dream-lockup-compact.png")
    save_png(
        white_background_logo(primary_lockup),
        BRAND_ASSETS / "drone-dream-logo-horizontal-white.png",
    )
    save_png(
        preview(primary_lockup, compact_lockup),
        BRAND_ASSETS / "drone-dream-brand-preview.png",
    )


if __name__ == "__main__":
    build()
