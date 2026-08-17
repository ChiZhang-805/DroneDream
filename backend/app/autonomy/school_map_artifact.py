"""Deterministic School Map SDF and semantic-contract export.

The artifact is deliberately marked runtime-unverified.  It is a Gazebo-readable
static model and a content-addressed collision/semantic contract, not evidence of
a completed PX4/Gazebo smoke run.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypedDict
from xml.etree import ElementTree

from app.autonomy.px4_x500_vehicle import (
    MY_DRONE_MODEL_NAME,
    PX4_X500_DRY_MASS_KG,
    PX4_X500_MAXIMUM_THRUST_N,
    PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT,
    TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M,
    TAKEOUT_PAYLOAD_MASS_KG,
    TAKEOUT_PAYLOAD_SIZE_M,
    px4_x500_loaded_thrust_to_weight,
)

Point2D = tuple[float, float]


class Crosswalk(TypedDict):
    id: str
    x: float
    y: float
    axis: Literal["x", "y"]
    bar_count: int


class RoadMarkings(TypedDict):
    centerline_width_m: float
    centerline_dash_m: float
    centerline_gap_m: float
    crosswalk_bar_count: int
    crosswalk_bar_width_m: float
    crosswalk_bar_spacing_m: float
    crosswalk_length_m: float
    junction_centerline_inset_m: float
    crosswalk_clearance_m: float


class RoadSegment(TypedDict):
    id: str
    width_m: float
    points: tuple[Point2D, ...]


class RoadJunction(TypedDict):
    id: str
    x: float
    y: float
    diameter_m: float
    minimum_degree: int


class RoadNetwork(TypedDict):
    facility_anchors: dict[str, Point2D]
    segments: tuple[RoadSegment, ...]
    junctions: tuple[RoadJunction, ...]


STRUCTURAL_TOLERANCE_M = 0.001
ROUTE_ENDPOINT_TOLERANCE_M = 0.01
SEMANTIC_FLOAT_DECIMAL_PLACES = 12
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
STAIR_HANDRAIL_HEIGHT_M = 0.9
STAIR_HANDRAIL_RADIUS_M = 0.025
STAIR_ROUTE_CENTER_ABOVE_TREAD_M = 0.85
VEHICLE_COLLISION_DIAMETER_M = 0.76
VEHICLE_COLLISION_HEIGHT_M = 0.43
VEHICLE_COLLISION_CENTER_ABOVE_CONTACT_M = VEHICLE_COLLISION_HEIGHT_M / 2
PX4_X500_MODEL_ROOT_TO_CONTACT_M = 0.013
PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M = (
    PX4_X500_MODEL_ROOT_TO_CONTACT_M + VEHICLE_COLLISION_CENTER_ABOVE_CONTACT_M
)
TEACHING_ENTRANCE_CENTER_X = -25.0
TEACHING_ENTRANCE_OPENING_M = 8.46
ENTRANCE_DOOR_FRAME_WIDTH_M = 0.16
ENTRANCE_DOOR_FRAME_DEPTH_M = 0.11
ENTRANCE_DOOR_LEAF_WIDTH_M = 1.995
ENTRANCE_DOOR_LEAF_DEPTH_M = 0.095
ENTRANCE_DOOR_HEIGHT_M = 2.7
ENTRANCE_DOOR_OPEN_ANGLE_RAD = math.radians(90)
TEACHING_OPEN_DOOR_PAIR_CENTER_X = (
    TEACHING_ENTRANCE_CENTER_X - ENTRANCE_DOOR_FRAME_WIDTH_M / 2 - ENTRANCE_DOOR_LEAF_WIDTH_M
)
TEACHING_OPEN_DOOR_FRAME_CLEARANCE_M = ENTRANCE_DOOR_LEAF_WIDTH_M * 2
TEACHING_OPEN_DOOR_CLEARANCE_M = (
    TEACHING_OPEN_DOOR_FRAME_CLEARANCE_M
    - 2 * ENTRANCE_DOOR_LEAF_WIDTH_M * math.cos(ENTRANCE_DOOR_OPEN_ANGLE_RAD)
    - 2 * ENTRANCE_DOOR_LEAF_DEPTH_M * math.sin(ENTRANCE_DOOR_OPEN_ANGLE_RAD)
)
CAFETERIA_ENTRANCE_CENTER_X = 30.0
CAFETERIA_ENTRANCE_OPENING_M = 7.5
CAFETERIA_DOOR_GROUP_WIDTH_M = 3.59
CAFETERIA_DOOR_FRAME_WIDTH_M = 0.08
CAFETERIA_DOOR_FRAME_DEPTH_M = 0.11
CAFETERIA_DOOR_LEAF_DEPTH_M = 0.06
CAFETERIA_DOOR_HEIGHT_M = 2.65

TREE_POSITIONS = [
    *((x, -11.6) for x in (-48, -40, -32, -16, -8, 16, 24, 47.5)),
    *((x, -24.4) for x in (-48, -40, -32, -16, -8, 16, 24, 40, 47.5)),
    *((x, 40.2) for x in (-54, -24, -14, 4, 12)),
    *((x, 40.2) for x in (20, 28, 36, 44)),
    (-44, 40),
    (-34, 40),
    (54, 40.2),
    (56.5, 20),
    (56.5, 8),
    (-56, -34),
    (56, -34),
    (44, -30),
    (32, -32),
    (20, -32),
    (-12, -32),
    (-36, -32),
]
TREE_TRUNK_RADIUS_M = 0.24

ROOM_CENTERS_X = (-45.25, -31.75, -18.25, -6.295)
ROOM_HALF_WIDTH_M = 5.75
EAST_STAIR_ROOM_HALF_WIDTH_M = 4.205
ROOM_FRONT_Y = 10.6
ROOM_BACK_Y = 19.3
ROOM_WALL_THICKNESS_M = 0.14
ROOM_DOOR_WIDTH_M = 1.2
ROOM_DOOR_HEIGHT_M = 2.2
ROOM_DOOR_FRAME_WIDTH_M = 0.08
ROOM_DOOR_FRAME_DEPTH_M = 0.11
ROOM_DOOR_LEAF_DEPTH_M = 0.06
CLASSROOM_DOOR_OFFSET_X_M = 3.35
EAST_STAIR_ROOM_DOOR_OFFSET_X_M = 3.0
OFFICE_DOOR_OFFSET_X_M = 3.6
OFFICE_DOOR_CENTER_X = ROOM_CENTERS_X[0] + OFFICE_DOOR_OFFSET_X_M
ROOM_WINDOW_OFFSETS_X_M = (-3.9, -1.3, 1.3, 3.9)
EAST_STAIR_ROOM_WINDOW_OFFSETS_X_M = (-3.0, -1.0, 1.0, 3.0)
ROOM_WINDOW_WIDTH_M = 1.5
ROOM_WINDOW_HEIGHT_M = 1.28
WINDOW_FRAME_WIDTH_M = 0.08
WINDOW_GLASS_THICKNESS_M = 0.02
WINDOW_MULLION_WIDTH_M = 0.045
TEACHING_FACADE_ROOM_CENTERS_X = (-45.25, -31.75, -18.25, -4.75)
TEACHING_FACADE_WINDOW_CENTERS_X = tuple(
    center_x + offset
    for center_x in TEACHING_FACADE_ROOM_CENTERS_X
    for offset in (-4.05, -1.35, 1.35, 4.05)
)
TEACHING_FACADE_WINDOW_WIDTH_M = 1.72
TEACHING_FACADE_WINDOW_HEIGHT_M = 1.34
CAFETERIA_WINDOW_CENTERS_X = (18.0, 26.0, 34.0, 42.0)
CAFETERIA_WINDOW_WIDTH_M = 2.7
CAFETERIA_WINDOW_HEIGHT_M = 1.35

FENCE_MIN_X = -59.0
FENCE_MAX_X = 59.0
FENCE_MIN_Y = -44.0
FENCE_MAX_Y = 44.0
FENCE_POST_RADIUS_M = 0.045
FENCE_POST_HEIGHT_M = 1.8
FENCE_RAIL_HEIGHT_M = 0.055
FENCE_RAIL_DEPTH_M = 0.055
FENCE_RAIL_CENTER_Z_M = 1.55
GATE_HALF_OPENING_M = 8.0
GATE_POST_RADIUS_M = 0.22
GATE_POST_HEIGHT_M = 3.475
GATE_HEADER_HEIGHT_M = 0.35
GATE_HEADER_DEPTH_M = 0.38

BIKE_SHELTER_CENTER = (-42.0, 30.2)
BIKE_SHELTER_COLUMN_RADIUS_M = 0.08
BIKE_SHELTER_COLUMN_HEIGHT_M = 2.89
PICKUP_CENTER = (48.5, 1.5)
PICKUP_ROUTE_CENTER = (48.5, 1.25)
PICKUP_ROUTE_ENVELOPE_CENTER_Z_M = 1.35
PICKUP_COLUMN_RADIUS_M = 0.075
PICKUP_COLUMN_HEIGHT_M = 2.71
PICKUP_PAD_RADIUS_M = 1.0
PICKUP_PAD_THICKNESS_M = 0.08
STREET_LIGHT_BASE_RADIUS_M = 0.18
STREET_LIGHT_BASE_HEIGHT_M = 0.12
STREET_LIGHT_POLE_RADIUS_M = 0.085
STREET_LIGHT_POLE_HEIGHT_M = 4.3
STREET_LIGHT_ARM_LENGTH_M = 1.25
STREET_LIGHT_ARM_HEIGHT_M = 0.1
TRAINING_GATE_ROUTE_Y = -18.0
TRAINING_GATE_TUBE_RADIUS_M = 0.09
TRAINING_GATE_SUPPORT_RADIUS_M = 0.075
TRAINING_GATE_BASE_HEIGHT_M = 0.08
TRAINING_GATE_SEGMENT_COUNT = 32
TRAINING_GATES = ((-5.0, 2.4, 1.55), (15.0, 2.5, 1.65), (35.0, 2.25, 1.5))
TRAINING_GATE_COLLISION_MAX_ERROR_M = max(
    radius_m * (1 - math.cos(math.pi / TRAINING_GATE_SEGMENT_COUNT))
    for _, _, radius_m in TRAINING_GATES
)

CROSSWALKS: tuple[Crosswalk, ...] = (
    {"id": "teaching-entry-crosswalk", "x": -25.0, "y": -4.6, "axis": "x", "bar_count": 7},
    {"id": "cafeteria-entry-crosswalk", "x": 30.0, "y": 3.0, "axis": "x", "bar_count": 7},
    {"id": "main-gate-crosswalk", "x": 0.0, "y": -24.5, "axis": "x", "bar_count": 9},
)
ROAD_MARKINGS: RoadMarkings = {
    "centerline_width_m": 0.11,
    "centerline_dash_m": 1.6,
    "centerline_gap_m": 1.1,
    "crosswalk_bar_count": 7,
    "crosswalk_bar_width_m": 0.34,
    "crosswalk_bar_spacing_m": 0.62,
    "crosswalk_length_m": 3.8,
    "junction_centerline_inset_m": 0.3,
    "crosswalk_clearance_m": 0.18,
}

ROAD_NETWORK: RoadNetwork = {
    "facility_anchors": {
        "campus-gate": (0.0, -43.0),
        "teaching-building": (-25.0, -1.055),
        "cafeteria": (30.0, 6.245),
        "takeout-pickup": (48.5, 1.5),
        "bicycle-shelter": (-42.0, 35.4),
        "tree-corridor": (0.0, -18.0),
    },
    "segments": (
        {"id": "campus-gate-spine", "width_m": 6.4, "points": ((0, -43), (0, -31), (0, -18))},
        {
            "id": "campus-east-west-road",
            "width_m": 6.2,
            "points": ((-51, -18), (-25, -18), (0, -18), (8, -18), (30, -18), (52, -18)),
        },
        {
            "id": "teaching-entrance-road",
            "width_m": 5.4,
            "points": ((-25, -18), (-25, -9), (-25, -1.055)),
        },
        {
            "id": "cafeteria-entrance-road",
            "width_m": 5.4,
            "points": ((30, -18), (30, -6), (30, 1), (30, 6.245)),
        },
        {
            "id": "takeout-pickup-road",
            "width_m": 5.2,
            "points": ((30, -18), (39, -12), (46, -5), (48.5, 1.5)),
        },
        {
            "id": "west-bicycle-service-road",
            "width_m": 4.8,
            "points": ((-51, -18), (-55.6, -8), (-55.6, 24), (-51, 34), (-42, 35.4)),
        },
        {
            "id": "campus-courtyard-road",
            "width_m": 4.8,
            "points": ((8, -18), (8, -5), (8, 10), (8, 27), (8, 35.4), (-15, 35.4), (-42, 35.4)),
        },
        {
            "id": "north-cafeteria-service-road",
            "width_m": 4.8,
            "points": ((8, 35.4), (30, 35.4), (45, 35.4), (52, 28), (52, -18)),
        },
    ),
    "junctions": (
        {
            "id": "south-gate-crossroads",
            "x": 0.0,
            "y": -18.0,
            "diameter_m": 7.2,
            "minimum_degree": 3,
        },
        {
            "id": "teaching-road-junction",
            "x": -25.0,
            "y": -18.0,
            "diameter_m": 6.6,
            "minimum_degree": 3,
        },
        {
            "id": "cafeteria-road-junction",
            "x": 30.0,
            "y": -18.0,
            "diameter_m": 6.8,
            "minimum_degree": 4,
        },
        {
            "id": "courtyard-road-junction",
            "x": 8.0,
            "y": -18.0,
            "diameter_m": 6.2,
            "minimum_degree": 3,
        },
        {"id": "north-loop-junction", "x": 8.0, "y": 35.4, "diameter_m": 5.5, "minimum_degree": 3},
        {
            "id": "bicycle-shelter-junction",
            "x": -42.0,
            "y": 35.4,
            "diameter_m": 5.4,
            "minimum_degree": 2,
        },
    ),
}

PEDESTRIAN_PATHS: tuple[RoadSegment, ...] = (
    {"id": "teaching-south-pedestrian-path", "width_m": 2.2, "points": ((-55, -5.2), (5, -5.2))},
    {"id": "teaching-cafeteria-path", "width_m": 3.1, "points": ((8.2, -7), (8.2, 32))},
    {"id": "cafeteria-south-path", "width_m": 2.4, "points": ((10, 3.4), (49, 3.4))},
)


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
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class CylinderPrimitive:
    name: str
    center_x: float
    center_y: float
    center_z: float
    radius_m: float
    height_m: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class CapsulePrimitive:
    name: str
    center_x: float
    center_y: float
    center_z: float
    radius_m: float
    length_m: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class SpherePrimitive:
    name: str
    center_x: float
    center_y: float
    center_z: float
    radius_m: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class MeshPrimitive:
    name: str
    center_x: float
    center_y: float
    center_z: float
    uri: str
    semantic: str
    scale_x: float = 1.0
    scale_y: float = 1.0
    scale_z: float = 1.0
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


CollisionPrimitive = (
    BoxPrimitive | CylinderPrimitive | CapsulePrimitive | SpherePrimitive | MeshPrimitive
)


@dataclass(frozen=True)
class SchoolMapGazeboArtifact:
    model_sdf: str
    semantic_json: str
    summary: dict[str, object]
    package_files: dict[str, str]


SCHOOL_MAP_GAZEBO_ARTIFACT_SUMMARY: dict[str, object] = {
    "schema_version": "dronedream.autonomy.gazebo-artifact-summary.v1",
    "format": "sdf",
    "sdf_version": "1.9",
    "model_sdf_sha256": "58809c97af977fe637d66fe2b1b72072a3c81b084782a14bc00425a97eba7071",
    "semantic_sha256": "a188c56169a616385e0c3998ae507ae656a6300207e9decd3442d1bd2cc6ccff",
    "world_sdf_sha256": "ddcde7bd30484e0f2c90cbecb5e7a0704703d92929b2de5847e5d9e1fe22b6e0",
    "physics_world_sdf_sha256": (
        "f5a861691a24fab815f7f1800bd29ab2483fe77ea9be9eb9af721e1677303bae"
    ),
    "physics_model_sdf_sha256": (
        "7d533e42aeffe2a612fa2f05c5fa711c9a1bdd3e0e1d7147e586b269fb6f7f14"
    ),
    "model_config_sha256": "eb06bf2d09e16f6e7b4c5ca379b5aea4c16b7a082f3e8a6e41c020049646dcf5",
    "package_file_sha256": {
        "README.md": "e81f2a37011ffd54e224917b373fb8f6d5e917586c60c55978b4e52661550b3a",
        "materials/textures/campus-surface.ppm": (
            "29514802bc60ff22947e116b350a0abb421f1d3c36d5337b2e89a09a31e087b0"
        ),
        "meshes/training-gate-1.obj": (
            "352342d5fa8d60f3caf631f63c650c7fd1b40ae58d3f019f6a70b008ebdce7d8"
        ),
        "meshes/training-gate-2.obj": (
            "c2f51abec480467ad1d84fb2a7f4fc64cc60350604c283f7ff61a96a2c39865b"
        ),
        "meshes/training-gate-3.obj": (
            "9a4aade0b45086914fdb0bfdecb215d57fff28b18f6e3e8da6ab49eb9042e8ab"
        ),
        "meshes/training-gate.mtl": (
            "d443f8c87e66c7fd914bdc86b19aa5266ab6376b4f4416b6c2aa78595cb23cb0"
        ),
        "model.config": "eb06bf2d09e16f6e7b4c5ca379b5aea4c16b7a082f3e8a6e41c020049646dcf5",
        "model.physics.sdf": ("7d533e42aeffe2a612fa2f05c5fa711c9a1bdd3e0e1d7147e586b269fb6f7f14"),
        "model.sdf": "58809c97af977fe637d66fe2b1b72072a3c81b084782a14bc00425a97eba7071",
        "ros_gz_bridge.yaml": ("89220ef78125348776575b1a14fa1727c9cb098d9c46d84a74e27e5e8715f0b1"),
        "semantic.json": "a188c56169a616385e0c3998ae507ae656a6300207e9decd3442d1bd2cc6ccff",
        "world.physics.sdf": ("f5a861691a24fab815f7f1800bd29ab2483fe77ea9be9eb9af721e1677303bae"),
        "world.sdf": "ddcde7bd30484e0f2c90cbecb5e7a0704703d92929b2de5847e5d9e1fe22b6e0",
    },
    "package_manifest_sha256": ("0f5135940c74844923a86cd6e000bb44f9097bbd79442fd9e014b94211c50f8d"),
    "package_file_count": 13,
    "collision_primitive_count": 4023,
    "visual_primitive_count": 3930,
    "geometry_scope": "simulation-static-scene-v2",
    "known_export_limit_count": 4,
    "gazebo_asset_contract_generated": True,
    "gazebo_cli_validation_required": True,
    "gazebo_runtime_verified": False,
    "px4_mission_smoke_verified": False,
    "simulation_execution_ready": False,
}


def get_school_map_gazebo_summary() -> dict[str, object]:
    """Return the cheap, CI-pinned package identity used by catalog reads."""

    return deepcopy(SCHOOL_MAP_GAZEBO_ARTIFACT_SUMMARY)


def _box(
    name: str,
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    semantic: str,
    yaw_rad: float = 0.0,
    roll_rad: float = 0.0,
    pitch_rad: float = 0.0,
) -> BoxPrimitive:
    return BoxPrimitive(name, *center, *size, semantic, yaw_rad, roll_rad, pitch_rad)


def _cylinder(
    name: str,
    center: tuple[float, float, float],
    radius_m: float,
    height_m: float,
    semantic: str,
    yaw_rad: float = 0.0,
    roll_rad: float = 0.0,
    pitch_rad: float = 0.0,
) -> CylinderPrimitive:
    return CylinderPrimitive(
        name,
        *center,
        radius_m,
        height_m,
        semantic,
        yaw_rad,
        roll_rad,
        pitch_rad,
    )


def _sphere(
    name: str,
    center: tuple[float, float, float],
    radius_m: float,
    semantic: str,
) -> SpherePrimitive:
    return SpherePrimitive(name, *center, radius_m, semantic)


def _capsule_between(
    name: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    radius_m: float,
    semantic: str,
) -> CapsulePrimitive:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    delta_z = end[2] - start[2]
    if abs(delta_x) > STRUCTURAL_TOLERANCE_M:
        raise ValueError("School Map training-gate capsules must remain in one Y-Z plane")
    length_m = math.sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z)
    return CapsulePrimitive(
        name,
        (start[0] + end[0]) / 2,
        (start[1] + end[1]) / 2,
        (start[2] + end[2]) / 2,
        radius_m,
        length_m,
        semantic,
        roll_rad=-math.atan2(delta_y, delta_z),
    )


def _mesh(
    name: str,
    center: tuple[float, float, float],
    uri: str,
    semantic: str,
) -> MeshPrimitive:
    return MeshPrimitive(name, *center, uri, semantic)


def _torus_obj(major_radius_m: float, tube_radius_m: float) -> str:
    major_segments = 64
    tube_segments = 12
    lines = [
        "# DroneDream closed-manifold vertical torus visual mesh",
        "mtllib training-gate.mtl",
        "o school_training_gate_ring",
        "usemtl SchoolGate",
        "s 1",
    ]
    for major_index in range(major_segments):
        theta = 2 * math.pi * major_index / major_segments
        for tube_index in range(tube_segments):
            phi = 2 * math.pi * tube_index / tube_segments
            radial = major_radius_m + tube_radius_m * math.sin(phi)
            vertex_x = tube_radius_m * math.cos(phi)
            vertex_y = radial * math.cos(theta)
            vertex_z = radial * math.sin(theta)
            lines.append(f"v {vertex_x:.9f} {vertex_y:.9f} {vertex_z:.9f}")
    for major_index in range(major_segments):
        theta = 2 * math.pi * major_index / major_segments
        for tube_index in range(tube_segments):
            phi = 2 * math.pi * tube_index / tube_segments
            normal_x = math.cos(phi)
            normal_y = math.sin(phi) * math.cos(theta)
            normal_z = math.sin(phi) * math.sin(theta)
            lines.append(f"vn {normal_x:.9f} {normal_y:.9f} {normal_z:.9f}")
    for major_index in range(major_segments):
        next_major = (major_index + 1) % major_segments
        for tube_index in range(tube_segments):
            next_tube = (tube_index + 1) % tube_segments
            a = major_index * tube_segments + tube_index + 1
            b = next_major * tube_segments + tube_index + 1
            c = next_major * tube_segments + next_tube + 1
            d = major_index * tube_segments + next_tube + 1
            lines.append(f"f {a}//{a} {b}//{b} {c}//{c}")
            lines.append(f"f {a}//{a} {c}//{c} {d}//{d}")
    return "\n".join(lines) + "\n"


def _torus_mtl() -> str:
    return (
        "# DroneDream School Map training gate material\n"
        "newmtl SchoolGate\n"
        "Ka 0.25 0.12 0.55\n"
        "Kd 0.40 0.24 0.85\n"
        "Ks 0.18 0.18 0.18\n"
        "Ns 32\n"
        "d 1.0\n"
    )


def _segment_projection(
    x: float,
    y: float,
    start: Point2D,
    end: Point2D,
) -> tuple[float, float]:
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return math.hypot(x - start[0], y - start[1]), 0.0
    ratio = max(
        0.0,
        min(1.0, ((x - start[0]) * delta_x + (y - start[1]) * delta_y) / length_squared),
    )
    closest_x = start[0] + ratio * delta_x
    closest_y = start[1] + ratio * delta_y
    return math.hypot(x - closest_x, y - closest_y), ratio * math.sqrt(length_squared)


def _within_polyline(
    x: float,
    y: float,
    points: tuple[Point2D, ...],
    width_m: float,
) -> bool:
    return any(
        _segment_projection(x, y, start, end)[0] <= width_m / 2
        for start, end in zip(points[:-1], points[1:], strict=True)
    )


@lru_cache(maxsize=1)
def _campus_surface_ppm() -> str:
    width_px = 480
    height_px = 360
    bounds_x_m = 120.0
    bounds_y_m = 90.0
    colors = {
        "grass": (141, 187, 135),
        "path": (185, 181, 177),
        "road": (63, 66, 73),
        "centerline": (233, 215, 128),
        "crosswalk": (240, 238, 233),
    }
    rows = [f"P3\n{width_px} {height_px}\n255"]
    dash_period = ROAD_MARKINGS["centerline_dash_m"] + ROAD_MARKINGS["centerline_gap_m"]

    def within_crosswalk_clearance(world_x: float, world_y: float, crosswalk: Crosswalk) -> bool:
        bar_span_m = (
            (crosswalk["bar_count"] - 1) * ROAD_MARKINGS["crosswalk_bar_spacing_m"]
            + ROAD_MARKINGS["crosswalk_bar_width_m"]
            + 2 * ROAD_MARKINGS["crosswalk_clearance_m"]
        )
        long_half_m = (
            ROAD_MARKINGS["crosswalk_length_m"] / 2 + ROAD_MARKINGS["crosswalk_clearance_m"]
        )
        if crosswalk["axis"] == "x":
            return (
                abs(world_x - crosswalk["x"]) <= bar_span_m / 2
                and abs(world_y - crosswalk["y"]) <= long_half_m
            )
        return (
            abs(world_x - crosswalk["x"]) <= long_half_m
            and abs(world_y - crosswalk["y"]) <= bar_span_m / 2
        )

    for pixel_y in range(height_px):
        world_y = bounds_y_m / 2 - (pixel_y + 0.5) / height_px * bounds_y_m
        row: list[str] = []
        for pixel_x in range(width_px):
            world_x = (pixel_x + 0.5) / width_px * bounds_x_m - bounds_x_m / 2
            color = colors["grass"]
            if any(
                _within_polyline(world_x, world_y, path["points"], path["width_m"])
                for path in PEDESTRIAN_PATHS
            ):
                color = colors["path"]
            on_road = any(
                _within_polyline(world_x, world_y, segment["points"], segment["width_m"])
                for segment in ROAD_NETWORK["segments"]
            ) or any(
                math.hypot(world_x - junction["x"], world_y - junction["y"])
                <= junction["diameter_m"] / 2
                for junction in ROAD_NETWORK["junctions"]
            )
            centerline_excluded = any(
                math.hypot(world_x - junction["x"], world_y - junction["y"])
                <= junction["diameter_m"] / 2 + ROAD_MARKINGS["junction_centerline_inset_m"]
                for junction in ROAD_NETWORK["junctions"]
            ) or any(
                within_crosswalk_clearance(world_x, world_y, crosswalk) for crosswalk in CROSSWALKS
            )
            if on_road and not centerline_excluded:
                color = colors["road"]
            if on_road:
                for segment in ROAD_NETWORK["segments"]:
                    cumulative_length = 0.0
                    for start, end in zip(
                        segment["points"][:-1],
                        segment["points"][1:],
                        strict=True,
                    ):
                        distance_m, along_m = _segment_projection(
                            world_x,
                            world_y,
                            start,
                            end,
                        )
                        if (
                            distance_m <= ROAD_MARKINGS["centerline_width_m"] / 2
                            and (cumulative_length + along_m) % dash_period
                            <= ROAD_MARKINGS["centerline_dash_m"]
                        ):
                            color = colors["centerline"]
                            break
                        cumulative_length += math.dist(start, end)
                    if color == colors["centerline"]:
                        break
            for crosswalk in CROSSWALKS if on_road else ():
                crosswalk_half_count = crosswalk["bar_count"] // 2
                for bar_index in range(-crosswalk_half_count, crosswalk_half_count + 1):
                    along = bar_index * ROAD_MARKINGS["crosswalk_bar_spacing_m"]
                    if crosswalk["axis"] == "x":
                        inside = (
                            abs(world_x - (crosswalk["x"] + along))
                            <= ROAD_MARKINGS["crosswalk_bar_width_m"] / 2
                            and abs(world_y - crosswalk["y"])
                            <= ROAD_MARKINGS["crosswalk_length_m"] / 2
                        )
                    else:
                        inside = (
                            abs(world_x - crosswalk["x"]) <= ROAD_MARKINGS["crosswalk_length_m"] / 2
                            and abs(world_y - (crosswalk["y"] + along))
                            <= ROAD_MARKINGS["crosswalk_bar_width_m"] / 2
                        )
                    if inside:
                        color = colors["crosswalk"]
                        break
                if color == colors["crosswalk"]:
                    break
            row.extend(str(component) for component in color)
        rows.append(" ".join(row))
    return "\n".join(rows) + "\n"


def _wall_span(floor: int) -> tuple[float, float]:
    bottom = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
    top = floor * STOREY_HEIGHT_M
    return (bottom + top) / 2, top - bottom


def school_map_stair_route_points(
    direction: str,
) -> list[tuple[float, float, float]]:
    if direction not in {"ascending", "descending"}:
        raise ValueError("direction must be 'ascending' or 'descending'")
    run = STAIR_RISERS_PER_FLIGHT * STAIR_TREAD_M
    half_rise = STAIR_RISERS_PER_FLIGHT * STAIR_RISER_M
    lane_offset = STAIR_WIDTH_M / 2 + STAIR_LANE_GAP_M / 2
    start_y = 10.5 - run / 2
    end_y = 10.5 + run / 2
    route_inset_m = 0.04
    flight_clearance_m = STAIR_ROUTE_CENTER_ABOVE_TREAD_M
    upper_landing_turn_y = start_y - STAIR_LANDING_M / 2
    middle_landing_turn_y = end_y + STAIR_LANDING_M / 2
    lower_approach_y = start_y - VEHICLE_COLLISION_DIAMETER_M / 2 - STAIR_HANDRAIL_RADIUS_M - 0.05
    ascending: list[tuple[float, float, float]] = []
    for storey in (1, 2):
        lower_z = (storey - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
        middle_z = lower_z + half_rise
        upper_z = lower_z + STOREY_HEIGHT_M
        if storey == 1:
            ascending.append(
                (
                    -0.1 - lane_offset,
                    upper_landing_turn_y,
                    lower_z + flight_clearance_m,
                )
            )
        ascending.extend(
            (
                (
                    -0.1 - lane_offset,
                    lower_approach_y,
                    lower_z + STAIR_RISER_M + flight_clearance_m,
                ),
                (
                    -0.1 - lane_offset,
                    start_y + route_inset_m,
                    lower_z + STAIR_RISER_M + flight_clearance_m,
                ),
                (
                    -0.1 - lane_offset,
                    end_y - route_inset_m,
                    middle_z + flight_clearance_m,
                ),
                (
                    -0.1 - lane_offset,
                    middle_landing_turn_y,
                    middle_z + flight_clearance_m,
                ),
                (
                    -0.1 + lane_offset,
                    middle_landing_turn_y,
                    middle_z + flight_clearance_m,
                ),
                (
                    -0.1 + lane_offset,
                    end_y - route_inset_m,
                    middle_z + STAIR_RISER_M + flight_clearance_m,
                ),
                (
                    -0.1 + lane_offset,
                    start_y + route_inset_m,
                    upper_z + flight_clearance_m,
                ),
                (
                    -0.1 + lane_offset,
                    upper_landing_turn_y,
                    upper_z + flight_clearance_m,
                ),
                (
                    -0.1 - lane_offset,
                    upper_landing_turn_y,
                    upper_z + flight_clearance_m,
                ),
            )
        )
    return ascending if direction == "ascending" else list(reversed(ascending))


def _window_primitives(
    prefix: str,
    center_x: float,
    center_y: float,
    center_z: float,
    width_m: float,
    height_m: float,
    wall_depth_m: float,
) -> list[BoxPrimitive]:
    glass_width = width_m - WINDOW_FRAME_WIDTH_M * 2
    glass_height = height_m - WINDOW_FRAME_WIDTH_M * 2
    half_mullion_span = (glass_width - WINDOW_MULLION_WIDTH_M) / 2
    mullion_y = center_y + WINDOW_GLASS_THICKNESS_M / 2 + 0.04 / 2
    return [
        _box(
            f"{prefix}-frame-west",
            (center_x - width_m / 2 + WINDOW_FRAME_WIDTH_M / 2, center_y, center_z),
            (WINDOW_FRAME_WIDTH_M, wall_depth_m, height_m),
            "window-frame",
        ),
        _box(
            f"{prefix}-frame-east",
            (center_x + width_m / 2 - WINDOW_FRAME_WIDTH_M / 2, center_y, center_z),
            (WINDOW_FRAME_WIDTH_M, wall_depth_m, height_m),
            "window-frame",
        ),
        _box(
            f"{prefix}-frame-top",
            (center_x, center_y, center_z + height_m / 2 - WINDOW_FRAME_WIDTH_M / 2),
            (glass_width, wall_depth_m, WINDOW_FRAME_WIDTH_M),
            "window-frame",
        ),
        _box(
            f"{prefix}-frame-bottom",
            (center_x, center_y, center_z - height_m / 2 + WINDOW_FRAME_WIDTH_M / 2),
            (glass_width, wall_depth_m, WINDOW_FRAME_WIDTH_M),
            "window-frame",
        ),
        _box(
            f"{prefix}-glass",
            (center_x, center_y, center_z),
            (glass_width, WINDOW_GLASS_THICKNESS_M, glass_height),
            "window-glazing",
        ),
        _box(
            f"{prefix}-mullion-vertical",
            (center_x, mullion_y, center_z),
            (WINDOW_MULLION_WIDTH_M, 0.04, glass_height),
            "window-mullion",
        ),
        _box(
            f"{prefix}-mullion-west",
            (
                center_x - WINDOW_MULLION_WIDTH_M / 2 - half_mullion_span / 2,
                mullion_y,
                center_z,
            ),
            (half_mullion_span, 0.04, WINDOW_MULLION_WIDTH_M),
            "window-mullion",
        ),
        _box(
            f"{prefix}-mullion-east",
            (
                center_x + WINDOW_MULLION_WIDTH_M / 2 + half_mullion_span / 2,
                mullion_y,
                center_z,
            ),
            (half_mullion_span, 0.04, WINDOW_MULLION_WIDTH_M),
            "window-mullion",
        ),
    ]


def _windowed_wall_primitives(
    prefix: str,
    *,
    min_x: float,
    max_x: float,
    center_y: float,
    wall_bottom_z: float,
    wall_top_z: float,
    window_center_z: float,
    window_height_m: float,
    window_width_m: float,
    window_centers_x: tuple[float, ...] | list[float],
    wall_depth_m: float,
    semantic: str,
) -> list[BoxPrimitive]:
    window_bottom_z = window_center_z - window_height_m / 2
    window_top_z = window_center_z + window_height_m / 2
    result = [
        _box(
            f"{prefix}-lower",
            ((min_x + max_x) / 2, center_y, (wall_bottom_z + window_bottom_z) / 2),
            (max_x - min_x, wall_depth_m, window_bottom_z - wall_bottom_z),
            semantic,
        ),
        _box(
            f"{prefix}-upper",
            ((min_x + max_x) / 2, center_y, (window_top_z + wall_top_z) / 2),
            (max_x - min_x, wall_depth_m, wall_top_z - window_top_z),
            semantic,
        ),
    ]
    cursor = min_x
    for index, window_center_x in enumerate(sorted(window_centers_x), start=1):
        opening_min_x = window_center_x - window_width_m / 2
        width = opening_min_x - cursor
        result.append(
            _box(
                f"{prefix}-pier-{index}",
                (cursor + width / 2, center_y, window_center_z),
                (width, wall_depth_m, window_height_m),
                semantic,
            )
        )
        result.extend(
            _window_primitives(
                f"{prefix}-window-{index}",
                window_center_x,
                center_y,
                window_center_z,
                window_width_m,
                window_height_m,
                wall_depth_m,
            )
        )
        cursor = window_center_x + window_width_m / 2
    result.append(
        _box(
            f"{prefix}-pier-{len(window_centers_x) + 1}",
            (cursor + (max_x - cursor) / 2, center_y, window_center_z),
            (max_x - cursor, wall_depth_m, window_height_m),
            semantic,
        )
    )
    return result


def _room_back_wall_primitives(
    prefix: str,
    center_x: float,
    floor: int,
    half_width_m: float,
    window_offsets_x_m: tuple[float, ...],
) -> list[BoxPrimitive]:
    floor_surface_z = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
    window_center_z = floor_surface_z + 1.73
    inner_min_x = center_x - half_width_m + ROOM_WALL_THICKNESS_M / 2
    inner_max_x = center_x + half_width_m - ROOM_WALL_THICKNESS_M / 2
    return _windowed_wall_primitives(
        f"{prefix}-back-wall",
        min_x=inner_min_x,
        max_x=inner_max_x,
        center_y=ROOM_BACK_Y,
        wall_bottom_z=floor_surface_z,
        wall_top_z=floor * STOREY_HEIGHT_M,
        window_center_z=window_center_z,
        window_height_m=ROOM_WINDOW_HEIGHT_M,
        window_width_m=ROOM_WINDOW_WIDTH_M,
        window_centers_x=[center_x + offset for offset in window_offsets_x_m],
        wall_depth_m=ROOM_WALL_THICKNESS_M,
        semantic="interior-wall",
    )


def _room_door_primitives(
    prefix: str,
    door_center_x: float,
    floor: int,
    *,
    open_door: bool,
) -> list[BoxPrimitive]:
    floor_surface_z = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
    door_center_z = floor_surface_z + ROOM_DOOR_HEIGHT_M / 2
    frame_offset_x = ROOM_DOOR_WIDTH_M / 2 + ROOM_DOOR_FRAME_WIDTH_M / 2
    result = [
        _box(
            f"{prefix}-frame-west",
            (door_center_x - frame_offset_x, ROOM_FRONT_Y, door_center_z),
            (ROOM_DOOR_FRAME_WIDTH_M, ROOM_DOOR_FRAME_DEPTH_M, ROOM_DOOR_HEIGHT_M),
            "door-frame",
        ),
        _box(
            f"{prefix}-frame-east",
            (door_center_x + frame_offset_x, ROOM_FRONT_Y, door_center_z),
            (ROOM_DOOR_FRAME_WIDTH_M, ROOM_DOOR_FRAME_DEPTH_M, ROOM_DOOR_HEIGHT_M),
            "door-frame",
        ),
        _box(
            f"{prefix}-frame-top",
            (
                door_center_x,
                ROOM_FRONT_Y,
                floor_surface_z + ROOM_DOOR_HEIGHT_M + ROOM_DOOR_FRAME_WIDTH_M / 2,
            ),
            (ROOM_DOOR_WIDTH_M, ROOM_DOOR_FRAME_DEPTH_M, ROOM_DOOR_FRAME_WIDTH_M),
            "door-frame",
        ),
    ]
    if open_door:
        result.append(
            _box(
                f"{prefix}-leaf-open",
                (
                    door_center_x - ROOM_DOOR_WIDTH_M / 2 + ROOM_DOOR_LEAF_DEPTH_M / 2,
                    ROOM_FRONT_Y - ROOM_DOOR_WIDTH_M / 2,
                    door_center_z,
                ),
                (ROOM_DOOR_WIDTH_M, ROOM_DOOR_LEAF_DEPTH_M, ROOM_DOOR_HEIGHT_M),
                "open-door-leaf",
                yaw_rad=math.pi / 2,
            )
        )
    else:
        result.append(
            _box(
                f"{prefix}-leaf-closed",
                (door_center_x, ROOM_FRONT_Y, door_center_z),
                (ROOM_DOOR_WIDTH_M, ROOM_DOOR_LEAF_DEPTH_M, ROOM_DOOR_HEIGHT_M),
                "closed-door-leaf",
            )
        )
    return result


def _teaching_room_primitives() -> list[BoxPrimitive]:
    result: list[BoxPrimitive] = []
    side_wall_depth = ROOM_BACK_Y - ROOM_FRONT_Y - ROOM_WALL_THICKNESS_M
    side_wall_center_y = (ROOM_FRONT_Y + ROOM_BACK_Y) / 2
    for floor in range(1, 4):
        wall_center_z, wall_height = _wall_span(floor)
        floor_surface_z = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
        for room_index, center_x in enumerate(ROOM_CENTERS_X, start=1):
            office = floor == 3 and room_index == 1
            east_stair_room = room_index == 4
            prefix = "office" if office else f"classroom-{floor}-{room_index}"
            half_width_m = EAST_STAIR_ROOM_HALF_WIDTH_M if east_stair_room else ROOM_HALF_WIDTH_M
            window_offsets_x_m = (
                EAST_STAIR_ROOM_WINDOW_OFFSETS_X_M if east_stair_room else ROOM_WINDOW_OFFSETS_X_M
            )
            inner_min_x = center_x - half_width_m + ROOM_WALL_THICKNESS_M / 2
            inner_max_x = center_x + half_width_m - ROOM_WALL_THICKNESS_M / 2
            door_center_x = center_x + (
                OFFICE_DOOR_OFFSET_X_M
                if office
                else EAST_STAIR_ROOM_DOOR_OFFSET_X_M
                if east_stair_room
                else CLASSROOM_DOOR_OFFSET_X_M
            )
            door_opening_half = (ROOM_DOOR_WIDTH_M + ROOM_DOOR_FRAME_WIDTH_M * 2) / 2
            west_wall_max_x = door_center_x - door_opening_half
            east_wall_min_x = door_center_x + door_opening_half
            door_header_bottom_z = floor_surface_z + ROOM_DOOR_HEIGHT_M + ROOM_DOOR_FRAME_WIDTH_M
            result.extend(
                (
                    _box(
                        f"{prefix}-left-wall",
                        (center_x - half_width_m, side_wall_center_y, wall_center_z),
                        (ROOM_WALL_THICKNESS_M, side_wall_depth, wall_height),
                        "interior-wall",
                    ),
                    _box(
                        f"{prefix}-right-wall",
                        (center_x + half_width_m, side_wall_center_y, wall_center_z),
                        (ROOM_WALL_THICKNESS_M, side_wall_depth, wall_height),
                        "interior-wall",
                    ),
                    _box(
                        f"{prefix}-front-wall-west",
                        ((inner_min_x + west_wall_max_x) / 2, ROOM_FRONT_Y, wall_center_z),
                        (
                            west_wall_max_x - inner_min_x,
                            ROOM_WALL_THICKNESS_M,
                            wall_height,
                        ),
                        "interior-wall",
                    ),
                    _box(
                        f"{prefix}-front-wall-east",
                        ((east_wall_min_x + inner_max_x) / 2, ROOM_FRONT_Y, wall_center_z),
                        (
                            inner_max_x - east_wall_min_x,
                            ROOM_WALL_THICKNESS_M,
                            wall_height,
                        ),
                        "interior-wall",
                    ),
                    _box(
                        f"{prefix}-front-wall-header",
                        (
                            door_center_x,
                            ROOM_FRONT_Y,
                            (door_header_bottom_z + floor * STOREY_HEIGHT_M) / 2,
                        ),
                        (
                            door_opening_half * 2,
                            ROOM_WALL_THICKNESS_M,
                            floor * STOREY_HEIGHT_M - door_header_bottom_z,
                        ),
                        "interior-wall",
                    ),
                )
            )
            result.extend(
                _room_back_wall_primitives(
                    prefix,
                    center_x,
                    floor,
                    half_width_m,
                    window_offsets_x_m,
                )
            )
            result.extend(_room_door_primitives(prefix, door_center_x, floor, open_door=office))
    return result


def _teaching_floor_primitives() -> list[BoxPrimitive]:
    result: list[BoxPrimitive] = []
    building_min_x, building_max_x = -53.0, 3.0
    building_min_y, building_max_y = 2.0, 24.0
    flight_run = STAIR_RISERS_PER_FLIGHT * STAIR_TREAD_M
    lane_offset = STAIR_WIDTH_M / 2 + STAIR_LANE_GAP_M / 2
    opening = {
        "min_x": -0.1 - lane_offset - STAIR_WIDTH_M / 2 - STAIR_HANDRAIL_RADIUS_M * 2,
        "max_x": -0.1 + lane_offset + STAIR_WIDTH_M / 2 + STAIR_HANDRAIL_RADIUS_M * 2,
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
        result.extend(
            _windowed_wall_primitives(
                f"teaching-north-{floor}",
                min_x=building_min_x,
                max_x=building_max_x,
                center_y=building_max_y,
                wall_bottom_z=(floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M,
                wall_top_z=floor * STOREY_HEIGHT_M,
                window_center_z=(floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M + 1.73,
                window_height_m=TEACHING_FACADE_WINDOW_HEIGHT_M,
                window_width_m=TEACHING_FACADE_WINDOW_WIDTH_M,
                window_centers_x=TEACHING_FACADE_WINDOW_CENTERS_X,
                wall_depth_m=0.22,
                semantic="exterior-wall",
            )
        )
        facade_belt_height = 0.15
        facade_pilaster_height = height - facade_belt_height
        for index, pilaster_x in enumerate((-52.85, -38.5, -25.0, -11.5, 2.85), start=1):
            result.append(
                _box(
                    f"teaching-facade-pilaster-{floor}-{index}",
                    (
                        pilaster_x,
                        24.17,
                        (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M + facade_pilaster_height / 2,
                    ),
                    (0.28, 0.12, facade_pilaster_height),
                    "facade-structure",
                )
            )
        result.append(
            _box(
                f"teaching-facade-belt-{floor}",
                (-25.0, 24.17, floor * STOREY_HEIGHT_M - facade_belt_height / 2),
                (56.2, 0.12, facade_belt_height),
                "facade-structure",
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
    result.append(
        _box(
            "main-door-canopy",
            (-25.0, 0.64, 3.25),
            (8.2, 2.5, 0.28),
            "canopy",
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
                    hinge_x
                    + math.cos(three_angle) * local_center_x
                    + math.sin(three_angle) * ENTRANCE_DOOR_LEAF_DEPTH_M / 2,
                    2.0
                    - math.sin(three_angle) * local_center_x
                    + math.cos(three_angle) * ENTRANCE_DOOR_LEAF_DEPTH_M / 2,
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
) -> list[CollisionPrimitive]:
    result: list[CollisionPrimitive] = []
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
        handrail_height = STAIR_HANDRAIL_HEIGHT_M
        handrail_radius = STAIR_HANDRAIL_RADIUS_M
        first_rail_xs = (
            center_x - lane_offset - STAIR_WIDTH_M / 2 - handrail_radius,
            center_x - lane_offset + STAIR_WIDTH_M / 2 + handrail_radius,
        )
        second_rail_xs = (
            center_x + lane_offset - STAIR_WIDTH_M / 2 - handrail_radius,
            center_x + lane_offset + STAIR_WIDTH_M / 2 + handrail_radius,
        )
        for side_index, rail_x in enumerate(first_rail_xs, start=1):
            start = (
                rail_x,
                start_y,
                lower_z + handrail_height + handrail_radius,
            )
            end = (
                rail_x,
                end_y,
                middle_z + handrail_height + handrail_radius,
            )
            length = math.dist(start, end)
            result.append(
                _cylinder(
                    f"{prefix}-stair-{storey}-rail-a-{side_index}",
                    (
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        (start[2] + end[2]) / 2,
                    ),
                    handrail_radius,
                    length,
                    "stair-handrail",
                    roll_rad=-math.atan2(end[1] - start[1], end[2] - start[2]),
                )
            )
        for side_index, rail_x in enumerate(second_rail_xs, start=1):
            start = (
                rail_x,
                end_y,
                middle_z + handrail_height + handrail_radius,
            )
            end = (
                rail_x,
                start_y,
                upper_z + handrail_height + handrail_radius,
            )
            length = math.dist(start, end)
            result.append(
                _cylinder(
                    f"{prefix}-stair-{storey}-rail-b-{side_index}",
                    (
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        (start[2] + end[2]) / 2,
                    ),
                    handrail_radius,
                    length,
                    "stair-handrail",
                    roll_rad=-math.atan2(end[1] - start[1], end[2] - start[2]),
                )
            )
        for rail_side, rail_x in enumerate(first_rail_xs, start=1):
            for post_index in range(7):
                post_y = start_y + run / 6 * post_index
                post_base_z = lower_z + half_rise * post_index / 6
                result.append(
                    _cylinder(
                        f"{prefix}-stair-{storey}-post-a-{rail_side}-{post_index + 1}",
                        (rail_x, post_y, post_base_z + handrail_height / 2),
                        handrail_radius,
                        handrail_height,
                        "stair-handrail-post",
                    )
                )
        for rail_side, rail_x in enumerate(second_rail_xs, start=1):
            for post_index in range(7):
                post_y = end_y - run / 6 * post_index
                post_base_z = middle_z + half_rise * post_index / 6
                result.append(
                    _cylinder(
                        f"{prefix}-stair-{storey}-post-b-{rail_side}-{post_index + 1}",
                        (rail_x, post_y, post_base_z + handrail_height / 2),
                        handrail_radius,
                        handrail_height,
                        "stair-handrail-post",
                    )
                )
    return result


def _cafeteria_primitives() -> list[BoxPrimitive]:
    result: list[BoxPrimitive] = []
    run = STAIR_RISERS_PER_FLIGHT * STAIR_TREAD_M
    total_width = STAIR_WIDTH_M * 2 + STAIR_LANE_GAP_M
    opening = {
        "min_x": 40 - total_width / 2 - STAIR_HANDRAIL_RADIUS_M * 2,
        "max_x": 40 + total_width / 2 + STAIR_HANDRAIL_RADIUS_M * 2,
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
        result.extend(
            _windowed_wall_primitives(
                f"cafeteria-north-{floor}",
                min_x=13.0,
                max_x=47.0,
                center_y=32.5,
                wall_bottom_z=(floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M,
                wall_top_z=floor * STOREY_HEIGHT_M,
                window_center_z=(floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M + 1.73,
                window_height_m=CAFETERIA_WINDOW_HEIGHT_M,
                window_width_m=CAFETERIA_WINDOW_WIDTH_M,
                window_centers_x=CAFETERIA_WINDOW_CENTERS_X,
                wall_depth_m=0.22,
                semantic="exterior-wall",
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


def _placed_box(
    name: str,
    origin: tuple[float, float, float],
    local_center: tuple[float, float, float],
    frontend_size: tuple[float, float, float],
    semantic: str,
    rotation_y_rad: float = 0.0,
) -> BoxPrimitive:
    cos_rotation = math.cos(rotation_y_rad)
    sin_rotation = math.sin(rotation_y_rad)
    local_x, local_up, local_y = local_center
    return _box(
        name,
        (
            origin[0] + cos_rotation * local_x + sin_rotation * local_y,
            origin[1] - sin_rotation * local_x + cos_rotation * local_y,
            origin[2] + local_up,
        ),
        (frontend_size[0], frontend_size[2], frontend_size[1]),
        semantic,
        yaw_rad=-rotation_y_rad,
    )


def _student_workstation_primitives(
    prefix: str,
    x: float,
    y: float,
    floor_surface_z: float,
    rotation_y_rad: float,
) -> list[BoxPrimitive]:
    origin = (x, y, floor_surface_z)
    desktop_thickness = 0.07
    desktop_top = 0.72
    desktop_bottom = desktop_top - desktop_thickness
    result = [
        _placed_box(
            f"{prefix}-desktop",
            origin,
            (0, desktop_top - desktop_thickness / 2, 0),
            (1.05, desktop_thickness, 0.48),
            "student-desktop",
            rotation_y_rad,
        )
    ]
    for index, (leg_x, leg_y) in enumerate(
        ((-0.43, -0.16), (0.43, -0.16), (-0.43, 0.16), (0.43, 0.16)),
        start=1,
    ):
        result.append(
            _placed_box(
                f"{prefix}-desk-leg-{index}",
                origin,
                (leg_x, desktop_bottom / 2, leg_y),
                (0.04, desktop_bottom, 0.04),
                "furniture-support",
                rotation_y_rad,
            )
        )
    seat_top = 0.46
    seat_thickness = 0.06
    seat_bottom = seat_top - seat_thickness
    result.extend(
        (
            _placed_box(
                f"{prefix}-chair-seat",
                origin,
                (0, seat_top - seat_thickness / 2, 0.72),
                (0.48, seat_thickness, 0.45),
                "chair",
                rotation_y_rad,
            ),
            _placed_box(
                f"{prefix}-chair-back",
                origin,
                (0, seat_top + 0.29, 0.92),
                (0.48, 0.58, 0.07),
                "chair",
                rotation_y_rad,
            ),
        )
    )
    for index, leg_x in enumerate((-0.18, 0.18), start=1):
        result.append(
            _placed_box(
                f"{prefix}-chair-leg-{index}",
                origin,
                (leg_x, seat_bottom / 2, 0.72),
                (0.04, seat_bottom, 0.04),
                "furniture-support",
                rotation_y_rad,
            )
        )
    return result


def _teaching_furniture_primitives() -> list[CollisionPrimitive]:
    result: list[CollisionPrimitive] = []
    for floor in range(1, 4):
        floor_surface_z = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
        for room_index, center_x in enumerate(ROOM_CENTERS_X, start=1):
            if floor == 3 and room_index == 1:
                continue
            prefix = f"classroom-{floor}-{room_index}"
            east_stair_room = room_index == 4
            teacher_desk_x = center_x - (2.7 if east_stair_room else 3.75)
            podium_x = center_x + (2.5 if east_stair_room else 3.8)
            result.extend(
                (
                    _box(
                        f"{prefix}-blackboard",
                        (center_x, ROOM_BACK_Y - 0.115, floor_surface_z + 1.53),
                        (4.3, 0.09, 1.25),
                        "blackboard",
                    ),
                    _box(
                        f"{prefix}-teacher-desk",
                        (teacher_desk_x, ROOM_BACK_Y - 1.15, floor_surface_z + 0.38),
                        (1.55, 0.7, 0.76),
                        "teacher-desk",
                    ),
                    _box(
                        f"{prefix}-podium",
                        (podium_x, ROOM_BACK_Y - 1.05, floor_surface_z + 0.46),
                        (0.75, 0.55, 0.92),
                        "podium",
                    ),
                )
            )
            for row in range(4):
                for column in range(3):
                    workstation_prefix = f"{prefix}-desk-{row + 1}-{column + 1}"
                    result.extend(
                        _student_workstation_primitives(
                            workstation_prefix,
                            center_x - 3.3 + column * 3.25,
                            ROOM_FRONT_Y + 1.35 + row * 1.35,
                            floor_surface_z,
                            math.pi,
                        )
                    )

    office_center_x = ROOM_CENTERS_X[0]
    office_floor_z = 2 * STOREY_HEIGHT_M + FLOOR_SLAB_M
    for desk_index in range(4):
        desk_x = office_center_x - 3.8 + (desk_index % 2) * 4.3
        desk_y = ROOM_FRONT_Y + 2.2 + (desk_index // 2) * 2.7
        prefix = f"office-desk-{desk_index + 1}"
        result.append(
            _box(
                f"{prefix}-top",
                (desk_x, desk_y, office_floor_z + 0.7),
                (1.55, 0.72, 0.08),
                "office-desk",
            )
        )
        for leg_index, (offset_x, offset_y) in enumerate(
            ((-0.65, -0.28), (-0.65, 0.28), (0.65, -0.28), (0.65, 0.28)),
            start=1,
        ):
            result.append(
                _box(
                    f"{prefix}-leg-{leg_index}",
                    (desk_x + offset_x, desk_y + offset_y, office_floor_z + 0.33),
                    (0.04, 0.04, 0.66),
                    "furniture-support",
                )
            )
        chair_y = desk_y + 0.82
        result.append(
            _box(
                f"office-chair-{desk_index + 1}-seat",
                (desk_x, chair_y, office_floor_z + 0.43),
                (0.54, 0.52, 0.08),
                "chair",
            )
        )
        for leg_index, (offset_x, offset_y) in enumerate(
            ((-0.18, -0.18), (-0.18, 0.18), (0.18, -0.18), (0.18, 0.18)),
            start=1,
        ):
            result.append(
                _box(
                    f"office-chair-{desk_index + 1}-leg-{leg_index}",
                    (desk_x + offset_x, chair_y + offset_y, office_floor_z + 0.195),
                    (0.035, 0.035, 0.39),
                    "furniture-support",
                )
            )
        result.append(
            _box(
                f"office-chair-{desk_index + 1}-back",
                (desk_x, desk_y + 1.02, office_floor_z + 0.795),
                (0.54, 0.08, 0.65),
                "chair",
            )
        )
    for shelf_index, offset_x in enumerate((-4.7, 4.7), start=1):
        shelf_x = office_center_x + offset_x
        shelf_y = ROOM_BACK_Y - 0.8
        result.extend(
            (
                _box(
                    f"office-bookshelf-{shelf_index}-back",
                    (shelf_x, shelf_y + 0.17, office_floor_z + 1.1),
                    (0.7, 0.04, 2.2),
                    "bookshelf",
                ),
                _box(
                    f"office-bookshelf-{shelf_index}-west",
                    (shelf_x - 0.33, shelf_y - 0.02, office_floor_z + 1.1),
                    (0.04, 0.34, 2.2),
                    "bookshelf",
                ),
                _box(
                    f"office-bookshelf-{shelf_index}-east",
                    (shelf_x + 0.33, shelf_y - 0.02, office_floor_z + 1.1),
                    (0.04, 0.34, 2.2),
                    "bookshelf",
                ),
            )
        )
        for board_index, shelf_z in enumerate((0.02, 0.42, 0.88, 1.34, 1.8, 2.18), start=1):
            result.append(
                _box(
                    f"office-bookshelf-{shelf_index}-board-{board_index}",
                    (shelf_x, shelf_y - 0.02, office_floor_z + shelf_z),
                    (0.62, 0.34, 0.04),
                    "bookshelf",
                )
            )
    for plant_index, offset_x in enumerate((-1.7, 3.0), start=1):
        plant_x = office_center_x + offset_x
        plant_y = ROOM_BACK_Y - 0.8
        result.extend(
            (
                _cylinder(
                    f"office-plant-{plant_index}-pot",
                    (plant_x, plant_y, office_floor_z + 0.275),
                    0.34,
                    0.55,
                    "plant-pot",
                ),
                _sphere(
                    f"office-plant-{plant_index}-crown",
                    (plant_x, plant_y, office_floor_z + 1.13),
                    0.58,
                    "plant-crown",
                ),
            )
        )
    result.append(
        _cylinder(
            "office-drone-launch-pad",
            (office_center_x + 3.0, ROOM_FRONT_Y + 4.7, office_floor_z + 0.04),
            0.85,
            0.08,
            "launch-pad",
        )
    )
    return result


def _cafeteria_table_primitives(
    prefix: str,
    x: float,
    y: float,
    floor_surface_z: float,
) -> list[BoxPrimitive]:
    tabletop_thickness = 0.08
    tabletop_top = 0.76
    tabletop_bottom = tabletop_top - tabletop_thickness
    result = [
        _box(
            f"{prefix}-top",
            (x, y, floor_surface_z + tabletop_top - tabletop_thickness / 2),
            (1.8, 0.82, tabletop_thickness),
            "cafeteria-table",
        ),
        _box(
            f"{prefix}-support",
            (x, y, floor_surface_z + tabletop_bottom / 2),
            (0.12, 0.12, tabletop_bottom),
            "furniture-support",
        ),
    ]
    for chair_index, (chair_x, chair_y) in enumerate(
        ((-1.15, 0.0), (1.15, 0.0), (0.0, -0.85), (0.0, 0.85)),
        start=1,
    ):
        seat_top = 0.46
        seat_thickness = 0.08
        seat_bottom = seat_top - seat_thickness
        result.append(
            _box(
                f"{prefix}-chair-{chair_index}-seat",
                (x + chair_x, y + chair_y, floor_surface_z + seat_top - seat_thickness / 2),
                (0.48, 0.48, seat_thickness),
                "chair",
            )
        )
        for leg_index, (offset_x, offset_y) in enumerate(
            ((-0.18, -0.18), (-0.18, 0.18), (0.18, -0.18), (0.18, 0.18)),
            start=1,
        ):
            result.append(
                _box(
                    f"{prefix}-chair-{chair_index}-leg-{leg_index}",
                    (
                        x + chair_x + offset_x,
                        y + chair_y + offset_y,
                        floor_surface_z + seat_bottom / 2,
                    ),
                    (0.035, 0.035, seat_bottom),
                    "furniture-support",
                )
            )
        chair_back_y = chair_y + (0.28 if chair_y == 0 else math.copysign(0.25, chair_y))
        result.append(
            _box(
                f"{prefix}-chair-{chair_index}-back",
                (x + chair_x, y + chair_back_y, floor_surface_z + seat_top + 0.29),
                (0.45, 0.08, 0.58),
                "chair",
            )
        )
    return result


def _cafeteria_furniture_primitives() -> list[CollisionPrimitive]:
    result: list[CollisionPrimitive] = []
    for floor in (1, 2):
        floor_surface_z = (floor - 1) * STOREY_HEIGHT_M + FLOOR_SLAB_M
        for row in range(3):
            for column in range(4):
                if row == 1 and column == 3:
                    continue
                result.extend(
                    _cafeteria_table_primitives(
                        f"cafeteria-{floor}-table-{row + 1}-{column + 1}",
                        18 + column * 7.4,
                        13 + row * 6.2,
                        floor_surface_z,
                    )
                )
        result.append(
            _box(
                f"cafeteria-{floor}-service-counter",
                (39.5, 28.7, floor_surface_z + 0.525),
                (11.5, 1.1, 1.05),
                "service-counter",
            )
        )
    return result


def _fence_primitives() -> list[CollisionPrimitive]:
    result: list[CollisionPrimitive] = []
    post_keys: set[tuple[float, float]] = set()
    lines = (
        (
            "fence-south-west",
            (FENCE_MIN_X, FENCE_MIN_Y),
            (-GATE_HALF_OPENING_M, FENCE_MIN_Y),
            26,
            (FENCE_POST_RADIUS_M, GATE_POST_RADIUS_M),
        ),
        (
            "fence-south-east",
            (GATE_HALF_OPENING_M, FENCE_MIN_Y),
            (FENCE_MAX_X, FENCE_MIN_Y),
            26,
            (GATE_POST_RADIUS_M, FENCE_POST_RADIUS_M),
        ),
        (
            "fence-north",
            (FENCE_MIN_X, FENCE_MAX_Y),
            (FENCE_MAX_X, FENCE_MAX_Y),
            58,
            (FENCE_POST_RADIUS_M, FENCE_POST_RADIUS_M),
        ),
        (
            "fence-west",
            (FENCE_MIN_X, FENCE_MIN_Y),
            (FENCE_MIN_X, FENCE_MAX_Y),
            44,
            (FENCE_POST_RADIUS_M, FENCE_POST_RADIUS_M),
        ),
        (
            "fence-east",
            (FENCE_MAX_X, FENCE_MIN_Y),
            (FENCE_MAX_X, FENCE_MAX_Y),
            44,
            (FENCE_POST_RADIUS_M, FENCE_POST_RADIUS_M),
        ),
    )
    for line_id, start, end, segment_count, endpoint_radii in lines:
        points: list[tuple[float, float, float]] = []
        for index in range(segment_count + 1):
            ratio = index / segment_count
            point_x = start[0] + (end[0] - start[0]) * ratio
            point_y = start[1] + (end[1] - start[1]) * ratio
            radius = (
                endpoint_radii[0]
                if index == 0
                else endpoint_radii[1]
                if index == segment_count
                else FENCE_POST_RADIUS_M
            )
            points.append((point_x, point_y, radius))
            key = (round(point_x, 6), round(point_y, 6))
            if radius == FENCE_POST_RADIUS_M and key not in post_keys:
                post_keys.add(key)
                result.append(
                    _cylinder(
                        f"{line_id}-post-{index + 1}",
                        (point_x, point_y, FENCE_POST_HEIGHT_M / 2),
                        FENCE_POST_RADIUS_M,
                        FENCE_POST_HEIGHT_M,
                        "fence-post",
                    )
                )
        for index, (start_point, end_point) in enumerate(
            zip(points[:-1], points[1:], strict=True),
            start=1,
        ):
            delta_x = end_point[0] - start_point[0]
            delta_y = end_point[1] - start_point[1]
            center_distance = math.hypot(delta_x, delta_y)
            rail_length = center_distance - start_point[2] - end_point[2]
            unit_x = delta_x / center_distance
            unit_y = delta_y / center_distance
            rail_center_distance = start_point[2] + rail_length / 2
            result.append(
                _box(
                    f"{line_id}-rail-{index}",
                    (
                        start_point[0] + unit_x * rail_center_distance,
                        start_point[1] + unit_y * rail_center_distance,
                        FENCE_RAIL_CENTER_Z_M,
                    ),
                    (rail_length, FENCE_RAIL_DEPTH_M, FENCE_RAIL_HEIGHT_M),
                    "fence-rail",
                    yaw_rad=math.atan2(delta_y, delta_x),
                )
            )
    gate_header_center_z = GATE_POST_HEIGHT_M + GATE_HEADER_HEIGHT_M / 2
    gate_header_width = GATE_HALF_OPENING_M * 2 + GATE_POST_RADIUS_M * 2
    result.extend(
        (
            _cylinder(
                "campus-main-gate-west",
                (-GATE_HALF_OPENING_M, FENCE_MIN_Y, GATE_POST_HEIGHT_M / 2),
                GATE_POST_RADIUS_M,
                GATE_POST_HEIGHT_M,
                "gate-post",
            ),
            _cylinder(
                "campus-main-gate-east",
                (GATE_HALF_OPENING_M, FENCE_MIN_Y, GATE_POST_HEIGHT_M / 2),
                GATE_POST_RADIUS_M,
                GATE_POST_HEIGHT_M,
                "gate-post",
            ),
            _box(
                "campus-main-gate-header",
                (0, FENCE_MIN_Y, gate_header_center_z),
                (gate_header_width, GATE_HEADER_DEPTH_M, GATE_HEADER_HEIGHT_M),
                "gate-header",
            ),
        )
    )
    return result


def _training_gate_primitives() -> list[CollisionPrimitive]:
    result: list[CollisionPrimitive] = []
    for index, (gate_x, gate_z, radius_m) in enumerate(TRAINING_GATES, start=1):
        result.append(
            _mesh(
                f"school-training-gate-{index}-ring",
                (gate_x, TRAINING_GATE_ROUTE_Y, gate_z),
                f"meshes/training-gate-{index}.obj",
                "training-gate-ring",
            )
        )
        ring_points = [
            (
                gate_x,
                TRAINING_GATE_ROUTE_Y
                + radius_m * math.cos(2 * math.pi * point_index / TRAINING_GATE_SEGMENT_COUNT),
                gate_z
                + radius_m * math.sin(2 * math.pi * point_index / TRAINING_GATE_SEGMENT_COUNT),
            )
            for point_index in range(TRAINING_GATE_SEGMENT_COUNT)
        ]
        for segment_index, start in enumerate(ring_points, start=1):
            end = ring_points[segment_index % TRAINING_GATE_SEGMENT_COUNT]
            result.append(
                _capsule_between(
                    f"school-training-gate-{index}-collision-segment-{segment_index}",
                    start,
                    end,
                    TRAINING_GATE_TUBE_RADIUS_M,
                    "training-gate-ring-collision",
                )
            )
        ring_contact_z = gate_z - TRAINING_GATE_TUBE_RADIUS_M
        post_height = ring_contact_z - TRAINING_GATE_BASE_HEIGHT_M
        for side_name, side in (("north", -1), ("south", 1)):
            support_y = TRAINING_GATE_ROUTE_Y + side * radius_m
            result.extend(
                (
                    _cylinder(
                        f"school-training-gate-{index}-post-{side_name}",
                        (
                            gate_x,
                            support_y,
                            TRAINING_GATE_BASE_HEIGHT_M + post_height / 2,
                        ),
                        TRAINING_GATE_SUPPORT_RADIUS_M,
                        post_height,
                        "training-gate-support",
                    ),
                    _box(
                        f"school-training-gate-{index}-foot-{side_name}",
                        (gate_x, support_y, TRAINING_GATE_BASE_HEIGHT_M / 2),
                        (0.52, 0.42, TRAINING_GATE_BASE_HEIGHT_M),
                        "training-gate-base",
                    ),
                )
            )
    return result


def _street_light_primitives() -> list[CollisionPrimitive]:
    lights: list[tuple[str, float, float, float]] = []
    for index, light_x in enumerate(
        (-50.0, -40.0, -30.0, -15.0, -5.0, 15.0, 25.0, 40.0, 50.0),
        start=1,
    ):
        lights.append((f"street-light-south-{index}", light_x, -14.4, 0.0))
        lights.append((f"street-light-north-{index}", light_x, -21.6, math.pi))
    courtyard_lights: tuple[Point2D, ...] = ((4.8, -4), (11.2, 8), (4.8, 21), (11.2, 31))
    for index, (light_x, light_y) in enumerate(courtyard_lights, start=1):
        lights.append(
            (
                f"street-light-courtyard-{index}",
                light_x,
                light_y,
                math.pi if index % 2 == 0 else 0.0,
            )
        )
    result: list[CollisionPrimitive] = []
    for light_id, light_x, light_y, yaw_rad in lights:
        direction_x = math.cos(yaw_rad)
        direction_y = math.sin(yaw_rad)
        result.extend(
            (
                _cylinder(
                    f"{light_id}-base",
                    (light_x, light_y, STREET_LIGHT_BASE_HEIGHT_M / 2),
                    STREET_LIGHT_BASE_RADIUS_M,
                    STREET_LIGHT_BASE_HEIGHT_M,
                    "street-light-base",
                ),
                _cylinder(
                    f"{light_id}-pole",
                    (
                        light_x,
                        light_y,
                        (STREET_LIGHT_BASE_HEIGHT_M + STREET_LIGHT_POLE_HEIGHT_M) / 2,
                    ),
                    STREET_LIGHT_POLE_RADIUS_M,
                    STREET_LIGHT_POLE_HEIGHT_M - STREET_LIGHT_BASE_HEIGHT_M,
                    "street-light-pole",
                ),
                _box(
                    f"{light_id}-arm",
                    (light_x + direction_x * 0.5, light_y + direction_y * 0.5, 4.35),
                    (STREET_LIGHT_ARM_LENGTH_M, 0.1, STREET_LIGHT_ARM_HEIGHT_M),
                    "street-light-arm",
                    yaw_rad=yaw_rad,
                ),
                _box(
                    f"{light_id}-lamp",
                    (light_x + direction_x * 1.08, light_y + direction_y * 1.08, 4.225),
                    (0.48, 0.3, 0.15),
                    "street-light-lamp",
                    yaw_rad=yaw_rad,
                ),
            )
        )
    return result


def _facility_primitives() -> list[CollisionPrimitive]:
    result: list[CollisionPrimitive] = [
        _box("bike-shelter-roof", (*BIKE_SHELTER_CENTER, 3.0), (18, 5.4, 0.22), "canopy"),
        _box("pickup-canopy", (*PICKUP_CENTER, 2.8), (7.4, 4.2, 0.18), "canopy"),
        _box("pickup-shelf", (48.5, 2.3, 0.525), (5.9, 0.65, 1.05), "pickup-shelf"),
        _cylinder(
            "takeout-drone-pad",
            (48.5, 0.35, PICKUP_PAD_THICKNESS_M / 2),
            PICKUP_PAD_RADIUS_M,
            PICKUP_PAD_THICKNESS_M,
            "pickup-pad",
        ),
        _box("guard-booth", (7.8, -39.5, 1.55), (4.2, 3.2, 3.1), "guard-booth"),
        _box("guard-booth-roof", (7.8, -39.5, 3.2), (4.8, 3.8, 0.2), "roof"),
        *_fence_primitives(),
        *_training_gate_primitives(),
        *_street_light_primitives(),
    ]
    for column_x in (-8.4, -2.8, 2.8, 8.4):
        for column_y in (-2.3, 2.3):
            result.append(
                _cylinder(
                    f"bike-shelter-column-{column_x:g}-{column_y:g}",
                    (
                        BIKE_SHELTER_CENTER[0] + column_x,
                        BIKE_SHELTER_CENTER[1] + column_y,
                        BIKE_SHELTER_COLUMN_HEIGHT_M / 2,
                    ),
                    BIKE_SHELTER_COLUMN_RADIUS_M,
                    BIKE_SHELTER_COLUMN_HEIGHT_M,
                    "canopy-column",
                )
            )
    for column_x in (-3.35, 3.35):
        for column_y in (-1.65, 1.65):
            result.append(
                _cylinder(
                    f"pickup-column-{column_x:g}-{column_y:g}",
                    (
                        PICKUP_CENTER[0] + column_x,
                        PICKUP_CENTER[1] + column_y,
                        PICKUP_COLUMN_HEIGHT_M / 2,
                    ),
                    PICKUP_COLUMN_RADIUS_M,
                    PICKUP_COLUMN_HEIGHT_M,
                    "canopy-column",
                )
            )
    for rack_index in range(9):
        rack_x = BIKE_SHELTER_CENTER[0] - 7.8 + rack_index * 1.95
        if rack_index % 2 == 0:
            result.append(
                _box(
                    f"bicycle-and-rack-{rack_index + 1}-conservative-envelope",
                    (rack_x, BIKE_SHELTER_CENTER[1] + 0.28, 0.62),
                    (1.84, 0.12, 1.24),
                    "conservative-bicycle-and-rack-envelope",
                )
            )
        else:
            result.append(
                _box(
                    f"bike-rack-{rack_index + 1}-conservative-envelope",
                    (rack_x, BIKE_SHELTER_CENTER[1], 0.5),
                    (1.04, 0.12, 1.0),
                    "conservative-bike-rack-envelope",
                )
            )
    return result


def school_map_collision_primitives() -> list[CollisionPrimitive]:
    primitives: list[CollisionPrimitive] = [
        _box("school-map-ground", (0, 0, -0.09), (120, 90, 0.18), "terrain"),
        *_teaching_floor_primitives(),
        *_teaching_room_primitives(),
        *_teaching_furniture_primitives(),
        *_switchback_stair_primitives("teaching", -0.1, 10.5, (1, 2)),
        *_cafeteria_primitives(),
        *_cafeteria_furniture_primitives(),
        *_switchback_stair_primitives("cafeteria", 40, 20, (1,)),
        *_facility_primitives(),
    ]
    for index, (tree_x, tree_y) in enumerate(TREE_POSITIONS, start=1):
        tree_height = 4.8 + ((index - 1) % 4) * 0.45
        trunk_height = tree_height * 0.48
        primitives.append(
            _cylinder(
                f"campus-tree-{index}-trunk",
                (tree_x, tree_y, trunk_height / 2),
                TREE_TRUNK_RADIUS_M,
                trunk_height,
                "tree-trunk",
            )
        )
        for crown_index, (offset_x, offset_y, radius_m) in enumerate(
            ((0.0, 0.0, 1.25), (-0.7, 0.12, 0.95), (0.66, 0.2, 1.0), (0.1, -0.65, 0.92)),
            start=1,
        ):
            primitives.append(
                _sphere(
                    f"campus-tree-{index}-crown-{crown_index}",
                    (
                        tree_x + offset_x,
                        tree_y + offset_y,
                        trunk_height + 1.25 + (crown_index - 1) * 0.13,
                    ),
                    radius_m,
                    "tree-crown",
                )
            )
    return primitives


def _model_for(
    primitives: list[CollisionPrimitive],
    *,
    include_visuals: bool,
) -> ElementTree.Element:
    model = ElementTree.Element("model", {"name": "school_map"})
    ElementTree.SubElement(model, "static").text = "true"
    link = ElementTree.SubElement(model, "link", {"name": "school-map-static-geometry"})
    ElementTree.SubElement(link, "self_collide").text = "false"
    semantic_colors = {
        "terrain": "0.36 0.52 0.34 1",
        "floor": "0.72 0.71 0.75 1",
        "exterior-wall": "0.78 0.72 0.64 1",
        "interior-wall": "0.84 0.78 0.7 1",
        "window-glazing": "0.42 0.72 0.82 0.42",
        "window-frame": "0.82 0.82 0.8 1",
        "closed-door-leaf": "0.48 0.31 0.22 1",
        "open-door-leaf": "0.48 0.31 0.22 1",
        "stair-tread": "0.62 0.62 0.65 1",
        "stair-landing": "0.62 0.62 0.65 1",
        "tree-trunk": "0.28 0.16 0.09 1",
        "tree-crown": "0.18 0.46 0.2 1",
        "training-gate-ring": "0.4 0.24 0.85 1",
    }
    for primitive in primitives:
        element_names: tuple[str, ...]
        if isinstance(primitive, MeshPrimitive):
            element_names = ("visual",) if include_visuals else ()
        elif isinstance(primitive, CapsulePrimitive) or not include_visuals:
            element_names = ("collision",)
        else:
            element_names = ("collision", "visual")
        for element_name in element_names:
            element = ElementTree.SubElement(
                link,
                element_name,
                {"name": f"{primitive.name}-{element_name}"},
            )
            ElementTree.SubElement(element, "pose").text = (
                f"{primitive.center_x:g} {primitive.center_y:g} {primitive.center_z:g} "
                f"{primitive.roll_rad:g} {primitive.pitch_rad:g} {primitive.yaw_rad:g}"
            )
            geometry = ElementTree.SubElement(element, "geometry")
            if isinstance(primitive, BoxPrimitive):
                box = ElementTree.SubElement(geometry, "box")
                ElementTree.SubElement(
                    box, "size"
                ).text = f"{primitive.size_x:g} {primitive.size_y:g} {primitive.size_z:g}"
            elif isinstance(primitive, CylinderPrimitive):
                cylinder = ElementTree.SubElement(geometry, "cylinder")
                ElementTree.SubElement(cylinder, "radius").text = f"{primitive.radius_m:g}"
                ElementTree.SubElement(cylinder, "length").text = f"{primitive.height_m:g}"
            elif isinstance(primitive, CapsulePrimitive):
                capsule = ElementTree.SubElement(geometry, "capsule")
                ElementTree.SubElement(capsule, "radius").text = f"{primitive.radius_m:g}"
                ElementTree.SubElement(capsule, "length").text = f"{primitive.length_m:g}"
            elif isinstance(primitive, SpherePrimitive):
                sphere = ElementTree.SubElement(geometry, "sphere")
                ElementTree.SubElement(sphere, "radius").text = f"{primitive.radius_m:g}"
            else:
                mesh = ElementTree.SubElement(geometry, "mesh")
                ElementTree.SubElement(mesh, "uri").text = primitive.uri
                ElementTree.SubElement(
                    mesh, "scale"
                ).text = f"{primitive.scale_x:g} {primitive.scale_y:g} {primitive.scale_z:g}"
            if element_name == "visual":
                material = ElementTree.SubElement(element, "material")
                color = semantic_colors.get(primitive.semantic, "0.56 0.55 0.58 1")
                ElementTree.SubElement(material, "ambient").text = color
                ElementTree.SubElement(material, "diffuse").text = color
                if primitive.semantic == "window-glazing":
                    ElementTree.SubElement(element, "transparency").text = "0.58"
                    ElementTree.SubElement(element, "cast_shadows").text = "false"
                if primitive.name == "school-map-ground":
                    pbr = ElementTree.SubElement(material, "pbr")
                    metal = ElementTree.SubElement(pbr, "metal")
                    ElementTree.SubElement(
                        metal, "albedo_map"
                    ).text = "materials/textures/campus-surface.ppm"
                    ElementTree.SubElement(metal, "roughness").text = "0.94"
                    ElementTree.SubElement(metal, "metalness").text = "0"
    ElementTree.SubElement(link, "enable_wind").text = "false"
    return model


def _sdf_for(model: ElementTree.Element) -> str:
    sdf = ElementTree.Element("sdf", {"version": "1.9"})
    sdf.append(deepcopy(model))
    return ElementTree.tostring(sdf, encoding="unicode", xml_declaration=False)


def _model_config() -> str:
    return (
        '<?xml version="1.0"?>\n'
        "<model>\n"
        "  <name>School Map</name>\n"
        "  <version>1.0.0</version>\n"
        '  <sdf version="1.9">model.sdf</sdf>\n'
        "  <author><name>DroneDream</name></author>\n"
        "  <description>Content-addressed School Map static simulation asset.</description>\n"
        "</model>\n"
    )


def _world_sdf(model: ElementTree.Element) -> str:
    sdf = ElementTree.Element("sdf", {"version": "1.9"})
    world = ElementTree.SubElement(sdf, "world", {"name": "school_map_world"})
    ElementTree.SubElement(world, "gravity").text = "0 0 -9.80665"
    ElementTree.SubElement(world, "magnetic_field").text = "6e-06 2.3e-05 -4.2e-05"
    ElementTree.SubElement(world, "atmosphere", {"type": "adiabatic"})
    physics = ElementTree.SubElement(
        world,
        "physics",
        {"name": "school-map-physics", "type": "ode"},
    )
    # Four milliseconds keeps the PX4 control clock real-time qualified on the
    # bundled WSL runtime. Designated landing contact has its own measured
    # solver tolerance; every School Map interface remains geometrically exact.
    ElementTree.SubElement(physics, "max_step_size").text = "0.004"
    ElementTree.SubElement(physics, "real_time_factor").text = "1"
    ElementTree.SubElement(physics, "real_time_update_rate").text = "250"
    scene = ElementTree.SubElement(world, "scene")
    ElementTree.SubElement(scene, "grid").text = "false"
    ElementTree.SubElement(scene, "ambient").text = "0.42 0.44 0.48 1"
    ElementTree.SubElement(scene, "background").text = "0.72 0.81 0.9 1"
    ElementTree.SubElement(scene, "shadows").text = "true"
    spherical = ElementTree.SubElement(world, "spherical_coordinates")
    ElementTree.SubElement(spherical, "surface_model").text = "EARTH_WGS84"
    ElementTree.SubElement(spherical, "world_frame_orientation").text = "ENU"
    ElementTree.SubElement(spherical, "latitude_deg").text = "30.27415"
    ElementTree.SubElement(spherical, "longitude_deg").text = "120.15515"
    ElementTree.SubElement(spherical, "elevation").text = "12"
    sun = ElementTree.SubElement(world, "light", {"type": "directional", "name": "sun"})
    ElementTree.SubElement(sun, "cast_shadows").text = "true"
    ElementTree.SubElement(sun, "pose").text = "0 0 20 0 0 0"
    ElementTree.SubElement(sun, "diffuse").text = "0.9 0.88 0.82 1"
    ElementTree.SubElement(sun, "specular").text = "0.2 0.2 0.2 1"
    ElementTree.SubElement(sun, "direction").text = "-0.45 0.35 -0.82"
    world.append(deepcopy(model))
    return ElementTree.tostring(sdf, encoding="unicode", xml_declaration=False)


def _ros_gz_bridge_yaml() -> str:
    return (
        "- ros_topic_name: /clock\n"
        "  gz_topic_name: /clock\n"
        "  ros_type_name: rosgraph_msgs/msg/Clock\n"
        "  gz_type_name: gz.msgs.Clock\n"
        "  direction: GZ_TO_ROS\n"
    )


def _runtime_readme() -> str:
    return """# School Map simulation package

This package is generated from the content-addressed DroneDream School Map geometry contract.

## Gazebo Sim

```sh
gz sdf -k model.sdf
gz sdf -k world.sdf
gz sdf -k model.physics.sdf
gz sdf -k world.physics.sdf
gz sim -r world.sdf
```

`world.sdf` embeds the static map model and resolves the relative `meshes/` and `materials/`
assets from this directory. `model.config` also allows the directory to be installed as a
Gazebo model package. `world.physics.sdf` contains the exact same collision primitives without
render visuals for deterministic headless PX4 qualification; the visible desktop run uses
`world.sdf`.

## ROS 2 bridge

The static map does not require ROS to exist in Gazebo. With a compatible ROS 2 and
`ros_gz_bridge` installation, bridge simulation time with:

```sh
ros2 run ros_gz_bridge parameter_bridge --ros-args \
  -p config_file:="$(pwd)/ros_gz_bridge.yaml"
```

Vehicle, camera, depth, odometry and control topics must be added by the signed Runtime for
the exact PX4 vehicle and sensor pack. This package does not claim that ROS 2 or PX4 mission
execution has been smoke-tested.
"""


def _canonicalize_semantic_value(value: object) -> object:
    """Project semantic JSON onto a cross-platform, content-addressable form.

    The collision compiler retains its native floats for SDF generation and
    clearance calculations. Only the semantic JSON projection is rounded,
    because equivalent libm trigonometry can differ by a few units in the last
    place across operating systems. Twelve decimal places is nine orders of
    magnitude tighter than the declared one-millimetre structural tolerance.
    """

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("School Map semantic values must be finite")
        rounded = round(value, SEMANTIC_FLOAT_DECIMAL_PLACES)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, dict):
        return {key: _canonicalize_semantic_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_semantic_value(item) for item in value]
    return value


@lru_cache(maxsize=1)
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
            "route_center_above_tread_m": STAIR_ROUTE_CENTER_ABOVE_TREAD_M,
        },
        "vehicle_clearance": {
            "collision_diameter_m": VEHICLE_COLLISION_DIAMETER_M,
            "collision_height_m": VEHICLE_COLLISION_HEIGHT_M,
            "collision_center_above_contact_m": VEHICLE_COLLISION_CENTER_ABOVE_CONTACT_M,
            "px4_x500_model_root_to_contact_m": PX4_X500_MODEL_ROOT_TO_CONTACT_M,
            "minimum_road_width_m": 4.8,
            "minimum_indoor_width_m": 1.6,
            "minimum_open_door_clearance_m": TEACHING_OPEN_DOOR_CLEARANCE_M,
            "gazebo_vehicle_model": MY_DRONE_MODEL_NAME,
            "dry_mass_kg": PX4_X500_DRY_MASS_KG,
            "maximum_thrust_n": PX4_X500_MAXIMUM_THRUST_N,
            "minimum_qualified_thrust_to_weight": (PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT),
            "mission_payload_mass_kg": TAKEOUT_PAYLOAD_MASS_KG,
            "loaded_thrust_to_weight": px4_x500_loaded_thrust_to_weight(TAKEOUT_PAYLOAD_MASS_KG),
        },
        "simulation_bindings": {
            "gazebo_world_file": "world.sdf",
            "gazebo_headless_physics_world_file": "world.physics.sdf",
            "gazebo_model_file": "model.sdf",
            "gazebo_headless_physics_model_file": "model.physics.sdf",
            "gazebo_model_name": "school_map",
            "ros_gz_bridge_config": "ros_gz_bridge.yaml",
            "px4_gz_bridge_axis_mapping": {
                "gazebo_x_school_map_east": "px4_local_east_executor_y",
                "gazebo_y_school_map_north": "px4_local_north_executor_x",
                "gazebo_z_school_map_up": "negative_px4_local_down_executor_z_up",
            },
            "px4_recommended_spawn": {
                "x": -42.25,
                "y": 15.3,
                "z": 7.5 - PX4_X500_MODEL_ROOT_TO_CONTACT_M,
                "yaw_rad": math.pi,
                "surface": "office-drone-launch-pad",
                "pose_reference": "px4-x500-model-root",
                "contact_surface_offset_z": PX4_X500_MODEL_ROOT_TO_CONTACT_M,
            },
            "mission_waypoint_reference": "vehicle-collision-envelope-center",
            "vehicle_collision_center_offset": {
                "x": 0.0,
                "y": 0.0,
                "z": PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M,
            },
            "mission_launch_waypoint": {"x": -42.25, "y": 15.3, "z": 8.15},
            "mission_pickup_waypoint": {
                "x": PICKUP_ROUTE_CENTER[0],
                "y": PICKUP_ROUTE_CENTER[1],
                "z": PICKUP_ROUTE_ENVELOPE_CENTER_Z_M,
            },
            "takeout_payload": {
                "mass_kg": TAKEOUT_PAYLOAD_MASS_KG,
                "size_m": TAKEOUT_PAYLOAD_SIZE_M,
                "center_above_px4_model_root_m": (TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M),
                "attachment": "gazebo-detachable-fixed-joint",
            },
        },
        "training_gate_collision": {
            "visual_geometry": "closed-manifold-torus-mesh",
            "collision_geometry": "gazebo-native-capsule-chain",
            "segments_per_gate": TRAINING_GATE_SEGMENT_COUNT,
            "maximum_centerline_error_m": TRAINING_GATE_COLLISION_MAX_ERROR_M,
            "default_dart_engine_compatible": True,
        },
        "roads": ROAD_NETWORK,
        "pedestrian_paths": PEDESTRIAN_PATHS,
        "road_markings": ROAD_MARKINGS,
        "crosswalks": CROSSWALKS,
        "collision_primitives": [
            primitive.__dict__
            for primitive in primitives
            if not isinstance(primitive, MeshPrimitive)
        ],
        "visual_only_primitives": [
            primitive.__dict__ for primitive in primitives if isinstance(primitive, MeshPrimitive)
        ],
        "geometry_scope": [
            "terrain",
            "single-textured-road-path-crosswalk-surface",
            "building-shells-and-floor-openings",
            "interior-room-walls-window-frames-glazing-and-door-states",
            "classroom-office-and-cafeteria-fixed-furniture",
            "teaching-and-cafeteria-switchback-stairs",
            "entrance-steps-and-thresholds",
            "door-frames-and-open-closed-door-leaves",
            "canopies-and-columns",
            "street-light-bases-poles-arms-and-lamps",
            "tree-trunks-and-crowns",
            "perimeter-fence-and-main-gate",
            "closed-manifold-training-gate-visual-meshes-native-capsule-collisions-and-supports",
            "launch-and-pickup-pads",
        ],
        "known_export_limits": [
            (
                "Curved bicycle racks and bicycle frames use named conservative collision "
                "envelopes; their finer rendered tubes remain visual-only."
            ),
            (
                "Training-gate torus visuals use closed-manifold meshes; default-DART-compatible "
                "capsule collision chains bound centerline error to "
                f"{TRAINING_GATE_COLLISION_MAX_ERROR_M:.6f} m."
            ),
            "Dynamic people are runtime-spawned semantic actors, not static map collisions.",
            "Occupancy and ESDF layers must be generated and smoke-tested by the signed Runtime.",
        ],
        "dynamic_people": {
            "static_collision_present": False,
            "runtime_spawn_required": True,
            "semantic_class": "person",
        },
        "execution": {
            "gazebo_asset_contract_generated": True,
            "gazebo_cli_validation_required": True,
            "gazebo_runtime_verified": False,
            "px4_mission_smoke_verified": False,
            "simulation_execution_ready": False,
        },
    }
    canonical_semantic = _canonicalize_semantic_value(semantic)
    semantic_json = json.dumps(
        canonical_semantic,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    model = _model_for(primitives, include_visuals=True)
    physics_model = _model_for(primitives, include_visuals=False)
    model_sdf = _sdf_for(model)
    physics_model_sdf = _sdf_for(physics_model)
    world_sdf = _world_sdf(model)
    physics_world_sdf = _world_sdf(physics_model)
    model_config = _model_config()
    mesh_files = {
        f"meshes/training-gate-{index}.obj": _torus_obj(radius_m, TRAINING_GATE_TUBE_RADIUS_M)
        for index, (_, _, radius_m) in enumerate(TRAINING_GATES, start=1)
    }
    mesh_files["meshes/training-gate.mtl"] = _torus_mtl()
    mesh_files["materials/textures/campus-surface.ppm"] = _campus_surface_ppm()
    package_files = {
        "model.sdf": model_sdf,
        "model.physics.sdf": physics_model_sdf,
        "model.config": model_config,
        "world.sdf": world_sdf,
        "world.physics.sdf": physics_world_sdf,
        "README.md": _runtime_readme(),
        "ros_gz_bridge.yaml": _ros_gz_bridge_yaml(),
        "semantic.json": semantic_json,
        **mesh_files,
    }
    package_hashes = {
        name: hashlib.sha256(content.encode()).hexdigest()
        for name, content in package_files.items()
    }
    sdf_sha = hashlib.sha256(model_sdf.encode()).hexdigest()
    semantic_sha = hashlib.sha256(semantic_json.encode()).hexdigest()
    package_manifest_sha = hashlib.sha256(
        json.dumps(package_hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    summary = {
        "schema_version": "dronedream.autonomy.gazebo-artifact-summary.v1",
        "format": "sdf",
        "sdf_version": "1.9",
        "model_sdf_sha256": sdf_sha,
        "semantic_sha256": semantic_sha,
        "world_sdf_sha256": package_hashes["world.sdf"],
        "physics_world_sdf_sha256": package_hashes["world.physics.sdf"],
        "physics_model_sdf_sha256": package_hashes["model.physics.sdf"],
        "model_config_sha256": package_hashes["model.config"],
        "package_file_sha256": package_hashes,
        "package_manifest_sha256": package_manifest_sha,
        "package_file_count": len(package_files),
        "collision_primitive_count": sum(
            not isinstance(primitive, MeshPrimitive) for primitive in primitives
        ),
        "visual_primitive_count": sum(
            not isinstance(primitive, CapsulePrimitive) for primitive in primitives
        ),
        "geometry_scope": "simulation-static-scene-v2",
        "known_export_limit_count": len(semantic["known_export_limits"]),
        "gazebo_asset_contract_generated": True,
        "gazebo_cli_validation_required": True,
        "gazebo_runtime_verified": False,
        "px4_mission_smoke_verified": False,
        "simulation_execution_ready": False,
    }
    if summary != SCHOOL_MAP_GAZEBO_ARTIFACT_SUMMARY:
        raise RuntimeError(
            "School Map package identity changed; regenerate and review the pinned Gazebo summary"
        )
    return SchoolMapGazeboArtifact(model_sdf, semantic_json, summary, package_files)


def export_school_map_gazebo_artifact(output_directory: Path) -> dict[str, str]:
    artifact = get_school_map_gazebo_artifact()
    output_directory.mkdir(parents=True, exist_ok=True)
    files = {
        **artifact.package_files,
        "summary.json": json.dumps(artifact.summary, indent=2, sort_keys=True) + "\n",
    }
    for name, content in files.items():
        output_path = output_directory / name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8", newline="\n")
    return {name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()}
