"""Evidence-based capability gates for static, dynamic, and unknown-map navigation."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import MapAsset, MapCatalog, NavigationReadinessReport, VehicleAsset

LOCALIZATION_SENSORS = frozenset(
    {
        "vio",
        "visual-inertial-odometry",
        "slam",
        "lidar-slam",
        "depth-slam",
        "stereo-vio",
    }
)
OBSTACLE_SENSORS = frozenset(
    {
        "lidar",
        "3d-lidar",
        "depth-camera",
        "stereo-camera",
        "radar",
        "rangefinder-array",
        "point-cloud",
    }
)


def _semantic(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def assess_navigation_readiness(
    graph: MapAsset,
    catalog: MapCatalog,
    semantic_path: Path,
    vehicle: VehicleAsset,
) -> NavigationReadinessReport:
    """Return only capabilities supported by explicit map, sensor, and test evidence."""

    semantic = _semantic(semantic_path)
    collisions = semantic.get("collision_primitives")
    static_collision_ready = isinstance(collisions, list) and bool(collisions)
    sensors = {sensor.strip().lower() for sensor in vehicle.sensors}
    indoor_localization = bool(sensors & LOCALIZATION_SENSORS)
    obstacle_perception = bool(sensors & OBSTACLE_SENSORS)

    navigation_layers = semantic.get("navigation_layers")
    if not isinstance(navigation_layers, dict):
        navigation_layers = {}
    occupancy_ready = bool(navigation_layers.get("occupancy_ready", False)) and bool(
        navigation_layers.get("esdf_ready", False)
    )

    dynamic_tracking = semantic.get("dynamic_obstacle_tracking")
    if not isinstance(dynamic_tracking, dict):
        dynamic_tracking = {}
    dynamic_tracking_ready = bool(dynamic_tracking.get("runtime_verified", False))

    execution = semantic.get("execution")
    if not isinstance(execution, dict):
        execution = {}
    qualified_static_simulation = all(
        bool(execution.get(key, False))
        for key in (
            "simulation_execution_ready",
            "gazebo_runtime_verified",
            "px4_mission_smoke_verified",
        )
    )
    static_planning = catalog.topology_available and bool(graph.edges) and static_collision_ready
    dynamic_ready = (
        static_planning
        and indoor_localization
        and obstacle_perception
        and dynamic_tracking_ready
    )
    arbitrary_ready = dynamic_ready and occupancy_ready
    issues: list[str] = []
    if not static_collision_ready:
        issues.append("STATIC_COLLISION_GEOMETRY_UNAVAILABLE")
    if not occupancy_ready:
        issues.append("OCCUPANCY_ESDF_NOT_RUNTIME_VERIFIED")
    if not indoor_localization:
        issues.append("INDOOR_LOCALIZATION_SENSOR_MISSING")
    if not obstacle_perception:
        issues.append("ONBOARD_OBSTACLE_PERCEPTION_MISSING")
    if not dynamic_tracking_ready:
        issues.append("DYNAMIC_OBSTACLE_TRACKING_NOT_RUNTIME_VERIFIED")
    if not qualified_static_simulation:
        issues.append("QUALIFIED_STATIC_SIMULATION_NOT_RUNTIME_VERIFIED")

    return NavigationReadinessReport(
        static_map_planning_ready=static_planning,
        static_collision_geometry_ready=static_collision_ready,
        occupancy_esdf_ready=occupancy_ready,
        indoor_localization_ready=indoor_localization,
        onboard_obstacle_perception_ready=obstacle_perception,
        dynamic_obstacle_tracking_ready=dynamic_tracking_ready,
        qualified_static_simulation_ready=qualified_static_simulation,
        known_dynamic_map_autonomy_ready=dynamic_ready,
        arbitrary_indoor_autonomy_ready=arbitrary_ready,
        sensor_evidence=sorted(sensors),
        issue_codes=issues,
    )


def enforce_environment_readiness(
    environment_mode: str,
    report: NavigationReadinessReport,
) -> None:
    """Block a requested autonomy scope when required evidence is unavailable."""

    if environment_mode == "known-map-with-dynamic-obstacles":
        if not report.known_dynamic_map_autonomy_ready:
            raise ValueError("KNOWN_DYNAMIC_MAP_AUTONOMY_NOT_READY")
    elif (
        environment_mode == "unknown-indoor-environment"
        and not report.arbitrary_indoor_autonomy_ready
    ):
        raise ValueError("ARBITRARY_INDOOR_AUTONOMY_NOT_READY")
