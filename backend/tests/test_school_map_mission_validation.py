from __future__ import annotations

import pytest

from app.autonomy.catalog import get_scene
from app.autonomy.school_map_artifact import school_map_collision_primitives
from app.autonomy.school_map_mission_validation import (
    VehicleCollisionEnvelope,
    model_root_to_world_envelope_center,
    px4_local_track_to_world_envelope_center,
    sample_polyline,
    validate_route_clearance,
    vehicle_clearance_to_primitive_m,
    world_envelope_center_to_px4_local_track,
)


def _reference_points() -> list[tuple[float, float, float]]:
    scene = get_scene("school-campus-v1")
    assert scene is not None
    return [(point.x, point.y, point.z) for point in scene.reference_path]


def _spawn_model_root() -> tuple[float, float, float]:
    """Return the generated Kumpula PX4 model-root spawn, not a legacy fixture."""

    return (-41.0, -83.0, 0.067)


def test_school_map_route_frame_round_trips_every_reference_waypoint() -> None:
    model_root_world = _spawn_model_root()
    for world_point in _reference_points():
        local = world_envelope_center_to_px4_local_track(
            world_point,
            model_root_world=model_root_world,
        )
        assert px4_local_track_to_world_envelope_center(
            local,
            model_root_world=model_root_world,
        ) == pytest.approx(world_point)


def test_school_map_route_frame_swaps_enu_axes_for_px4_bridge_fields() -> None:
    origin = _spawn_model_root()
    point = (-39.0, -80.0, 8.15)
    executor_x, executor_y, up = world_envelope_center_to_px4_local_track(
        point,
        model_root_world=origin,
    )

    assert executor_x == pytest.approx(3.0)
    assert executor_y == pytest.approx(2.0)
    assert up == pytest.approx(8.15 - 0.228 - _spawn_model_root()[2])


def test_office_launch_model_root_touches_pad_without_penetration() -> None:
    primitives = {item.name: item for item in school_map_collision_primitives()}
    envelope_center = model_root_to_world_envelope_center(_spawn_model_root())
    clearance = vehicle_clearance_to_primitive_m(
        envelope_center,
        primitives["office-drone-launch-pad"],
    )

    assert clearance == pytest.approx(0.0, abs=1e-12)


def test_reference_route_has_no_static_penetration_at_40_mm_sampling() -> None:
    samples = sample_polyline(_reference_points(), interval_m=0.04)
    result = validate_route_clearance(samples, school_map_collision_primitives())

    assert result.sample_count > 10_000
    assert result.collision_count == 0, result.collisions
    assert result.minimum_clearance_m >= -0.001


def test_pickup_hover_preserves_operational_clearance_from_handoff_pad() -> None:
    primitives = {item.name: item for item in school_map_collision_primitives()}
    clearance = vehicle_clearance_to_primitive_m(
        (43.0, 55.0, 2.0),
        primitives["takeout-pickup-pad"],
    )

    assert clearance >= 1.7


def test_route_preserves_tracking_margin_from_real_kumpula_buildings() -> None:
    building_primitives = [
        primitive
        for primitive in school_map_collision_primitives()
        if primitive.semantic == "building"
    ]
    result = validate_route_clearance(
        sample_polyline(_reference_points(), interval_m=0.04),
        building_primitives,
    )
    assert result.collision_count == 0, result.collisions
    assert result.minimum_clearance_m >= 3.6


def test_actual_model_root_samples_use_explicit_vertical_center_offset() -> None:
    envelope = VehicleCollisionEnvelope()
    center = model_root_to_world_envelope_center((2.0, 3.0, 4.0), envelope)

    assert center == pytest.approx((2.0, 3.0, 4.228))
