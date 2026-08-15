"""Strict wire models for the shared DroneDream mission-autonomy service."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Edition = Literal["universal", "sim", "lab", "field"]
ExecutionTarget = Literal["simulation", "hitl", "hardware"]
PerceptionMode = Literal["map", "vision", "fusion"]
ExecutionAdapter = Literal[
    "px4_gazebo_contract",
    "hitl_contract",
    "hardware_contract",
]
RuntimePhase = Literal[
    "ready",
    "takeoff",
    "navigating",
    "pickup",
    "replanning",
    "returning",
    "landing",
    "holding",
    "completed",
    "aborted",
]
SafetyAction = Literal["continue", "hold", "land", "abort"]
RuntimeComponentId = Literal[
    "mission_executive",
    "perception_vio_slam",
    "world_model",
    "global_planner",
    "local_planner",
    "trajectory_tracker",
    "px4_bridge",
    "safety_supervisor",
    "evidence_recorder",
]
RuntimeComponentStatus = Literal["available", "shadow", "locked"]
RuntimeMode = Literal["simulation_contract", "hitl_shadow", "hardware_locked"]
RuntimeBridge = Literal["px4_gazebo", "px4_hitl_shadow", "px4_hardware_locked"]
TaskNodeStatus = Literal[
    "pending",
    "ready",
    "active",
    "blocked",
    "completed",
    "failed",
    "skipped",
]
TaskExecutor = Literal[
    "language_model",
    "mission_executive",
    "perception",
    "global_planner",
    "local_planner",
    "payload_controller",
    "px4_bridge",
    "operator",
]
TaskRisk = Literal["low", "medium", "high", "critical"]
MissionAction = Literal[
    "takeoff",
    "transit",
    "traverse_stairs",
    "pass_gate",
    "pickup",
    "return",
    "land",
]
RuntimeDecisionKind = Literal[
    "session",
    "task_transition",
    "dynamic_entity",
    "safety",
    "operator",
]
AutonomyHarnessStatus = Literal[
    "needs_assets",
    "needs_input",
    "draft",
    "blocked",
]
AutonomyAssetKind = Literal["aircraft", "map"]
AutonomyToolOutcome = Literal["accepted", "blocked"]


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
        "classroom",
        "office",
        "cafeteria",
        "road",
        "fence",
        "street-light",
        "bicycle-shelter",
        "guard-booth",
        "launch",
        "door",
        "window",
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
    action: MissionAction
    label: str = Field(min_length=1, max_length=160)
    payload_delta_kg: float = Field(default=0.0, ge=0.0, le=10.0)


class MissionTaskNode(StrictModel):
    task_id: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    label: str = Field(min_length=1, max_length=200)
    status: TaskNodeStatus = "pending"
    depends_on: list[str] = Field(default_factory=list, max_length=16)
    executor: TaskExecutor
    risk: TaskRisk
    max_retries: int = Field(default=1, ge=0, le=20)
    timeout_s: float = Field(default=30.0, gt=0.0, le=3600.0)
    fallback: SafetyAction
    expected_output: str = Field(min_length=1, max_length=240)
    completion_evidence: list[str] = Field(default_factory=list, max_length=12)
    inserted_by: Literal["compiler", "runtime", "operator"] = "compiler"


class MissionTaskGraph(StrictModel):
    schema_version: Literal["dronedream.autonomy.task-graph.v1"] = (
        "dronedream.autonomy.task-graph.v1"
    )
    revision: int = Field(default=1, ge=1)
    nodes: list[MissionTaskNode] = Field(min_length=1, max_length=128)
    active_node_ids: list[str] = Field(default_factory=list, max_length=16)
    change_reason: str = Field(default="compiled", min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_graph(self) -> MissionTaskGraph:
        identifiers = [node.task_id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("task graph contains duplicate task_id values")
        known = set(identifiers)
        for node in self.nodes:
            if node.task_id in node.depends_on:
                raise ValueError("task graph node cannot depend on itself")
            if any(dependency not in known for dependency in node.depends_on):
                raise ValueError("task graph dependency is missing")
        if any(task_id not in known for task_id in self.active_node_ids):
            raise ValueError("active_node_ids contains an unknown task")
        return self


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
    def validate_mass_contract(self) -> VehicleEnvelope:
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


class AutonomyHarnessAsset(StrictModel):
    kind: AutonomyAssetKind
    asset_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    name: str = Field(min_length=1, max_length=160)
    version: int = Field(ge=1, le=1_000_000)
    status: str = Field(min_length=1, max_length=64)
    content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    qualification_receipt_id: str | None = Field(default=None, max_length=160)
    capabilities: dict[str, str | int | float | bool | list[str] | None] = Field(
        default_factory=dict,
        max_length=48,
    )


class AutonomyHarnessInspectRequest(StrictModel):
    schema_version: Literal["dronedream.autonomy.harness-inspect.v1"] = (
        "dronedream.autonomy.harness-inspect.v1"
    )
    edition: Edition
    natural_language: str = Field(min_length=3, max_length=2_000)
    aircraft: AutonomyHarnessAsset
    map_pack: AutonomyHarnessAsset

    @model_validator(mode="after")
    def validate_asset_kinds(self) -> AutonomyHarnessInspectRequest:
        if self.aircraft.kind != "aircraft" or self.map_pack.kind != "map":
            raise ValueError("autonomy harness assets are bound to the wrong slots")
        return self


class AutonomyCompileAssetContext(StrictModel):
    schema_version: Literal["dronedream.autonomy.compile-assets.v1"] = (
        "dronedream.autonomy.compile-assets.v1"
    )
    harness_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    aircraft: AutonomyHarnessAsset
    map_pack: AutonomyHarnessAsset

    @model_validator(mode="after")
    def validate_asset_kinds(self) -> AutonomyCompileAssetContext:
        if self.aircraft.kind != "aircraft" or self.map_pack.kind != "map":
            raise ValueError("compile assets are bound to the wrong slots")
        return self


class AutonomyHarnessToolReceipt(StrictModel):
    tool_id: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9._-]*$",
    )
    tool_version: str = Field(min_length=1, max_length=32)
    outcome: AutonomyToolOutcome
    evidence: dict[str, str | int | float | bool | list[str] | None] = Field(
        default_factory=dict,
        max_length=48,
    )
    issue_codes: list[str] = Field(default_factory=list, max_length=24)


class AutonomyHarnessRepairPolicy(StrictModel):
    schema_version: Literal["dronedream.autonomy.repair-policy.v1"] = (
        "dronedream.autonomy.repair-policy.v1"
    )
    semantic_attempt_limit: int = Field(default=3, ge=0, le=8)
    trajectory_attempt_limit: int = Field(default=5, ge=0, le=12)
    repeated_plan_hash_limit: int = Field(default=2, ge=1, le=4)
    may_relax_safety_constraints: Literal[False] = False


class AutonomyHarnessInspectResponse(StrictModel):
    schema_version: Literal["dronedream.autonomy.harness-context.v1"] = (
        "dronedream.autonomy.harness-context.v1"
    )
    prompt_version: Literal["dronedream.autonomy.system.v1"] = "dronedream.autonomy.system.v1"
    tool_registry_version: Literal["dronedream.autonomy.tools.v1"] = "dronedream.autonomy.tools.v1"
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AutonomyHarnessStatus
    planning_ready: bool
    blockers: list[str] = Field(default_factory=list, max_length=24)
    required_next_actions: list[str] = Field(default_factory=list, max_length=24)
    eligible_tool_ids: list[str] = Field(default_factory=list, max_length=24)
    tool_receipts: list[AutonomyHarnessToolReceipt] = Field(max_length=24)
    repair_policy: AutonomyHarnessRepairPolicy = Field(default_factory=AutonomyHarnessRepairPolicy)


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
    asset_context: AutonomyCompileAssetContext | None = None

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
    schema_version: Literal["dronedream.autonomy.mission.v2"] = "dronedream.autonomy.mission.v2"
    contract_id: str
    edition: Edition
    execution_target: ExecutionTarget
    scene_id: str
    perception_mode: PerceptionMode
    intent: str
    steps: list[MissionStep]
    task_graph: MissionTaskGraph
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
    adapter: ExecutionAdapter
    can_execute: bool
    validated_signed_pack_count: int = 0
    blockers: list[str]
    required_next_steps: list[str]


class RuntimeComponent(StrictModel):
    id: RuntimeComponentId
    status: RuntimeComponentStatus
    role: str = Field(min_length=1, max_length=160)
    rate_hz: float | None = Field(default=None, gt=0.0, le=1000.0)
    actuator_authority: bool = False


class OnboardRuntimeProfile(StrictModel):
    schema_version: Literal["dronedream.autonomy.runtime-profile.v1"] = (
        "dronedream.autonomy.runtime-profile.v1"
    )
    mode: RuntimeMode
    bridge: RuntimeBridge
    command_authority: bool
    persistence: Literal["process_local_bounded"] = "process_local_bounded"
    observation_contract: Literal["dronedream.autonomy.observation.v1"] = (
        "dronedream.autonomy.observation.v1"
    )
    components: list[RuntimeComponent]
    fail_safe_actions: list[SafetyAction]


class PerceivedEntity(StrictModel):
    track_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    kind: Literal["person", "vehicle", "animal", "obstacle", "unknown"]
    position_m: Vector3
    velocity_mps: Vector3
    confidence: float = Field(ge=0.0, le=1.0)
    safety_radius_m: float = Field(default=0.8, ge=0.1, le=20.0)
    age_ms: int = Field(default=0, ge=0, le=60000)
    source_stream: str = Field(min_length=1, max_length=80)


class PerceptionStreamHealth(StrictModel):
    stream_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    kind: Literal["rgb", "depth", "stereo", "thermal", "lidar", "vio", "slam", "map"]
    source: Literal["simulator", "onboard", "cloud", "external"]
    status: Literal["healthy", "degraded", "stale", "offline"]
    rate_hz: float = Field(ge=0.0, le=1000.0)
    latency_ms: float = Field(ge=0.0, le=60000.0)
    dropped_percent: float = Field(default=0.0, ge=0.0, le=100.0)


class RuntimeObservation(StrictModel):
    schema_version: Literal["dronedream.autonomy.observation.v1"] = (
        "dronedream.autonomy.observation.v1"
    )
    sequence: int = Field(ge=1)
    monotonic_ms: int = Field(ge=0)
    armed: bool
    landed: bool
    position_m: Vector3
    velocity_mps: Vector3
    localization_covariance_m2: float = Field(ge=0.0, le=10000.0)
    perception_age_ms: int = Field(ge=0, le=60000)
    minimum_clearance_m: float = Field(ge=0.0, le=1000.0)
    battery_percent: float = Field(ge=0.0, le=100.0)
    link_ok: bool
    geofence_ok: bool
    payload_mass_kg: float = Field(ge=0.0, le=50.0)
    mission_progress: float = Field(ge=0.0, le=1.0)
    pickup_confirmed: bool = False
    local_replan_active: bool = False
    emergency_stop: bool = False
    perceived_entities: list[PerceivedEntity] = Field(default_factory=list, max_length=128)
    stream_health: list[PerceptionStreamHealth] = Field(default_factory=list, max_length=24)


class RuntimeDecisionEvent(StrictModel):
    revision: int = Field(ge=1)
    created_at: datetime
    kind: RuntimeDecisionKind
    code: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=240)
    task_ids: list[str] = Field(default_factory=list, max_length=16)
    entity_ids: list[str] = Field(default_factory=list, max_length=32)


class SafetyDecision(StrictModel):
    action: SafetyAction
    accepted: bool
    codes: list[str]


class RuntimeSessionCreateRequest(StrictModel):
    mission: AutonomyCompileRequest
    client_request_id: str = Field(
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class RuntimeOperatorCommand(StrictModel):
    action: Literal["hold", "resume", "abort"]
    reason: str = Field(min_length=3, max_length=240)


class RuntimeSession(StrictModel):
    schema_version: Literal["dronedream.autonomy.runtime-session.v1"] = (
        "dronedream.autonomy.runtime-session.v1"
    )
    session_id: str
    contract_id: str
    execution_target: ExecutionTarget
    phase: RuntimePhase
    bridge: str
    command_authority: bool
    created_at: datetime
    updated_at: datetime
    latest_sequence: int
    latest_monotonic_ms: int
    observation_count: int
    decision: SafetyDecision
    task_graph: MissionTaskGraph
    perceived_entities: list[PerceivedEntity] = Field(default_factory=list, max_length=128)
    stream_health: list[PerceptionStreamHealth] = Field(default_factory=list, max_length=24)
    decision_events: list[RuntimeDecisionEvent] = Field(default_factory=list, max_length=100)
    evidence_chain_head: str
    terminal: bool


class AutonomyCompileResponse(StrictModel):
    scene: TerrainScene
    contract: MissionContract
    trajectory: list[RoutePoint]
    feasible: bool
    issues: list[ValidationIssue]
    metrics: MissionMetrics
    execution_policy: ExecutionPolicy
    planner: dict[str, str]
    runtime_profile: OnboardRuntimeProfile
