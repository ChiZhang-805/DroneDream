"""Deterministic complex-terrain catalog with prevalidated reference corridors."""

from __future__ import annotations

from typing import Literal

from app.autonomy.models import RoutePoint, TerrainObject, TerrainScene, Vector3


def _p(
    x: float,
    y: float,
    z: float,
    phase: Literal["launch", "transit", "stairs", "gate", "pickup", "return", "land"],
    speed: float = 1.3,
) -> RoutePoint:
    return RoutePoint(x=x, y=y, z=z, phase=phase, speed_limit_mps=speed)


SCENES: dict[str, TerrainScene] = {
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
                id="office-block", kind="building", center=Vector3(x=6, y=14, z=5.5),
                size=Vector3(x=10, y=24, z=11),
            ),
            TerrainObject(
                id="stairwell", kind="stairwell", center=Vector3(x=14, y=10, z=5.5),
                size=Vector3(x=5, y=8, z=11), traversable=True,
                required_clearance_m=0.55,
            ),
            TerrainObject(
                id="courtyard-building", kind="building", center=Vector3(x=31, y=23, z=5),
                size=Vector3(x=17, y=7, z=10),
            ),
            TerrainObject(
                id="tree-a", kind="tree", center=Vector3(x=24, y=8, z=3.5),
                size=Vector3(x=2.2, y=2.2, z=7),
            ),
            TerrainObject(
                id="tree-b", kind="tree", center=Vector3(x=33, y=9, z=3.0),
                size=Vector3(x=2.0, y=2.0, z=6),
            ),
            TerrainObject(
                id="sign-a", kind="sign", center=Vector3(x=27, y=15, z=1.3),
                size=Vector3(x=2.4, y=0.4, z=2.6),
            ),
            TerrainObject(
                id="pole-a", kind="pole", center=Vector3(x=36, y=14, z=2.5),
                size=Vector3(x=0.5, y=0.5, z=5),
            ),
            TerrainObject(
                id="coffee-dock", kind="pickup", center=Vector3(x=39, y=5, z=1.2),
                size=Vector3(x=1.4, y=1.4, z=1.2), traversable=True,
            ),
        ],
        reference_path=[
            _p(3, 13, 8.6, "launch", 0.8), _p(8, 13, 8.6, "transit"),
            _p(12, 12, 8.4, "transit"), _p(14, 12, 7.2, "stairs", 0.7),
            _p(16, 10, 5.7, "stairs", 0.65), _p(14, 8, 4.3, "stairs", 0.65),
            _p(16, 6, 2.8, "stairs", 0.65), _p(18, 5, 1.5, "stairs", 0.7),
            _p(22, 4, 1.6, "transit"), _p(28, 4, 1.9, "transit"),
            _p(34, 4, 1.8, "transit"), _p(39, 5, 1.2, "pickup", 0.45),
            _p(35, 6, 1.8, "return", 1.0), _p(29, 6, 2.0, "return"),
            _p(22, 5, 1.6, "return"), _p(18, 5, 1.5, "return", 0.8),
            _p(16, 6, 2.8, "stairs", 0.6), _p(14, 8, 4.3, "stairs", 0.6),
            _p(16, 10, 5.7, "stairs", 0.6), _p(14, 12, 7.2, "stairs", 0.6),
            _p(12, 12, 8.4, "return", 0.9), _p(8, 13, 8.6, "return", 0.8),
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
        bounds_m=Vector3(x=48, y=24, z=8), floors=1, minimum_clearance_m=1.15,
        tags=["vision", "gates", "trees", "unknown-space"],
        objects=[
            TerrainObject(
                id="tree-1", kind="tree", center=Vector3(x=12, y=6, z=3),
                size=Vector3(x=2, y=2, z=6),
            ),
            TerrainObject(
                id="tree-2", kind="tree", center=Vector3(x=21, y=17, z=3.5),
                size=Vector3(x=2.4, y=2.4, z=7),
            ),
            TerrainObject(
                id="tree-3", kind="tree", center=Vector3(x=34, y=7, z=3),
                size=Vector3(x=2, y=2, z=6),
            ),
            TerrainObject(
                id="gate-1", kind="gate", center=Vector3(x=15, y=12, z=2.4),
                size=Vector3(x=0.4, y=3.4, z=3.4), traversable=True,
                required_clearance_m=0.45,
            ),
            TerrainObject(
                id="gate-2", kind="gate", center=Vector3(x=27, y=12, z=2.8),
                size=Vector3(x=0.4, y=3.6, z=3.6), traversable=True,
                required_clearance_m=0.5,
            ),
            TerrainObject(
                id="gate-3", kind="gate", center=Vector3(x=39, y=12, z=2.3),
                size=Vector3(x=0.4, y=3.2, z=3.2), traversable=True,
                required_clearance_m=0.42,
            ),
        ],
        reference_path=[
            _p(3, 12, 1.2, "launch", 0.8), _p(9, 12, 2.2, "transit"),
            _p(15, 12, 2.4, "gate", 0.9), _p(21, 12, 2.6, "transit"),
            _p(27, 12, 2.8, "gate", 0.9), _p(33, 12, 2.5, "transit"),
            _p(39, 12, 2.3, "gate", 0.9), _p(45, 12, 2.0, "land", 0.5),
        ],
    ),
    "service-corridor-dock": TerrainScene(
        id="service-corridor-dock",
        name="Service corridor docking",
        summary=(
            "Confined indoor corridor with vertical signs, blind corners and a precision "
            "docking target."
        ),
        bounds_m=Vector3(x=34, y=18, z=5), floors=1, minimum_clearance_m=0.78,
        tags=["narrow", "indoor", "blind-corner", "docking"],
        objects=[
            TerrainObject(
                id="wall-a", kind="wall", center=Vector3(x=10, y=4, z=2.5),
                size=Vector3(x=14, y=0.4, z=5),
            ),
            TerrainObject(
                id="wall-b", kind="wall", center=Vector3(x=18, y=14, z=2.5),
                size=Vector3(x=18, y=0.4, z=5),
            ),
            TerrainObject(
                id="sign-b", kind="sign", center=Vector3(x=19, y=8, z=1.4),
                size=Vector3(x=0.4, y=2.2, z=2.8),
            ),
            TerrainObject(
                id="dock", kind="landing", center=Vector3(x=31, y=10, z=0.5),
                size=Vector3(x=1.6, y=1.6, z=0.3), traversable=True,
            ),
        ],
        reference_path=[
            _p(3, 9, 1.3, "launch", 0.7), _p(8, 9, 1.6, "transit", 1.0),
            _p(14, 9, 1.7, "transit", 0.9), _p(19, 11, 1.6, "transit", 0.75),
            _p(25, 11, 1.4, "transit", 0.9), _p(31, 10, 0.6, "land", 0.4),
        ],
    ),
}


def list_scenes() -> list[TerrainScene]:
    return list(SCENES.values())


def get_scene(scene_id: str) -> TerrainScene | None:
    return SCENES.get(scene_id)
