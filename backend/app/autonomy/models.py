"""Strict wire models for the shared DroneDream mission-autonomy service."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Edition = Literal["universal", "sim", "lab", "field"]
ExecutionTarget = Literal["simulation", "hitl", "hardware"]
PerceptionMode = Literal["map", "vision", "fusion"]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
        strict=True,
    )


class Vector3(StrictModel):
    x: float
    y: float
    z: float


class TerrainObject(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: Literal[
        "building",
        "stairwell",
        "wall",
        "tree",
        "sign",
        "pole",
        "gate",
        "pickup",
        "landing",
    ]
    center: Vector3
    size: Vector3
    traversable: bool = False
    required_clearance_m: float = Field(default=0.35, ge=0.1, le=5.0)


class RoutePoint(StrictModel):
    x: float
    y: float
    z: float
    phase: Literal["launch", "transit", "stairs", "gate", "pickup", "return", "land"]
    speed_limit_mps: float = Field(ge=0.1, le=10.0)


class MissionStep(StrictModel):
    order: int = Field(ge=1, le=64)
    action: Literal[
        "takeoff",
        "transit",
        "traverse_stairs",
        "pass_gate",
        "pickup",
        "return",
        "land",
    ]
    label: str = Field(min_length=1, max_length=160)
    payload_delta_kg: float = Field(default=0.0, ge=0.0, le=10.0)


class VehicleEnvelope(StrictModel):
    dry_mass_kg: float = Field(default=1.55, gt=0.1, le=50.0)
    launch_payload_kg: float = Field(default=0.10, ge=0.0, le=20.0)
    pickup_payload_kg: float = Field(default=0.35, ge=0.0, le=20.0)
    max_takeoff_mass_kg: float = Field(default=2.60, gt=0.1, le=70.0)
    max_total_thrust_n: float = Field(default=39.0, gt=1.0, le=5000.0)
    radius_m: float = Field(default=0.28, ge=0.05, le=3.0)
    max_speed_mps: float = Field(default=1.30, ge=0.2, le=20.0)
    max_acceleration_mps2: float = Field(default=3.0, ge=0.2, le=30.0)
    reserve_battery_percent: float = Field(default=30.0, ge=10.0, le=90.0)

    @model_validator(mode="after")
    def validate_mass_contract(self) -> "VehicleEnvelope":
        if self.dry_mass_kg + self.launch_payload_kg > self.max_takeoff_mass_kg:
            raise ValueError("launch mass exceeds max_takeoff_mass_kg")
        return self


class RuntimeEvidence(StrictModel):
    simulation_qualified: bool = False
    signed_vehicle_pack_id: str | None = Field(default=None, max_length=128)
    operator_confirmed: bool = False
    localization_ready: bool = False
    link_ready: bool = False
    geofence_ready: bool = False
    battery_ready: bool = False


class AutonomyCompileRequest(StrictModel):
    edition: Edition
    execution_target: ExecutionTarget = "simulation"
    natural_language: str = Field(min_length=3, max_length=2000)
    scene_id: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    perception_mode: PerceptionMode | None = None
    vehicle: VehicleEnvelope = Field(default_factory=VehicleEnvelope)
    evidence: RuntimeEvidence = Field(default_factory=RuntimeEvidence)

    @field_validator("natural_language")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        if any(ord(char) < 32 and char not in {"\n", "\t"} for char in value):
            raise ValueError("natural_language contains control characters")
        return value


class TerrainScene(StrictModel):
    id: str
    name: str
    summary: str
    bounds_m: Vector3
    floors: int = Field(ge=1, le=64)
    minimum_clearance_m: float = Field(gt=0.0, le=20.0)
    objects: list[TerrainObject]
    reference_path: list[RoutePoint]
    tags: list[str]


class MissionContract(StrictModel):
    schema_version: Literal["dronedream.autonomy.mission.v1"] = (
        "dronedream.autonomy.mission.v1"
    )
    contract_id: str
    edition: Edition
    execution_target: ExecutionTarget
    scene_id: str
    perception_mode: PerceptionMode
    intent: str
    steps: list[MissionStep]
    immutable_safety_rules: list[str]


class ValidationIssue(StrictModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class MissionMetrics(StrictModel):
    route_length_m: float = Field(ge=0.0)
    vertical_travel_m: float = Field(ge=0.0)
    estimated_duration_s: float = Field(ge=0.0)
    minimum_clearance_m: float = Field(ge=0.0)
    launch_mass_kg: float = Field(ge=0.0)
    post_pickup_mass_kg: float = Field(ge=0.0)
    post_pickup_thrust_to_weight: float = Field(ge=0.0)
    braking_distance_m: float = Field(ge=0.0)

    @field_validator("*")
    @classmethod
    def finite_metrics(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("metrics must be finite")
        return round(value, 3)


class ExecutionPolicy(StrictModel):
    readiness: Literal["simulation_ready", "preview_only", "denied"]
    adapter: Literal["px4_gazebo_contract", "hitl_contract", "hardware_contract"]
    can_execute: bool
    validated_signed_pack_count: int = 0
    blockers: list[str]
    required_next_steps: list[str]


class AutonomyCompileResponse(StrictModel):
    scene: TerrainScene
    contract: MissionContract
    trajectory: list[RoutePoint]
    feasible: bool
    issues: list[ValidationIssue]
    metrics: MissionMetrics
    execution_policy: ExecutionPolicy
    planner: dict[str, str]
