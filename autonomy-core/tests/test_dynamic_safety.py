from dronedream_agent_core.contracts import (
    DynamicObstacleObservation,
    LocalPlannerRequest,
    Vector3,
)
from dronedream_agent_core.dynamic_safety import predictive_safety_decision


def _request(*, obstacles=None) -> LocalPlannerRequest:
    return LocalPlannerRequest(
        current_position_m=Vector3(x=0, y=0, z=1),
        current_velocity_mps=Vector3(x=0, y=0, z=0),
        target_position_m=Vector3(x=5, y=0, z=1),
        dynamic_obstacles=obstacles or [],
        vehicle_radius_m=0.2,
        vehicle_height_m=0.3,
        max_speed_mps=2,
        max_acceleration_mps2=10,
        required_clearance_m=0.3,
        prediction_horizon_seconds=2,
        prediction_step_seconds=0.2,
    )


def test_clear_corridor_continues_toward_target() -> None:
    decision = predictive_safety_decision(_request(), [])

    assert decision.action == "continue"
    assert decision.selected_velocity_mps.x > 1.5
    assert abs(decision.selected_velocity_mps.y) < 1e-9
    assert decision.minimum_predicted_clearance_m == 999.0


def test_static_wall_rejects_direct_velocity_before_impact() -> None:
    wall = {
        "name": "corridor-wall",
        "center_x": 2.0,
        "center_y": 0.0,
        "center_z": 1.0,
        "size_x": 0.3,
        "size_y": 2.0,
        "size_z": 3.0,
    }

    decision = predictive_safety_decision(_request(), [wall])

    assert decision.action in {"slow", "replan"}
    assert abs(decision.selected_velocity_mps.y) > 0.1
    assert decision.minimum_predicted_clearance_m >= 0.3


def test_crossing_obstacle_changes_the_local_motion() -> None:
    crossing = DynamicObstacleObservation(
        obstacle_id="person-1",
        position_m=Vector3(x=2, y=-1, z=1),
        velocity_mps=Vector3(x=0, y=1, z=0),
        radius_m=0.3,
        height_m=1.7,
        confidence=0.95,
        age_seconds=0.05,
    )

    decision = predictive_safety_decision(_request(obstacles=[crossing]), [])

    assert decision.action in {"slow", "replan"}
    assert decision.threat_obstacle_id == "person-1"
    assert decision.minimum_predicted_clearance_m >= 0.3


def test_no_safe_velocity_fails_closed_to_hold() -> None:
    enclosing_volume = {
        "name": "invalid-start-volume",
        "center_x": 0.0,
        "center_y": 0.0,
        "center_z": 1.0,
        "size_x": 20.0,
        "size_y": 20.0,
        "size_z": 20.0,
    }

    decision = predictive_safety_decision(_request(), [enclosing_volume])

    assert decision.action == "hold"
    assert "NO_SAFE_LOCAL_VELOCITY" in decision.issue_codes
    assert decision.minimum_predicted_clearance_m < 0


def test_stale_perception_brakes_and_holds_before_planning_motion() -> None:
    request = _request().model_copy(
        update={
            "current_velocity_mps": Vector3(x=1.0, y=0.0, z=0.0),
            "perception_stream_age_seconds": 0.8,
            "maximum_perception_age_seconds": 0.5,
        }
    )

    decision = predictive_safety_decision(request, [])

    assert decision.action == "hold"
    assert decision.selected_velocity_mps.x < request.current_velocity_mps.x
    assert "PERCEPTION_STREAM_STALE" in decision.issue_codes
    assert "HOLD_UNTIL_FRESH_LOCAL_WORLD" in decision.issue_codes
