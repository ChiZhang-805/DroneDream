"""Import qualified metadata from real DroneDream Gazebo asset packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import CatalogEntity, MapCatalog, Vector3

KNOWN_ENTITY_ALIASES = {
    "bicycle-shelter": ["自行车棚", "单车棚"],
    "cafeteria": ["食堂", "餐厅", "学校食堂"],
    "campus-gate": ["校园门口", "校门", "学校大门"],
    "takeout-pickup": ["外卖点", "外卖取餐处"],
    "teaching-building": ["教学楼", "教学楼入口"],
    "tree-corridor": ["林荫道", "树木走廊"],
}


class AssetQualificationError(ValueError):
    """The supplied asset cannot support the requested planning stage."""


def _load_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssetQualificationError(f"expected JSON object: {path}")
    return value


def _vector(value: object, *, default_z: float = 1.5) -> Vector3:
    if not isinstance(value, list) or len(value) < 2:
        raise AssetQualificationError(f"invalid ENU anchor: {value!r}")
    return Vector3(x=float(value[0]), y=float(value[1]), z=default_z)


def load_school_map_catalog(semantic_path: Path) -> MapCatalog:
    """Extract entity grounding without pretending the asset contains a route graph."""

    semantic = _load_object(semantic_path)
    if semantic.get("schema_version") != "dronedream.autonomy.school-map-semantic.v1":
        raise AssetQualificationError("unsupported School Map semantic schema")
    if semantic.get("coordinate_frame") != "ENU":
        raise AssetQualificationError("School Map must use ENU coordinates")

    roads = semantic.get("roads")
    if not isinstance(roads, dict):
        raise AssetQualificationError("School Map roads metadata is missing")
    anchors = roads.get("facility_anchors")
    if not isinstance(anchors, dict) or not anchors:
        raise AssetQualificationError("School Map facility anchors are missing")

    bindings = semantic.get("simulation_bindings")
    pickup_binding_available = (
        isinstance(bindings, dict)
        and isinstance(bindings.get("mission_pickup_waypoint"), dict)
        and {"x", "y", "z"}.issubset(bindings["mission_pickup_waypoint"])
    )

    entities: list[CatalogEntity] = []
    for entity_id, position in sorted(anchors.items()):
        aliases = [
            str(entity_id),
            str(entity_id).replace("-", " "),
            *KNOWN_ENTITY_ALIASES.get(str(entity_id), []),
        ]
        # "外卖点" denotes the action-capable pickup pad whenever the qualified
        # simulation binding exists. Keep the nearby facility anchor addressable
        # by its explicit names without exposing an avoidable natural-language
        # alias collision to the model.
        if str(entity_id) == "takeout-pickup" and pickup_binding_available:
            aliases = [alias for alias in aliases if alias != "外卖点"]
        entities.append(
            CatalogEntity(
                entity_id=str(entity_id),
                aliases=list(dict.fromkeys(aliases)),
                position_m=_vector(position),
                semantic="facility-anchor",
                source_pointer=f"/roads/facility_anchors/{entity_id}",
            )
        )

    if isinstance(bindings, dict):
        launch = bindings.get("mission_launch_waypoint")
        pickup = bindings.get("mission_pickup_waypoint")
        for entity_id, aliases, raw, semantic_name, pointer in (
            (
                "office-launch-pad",
                [
                    "office launch pad",
                    "办公室起飞点",
                    "办公室起降坪",
                    "办公室无人机起降坪",
                    "三楼办公室起降坪",
                ],
                launch,
                "launch",
                "/simulation_bindings/mission_launch_waypoint",
            ),
            (
                "takeout-pickup-pad",
                ["takeout pickup pad", "外卖点", "外卖取餐点"],
                pickup,
                "pickup",
                "/simulation_bindings/mission_pickup_waypoint",
            ),
        ):
            if isinstance(raw, dict) and {"x", "y", "z"}.issubset(raw):
                entities.append(
                    CatalogEntity(
                        entity_id=entity_id,
                        aliases=aliases,
                        position_m=Vector3(
                            x=float(raw["x"]),
                            y=float(raw["y"]),
                            z=float(raw["z"]),
                        ),
                        semantic=semantic_name,
                        source_pointer=pointer,
                    )
                )

    segments = roads.get("segments")
    segment_ids = []
    if isinstance(segments, list):
        segment_ids = [
            str(segment["id"])
            for segment in segments
            if isinstance(segment, dict) and isinstance(segment.get("id"), str)
        ]
    # Road polylines do not describe indoor doors, stairs, or traversable 3-D
    # adjacency, so the full planner must fail closed until a qualified graph exists.
    known_limits = [str(item) for item in semantic.get("known_export_limits", [])]
    known_limits.append(
        "This asset exposes road polylines and facility anchors, not a qualified 3-D route graph."
    )
    digest = hashlib.sha256(semantic_path.read_bytes()).hexdigest()
    return MapCatalog(
        scene_id=str(semantic.get("compiler_scene_id", "unknown")),
        semantic_sha256=digest,
        entities=entities,
        road_segment_ids=segment_ids,
        topology_available=False,
        known_limits=known_limits,
    )
