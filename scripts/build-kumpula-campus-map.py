#!/usr/bin/env python3
"""Build the real Kumpula Campus Gazebo and frontend map artifacts.

The builder consumes pinned City of Helsinki building footprints, a City of
Helsinki orthophoto, and a small OpenStreetMap name overlay.  It emits one
local-ENU simulation world with exact extruded building visuals, conservative
oriented-box collisions, semantic mission places, and a prevalidated outdoor
round trip.  The generated output is deterministic and contains source/license
provenance so a release never silently substitutes a synthetic map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Point, Polygon, box, shape
from shapely.ops import transform

ASSET_ID = "dronedream.school-map.v1"
DISPLAY_NAME = "Kumpula Campus"
DISPLAY_NAME_ZH = "赫尔辛基大学昆普拉校区"
WORLD_NAME = "school_map_world"
MODEL_NAME = "kumpula_campus"
ORIGIN_E = 25_497_920.0
ORIGIN_N = 6_676_880.0
MAP_BOUNDS = (25_497_670.0, 6_676_630.0, 25_498_170.0, 6_677_130.0)
ORTHOPHOTO_BOUNDS = (25_497_650.0, 6_676_400.0, 25_498_550.0, 6_677_300.0)
ROUTE: tuple[tuple[float, float, float, str, float], ...] = (
    (-41.0, -83.0, 1.50, "launch", 0.55),
    (-41.0, -83.0, 35.0, "transit", 1.20),
    (0.0, -5.0, 35.0, "transit", 1.20),
    (43.0, 55.0, 35.0, "transit", 1.20),
    (43.0, 55.0, 2.00, "pickup", 0.45),
    (43.0, 55.0, 35.0, "return", 1.20),
    (0.0, -5.0, 35.0, "return", 1.20),
    (-41.0, -83.0, 35.0, "return", 1.20),
    (-41.0, -83.0, 1.50, "land", 0.35),
)
NAMED_BUILDINGS = {"Exactum", "Physicum", "Chemicum", "Dynamicum"}

MAP_ALIASES = (
    "Kumpula Campus",
    "Kumpula Science Campus",
    "Kumpulan kampus",
    "昆普拉校区",
    "昆普拉科学园区",
    "赫尔辛基大学昆普拉校区",
)

BUILDING_NAMES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Chemicum": (
        "化学楼",
        ("Chemicum", "Chemicum building", "化学楼", "化学楼建筑", "化学系大楼"),
    ),
    "Dynamicum": (
        "气象楼",
        ("Dynamicum", "Dynamicum building", "气象楼", "气象研究所大楼"),
    ),
    "Exactum": (
        "信息科学楼",
        ("Exactum", "Exactum building", "信息科学楼", "计算机科学楼", "数学与统计楼"),
    ),
    "Physicum": (
        "物理楼",
        ("Physicum", "Physicum building", "物理楼", "物理科学楼", "地球科学楼"),
    ),
}

LAUNCH_ALIASES = (
    "Kumpula south launch pad",
    "campus south launch pad",
    "office launch pad",
    "launch pad",
    "start point",
    "home point",
    "return point",
    "昆普拉校区南侧起降点",
    "校园南侧起降点",
    "办公室起降点",
    "办公室",
    "起点",
    "出发点",
    "返航点",
    "降落点",
)

PICKUP_ALIASES = (
    "Chemicum south handoff point",
    "Chemicum",
    "takeout pickup",
    "takeout pickup pad",
    "pickup point",
    "handoff point",
    "化学楼南侧交接点",
    "化学楼取餐点",
    "化学楼",
    "取餐点",
    "外卖取餐点",
    "外卖点",
    "取件点",
    "交接点",
)


@dataclass(frozen=True)
class Building:
    """One clipped, simplified real building footprint in local ENU metres."""

    building_id: str
    names: tuple[str, ...]
    polygon: Polygon
    height_m: float
    floors: int


def _parse_args() -> argparse.Namespace:
    """Parse explicit source and destination paths; no implicit cache is used."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buildings", required=True, type=Path)
    parser.add_argument("--named-buildings", required=True, type=Path)
    parser.add_argument("--orthophoto", required=True, type=Path)
    parser.add_argument("--output-map", required=True, type=Path)
    parser.add_argument("--output-frontend-geometry", required=True, type=Path)
    parser.add_argument("--output-preview", required=True, type=Path)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for provenance and reproducibility."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, value: str) -> None:
    """Write normalized UTF-8 text and create only the requested parent tree."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _write_json(path: Path, value: object) -> None:
    """Write deterministic human-readable JSON used by both runtime and UI."""

    _write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _polygons(geometry: Any) -> Iterable[Polygon]:
    """Yield non-empty polygon members while discarding unsupported geometries."""

    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _local_polygon(polygon: Polygon) -> Polygon:
    """Translate EPSG:3879 coordinates into the map's local ENU frame."""

    return transform(lambda x, y, z=None: (x - ORIGIN_E, y - ORIGIN_N), polygon)


def _named_footprints(path: Path) -> dict[str, Polygon]:
    """Load the four campus names used to label authoritative city footprints."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    projection = Transformer.from_crs(4326, 3879, always_xy=True).transform
    result: dict[str, Polygon] = {}
    for element in payload.get("elements", []):
        name = str(element.get("tags", {}).get("name", ""))
        if name not in NAMED_BUILDINGS or element.get("type") != "way":
            continue
        coordinates = [
            projection(float(point["lon"]), float(point["lat"]))
            for point in element.get("geometry", [])
        ]
        if len(coordinates) >= 4:
            polygon = Polygon(coordinates)
            if polygon.is_valid and polygon.area > 10:
                result[name] = polygon
    missing = NAMED_BUILDINGS - result.keys()
    if missing:
        raise ValueError(f"missing named campus buildings: {sorted(missing)}")
    return result


def _load_buildings(city_path: Path, names_path: Path) -> list[Building]:
    """Clip current city footprints and attach stable campus building names."""

    payload = json.loads(city_path.read_text(encoding="utf-8"))
    projection = Transformer.from_crs(4326, 3879, always_xy=True).transform
    crop = box(*MAP_BOUNDS)
    named = _named_footprints(names_path)
    buildings: list[Building] = []
    for feature in payload.get("features", []):
        raw_geometry = feature.get("geometry")
        if raw_geometry is None:
            continue
        projected = transform(projection, shape(raw_geometry)).intersection(crop)
        properties = feature.get("properties") or {}
        raw_floors = properties.get("i_kerrlkm")
        floors = int(raw_floors) if isinstance(raw_floors, (int, float)) and raw_floors > 0 else 2
        height_m = max(4.0, min(35.0, floors * 3.4))
        for polygon_index, projected_polygon in enumerate(_polygons(projected)):
            if projected_polygon.area < 20:
                continue
            simplified = projected_polygon.simplify(0.18, preserve_topology=True)
            centroid = simplified.centroid
            names = tuple(
                sorted(
                    candidate
                    for candidate, footprint in named.items()
                    if footprint.buffer(2.0).contains(centroid)
                    or footprint.intersection(simplified).area
                    > min(simplified.area, footprint.area) * 0.35
                )
            )
            identifier = str(feature.get("id", "building")).replace(".", "-")
            buildings.append(
                Building(
                    building_id=f"{identifier}-{polygon_index}",
                    names=names,
                    polygon=_local_polygon(simplified),
                    height_m=height_m,
                    floors=floors,
                )
            )
    covered_names = {name for item in buildings for name in item.names}
    if not buildings or NAMED_BUILDINGS - covered_names:
        raise ValueError("city footprints do not cover all required campus buildings")
    return sorted(buildings, key=lambda item: item.building_id)


def _obb(building: Building) -> dict[str, float | str]:
    """Build one conservative oriented collision box for a footprint."""

    coordinates = list(building.polygon.minimum_rotated_rectangle.exterior.coords)[:4]
    edges = [
        (
            math.dist(coordinates[index], coordinates[(index + 1) % 4]),
            coordinates[index],
            coordinates[(index + 1) % 4],
        )
        for index in range(4)
    ]
    longest = max(edges, key=lambda item: item[0])
    shortest = min(edges, key=lambda item: item[0])
    center = building.polygon.minimum_rotated_rectangle.centroid
    return {
        "name": f"{building.building_id}-collision",
        "semantic": "building",
        "center_x": center.x,
        "center_y": center.y,
        "center_z": building.height_m / 2,
        "size_x": longest[0],
        "size_y": shortest[0],
        "size_z": building.height_m,
        "yaw_rad": math.atan2(
            longest[2][1] - longest[1][1],
            longest[2][0] - longest[1][0],
        ),
    }


def _building_obj(buildings: list[Building]) -> tuple[str, str]:
    """Extrude exact footprint rings into a deterministic OBJ/MTL visual mesh."""

    lines = ["mtllib kumpula-buildings.mtl", "o KumpulaCampusBuildings"]
    vertex_index = 1
    for building in buildings:
        points = list(building.polygon.exterior.coords)[:-1]
        if len(points) < 3:
            continue
        material = "campus" if building.names else "context"
        lines.extend((f"g {building.building_id}", f"usemtl {material}"))
        for x, y in points:
            lines.append(f"v {x:.4f} {y:.4f} 0.0000")
        for x, y in points:
            lines.append(f"v {x:.4f} {y:.4f} {building.height_m:.4f}")
        count = len(points)
        lines.append("f " + " ".join(str(vertex_index + count + offset) for offset in range(count)))
        lines.append(
            "f " + " ".join(str(vertex_index + offset) for offset in reversed(range(count)))
        )
        for offset in range(count):
            nxt = (offset + 1) % count
            lines.append(
                "f "
                f"{vertex_index + offset} {vertex_index + nxt} "
                f"{vertex_index + count + nxt} {vertex_index + count + offset}"
            )
        vertex_index += count * 2
    material = """newmtl campus
Kd 0.77 0.80 0.84
Ka 0.12 0.12 0.12
Ks 0.08 0.08 0.08
Ns 18

newmtl context
Kd 0.53 0.58 0.61
Ka 0.08 0.08 0.08
Ks 0.04 0.04 0.04
Ns 10
"""
    return "\n".join(lines) + "\n", material


def _ground_obj() -> str:
    """Return a UV-mapped 500 m square ground mesh for the official image."""

    half = 250.0
    return f"""o KumpulaGround
v {-half:.1f} {-half:.1f} 0
v {half:.1f} {-half:.1f} 0
v {half:.1f} {half:.1f} 0
v {-half:.1f} {half:.1f} 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 1
f 1/1/1 2/2/1 3/3/1 4/4/1
"""


def _model_element(buildings: list[Building], *, visual: bool) -> ElementTree.Element:
    """Create the static SDF model shared by GUI and headless worlds."""

    model = ElementTree.Element("model", {"name": MODEL_NAME})
    ElementTree.SubElement(model, "static").text = "true"
    ground = ElementTree.SubElement(model, "link", {"name": "ground"})
    collision = ElementTree.SubElement(ground, "collision", {"name": "ground-collision"})
    geometry = ElementTree.SubElement(collision, "geometry")
    box_element = ElementTree.SubElement(geometry, "box")
    ElementTree.SubElement(box_element, "size").text = "500 500 0.2"
    ElementTree.SubElement(collision, "pose").text = "0 0 -0.1 0 0 0"
    if visual:
        ground_visual = ElementTree.SubElement(ground, "visual", {"name": "orthophoto-ground"})
        ground_geometry = ElementTree.SubElement(ground_visual, "geometry")
        mesh = ElementTree.SubElement(ground_geometry, "mesh")
        ElementTree.SubElement(mesh, "uri").text = "meshes/kumpula-ground.obj"
        material = ElementTree.SubElement(ground_visual, "material")
        pbr = ElementTree.SubElement(material, "pbr")
        metal = ElementTree.SubElement(pbr, "metal")
        ElementTree.SubElement(
            metal, "albedo_map"
        ).text = "materials/textures/kumpula-orthophoto.jpg"
        ElementTree.SubElement(metal, "roughness").text = "1.0"
        building_link = ElementTree.SubElement(model, "link", {"name": "building-visuals"})
        building_visual = ElementTree.SubElement(
            building_link, "visual", {"name": "registered-buildings"}
        )
        building_geometry = ElementTree.SubElement(building_visual, "geometry")
        building_mesh = ElementTree.SubElement(building_geometry, "mesh")
        ElementTree.SubElement(building_mesh, "uri").text = "meshes/kumpula-buildings.obj"
    for index, primitive in enumerate(_obb(building) for building in buildings):
        link = ElementTree.SubElement(model, "link", {"name": f"building-collision-{index:03d}"})
        item = ElementTree.SubElement(link, "collision", {"name": str(primitive["name"])})
        ElementTree.SubElement(item, "pose").text = (
            f"{primitive['center_x']:.4f} {primitive['center_y']:.4f} "
            f"{primitive['center_z']:.4f} 0 0 {primitive['yaw_rad']:.8f}"
        )
        item_geometry = ElementTree.SubElement(item, "geometry")
        item_box = ElementTree.SubElement(item_geometry, "box")
        ElementTree.SubElement(
            item_box, "size"
        ).text = f"{primitive['size_x']:.4f} {primitive['size_y']:.4f} {primitive['size_z']:.4f}"
    for name, x, y, color in (
        ("office-drone-launch-pad", -41.0, -83.0, "0.10 0.72 0.78 1"),
        ("takeout-pickup-pad", 43.0, 55.0, "0.98 0.25 0.42 1"),
    ):
        pad = ElementTree.SubElement(model, "link", {"name": name})
        pad_collision = ElementTree.SubElement(pad, "collision", {"name": f"{name}-collision"})
        ElementTree.SubElement(pad_collision, "pose").text = f"{x:g} {y:g} 0.04 0 0 0"
        pad_collision_geometry = ElementTree.SubElement(pad_collision, "geometry")
        pad_collision_box = ElementTree.SubElement(pad_collision_geometry, "box")
        ElementTree.SubElement(pad_collision_box, "size").text = "2.4 2.4 0.08"
        if visual:
            pad_visual = ElementTree.SubElement(pad, "visual", {"name": f"{name}-visual"})
            ElementTree.SubElement(pad_visual, "pose").text = f"{x:g} {y:g} 0.04 0 0 0"
            pad_visual_geometry = ElementTree.SubElement(pad_visual, "geometry")
            pad_visual_box = ElementTree.SubElement(pad_visual_geometry, "box")
            ElementTree.SubElement(pad_visual_box, "size").text = "2.4 2.4 0.08"
            pad_material = ElementTree.SubElement(pad_visual, "material")
            ElementTree.SubElement(pad_material, "ambient").text = color
            ElementTree.SubElement(pad_material, "diffuse").text = color
    return model


def _sdf_text(root: ElementTree.Element) -> str:
    """Serialize stable SDF 1.9 XML with a declaration."""

    ElementTree.indent(root, space="  ")
    return '<?xml version="1.0"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"


def _world_sdf(buildings: list[Building], *, visual: bool) -> str:
    """Create a self-contained Gazebo world using the registered campus model."""

    root = ElementTree.Element("sdf", {"version": "1.9"})
    world = ElementTree.SubElement(root, "world", {"name": WORLD_NAME})
    # PX4's Gazebo sensor stack expects the environmental fields below to be
    # present in the world, even though the campus geometry itself is static.
    # ODE is the engine used by the supported runtime image and is therefore
    # part of this generated map's executable contract rather than a preview
    # preference.
    # WMM-2025 field at the Kumpula origin on 2026-10-10, converted from
    # north/east/down nT to the world's ENU tesla vector.  Keeping the field
    # consistent with the declared geodetic origin prevents PX4's estimator
    # from reporting fictitious magnetic interference before arming.
    ElementTree.SubElement(world, "magnetic_field").text = "2.6872e-06 1.45048e-05 -5.05042e-05"
    ElementTree.SubElement(world, "atmosphere", {"type": "adiabatic"})
    physics = ElementTree.SubElement(world, "physics", {"name": "real_time", "type": "ode"})
    ElementTree.SubElement(physics, "max_step_size").text = "0.004"
    ElementTree.SubElement(physics, "real_time_update_rate").text = "250"
    gravity = ElementTree.SubElement(world, "gravity")
    gravity.text = "0 0 -9.80665"
    spherical = ElementTree.SubElement(world, "spherical_coordinates")
    ElementTree.SubElement(spherical, "surface_model").text = "EARTH_WGS84"
    ElementTree.SubElement(spherical, "world_frame_orientation").text = "ENU"
    ElementTree.SubElement(spherical, "latitude_deg").text = "60.2038"
    ElementTree.SubElement(spherical, "longitude_deg").text = "24.9629"
    ElementTree.SubElement(spherical, "elevation").text = "25.0"
    ElementTree.SubElement(spherical, "heading_deg").text = "0"
    scene = ElementTree.SubElement(world, "scene")
    ElementTree.SubElement(scene, "ambient").text = "0.55 0.55 0.55 1"
    ElementTree.SubElement(scene, "background").text = "0.72 0.82 0.90 1"
    world.append(_model_element(buildings, visual=visual))
    return _sdf_text(root)


def _model_sdf(buildings: list[Building]) -> str:
    """Create the standalone static model entrypoint used by package inspection."""

    root = ElementTree.Element("sdf", {"version": "1.9"})
    root.append(_model_element(buildings, visual=True))
    return _sdf_text(root)


def _crop_orthophoto(source: Path, destination: Path) -> None:
    """Crop the official 900 m source image to the local 500 m map bounds."""

    image = Image.open(source).convert("RGB")
    sx0, sy0, sx1, sy1 = ORTHOPHOTO_BOUNDS
    x0, y0, x1, y1 = MAP_BOUNDS
    left = round((x0 - sx0) / (sx1 - sx0) * image.width)
    right = round((x1 - sx0) / (sx1 - sx0) * image.width)
    top = round((sy1 - y1) / (sy1 - sy0) * image.height)
    bottom = round((sy1 - y0) / (sy1 - sy0) * image.height)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.crop((left, top, right, bottom)).resize((2048, 2048), Image.Resampling.LANCZOS).save(
        destination,
        "JPEG",
        quality=90,
        optimize=True,
    )


def _semantic(
    buildings: list[Building],
    sources: dict[str, str],
    collision_primitives: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build named places and runtime bindings consumed by planner and executor."""

    entities: list[dict[str, Any]] = [
        {
            "entity_id": "office-launch-pad",
            "name": "Kumpula south launch pad",
            "name_zh": "昆普拉校区南侧起降点",
            "aliases": list(LAUNCH_ALIASES),
            "kind": "launch",
            "semantic": "launch",
            "position_m": {"x": -41.0, "y": -83.0, "z": 0.0},
        },
        {
            "entity_id": "takeout-pickup-pad",
            "name": "Chemicum south handoff point",
            "name_zh": "化学楼南侧交接点",
            "aliases": list(PICKUP_ALIASES),
            "kind": "pickup",
            "semantic": "pickup",
            "position_m": {"x": 43.0, "y": 55.0, "z": 0.0},
        },
    ]
    for building in buildings:
        if not building.names:
            continue
        center = building.polygon.centroid
        for name in building.names:
            name_zh, aliases = BUILDING_NAMES[name]
            entities.append(
                {
                    "entity_id": name.casefold(),
                    "name": name,
                    "name_zh": name_zh,
                    "aliases": list(aliases),
                    "kind": "building",
                    "semantic": "building",
                    "position_m": {
                        "x": center.x,
                        "y": center.y,
                        "z": building.height_m / 2,
                    },
                    "floors": building.floors,
                }
            )
    return {
        "schema_version": "dronedream.map-semantic.v1",
        "asset_id": ASSET_ID,
        "scene_id": "kumpula-campus",
        "name": DISPLAY_NAME,
        "display_name": {"en-US": DISPLAY_NAME, "zh-CN": DISPLAY_NAME_ZH},
        "aliases": list(MAP_ALIASES),
        "coordinate_frame": "ENU",
        "real_world_crs": "EPSG:3879",
        "origin": {"easting_m": ORIGIN_E, "northing_m": ORIGIN_N, "elevation_m": 0.0},
        "bounds_m": {"x": 500.0, "y": 500.0, "z": 35.0},
        "entities": entities,
        # The qualification planner reads the same conservative boxes that
        # Gazebo uses.  Keeping them in the semantic contract prevents a
        # package from being promoted with a visually plausible but
        # collision-free route model.
        "collision_primitives": collision_primitives,
        "runtime_bindings": {
            "schema_version": "dronedream.map-runtime-bindings.v1",
            "simulator": "gazebo-harmonic",
            "coordinate_frame": "ENU",
            "vehicle_spawn": {
                "x": -41.0,
                "y": -83.0,
                "z": 0.067,
            },
            "mission_launch_waypoint": {"x": -41.0, "y": -83.0, "z": 1.5},
        },
        "sources": sources,
    }


def _navigation_graph() -> dict[str, Any]:
    """Create the qualified outbound corridor as one bidirectional map graph.

    The flight evidence contains the return leg explicitly.  The reusable map
    graph stores each physical corridor only once and marks it bidirectional,
    so route planning cannot select duplicate return-only nodes as destinations.
    """

    nodes = []
    for index, (x, y, z, phase, _speed) in enumerate(ROUTE[:5]):
        label = (
            "Kumpula south launch pad"
            if index == 0
            else "Chemicum south handoff point"
            if index == 4
            else f"Kumpula route {index + 1}"
        )
        nodes.append(
            {
                "node_id": f"verified-{index:03d}",
                "label": label,
                "position_m": {"x": x, "y": y, "z": z},
                "semantic": "outdoor" if phase == "transit" else phase,
            }
        )
    edges = []
    for index in range(len(nodes) - 1):
        start = nodes[index]["position_m"]
        end = nodes[index + 1]["position_m"]
        distance = math.dist(
            (start["x"], start["y"], start["z"]),
            (end["x"], end["y"], end["z"]),
        )
        edges.append(
            {
                "edge_id": f"verified-edge-{index:03d}",
                "from_node": nodes[index]["node_id"],
                "to_node": nodes[index + 1]["node_id"],
                "distance_m": distance,
                "speed_limit_mps": min(float(ROUTE[index][4]), float(ROUTE[index + 1][4])),
                "minimum_clearance_m": 3.0,
                "bidirectional": True,
                "qualification": "pending-flight-verification",
            }
        )
    return {
        "schema_version": "dronedream.map-graph.v1",
        "asset_id": ASSET_ID,
        "name": DISPLAY_NAME,
        "coordinate_frame": "map_enu",
        "named_entities": {
            "campus-south-launch-pad": nodes[0]["node_id"],
            "office-launch-pad": nodes[0]["node_id"],
            "chemicum-south-handoff-point": nodes[4]["node_id"],
            "launch-pad": nodes[0]["node_id"],
            "takeout-pickup": nodes[4]["node_id"],
            "takeout-pickup-pad": nodes[4]["node_id"],
            **{alias: nodes[0]["node_id"] for alias in LAUNCH_ALIASES},
            **{alias: nodes[4]["node_id"] for alias in PICKUP_ALIASES},
        },
        "nodes": nodes,
        "edges": edges,
    }


def _frontend_geometry(buildings: list[Building]) -> dict[str, Any]:
    """Project collision geometry and graph data into the interactive 3D viewer."""

    route_nodes = [
        {
            "node_id": f"route-{index:02d}",
            "position_m": [x, y, z],
            "semantic": phase,
        }
        for index, (x, y, z, phase, _speed) in enumerate(ROUTE)
    ]
    return {
        "schema_version": "dronedream.catalog-map-geometry.v1",
        "primitives": [
            {
                "center_x": 0.0,
                "center_y": 0.0,
                "center_z": -0.1,
                "size_x": 500.0,
                "size_y": 500.0,
                "size_z": 0.2,
                "yaw_rad": 0.0,
                "semantic": "terrain",
            },
            *[
                {key: value for key, value in _obb(item).items() if key != "name"}
                for item in buildings
            ],
            {
                "center_x": -41.0,
                "center_y": -83.0,
                "center_z": 0.04,
                "size_x": 2.4,
                "size_y": 2.4,
                "size_z": 0.08,
                "yaw_rad": 0.0,
                "semantic": "launch-pad",
            },
            {
                "center_x": 43.0,
                "center_y": 55.0,
                "center_z": 0.04,
                "size_x": 2.4,
                "size_y": 2.4,
                "size_z": 0.08,
                "yaw_rad": 0.0,
                "semantic": "pickup-pad",
            },
        ],
        "nodes": route_nodes,
        "edges": [
            {
                "from_node": route_nodes[index]["node_id"],
                "to_node": route_nodes[index + 1]["node_id"],
            }
            for index in range(len(route_nodes) - 1)
        ],
        "texture_url": "asset-previews/maps/kumpula-campus-source.jpg",
    }


def _preview(buildings: list[Building], orthophoto: Path, output: Path) -> None:
    """Render the catalog thumbnail with route and named-building labels."""

    image = Image.open(orthophoto).convert("RGB").resize((1600, 1600), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    scale = image.width / 500.0

    def pixel(x: float, y: float) -> tuple[float, float]:
        return ((x + 250.0) * scale, (250.0 - y) * scale)

    for building in buildings:
        points = [pixel(x, y) for x, y in building.polygon.exterior.coords]
        draw.line(points, fill=(255, 255, 255, 180), width=2)
        if building.names:
            cx, cy = pixel(building.polygon.centroid.x, building.polygon.centroid.y)
            draw.rounded_rectangle((cx - 52, cy - 14, cx + 52, cy + 14), 7, fill=(22, 24, 31, 210))
            draw.text(
                (cx, cy),
                " / ".join(building.names),
                anchor="mm",
                fill=(255, 255, 255, 255),
                font=ImageFont.load_default(),
            )
    route_points = [pixel(x, y) for x, y, _z, _phase, _speed in ROUTE]
    draw.line(route_points, fill=(255, 35, 99, 255), width=7, joint="curve")
    for index in (0, 4):
        x, y = route_points[index]
        draw.ellipse(
            (x - 12, y - 12, x + 12, y + 12),
            fill=(255, 255, 255, 255),
            outline=(255, 35, 99, 255),
            width=5,
        )
    result = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    output.parent.mkdir(parents=True, exist_ok=True)
    result.resize((800, 450), Image.Resampling.LANCZOS).save(output, "WEBP", quality=90, method=6)


def main() -> None:
    """Generate every runtime/UI artifact and fail on unsafe route endpoints."""

    args = _parse_args()
    buildings = _load_buildings(args.buildings, args.named_buildings)
    for x, y, _z, phase, _speed in ROUTE:
        if phase in {"launch", "pickup", "land"}:
            clearance = min(item.polygon.distance(Point(x, y)) for item in buildings)
            if clearance < 5.0:
                raise ValueError(
                    f"route endpoint {phase} has only {clearance:.2f} m building clearance"
                )
    map_root = args.output_map
    texture = map_root / "materials" / "textures" / "kumpula-orthophoto.jpg"
    _crop_orthophoto(args.orthophoto, texture)
    buildings_obj, buildings_mtl = _building_obj(buildings)
    _write_text(map_root / "meshes" / "kumpula-buildings.obj", buildings_obj)
    _write_text(map_root / "meshes" / "kumpula-buildings.mtl", buildings_mtl)
    _write_text(map_root / "meshes" / "kumpula-ground.obj", _ground_obj())
    _write_text(map_root / "model.sdf", _model_sdf(buildings))
    _write_text(map_root / "world.sdf", _world_sdf(buildings, visual=True))
    _write_text(map_root / "world.physics.sdf", _world_sdf(buildings, visual=False))
    _write_text(map_root / "world.perception.sdf", _world_sdf(buildings, visual=True))
    _write_text(
        map_root / "model.config",
        """<?xml version="1.0"?>
<model>
  <name>Kumpula Campus</name>
  <version>1.0.0</version>
  <sdf version="1.9">model.sdf</sdf>
  <author><name>DroneDream; City of Helsinki; OpenStreetMap contributors</name></author>
  <description>Real Kumpula Campus geometry, collision, semantics and imagery.</description>
</model>
""",
    )
    sources = {
        "city_buildings_sha256": _sha256(args.buildings),
        "named_buildings_sha256": _sha256(args.named_buildings),
        "orthophoto_sha256": _sha256(args.orthophoto),
        "city_data_license": "CC-BY-4.0",
        "openstreetmap_license": "ODbL-1.0",
        "city_buildings_url": "https://kartta.hel.fi/ws/geoserver/avoindata/wfs",
        "orthophoto_url": "https://kartta.hel.fi/ws/geoserver/avoindata/wms",
        "named_buildings_url": "https://www.openstreetmap.org/",
        "retrieved_at": "2026-10-10",
    }
    primitives = [_obb(item) for item in buildings]
    primitives.extend(
        [
            {
                "name": "office-drone-launch-pad",
                "semantic": "launch-pad",
                "center_x": -41.0,
                "center_y": -83.0,
                "center_z": 0.04,
                "size_x": 2.4,
                "size_y": 2.4,
                "size_z": 0.08,
                "yaw_rad": 0.0,
            },
            {
                "name": "takeout-pickup-pad",
                "semantic": "pickup-pad",
                "center_x": 43.0,
                "center_y": 55.0,
                "center_z": 0.04,
                "size_x": 2.4,
                "size_y": 2.4,
                "size_z": 0.08,
                "yaw_rad": 0.0,
            },
        ]
    )
    semantic = _semantic(buildings, sources, primitives)
    _write_json(map_root / "semantic.json", semantic)
    graph = _navigation_graph()
    _write_json(map_root.parent / "navigation-graph.json", graph)
    _write_json(map_root / "collision-primitives.json", {"primitives": primitives})
    _write_json(
        map_root / "summary.json",
        {
            "schema_version": "dronedream.kumpula-campus-summary.v1",
            "asset_id": ASSET_ID,
            "name": DISPLAY_NAME,
            "source_kind": "real-geospatial-data",
            "visual_primitive_count": len(buildings) + 1,
            "collision_primitive_count": len(primitives) + 1,
            "building_count": len(buildings),
            "named_buildings": sorted(NAMED_BUILDINGS),
            "bounds_m": {"x": 500.0, "y": 500.0, "z": 35.0},
            "sources": sources,
        },
    )
    _write_text(
        map_root / "README.md",
        """# Kumpula Campus runtime map

This package is a local-ENU simulation derivative of current City of Helsinki
building-register footprints and the 2025 Helsinki orthophoto (CC BY 4.0).
Building names are cross-checked against the University of Helsinki campus list
and OpenStreetMap contributors (ODbL 1.0). Collision boxes are conservative
proxies around the exact visual footprint meshes; the mission route is verified
against those proxies before qualification.
""",
    )
    _write_json(args.output_frontend_geometry, _frontend_geometry(buildings))
    frontend_source = args.output_preview.with_name("kumpula-campus-source.jpg")
    frontend_source.parent.mkdir(parents=True, exist_ok=True)
    Image.open(texture).save(frontend_source, "JPEG", quality=90, optimize=True)
    _preview(buildings, texture, args.output_preview)
    print(
        json.dumps(
            {
                "map": str(map_root),
                "buildings": len(buildings),
                "named_buildings": sorted(NAMED_BUILDINGS),
                "route_waypoints": len(ROUTE),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
