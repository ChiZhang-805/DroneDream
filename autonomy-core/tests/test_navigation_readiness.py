import json

import pytest

from dronedream_agent_core.contracts import (
    CatalogEntity,
    MapAsset,
    MapCatalog,
    MapEdge,
    MapNode,
    Vector3,
    VehicleAsset,
)
from dronedream_agent_core.navigation_readiness import (
    assess_navigation_readiness,
    enforce_environment_readiness,
)


def _graph_and_catalog() -> tuple[MapAsset, MapCatalog]:
    graph = MapAsset(
        asset_id="map",
        name="Map",
        nodes=[
            MapNode(
                node_id="a",
                label="A",
                position_m=Vector3(x=0, y=0, z=1),
                semantic="launch",
            ),
            MapNode(
                node_id="b",
                label="B",
                position_m=Vector3(x=1, y=0, z=1),
                semantic="pickup",
            ),
        ],
        edges=[
            MapEdge(
                edge_id="a-b",
                from_node="a",
                to_node="b",
                distance_m=1,
                minimum_clearance_m=1,
                speed_limit_mps=1,
            )
        ],
        named_entities={"a": "a", "b": "b"},
    )
    catalog = MapCatalog(
        scene_id="map",
        semantic_sha256="1" * 64,
        entities=[
            CatalogEntity(
                entity_id="a",
                aliases=["a"],
                position_m=Vector3(x=0, y=0, z=1),
                semantic="launch",
                source_pointer="/a",
            )
        ],
        topology_available=True,
    )
    return graph, catalog


def _vehicle(sensors: list[str]) -> VehicleAsset:
    return VehicleAsset(
        asset_id="vehicle",
        name="Vehicle",
        dry_mass_kg=1,
        max_takeoff_mass_kg=2,
        body_radius_m=0.2,
        body_height_m=0.3,
        max_speed_mps=2,
        max_acceleration_mps2=2,
        qualified_range_m=100,
        reserve_battery_percent=20,
        max_pickup_payload_kg=0,
        sensors=sensors,
    )


def test_gps_and_odometry_do_not_claim_arbitrary_indoor_autonomy(tmp_path) -> None:
    graph, catalog = _graph_and_catalog()
    semantic = tmp_path / "semantic.json"
    semantic.write_text(json.dumps({"collision_primitives": [{"name": "wall"}]}))

    report = assess_navigation_readiness(
        graph,
        catalog,
        semantic,
        _vehicle(["imu", "gps", "odometry"]),
    )

    assert report.static_map_planning_ready is True
    assert report.indoor_localization_ready is False
    assert report.onboard_obstacle_perception_ready is False
    assert report.arbitrary_indoor_autonomy_ready is False
    with pytest.raises(ValueError, match="ARBITRARY_INDOOR_AUTONOMY_NOT_READY"):
        enforce_environment_readiness("unknown-indoor-environment", report)


def test_explicit_sensor_and_runtime_evidence_enables_dynamic_unknown_mode(tmp_path) -> None:
    graph, catalog = _graph_and_catalog()
    semantic = tmp_path / "semantic.json"
    semantic.write_text(
        json.dumps(
            {
                "collision_primitives": [{"name": "wall"}],
                "navigation_layers": {"occupancy_ready": True, "esdf_ready": True},
                "dynamic_obstacle_tracking": {"runtime_verified": True},
                "execution": {
                    "simulation_execution_ready": True,
                    "gazebo_runtime_verified": True,
                    "px4_mission_smoke_verified": True,
                },
            }
        )
    )

    report = assess_navigation_readiness(
        graph,
        catalog,
        semantic,
        _vehicle(["imu", "stereo-vio", "3d-lidar"]),
    )

    assert report.known_dynamic_map_autonomy_ready is True
    assert report.arbitrary_indoor_autonomy_ready is True
    enforce_environment_readiness("unknown-indoor-environment", report)
