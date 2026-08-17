"""Deterministic complex-terrain catalog with prevalidated reference corridors."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from app.autonomy.models import RoutePoint, TerrainObject, TerrainScene, Vector3
from app.autonomy.school_map_artifact import (
    OFFICE_DOOR_CENTER_X,
    PICKUP_ROUTE_CENTER,
    PICKUP_ROUTE_ENVELOPE_CENTER_Z_M,
    TEACHING_OPEN_DOOR_PAIR_CENTER_X,
    get_school_map_gazebo_artifact,
    school_map_stair_route_points,
)


def _p(
    x: float,
    y: float,
    z: float,
    phase: Literal["launch", "transit", "stairs", "gate", "pickup", "return", "land"],
    speed: float = 1.3,
) -> RoutePoint:
    return RoutePoint(x=x, y=y, z=z, phase=phase, speed_limit_mps=speed)


SCENES: dict[str, TerrainScene] = {
    "school-campus-v1": TerrainScene(
        id="school-campus-v1",
        name="School Map",
        summary=(
            "Three-floor teaching building with navigable 12+12 switchback stairs, "
            "classrooms and an office launch point; a two-floor cafeteria, guarded campus "
            "gate, roads, bicycle shelter, vegetation, street furniture and takeout pickup."
        ),
        bounds_m=Vector3(x=120.0, y=90.0, z=12.6),
        floors=3,
        minimum_clearance_m=0.82,
        tags=[
            "school",
            "indoor-outdoor",
            "switchback-stairs",
            "classrooms",
            "office",
            "cafeteria",
            "roads",
            "dynamic-people",
            "payload",
            "return",
        ],
        objects=[
            TerrainObject(
                id="teaching-building",
                kind="building",
                center=Vector3(x=-25.0, y=13.0, z=5.4),
                size=Vector3(x=56.0, y=22.0, z=10.8),
            ),
            TerrainObject(
                id="teaching-stairwell",
                kind="stairwell",
                center=Vector3(x=-0.1, y=10.5, z=5.4),
                size=Vector3(x=4.2, y=6.6, z=10.8),
                traversable=True,
                required_clearance_m=0.8,
            ),
            TerrainObject(
                id="third-floor-autonomy-office",
                kind="office",
                center=Vector3(x=-45.25, y=14.95, z=9.0),
                size=Vector3(x=11.5, y=8.7, z=3.25),
                traversable=True,
                required_clearance_m=0.7,
            ),
            TerrainObject(
                id="classroom-blocks",
                kind="classroom",
                center=Vector3(x=-24.0, y=15.0, z=5.4),
                size=Vector3(x=44.0, y=8.7, z=10.4),
                traversable=True,
                required_clearance_m=0.68,
            ),
            TerrainObject(
                id="cafeteria",
                kind="cafeteria",
                center=Vector3(x=30.0, y=20.0, z=3.6),
                size=Vector3(x=34.0, y=25.0, z=7.2),
                traversable=True,
                required_clearance_m=0.75,
            ),
            TerrainObject(
                id="campus-road-network",
                kind="road",
                center=Vector3(x=0.0, y=-3.8, z=0.1),
                size=Vector3(x=110.0, y=78.4, z=0.2),
                traversable=True,
                required_clearance_m=1.2,
            ),
            TerrainObject(
                id="teaching-main-open-door-pair",
                kind="door",
                center=Vector3(x=-27.1, y=1.92, z=1.5),
                size=Vector3(x=4.1, y=0.2, z=3.0),
                traversable=True,
                required_clearance_m=1.9,
            ),
            TerrainObject(
                id="cafeteria-main-entrance",
                kind="door",
                center=Vector3(x=30.0, y=7.5, z=1.45),
                size=Vector3(x=7.5, y=0.2, z=2.9),
                traversable=False,
                required_clearance_m=1.1,
            ),
            TerrainObject(
                id="campus-perimeter",
                kind="fence",
                center=Vector3(x=0.0, y=0.0, z=0.9),
                size=Vector3(x=118.0, y=88.0, z=1.8),
            ),
            TerrainObject(
                id="south-gate-guard-booth",
                kind="guard-booth",
                center=Vector3(x=7.8, y=-39.5, z=1.55),
                size=Vector3(x=4.2, y=3.2, z=3.1),
            ),
            TerrainObject(
                id="teaching-bicycle-shelter",
                kind="bicycle-shelter",
                center=Vector3(x=-42.0, y=30.2, z=1.5),
                size=Vector3(x=18.0, y=5.4, z=3.0),
            ),
            TerrainObject(
                id="campus-takeout-pickup",
                kind="pickup",
                center=Vector3(x=48.5, y=1.5, z=1.4),
                size=Vector3(x=7.4, y=4.2, z=2.8),
                traversable=True,
                required_clearance_m=0.8,
            ),
            TerrainObject(
                id="office-drone-launch",
                kind="launch",
                center=Vector3(x=-42.25, y=15.3, z=7.46),
                size=Vector3(x=1.7, y=1.7, z=0.08),
                traversable=True,
                required_clearance_m=0.75,
            ),
            TerrainObject(
                id="roadside-tree-belt",
                kind="tree",
                center=Vector3(x=0.0, y=-18.0, z=3.0),
                size=Vector3(x=106.0, y=13.0, z=6.0),
            ),
            TerrainObject(
                id="roadside-light-belt",
                kind="street-light",
                center=Vector3(x=0.0, y=-18.0, z=2.2),
                size=Vector3(x=106.0, y=8.0, z=4.4),
            ),
        ],
        reference_path=[
            _p(-42.25, 15.3, 8.15, "launch", 0.55),
            _p(-42.25, 11.5, 8.15, "transit", 0.55),
            _p(OFFICE_DOOR_CENTER_X, 11.0, 8.15, "transit", 0.55),
            _p(OFFICE_DOOR_CENTER_X, 9.75, 8.15, "transit", 0.55),
            _p(-35.0, 8.02, 8.12, "transit", 0.8),
            _p(-14.0, 8.02, 8.08, "transit", 0.9),
            _p(-4.0, 8.02, 8.05, "transit", 0.65),
            *[
                _p(x, y, z, "stairs", 0.42)
                for x, y, z in school_map_stair_route_points("descending")
            ],
            _p(-3.0, 8.02, 1.05, "transit", 0.55),
            _p(-8.0, 5.0, 1.25, "transit", 0.65),
            _p(TEACHING_OPEN_DOOR_PAIR_CENTER_X, 2.7, 1.35, "transit", 0.7),
            _p(TEACHING_OPEN_DOOR_PAIR_CENTER_X, -1.055, 1.45, "transit", 0.7),
            _p(-25.0, -9.0, 1.55, "transit", 0.9),
            _p(-25.0, -18.0, 1.65, "transit", 1.0),
            _p(0.0, -18.0, 1.8, "transit", 1.1),
            _p(30.0, -18.0, 1.8, "transit", 1.1),
            _p(39.0, -12.0, 1.7, "transit", 0.9),
            _p(46.0, -5.0, 1.55, "transit", 0.75),
            _p(
                PICKUP_ROUTE_CENTER[0],
                PICKUP_ROUTE_CENTER[1],
                PICKUP_ROUTE_ENVELOPE_CENTER_Z_M,
                "pickup",
                0.4,
            ),
            _p(46.0, -5.0, 1.55, "return", 0.75),
            _p(39.0, -12.0, 1.7, "return", 0.9),
            _p(30.0, -18.0, 1.8, "return", 1.0),
            _p(0.0, -18.0, 1.8, "return", 1.0),
            _p(-25.0, -18.0, 1.65, "return", 0.9),
            _p(-25.0, -9.0, 1.55, "return", 0.8),
            _p(TEACHING_OPEN_DOOR_PAIR_CENTER_X, -1.055, 1.45, "return", 0.7),
            _p(TEACHING_OPEN_DOOR_PAIR_CENTER_X, 2.7, 1.35, "return", 0.7),
            _p(-8.0, 5.0, 1.25, "return", 0.65),
            _p(-3.0, 8.02, 1.05, "return", 0.55),
            *[
                _p(x, y, z, "stairs", 0.42)
                for x, y, z in school_map_stair_route_points("ascending")
            ],
            _p(-4.0, 8.02, 8.05, "return", 0.65),
            _p(-14.0, 8.02, 8.08, "return", 0.8),
            _p(-35.0, 8.02, 8.12, "return", 0.8),
            _p(OFFICE_DOOR_CENTER_X, 9.75, 8.15, "return", 0.55),
            _p(OFFICE_DOOR_CENTER_X, 11.0, 8.15, "return", 0.55),
            _p(-42.25, 11.5, 8.15, "return", 0.55),
            _p(-42.25, 15.3, 8.15, "land", 0.3),
        ],
    ),
    "stairwell-coffee-return": TerrainScene(
        id="stairwell-coffee-return",
        name="Multi-level coffee pickup",
        summary=(
            "Third-floor office, narrow stairwell, lobby exit, obstacle-rich courtyard, "
            "pickup and loaded return."
        ),
        bounds_m=Vector3(x=42.0, y=28.0, z=11.0),
        floors=3,
        minimum_clearance_m=0.92,
        tags=["stairs", "indoor-outdoor", "trees", "signs", "payload", "return"],
        objects=[
            TerrainObject(
                id="office-block",
                kind="building",
                center=Vector3(x=6, y=14, z=5.5),
                size=Vector3(x=10, y=24, z=11),
            ),
            TerrainObject(
                id="stairwell",
                kind="stairwell",
                center=Vector3(x=14, y=10, z=5.5),
                size=Vector3(x=5, y=8, z=11),
                traversable=True,
                required_clearance_m=0.55,
            ),
            TerrainObject(
                id="courtyard-building",
                kind="building",
                center=Vector3(x=31, y=23, z=5),
                size=Vector3(x=17, y=7, z=10),
            ),
            TerrainObject(
                id="tree-a",
                kind="tree",
                center=Vector3(x=24, y=8, z=3.5),
                size=Vector3(x=2.2, y=2.2, z=7),
            ),
            TerrainObject(
                id="tree-b",
                kind="tree",
                center=Vector3(x=33, y=9, z=3.0),
                size=Vector3(x=2.0, y=2.0, z=6),
            ),
            TerrainObject(
                id="sign-a",
                kind="sign",
                center=Vector3(x=27, y=15, z=1.3),
                size=Vector3(x=2.4, y=0.4, z=2.6),
            ),
            TerrainObject(
                id="pole-a",
                kind="pole",
                center=Vector3(x=36, y=14, z=2.5),
                size=Vector3(x=0.5, y=0.5, z=5),
            ),
            TerrainObject(
                id="coffee-dock",
                kind="pickup",
                center=Vector3(x=39, y=5, z=1.2),
                size=Vector3(x=1.4, y=1.4, z=1.2),
                traversable=True,
            ),
        ],
        reference_path=[
            _p(3, 13, 8.6, "launch", 0.8),
            _p(8, 13, 8.6, "transit"),
            _p(12, 12, 8.4, "transit"),
            _p(14, 12, 7.2, "stairs", 0.7),
            _p(16, 10, 5.7, "stairs", 0.65),
            _p(14, 8, 4.3, "stairs", 0.65),
            _p(16, 6, 2.8, "stairs", 0.65),
            _p(18, 5, 1.5, "stairs", 0.7),
            _p(22, 4, 1.6, "transit"),
            _p(28, 4, 1.9, "transit"),
            _p(34, 4, 1.8, "transit"),
            _p(39, 5, 1.2, "pickup", 0.45),
            _p(35, 6, 1.8, "return", 1.0),
            _p(29, 6, 2.0, "return"),
            _p(22, 5, 1.6, "return"),
            _p(18, 5, 1.5, "return", 0.8),
            _p(16, 6, 2.8, "stairs", 0.6),
            _p(14, 8, 4.3, "stairs", 0.6),
            _p(16, 10, 5.7, "stairs", 0.6),
            _p(14, 12, 7.2, "stairs", 0.6),
            _p(12, 12, 8.4, "return", 0.9),
            _p(8, 13, 8.6, "return", 0.8),
            _p(3, 13, 8.4, "land", 0.4),
        ],
    ),
    "forest-gate-inspection": TerrainScene(
        id="forest-gate-inspection",
        name="Forest gate inspection",
        summary=(
            "Unknown vegetation corridor with three centered gates, poles and a final "
            "inspection hover."
        ),
        bounds_m=Vector3(x=48, y=24, z=8),
        floors=1,
        minimum_clearance_m=1.15,
        tags=["vision", "gates", "trees", "unknown-space"],
        objects=[
            TerrainObject(
                id="tree-1",
                kind="tree",
                center=Vector3(x=12, y=6, z=3),
                size=Vector3(x=2, y=2, z=6),
            ),
            TerrainObject(
                id="tree-2",
                kind="tree",
                center=Vector3(x=21, y=17, z=3.5),
                size=Vector3(x=2.4, y=2.4, z=7),
            ),
            TerrainObject(
                id="tree-3",
                kind="tree",
                center=Vector3(x=34, y=7, z=3),
                size=Vector3(x=2, y=2, z=6),
            ),
            TerrainObject(
                id="gate-1",
                kind="gate",
                center=Vector3(x=15, y=12, z=2.4),
                size=Vector3(x=0.4, y=3.4, z=3.4),
                traversable=True,
                required_clearance_m=0.45,
            ),
            TerrainObject(
                id="gate-2",
                kind="gate",
                center=Vector3(x=27, y=12, z=2.8),
                size=Vector3(x=0.4, y=3.6, z=3.6),
                traversable=True,
                required_clearance_m=0.5,
            ),
            TerrainObject(
                id="gate-3",
                kind="gate",
                center=Vector3(x=39, y=12, z=2.3),
                size=Vector3(x=0.4, y=3.2, z=3.2),
                traversable=True,
                required_clearance_m=0.42,
            ),
        ],
        reference_path=[
            _p(3, 12, 1.2, "launch", 0.8),
            _p(9, 12, 2.2, "transit"),
            _p(15, 12, 2.4, "gate", 0.9),
            _p(21, 12, 2.6, "transit"),
            _p(27, 12, 2.8, "gate", 0.9),
            _p(33, 12, 2.5, "transit"),
            _p(39, 12, 2.3, "gate", 0.9),
            _p(45, 12, 2.0, "land", 0.5),
        ],
    ),
    "service-corridor-dock": TerrainScene(
        id="service-corridor-dock",
        name="Service corridor docking",
        summary=(
            "Confined indoor corridor with vertical signs, blind corners and a precision "
            "docking target."
        ),
        bounds_m=Vector3(x=34, y=18, z=5),
        floors=1,
        minimum_clearance_m=0.78,
        tags=["narrow", "indoor", "blind-corner", "docking"],
        objects=[
            TerrainObject(
                id="wall-a",
                kind="wall",
                center=Vector3(x=10, y=4, z=2.5),
                size=Vector3(x=14, y=0.4, z=5),
            ),
            TerrainObject(
                id="wall-b",
                kind="wall",
                center=Vector3(x=18, y=14, z=2.5),
                size=Vector3(x=18, y=0.4, z=5),
            ),
            TerrainObject(
                id="sign-b",
                kind="sign",
                center=Vector3(x=19, y=8, z=1.4),
                size=Vector3(x=0.4, y=2.2, z=2.8),
            ),
            TerrainObject(
                id="dock",
                kind="landing",
                center=Vector3(x=31, y=10, z=0.5),
                size=Vector3(x=1.6, y=1.6, z=0.3),
                traversable=True,
            ),
        ],
        reference_path=[
            _p(3, 9, 1.3, "launch", 0.7),
            _p(8, 9, 1.6, "transit", 1.0),
            _p(14, 9, 1.7, "transit", 0.9),
            _p(19, 11, 1.6, "transit", 0.75),
            _p(25, 11, 1.4, "transit", 0.9),
            _p(31, 10, 0.6, "land", 0.4),
        ],
    ),
}


class BundledMapProfile(TypedDict):
    representation: str
    coordinate_frame: str
    resolution_m: float
    confidence_percent: float
    semantic_layers: list[str]
    planning_layers: list[str]


class BundledMapManifest(TypedDict):
    schema_version: str
    compiler_scene_id: str
    name: str
    representation: str
    coordinate_frame: str
    resolution_m: float
    floor_count: int
    bounds_m: dict[str, float]
    confidence_percent: float
    semantic_layers: list[str]
    planning_layers: list[str]
    gazebo_artifact: dict[str, object] | None
    manifest_sha256: str


# The server owns the planning contract for every bundled scene.  Frontends may
# render these values, but they must never invent or independently qualify them.
_BUNDLED_MAP_PROFILES: dict[str, BundledMapProfile] = {
    "school-campus-v1": {
        "representation": "hybrid-3d",
        "coordinate_frame": "ENU",
        "resolution_m": 0.05,
        "confidence_percent": 100.0,
        "semantic_layers": [
            "free-space",
            "stairs",
            "doors",
            "gates",
            "people",
            "pickup-zones",
            "launch-zones",
            "rooms",
            "corridors",
            "roads",
            "vegetation",
            "street-furniture",
        ],
        "planning_layers": [
            "collision-geometry",
            "occupancy",
            "esdf",
            "dynamic-overlay",
            "confidence",
        ],
    },
    "stairwell-coffee-return": {
        "representation": "hybrid-3d",
        "coordinate_frame": "ENU",
        "resolution_m": 0.1,
        "confidence_percent": 100.0,
        "semantic_layers": ["free-space", "stairs", "doors", "people", "pickup-zones"],
        "planning_layers": [
            "collision-geometry",
            "occupancy",
            "esdf",
            "dynamic-overlay",
            "confidence",
        ],
    },
    "forest-gate-inspection": {
        "representation": "hybrid-3d",
        "coordinate_frame": "ENU",
        "resolution_m": 0.1,
        "confidence_percent": 100.0,
        "semantic_layers": ["free-space", "gates", "people"],
        "planning_layers": [
            "collision-geometry",
            "occupancy",
            "esdf",
            "dynamic-overlay",
            "confidence",
        ],
    },
    "service-corridor-dock": {
        "representation": "hybrid-3d",
        "coordinate_frame": "ENU",
        "resolution_m": 0.1,
        "confidence_percent": 100.0,
        "semantic_layers": ["free-space", "doors", "people"],
        "planning_layers": [
            "collision-geometry",
            "occupancy",
            "esdf",
            "dynamic-overlay",
            "confidence",
        ],
    },
}


def get_bundled_map_manifest(scene_id: str) -> BundledMapManifest | None:
    """Return the canonical, content-addressed Map Pack contract for one scene."""

    scene = SCENES.get(scene_id)
    profile = _BUNDLED_MAP_PROFILES.get(scene_id)
    if scene is None or profile is None:
        return None
    gazebo_artifact = (
        get_school_map_gazebo_artifact().summary if scene_id == "school-campus-v1" else None
    )
    canonical = {
        "schema_version": "dronedream.autonomy.bundled-map-manifest.v1",
        "compiler_scene_id": scene.id,
        "scene": scene.model_dump(mode="json"),
        "profile": profile,
        "gazebo_artifact": gazebo_artifact,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "dronedream.autonomy.bundled-map-manifest.v1",
        "compiler_scene_id": scene.id,
        "name": scene.name,
        "representation": profile["representation"],
        "coordinate_frame": profile["coordinate_frame"],
        "resolution_m": profile["resolution_m"],
        "floor_count": scene.floors,
        "bounds_m": scene.bounds_m.model_dump(mode="json"),
        "confidence_percent": profile["confidence_percent"],
        "semantic_layers": list(profile["semantic_layers"]),
        "planning_layers": list(profile["planning_layers"]),
        "gazebo_artifact": gazebo_artifact,
        "manifest_sha256": digest,
    }


def list_scenes() -> list[TerrainScene]:
    # Legacy compiler identifiers remain accepted for stored contracts, but the
    # product exposes one canonical bundled map asset and one user-visible name.
    return [SCENES["school-campus-v1"]]


def get_scene(scene_id: str) -> TerrainScene | None:
    return SCENES.get(scene_id)
