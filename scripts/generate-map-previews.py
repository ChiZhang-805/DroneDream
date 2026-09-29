"""Render deterministic oblique catalog previews from the packaged Gazebo worlds."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw


@dataclass(frozen=True)
class Box:
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    yaw: float
    color: tuple[int, int, int]


CATALOG = {
    "school-map": ("school-map.ddpkg", "normalized/map/gazebo/world.sdf"),
    "airport-terminal": ("pairs/open-rmf-airport-terminal/map.ddpkg", "normalized/rmf/generated/world.sdf"),
    "open-test-arena": ("pairs/open-rmf-battle-royale/map.ddpkg", "normalized/rmf/generated/world.sdf"),
    "campus-site": ("pairs/open-rmf-campus/map.ddpkg", "normalized/rmf/generated/world.sdf"),
    "two-level-clinic": ("pairs/open-rmf-clinic/map.ddpkg", "normalized/rmf/generated/world.sdf"),
    "three-level-hotel": ("pairs/open-rmf-hotel/map.ddpkg", "normalized/rmf/generated/world.sdf"),
    "office": ("pairs/open-rmf-office/map.ddpkg", "normalized/rmf/generated/world.sdf"),
    "triple-h-corridor": ("pairs/open-rmf-triple-h/map.ddpkg", "normalized/rmf/generated/world.sdf"),
}


def _numbers(text: str | None, count: int, default: tuple[float, ...]) -> tuple[float, ...]:
    if not text:
        return default
    values = tuple(float(value) for value in text.split())
    return values if len(values) >= count else default


def _pose(node: ET.Element | None) -> tuple[float, float, float, float]:
    values = _numbers(node.findtext("pose") if node is not None else None, 6, (0, 0, 0, 0, 0, 0))
    return values[0], values[1], values[2], values[5]


def _color(visual: ET.Element) -> tuple[int, int, int]:
    values = _numbers(visual.findtext("./material/diffuse"), 3, (0.68, 0.72, 0.76, 1.0))
    return tuple(max(25, min(235, round(value * 255))) for value in values[:3])


def _compose(parent: tuple[float, float, float, float], child: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    px, py, pz, pyaw = parent
    cx, cy, cz, cyaw = child
    cosine, sine = math.cos(pyaw), math.sin(pyaw)
    return px + cosine * cx - sine * cy, py + sine * cx + cosine * cy, pz + cz, pyaw + cyaw


def _boxes(raw: bytes) -> list[Box]:
    root = ET.fromstring(raw)
    result: list[Box] = []
    for model in root.findall("./world/model"):
        model_pose = _pose(model)
        for link in model.findall("./link"):
            link_pose = _compose(model_pose, _pose(link))
            for visual in link.findall("./visual"):
                size = _numbers(visual.findtext("./geometry/box/size"), 3, ())
                if len(size) != 3 or min(size) <= 0:
                    continue
                pose = _compose(link_pose, _pose(visual))
                result.append(Box(pose[:3], size[:3], pose[3], _color(visual)))
    if not result:
        raise ValueError("packaged world does not contain renderable box visuals")
    return result


def _navigation_ribbons(raw: bytes, ground_z: float) -> list[Box]:
    graph = json.loads(raw)
    nodes = {
        node["node_id"]: node["position_m"]
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("position_m"), dict)
    }
    result: list[Box] = []
    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        start = nodes.get(edge.get("from_node"))
        end = nodes.get(edge.get("to_node"))
        if start is None or end is None:
            continue
        dx, dy = float(end["x"]) - float(start["x"]), float(end["y"]) - float(start["y"])
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        result.append(Box(
            ((float(start["x"]) + float(end["x"])) / 2,
             (float(start["y"]) + float(end["y"])) / 2,
             ground_z + 0.05),
            (length, 1.15, 0.10),
            math.atan2(dy, dx),
            (58, 115, 142),
        ))
    return result


def _vertices(box: Box) -> list[tuple[float, float, float]]:
    cx, cy, cz = box.center
    sx, sy, sz = (value / 2 for value in box.size)
    cosine, sine = math.cos(box.yaw), math.sin(box.yaw)
    points = []
    for x, y, z in ((x, y, z) for z in (-sz, sz) for y in (-sy, sy) for x in (-sx, sx)):
        points.append((cx + cosine * x - sine * y, cy + sine * x + cosine * y, cz + z))
    return points


def _project(point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    # Camera is high and south-east of the scene, giving the requested oblique
    # UAV-like view while preserving building height and internal corridors.
    return (x - y, (x + y) * 0.43 - z * 1.55, x + y + z * 0.4)


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(channel * factor))) for channel in color)


def render(boxes: list[Box], output: Path) -> None:
    width, height = 1200, 675
    projected = [[_project(point) for point in _vertices(box)] for box in boxes]
    all_points = [point for points in projected for point in points]
    min_u, max_u = min(p[0] for p in all_points), max(p[0] for p in all_points)
    min_v, max_v = min(p[1] for p in all_points), max(p[1] for p in all_points)
    scale = min((width - 96) / max(max_u - min_u, 1), (height - 72) / max(max_v - min_v, 1))

    def screen(point: tuple[float, float, float]) -> tuple[float, float]:
        u, v, _ = point
        return 48 + (u - min_u) * scale, 36 + (v - min_v) * scale

    image = Image.new("RGB", (width, height), (19, 28, 39))
    draw = ImageDraw.Draw(image)
    faces = []
    face_indices = (
        ((4, 5, 7, 6), 1.14),
        ((0, 1, 5, 4), 0.78),
        ((0, 2, 6, 4), 0.9),
        ((1, 3, 7, 5), 0.67),
        ((2, 3, 7, 6), 0.74),
    )
    for box, points in zip(boxes, projected, strict=True):
        world_points = _vertices(box)
        for indices, factor in face_indices:
            face = [points[index] for index in indices]
            world_face = [world_points[index] for index in indices]
            depth = sum(point[2] for point in face) / len(face)
            elevation = sum(point[2] for point in world_face) / len(world_face)
            footprint = box.size[0] * box.size[1]
            faces.append((elevation, depth, -footprint, [screen(point) for point in face], _shade(box.color, factor)))
    for _elevation, _depth, _footprint, polygon, color in sorted(faces, key=lambda item: item[:3]):
        draw.polygon(polygon, fill=color, outline=_shade(color, 0.63))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.resize((800, 450), Image.Resampling.LANCZOS).save(output, "WEBP", quality=88, method=6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = args.core_root / "app/desktop/src-tauri/resources/default-assets"
    for key, (archive_name, member) in CATALOG.items():
        with zipfile.ZipFile(assets / archive_name) as archive:
            boxes = _boxes(archive.read(member))
            if len(boxes) == 1:
                graph_name = str(Path(member).with_name("navigation-semantic-graph.json")).replace("\\", "/")
                if graph_name in archive.namelist():
                    ground_z = boxes[0].center[2] + boxes[0].size[2] / 2
                    boxes.extend(_navigation_ribbons(archive.read(graph_name), ground_z))
            render(boxes, args.output / f"{key}.webp")


if __name__ == "__main__":
    main()
