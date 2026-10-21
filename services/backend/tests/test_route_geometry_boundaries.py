"""Invalid/rotated geometry must not produce a false collision-free receipt."""

import math

import pytest

from app.autonomy.school_map_artifact import BoxPrimitive
from app.autonomy.school_map_mission_validation import (
    VehicleCollisionEnvelope,
    sample_polyline,
    validate_route_clearance,
    vehicle_clearance_to_primitive_m,
)


def _box(**changes):
    values = dict(
        name="test-box", center_x=0.0, center_y=0.0, center_z=0.0,
        size_x=0.2, size_y=0.2, size_z=4.0, semantic="wall",
    )
    return BoxPrimitive(**(values | changes))


def test_pitched_box_is_not_treated_as_an_upright_pole():
    """A horizontal beam crossing the aircraft is not a vertical distant pole."""
    beam = _box(pitch_rad=math.pi / 2)
    assert vehicle_clearance_to_primitive_m((1.5, 0.0, 0.0), beam) < 0


@pytest.mark.parametrize("point", [(float("nan"), 0.0, 0.0), (True, 0.0, 0.0)])
def test_bad_sample_cannot_disappear_among_valid_samples(point):
    with pytest.raises(ValueError):
        validate_route_clearance([(10.0, 10.0, 10.0), point], [_box()])


@pytest.mark.parametrize("dimension", [-1.0, 0.0, float("nan"), True])
def test_vehicle_envelope_rejects_invalid_dimensions(dimension):
    with pytest.raises(ValueError):
        VehicleCollisionEnvelope(diameter_m=dimension)


def test_single_point_route_still_validates_coordinates():
    with pytest.raises(ValueError):
        sample_polyline([(float("nan"), 0.0, 0.0)], 0.1)


def test_non_finite_primitive_cannot_disappear_among_valid_primitives():
    with pytest.raises(ValueError):
        validate_route_clearance([(10.0, 10.0, 10.0)], [_box(), _box(size_z=float("nan"))])


def test_sampling_checks_resource_budget_before_allocating():
    with pytest.raises(ValueError, match="sample budget"):
        sample_polyline([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], 1e-7)
