"""Hash-bound adapter from live world observations to executable local safety commands."""

from __future__ import annotations

from typing import Any

from .contracts import (
    LocalPlannerRequest,
    RuntimeLocalSafetyCommand,
    RuntimeLocalSafetyObservation,
    Vector3,
    VehicleAsset,
)
from .dynamic_safety import predictive_safety_decision
from .hashing import sha256_json


def evaluate_runtime_local_safety(
    *,
    observation: RuntimeLocalSafetyObservation,
    vehicle: VehicleAsset,
    static_primitives: list[dict[str, Any]],
    required_clearance_m: float,
    generated_at_unix_ms: int,
    command_horizon_seconds: float = 0.2,
    validity_milliseconds: int = 500,
) -> RuntimeLocalSafetyCommand:
    """Produce one short-lived command; consumers must reject it after expiry."""

    if not 0.05 <= command_horizon_seconds <= 1.0:
        raise ValueError("command horizon must be in [0.05, 1.0] seconds")
    if not 50 <= validity_milliseconds <= 2_000:
        raise ValueError("command validity must be in [50, 2000] milliseconds")
    request = LocalPlannerRequest(
        current_position_m=observation.current_position_m,
        current_velocity_mps=observation.current_velocity_mps,
        target_position_m=observation.target_position_m,
        dynamic_obstacles=observation.dynamic_obstacles,
        vehicle_radius_m=vehicle.body_radius_m,
        vehicle_height_m=vehicle.body_height_m,
        max_speed_mps=vehicle.max_speed_mps,
        max_acceleration_mps2=vehicle.max_acceleration_mps2,
        required_clearance_m=required_clearance_m,
        prediction_horizon_seconds=3.0,
        prediction_step_seconds=command_horizon_seconds,
        perception_stream_healthy=observation.stream_healthy,
        perception_stream_age_seconds=observation.stream_age_seconds,
        localization_covariance_m2=observation.localization_covariance_m2,
    )
    decision = predictive_safety_decision(request, static_primitives)
    velocity = decision.selected_velocity_mps
    position = observation.current_position_m
    command_position = Vector3(
        x=position.x + velocity.x * command_horizon_seconds,
        y=position.y + velocity.y * command_horizon_seconds,
        z=position.z + velocity.z * command_horizon_seconds,
    )
    return RuntimeLocalSafetyCommand(
        observation_sha256=sha256_json(observation),
        observation_sequence=observation.sequence,
        generated_at_unix_ms=generated_at_unix_ms,
        valid_until_unix_ms=generated_at_unix_ms + validity_milliseconds,
        source=observation.source,
        command_position_m=command_position,
        decision=decision,
    )

