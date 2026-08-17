from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.autonomy.catalog import get_bundled_map_manifest
from app.autonomy.qualification import MapPackQualificationRequest, qualify_map_pack
from app.autonomy.school_map_artifact import (
    ROUTE_ENDPOINT_TOLERANCE_M,
    STRUCTURAL_TOLERANCE_M,
    export_school_map_gazebo_artifact,
    get_school_map_gazebo_artifact,
    school_map_collision_primitives,
)


def _bounds(primitive: object, axis: str) -> tuple[float, float]:
    center = getattr(primitive, f"center_{axis}")
    size = getattr(primitive, f"size_{axis}")
    return center - size / 2, center + size / 2


def test_school_map_exports_parseable_content_addressed_sdf() -> None:
    artifact = get_school_map_gazebo_artifact()
    root = ElementTree.fromstring(artifact.model_sdf)
    links = root.findall("./model/link")

    assert root.attrib["version"] == "1.9"
    assert root.findtext("./model/static") == "true"
    assert len(links) == artifact.summary["collision_primitive_count"]
    assert len({link.attrib["name"] for link in links}) == len(links)
    assert all(link.find("./collision/geometry/box/size") is not None for link in links)
    assert all(link.find("./visual/geometry/box/size") is not None for link in links)
    assert (
        hashlib.sha256(artifact.model_sdf.encode()).hexdigest()
        == artifact.summary["model_sdf_sha256"]
    )
    assert (
        hashlib.sha256(artifact.semantic_json.encode()).hexdigest()
        == artifact.summary["semantic_sha256"]
    )
    assert artifact.summary["gazebo_asset_contract_generated"] is True
    assert artifact.summary["gazebo_runtime_verified"] is False
    assert artifact.summary["simulation_execution_ready"] is False


def test_school_map_export_materializes_digest_bound_files(tmp_path: Path) -> None:
    output_directory = tmp_path / "school-map"
    hashes = export_school_map_gazebo_artifact(output_directory)

    assert set(hashes) == {"model.sdf", "semantic.json", "summary.json"}
    assert ElementTree.fromstring((output_directory / "model.sdf").read_text()).tag == "sdf"
    assert json.loads((output_directory / "semantic.json").read_text())["name"] == "School Map"


def test_school_map_stairs_share_exact_tread_landing_and_floor_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    tolerance = STRUCTURAL_TOLERANCE_M

    for storey in (1, 2):
        first_last = primitives[f"teaching-stair-{storey}-a-12"]
        second_first = primitives[f"teaching-stair-{storey}-b-1"]
        second_last = primitives[f"teaching-stair-{storey}-b-12"]
        middle = primitives[f"teaching-stair-{storey}-mid-landing"]
        upper = primitives[f"teaching-stair-{storey}-upper-landing"]

        assert abs(_bounds(first_last, "y")[1] - _bounds(middle, "y")[0]) <= tolerance
        assert abs(_bounds(second_first, "y")[1] - _bounds(middle, "y")[0]) <= tolerance
        assert abs(_bounds(first_last, "z")[1] - _bounds(middle, "z")[1]) <= tolerance
        assert abs(_bounds(second_first, "z")[0] - _bounds(middle, "z")[1]) <= tolerance
        assert abs(_bounds(second_last, "y")[0] - _bounds(upper, "y")[1]) <= tolerance
        assert abs(_bounds(second_last, "z")[1] - _bounds(upper, "z")[1]) <= tolerance

    stair_treads = [
        primitive for primitive in primitives.values() if primitive.semantic == "stair-tread"
    ]
    assert len(stair_treads) == 72
    assert "cafeteria-stair-1-upper-landing" in primitives
    assert all(
        f"cafeteria-floor-2-{side}" in primitives for side in ("west", "east", "south", "north")
    )


def test_school_map_semantic_road_graph_reaches_every_facility() -> None:
    semantic = json.loads(get_school_map_gazebo_artifact().semantic_json)
    roads = semantic["roads"]

    def key(point: list[float]) -> tuple[float, float]:
        return (round(point[0], 3), round(point[1], 3))

    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for segment in roads["segments"]:
        assert segment["width_m"] >= 4.8
        for start, end in zip(segment["points"][:-1], segment["points"][1:], strict=True):
            a, b = key(start), key(end)
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
    start = key(roads["facility_anchors"]["campus-gate"])
    visited: set[tuple[float, float]] = set()
    pending = [start]
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(adjacency.get(node, ()))
    for anchor in roads["facility_anchors"].values():
        exact = min(
            (abs(node[0] - anchor[0]) + abs(node[1] - anchor[1]) for node in visited),
            default=float("inf"),
        )
        assert exact <= ROUTE_ENDPOINT_TOLERANCE_M


def test_school_map_facility_columns_share_canopy_bottom_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    bike_roof_bottom = _bounds(primitives["bike-shelter-roof"], "z")[0]
    pickup_roof_bottom = _bounds(primitives["pickup-canopy"], "z")[0]

    for primitive in primitives.values():
        if primitive.name.startswith("bike-shelter-column-"):
            assert abs(_bounds(primitive, "z")[1] - bike_roof_bottom) <= STRUCTURAL_TOLERANCE_M
        if primitive.name.startswith("pickup-column-"):
            assert abs(_bounds(primitive, "z")[1] - pickup_roof_bottom) <= STRUCTURAL_TOLERANCE_M
    assert len([name for name in primitives if name.endswith("-pole")]) == 22
    assert len([name for name in primitives if name.endswith("-arm")]) == 22


def test_road_endpoints_share_entrance_step_and_threshold_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    semantic = json.loads(get_school_map_gazebo_artifact().semantic_json)

    teaching_steps = [primitives[f"teaching-entry-step-{index}"] for index in range(1, 5)]
    cafeteria_steps = [primitives[f"cafeteria-entry-step-{index}"] for index in range(1, 3)]
    for steps, facility, threshold_name in (
        (teaching_steps, "teaching-building", "teaching-entry-threshold"),
        (cafeteria_steps, "cafeteria", "cafeteria-entry-threshold"),
    ):
        road_end = semantic["roads"]["facility_anchors"][facility][1]
        assert abs(_bounds(steps[0], "y")[0] - road_end) <= ROUTE_ENDPOINT_TOLERANCE_M
        for current, following in zip(steps[:-1], steps[1:], strict=True):
            assert (
                abs(_bounds(current, "y")[1] - _bounds(following, "y")[0]) <= STRUCTURAL_TOLERANCE_M
            )
        threshold = primitives[threshold_name]
        assert (
            abs(_bounds(steps[-1], "y")[1] - _bounds(threshold, "y")[0]) <= STRUCTURAL_TOLERANCE_M
        )
        assert (
            abs(_bounds(steps[-1], "z")[1] - _bounds(threshold, "z")[1]) <= STRUCTURAL_TOLERANCE_M
        )


def test_school_map_manifest_and_qualification_bind_unverified_gazebo_contract() -> None:
    manifest = get_bundled_map_manifest("school-campus-v1")
    assert manifest is not None
    assert manifest["gazebo_artifact"] == get_school_map_gazebo_artifact().summary

    payload = {
        "name": "School Map",
        "pack_id": "map-school",
        "version": 1,
        "compiler_scene_id": "school-campus-v1",
        "representation": "hybrid-3d",
        "coordinate_frame": "ENU",
        "resolution_m": 0.05,
        "floor_count": 3,
        "bounds_m": {"x": 120, "y": 90, "z": 12.6},
        "origin": {"latitude": None, "longitude": None, "altitude_m": None},
        "live_updates": "depth-fusion",
        "calibrated": True,
        "confidence_percent": 100,
        "semantic_layers": manifest["semantic_layers"],
        "planning_layers": manifest["planning_layers"],
        "source_asset_receipt_ids": [],
    }
    receipt = qualify_map_pack(MapPackQualificationRequest.model_validate(payload))

    assert receipt.status == "qualified"
    assert receipt.manifest_sha256 == manifest["manifest_sha256"]
    assert {issue.code for issue in receipt.issues} == {"map.gazebo-runtime.not-verified"}


@pytest.mark.parametrize("floor", [1, 2, 3])
def test_teaching_walls_share_slab_and_next_interface_planes(floor: int) -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    wall = primitives[f"teaching-north-{floor}"]
    slab_top = (floor - 1) * 3.6 + 0.22
    next_interface = floor * 3.6

    assert abs(_bounds(wall, "z")[0] - slab_top) <= STRUCTURAL_TOLERANCE_M
    assert abs(_bounds(wall, "z")[1] - next_interface) <= STRUCTURAL_TOLERANCE_M


@pytest.mark.parametrize(
    ("building", "floor_count"),
    [("teaching", 3), ("cafeteria", 2)],
)
def test_exterior_wall_corners_butt_without_gap_or_volume_overlap(
    building: str,
    floor_count: int,
) -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}

    for floor in range(1, floor_count + 1):
        north = primitives[f"{building}-north-{floor}"]
        west = primitives[f"{building}-west-{floor}"]
        south_name = (
            f"{building}-south-{floor}-west"
            if building == "teaching" and floor == 1
            else "cafeteria-south-1-west"
            if building == "cafeteria" and floor == 1
            else f"{building}-south-{floor}"
        )
        south = primitives[south_name]

        assert abs(_bounds(west, "y")[1] - _bounds(north, "y")[0]) <= STRUCTURAL_TOLERANCE_M
        assert abs(_bounds(west, "y")[0] - _bounds(south, "y")[1]) <= STRUCTURAL_TOLERANCE_M
