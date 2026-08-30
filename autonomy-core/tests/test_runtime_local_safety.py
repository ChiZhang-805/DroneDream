from dronedream_agent_core.contracts import (
    DynamicObstacleObservation,
    RuntimeLocalSafetyObservation,
    Vector3,
    VehicleAsset,
)
from dronedream_agent_core.runtime_local_safety import evaluate_runtime_local_safety


def _vehicle() -> VehicleAsset:
    return VehicleAsset(
        asset_id="test-x500",
        name="Test X500",
        dry_mass_kg=2.0,
        max_takeoff_mass_kg=3.0,
        body_radius_m=0.38,
        body_height_m=0.43,
        max_speed_mps=2.0,
        max_acceleration_mps2=4.0,
        qualified_range_m=100.0,
        reserve_battery_percent=30.0,
        max_pickup_payload_kg=0.2,
        sensors=["depth", "vio"],
    )


def test_runtime_command_is_short_lived_hash_bound_and_avoids_crossing_track() -> None:
    observation = RuntimeLocalSafetyObservation(
        sequence=7,
        observed_at_unix_ms=10_000,
        source="simulation-ground-truth",
        stream_healthy=True,
        stream_age_seconds=0.02,
        localization_covariance_m2=0.01,
        current_position_m=Vector3(x=0.0, y=0.0, z=1.5),
        current_velocity_mps=Vector3(x=1.0, y=0.0, z=0.0),
        target_position_m=Vector3(x=5.0, y=0.0, z=1.5),
        dynamic_obstacles=[
            DynamicObstacleObservation(
                obstacle_id="person-crossing",
                position_m=Vector3(x=2.0, y=-1.0, z=1.5),
                velocity_mps=Vector3(x=0.0, y=1.0, z=0.0),
                radius_m=0.35,
                height_m=1.7,
                confidence=0.98,
                age_seconds=0.02,
            )
        ],
    )

    command = evaluate_runtime_local_safety(
        observation=observation,
        vehicle=_vehicle(),
        static_primitives=[],
        required_clearance_m=0.35,
        generated_at_unix_ms=10_010,
    )

    assert command.observation_sequence == 7
    assert command.valid_until_unix_ms == 10_510
    assert command.decision.action in {"slow", "replan", "hold"}
    assert command.decision.threat_obstacle_id == "person-crossing"
    assert command.command_position_m != observation.target_position_m


def test_runtime_command_holds_when_localization_is_not_bounded() -> None:
    observation = RuntimeLocalSafetyObservation(
        sequence=1,
        observed_at_unix_ms=1_000,
        source="onboard",
        stream_healthy=True,
        stream_age_seconds=0.01,
        localization_covariance_m2=0.9,
        current_position_m=Vector3(x=0.0, y=0.0, z=1.0),
        current_velocity_mps=Vector3(x=0.2, y=0.0, z=0.0),
        target_position_m=Vector3(x=2.0, y=0.0, z=1.0),
    )

    command = evaluate_runtime_local_safety(
        observation=observation,
        vehicle=_vehicle(),
        static_primitives=[],
        required_clearance_m=0.35,
        generated_at_unix_ms=1_010,
    )

    assert command.decision.action == "hold"
    assert "LOCALIZATION_UNCERTAIN" in command.decision.issue_codes
