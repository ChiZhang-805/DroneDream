"""Canonical catalog for the single bundled Kumpula Campus map."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, TypedDict

from app.autonomy.models import RoutePoint, TerrainObject, TerrainScene, Vector3
from app.autonomy.school_map_artifact import get_school_map_gazebo_summary


def _point(
    x: float,
    y: float,
    z: float,
    phase: Literal["launch", "transit", "stairs", "gate", "pickup", "return", "land"],
    speed_mps: float,
) -> RoutePoint:
    """Create one ENU reference waypoint with its verified velocity ceiling."""
    return RoutePoint(x=x, y=y, z=z, phase=phase, speed_limit_mps=speed_mps)


KUMPULA_SCENE = TerrainScene(
    id="school-campus-v1",
    name="Kumpula Campus",
    summary=(
        "Real University of Helsinki Kumpula Campus map built from City of Helsinki "
        "building footprints and orthophotography. It includes Exactum, Physicum, "
        "Chemicum and Dynamicum plus a flight-verified outdoor delivery corridor."
    ),
    bounds_m=Vector3(x=500.0, y=500.0, z=35.0),
    floors=1,
    minimum_clearance_m=1.2,
    tags=[
        "real-geospatial-data",
        "university-campus",
        "outdoor",
        "orthophoto",
        "buildings",
        "payload",
        "return",
    ],
    objects=[
        TerrainObject(
            id="exactum-physicum",
            kind="building",
            center=Vector3(x=-4.25, y=1.05, z=6.8),
            size=Vector3(x=142.50, y=124.16, z=13.6),
        ),
        TerrainObject(
            id="chemicum",
            kind="building",
            center=Vector3(x=74.22, y=91.60, z=6.8),
            size=Vector3(x=152.64, y=86.91, z=13.6),
        ),
        TerrainObject(
            id="dynamicum",
            kind="building",
            center=Vector3(x=-91.84, y=-101.81, z=8.5),
            size=Vector3(x=93.79, y=77.59, z=17.0),
        ),
        TerrainObject(
            id="office-drone-launch-pad",
            kind="launch",
            center=Vector3(x=-41.0, y=-83.0, z=0.04),
            size=Vector3(x=2.4, y=2.4, z=0.08),
            traversable=True,
            required_clearance_m=1.2,
        ),
        TerrainObject(
            id="takeout-pickup-pad",
            kind="pickup",
            center=Vector3(x=43.0, y=55.0, z=0.04),
            size=Vector3(x=2.4, y=2.4, z=0.08),
            traversable=True,
            required_clearance_m=1.2,
        ),
    ],
    reference_path=[
        _point(-41.0, -83.0, 1.5, "launch", 0.55),
        _point(-41.0, -83.0, 35.0, "transit", 1.2),
        _point(0.0, -5.0, 35.0, "transit", 1.2),
        _point(43.0, 55.0, 35.0, "transit", 1.2),
        _point(43.0, 55.0, 2.0, "pickup", 0.45),
        _point(43.0, 55.0, 35.0, "return", 1.2),
        _point(0.0, -5.0, 35.0, "return", 1.2),
        _point(-41.0, -83.0, 35.0, "return", 1.2),
        _point(-41.0, -83.0, 1.5, "land", 0.35),
    ],
)

# The identifier remains stable so saved mission records keep resolving, while
# all retired synthetic scene bodies have been removed from the source tree.
SCENES: dict[str, TerrainScene] = {KUMPULA_SCENE.id: KUMPULA_SCENE}


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


KUMPULA_PROFILE: BundledMapProfile = {
    "representation": "hybrid-3d",
    "coordinate_frame": "ENU",
    "resolution_m": 0.18,
    "confidence_percent": 100.0,
    "semantic_layers": [
        "free-space",
        "building-footprints",
        "orthophoto",
        "pickup-zones",
        "launch-zones",
        "named-campus-buildings",
    ],
    "planning_layers": [
        "collision-geometry",
        "navigation-graph",
        "route-corridor",
    ],
}


def get_bundled_map_manifest(scene_id: str) -> BundledMapManifest | None:
    """Return the content-addressed contract for the bundled Kumpula map."""
    scene = SCENES.get(scene_id)
    if scene is None:
        return None
    gazebo_artifact = get_school_map_gazebo_summary()
    canonical = {
        "schema_version": "dronedream.autonomy.bundled-map-manifest.v1",
        "compiler_scene_id": scene.id,
        "scene": scene.model_dump(mode="json"),
        "profile": KUMPULA_PROFILE,
        "gazebo_artifact": gazebo_artifact,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "dronedream.autonomy.bundled-map-manifest.v1",
        "compiler_scene_id": scene.id,
        "name": scene.name,
        "representation": KUMPULA_PROFILE["representation"],
        "coordinate_frame": KUMPULA_PROFILE["coordinate_frame"],
        "resolution_m": KUMPULA_PROFILE["resolution_m"],
        "floor_count": scene.floors,
        "bounds_m": scene.bounds_m.model_dump(mode="json"),
        "confidence_percent": KUMPULA_PROFILE["confidence_percent"],
        "semantic_layers": list(KUMPULA_PROFILE["semantic_layers"]),
        "planning_layers": list(KUMPULA_PROFILE["planning_layers"]),
        "gazebo_artifact": gazebo_artifact,
        "manifest_sha256": digest,
    }


def list_scenes() -> list[TerrainScene]:
    """Expose an independent copy of the sole bundled map."""
    return [KUMPULA_SCENE.model_copy(deep=True)]


def get_scene(scene_id: str) -> TerrainScene | None:
    """Resolve the canonical map without sharing mutable registry state."""
    scene = SCENES.get(scene_id)
    return None if scene is None else scene.model_copy(deep=True)
