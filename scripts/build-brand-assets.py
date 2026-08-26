from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

REPO = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO / "brand" / "editions.json"
ICON_DIR = REPO / "brand" / "icons"
WEBSITE_FAVICON_PATH = ICON_DIR / "website-favicon-64.png"
DEFAULT_DERIVATIVE_ROOT = REPO / "desktop" / "src-tauri" / "gen" / "brand"
DEFAULT_FAVICON_PATH = REPO / "frontend" / "public" / "drone-favicon.png"
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
        raise BrandAssetError("edition brand contract identity drifted")
    return payload


def validate_png(path: Path, descriptor: dict[str, object]) -> Image.Image:
    if not path.is_file() or not path.resolve().is_relative_to(REPO.resolve()):
        raise BrandAssetError(
            f"canonical brand asset is missing or escaped the repository: {path}"
        )
    if sha256(path) != descriptor["sha256"]:
        raise BrandAssetError(
            f"canonical brand asset hash drifted: {path.relative_to(REPO)}"
        )
    with Image.open(path) as source:
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

    actual_paths = {
        path.resolve()
        for path in ICON_DIR.glob("*.png")
        if path.is_file() and path.resolve() != WEBSITE_FAVICON_PATH.resolve()
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
    favicon = validate_png(
        WEBSITE_FAVICON_PATH,
        {
            "sha256": "39f1c9e1bec804cb5834b12514408c9673b3a954d5c75544a5f92802387f2ea7",
            "width": 64,
            "height": 64,
        },
    )
    if favicon.size != (64, 64):
        raise BrandAssetError("approved website favicon dimensions drifted")

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

        prefix = alpha.crop((0, 0, wordmark_end + 1, image.height))
        if reference_prefix is None:
            reference_prefix = prefix
        elif (
            prefix.size != reference_prefix.size
            or ImageChops.difference(prefix, reference_prefix).getbbox()
        ):
            raise BrandAssetError(
                f"DroneDream wordmark letters changed size or position: {edition_id}"
            )

        # The first 249 columns contain the bat mark. Compare visible letter
        # heights, not the full lockup prefix, so the mark cannot distort the
        # typography measurement.
        wordmark_bbox = alpha.crop(
            (249, 0, wordmark_end + 1, image.height)
        ).getbbox()
        label_bbox = alpha.crop(
            (label_start, 0, image.width, image.height)
        ).getbbox()
        if wordmark_bbox is None or label_bbox is None:
            raise BrandAssetError(f"lockup visible text is missing: {edition_id}")
        label_ratios.append(
            (label_bbox[3] - label_bbox[1])
            / (wordmark_bbox[3] - wordmark_bbox[1])
        )

    if max(label_ratios) - min(label_ratios) > 0.005:
        raise BrandAssetError("edition label font heights are not consistent")
    if not all(1.0 <= ratio <= 1.03 for ratio in label_ratios):
        raise BrandAssetError(
            "edition labels and DroneDream letters must remain the same visible height"
        )
    return marks


def generate_derivatives(
    marks: dict[str, Image.Image],
    edition_ids: tuple[str, ...],
    derivative_root: Path,
    favicon_path: Path,
) -> list[Path]:
    outputs: list[Path] = []
    for edition_id in edition_ids:
        windows_dir = derivative_root / edition_id / "windows"
        windows_dir.mkdir(parents=True, exist_ok=True)
        source = marks[edition_id]
        for size, name in (
            (32, "32x32.png"),
            (128, "128x128.png"),
            (256, "128x128@2x.png"),
        ):
            output = windows_dir / name
            source.resize((size, size), Image.Resampling.LANCZOS).save(
                output, format="PNG"
            )
            outputs.append(output)
        ico_path = windows_dir / "icon.ico"
        source.save(
            ico_path,
            format="ICO",
            sizes=[(size, size) for size in ICO_SIZES],
        )
        outputs.append(ico_path)

    favicon_path.parent.mkdir(parents=True, exist_ok=True)
    favicon_path.write_bytes(WEBSITE_FAVICON_PATH.read_bytes())
    outputs.append(favicon_path)
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
