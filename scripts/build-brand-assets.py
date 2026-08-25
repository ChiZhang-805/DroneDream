from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO / "brand" / "brand-editions.v1.json"
SCHEMA_PATH = REPO / "brand" / "brand-editions.schema.json"
SOURCE_PATH = REPO / "brand" / "source" / "drone-dream-mark-master.png"
FONT_PATH = REPO / "brand" / "source" / "space-grotesk-latin-wght-normal.woff2"
FONT_LICENSE_PATH = REPO / "brand" / "source" / "Space-Grotesk-OFL-1.1.txt"
REQUIREMENTS_PATH = REPO / "brand" / "requirements.lock.txt"
MANIFEST_PATH = REPO / "brand" / "generated" / "brand-assets.v1.json"
VISUAL_RECEIPT_PATH = REPO / "brand" / "generated" / "brand-visual-receipt.v1.json"
APPROVED_PREVIEW_PATH = (
    REPO
    / "brand"
    / "source"
    / "approved"
    / "edition-brand-centered-separator-approved-preview.png"
)
APPROVED_WEBSITE_FAVICON_PATH = (
    REPO / "brand" / "source" / "approved" / "website-favicon-64.png"
)

EDITION_IDS = ("universal", "sim", "lab", "field", "autonomy")
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


class BrandAssetError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract() -> dict[str, object]:
    try:
        payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BrandAssetError("brand/editions.json could not be read") from exc
    if (
        payload.get("schemaVersion") != 1
        or payload.get("kind") != "dronedream-edition-brand-system"
        or payload.get("separator") != "·"
        or payload.get("safety")
        != {"presentationOnly": True, "grantsHardwareAuthority": False}
        or tuple(payload.get("editions", {})) != EDITION_IDS
    ):
        raise BrandBuildError("brand contract identity or safety boundary drifted")
    for edition_id, expected_label in zip(
        EDITION_IDS,
        (None, "SIM", "LAB", "FIELD", "AUTONOMY"),
        strict=True,
    ):
        edition = contract["editions"][edition_id]
        if edition.get("editionLabel") != expected_label:
            raise BrandBuildError(f"brand edition label drifted: {edition_id}")
        colors = edition.get("gradientStops")
        if not isinstance(colors, list) or len(colors) != 3:
            raise BrandBuildError(f"brand gradient is invalid: {edition_id}")
    approved_assets = contract.get("approvedEditionAssets")
    if not isinstance(approved_assets, dict) or tuple(approved_assets) != EDITION_IDS[1:]:
        raise BrandBuildError("approved edition asset inventory drifted")
    approval = contract.get("approval", {})
    if (
        approval.get("largeLabelLockupsAreCanonicalSources") is not True
        or approval.get("largeLabelReviewPreviewPath")
        != APPROVED_PREVIEW_PATH.relative_to(REPO).as_posix()
        or approval.get("largeLabelReviewPreviewSha256")
        != "77d5326be1155528d9585a56de99c80364640ed7f4d488222c7f581ef70da02e"
        or approval.get("largeLabelReviewStudySha256")
        != "9b3e9a274ef51393ffbf8ba3cf5d41224a0cafc9990deddeafcef1a92122353a"
        or approval.get("editionLabelHeightRatio") != 0.9
        or approval.get("preserveNaturalLabelWidth") is not True
        or approval.get("separatorCentering")
        != {"method": "equal-alpha-edge-gaps", "tolerancePx": 0}
    ):
        raise BrandBuildError("large-label approval identity drifted")
    if contract.get("websiteFavicon") != {
        "sourcePath": APPROVED_WEBSITE_FAVICON_PATH.relative_to(REPO).as_posix(),
        "sourceSha256": "39f1c9e1bec804cb5834b12514408c9673b3a954d5c75544a5f92802387f2ea7",
        "dimensions": {"width": 64, "height": 64},
        "canonicalOutputPath": "frontend/public/drone-favicon.png",
        "approvalBasis": "mainland-preview-approved-v1",
    }:
        raise BrandBuildError("approved website favicon identity drifted")
    return contract


def require_inputs() -> None:
    missing = [
        path
        for path in (
            CONTRACT_PATH,
            SCHEMA_PATH,
            SOURCE_PATH,
            FONT_PATH,
            FONT_LICENSE_PATH,
            REQUIREMENTS_PATH,
            APPROVED_PREVIEW_PATH,
            APPROVED_WEBSITE_FAVICON_PATH,
        )
        if not path.is_file()
    ]
    if missing:
        raise BrandBuildError(
            "required brand inputs are missing: "
            + ", ".join(path.relative_to(REPO).as_posix() for path in missing)
        )


def load_approved_edition_asset(
    contract: dict[str, Any],
    edition_id: str,
    path_key: str,
    hash_key: str,
    expected_size: tuple[int, int],
) -> tuple[Image.Image, bytes, Path]:
    descriptor = contract["approvedEditionAssets"][edition_id]
    path = REPO / descriptor[path_key]
    if not path.is_file() or not path.resolve().is_relative_to(REPO.resolve()):
        raise BrandBuildError(f"approved {edition_id} asset is missing or escaped the repository")
    payload = path.read_bytes()
    if sha256_bytes(payload) != descriptor[hash_key]:
        raise BrandBuildError(f"approved {edition_id} asset hash drifted: {path_key}")
    with Image.open(io.BytesIO(payload)) as source:
        if source.format != "PNG" or source.size != expected_size or source.mode != "RGBA":
            raise BrandBuildError(f"approved {edition_id} asset format drifted: {path_key}")
        image = source.copy()
    return image, payload, path


def validate_centered_separator(
    image: Image.Image,
    descriptor: dict[str, Any],
    edition_id: str,
    tolerance_px: int,
) -> None:
    geometry = descriptor.get("separatorGeometry")
    if not isinstance(geometry, dict):
        raise BrandBuildError(f"separator geometry is missing: {edition_id}")
    try:
        wordmark_end = int(geometry["wordmarkEndX"])
        separator_start = int(geometry["separatorStartX"])
        separator_end = int(geometry["separatorEndX"])
        label_start = int(geometry["editionLabelStartX"])
        declared_left_gap = int(geometry["leftGapPx"])
        declared_right_gap = int(geometry["rightGapPx"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BrandBuildError(f"separator geometry is invalid: {edition_id}") from exc

    if not (0 <= wordmark_end < separator_start <= separator_end < label_start < image.width):
        raise BrandBuildError(f"separator geometry escaped the lockup: {edition_id}")

    alpha = image.getchannel("A")

    def column_has_alpha(x: int) -> bool:
        return alpha.crop((x, 0, x + 1, image.height)).getbbox() is not None

    boundary_columns = (wordmark_end, separator_start, separator_end, label_start)
    if not all(column_has_alpha(x) for x in boundary_columns):
        raise BrandBuildError(f"separator alpha boundary drifted: {edition_id}")
    if any(column_has_alpha(x) for x in range(wordmark_end + 1, separator_start)):
        raise BrandBuildError(f"separator left gap is not transparent: {edition_id}")
    if any(column_has_alpha(x) for x in range(separator_end + 1, label_start)):
        raise BrandBuildError(f"separator right gap is not transparent: {edition_id}")

    left_gap = separator_start - wordmark_end - 1
    right_gap = label_start - separator_end - 1
    if (left_gap, right_gap) != (declared_left_gap, declared_right_gap):
        raise BrandBuildError(f"separator declared gap drifted: {edition_id}")
    if abs(left_gap - right_gap) > tolerance_px:
        raise BrandBuildError(f"separator is not centered: {edition_id}")


def parse_color(value: str) -> tuple[int, int, int]:
    if len(value) != 7 or not value.startswith("#"):
        raise BrandBuildError(f"invalid brand color: {value}")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def mix(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    return tuple(
        round(start + (end - start) * amount) for start, end in zip(left, right, strict=True)
    )


def palette_at(colors: tuple[str, str, str], amount: float) -> tuple[int, int, int]:
    anchors = tuple(parse_color(value) for value in colors)
    bounded = max(0.0, min(1.0, amount))
    if bounded <= 0.5:
        return mix(anchors[0], anchors[1], bounded * 2)
    return mix(anchors[1], anchors[2], (bounded - 0.5) * 2)


def crop_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise BrandBuildError("brand source contains no visible pixels")
    return rgba.crop(bbox)


def square_mark(source: Image.Image, size: int, padding_ratio: float) -> Image.Image:
    visible = crop_alpha(source)
    extent = round(size * (1 - 2 * padding_ratio))
    scale = min(extent / visible.width, extent / visible.height)
    resized = visible.resize(
        (max(1, round(visible.width * scale)), max(1, round(visible.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


def recolor_mark(image: Image.Image, colors: tuple[str, str, str]) -> Image.Image:
    source = image.convert("RGBA")
    output = Image.new("RGBA", source.size)
    source_pixels = source.load()
    output_pixels = output.load()
    width, height = source.size
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = source_pixels[x, y]
            if alpha == 0:
                continue
            _, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            if saturation < 0.14:
                output_pixels[x, y] = (red, green, blue, alpha)
                continue
            amount = 0.62 * (x / max(1, width - 1)) + 0.38 * (y / max(1, height - 1))
            color = palette_at(colors, amount)
            light_scale = 0.78 + 0.22 * value
            output_pixels[x, y] = (
                *(round(channel * light_scale) for channel in color),
                alpha,
            )
    return output


def horizontal_gradient(size: tuple[int, int], colors: tuple[str, str, str]) -> Image.Image:
    width, height = size
    row = Image.new("RGB", (width, 1))
    pixels = row.load()
    for x in range(width):
        pixels[x, 0] = palette_at(colors, x / max(1, width - 1))
    return row.resize((width, height)).convert("RGBA")


def convert_font(output: Path) -> Path:
    font = TTFont(FONT_PATH)
    font.flavor = None
    font.save(output, reorderTables=True)
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


def gradient_text(
    font_path: Path,
    *,
    word: str,
    colors: tuple[str, str, str],
    weight: int,
    size: int,
    tracking: int,
    notch: bool,
) -> Image.Image:
    font = font_at(font_path, size, weight)
    letters, width = measured_letters(word, font, tracking)
    ascent, descent = font.getmetrics()
    mask = Image.new("L", (width + 28, ascent + descent + 28), 0)
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
    fill = horizontal_gradient(mask.size, colors)
    fill.putalpha(mask)
    return crop_alpha(fill)


def fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    visible = crop_alpha(image)
    scale = min(max_width / visible.width, max_height / visible.height)
    return visible.resize(
        (max(1, round(visible.width * scale)), max(1, round(visible.height * scale))),
        Image.Resampling.LANCZOS,
    )


def lockup(
    mark: Image.Image,
    wordmark: Image.Image,
    suffix: Image.Image | None,
) -> Image.Image:
    mark_fit = fit(mark, 220, 220)
    text_fit = fit(wordmark, 1500, 210)
    suffix_fit = fit(suffix, 430, 112) if suffix is not None else None
    mark_gap = 46
    suffix_gap = 34 if suffix_fit is not None else 0
    width = mark_fit.width + mark_gap + text_fit.width
    if suffix_fit is not None:
        width += suffix_gap + suffix_fit.width
    height = max(mark_fit.height, text_fit.height, suffix_fit.height if suffix_fit else 0)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mark_y = min(height - mark_fit.height, (height - mark_fit.height) // 2 + 2)
    canvas.alpha_composite(mark_fit, (0, mark_y))
    text_x = mark_fit.width + mark_gap
    canvas.alpha_composite(text_fit, (text_x, (height - text_fit.height) // 2))
    if suffix_fit is not None:
        canvas.alpha_composite(
            suffix_fit,
            (text_x + text_fit.width + suffix_gap, (height - suffix_fit.height) // 2 + 2),
        )
    return crop_alpha(canvas)


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def ico_bytes(mark: Image.Image, sizes: list[int]) -> bytes:
    buffer = io.BytesIO()
    mark.convert("RGBA").save(
        buffer,
        format="ICO",
        sizes=[(size, size) for size in sizes],
    )
    return buffer.getvalue()


def preview_board(
    contract: dict[str, Any],
    lockups: dict[tuple[str, str], Image.Image],
    font_path: Path,
) -> Image.Image:
    width, height = 5200, 2035
    canvas = Image.new("RGBA", (width, height), "#EFF1F7")
    draw = ImageDraw.Draw(canvas)
    title_font = font_at(font_path, 74, 700)
    body_font = font_at(font_path, 34, 520)
    label_font = font_at(font_path, 30, 650)
    draw.text(
        (100, 58),
        "DRONEDREAM \u00b7 CANONICAL LARGE EDITION LABELS",
        font=title_font,
        fill="#171225",
    )
    draw.text(
        (104, 146),
        "Approved exact-byte lockups; edition labels use about 90% of the main wordmark height.",
        font=body_font,
        fill="#6B6676",
    )
    row_height = 330
    for index, edition_id in enumerate(EDITION_IDS):
        edition = contract["editions"][edition_id]
        top = 235 + index * 355
        draw.rounded_rectangle((70, top, 5130, top + row_height), radius=34, fill="#FFFFFF")
        draw.text((105, top + 24), edition["productName"], font=label_font, fill="#4E4855")
        light = (260, top + 55, 2470, top + 295)
        dark = (2530, top + 55, 5040, top + 295)
        draw.rounded_rectangle(light, radius=28, fill=edition["lightSurface"])
        draw.rounded_rectangle(dark, radius=28, fill=edition["darkSurface"])
        item = fit(lockups[(edition_id, "primary")], 2200, 158)
        for bounds in (light, dark):
            left, upper, right, lower = bounds
            canvas.alpha_composite(
                item,
                (
                    left + (right - left - item.width) // 2,
                    upper + (lower - upper - item.height) // 2,
                ),
            )
    return canvas.convert("RGB")


def generated_ts(contract: dict[str, Any]) -> bytes:
    tokens = json.dumps(contract["editions"], ensure_ascii=False, indent=2)
    edition_ids = json.dumps(list(EDITION_IDS), ensure_ascii=False)
    return (
        "// Generated by scripts/build-brand-assets.py. Do not edit.\n"
        f"export const BRAND_EDITION_IDS = {edition_ids} as const;\n"
        "export type BrandEditionId = (typeof BRAND_EDITION_IDS)[number];\n"
        f"export const EDITION_BRAND_TOKENS = {tokens} as const;\n"
        "export const BRAND_PRESENTATION_ONLY = true as const;\n"
        "export const BRAND_GRANTS_HARDWARE_AUTHORITY = false as const;\n"
    ).encode()


def generated_css(contract: dict[str, Any]) -> bytes:
    blocks: list[str] = ["/* Generated by scripts/build-brand-assets.py. Do not edit. */"]
    for edition_id in EDITION_IDS:
        edition = contract["editions"][edition_id]
        selector = (
            ':root, [data-brand-edition="universal"]'
            if edition_id == "universal"
            else f'[data-brand-edition="{edition_id}"]'
        )
        first, middle, last = edition["gradientStops"]
        blocks.append(
            f"{selector} {{\n"
            f"  --dd-brand-start: {first};\n"
            f"  --dd-brand-middle: {middle};\n"
            f"  --dd-brand-end: {last};\n"
            f"  --dd-brand-light-surface: {edition['lightSurface']};\n"
            f"  --dd-brand-dark-surface: {edition['darkSurface']};\n"
            f"  --dd-brand-gradient: linear-gradient(110deg, {first}, {middle} 52%, {last});\n"
            "}"
        )
    return ("\n\n".join(blocks) + "\n").encode("utf-8")


def add_image(outputs: dict[Path, bytes], path: str, image: Image.Image) -> bytes:
    payload = png_bytes(image)
    outputs[REPO / path] = payload
    return payload


def build_outputs() -> dict[Path, bytes]:
    require_inputs()
    contract = load_contract()
    website_favicon = contract["websiteFavicon"]
    website_favicon_payload = APPROVED_WEBSITE_FAVICON_PATH.read_bytes()
    if sha256_bytes(website_favicon_payload) != website_favicon["sourceSha256"]:
        raise BrandBuildError("approved website favicon hash drifted")
    with Image.open(io.BytesIO(website_favicon_payload)) as favicon_source:
        expected_favicon = website_favicon["dimensions"]
        if (
            favicon_source.format != "PNG"
            or favicon_source.mode != "RGBA"
            or favicon_source.size
            != (expected_favicon["width"], expected_favicon["height"])
        ):
            raise BrandBuildError("approved website favicon format drifted")
    approved_preview = APPROVED_PREVIEW_PATH.read_bytes()
    if sha256_bytes(approved_preview) != contract["approval"]["largeLabelReviewPreviewSha256"]:
        raise BrandBuildError("approved large-label review preview hash drifted")
    with Image.open(io.BytesIO(approved_preview)) as preview_source:
        expected_preview = contract["approval"]["largeLabelReviewPreviewDimensions"]
        if (
            source.format != "PNG"
            or source.mode != "RGBA"
            or source.size != (descriptor["width"], descriptor["height"])
        ):
            raise BrandAssetError(
                f"canonical brand asset format drifted: {path.relative_to(REPO)}"
            )
        image = source.copy()
    alpha = image.getchannel("A")
    minimum, maximum = alpha.getextrema()
    if minimum != 0 or maximum != 255 or alpha.getbbox() is None:
        raise BrandAssetError(
            f"canonical brand asset must have a transparent background: {path.relative_to(REPO)}"
        )
    return image


def validate_canonical_assets(
    contract: dict[str, object],
) -> dict[str, Image.Image]:
    editions = contract["editions"]
    expected_paths: set[Path] = set()
    marks: dict[str, Image.Image] = {}
    lockups: dict[str, Image.Image] = {}
    for edition_id in EDITION_IDS:
        edition = editions[edition_id]
        for kind in ("mark", "lockup"):
            descriptor = edition[kind]
            path = REPO / descriptor["path"]
            expected_paths.add(path.resolve())
            image = validate_png(path, descriptor)
            if kind == "mark":
                marks[edition_id] = image
            else:
                lockups[edition_id] = image

            marks[edition_id] = mark
            lockups[(edition_id, "primary")] = primary_lockup
            lockups[(edition_id, "compact")] = compact_lockup

            base = f"brand/generated/{edition_id}"
            outputs[REPO / f"{base}/mark-1024.png"] = mark_payload
            add_image(
                outputs, f"{base}/mark-512.png", mark.resize((512, 512), Image.Resampling.LANCZOS)
            )
            add_image(
                outputs, f"{base}/mark-256.png", mark.resize((256, 256), Image.Resampling.LANCZOS)
            )
            add_image(outputs, f"{base}/favicon-64.png", favicon)
            outputs[REPO / f"{base}/lockup-primary.png"] = primary_lockup_payload
            outputs[REPO / f"{base}/lockup-compact.png"] = compact_lockup_payload
            windows = f"{base}/windows"
            add_image(
                outputs, f"{windows}/32x32.png", mark.resize((32, 32), Image.Resampling.LANCZOS)
            )
            add_image(
                outputs, f"{windows}/128x128.png", mark.resize((128, 128), Image.Resampling.LANCZOS)
            )
            add_image(
                outputs,
                f"{windows}/128x128@2x.png",
                mark.resize((256, 256), Image.Resampling.LANCZOS),
            )
            outputs[REPO / f"{windows}/icon.ico"] = ico_bytes(
                mark,
                contract["artifactContract"]["windowsIcoFrameSizesPx"],
            )

            outputs[REPO / f"frontend/src/assets/brand/{edition_id}-mark.png"] = mark_payload
            outputs[REPO / f"frontend/src/assets/brand/{edition_id}-lockup-primary.png"] = (
                primary_lockup_payload
            )
            outputs[REPO / f"frontend/src/assets/brand/{edition_id}-lockup-compact.png"] = (
                compact_lockup_payload
            )

        preview = preview_board(contract, lockups, font_path)
        preview_bytes = add_image(outputs, "brand/generated/edition-brand-preview.png", preview)

    universal_mark = marks["universal"]
    universal_primary = lockups[("universal", "primary")]
    universal_compact = lockups[("universal", "compact")]
    outputs[REPO / website_favicon["canonicalOutputPath"]] = website_favicon_payload
    for path, image in (
        ("docs/assets/drone-dream-icon.png", universal_mark),
        ("frontend/src/assets/drone-dream-mark.png", universal_mark),
        ("desktop/src-tauri/app-icon.png", universal_mark),
        ("docs/assets/brand/drone-dream-lockup-primary.png", universal_primary),
        ("docs/assets/brand/drone-dream-lockup-compact.png", universal_compact),
        ("frontend/src/assets/drone-dream-lockup-primary.png", universal_primary),
        ("frontend/src/assets/drone-dream-lockup-compact.png", universal_compact),
    ):
        add_image(outputs, path, image)
    for path, size in (
        ("desktop/src-tauri/icons/32x32.png", 32),
        ("desktop/src-tauri/icons/128x128.png", 128),
        ("desktop/src-tauri/icons/128x128@2x.png", 256),
    ):
        add_image(outputs, path, universal_mark.resize((size, size), Image.Resampling.LANCZOS))
    outputs[REPO / "desktop/src-tauri/icons/icon.ico"] = outputs[
        REPO / "brand/generated/universal/windows/icon.ico"
    ]

    outputs[REPO / "frontend/src/brand/edition-brand.generated.ts"] = generated_ts(contract)
    outputs[REPO / "frontend/src/brand/edition-brand.generated.css"] = generated_css(contract)

    visual_receipt = {
        "schemaVersion": 1,
        "kind": "dronedream-brand-visual-receipt",
        "brandVersion": contract["brandVersion"],
        "previewPath": "brand/generated/edition-brand-preview.png",
        "previewBytes": len(preview_bytes),
        "previewSha256": sha256_bytes(preview_bytes),
        "previewDimensions": {"width": 5200, "height": 2035},
        "approvedReviewPreviewPath": contract["approval"]["largeLabelReviewPreviewPath"],
        "approvedReviewPreviewSha256": contract["approval"][
            "largeLabelReviewPreviewSha256"
        ],
        "approvedReviewStudySha256": contract["approval"]["largeLabelReviewStudySha256"],
        "verifiedEditions": list(EDITION_IDS),
        "verifiedSurfaces": ["light", "dark"],
        "singleLineCenteredDotLockups": True,
        "editionLabelHeightRatio": contract["approval"]["editionLabelHeightRatio"],
        "naturalEditionLabelWidths": contract["approval"]["preserveNaturalLabelWidth"],
        "separatorCentering": contract["approval"]["separatorCentering"],
        "sharedGeometry": True,
        "approvedExactByteEditions": list(EDITION_IDS[1:]),
        "presentationOnly": True,
        "releaseAsset": False,
    }
    if actual_paths != expected_paths or len(actual_paths) != 10:
        unexpected = sorted(
            str(path.relative_to(REPO)) for path in actual_paths - expected_paths
        )
        missing = sorted(
            str(path.relative_to(REPO)) for path in expected_paths - actual_paths
        )
        raise BrandAssetError(
            "canonical icon inventory must equal ten files; "
            f"unexpected={unexpected}, missing={missing}"
        )

    reference_prefix: Image.Image | None = None
    label_ratios: list[float] = []
    for edition_id in EDITION_IDS[1:]:
        edition = editions[edition_id]
        image = lockups[edition_id]
        alpha = image.getchannel("A")
        wordmark_end = int(edition["wordmarkEndX"])
        separator_start = int(edition["separatorStartX"])
        separator_end = int(edition["separatorEndX"])
        label_start = int(edition["editionLabelStartX"])
        if not (
            wordmark_end
            < separator_start
            <= separator_end
            < label_start
            < image.width
        ):
            raise BrandAssetError(f"lockup separator geometry drifted: {edition_id}")
        left_gap = alpha.crop(
            (wordmark_end + 1, 0, separator_start, image.height)
        )
        right_gap = alpha.crop(
            (separator_end + 1, 0, label_start, image.height)
        )
        if left_gap.getbbox() is not None or right_gap.getbbox() is not None:
            raise BrandAssetError(
                f"lockup separator gaps are not transparent: {edition_id}"
            )
        if (
            separator_start - wordmark_end - 1
            != label_start - separator_end - 1
        ):
            raise BrandAssetError(f"lockup separator is not centered: {edition_id}")

    manifest = {
        "schemaVersion": 1,
        "kind": "dronedream-canonical-brand-assets",
        "brandVersion": contract["brandVersion"],
        "contractPath": CONTRACT_PATH.relative_to(REPO).as_posix(),
        "contractSha256": sha256_bytes(CONTRACT_PATH.read_bytes()),
        "schemaSha256": sha256_bytes(SCHEMA_PATH.read_bytes()),
        "generatorPath": Path(__file__).resolve().relative_to(REPO).as_posix(),
        "generatorSha256": sha256_bytes(Path(__file__).read_bytes()),
        "sourceGeometry": {
            "path": SOURCE_PATH.relative_to(REPO).as_posix(),
            "bytes": SOURCE_PATH.stat().st_size,
            "sha256": sha256_bytes(SOURCE_PATH.read_bytes()),
        },
        "websiteFavicon": {
            "sourcePath": website_favicon["sourcePath"],
            "bytes": len(website_favicon_payload),
            "sha256": website_favicon["sourceSha256"],
            "dimensions": website_favicon["dimensions"],
            "canonicalOutputPath": website_favicon["canonicalOutputPath"],
            "approvalBasis": website_favicon["approvalBasis"],
        },
        "font": {
            "path": FONT_PATH.relative_to(REPO).as_posix(),
            "sha256": sha256_bytes(FONT_PATH.read_bytes()),
            "licensePath": FONT_LICENSE_PATH.relative_to(REPO).as_posix(),
            "licenseSha256": sha256_bytes(FONT_LICENSE_PATH.read_bytes()),
        },
        "lockedRequirements": {
            "path": REQUIREMENTS_PATH.relative_to(REPO).as_posix(),
            "sha256": sha256_bytes(REQUIREMENTS_PATH.read_bytes()),
        },
        "toolchain": {
            "python": platform.python_version(),
            "pillow": pillow_version,
            "fonttools": fonttools_version,
            "zlib": zlib.ZLIB_VERSION,
        },
        "approvedEditionAssets": approved_asset_records,
        "approvalHandoffSha256": contract["approval"]["handoffSha256"],
        "largeLabelApproval": {
            "canonicalSources": contract["approval"]["largeLabelLockupsAreCanonicalSources"],
            "reviewPreviewPath": contract["approval"]["largeLabelReviewPreviewPath"],
            "reviewPreviewSha256": contract["approval"]["largeLabelReviewPreviewSha256"],
            "reviewStudySha256": contract["approval"]["largeLabelReviewStudySha256"],
            "editionLabelHeightRatio": contract["approval"]["editionLabelHeightRatio"],
            "preserveNaturalLabelWidth": contract["approval"]["preserveNaturalLabelWidth"],
            "separatorCentering": contract["approval"]["separatorCentering"],
        },
        "conceptAssetsAreReleaseAssets": False,
        "universalIsCanonical": True,
        "presentationOnly": True,
        "grantsHardwareAuthority": False,
        "artifactContract": contract["artifactContract"],
        "assets": asset_records,
    }
    outputs[MANIFEST_PATH] = canonical_json(manifest)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--edition", choices=("all",) + EDITION_IDS, default="all"
    )
    parser.add_argument(
        "--derivative-root", type=Path, default=DEFAULT_DERIVATIVE_ROOT
    )
    parser.add_argument(
        "--favicon-path", type=Path, default=DEFAULT_FAVICON_PATH
    )
    args = parser.parse_args()

    contract = load_contract()
    marks = validate_canonical_assets(contract)
    if args.check:
        print(
            json.dumps(
                {"status": "verified", "canonicalIconCount": 10},
                separators=(",", ":"),
            )
        )
        return 0

    edition_ids = EDITION_IDS if args.edition == "all" else (args.edition,)
    outputs = generate_derivatives(
        marks,
        edition_ids,
        args.derivative_root.resolve(),
        args.favicon_path.resolve(),
    )
    print(
        json.dumps(
            {
                "status": "generated",
                "editionIds": edition_ids,
                "derivativeCount": len(outputs),
                "outputs": [str(path) for path in outputs],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
