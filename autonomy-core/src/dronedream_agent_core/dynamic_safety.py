"""Deterministic short-horizon avoidance for static and tracked moving obstacles.

The language model can request a route objective or a replan, but this module owns
the high-rate safety decision.  It samples reachable velocities, predicts both the
vehicle and fresh obstacle tracks, and fails closed to a hold when no candidate
maintains the configured clearance.
"""

from __future__ import annotations

import math
from typing import Any

from .collision import vehicle_clearance
from .contracts import LocalPlannerRequest, PredictiveSafetyDecision, Vector3

Point = tuple[float, float, float]


def _point(value: Vector3) -> Point:
    return value.x, value.y, value.z


def _magnitude(value: Point) -> float:
    return math.sqrt(sum(component * component for component in value))


def _subtract(first: Point, second: Point) -> Point:
    return tuple(first[index] - second[index] for index in range(3))


def _limit_delta(current: Point, requested: Point, maximum_delta: float) -> Point:
    delta = _subtract(requested, current)
    magnitude = _magnitude(delta)
    if magnitude <= maximum_delta or magnitude <= 1e-12:
        return requested
    scale = maximum_delta / magnitude
    return tuple(current[index] + delta[index] * scale for index in range(3))


def _orthogonal_clearance(horizontal: float, vertical: float) -> float:
    if horizontal > 0 and vertical > 0:
        return math.hypot(horizontal, vertical)
    if horizontal > 0:
        return horizontal
    if vertical > 0:
        return vertical
    return max(horizontal, vertical)


def _dynamic_clearance(
    point: Point,
    *,
    elapsed: float,
    request: LocalPlannerRequest,
) -> tuple[float, str | None]:
    minimum = 999.0
    threat: str | None = None
    for obstacle in request.dynamic_obstacles:
        if obstacle.confidence < 0.35 or obstacle.age_seconds > 1.0:
            continue
        position = _point(obstacle.position_m)
        velocity = _point(obstacle.velocity_mps)
        predicted = tuple(
            position[index] + velocity[index] * (elapsed + obstacle.age_seconds)
            for index in range(3)
        )
        uncertainty = (1.0 - obstacle.confidence) * 0.5
        uncertainty += obstacle.age_seconds * _magnitude(velocity) * 0.25
        horizontal = math.hypot(point[0] - predicted[0], point[1] - predicted[1])
        horizontal -= request.vehicle_radius_m + obstacle.radius_m + uncertainty
        vertical = abs(point[2] - predicted[2])
        vertical -= (request.vehicle_height_m + obstacle.height_m) / 2 + uncertainty
        clearance = _orthogonal_clearance(horizontal, vertical)
        if clearance < minimum:
            minimum = clearance
            threat = obstacle.obstacle_id
    return minimum, threat


def _candidate_velocities(request: LocalPlannerRequest) -> list[Point]:
    current = _point(request.current_velocity_mps)
    position = _point(request.current_position_m)
    target = _point(request.target_position_m)
    to_target = _subtract(target, position)
    horizontal_distance = math.hypot(to_target[0], to_target[1])
    heading = math.atan2(to_target[1], to_target[0]) if horizontal_distance > 1e-9 else 0.0
    target_distance = max(_magnitude(to_target), 1e-9)
    desired_speed = min(request.max_speed_mps, target_distance)
    desired_vertical = desired_speed * to_target[2] / target_distance
    maximum_delta = request.max_acceleration_mps2 * request.prediction_step_seconds
    candidates: list[Point] = []
    for speed_ratio in (1.0, 0.7, 0.4):
        horizontal_speed = desired_speed * speed_ratio
        for angle_degrees in (0, -30, 30, -60, 60, -90, 90, 180):
            angle = heading + math.radians(angle_degrees)
            for vertical_bias in (0.0, 0.35, -0.35):
                requested = (
                    horizontal_speed * math.cos(angle),
                    horizontal_speed * math.sin(angle),
                    max(
                        -request.max_speed_mps,
                        min(
                            request.max_speed_mps,
                            desired_vertical + vertical_bias * desired_speed,
                        ),
                    ),
                )
                candidates.append(_limit_delta(current, requested, maximum_delta))
    candidates.append(_limit_delta(current, (0.0, 0.0, 0.0), maximum_delta))
    return list(dict.fromkeys(candidates))


def _predict(
    request: LocalPlannerRequest,
    velocity: Point,
    static_primitives: list[dict[str, Any]],
) -> tuple[list[Point], float, float, str | None]:
    origin = _point(request.current_position_m)
    steps = max(
        1,
        math.ceil(request.prediction_horizon_seconds / request.prediction_step_seconds),
    )
    path: list[Point] = []
    minimum = 999.0
    time_to_minimum = 0.0
    threat: str | None = None
    for index in range(1, steps + 1):
        elapsed = min(
            request.prediction_horizon_seconds,
            index * request.prediction_step_seconds,
        )
        point = tuple(origin[axis] + velocity[axis] * elapsed for axis in range(3))
        path.append(point)
        static_clearance = 999.0
        static_name: str | None = None
        for primitive in static_primitives:
            clearance = vehicle_clearance(
                point,
                primitive,
                radius_m=request.vehicle_radius_m,
                half_height_m=request.vehicle_height_m / 2,
            )
            if clearance < static_clearance:
                static_clearance = clearance
                static_name = f"static:{primitive.get('name', 'unknown')}"
        dynamic_clearance, dynamic_name = _dynamic_clearance(
            point,
            elapsed=elapsed,
            request=request,
        )
        clearance, name = min(
            (static_clearance, static_name),
            (dynamic_clearance, dynamic_name),
            key=lambda item: item[0],
        )
        if clearance < minimum:
            minimum = clearance
            time_to_minimum = elapsed
            threat = name
    return path, minimum, time_to_minimum, threat


def predictive_safety_decision(
    request: LocalPlannerRequest,
    static_primitives: list[dict[str, Any]],
) -> PredictiveSafetyDecision:
    """Choose a reachable safe velocity or fail closed to a bounded hold."""

    position = _point(request.current_position_m)
    unhealthy_codes: list[str] = []
    if not request.perception_stream_healthy:
        unhealthy_codes.append("PERCEPTION_STREAM_UNHEALTHY")
    if request.perception_stream_age_seconds > request.maximum_perception_age_seconds:
        unhealthy_codes.append("PERCEPTION_STREAM_STALE")
    if request.localization_covariance_m2 > request.maximum_localization_covariance_m2:
        unhealthy_codes.append("LOCALIZATION_UNCERTAIN")
    if unhealthy_codes:
        current = _point(request.current_velocity_mps)
        maximum_delta = request.max_acceleration_mps2 * request.prediction_step_seconds
        brake_velocity = _limit_delta(current, (0.0, 0.0, 0.0), maximum_delta)
        path, clearance, minimum_time, threat = _predict(
            request,
            brake_velocity,
            static_primitives,
        )
        return PredictiveSafetyDecision(
            action="hold",
            selected_velocity_mps=Vector3(
                x=brake_velocity[0],
                y=brake_velocity[1],
                z=brake_velocity[2],
            ),
            predicted_path_m=[Vector3(x=item[0], y=item[1], z=item[2]) for item in path],
            minimum_predicted_clearance_m=clearance,
            time_to_minimum_clearance_seconds=minimum_time,
            threat_obstacle_id=threat,
            evaluated_candidate_count=1,
            issue_codes=[*unhealthy_codes, "HOLD_UNTIL_FRESH_LOCAL_WORLD"],
        )
    target = _point(request.target_position_m)
    target_delta = _subtract(target, position)
    target_distance = max(_magnitude(target_delta), 1e-9)
    target_unit = tuple(component / target_distance for component in target_delta)
    current = _point(request.current_velocity_mps)
    evaluations: list[tuple[float, Point, list[Point], float, float, str | None]] = []
    fallback: tuple[Point, list[Point], float, float, str | None] | None = None
    candidates = _candidate_velocities(request)
    for velocity in candidates:
        path, clearance, minimum_time, threat = _predict(
            request,
            velocity,
            static_primitives,
        )
        if _magnitude(velocity) < 0.05:
            fallback = velocity, path, clearance, minimum_time, threat
        if clearance < request.required_clearance_m:
            continue
        progress = sum(velocity[index] * target_unit[index] for index in range(3))
        smoothness = _magnitude(_subtract(velocity, current))
        clearance_reward = min(clearance, request.required_clearance_m + 2.0)
        score = progress * 3.0 + clearance_reward * 0.8 - smoothness * 0.25
        evaluations.append((score, velocity, path, clearance, minimum_time, threat))

    candidate_count = len(candidates)
    if not evaluations:
        if fallback is None:
            fallback = (0.0, 0.0, 0.0), [position], -999.0, 0.0, None
        velocity, path, clearance, minimum_time, threat = fallback
        return PredictiveSafetyDecision(
            action="hold",
            selected_velocity_mps=Vector3(x=velocity[0], y=velocity[1], z=velocity[2]),
            predicted_path_m=[Vector3(x=item[0], y=item[1], z=item[2]) for item in path],
            minimum_predicted_clearance_m=clearance,
            time_to_minimum_clearance_seconds=minimum_time,
            threat_obstacle_id=threat,
            evaluated_candidate_count=candidate_count,
            issue_codes=["NO_SAFE_LOCAL_VELOCITY", "HOLD_AND_REQUEST_REPLAN"],
        )

    _score, velocity, path, clearance, minimum_time, threat = max(
        evaluations, key=lambda item: item[0]
    )
    speed = _magnitude(velocity)
    desired_speed = min(request.max_speed_mps, target_distance)
    forward = sum(velocity[index] * target_unit[index] for index in range(3))
    cosine = forward / max(speed, 1e-9)
    if speed < 0.05:
        action = "hold"
    elif cosine < math.cos(math.radians(45)):
        action = "replan"
    elif speed < desired_speed * 0.75 or clearance < request.required_clearance_m + 0.4:
        action = "slow"
    else:
        action = "continue"
    issue_codes = [] if action == "continue" else [f"LOCAL_SAFETY_{action.upper()}"]
    return PredictiveSafetyDecision(
        action=action,
        selected_velocity_mps=Vector3(x=velocity[0], y=velocity[1], z=velocity[2]),
        predicted_path_m=[Vector3(x=item[0], y=item[1], z=item[2]) for item in path],
        minimum_predicted_clearance_m=clearance,
        time_to_minimum_clearance_seconds=minimum_time,
        threat_obstacle_id=threat,
        evaluated_candidate_count=candidate_count,
        issue_codes=issue_codes,
    )
