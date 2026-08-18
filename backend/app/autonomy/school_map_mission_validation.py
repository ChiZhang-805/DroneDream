"""Reusable School Map route-frame and conservative collision validation.

Mission waypoints are expressed at the center of the qualified vehicle collision
envelope in School Map ENU coordinates.  PX4's Gazebo bridge exposes local north
as Gazebo world y and local east as Gazebo world x.  School Map x is east and y is
north, so the adapter swaps the map axes into the executor's north/east fields.
The vertical model-root offset remains explicit so the route cannot shift by half
the aircraft height.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.autonomy.school_map_artifact import (
    PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M,
    VEHICLE_COLLISION_DIAMETER_M,
    VEHICLE_COLLISION_HEIGHT_M,
    BoxPrimitive,
    CapsulePrimitive,
    CollisionPrimitive,
    CylinderPrimitive,
    MeshPrimitive,
    SpherePrimitive,
)

WorldPoint = tuple[float, float, float]
Px4LocalTrackPoint = tuple[float, float, float]


@dataclass(frozen=True)
class VehicleCollisionEnvelope:
    diameter_m: float = VEHICLE_COLLISION_DIAMETER_M
    height_m: float = VEHICLE_COLLISION_HEIGHT_M
    center_above_model_root_m: float = PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M

    @property
    def radius_m(self) -> float:
        return self.diameter_m / 2

    @property
    def half_height_m(self) -> float:
        return self.height_m / 2

    @property
    def conservative_sphere_radius_m(self) -> float:
        return math.hypot(self.radius_m, self.half_height_m)


DEFAULT_VEHICLE_ENVELOPE = VehicleCollisionEnvelope()


@dataclass(frozen=True)
class RouteClearanceResult:
    sample_count: int
    collision_count: int
    minimum_clearance_m: float
    minimum_clearance_point: WorldPoint
    minimum_clearance_primitive: str
    collisions: tuple[tuple[WorldPoint, str, float], ...]


def _axis_endpoints(
    primitive: CylinderPrimitive | CapsulePrimitive,
) -> tuple[WorldPoint, WorldPoint]:
    roll = primitive.roll_rad
    pitch = primitive.pitch_rad
    yaw = primitive.yaw_rad
    axis = (
        math.cos(yaw) * math.sin(pitch) * math.cos(roll) + math.sin(yaw) * math.sin(roll),
        math.sin(yaw) * math.sin(pitch) * math.cos(roll) - math.cos(yaw) * math.sin(roll),
        math.cos(pitch) * math.cos(roll),
    )
    half_length = (
        primitive.height_m if isinstance(primitive, CylinderPrimitive) else primitive.length_m
    ) / 2
    center = (primitive.center_x, primitive.center_y, primitive.center_z)
    return (
        (
            center[0] - axis[0] * half_length,
            center[1] - axis[1] * half_length,
            center[2] - axis[2] * half_length,
        ),
        (
            center[0] + axis[0] * half_length,
            center[1] + axis[1] * half_length,
            center[2] + axis[2] * half_length,
        ),
    )


def _point_segment_distance(point: WorldPoint, start: WorldPoint, end: WorldPoint) -> float:
    delta = tuple(end[index] - start[index] for index in range(3))
    length_squared = sum(component * component for component in delta)
    if length_squared <= 1e-18:
        return math.dist(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            sum((point[index] - start[index]) * delta[index] for index in range(3))
            / length_squared,
        ),
    )
    closest = tuple(start[index] + ratio * delta[index] for index in range(3))
    return math.dist(point, closest)


def _orthogonal_clearance(first: float, second: float) -> float:
    """Combine signed clearances on orthogonal axes.

    Positive values are Euclidean separation.  If both axes overlap, the value
    nearest zero is the conservative penetration depth.
    """

    if first > 0 and second > 0:
        return math.hypot(first, second)
    if first > 0:
        return first
    if second > 0:
        return second
    return max(first, second)


def vehicle_clearance_to_primitive_m(
    envelope_center: WorldPoint,
    primitive: CollisionPrimitive,
    envelope: VehicleCollisionEnvelope = DEFAULT_VEHICLE_ENVELOPE,
) -> float:
    """Return conservative signed clearance from an aircraft envelope.

    Zero is exact contact, positive is separation, and negative is penetration.
    MeshPrimitive instances are visual-only in the School Map package and are
    therefore excluded from collision evaluation.
    """

    if isinstance(primitive, MeshPrimitive):
        return math.inf
    if isinstance(primitive, BoxPrimitive):
        delta_x = envelope_center[0] - primitive.center_x
        delta_y = envelope_center[1] - primitive.center_y
        cosine = math.cos(primitive.yaw_rad)
        sine = math.sin(primitive.yaw_rad)
        local_x = cosine * delta_x + sine * delta_y
        local_y = -sine * delta_x + cosine * delta_y
        outside_x = max(abs(local_x) - primitive.size_x / 2, 0.0)
        outside_y = max(abs(local_y) - primitive.size_y / 2, 0.0)
        horizontal = math.hypot(outside_x, outside_y) - envelope.radius_m
        vertical = (
            abs(envelope_center[2] - primitive.center_z)
            - primitive.size_z / 2
            - envelope.half_height_m
        )
        return _orthogonal_clearance(horizontal, vertical)
    if isinstance(primitive, CylinderPrimitive) and (
        abs(primitive.roll_rad) <= 1e-12 and abs(primitive.pitch_rad) <= 1e-12
    ):
        horizontal = (
            math.hypot(
                envelope_center[0] - primitive.center_x,
                envelope_center[1] - primitive.center_y,
            )
            - primitive.radius_m
            - envelope.radius_m
        )
        vertical = (
            abs(envelope_center[2] - primitive.center_z)
            - primitive.height_m / 2
            - envelope.half_height_m
        )
        return _orthogonal_clearance(horizontal, vertical)
    if isinstance(primitive, (CylinderPrimitive, CapsulePrimitive)):
        start, end = _axis_endpoints(primitive)
        return (
            _point_segment_distance(envelope_center, start, end)
            - primitive.radius_m
            - envelope.conservative_sphere_radius_m
        )
    if isinstance(primitive, SpherePrimitive):
        return (
            math.dist(
                envelope_center,
                (primitive.center_x, primitive.center_y, primitive.center_z),
            )
            - primitive.radius_m
            - envelope.conservative_sphere_radius_m
        )
    raise TypeError(f"Unsupported School Map collision primitive: {primitive!r}")


def sample_polyline(points: Sequence[WorldPoint], interval_m: float) -> list[WorldPoint]:
    if not math.isfinite(interval_m) or interval_m <= 0:
        raise ValueError("route sample interval must be finite and greater than zero")
    if not points:
        raise ValueError("route must contain at least one waypoint")
    samples: list[WorldPoint] = []
    for start, end in zip(points[:-1], points[1:], strict=True):
        segment_samples = max(1, math.ceil(math.dist(start, end) / interval_m))
        samples.extend(
            (
                start[0] + (end[0] - start[0]) * sample_index / segment_samples,
                start[1] + (end[1] - start[1]) * sample_index / segment_samples,
                start[2] + (end[2] - start[2]) * sample_index / segment_samples,
            )
            for sample_index in range(segment_samples)
        )
    samples.append(points[-1])
    return samples


def validate_route_clearance(
    envelope_centers: Iterable[WorldPoint],
    primitives: Sequence[CollisionPrimitive],
    *,
    penetration_tolerance_m: float = 0.001,
    maximum_reported_collisions: int = 50,
) -> RouteClearanceResult:
    if penetration_tolerance_m < 0 or not math.isfinite(penetration_tolerance_m):
        raise ValueError("penetration tolerance must be finite and non-negative")
    minimum_clearance = math.inf
    minimum_point: WorldPoint | None = None
    minimum_primitive = ""
    collisions: list[tuple[WorldPoint, str, float]] = []
    sample_count = 0
    collision_count = 0
    for point in envelope_centers:
        sample_count += 1
        for primitive in primitives:
            clearance = vehicle_clearance_to_primitive_m(point, primitive)
            if clearance < minimum_clearance:
                minimum_clearance = clearance
                minimum_point = point
                minimum_primitive = primitive.name
            if clearance < -penetration_tolerance_m:
                collision_count += 1
                if len(collisions) < maximum_reported_collisions:
                    collisions.append((point, primitive.name, clearance))
    if sample_count == 0 or minimum_point is None:
        raise ValueError("route clearance validation requires at least one sample")
    return RouteClearanceResult(
        sample_count=sample_count,
        collision_count=collision_count,
        minimum_clearance_m=minimum_clearance,
        minimum_clearance_point=minimum_point,
        minimum_clearance_primitive=minimum_primitive,
        collisions=tuple(collisions),
    )


def world_envelope_center_to_px4_local_track(
    point: WorldPoint,
    *,
    model_root_world: WorldPoint,
    envelope: VehicleCollisionEnvelope = DEFAULT_VEHICLE_ENVELOPE,
) -> Px4LocalTrackPoint:
    """Convert School Map envelope-center coordinates to PX4/Gazebo track fields.

    The returned tuple uses the executor's historical field names x=north and
    y=east. PX4 gz_bridge maps those to Gazebo y/x respectively, which is the
    measured physical mapping used by School Map.
    """

    model_root_x = point[0]
    model_root_y = point[1]
    model_root_z = point[2] - envelope.center_above_model_root_m
    return (
        model_root_y - model_root_world[1],
        model_root_x - model_root_world[0],
        model_root_z - model_root_world[2],
    )


def px4_local_track_to_world_envelope_center(
    point: Px4LocalTrackPoint,
    *,
    model_root_world: WorldPoint,
    envelope: VehicleCollisionEnvelope = DEFAULT_VEHICLE_ENVELOPE,
) -> WorldPoint:
    return (
        model_root_world[0] + point[1],
        model_root_world[1] + point[0],
        model_root_world[2] + point[2] + envelope.center_above_model_root_m,
    )


def model_root_to_world_envelope_center(
    point: WorldPoint,
    envelope: VehicleCollisionEnvelope = DEFAULT_VEHICLE_ENVELOPE,
) -> WorldPoint:
    return (point[0], point[1], point[2] + envelope.center_above_model_root_m)
