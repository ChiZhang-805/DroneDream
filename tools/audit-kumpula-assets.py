#!/usr/bin/env python3
"""Audit the Kumpula exterior map and pinned PX4 X500-depth model closure.

This audit deliberately distinguishes release-blocking defects from disclosed
fidelity limits.  Passing it means that the shipped outdoor mission assets are
internally complete and consistent; it does not claim interiors, terrain
relief, facade detail, vegetation, or additional qualified routes.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

MAXIMUM_COLLISION_OVERCOVERAGE_RATIO = 3.0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-root", required=True, type=Path)
    parser.add_argument("--navigation-graph", required=True, type=Path)
    parser.add_argument("--px4-model-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


class Audit:
    """Collect deterministic checks, warnings, and measurements."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.measurements: dict[str, Any] = {}

    def require(self, condition: bool, name: str, detail: str) -> None:
        self.checks.append({"name": name, "passed": bool(condition), "detail": detail})

    def report(self) -> dict[str, Any]:
        failures = [check for check in self.checks if not check["passed"]]
        return {
            "schema_version": "dronedream.kumpula-asset-quality-audit.v1",
            "status": "verified" if not failures else "failed",
            "checks": self.checks,
            "failures": failures,
            "warnings": self.warnings,
            "measurements": self.measurements,
        }


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _jpeg_dimensions(path: Path) -> tuple[int, int]:
    """Read JPEG dimensions without adding a release-time imaging dependency."""

    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"{path} is not a JPEG")
    offset = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            break
        if marker in sof:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        offset += length
    raise ValueError(f"{path} has no JPEG size marker")


def _obj_metrics(path: Path) -> dict[str, Any]:
    vertices: list[tuple[float, float, float]] = []
    group = "ungrouped"
    faces: dict[str, list[tuple[int, ...]]] = defaultdict(list)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("v "):
            xyz = tuple(float(value) for value in line.split()[1:4])
            vertices.append((xyz[0], xyz[1], xyz[2]))
        elif line.startswith("g "):
            group = line[2:].strip()
        elif line.startswith("f "):
            indices = tuple(int(value.split("/")[0]) - 1 for value in line.split()[1:])
            faces[group].append(indices)
    invalid_indices = 0
    degenerate_faces = 0
    nonmanifold_edges = 0
    footprint_areas: dict[str, float] = {}
    for group_faces in faces.values():
        edges: Counter[tuple[int, int]] = Counter()
        for face in group_faces:
            if len(set(face)) < 3:
                degenerate_faces += 1
            for index in face:
                if index < 0 or index >= len(vertices):
                    invalid_indices += 1
            for index, start in enumerate(face):
                end = face[(index + 1) % len(face)]
                edges[tuple(sorted((start, end)))] += 1
        nonmanifold_edges += sum(count != 2 for count in edges.values())
    for group_name, group_faces in faces.items():
        referenced = {index for face in group_faces for index in face}
        maximum_z = max(vertices[index][2] for index in referenced)
        area = 0.0
        for face in group_faces:
            points = [vertices[index] for index in face]
            if not all(math.isclose(point[2], maximum_z, abs_tol=1e-8) for point in points):
                continue
            area += abs(
                sum(
                    points[index][0] * points[(index + 1) % len(points)][1]
                    - points[(index + 1) % len(points)][0] * points[index][1]
                    for index in range(len(points))
                )
            ) / 2
        footprint_areas[group_name] = area
    return {
        "vertices": len(vertices),
        "faces": sum(len(value) for value in faces.values()),
        "groups": len(faces),
        "invalid_indices": invalid_indices,
        "degenerate_faces": degenerate_faces,
        "nonmanifold_edges": nonmanifold_edges,
        "footprint_areas_m2": footprint_areas,
    }


def _audit_map(audit: Audit, root: Path, graph_path: Path) -> None:
    required = {
        "model.sdf",
        "world.sdf",
        "world.physics.sdf",
        "world.perception.sdf",
        "semantic.json",
        "collision-primitives.json",
        "qualification-evidence.json",
        "meshes/kumpula-buildings.obj",
        "meshes/kumpula-buildings.mtl",
        "meshes/kumpula-ground.obj",
        "materials/textures/kumpula-orthophoto.jpg",
    }
    missing = sorted(name for name in required if not (root / name).is_file())
    audit.require(not missing, "map.file-closure", f"missing={missing}")

    width, height = _jpeg_dimensions(root / "materials/textures/kumpula-orthophoto.jpg")
    audit.measurements["orthophoto_pixels"] = {"width": width, "height": height}
    audit.require((width, height) == (2048, 2048), "map.orthophoto-resolution", f"{width}x{height}")

    mesh = _obj_metrics(root / "meshes/kumpula-buildings.obj")
    footprint_areas = mesh.pop("footprint_areas_m2")
    audit.measurements["building_mesh"] = mesh
    audit.require(mesh["groups"] == 42, "map.building-mesh-count", str(mesh["groups"]))
    audit.require(mesh["invalid_indices"] == 0, "map.obj-indices", str(mesh["invalid_indices"]))
    audit.require(
        mesh["degenerate_faces"] == 0, "map.obj-degenerate-faces", str(mesh["degenerate_faces"])
    )
    audit.require(
        mesh["nonmanifold_edges"] == 0, "map.obj-watertight", str(mesh["nonmanifold_edges"])
    )

    collision = _json(root / "collision-primitives.json").get("primitives", [])
    collision_names = [item.get("name") for item in collision]
    positive = all(
        isinstance(item, dict)
        and all(
            isinstance(item.get(key), (int, float))
            and not isinstance(item.get(key), bool)
            and math.isfinite(float(item[key]))
            and float(item[key]) > 0
            for key in ("size_x", "size_y", "size_z")
        )
        for item in collision
    )
    audit.require(len(collision) == 44, "map.collision-count", str(len(collision)))
    audit.require(
        len(collision_names) == len(set(collision_names)), "map.collision-names", "unique"
    )
    audit.require(positive, "map.collision-dimensions", "finite and positive")
    overcoverage_ratios = sorted(
        float(item["size_x"]) * float(item["size_y"])
        / footprint_areas[str(item["name"]).removesuffix("-collision")]
        for item in collision
        if item.get("semantic") == "building"
    )
    audit.measurements["collision_overcoverage_ratio"] = {
        "minimum": overcoverage_ratios[0],
        "median": overcoverage_ratios[len(overcoverage_ratios) // 2],
        "maximum": overcoverage_ratios[-1],
    }
    audit.require(
        len(overcoverage_ratios) == 42
        and overcoverage_ratios[-1] <= MAXIMUM_COLLISION_OVERCOVERAGE_RATIO,
        "map.collision-overcoverage",
        f"maximum={overcoverage_ratios[-1]:.3f}",
    )

    for sdf_name in ("model.sdf", "world.sdf", "world.physics.sdf", "world.perception.sdf"):
        document = ElementTree.parse(root / sdf_name)
        unresolved: list[str] = []
        for uri_node in document.findall(".//uri"):
            uri = (uri_node.text or "").strip()
            if uri and "://" not in uri and not (root / uri).is_file():
                unresolved.append(uri)
        audit.require(not unresolved, f"map.{sdf_name}.uri-closure", f"unresolved={unresolved}")

    semantic = _json(root / "semantic.json")
    fidelity = semantic.get("fidelity", {})
    audit.require(
        fidelity
        == {
            "building_collisions": "conservative-oriented-boxes",
            "building_visuals": "city-footprint-extrusions",
            "interior_geometry": False,
            "qualified_routes": 1,
            "scope": "outdoor-exterior-only",
            "terrain": "flat-orthophoto-plane",
        },
        "map.fidelity-disclosure",
        json.dumps(fidelity, sort_keys=True),
    )
    entities = semantic.get("entities", [])
    ids = [entity.get("entity_id") for entity in entities]
    audit.require(len(ids) == len(set(ids)), "map.semantic-ids", "unique")
    required_names = {"Chemicum", "Dynamicum", "Exactum", "Physicum"}
    buildings = [entity for entity in entities if entity.get("name") in required_names]
    positions = {
        tuple(float(entity["position_m"][axis]) for axis in ("x", "y", "z")) for entity in buildings
    }
    audit.require(
        {item.get("name") for item in buildings} == required_names,
        "map.named-buildings",
        "four required names",
    )
    audit.require(len(positions) == 4, "map.named-building-positions", "four distinct centroids")
    audit.require(
        all(
            item.get("name_zh") and any(not alias.isascii() for alias in item.get("aliases", []))
            for item in buildings
        ),
        "map.bilingual-building-semantics",
        "Chinese display names and aliases",
    )

    graph = _json(graph_path)
    nodes = graph.get("nodes", [])
    node_by_id = {node["node_id"]: node for node in nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    distances_valid = True
    for edge in graph.get("edges", []):
        start_id, end_id = edge["from_node"], edge["to_node"]
        adjacency[start_id].add(end_id)
        if edge.get("bidirectional"):
            adjacency[end_id].add(start_id)
        start, end = node_by_id[start_id]["position_m"], node_by_id[end_id]["position_m"]
        actual = math.dist(tuple(start[axis] for axis in "xyz"), tuple(end[axis] for axis in "xyz"))
        distances_valid &= math.isclose(actual, float(edge["distance_m"]), abs_tol=1e-6)
    reached: set[str] = set()
    queue = deque([nodes[0]["node_id"]] if nodes else [])
    while queue:
        current = queue.popleft()
        if current in reached:
            continue
        reached.add(current)
        queue.extend(adjacency[current] - reached)
    audit.require(
        bool(nodes) and reached == set(node_by_id),
        "map.navigation-connected",
        f"{len(reached)}/{len(nodes)}",
    )
    audit.require(distances_valid, "map.navigation-distances", "match node geometry")

    audit.warnings.extend(
        [
            "Exterior-only asset: no rooms, doors, indoor connectivity, "
            "or interior collision geometry.",
            "Flat terrain plane: no elevation relief.",
            "Building visuals are footprint extrusions, not photorealistic facade/roof models.",
            "One conservative oriented collision box per building can over-block "
            "concave footprint space.",
            "Only one outdoor route is runtime-qualified.",
        ]
    )


def _resolve_model_uri(model_root: Path, current_model: Path, uri: str) -> Path | None:
    value = uri.strip()
    if value.startswith("model://"):
        parts = value.removeprefix("model://").split("/", 1)
        target = model_root / parts[0]
        return target / parts[1] if len(parts) == 2 else target / "model.sdf"
    if value.startswith("file://"):
        return None
    direct_model = model_root / value / "model.sdf"
    if direct_model.is_file():
        return direct_model
    return current_model.parent / value


def _audit_vehicle(audit: Audit, model_root: Path) -> None:
    pending = deque([model_root / "x500_depth" / "model.sdf"])
    visited: set[Path] = set()
    unresolved: list[str] = []
    sensors: set[str] = set()
    link_masses: list[float] = []
    collisions = visuals = motor_plugins = 0
    while pending:
        sdf_path = pending.popleft()
        sdf_path = sdf_path.resolve()
        if sdf_path in visited:
            continue
        visited.add(sdf_path)
        if not sdf_path.is_file():
            unresolved.append(str(sdf_path))
            continue
        document = ElementTree.parse(sdf_path)
        sensors.update(node.get("type", "") for node in document.findall(".//sensor"))
        collisions += len(document.findall(".//collision"))
        visuals += len(document.findall(".//visual"))
        motor_plugins += len(
            document.findall(".//plugin[@filename='gz-sim-multicopter-motor-model-system']")
        )
        for link in document.findall(".//link"):
            mass = link.findtext("inertial/mass")
            if mass is not None:
                link_masses.append(float(mass))
            inertia = link.find("inertial/inertia")
            if inertia is not None:
                for key in ("ixx", "iyy", "izz"):
                    value = inertia.findtext(key)
                    audit.require(
                        value is not None and float(value) > 0,
                        f"vehicle.inertia.{sdf_path.parent.name}.{link.get('name')}.{key}",
                        str(value),
                    )
        for include in document.findall(".//include/uri"):
            target = _resolve_model_uri(model_root, sdf_path, include.text or "")
            if target is not None:
                pending.append(target)
        for uri in document.findall(".//geometry/mesh/uri"):
            target = _resolve_model_uri(model_root, sdf_path, uri.text or "")
            if target is not None and not target.is_file():
                unresolved.append(str(target))
    audit.measurements["vehicle_runtime_closure"] = {
        "model_documents": len(visited),
        "total_mass_kg": sum(link_masses),
        "collisions": collisions,
        "visuals": visuals,
        "motor_plugins": motor_plugins,
        "sensor_types": sorted(sensors),
    }
    audit.require(not unresolved, "vehicle.runtime-uri-closure", f"unresolved={unresolved}")
    audit.require(len(visited) == 4, "vehicle.model-closure", f"documents={len(visited)}")
    audit.require(
        all(mass > 0 and math.isfinite(mass) for mass in link_masses),
        "vehicle.masses",
        str(link_masses),
    )
    audit.require(
        collisions >= 10 and visuals >= 17,
        "vehicle.geometry",
        f"collisions={collisions}, visuals={visuals}",
    )
    audit.require(motor_plugins == 4, "vehicle.motor-count", str(motor_plugins))
    audit.require(
        {"air_pressure", "magnetometer", "imu", "navsat", "camera", "depth_camera"}.issubset(
            sensors
        ),
        "vehicle.sensor-suite",
        ",".join(sorted(sensors)),
    )


def main() -> None:
    args = _arguments()
    audit = Audit()
    _audit_map(audit, args.map_root, args.navigation_graph)
    if args.px4_model_root is not None:
        _audit_vehicle(audit, args.px4_model_root)
    else:
        audit.warnings.append(
            "PX4 Runtime model closure was not audited because --px4-model-root was omitted."
        )
    report = audit.report()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    raise SystemExit(0 if report["status"] == "verified" else 1)


if __name__ == "__main__":
    main()
