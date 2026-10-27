#!/usr/bin/env python3
"""Build the five first-party Helsinki maps from current official open data.

The output is deliberately shared across the product: Gazebo consumes the SDF
and meshes, Agent Core consumes the semantic and navigation contracts, and the
desktop catalog consumes the same geometry and imagery.  A map therefore cannot
silently drift between its card, planner, and simulator representation.

Install the reproducible builder dependencies from ``tools/requirements-maps.txt``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import shutil
import zipfile
from collections import defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree

import requests
from PIL import Image, ImageDraw
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import transform, unary_union

CITY_WFS = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
CITY_WMS = "https://kartta.hel.fi/ws/geoserver/avoindata/wms"
BUILDING_LAYER = "avoindata:Rakennukset_alue_rekisteritiedot"
ROAD_LAYER = "avoindata:Liikennevaylat"
TREE_LAYER = "avoindata:Puurekisteri_piste"
FOREST_LAYER = "avoindata:LTJ_avoin_metsaverkosto_2015"
ORTHOPHOTO_LAYER = "avoindata:Ortoilmakuva_2026_5cm"
ARCHIVE_TIMESTAMP = (2026, 10, 27, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("data") / "helsinki-maps.json"
    )
    parser.add_argument(
        "--map", dest="map_key", action="append", help="Build only this map key; may be repeated"
    )
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--backend-assets", type=Path, required=True)
    parser.add_argument("--frontend-public", type=Path, required=True)
    parser.add_argument("--agent-core-assets", type=Path, required=True)
    parser.add_argument("--catalog-output", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def polygons(value: Any) -> Iterable[Polygon]:
    if isinstance(value, Polygon):
        yield value
    elif isinstance(value, MultiPolygon):
        yield from value.geoms


def lines(value: Any) -> Iterable[LineString]:
    if isinstance(value, LineString):
        yield value
    elif isinstance(value, MultiLineString):
        yield from value.geoms


def download(session: requests.Session, url: str, destination: Path, *, refresh: bool) -> None:
    if destination.is_file() and destination.stat().st_size > 0 and not refresh:
        return
    response = session.get(url, timeout=180)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)


def wfs_url(layer: str, bbox_wgs84: tuple[float, float, float, float]) -> str:
    query = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": layer,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": ",".join(f"{value:.8f}" for value in bbox_wgs84) + ",EPSG:4326",
        "count": "20000",
    }
    return f"{CITY_WFS}?{urlencode(query)}"


def wms_url(bounds: tuple[float, float, float, float]) -> str:
    query = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetMap",
        "layers": ORTHOPHOTO_LAYER,
        "styles": "",
        "srs": "EPSG:3879",
        "bbox": ",".join(f"{value:.3f}" for value in bounds),
        "width": "2048",
        "height": "2048",
        "format": "image/jpeg",
        "transparent": "false",
    }
    return f"{CITY_WMS}?{urlencode(query)}"


def source_paths(cache_root: Path, key: str) -> dict[str, Path]:
    root = cache_root / key
    return {
        "buildings": root / "buildings.geojson",
        "roads": root / "roads.geojson",
        "trees": root / "trees.geojson",
        "forest": root / "forest.geojson",
        "orthophoto": root / "orthophoto.jpg",
    }


def acquire_sources(
    config: dict[str, Any], cache_root: Path, *, refresh: bool
) -> tuple[dict[str, Path], dict[str, Any]]:
    to_local = Transformer.from_crs(4326, 3879, always_xy=True)
    to_wgs84 = Transformer.from_crs(3879, 4326, always_xy=True)
    east, north = to_local.transform(config["longitude"], config["latitude"])
    half_x, half_y = config["width_m"] / 2, config["height_m"] / 2
    bounds = (east - half_x, north - half_y, east + half_x, north + half_y)
    west, south = to_wgs84.transform(bounds[0], bounds[1])
    east_lon, north_lat = to_wgs84.transform(bounds[2], bounds[3])
    bbox_wgs84 = (west, south, east_lon, north_lat)
    paths = source_paths(cache_root, config["key"])
    with requests.Session() as session:
        session.headers["User-Agent"] = "DroneDream map builder/1.0 (first-party product assets)"
        for name, layer in (
            ("buildings", BUILDING_LAYER),
            ("roads", ROAD_LAYER),
            ("trees", TREE_LAYER),
            ("forest", FOREST_LAYER),
        ):
            download(session, wfs_url(layer, bbox_wgs84), paths[name], refresh=refresh)
        download(session, wms_url(bounds), paths["orthophoto"], refresh=refresh)
    Image.open(paths["orthophoto"]).verify()
    return paths, {
        "origin_easting_m": east,
        "origin_northing_m": north,
        "bounds_epsg_3879": bounds,
        "bbox_wgs84": bbox_wgs84,
    }


def local_geometry(raw: Any, projection: Any, origin: tuple[float, float]) -> Any:
    projected = transform(projection, shape(raw))
    return transform(lambda x, y, z=None: (x - origin[0], y - origin[1]), projected)


def building_name(properties: dict[str, Any], identifier: str) -> tuple[str, str]:
    street = str(properties.get("katunimi_suomi") or "").strip()
    number = str(properties.get("osoitenumero") or "").strip()
    kind = str(properties.get("tyyppi") or "Building").strip()
    address = " ".join(part for part in (street, number) if part)
    return (address or f"Building {identifier}", kind)


def load_buildings(
    path: Path, config: dict[str, Any], origin: tuple[float, float]
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    projection = Transformer.from_crs(4326, 3879, always_xy=True).transform
    crop = box(
        -config["width_m"] / 2,
        -config["height_m"] / 2,
        config["width_m"] / 2,
        config["height_m"] / 2,
    )
    result: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        if not feature.get("geometry"):
            continue
        geometry = local_geometry(feature["geometry"], projection, origin).intersection(crop)
        properties = feature.get("properties") or {}
        floors_value = properties.get("i_kerrlkm")
        floors = (
            int(floors_value) if isinstance(floors_value, (int, float)) and floors_value > 0 else 2
        )
        height_m = min(float(config["ceiling_m"]), max(4.0, floors * 3.4))
        identifier = str(
            properties.get("vtj_prt") or properties.get("id") or feature.get("id") or "building"
        )
        name, function = building_name(properties, identifier)
        for index, polygon in enumerate(polygons(geometry)):
            if polygon.area < 12:
                continue
            simplified = polygon.simplify(0.18, preserve_topology=True)
            result.append(
                {
                    "id": f"{identifier}-{index}",
                    "polygon": simplified,
                    "height_m": height_m,
                    "floors": floors,
                    "name": name,
                    "name_zh": name,
                    "function": function,
                    "address": name if not name.startswith("Building ") else None,
                    "registry_id": identifier,
                }
            )
    if not result:
        raise ValueError(f"{config['key']}: official building query returned no usable footprints")
    return sorted(result, key=lambda item: item["id"])


def load_trees(
    path: Path, config: dict[str, Any], origin: tuple[float, float]
) -> tuple[list[dict[str, float]], int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    projection = Transformer.from_crs(4326, 3879, always_xy=True).transform
    crop = box(
        -config["width_m"] / 2,
        -config["height_m"] / 2,
        config["width_m"] / 2,
        config["height_m"] / 2,
    )
    points: list[dict[str, float]] = []
    for feature in payload.get("features", []):
        if not feature.get("geometry"):
            continue
        value = local_geometry(feature["geometry"], projection, origin)
        if isinstance(value, Point) and crop.contains(value):
            props = feature.get("properties") or {}
            diameter = props.get("latvuksen_halkaisija") or props.get("latvus_halk") or 5.0
            try:
                radius = min(6.0, max(1.5, float(diameter) / 2))
            except (TypeError, ValueError):
                radius = 2.5
            points.append(
                {"x": value.x, "y": value.y, "radius": radius, "height": max(5.0, radius * 3.0)}
            )
    return points[:1000], len(points)


def load_regions(
    path: Path, config: dict[str, Any], origin: tuple[float, float]
) -> list[list[list[float]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    projection = Transformer.from_crs(4326, 3879, always_xy=True).transform
    crop = box(
        -config["width_m"] / 2,
        -config["height_m"] / 2,
        config["width_m"] / 2,
        config["height_m"] / 2,
    )
    result: list[list[list[float]]] = []
    for feature in payload.get("features", []):
        if not feature.get("geometry"):
            continue
        geometry = local_geometry(feature["geometry"], projection, origin).intersection(crop)
        for polygon in polygons(geometry):
            simplified = polygon.simplify(1.0, preserve_topology=True)
            if simplified.area >= 80:
                result.append(
                    [[round(x, 3), round(y, 3)] for x, y in list(simplified.exterior.coords)[:-1]]
                )
    return result


def load_road_graph(
    path: Path,
    config: dict[str, Any],
    origin: tuple[float, float],
    buildings: list[dict[str, Any]],
    trees: list[dict[str, float]],
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    projection = Transformer.from_crs(4326, 3879, always_xy=True).transform
    crop = box(
        -config["width_m"] / 2,
        -config["height_m"] / 2,
        config["width_m"] / 2,
        config["height_m"] / 2,
    )
    nodes: dict[tuple[float, float], dict[str, Any]] = {}
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    adjacency: dict[str, set[str]] = defaultdict(set)
    obstacle = unary_union(
        [
            *[
                entry["polygon"].minimum_rotated_rectangle.buffer(0.8, join_style="mitre")
                for entry in buildings
            ],
            *[Point(entry["x"], entry["y"]).buffer(entry["radius"] + 0.8) for entry in trees],
        ]
    )

    def node_id(x: float, y: float) -> str:
        key = (round(x, 1), round(y, 1))
        if key not in nodes:
            identifier = f"road-{len(nodes):05d}"
            nodes[key] = {
                "node_id": identifier,
                "label": "Official road network",
                "position_m": {"x": key[0], "y": key[1], "z": 8.0},
                "semantic": "outdoor",
            }
        return nodes[key]["node_id"]

    for feature in payload.get("features", []):
        if not feature.get("geometry"):
            continue
        geometry = local_geometry(feature["geometry"], projection, origin).intersection(crop)
        for segment in lines(geometry):
            coordinates = list(segment.coords)
            for start, end in zip(coordinates, coordinates[1:], strict=False):
                if math.dist(start[:2], end[:2]) < 0.4:
                    continue
                if LineString((start[:2], end[:2])).intersects(obstacle):
                    continue
                left, right = node_id(*start[:2]), node_id(*end[:2])
                key = tuple(sorted((left, right)))
                if key in edges:
                    continue
                edges[key] = {
                    "edge_id": f"road-edge-{len(edges):05d}",
                    "from_node": left,
                    "to_node": right,
                    "distance_m": round(math.dist(start[:2], end[:2]), 3),
                    "speed_limit_mps": 5.0,
                    "minimum_clearance_m": 0.8,
                    "bidirectional": True,
                    "qualification": "geometry-derived",
                }
                adjacency[left].add(right)
                adjacency[right].add(left)
    if not nodes or not edges:
        raise ValueError(f"{config['key']}: official road query returned no connected geometry")

    by_id = {value["node_id"]: value for value in nodes.values()}
    components: list[set[str]] = []
    unseen = set(by_id)
    while unseen:
        seed = unseen.pop()
        component = {seed}
        queue = deque([seed])
        while queue:
            current = queue.popleft()
            for candidate in adjacency[current]:
                if candidate in unseen:
                    unseen.remove(candidate)
                    component.add(candidate)
                    queue.append(candidate)
        components.append(component)
    largest = max(components, key=len)
    # A valid road node is not automatically a valid launch pad.  Keep the
    # complete x500 footprint well inside the finite Gazebo ground collision;
    # otherwise a return-to-launch can put one rotor outside the plane and the
    # vehicle falls through while PX4 is trying to confirm landing.
    launch_margin_m = max(12.0, min(config["width_m"], config["height_m"]) * 0.04)
    half_width = float(config["width_m"]) / 2.0
    half_height = float(config["height_m"]) / 2.0
    safe = [
        entry
        for identifier, entry in by_id.items()
        if identifier in largest
        and not obstacle.contains(Point(entry["position_m"]["x"], entry["position_m"]["y"]))
        and -half_width + launch_margin_m
        <= float(entry["position_m"]["x"])
        <= half_width - launch_margin_m
        and -half_height + launch_margin_m
        <= float(entry["position_m"]["y"])
        <= half_height - launch_margin_m
    ]
    if len(safe) < 2:
        raise ValueError(f"{config['key']}: road graph has no safe mission endpoints")
    launch = min(safe, key=lambda entry: entry["position_m"]["x"] + entry["position_m"]["y"])
    representative_distance_m = min(180.0, min(config["width_m"], config["height_m"]) * 0.3)
    candidates = [
        entry
        for entry in safe
        if 60.0
        <= math.dist(
            (entry["position_m"]["x"], entry["position_m"]["y"]),
            (launch["position_m"]["x"], launch["position_m"]["y"]),
        )
        <= representative_distance_m
    ]
    handoff = max(
        candidates or safe,
        key=lambda entry: math.dist(
            (entry["position_m"]["x"], entry["position_m"]["y"]),
            (launch["position_m"]["x"], launch["position_m"]["y"]),
        ),
    )
    launch["label"] = f"{config['name']} launch point"
    launch["semantic"] = "launch"
    handoff["label"] = f"{config['name']} outdoor handoff point"
    handoff["semantic"] = "delivery"
    connected_nodes = [by_id[identifier] for identifier in sorted(largest)]
    building_handoffs = []
    for building in buildings:
        center = building["polygon"].centroid
        road_node = min(
            connected_nodes,
            key=lambda entry: math.dist(
                (center.x, center.y),
                (entry["position_m"]["x"], entry["position_m"]["y"]),
            ),
        )
        building_handoffs.append(
            {
                "building_id": building["id"],
                "node_id": road_node["node_id"],
                "position_m": road_node["position_m"],
                "distance_to_building_m": round(
                    math.dist(
                        (center.x, center.y),
                        (road_node["position_m"]["x"], road_node["position_m"]["y"]),
                    ),
                    3,
                ),
            }
        )
    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "launch": launch,
        "handoff": handoff,
        "building_handoffs": building_handoffs,
        "largest_component_size": len(largest),
    }


def obb(building: dict[str, Any]) -> dict[str, Any]:
    rectangle = building["polygon"].minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)[:4]
    sides = [
        (
            math.dist(coordinates[i], coordinates[(i + 1) % 4]),
            coordinates[i],
            coordinates[(i + 1) % 4],
        )
        for i in range(4)
    ]
    longest = max(sides, key=lambda item: item[0])
    shortest = min(sides, key=lambda item: item[0])
    center = rectangle.centroid
    return {
        "name": f"{building['id']}-collision",
        "semantic": "building",
        "center_x": round(center.x, 4),
        "center_y": round(center.y, 4),
        "center_z": round(building["height_m"] / 2, 4),
        "size_x": round(longest[0], 4),
        "size_y": round(shortest[0], 4),
        "size_z": round(building["height_m"], 4),
        "yaw_rad": round(
            math.atan2(longest[2][1] - longest[1][1], longest[2][0] - longest[1][0]), 8
        ),
    }


def building_mesh(buildings: list[dict[str, Any]], key: str) -> tuple[str, str]:
    lines_out = [f"mtllib {key}-buildings.mtl", f"o {key}"]
    vertex = 1
    for building in buildings:
        points = list(building["polygon"].exterior.coords)[:-1]
        if len(points) < 3:
            continue
        lines_out.extend((f"g {building['id']}", "usemtl buildings"))
        lines_out.extend(f"v {x:.4f} {y:.4f} 0.0000" for x, y in points)
        lines_out.extend(f"v {x:.4f} {y:.4f} {building['height_m']:.4f}" for x, y in points)
        count = len(points)
        lines_out.append("f " + " ".join(str(vertex + count + offset) for offset in range(count)))
        lines_out.append("f " + " ".join(str(vertex + offset) for offset in reversed(range(count))))
        for offset in range(count):
            nxt = (offset + 1) % count
            lines_out.append(
                "f "
                f"{vertex + offset} {vertex + nxt} "
                f"{vertex + count + nxt} {vertex + count + offset}"
            )
        vertex += count * 2
    material = "newmtl buildings\nKd 0.72 0.75 0.80\nKa 0.10 0.10 0.10\nKs 0.05 0.05 0.05\nNs 12\n"
    return "\n".join(lines_out) + "\n", material


def ground_mesh(config: dict[str, Any]) -> str:
    hx, hy = config["width_m"] / 2, config["height_m"] / 2
    return f"""o {config["key"]}-ground
v {-hx:.3f} {-hy:.3f} 0
v {hx:.3f} {-hy:.3f} 0
v {hx:.3f} {hy:.3f} 0
v {-hx:.3f} {hy:.3f} 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 1
f 1/1/1 2/2/1 3/3/1 4/4/1
"""


def sdf_text(
    config: dict[str, Any],
    buildings: list[dict[str, Any]],
    trees: list[dict[str, float]],
    *,
    model_only: bool = False,
) -> str:
    root = ElementTree.Element("sdf", {"version": "1.9"})
    if model_only:
        parent = root
    else:
        world = ElementTree.SubElement(root, "world", {"name": f"{config['key']}-world"})
        ElementTree.SubElement(world, "magnetic_field").text = "2.7e-06 1.45e-05 -5.05e-05"
        ElementTree.SubElement(world, "atmosphere", {"type": "adiabatic"})
        ElementTree.SubElement(world, "gravity").text = "0 0 -9.80665"
        physics = ElementTree.SubElement(world, "physics", {"name": "real_time", "type": "ode"})
        ElementTree.SubElement(physics, "max_step_size").text = "0.004"
        ElementTree.SubElement(physics, "real_time_update_rate").text = "250"
        spherical = ElementTree.SubElement(world, "spherical_coordinates")
        ElementTree.SubElement(spherical, "surface_model").text = "EARTH_WGS84"
        ElementTree.SubElement(spherical, "world_frame_orientation").text = "ENU"
        ElementTree.SubElement(spherical, "latitude_deg").text = str(config["latitude"])
        ElementTree.SubElement(spherical, "longitude_deg").text = str(config["longitude"])
        ElementTree.SubElement(spherical, "elevation").text = "0"
        ElementTree.SubElement(spherical, "heading_deg").text = "0"
        parent = world
    model = ElementTree.SubElement(parent, "model", {"name": config["key"]})
    ElementTree.SubElement(model, "static").text = "true"
    ground = ElementTree.SubElement(model, "link", {"name": "ground"})
    collision = ElementTree.SubElement(ground, "collision", {"name": "ground-collision"})
    ElementTree.SubElement(collision, "pose").text = "0 0 -0.1 0 0 0"
    size = ElementTree.SubElement(
        ElementTree.SubElement(ElementTree.SubElement(collision, "geometry"), "box"), "size"
    )
    size.text = f"{config['width_m']} {config['height_m']} 0.2"
    visual = ElementTree.SubElement(ground, "visual", {"name": "orthophoto-ground"})
    mesh = ElementTree.SubElement(ElementTree.SubElement(visual, "geometry"), "mesh")
    ElementTree.SubElement(mesh, "uri").text = f"meshes/{config['key']}-ground.obj"
    metal = ElementTree.SubElement(
        ElementTree.SubElement(ElementTree.SubElement(visual, "material"), "pbr"), "metal"
    )
    ElementTree.SubElement(
        metal, "albedo_map"
    ).text = f"materials/textures/{config['key']}-orthophoto.jpg"
    ElementTree.SubElement(metal, "roughness").text = "1.0"
    structures = ElementTree.SubElement(model, "link", {"name": "building-visuals"})
    building_visual = ElementTree.SubElement(
        structures, "visual", {"name": "registered-building-visuals"}
    )
    visual_mesh = ElementTree.SubElement(
        ElementTree.SubElement(building_visual, "geometry"), "mesh"
    )
    ElementTree.SubElement(visual_mesh, "uri").text = f"meshes/{config['key']}-buildings.obj"
    # DART/ODE cannot safely collide one OBJ containing many concave footprint
    # groups.  Use one conservative oriented box per registered footprint while
    # retaining the exact extrusion for the visual and semantic geometry.
    for index, primitive in enumerate(obb(building) for building in buildings):
        link = ElementTree.SubElement(model, "link", {"name": f"building-collision-{index:04d}"})
        item = ElementTree.SubElement(link, "collision", {"name": str(primitive["name"])})
        ElementTree.SubElement(item, "pose").text = (
            f"{primitive['center_x']} {primitive['center_y']} {primitive['center_z']} "
            f"0 0 {primitive['yaw_rad']}"
        )
        item_box = ElementTree.SubElement(ElementTree.SubElement(item, "geometry"), "box")
        ElementTree.SubElement(
            item_box, "size"
        ).text = f"{primitive['size_x']} {primitive['size_y']} {primitive['size_z']}"
    for index, tree in enumerate(trees):
        link = ElementTree.SubElement(model, "link", {"name": f"tree-{index:04d}"})
        item = ElementTree.SubElement(link, "collision", {"name": f"tree-canopy-{index:04d}"})
        ElementTree.SubElement(
            item, "pose"
        ).text = f"{tree['x']:.3f} {tree['y']:.3f} {tree['height'] / 2:.3f} 0 0 0"
        cylinder = ElementTree.SubElement(ElementTree.SubElement(item, "geometry"), "cylinder")
        ElementTree.SubElement(cylinder, "radius").text = f"{tree['radius']:.3f}"
        ElementTree.SubElement(cylinder, "length").text = f"{tree['height']:.3f}"
    ElementTree.indent(root, space="  ")
    return '<?xml version="1.0"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"


def semantic_contract(
    config: dict[str, Any],
    georef: dict[str, Any],
    buildings: list[dict[str, Any]],
    trees: list[dict[str, float]],
    forests: list[list[list[float]]],
    graph: dict[str, Any],
    sources: dict[str, Any],
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    handoff_by_building = {item["building_id"]: item for item in graph["building_handoffs"]}
    for building in buildings:
        center = building["polygon"].centroid
        aliases = [building["name"]]
        if building["address"]:
            aliases.append(building["address"])
        handoff = handoff_by_building[building["id"]]
        handoff_entity_id = f"building-{building['id']}-outdoor-handoff"
        entities.append(
            {
                "entity_id": f"building-{building['id']}",
                "name": building["name"],
                "name_zh": building["name_zh"],
                "aliases": sorted(set(aliases)),
                "kind": "building",
                "semantic": "building",
                "position_m": {
                    "x": round(center.x, 3),
                    "y": round(center.y, 3),
                    "z": round(building["height_m"] / 2, 3),
                },
                "floors": building["floors"],
                "function": building["function"],
                "address": building["address"],
                "registry_id": building["registry_id"],
                "outdoor_handoff_entity_id": handoff_entity_id,
                "footprint_m": [
                    [round(x, 3), round(y, 3)]
                    for x, y in list(building["polygon"].exterior.coords)[:-1]
                ],
                "source": "City of Helsinki building register",
            }
        )
        entities.append(
            {
                "entity_id": handoff_entity_id,
                "name": f"{building['name']} outdoor handoff",
                "name_zh": f"{building['name_zh']}室外交接点",
                "aliases": [
                    f"{building['name']} handoff",
                    f"{building['address']} handoff" if building["address"] else handoff_entity_id,
                ],
                "kind": "delivery",
                "semantic": "delivery",
                "position_m": handoff["position_m"],
                "operation": "outdoor-hover-handoff",
                "building_entity_id": f"building-{building['id']}",
                "route_node_id": handoff["node_id"],
                "distance_to_building_m": handoff["distance_to_building_m"],
                "route_source": "official-road-network",
                "location_claim": "nearest-connected-road-node-not-a-surveyed-doorway",
            }
        )
    launch, handoff = graph["launch"], graph["handoff"]
    for kind, entry, suffix in (
        ("launch", launch, "launch point"),
        ("delivery", handoff, "outdoor handoff point"),
    ):
        entities.append(
            {
                "entity_id": f"{config['key']}-{kind}",
                "name": f"{config['name']} {suffix}",
                "name_zh": f"{config['name_zh']}{'起降点' if kind == 'launch' else '室外交接点'}",
                "aliases": [entry["label"], suffix],
                "kind": kind,
                "semantic": kind,
                "position_m": entry["position_m"],
                "operation": "outdoor-launch-land" if kind == "launch" else "outdoor-hover-handoff",
                "route_source": "official-road-network",
            }
        )
    primitives = [
        {
            "name": "terrain-ground",
            "semantic": "terrain",
            "center_x": 0.0,
            "center_y": 0.0,
            "center_z": -0.1,
            "size_x": float(config["width_m"]),
            "size_y": float(config["height_m"]),
            "size_z": 0.2,
            "yaw_rad": 0.0,
        },
        *[obb(item) for item in buildings],
    ]
    primitives.extend(
        {
            "name": f"tree-canopy-{index:04d}",
            "semantic": "vegetation",
            "center_x": tree["x"],
            "center_y": tree["y"],
            "center_z": tree["height"] / 2,
            "size_x": tree["radius"] * 2,
            "size_y": tree["radius"] * 2,
            "size_z": tree["height"],
            "yaw_rad": 0.0,
        }
        for index, tree in enumerate(trees)
    )
    return {
        "schema_version": "dronedream.map-semantic.v1",
        "asset_id": config["asset_id"],
        "scene_id": config["key"],
        "name": config["name"],
        "display_name": {"en-US": config["name"], "zh-CN": config["name_zh"]},
        "aliases": [config["name"], config["name_zh"]],
        "coordinate_frame": "ENU",
        "real_world_crs": "EPSG:3879",
        "origin": {
            "easting_m": georef["origin_easting_m"],
            "northing_m": georef["origin_northing_m"],
            "elevation_m": 0.0,
        },
        "bounds_m": {"x": config["width_m"], "y": config["height_m"], "z": config["ceiling_m"]},
        "fidelity": {
            "scope": "outdoor-exterior-only",
            "terrain": "registered-orthophoto-plane",
            "building_visuals": "city-register-footprint-extrusions",
            "building_collisions": "conservative-oriented-boxes",
            "tree_collisions": "city-tree-register-canopy-cylinders",
            "forest_restrictions": "city-ecological-network-polygons",
            "interior_geometry": False,
            "qualified_routes": 0,
        },
        "entities": entities,
        "collision_primitives": primitives,
        "restricted_regions": [
            {
                "region_id": f"forest-{index:04d}",
                "semantic": "protected-forest",
                "polygon_m": polygon,
            }
            for index, polygon in enumerate(forests)
        ],
        "runtime_bindings": {
            "schema_version": "dronedream.map-runtime-bindings.v1",
            "simulator": "gazebo-harmonic",
            "coordinate_frame": "ENU",
            "vehicle_spawn": {**launch["position_m"], "z": 0.067},
            "mission_launch_waypoint": launch["position_m"],
        },
        "sources": sources,
    }


def render_preview(
    config: dict[str, Any],
    image_path: Path,
    buildings: list[dict[str, Any]],
    graph: dict[str, Any],
    destination: Path,
) -> None:
    image = Image.open(image_path).convert("RGB").resize((1600, 1600), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    sx, sy = image.width / config["width_m"], image.height / config["height_m"]

    def pixel(x: float, y: float) -> tuple[float, float]:
        return ((x + config["width_m"] / 2) * sx, (config["height_m"] / 2 - y) * sy)

    for building in buildings:
        draw.line(
            [pixel(x, y) for x, y in building["polygon"].exterior.coords],
            fill=(255, 255, 255, 190),
            width=2,
        )
    node_by_id = {entry["node_id"]: entry for entry in graph["nodes"]}
    for edge in graph["edges"]:
        left = node_by_id[edge["from_node"]]["position_m"]
        right = node_by_id[edge["to_node"]]["position_m"]
        draw.line(
            [pixel(left["x"], left["y"]), pixel(right["x"], right["y"])],
            fill=(115, 245, 255, 95),
            width=2,
        )
    for entry, color in (
        (graph["launch"], (83, 221, 234, 255)),
        (graph["handoff"], (255, 70, 132, 255)),
    ):
        x, y = pixel(entry["position_m"]["x"], entry["position_m"]["y"])
        draw.ellipse(
            (x - 13, y - 13, x + 13, y + 13), fill=(255, 255, 255, 255), outline=color, width=6
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB").resize(
        (800, 450), Image.Resampling.LANCZOS
    ).save(destination, "WEBP", quality=91, method=6)


def frontend_geometry(
    config: dict[str, Any],
    buildings: list[dict[str, Any]],
    trees: list[dict[str, float]],
    forests: list[list[list[float]]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "dronedream.catalog-map-geometry.v1",
        "building_footprints": [
            {
                "building_id": item["id"],
                "height_m": item["height_m"],
                "points": [
                    [round(x, 4), round(y, 4)]
                    for x, y in list(item["polygon"].exterior.coords)[:-1]
                ],
                "semantic": "building",
                "name": item["name"],
                "name_zh": item["name_zh"],
                "function": item["function"],
                "function_zh": item["function"],
                "address": item["address"],
            }
            for item in buildings
        ],
        "primitives": [
            {
                "center_x": 0,
                "center_y": 0,
                "center_z": -0.1,
                "size_x": config["width_m"],
                "size_y": config["height_m"],
                "size_z": 0.2,
                "yaw_rad": 0,
                "semantic": "terrain",
            },
            *[
                {key: value for key, value in obb(item).items() if key != "name"}
                for item in buildings
            ],
            *[
                {
                    "center_x": item["x"],
                    "center_y": item["y"],
                    "center_z": item["height"] / 2,
                    "size_x": item["radius"] * 2,
                    "size_y": item["radius"] * 2,
                    "size_z": item["height"],
                    "yaw_rad": 0,
                    "semantic": "vegetation",
                }
                for item in trees
            ],
        ],
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "restricted_regions": forests,
        "texture_url": f"asset-previews/maps/{config['key']}-source.jpg",
    }


def file_role(relative: str) -> str:
    lowered = relative.casefold()
    suffix = Path(relative).suffix.casefold()
    if lowered.endswith("semantic.json"):
        return "semantic"
    if suffix in {".sdf", ".world"}:
        return "sdf"
    if suffix in {".obj", ".dae", ".stl", ".gltf", ".glb", ".png", ".jpg", ".jpeg"}:
        return "visual"
    return "metadata"


def package_content_sha256(files: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        sorted(files, key=lambda item: item["path"].casefold()),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256_bytes(encoded.encode())


def build_ddpkg(config: dict[str, Any], source_root: Path, destination: Path) -> dict[str, str]:
    payloads: dict[str, bytes] = {}
    for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
        relative = source.relative_to(source_root).as_posix()
        payloads[f"normalized/map/{relative}"] = source.read_bytes()
    files = []
    for path, payload in sorted(payloads.items()):
        media_type = (
            "application/json"
            if path.endswith(".json")
            else "application/xml"
            if path.endswith(".sdf")
            else mimetypes.guess_type(path)[0] or "application/octet-stream"
        )
        files.append(
            {
                "path": path,
                "role": file_role(path.removeprefix("normalized/map/")),
                "media_type": media_type,
                "sha256": sha256_bytes(payload),
                "size_bytes": len(payload),
            }
        )
    summary = json.loads(payloads["normalized/map/gazebo/summary.json"])
    graph = json.loads(payloads["normalized/map/navigation-graph.json"])
    provenance = package_content_sha256(files)
    asset_ir = {
        "schema_version": "dronedream.asset-ir.v1",
        "asset_id": config["asset_id"],
        "name": config["name"],
        "version": "1.0.0",
        "kind": "map",
        "source": {
            "adapter_id": "dronedream.first-party-map",
            "adapter_version": "1.0.0",
            "application": "DroneDream",
            "application_version": "1.0.0",
            "source_format": "dronedream-native",
            "source_sha256": provenance,
        },
        "coordinate_frame": "map_enu",
        "length_unit": "metre",
        "mass_unit": "kilogram",
        "angle_unit": "radian",
        "files": files,
        "simulation_targets": [
            {
                "target_id": "gazebo-harmonic",
                "simulator": "gazebo-harmonic",
                "simulator_version": "8",
                "autopilot": "none",
                "entrypoint": "normalized/map/gazebo/world.sdf",
            }
        ],
        "runtime_extensions": [],
        "geometry": {
            "visual_paths": [entry["path"] for entry in files if entry["role"] == "visual"],
            "collision_paths": [],
            "coordinate_frames": ["map_enu"],
            "up_axis": "z",
            "paths_normalized": True,
            "visual_count": summary["visual_primitive_count"],
            "collision_count": summary["collision_primitive_count"],
        },
        "physics": {
            "link_count": 3 + summary["tree_collision_count"],
            "joint_count": 0,
            "mass_entry_count": 0,
            "inertia_entry_count": 0,
            "collision_complete": True,
            "mass_complete": False,
            "inertia_complete": False,
            "contact_materials": [],
        },
        "vehicle": None,
        "sensors": [],
        "semantics": {
            "named_place_count": len(graph["named_entities"]),
            "region_count": summary["forest_region_count"],
            "navigation_graph_path": "normalized/map/navigation-graph.json",
            "traversability_path": None,
        },
        "interfaces": {
            "gazebo_entrypoints": ["normalized/map/gazebo/world.sdf"],
            "ros2_entrypoints": [],
            "px4_profiles": [],
        },
        "readiness": {
            "maturity_ceiling": "physics_ready",
            "qualification_required": True,
            "runtime_validation_performed": False,
            "missing_fields": ["real-px4-gazebo-roundtrip"],
            "evidence_paths": [],
        },
        "semantic_layers": [
            "navigation",
            "collision",
            "buildings",
            "roads",
            "vegetation",
            "restricted-regions",
        ],
        "capabilities": ["gazebo", "semantic-map", "content-addressed"],
        "dependencies": [],
        "license_expression": "CC-BY-4.0",
    }
    ir_payload = (
        json.dumps(asset_ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    ir_file = {
        "path": "normalized/asset-ir.json",
        "role": "asset_ir",
        "media_type": "application/json",
        "sha256": sha256_bytes(ir_payload),
        "size_bytes": len(ir_payload),
    }
    manifest = {
        "schema_version": "dronedream.ddpkg.v1",
        "package_id": f"{config['asset_id']}.1.0.0",
        "asset_id": config["asset_id"],
        "asset_kind": "map",
        "asset_ir_path": "normalized/asset-ir.json",
        "content_sha256": package_content_sha256([*files, ir_file]),
        "files": [*files, ir_file],
        "qualification": None,
        "created_at": "2026-10-27T00:00:00Z",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as bundle:
        for path, payload in sorted(payloads.items()):
            info = zipfile.ZipInfo(path, date_time=ARCHIVE_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, payload)
        for path, payload in (
            ("normalized/asset-ir.json", ir_payload),
            (
                "manifest.json",
                (
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                ).encode(),
            ),
        ):
            info = zipfile.ZipInfo(path, date_time=ARCHIVE_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, payload)
    return {"sha256": sha256_file(destination), "content_sha256": manifest["content_sha256"]}


def build_map(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    paths, georef = acquire_sources(config, args.cache_root, refresh=args.refresh)
    origin = (georef["origin_easting_m"], georef["origin_northing_m"])
    buildings = load_buildings(paths["buildings"], config, origin)
    trees, tree_source_count = load_trees(paths["trees"], config, origin)
    forests = load_regions(paths["forest"], config, origin)
    graph = load_road_graph(paths["roads"], config, origin, buildings, trees)
    sources = {
        "retrieved_at": "2026-10-27",
        "city_data_license": "CC-BY-4.0",
        "city_data_owner": "City of Helsinki",
        "building_register_url": CITY_WFS,
        "road_register_url": CITY_WFS,
        "tree_register_url": CITY_WFS,
        "ecological_network_url": CITY_WFS,
        "orthophoto_url": CITY_WMS,
        "orthophoto_layer": ORTHOPHOTO_LAYER,
        "subject_source_page": config["source_page"],
        **{f"{name}_sha256": sha256_file(path) for name, path in paths.items()},
    }
    map_root = args.backend_assets / config["key"] / "gazebo"
    if map_root.parent.exists():
        shutil.rmtree(map_root.parent)
    texture = map_root / "materials" / "textures" / f"{config['key']}-orthophoto.jpg"
    texture.parent.mkdir(parents=True, exist_ok=True)
    Image.open(paths["orthophoto"]).convert("RGB").save(texture, "JPEG", quality=91, optimize=True)
    mesh, material = building_mesh(buildings, config["key"])
    write_text(map_root / "meshes" / f"{config['key']}-buildings.obj", mesh)
    write_text(map_root / "meshes" / f"{config['key']}-buildings.mtl", material)
    write_text(map_root / "meshes" / f"{config['key']}-ground.obj", ground_mesh(config))
    write_text(map_root / "world.sdf", sdf_text(config, buildings, trees))
    write_text(map_root / "world.physics.sdf", sdf_text(config, buildings, trees))
    write_text(map_root / "model.sdf", sdf_text(config, buildings, trees, model_only=True))
    write_text(
        map_root / "model.config",
        '<?xml version="1.0"?>\n'
        f"<model><name>{config['name']}</name><version>1.0.0</version>"
        '<sdf version="1.9">model.sdf</sdf><author>'
        "<name>DroneDream; City of Helsinki</name></author>"
        f"<description>{config['description']}</description></model>\n",
    )
    semantic = semantic_contract(config, georef, buildings, trees, forests, graph, sources)
    write_json(map_root / "semantic.json", semantic)
    write_json(
        map_root / "collision-primitives.json", {"primitives": semantic["collision_primitives"]}
    )
    navigation = {
        "schema_version": "dronedream.map-graph.v1",
        "asset_id": config["asset_id"],
        "name": config["name"],
        "coordinate_frame": "map_enu",
        "named_entities": {
            "launch": graph["launch"]["node_id"],
            "outdoor_handoff": graph["handoff"]["node_id"],
            **{
                f"building-{item['building_id']}-outdoor-handoff": item["node_id"]
                for item in graph["building_handoffs"]
            },
        },
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }
    write_json(map_root.parent / "navigation-graph.json", navigation)
    summary = {
        "schema_version": "dronedream.helsinki-map-summary.v1",
        "asset_id": config["asset_id"],
        "name": config["name"],
        "source_kind": "real-geospatial-data",
        "visual_primitive_count": len(buildings) + 1,
        "collision_primitive_count": len(buildings) + len(trees) + 1,
        "building_count": len(buildings),
        "building_handoff_count": len(graph["building_handoffs"]),
        "tree_collision_count": len(trees),
        "tree_source_count": tree_source_count,
        "road_node_count": len(graph["nodes"]),
        "road_edge_count": len(graph["edges"]),
        "forest_region_count": len(forests),
        "bounds_m": {"x": config["width_m"], "y": config["height_m"], "z": config["ceiling_m"]},
        "resolution_m": config["resolution_m"],
        "fidelity": semantic["fidelity"],
        "sources": sources,
    }
    write_json(map_root / "summary.json", summary)
    write_text(
        map_root / "README.md",
        f"# {config['name']} runtime map\n\n"
        "This exterior-only local-ENU map is generated from City of Helsinki "
        "building, road, tree, ecological-network, and "
        f"{ORTHOPHOTO_LAYER} data under CC BY 4.0. Buildings use registered "
        "footprints and addresses; launch and handoff points are selected on "
        "the official road network. No indoor geometry or unverified doorway "
        "location is claimed.\n",
    )
    geometry_path = args.frontend_public / "asset-geometry" / "maps" / f"{config['key']}.json"
    preview_path = args.frontend_public / "asset-previews" / "maps" / f"{config['key']}.webp"
    source_preview = (
        args.frontend_public / "asset-previews" / "maps" / f"{config['key']}-source.jpg"
    )
    write_json(geometry_path, frontend_geometry(config, buildings, trees, forests, graph))
    source_preview.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(texture, source_preview)
    render_preview(config, source_preview, buildings, graph, preview_path)
    package_path = args.agent_core_assets / f"{config['key']}.ddpkg"
    package = build_ddpkg(config, map_root.parent, package_path)
    return {**config, **package, **summary, "package_file": package_path.name, "source": sources}


def catalog_resource(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "dronedream.map-resource.v1",
        "resource_id": item["resource_id"],
        "display_name": {"zh-CN": item["name_zh"], "en-US": item["name"]},
        "aliases": {"zh-CN": [item["name_zh"]], "en-US": [item["name"]]},
        "description": {"zh-CN": item["description_zh"], "en-US": item["description"]},
        "category": item["category"],
        "default_resource": True,
        "install_mode": "bundled",
        "review": {
            "status": "approved",
            "reviewed_at": "2026-10-27",
            "source_commit_pinned": False,
            "source_data_hashes_pinned": True,
            "license_reviewed": True,
            "executable_content_required": False,
        },
        "license": {
            "spdx_id": "CC-BY-4.0",
            "name": "City of Helsinki open data CC BY 4.0",
            "commercial_use": True,
            "redistribution": True,
            "automated_analysis": True,
            "attribution_required": True,
        },
        "source": {
            "source_type": "bundled_ddpkg",
            "location": f"dronedream://default-assets/{item['package_file']}",
            "expected_sha256": item["sha256"],
            "source_format": "dronedream-ddpkg",
            "expected_kind": "map",
            "real_world_crs": "EPSG:3879",
        },
        "analysis": {
            "status": "physics_ready",
            "asset_id": item["asset_id"],
            "parser": "dronedream.helsinki-open-data-map.v1",
            "building_count": item["building_count"],
            "building_handoff_count": item["building_handoff_count"],
            "collision_primitive_count": item["collision_primitive_count"],
            "visual_primitive_count": item["visual_primitive_count"],
            "road_node_count": item["road_node_count"],
            "road_edge_count": item["road_edge_count"],
            "tree_collision_count": item["tree_collision_count"],
            "forest_region_count": item["forest_region_count"],
            "coordinate_frame": "ENU",
            "bounds_m": item["bounds_m"],
            "resolution_m": item["resolution_m"],
            "origin": {
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "altitude_m": 0,
            },
            "source_page": item["source_page"],
        },
        "readiness": {
            "catalog": "ready",
            "planning": "ready",
            "simulation": "pending-runtime-validation",
            "flight": "pending-qualification",
            "qualification_id": None,
            "required_inputs": ["real-px4-gazebo-roundtrip"],
        },
    }


def update_preview_manifest(public_root: Path, resources: list[dict[str, Any]]) -> None:
    path = public_root / "asset-previews" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    generated_paths = {f"maps/{resource['key']}.webp" for resource in resources} | {
        f"maps/{resource['key']}-source.jpg" for resource in resources
    }
    retained = [entry for entry in manifest["files"] if entry["path"] not in generated_paths]
    generated = []
    for relative in sorted(generated_paths):
        candidate = public_root / "asset-previews" / relative
        generated.append(
            {
                "path": relative,
                "bytes": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
            }
        )
    manifest["generator"] = "tools/build-helsinki-maps.py"
    manifest["sources"]["maps"] = {
        "project": "City of Helsinki Open Data",
        "retrieved_at": "2026-10-27",
        "license": "CC-BY-4.0",
    }
    manifest["files"] = sorted([*retained, *generated], key=lambda entry: entry["path"])
    write_json(path, manifest)


def main() -> None:
    args = parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    selected = [
        entry for entry in payload["maps"] if not args.map_key or entry["key"] in set(args.map_key)
    ]
    if not selected:
        raise ValueError("No configured map matched --map")
    resources = [catalog_resource(build_map(entry, args)) for entry in selected]
    write_json(
        args.catalog_output,
        {
            "schema_version": "dronedream.generated-map-resources.v1",
            "generated_at": "2026-10-27",
            "resources": resources,
        },
    )
    update_preview_manifest(args.frontend_public, selected)
    print(
        json.dumps(
            {
                "maps": [
                    {
                        "resource_id": item["resource_id"],
                        "buildings": item["analysis"]["building_count"],
                        "roads": item["analysis"]["road_edge_count"],
                    }
                    for item in resources
                ]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
