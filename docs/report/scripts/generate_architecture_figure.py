from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 2640
HEIGHT = 1034
TOP_Y = 157
TOP_HEIGHT = 220
BOTTOM_Y = 589
BOTTOM_HEIGHT = 201
BOX_WIDTH = 352
TOP_X = [66, 488, 910, 1331, 1753, 2174]
BOTTOM_X = [910, 1331, 1753]
VIOLET = "#5531c5"
ARROW_GRAY = "#786d82"
TOP_COLORS = [
    "#6848f2",
    "#6848f2",
    "#bf38dd",
    "#bf38dd",
    "#eb4292",
    "#eb4292",
]
BOTTOM_COLOR = "#603bc2"
FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
)


def font_path() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No supported bold font was found.")


def fitted_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    maximum_size: int,
    maximum_width: int,
    maximum_height: int,
) -> ImageFont.FreeTypeFont:
    path = font_path()
    for size in range(maximum_size, 23, -1):
        font = ImageFont.truetype(str(path), size=size)
        bounds = draw.multiline_textbbox(
            (0, 0),
            text,
            font=font,
            spacing=2,
            align="center",
        )
        if (
            bounds[2] - bounds[0] <= maximum_width
            and bounds[3] - bounds[1] <= maximum_height
        ):
            return font
    raise ValueError(f"Text does not fit its box: {text!r}")


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    maximum_size: int = 51,
) -> None:
    left, top, right, bottom = box
    font = fitted_font(
        draw,
        text,
        maximum_size=maximum_size,
        maximum_width=(right - left) - 36,
        maximum_height=(bottom - top) - 30,
    )
    bounds = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=2,
        align="center",
    )
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    x = left + (right - left - text_width) / 2 - bounds[0]
    y = top + (bottom - top - text_height) / 2 - bounds[1]
    draw.multiline_text(
        (x, y),
        text,
        fill="white",
        font=font,
        spacing=2,
        align="center",
    )


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str,
    width: int = 7,
    both_ends: bool = False,
) -> None:
    draw.line((start, end), fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    if x1 == x2:
        direction = 1 if y2 > y1 else -1
        tip = (x2, y2)
        draw.line(
            (tip, (x2 - 10, y2 - direction * 17)),
            fill=color,
            width=width,
        )
        draw.line(
            (tip, (x2 + 10, y2 - direction * 17)),
            fill=color,
            width=width,
        )
        if both_ends:
            tip = (x1, y1)
            draw.line(
                (tip, (x1 - 10, y1 + direction * 17)),
                fill=color,
                width=width,
            )
            draw.line(
                (tip, (x1 + 10, y1 + direction * 17)),
                fill=color,
                width=width,
            )
    else:
        direction = 1 if x2 > x1 else -1
        tip = (x2, y2)
        draw.line(
            (tip, (x2 - direction * 17, y2 - 10)),
            fill=color,
            width=width,
        )
        draw.line(
            (tip, (x2 - direction * 17, y2 + 10)),
            fill=color,
            width=width,
        )


def build(output: Path) -> None:
    image = Image.new("RGBA", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)

    top_labels = (
        "Task +\nScenario",
        "AURORA\nCompiler",
        "Eligibility +\nTool Router",
        "Optimizer\nPortfolio",
        "PX4 / Gazebo\nExecution",
        "Evidence\nVerifier",
    )
    for x, color, label in zip(TOP_X, TOP_COLORS, top_labels, strict=True):
        box = (x, TOP_Y, x + BOX_WIDTH, TOP_Y + TOP_HEIGHT)
        draw.rectangle(box, fill=color, outline=color, width=4)
        draw_centered_text(draw, box, label)

    bottom_labels = (
        "Failure\nTaxonomy",
        "Decision +\nOutcome Memory",
        "Freeze +\nFinal Gate",
    )
    for x, label in zip(BOTTOM_X, bottom_labels, strict=True):
        box = (x, BOTTOM_Y, x + BOX_WIDTH, BOTTOM_Y + BOTTOM_HEIGHT)
        draw.rectangle(
            box,
            fill=BOTTOM_COLOR,
            outline=VIOLET,
            width=4,
        )
        draw_centered_text(draw, box, label, maximum_size=49)

    top_center_y = TOP_Y + TOP_HEIGHT // 2
    for index in range(len(TOP_X) - 1):
        arrow(
            draw,
            (TOP_X[index] + BOX_WIDTH + 10, top_center_y),
            (TOP_X[index + 1] - 14, top_center_y),
            VIOLET,
        )

    bottom_center_y = BOTTOM_Y + BOTTOM_HEIGHT // 2
    for index in range(len(BOTTOM_X) - 1):
        arrow(
            draw,
            (BOTTOM_X[index] + BOX_WIDTH + 10, bottom_center_y),
            (BOTTOM_X[index + 1] - 14, bottom_center_y),
            VIOLET,
        )

    for x in (TOP_X[2], TOP_X[3], TOP_X[4]):
        center_x = x + BOX_WIDTH // 2
        arrow(
            draw,
            (center_x, TOP_Y + TOP_HEIGHT + 16),
            (center_x, BOTTOM_Y - 16),
            ARROW_GRAY,
            width=6,
            both_ends=True,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=False, compress_level=9)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.output)


if __name__ == "__main__":
    main()
