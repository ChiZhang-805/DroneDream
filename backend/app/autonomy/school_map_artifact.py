"""Deterministic School Map SDF and semantic-contract export.

The artifact is deliberately marked runtime-unverified.  It is a Gazebo-readable
static model and a content-addressed collision/semantic contract, not evidence of
a completed PX4/Gazebo smoke run.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

STRUCTURAL_TOLERANCE_M = 0.001
ROUTE_ENDPOINT_TOLERANCE_M = 0.01
FLOOR_SLAB_M = 0.22
STOREY_HEIGHT_M = 3.6
WALL_HEIGHT_M = STOREY_HEIGHT_M - FLOOR_SLAB_M
STAIR_RISERS_PER_FLIGHT = 12
STAIR_RISER_M = 0.15
STAIR_TREAD_M = 0.28
STAIR_WIDTH_M = 1.6
STAIR_LANE_GAP_M = 0.44
STAIR_LANDING_M = 1.6
STAIR_LANDING_THICKNESS_M = 0.18
TEACHING_ENTRANCE_CENTER_X = -25.0
TEACHING_ENTRANCE_OPENING_M = 8.46
ENTRANCE_DOOR_FRAME_WIDTH_M = 0.16
ENTRANCE_DOOR_FRAME_DEPTH_M = 0.11
ENTRANCE_DOOR_LEAF_WIDTH_M = 1.995
ENTRANCE_DOOR_LEAF_DEPTH_M = 0.095
ENTRANCE_DOOR_HEIGHT_M = 2.7
ENTRANCE_DOOR_OPEN_ANGLE_RAD = math.radians(78)
TEACHING_OPEN_DOOR_PAIR_CENTER_X = (
    TEACHING_ENTRANCE_CENTER_X - ENTRANCE_DOOR_FRAME_WIDTH_M / 2 - ENTRANCE_DOOR_LEAF_WIDTH_M
)
CAFETERIA_ENTRANCE_CENTER_X = 30.0
CAFETERIA_ENTRANCE_OPENING_M = 7.5
CAFETERIA_DOOR_GROUP_WIDTH_M = 3.59
CAFETERIA_DOOR_FRAME_WIDTH_M = 0.08
CAFETERIA_DOOR_FRAME_DEPTH_M = 0.11
CAFETERIA_DOOR_LEAF_DEPTH_M = 0.06
CAFETERIA_DOOR_HEIGHT_M = 2.65

ROAD_NETWORK = {
    "facility_anchors": {
        "campus-gate": [0.0, -43.0],
        "teaching-building": [-25.0, -1.055],
        "cafeteria": [30.0, 6.245],
        "takeout-pickup": [48.5, 1.5],
        "bicycle-shelter": [-42.0, 35.4],
        "tree-corridor": [0.0, -18.0],
    },
    "segments": [
        {"id": "campus-gate-spine", "width_m": 6.4, "points": [[0, -43], [0, -31], [0, -18]]},
        {
            "id": "campus-east-west-road",
            "width_m": 6.2,
            "points": [[-51, -18], [-25, -18], [0, -18], [8, -18], [30, -18], [52, -18]],
        },
        {
            "id": "teaching-entrance-road",
            "width_m": 5.4,
            "points": [[-25, -18], [-25, -9], [-25, -1.055]],
        },
        {
            "id": "cafeteria-entrance-road",
            "width_m": 5.4,
            "points": [[30, -18], [30, -6], [30, 1], [30, 6.245]],
        },
        {
            "id": "takeout-pickup-road",
            "width_m": 5.2,
            "points": [[30, -18], [39, -12], [46, -5], [48.5, 1.5]],
        },
        {
            "id": "west-bicycle-service-road",
            "width_m": 4.8,
            "points": [[-51, -18], [-55, -8], [-55, 24], [-51, 34], [-42, 35.4]],
        },
        {
            "id": "campus-courtyard-road",
            "width_m": 4.8,
            "points": [[8, -18], [8, -5], [8, 10], [8, 27], [8, 35.4], [-15, 35.4], [-42, 35.4]],
        },
        {
            "id": "north-cafeteria-service-road",
            "width_m": 4.8,
            "points": [[8, 35.4], [30, 35.4], [45, 35.4], [52, 28], [52, -18]],
        },
    ],
}


@dataclass(frozen=True)
class BoxPrimitive:
    name: str
    center_x: float
    center_y: float
    center_z: float
    size_x: float
    size_y: float
    size_z: float
    semantic: str
    yaw_rad: float = 0.0


@dataclass(frozen=True)
class SchoolMapGazeboArtifact:
    model_sdf: str
    semantic_json: str
    summary: dict[str, object]


def _box(
    name: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    semantic: str,
    yaw_rad: float = 0.0,
) -> BoxPrimitive:
    return BoxPrimitive(name, *center, *size, semantic, yaw_rad)


def _wall_span(floor: int) -> tuple[float, float]:
    bottom = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
    top = floor * STOREY_HEIGHT_M
    return (bottom + top) / 2, top - bottom


def _teaching_floor_primitives() -> list[BoxPrimitive]:
    result: list[BoxPrimitive] = []
    building_min_x, building_max_x = -53.0, 3.0
    building_min_y, building_max_y = 2.0, 24.0
    flight_run = STAIR_RISERS_PER_FLIGHT * STAIR_TREAD_M
    lane_offset = STAIR_WIDTH_M / 2 + STAIR_LANE_GAP_M / 2
    opening = {
        "min_x": -0.1 - lane_offset - STAIR_WIDTH_M / 2,
        "max_x": -0.1 + lane_offset + STAIR_WIDTH_M / 2,
        "min_y": 10.5 - flight_run / 2 - STAIR_LANDING_M,
        "max_y": 10.5 + flight_run / 2 + STAIR_LANDING_M,
    }
    for floor in range(1, 4):
        base_z = (floor - 1) * STOREY_HEIGHT_M
        if floor == 1:
            result.append(
                _box(
                    "teaching-floor-1-slab",
                    (-25, 13, FLOOR_SLAB_M / 2),
                    (56, 22, FLOOR_SLAB_M),
                    "floor",
                )
            )
        else:
            pieces = (
                ("west", building_min_x, opening["min_x"], building_min_y, building_max_y),
                ("east", opening["max_x"], building_max_x, building_min_y, building_max_y),
                ("south", opening["min_x"], opening["max_x"], building_min_y, opening["min_y"]),
                ("north", opening["min_x"], opening["max_x"], opening["max_y"], building_max_y),
            )
            for suffix, min_x, max_x, min_y, max_y in pieces:
                result.append(
                    _box(
                        f"teaching-floor-{floor}-slab-{suffix}",
                        ((min_x + max_x) / 2, (min_y + max_y) / 2, base_z + FLOOR_SLAB_M / 2),
                        (max_x - min_x, max_y - min_y, FLOOR_SLAB_M),
                        "floor",
                    )
                )
        center_z, height = _wall_span(floor)
        result.extend(
            (
                _box(
                    f"teaching-north-{floor}",
                    (-25, 24, center_z),
                    (56, 0.22, height),
                    "exterior-wall",
                ),
                _box(
                    f"teaching-west-{floor}",
                    (-53, 13, center_z),
                    (0.22, 21.78, height),
                    "exterior-wall",
                ),
                _box(
                    f"teaching-east-{floor}",
                    (3, 13, center_z),
                    (0.22, 21.78, height),
                    "exterior-wall",
                ),
            )
        )
        if floor == 1:
            side_width = (56 - TEACHING_ENTRANCE_OPENING_M) / 2
            result.extend(
                (
                    _box(
                        "teaching-south-1-west",
                        (-53 + side_width / 2, 2, center_z),
                        (side_width, 0.22, height),
                        "exterior-wall",
                    ),
                    _box(
                        "teaching-south-1-east",
                        (3 - side_width / 2, 2, center_z),
                        (side_width, 0.22, height),
                        "exterior-wall",
                    ),
                    _box(
                        "teaching-south-1-header",
                        (-25, 2, (2.92 + 3.6) / 2),
                        (TEACHING_ENTRANCE_OPENING_M, 0.22, 3.6 - 2.92),
                        "door-header",
                    ),
                )
            )
        else:
            result.append(
                _box(
                    f"teaching-south-{floor}",
                    (-25, 2, center_z),
                    (56, 0.22, height),
                    "exterior-wall",
                )
            )
    result.append(_box("teaching-roof", (-25, 13, 10.8 + 0.35 / 2), (56.8, 22.8, 0.35), "roof"))
    for step in range(4):
        height = (step + 1) * (FLOOR_SLAB_M / 4)
        result.append(
            _box(
                f"teaching-entry-step-{step + 1}",
                (-25, -1.055 + (step + 0.5) * 0.75, height / 2),
                (7.2, 0.75, height),
                "entrance-step",
            )
        )
    threshold_depth = (ENTRANCE_DOOR_FRAME_DEPTH_M - ENTRANCE_DOOR_LEAF_DEPTH_M) / 2
    threshold_center_y = 2.0 - ENTRANCE_DOOR_FRAME_DEPTH_M / 2 + threshold_depth / 2
    result.append(
        _box(
            "teaching-entry-threshold",
            (TEACHING_ENTRANCE_CENTER_X, threshold_center_y, FLOOR_SLAB_M - 0.01),
            (TEACHING_ENTRANCE_OPENING_M, threshold_depth, 0.02),
            "door-threshold",
        )
    )
    opening_half = TEACHING_ENTRANCE_OPENING_M / 2
    frame_half = ENTRANCE_DOOR_FRAME_WIDTH_M / 2
    door_center_height = FLOOR_SLAB_M + ENTRANCE_DOOR_HEIGHT_M / 2
    for suffix, frame_x in (
        (
            "west",
            TEACHING_ENTRANCE_CENTER_X - opening_half + frame_half,
        ),
        ("center", TEACHING_ENTRANCE_CENTER_X),
        (
            "east",
            TEACHING_ENTRANCE_CENTER_X + opening_half - frame_half,
        ),
    ):
        result.append(
            _box(
                f"teaching-entry-frame-{suffix}",
                (frame_x, 2.0, door_center_height),
                (
                    ENTRANCE_DOOR_FRAME_WIDTH_M,
                    ENTRANCE_DOOR_FRAME_DEPTH_M,
                    ENTRANCE_DOOR_HEIGHT_M,
                ),
                "door-frame",
            )
        )
    for index, hinge_x, direction in (
        (
            1,
            TEACHING_ENTRANCE_CENTER_X - opening_half + ENTRANCE_DOOR_FRAME_WIDTH_M,
            1,
        ),
        (2, TEACHING_ENTRANCE_CENTER_X - frame_half, -1),
    ):
        three_angle = direction * ENTRANCE_DOOR_OPEN_ANGLE_RAD
        local_center_x = direction * ENTRANCE_DOOR_LEAF_WIDTH_M / 2
        result.append(
            _box(
                f"teaching-entry-door-{index}-west-open",
                (
                    hinge_x + math.cos(three_angle) * local_center_x,
                    2.0 - math.sin(three_angle) * local_center_x,
                    door_center_height,
                ),
                (
                    ENTRANCE_DOOR_LEAF_WIDTH_M,
                    ENTRANCE_DOOR_LEAF_DEPTH_M,
                    ENTRANCE_DOOR_HEIGHT_M,
                ),
                "open-door-leaf",
                yaw_rad=-three_angle,
            )
        )
    for index, leaf_x in enumerate(
        (
            TEACHING_ENTRANCE_CENTER_X + frame_half + ENTRANCE_DOOR_LEAF_WIDTH_M / 2,
            TEACHING_ENTRANCE_CENTER_X + frame_half + ENTRANCE_DOOR_LEAF_WIDTH_M * 1.5,
        ),
        start=3,
    ):
        result.append(
            _box(
                f"teaching-entry-door-{index}-east-closed",
                (leaf_x, 2.0, door_center_height),
                (
                    ENTRANCE_DOOR_LEAF_WIDTH_M,
                    ENTRANCE_DOOR_LEAF_DEPTH_M,
                    ENTRANCE_DOOR_HEIGHT_M,
                ),
                "closed-door-leaf",
            )
        )
    return result


def _switchback_stair_primitives(
    prefix: str,
    center_x: float,
    center_y: float,
    storeys: tuple[int, ...],
) -> list[BoxPrimitive]:
    result: list[BoxPrimitive] = []
    run = STAIR_RISERS_PER_FLIGHT * STAIR_TREAD_M
    half_rise = STAIR_RISERS_PER_FLIGHT * STAIR_RISER_M
    lane_offset = STAIR_WIDTH_M / 2 + STAIR_LANE_GAP_M / 2
    total_width = STAIR_WIDTH_M * 2 + STAIR_LANE_GAP_M
    start_y = center_y - run / 2
    end_y = center_y + run / 2
    for storey in storeys:
        lower_z = (storey - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
        middle_z = lower_z + half_rise
        upper_z = lower_z + STOREY_HEIGHT_M
        for step in range(STAIR_RISERS_PER_FLIGHT):
            height = (step + 1) * STAIR_RISER_M
            result.append(
                _box(
                    f"{prefix}-stair-{storey}-a-{step + 1}",
                    (
                        center_x - lane_offset,
                        start_y + (step + 0.5) * STAIR_TREAD_M,
                        lower_z + height / 2,
                    ),
                    (STAIR_WIDTH_M, STAIR_TREAD_M, height),
                    "stair-tread",
                )
            )
            result.append(
                _box(
                    f"{prefix}-stair-{storey}-b-{step + 1}",
                    (
                        center_x + lane_offset,
                        end_y - (step + 0.5) * STAIR_TREAD_M,
                        middle_z + height / 2,
                    ),
                    (STAIR_WIDTH_M, STAIR_TREAD_M, height),
                    "stair-tread",
                )
            )
        result.extend(
            (
                _box(
                    f"{prefix}-stair-{storey}-mid-landing",
                    (
                        center_x,
                        end_y + STAIR_LANDING_M / 2,
                        middle_z - STAIR_LANDING_THICKNESS_M / 2,
                    ),
                    (total_width, STAIR_LANDING_M, STAIR_LANDING_THICKNESS_M),
                    "stair-landing",
                ),
                _box(
                    f"{prefix}-stair-{storey}-upper-landing",
                    (
                        center_x,
                        start_y - STAIR_LANDING_M / 2,
                        upper_z - STAIR_LANDING_THICKNESS_M / 2,
                    ),
                    (total_width, STAIR_LANDING_M, STAIR_LANDING_THICKNESS_M),
                    "stair-landing",
                ),
            )
        )
    return result


def _cafeteria_primitives() -> list[BoxPrimitive]:
    result: list[BoxPrimitive] = []
    run = STAIR_RISERS_PER_FLIGHT * STAIR_TREAD_M
    total_width = STAIR_WIDTH_M * 2 + STAIR_LANE_GAP_M
    opening = {
        "min_x": 40 - total_width / 2,
        "max_x": 40 + total_width / 2,
        "min_y": 20 - run / 2 - STAIR_LANDING_M,
        "max_y": 20 + run / 2 + STAIR_LANDING_M,
    }
    entrance_side_width = (34 - CAFETERIA_ENTRANCE_OPENING_M) / 2
    threshold_depth = (CAFETERIA_DOOR_FRAME_DEPTH_M - CAFETERIA_DOOR_LEAF_DEPTH_M) / 2
    threshold_center_y = 7.5 - CAFETERIA_DOOR_FRAME_DEPTH_M / 2 + threshold_depth / 2
    for floor in (1, 2):
        base_z = (floor - 1) * STOREY_HEIGHT_M
        center_z, height = _wall_span(floor)
        if floor == 1:
            result.append(
                _box(
                    "cafeteria-floor-1", (30, 20, FLOOR_SLAB_M / 2), (34, 25, FLOOR_SLAB_M), "floor"
                )
            )
        else:
            pieces = (
                ("west", 13.0, opening["min_x"], 7.5, 32.5),
                ("east", opening["max_x"], 47.0, 7.5, 32.5),
                ("south", opening["min_x"], opening["max_x"], 7.5, opening["min_y"]),
                ("north", opening["min_x"], opening["max_x"], opening["max_y"], 32.5),
            )
            for suffix, min_x, max_x, min_y, max_y in pieces:
                result.append(
                    _box(
                        f"cafeteria-floor-2-{suffix}",
                        ((min_x + max_x) / 2, (min_y + max_y) / 2, base_z + FLOOR_SLAB_M / 2),
                        (max_x - min_x, max_y - min_y, FLOOR_SLAB_M),
                        "floor",
                    )
                )
        result.extend(
            (
                _box(
                    f"cafeteria-north-{floor}",
                    (30, 32.5, center_z),
                    (34, 0.22, height),
                    "exterior-wall",
                ),
                _box(
                    f"cafeteria-west-{floor}",
                    (13, 20, center_z),
                    (0.22, 24.78, height),
                    "exterior-wall",
                ),
                _box(
                    f"cafeteria-east-{floor}",
                    (47, 20, center_z),
                    (0.22, 24.78, height),
                    "exterior-wall",
                ),
            )
        )
        if floor == 1:
            result.extend(
                (
                    _box(
                        "cafeteria-south-1-west",
                        (13 + entrance_side_width / 2, 7.5, center_z),
                        (entrance_side_width, 0.22, height),
                        "exterior-wall",
                    ),
                    _box(
                        "cafeteria-south-1-east",
                        (47 - entrance_side_width / 2, 7.5, center_z),
                        (entrance_side_width, 0.22, height),
                        "exterior-wall",
                    ),
                    _box(
                        "cafeteria-south-1-header",
                        (30, 7.5, (2.95 + 3.6) / 2),
                        (CAFETERIA_ENTRANCE_OPENING_M, 0.22, 3.6 - 2.95),
                        "door-header",
                    ),
                )
            )
        else:
            result.append(
                _box("cafeteria-south-2", (30, 7.5, center_z), (34, 0.22, height), "exterior-wall")
            )
    result.append(_box("cafeteria-roof", (30, 20, 7.2 + 0.35 / 2), (34.8, 25.8, 0.35), "roof"))
    result.extend(
        (
            _box(
                "cafeteria-entry-step-1",
                (30, 6.545, 0.055),
                (CAFETERIA_ENTRANCE_OPENING_M, 0.6, 0.11),
                "entrance-step",
            ),
            _box(
                "cafeteria-entry-step-2",
                (30, 7.145, 0.11),
                (CAFETERIA_ENTRANCE_OPENING_M, 0.6, 0.22),
                "entrance-step",
            ),
            _box(
                "cafeteria-entry-threshold",
                (30, threshold_center_y, 0.21),
                (CAFETERIA_ENTRANCE_OPENING_M, threshold_depth, 0.02),
                "door-threshold",
            ),
            _box(
                "cafeteria-entry-canopy",
                (30, 6.195, 3.1),
                (CAFETERIA_ENTRANCE_OPENING_M, 2.39, 0.28),
                "canopy",
            ),
        )
    )
    door_center_height = FLOOR_SLAB_M + CAFETERIA_DOOR_HEIGHT_M / 2
    door_group_offset = CAFETERIA_ENTRANCE_OPENING_M / 4
    for side, group_x in (
        ("west", CAFETERIA_ENTRANCE_CENTER_X - door_group_offset),
        ("east", CAFETERIA_ENTRANCE_CENTER_X + door_group_offset),
    ):
        for jamb, frame_x in (
            (
                "left",
                group_x - CAFETERIA_DOOR_GROUP_WIDTH_M / 2 - CAFETERIA_DOOR_FRAME_WIDTH_M / 2,
            ),
            (
                "right",
                group_x + CAFETERIA_DOOR_GROUP_WIDTH_M / 2 + CAFETERIA_DOOR_FRAME_WIDTH_M / 2,
            ),
        ):
            result.append(
                _box(
                    f"cafeteria-entry-frame-{side}-{jamb}",
                    (frame_x, 7.5, door_center_height),
                    (
                        CAFETERIA_DOOR_FRAME_WIDTH_M,
                        CAFETERIA_DOOR_FRAME_DEPTH_M,
                        CAFETERIA_DOOR_HEIGHT_M,
                    ),
                    "door-frame",
                )
            )
        result.append(
            _box(
                f"cafeteria-entry-frame-{side}-top",
                (
                    group_x,
                    7.5,
                    FLOOR_SLAB_M + CAFETERIA_DOOR_HEIGHT_M + CAFETERIA_DOOR_FRAME_WIDTH_M / 2,
                ),
                (
                    CAFETERIA_DOOR_GROUP_WIDTH_M,
                    CAFETERIA_DOOR_FRAME_DEPTH_M,
                    CAFETERIA_DOOR_FRAME_WIDTH_M,
                ),
                "door-frame",
            )
        )
        for leaf_index, leaf_x in enumerate(
            (
                group_x - CAFETERIA_DOOR_GROUP_WIDTH_M / 4,
                group_x + CAFETERIA_DOOR_GROUP_WIDTH_M / 4,
            ),
            start=1,
        ):
            result.append(
                _box(
                    f"cafeteria-entry-door-{side}-{leaf_index}-closed",
                    (leaf_x, 7.5, door_center_height),
                    (
                        CAFETERIA_DOOR_GROUP_WIDTH_M / 2,
                        CAFETERIA_DOOR_LEAF_DEPTH_M,
                        CAFETERIA_DOOR_HEIGHT_M,
                    ),
                    "closed-door-leaf",
                )
            )
    return result


def _facility_primitives() -> list[BoxPrimitive]:
    result = [
        _box("bike-shelter-roof", (-42, 30.2, 3.0), (18, 5.4, 0.22), "canopy"),
        _box("pickup-canopy", (48.5, 1.5, 2.8), (7.4, 4.2, 0.18), "canopy"),
        _box("pickup-shelf", (48.5, 2.3, 0.525), (5.9, 0.65, 1.05), "pickup-shelf"),
        _box("guard-booth", (7.8, -39.5, 1.55), (4.2, 3.2, 3.1), "guard-booth"),
    ]
    for column_x in (-8.4, -2.8, 2.8, 8.4):
        for column_y in (-2.3, 2.3):
            result.append(
                _box(
                    f"bike-shelter-column-{column_x:g}-{column_y:g}",
                    (-42 + column_x, 30.2 + column_y, 2.89 / 2),
                    (0.16, 0.16, 2.89),
                    "canopy-column",
                )
            )
    for column_x in (-3.35, 3.35):
        for column_y in (-1.65, 1.65):
            result.append(
                _box(
                    f"pickup-column-{column_x:g}-{column_y:g}",
                    (48.5 + column_x, 1.5 + column_y, 2.71 / 2),
                    (0.15, 0.15, 2.71),
                    "canopy-column",
                )
            )
    street_lights = [
        *((x, -14.4) for x in (-50, -40, -30, -15, -5, 15, 25, 40, 50)),
        *((x, -21.6) for x in (-50, -40, -30, -15, -5, 15, 25, 40, 50)),
        (4.8, -4),
        (11.2, 8),
        (4.8, 21),
        (11.2, 31),
    ]
    for index, (light_x, light_y) in enumerate(street_lights, start=1):
        result.extend(
            (
                _box(
                    f"street-light-{index}-base",
                    (light_x, light_y, 0.06),
                    (0.36, 0.36, 0.12),
                    "street-light-base",
                ),
                _box(
                    f"street-light-{index}-pole",
                    (light_x, light_y, (0.12 + 4.3) / 2),
                    (0.17, 0.17, 4.3 - 0.12),
                    "street-light-pole",
                ),
                _box(
                    f"street-light-{index}-arm",
                    (light_x + 0.5, light_y, 4.35),
                    (1.25, 0.1, 0.1),
                    "street-light-arm",
                ),
            )
        )
    return result


def school_map_collision_primitives() -> list[BoxPrimitive]:
    primitives = [
        _box("school-map-ground", (0, 0, -0.09), (120, 90, 0.18), "terrain"),
        *_teaching_floor_primitives(),
        *_switchback_stair_primitives("teaching", -0.1, 10.5, (1, 2)),
        *_cafeteria_primitives(),
        *_switchback_stair_primitives("cafeteria", 40, 20, (1,)),
        *_facility_primitives(),
    ]
    return primitives


def _sdf_for(primitives: list[BoxPrimitive]) -> str:
    sdf = ElementTree.Element("sdf", {"version": "1.9"})
    model = ElementTree.SubElement(sdf, "model", {"name": "school_map"})
    ElementTree.SubElement(model, "static").text = "true"
    for primitive in primitives:
        link = ElementTree.SubElement(model, "link", {"name": primitive.name})
        ElementTree.SubElement(link, "pose").text = (
            f"{primitive.center_x:g} {primitive.center_y:g} {primitive.center_z:g} "
            f"0 0 {primitive.yaw_rad:g}"
        )
        size = f"{primitive.size_x:g} {primitive.size_y:g} {primitive.size_z:g}"
        for element_name in ("collision", "visual"):
            element = ElementTree.SubElement(link, element_name, {"name": element_name})
            geometry = ElementTree.SubElement(element, "geometry")
            box = ElementTree.SubElement(geometry, "box")
            ElementTree.SubElement(box, "size").text = size
        ElementTree.SubElement(link, "enable_wind").text = "false"
    return ElementTree.tostring(sdf, encoding="unicode", xml_declaration=False)


def get_school_map_gazebo_artifact() -> SchoolMapGazeboArtifact:
    primitives = school_map_collision_primitives()
    semantic = {
        "schema_version": "dronedream.autonomy.school-map-semantic.v1",
        "compiler_scene_id": "school-campus-v1",
        "name": "School Map",
        "coordinate_frame": "ENU",
        "gazebo_axes": {"frontend_x": "x", "frontend_y_up": "z", "frontend_z": "y"},
        "tolerances_m": {
            "structural": STRUCTURAL_TOLERANCE_M,
            "route_endpoint": ROUTE_ENDPOINT_TOLERANCE_M,
        },
        "stair": {
            "risers_per_flight": STAIR_RISERS_PER_FLIGHT,
            "flights_per_storey": 2,
            "riser_m": STAIR_RISER_M,
            "tread_m": STAIR_TREAD_M,
            "storey_height_m": STOREY_HEIGHT_M,
        },
        "vehicle_clearance": {
            "collision_diameter_m": 0.76,
            "collision_height_m": 0.43,
            "minimum_road_width_m": 4.8,
            "minimum_indoor_width_m": 1.6,
            "minimum_open_door_clearance_m": 3.8,
        },
        "roads": ROAD_NETWORK,
        "collision_primitives": [primitive.__dict__ for primitive in primitives],
        "geometry_scope": [
            "terrain",
            "building-shells-and-floor-openings",
            "teaching-and-cafeteria-switchback-stairs",
            "entrance-steps-and-thresholds",
            "door-frames-and-open-closed-door-leaves",
            "canopies-and-columns",
            "street-light-obstacles",
        ],
        "known_export_limits": [
            (
                "Furniture, glazing, tree crowns and training-gate torus visuals "
                "are not collision primitives in this export."
            ),
            "Occupancy and ESDF layers must be generated and smoke-tested by the signed Runtime.",
        ],
        "execution": {
            "gazebo_asset_contract_generated": True,
            "gazebo_runtime_verified": False,
            "px4_mission_smoke_verified": False,
            "simulation_execution_ready": False,
        },
    }
    semantic_json = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    model_sdf = _sdf_for(primitives)
    sdf_sha = hashlib.sha256(model_sdf.encode()).hexdigest()
    semantic_sha = hashlib.sha256(semantic_json.encode()).hexdigest()
    summary = {
        "schema_version": "dronedream.autonomy.gazebo-artifact-summary.v1",
        "format": "sdf",
        "sdf_version": "1.9",
        "model_sdf_sha256": sdf_sha,
        "semantic_sha256": semantic_sha,
        "collision_primitive_count": len(primitives),
        "visual_primitive_count": len(primitives),
        "geometry_scope": "structural-shell-stairs-facilities-v1",
        "known_export_limit_count": 2,
        "gazebo_asset_contract_generated": True,
        "gazebo_runtime_verified": False,
        "px4_mission_smoke_verified": False,
        "simulation_execution_ready": False,
    }
    return SchoolMapGazeboArtifact(model_sdf, semantic_json, summary)


def export_school_map_gazebo_artifact(output_directory: Path) -> dict[str, str]:
    artifact = get_school_map_gazebo_artifact()
    output_directory.mkdir(parents=True, exist_ok=True)
    files = {
        "model.sdf": artifact.model_sdf,
        "semantic.json": artifact.semantic_json,
        "summary.json": json.dumps(artifact.summary, indent=2, sort_keys=True) + "\n",
    }
    for name, content in files.items():
        (output_directory / name).write_text(content, encoding="utf-8", newline="\n")
    return {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}
