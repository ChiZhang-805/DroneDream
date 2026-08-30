"""Continuous conservative vehicle-envelope checks against real SDF semantics."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .contracts import GraphRoute, RouteClearanceReport, RouteCollision, Vector3
from .hashing import sha256_json

Point = tuple[float, float, float]


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _orthogonal(first: float, second: float) -> float:
    if first > 0 and second > 0:
        return math.hypot(first, second)
    if first > 0:
        return first
    if second > 0:
        return second
    return max(first, second)


def _axis_endpoints(primitive: dict[str, Any], length: float) -> tuple[Point, Point]:
    roll = float(primitive.get("roll_rad", 0.0))
    pitch = float(primitive.get("pitch_rad", 0.0))
    yaw = float(primitive.get("yaw_rad", 0.0))
    axis = (
        math.cos(yaw) * math.sin(pitch) * math.cos(roll) + math.sin(yaw) * math.sin(roll),
        math.sin(yaw) * math.sin(pitch) * math.cos(roll) - math.cos(yaw) * math.sin(roll),
        math.cos(pitch) * math.cos(roll),
    )
    center = (
        float(primitive["center_x"]),
        float(primitive["center_y"]),
        float(primitive["center_z"]),
    )
    half = length / 2
    return (
        tuple(center[index] - axis[index] * half for index in range(3)),
        tuple(center[index] + axis[index] * half for index in range(3)),
    )


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
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


def vehicle_clearance(
    point: Point,
    primitive: dict[str, Any],
    *,
    radius_m: float,
    half_height_m: float,
) -> float:
    center = (
        float(primitive["center_x"]),
        float(primitive["center_y"]),
        float(primitive["center_z"]),
    )
    if "size_x" in primitive:
        delta_x = point[0] - center[0]
        delta_y = point[1] - center[1]
        yaw = float(primitive.get("yaw_rad", 0.0))
        cosine = math.cos(yaw)
        sine = math.sin(yaw)
        local_x = cosine * delta_x + sine * delta_y
        local_y = -sine * delta_x + cosine * delta_y
        outside_x = max(abs(local_x) - float(primitive["size_x"]) / 2, 0.0)
        outside_y = max(abs(local_y) - float(primitive["size_y"]) / 2, 0.0)
        horizontal = math.hypot(outside_x, outside_y) - radius_m
        vertical = abs(point[2] - center[2]) - float(primitive["size_z"]) / 2 - half_height_m
        return _orthogonal(horizontal, vertical)

    primitive_radius = float(primitive["radius_m"])
    conservative_radius = math.hypot(radius_m, half_height_m)
    if "length_m" in primitive:
        start, end = _axis_endpoints(primitive, float(primitive["length_m"]))
        return _point_segment_distance(point, start, end) - primitive_radius - conservative_radius
    if "height_m" in primitive:
        roll = abs(float(primitive.get("roll_rad", 0.0)))
        pitch = abs(float(primitive.get("pitch_rad", 0.0)))
        height = float(primitive["height_m"])
        if roll <= 1e-12 and pitch <= 1e-12:
            horizontal = math.hypot(point[0] - center[0], point[1] - center[1])
            horizontal -= primitive_radius + radius_m
            vertical = abs(point[2] - center[2]) - height / 2 - half_height_m
            return _orthogonal(horizontal, vertical)
        start, end = _axis_endpoints(primitive, height)
        return _point_segment_distance(point, start, end) - primitive_radius - conservative_radius
    return math.dist(point, center) - primitive_radius - conservative_radius


# Kept as a compatibility alias for older runtime integrations.  New safety code
# uses the public name so the geometry contract is explicit and testable.
_clearance = vehicle_clearance


def _samples(points: list[Vector3], interval_m: float) -> list[Point]:
    if not points:
        raise ValueError("route contains no points")
    output: list[Point] = []
    tuples = [(point.x, point.y, point.z) for point in points]
    for start, end in zip(tuples, tuples[1:], strict=False):
        count = max(1, math.ceil(math.dist(start, end) / interval_m))
        output.extend(
            tuple(start[axis] + (end[axis] - start[axis]) * index / count for axis in range(3))
            for index in range(count)
        )
    output.append(tuples[-1])
    return output


def validate_route_clearance(
    route: GraphRoute,
    semantic_path: Path,
    *,
    vehicle_diameter_m: float,
    vehicle_height_m: float,
    sample_interval_m: float = 0.1,
    penetration_tolerance_m: float = 0.001,
) -> RouteClearanceReport:
    if vehicle_diameter_m <= 0 or vehicle_height_m <= 0:
        raise ValueError("vehicle envelope dimensions must be positive")
    if sample_interval_m <= 0:
        raise ValueError("sample interval must be positive")
    semantic = _load(semantic_path)
    primitives = semantic.get("collision_primitives")
    if not isinstance(primitives, list) or not primitives:
        raise ValueError("semantic artifact has no collision primitives")
    samples = _samples(route.positions_m, sample_interval_m)
    minimum = math.inf
    minimum_point = samples[0]
    minimum_primitive = ""
    collision_count = 0
    collisions: list[RouteCollision] = []
    for sample_index, point in enumerate(samples):
        for primitive in primitives:
            if not isinstance(primitive, dict):
                raise ValueError("collision primitive is not an object")
            clearance = vehicle_clearance(
                point,
                primitive,
                radius_m=vehicle_diameter_m / 2,
                half_height_m=vehicle_height_m / 2,
            )
            if clearance < minimum:
                minimum = clearance
                minimum_point = point
                minimum_primitive = str(primitive.get("name", "unknown"))
            if clearance < -penetration_tolerance_m:
                collision_count += 1
                if len(collisions) < 100:
                    collisions.append(
                        RouteCollision(
                            sample_index=sample_index,
                            position_m=Vector3(x=point[0], y=point[1], z=point[2]),
                            primitive_name=str(primitive.get("name", "unknown")),
                            clearance_m=clearance,
                        )
                    )
    return RouteClearanceReport(
        accepted=collision_count == 0,
        route_sha256=sha256_json(route),
        semantic_sha256=hashlib.sha256(semantic_path.read_bytes()).hexdigest(),
        sample_interval_m=sample_interval_m,
        sample_count=len(samples),
        primitive_count=len(primitives),
        collision_count=collision_count,
        minimum_clearance_m=minimum,
        minimum_clearance_point=Vector3(x=minimum_point[0], y=minimum_point[1], z=minimum_point[2]),
        minimum_clearance_primitive=minimum_primitive,
        collisions=collisions,
    )
