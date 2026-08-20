"""Versioned structured contracts for the complete flight-agent workflow."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .harness_graph import HarnessStageReceipt, HarnessTopology
from .plugin_contracts import PluginHookReceipt, PluginSnapshot

ModelRole = Literal[
    "intent_parser",
    "intent_critic",
    "plugin_router",
    "task_decomposer",
    "global_planner",
    "plan_critic",
    "execution_monitor",
    "runtime_message_classifier",
    "completion_verifier",
    "context_summarizer",
]
SafetyAction = Literal["continue", "hold", "return", "land", "abort"]
DomainActionId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", min_length=3, max_length=120),
]
TaskAction = DomainActionId


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class Vector3(StrictModel):
    x: float
    y: float
    z: float


class VehicleAsset(StrictModel):
    schema_version: Literal["dronedream.vehicle.v1"] = "dronedream.vehicle.v1"
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str
    coordinate_frame: Literal["base_link_frd"] = "base_link_frd"
    dry_mass_kg: float = Field(gt=0.1, le=50.0)
    max_takeoff_mass_kg: float = Field(gt=0.1, le=70.0)
    body_radius_m: float = Field(ge=0.05, le=3.0)
    body_height_m: float = Field(ge=0.05, le=3.0)
    max_speed_mps: float = Field(gt=0.0, le=20.0)
    max_acceleration_mps2: float = Field(gt=0.0, le=30.0)
    qualified_range_m: float = Field(gt=0.0, le=1_000_000.0)
    reserve_battery_percent: float = Field(ge=10.0, le=90.0)
    max_pickup_payload_kg: float = Field(ge=0.0, le=20.0)
    sensors: list[str] = Field(min_length=1, max_length=24)


class MapNode(StrictModel):
    node_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    label: str = Field(min_length=1, max_length=160)
    position_m: Vector3
    semantic: Literal[
        "launch",
        "office",
        "stairs",
        "door",
        "corridor",
        "outdoor",
        "pickup",
    ]


class MapEdge(StrictModel):
    edge_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    from_node: str
    to_node: str
    distance_m: float = Field(gt=0.0, le=10_000.0)
    minimum_clearance_m: float = Field(ge=0.0, le=100.0)
    speed_limit_mps: float = Field(gt=0.0, le=20.0)
    bidirectional: bool = True
    qualification: Literal["flight-verified", "geometry-derived"] = "geometry-derived"
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class MapAsset(StrictModel):
    schema_version: Literal["dronedream.map-graph.v1"] = "dronedream.map-graph.v1"
    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str
    coordinate_frame: Literal["map_enu"] = "map_enu"
    nodes: list[MapNode] = Field(min_length=2, max_length=10_000)
    edges: list[MapEdge] = Field(min_length=1, max_length=50_000)
    named_entities: dict[str, str] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_graph(self) -> MapAsset:
        identifiers = [node.node_id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("map node identifiers must be unique")
        known = set(identifiers)
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("map edge identifiers must be unique")
        if any(edge.from_node not in known or edge.to_node not in known for edge in self.edges):
            raise ValueError("map edge references an unknown node")
        if any(node_id not in known for node_id in self.named_entities.values()):
            raise ValueError("named entity references an unknown node")
        return self


class CatalogEntity(StrictModel):
    entity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    aliases: list[str] = Field(min_length=1, max_length=24)
    position_m: Vector3
    semantic: str = Field(min_length=1, max_length=96)
    source_pointer: str = Field(min_length=1, max_length=240)


class MapCatalog(StrictModel):
    schema_version: Literal["dronedream.map-catalog.v1"] = "dronedream.map-catalog.v1"
    scene_id: str
    coordinate_frame: Literal["ENU"] = "ENU"
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entities: list[CatalogEntity] = Field(min_length=1, max_length=2_000)
    road_segment_ids: list[str] = Field(default_factory=list, max_length=2_000)
    topology_available: bool
    known_limits: list[str] = Field(default_factory=list, max_length=64)


class AttachmentArtifact(StrictModel):
    schema_version: Literal["dronedream.attachment-artifact.v1"] = (
        "dronedream.attachment-artifact.v1"
    )
    attachment_id: str = Field(pattern=r"^attachment-[0-9a-f]{32}$")
    display_name: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=160)
    size_bytes: int = Field(ge=0, le=512 * 1024 * 1024)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decoder_plugin_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    decoded_kind: Literal[
        "text",
        "document",
        "image",
        "video",
        "audio",
        "rosbag",
        "point-cloud",
        "geospatial",
        "bim",
        "cad",
        "binary-metadata",
    ]
    text: str | None = Field(default=None, max_length=200_000)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    model_input: dict[str, Any] = Field(default_factory=dict)
    issue_codes: list[str] = Field(default_factory=list, max_length=32)


class MissionRequest(StrictModel):
    schema_version: Literal["dronedream.mission-request.v1"] = "dronedream.mission-request.v1"
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=96)
    message: str = Field(min_length=3, max_length=4_000)
    start_entity: str = Field(default="office launch pad", min_length=1, max_length=160)
    locale: Literal["zh-CN", "en-US"] = "zh-CN"
    attachments: list[AttachmentArtifact] = Field(default_factory=list, max_length=32)
    input_channel: Literal["text", "voice", "camera", "api", "webhook", "scheduled"] = "text"
    input_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in {"\n", "\t"} for character in value):
            raise ValueError("message contains control characters")
        return value


class IntentArtifact(StrictModel):
    schema_version: Literal["dronedream.intent.v1"] = "dronedream.intent.v1"
    goal: str = Field(min_length=3, max_length=1_000)
    start_entity: str = Field(min_length=1, max_length=160)
    target_entity: str = Field(min_length=1, max_length=160)
    return_entity: str = Field(min_length=1, max_length=160)
    payload_action: DomainActionId
    constraints: list[str] = Field(default_factory=list, max_length=32)
    missing_critical_fields: list[str] = Field(default_factory=list, max_length=16)
    assumptions: list[str] = Field(default_factory=list, max_length=16)


class IntentCritique(StrictModel):
    schema_version: Literal["dronedream.intent-critique.v1"] = "dronedream.intent-critique.v1"
    accepted: bool
    issue_codes: list[str] = Field(default_factory=list, max_length=16)
    repair_instructions: list[str] = Field(default_factory=list, max_length=16)


class ActionDefinition(StrictModel):
    schema_version: Literal["dronedream.action-definition.v1"] = "dronedream.action-definition.v1"
    action_id: DomainActionId
    domain_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    movement: bool = False
    payload: bool = False
    flight_boundary: Literal["none", "takeoff", "landing"] = "none"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    required_success_evidence: list[str] = Field(min_length=1, max_length=24)
    allowed_fallbacks: list[SafetyAction] = Field(min_length=1, max_length=6)
    simulator_executor: str = Field(min_length=3, max_length=160)
    runtime_executor: str | None = Field(default=None, max_length=160)
    authority: Literal["plan", "simulate", "control", "actuate"] = "plan"


class DomainActionCatalog(StrictModel):
    schema_version: Literal["dronedream.domain-action-catalog.v1"] = (
        "dronedream.domain-action-catalog.v1"
    )
    catalog_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,119}$")
    domain_ids: list[str] = Field(min_length=1, max_length=32)
    actions: list[ActionDefinition] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_actions(self) -> DomainActionCatalog:
        identifiers = [item.action_id for item in self.actions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("domain action identifiers must be unique")
        if "takeoff" not in identifiers or "land" not in identifiers:
            raise ValueError("domain catalog must retain takeoff and land boundaries")
        return self


class MissionContract(StrictModel):
    schema_version: Literal["dronedream.mission-contract.v1"] = "dronedream.mission-contract.v1"
    contract_id: str = Field(pattern=r"^mission-[0-9a-f]{24}$")
    conversation_id: str
    goal: str
    start_node: str
    target_node: str
    return_node: str
    payload_action: DomainActionId
    domain_ids: list[str] = Field(default_factory=lambda: ["core.flight"], max_length=32)
    authorized_actions: list[DomainActionId] = Field(
        default_factory=lambda: [
            "takeoff",
            "traverse",
            "navigate",
            "pickup",
            "return",
            "land",
        ],
        min_length=2,
        max_length=256,
    )
    action_catalog_sha256: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")
    map_asset_id: str
    map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    map_semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vehicle_asset_id: str
    vehicle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    constraints: list[str] = Field(max_length=32)
    immutable_safety_rules: list[str] = Field(min_length=1, max_length=32)


class TaskNode(StrictModel):
    task_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=64)
    action: TaskAction
    target_node: str
    depends_on: list[str] = Field(default_factory=list, max_length=16)
    success_evidence: list[str] = Field(min_length=1, max_length=16)
    max_retries: int = Field(default=1, ge=0, le=8)
    fallback: SafetyAction


class TaskGraph(StrictModel):
    schema_version: Literal["dronedream.task-graph.v1"] = "dronedream.task-graph.v1"
    revision: int = Field(default=1, ge=1)
    nodes: list[TaskNode] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_dag(self) -> TaskGraph:
        identifiers = [node.task_id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("task identifiers must be unique")
        known = set(identifiers)
        remaining: dict[str, set[str]] = {}
        for node in self.nodes:
            if node.task_id in node.depends_on:
                raise ValueError("task cannot depend on itself")
            if any(dependency not in known for dependency in node.depends_on):
                raise ValueError("task dependency is unknown")
            remaining[node.task_id] = set(node.depends_on)
        while remaining:
            roots = [node_id for node_id, dependencies in remaining.items() if not dependencies]
            if not roots:
                raise ValueError("task graph must be acyclic")
            for node_id in roots:
                del remaining[node_id]
            for dependencies in remaining.values():
                dependencies.difference_update(roots)
        return self


class TaskGraphArtifact(StrictModel):
    schema_version: Literal["dronedream.task-graph-artifact.v1"] = (
        "dronedream.task-graph-artifact.v1"
    )
    graph: TaskGraph


class SemanticPlan(StrictModel):
    schema_version: Literal["dronedream.semantic-plan.v1"] = "dronedream.semantic-plan.v1"
    ordered_targets: list[str] = Field(min_length=1, max_length=64)
    rationale_summary: str = Field(min_length=1, max_length=600)


class PlannerContribution(StrictModel):
    schema_version: Literal["dronedream.planner-contribution.v1"] = (
        "dronedream.planner-contribution.v1"
    )
    planner_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    layer: Literal[
        "semantic",
        "temporal",
        "global",
        "local",
        "indoor",
        "outdoor",
        "dynamic-obstacle",
        "energy",
        "link",
        "payload",
        "regulatory",
    ]
    applicable: bool
    hard_constraints: list[str] = Field(default_factory=list, max_length=32)
    objective_metrics: list[str] = Field(default_factory=list, max_length=32)
    required_inputs: list[str] = Field(default_factory=list, max_length=32)
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)


class PlannerValidation(StrictModel):
    schema_version: Literal["dronedream.planner-validation.v1"] = "dronedream.planner-validation.v1"
    planner_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    accepted: bool
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)
    issue_codes: list[str] = Field(default_factory=list, max_length=32)


class RoutePoint(StrictModel):
    node_id: str
    position_m: Vector3


class PlanSegment(StrictModel):
    segment_id: str = Field(pattern=r"^segment-[0-9]{3}$")
    task_id: str
    from_node: str
    to_node: str
    path: list[RoutePoint] = Field(min_length=2, max_length=1_000)
    speed_limit_mps: float = Field(gt=0.0, le=20.0)
    minimum_clearance_m: float = Field(gt=0.0, le=100.0)
    success_evidence: list[str] = Field(min_length=1, max_length=16)


class FlightPlan(StrictModel):
    schema_version: Literal["dronedream.flight-plan.v1"] = "dronedream.flight-plan.v1"
    revision: int = Field(ge=1)
    contract_id: str
    segments: list[PlanSegment] = Field(min_length=1, max_length=256)
    semantic_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_continuity(self) -> FlightPlan:
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if previous.to_node != current.from_node:
                raise ValueError("flight plan segments are discontinuous")
        return self


class PlanCritique(StrictModel):
    schema_version: Literal["dronedream.plan-critique.v1"] = "dronedream.plan-critique.v1"
    accepted: bool
    issue_codes: list[str] = Field(default_factory=list, max_length=32)
    repair_instructions: list[str] = Field(default_factory=list, max_length=32)


class RouteQuery(StrictModel):
    schema_version: Literal["dronedream.route-query.v1"] = "dronedream.route-query.v1"
    start_node: str
    goal_node: str
    require_flight_verified_edges: bool = False


class GraphRoute(StrictModel):
    schema_version: Literal["dronedream.graph-route.v1"] = "dronedream.graph-route.v1"
    start_node: str
    goal_node: str
    node_ids: list[str] = Field(min_length=1, max_length=10_000)
    edge_ids: list[str] = Field(max_length=10_000)
    positions_m: list[Vector3] = Field(min_length=1, max_length=10_000)
    route_length_m: float = Field(ge=0.0)
    all_edges_flight_verified: bool


class RouteCollision(StrictModel):
    sample_index: int = Field(ge=0)
    position_m: Vector3
    primitive_name: str
    clearance_m: float


class RouteClearanceReport(StrictModel):
    schema_version: Literal["dronedream.route-clearance.v1"] = "dronedream.route-clearance.v1"
    accepted: bool
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_interval_m: float = Field(gt=0.0)
    sample_count: int = Field(ge=1)
    primitive_count: int = Field(ge=1)
    collision_count: int = Field(ge=0)
    minimum_clearance_m: float
    minimum_clearance_point: Vector3
    minimum_clearance_primitive: str
    collisions: list[RouteCollision] = Field(default_factory=list, max_length=100)


class RouteAlternativeCandidate(StrictModel):
    schema_version: Literal["dronedream.route-alternative-candidate.v1"] = (
        "dronedream.route-alternative-candidate.v1"
    )
    alternative_id: str
    strategy_tool_id: str
    route: GraphRoute
    clearance: RouteClearanceReport
    objectives: dict[str, float]
    hard_gates: dict[str, bool]
    feasible: bool
    issue_codes: list[str] = Field(default_factory=list, max_length=32)


class RouteAlternativeSet(StrictModel):
    schema_version: Literal["dronedream.route-alternative-set.v1"] = (
        "dronedream.route-alternative-set.v1"
    )
    contract_id: str
    candidates: list[RouteAlternativeCandidate] = Field(min_length=1, max_length=16)
    objective_weights: dict[str, float]


class RouteAlternativeDecision(StrictModel):
    schema_version: Literal["dronedream.route-alternative-decision.v1"] = (
        "dronedream.route-alternative-decision.v1"
    )
    selected_alternative_id: str
    ranked_alternative_ids: list[str] = Field(min_length=1, max_length=16)
    normalized_scores: dict[str, float]
    selection_reasons: list[str] = Field(min_length=1, max_length=16)
    rejected_alternatives: dict[str, list[str]] = Field(default_factory=dict)


class Px4TrackPoint(StrictModel):
    x: float
    y: float
    z: float
    phase: Literal["launch", "transit", "stairs", "pickup", "return", "land"]
    speed_limit_mps: float = Field(gt=0.0, le=20.0)


class WorldTrackPoint(StrictModel):
    east_m: float
    north_m: float
    up_m: float


class Px4CoordinateContract(StrictModel):
    source: Literal["Gazebo ENU vehicle-collision-envelope center"] = (
        "Gazebo ENU vehicle-collision-envelope center"
    )
    executor_x: Literal["PX4 local north physically mapped to Gazebo y / School Map north"] = (
        "PX4 local north physically mapped to Gazebo y / School Map north"
    )
    executor_y: Literal["PX4 local east physically mapped to Gazebo x / School Map east"] = (
        "PX4 local east physically mapped to Gazebo x / School Map east"
    )
    executor_z: Literal["PX4 local up"] = "PX4 local up"
    model_root_world_enu_m: list[float] = Field(min_length=3, max_length=3)
    collision_center_above_model_root_m: float = Field(gt=0.0, le=5.0)


class Px4Track(StrictModel):
    schema_version: Literal["dronedream.school-map-px4-track.v1"] = (
        "dronedream.school-map-px4-track.v1"
    )
    track_type: Literal["custom"] = "custom"
    coordinate_contract: Px4CoordinateContract
    points: list[Px4TrackPoint] = Field(min_length=2, max_length=10_000)
    source_world_points: list[WorldTrackPoint] = Field(min_length=2, max_length=10_000)
    stop_at_waypoints: bool = True
    waypoint_hold_seconds: float = Field(ge=0.0, le=30.0)

    @model_validator(mode="after")
    def aligned_points(self) -> Px4Track:
        if len(self.points) != len(self.source_world_points):
            raise ValueError("PX4 and world point arrays must be aligned")
        return self


class Px4TrackRequest(StrictModel):
    schema_version: Literal["dronedream.px4-track-request.v1"] = "dronedream.px4-track-request.v1"
    route: GraphRoute
    waypoint_hold_seconds: float = Field(default=0.4, ge=0.0, le=30.0)


class RuntimeTrackRequest(StrictModel):
    schema_version: Literal["dronedream.runtime-track-request.v1"] = (
        "dronedream.runtime-track-request.v1"
    )
    route: GraphRoute
    prior_track: Px4Track
    target_node: str
    vehicle: VehicleAsset


class RuntimeAssessment(StrictModel):
    schema_version: Literal["dronedream.runtime-assessment.v1"] = "dronedream.runtime-assessment.v1"
    action: Literal["accept", "retry", "replan", "hold", "abort"]
    issue_codes: list[str] = Field(default_factory=list, max_length=32)
    repair_hint: str | None = Field(default=None, max_length=400)


class RuntimeCheckpoint(StrictModel):
    checkpoint_id: str = Field(pattern=r"^checkpoint-[0-9]{3}$")
    segment_id: str = Field(pattern=r"^segment-[0-9]{3}$")
    task_id: str
    track_point_index: int = Field(ge=1)
    target_node: str


class RuntimeCheckpointContract(StrictModel):
    schema_version: Literal["dronedream.runtime-checkpoints.v1"] = (
        "dronedream.runtime-checkpoints.v1"
    )
    contract_id: str
    checkpoints: list[RuntimeCheckpoint] = Field(min_length=1, max_length=128)


class RuntimeCheckpointRequest(StrictModel):
    schema_version: Literal["dronedream.runtime-checkpoint-request.v1"] = (
        "dronedream.runtime-checkpoint-request.v1"
    )
    contract_id: str
    checkpoint: RuntimeCheckpoint
    observed_position_ned_m: Vector3
    observed_velocity_ned_mps: Vector3
    commanded_position_ned_m: Vector3
    position_error_m: float = Field(ge=0.0)
    speed_mps: float = Field(ge=0.0)
    battery_percent: float = Field(ge=0.0, le=100.0)
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)


class RuntimeCheckpointDecision(StrictModel):
    schema_version: Literal["dronedream.runtime-checkpoint-decision.v1"] = (
        "dronedream.runtime-checkpoint-decision.v1"
    )
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment: RuntimeAssessment
    model_call: ModelCallRecord
    continue_authorized: bool
    plugin_hook_receipts: list[PluginHookReceipt] = Field(default_factory=list)


class TaskThread(StrictModel):
    """Stable identity and lifecycle for one user-visible mission conversation."""

    schema_version: Literal["dronedream.task-thread.v1"] = "dronedream.task-thread.v1"
    conversation_id: str
    mission_id: str = Field(pattern=r"^mission-[0-9a-f]{32}$")
    state: Literal[
        "planning",
        "awaiting_confirmation",
        "executing",
        "holding",
        "landing",
        "completed",
        "failed",
    ]
    current_plan_revision_id: str | None = Field(default=None, pattern=r"^plan-[0-9a-f]{32}$")
    active_execution_id: str | None = Field(default=None, pattern=r"^execution-[0-9a-f]{32}$")
    created_at: datetime
    updated_at: datetime


class PlanRevisionRecord(StrictModel):
    """One replaceable plan inside a stable task thread."""

    schema_version: Literal["dronedream.plan-revision.v1"] = "dronedream.plan-revision.v1"
    plan_revision_id: str = Field(pattern=r"^plan-[0-9a-f]{32}$")
    conversation_id: str
    mission_id: str = Field(pattern=r"^mission-[0-9a-f]{32}$")
    revision: int = Field(ge=1)
    parent_plan_revision_id: str | None = Field(default=None, pattern=r"^plan-[0-9a-f]{32}$")
    status: Literal["proposed", "superseded", "confirmed", "executing", "completed", "failed"]
    contract_id: str
    prepared_mission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class MissionLifecycleBinding(StrictModel):
    """Sidecar that avoids changing an already hash-bound PreparedMission schema."""

    schema_version: Literal["dronedream.mission-lifecycle-binding.v1"] = (
        "dronedream.mission-lifecycle-binding.v1"
    )
    thread: TaskThread
    plan_revision: PlanRevisionRecord


class RuntimeControlSession(StrictModel):
    schema_version: Literal["dronedream.runtime-control-session.v1"] = (
        "dronedream.runtime-control-session.v1"
    )
    conversation_id: str
    mission_id: str = Field(pattern=r"^mission-[0-9a-f]{32}$")
    plan_revision_id: str = Field(pattern=r"^plan-[0-9a-f]{32}$")
    contract_id: str
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    prepared_mission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["accepting", "closed"] = "accepting"
    created_at: datetime


class RuntimeUserMessage(StrictModel):
    schema_version: Literal["dronedream.runtime-user-message.v1"] = (
        "dronedream.runtime-user-message.v1"
    )
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    conversation_id: str
    mission_id: str = Field(pattern=r"^mission-[0-9a-f]{32}$")
    plan_revision_id: str = Field(pattern=r"^plan-[0-9a-f]{32}$")
    contract_id: str
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    text: str = Field(min_length=1, max_length=4_000)
    submitted_at: datetime

    @field_validator("text")
    @classmethod
    def reject_message_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in {"\n", "\t"} for character in value):
            raise ValueError("runtime message contains control characters")
        return value


class RuntimeHoldAcknowledgement(StrictModel):
    schema_version: Literal["dronedream.runtime-hold-ack.v1"] = "dronedream.runtime-hold-ack.v1"
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    interrupted_phase: Literal["TAKEOFF", "TRACK", "CHECKPOINT"]
    schedule_index: int | None = Field(default=None, ge=0)
    detected_at: datetime
    detection_latency_ms: int = Field(ge=0)
    stable_at: datetime
    stabilization_latency_ms: int = Field(ge=0)
    frozen_command_ned_m: Vector3
    hold_command_ned_m: Vector3
    observed_position_ned_m: Vector3
    observed_velocity_ned_mps: Vector3
    position_error_m: float = Field(ge=0.0)
    speed_mps: float = Field(ge=0.0)
    side_effects_inhibited: Literal[True] = True
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)


class RuntimeMessageClassification(StrictModel):
    schema_version: Literal["dronedream.runtime-message-classification.v1"] = (
        "dronedream.runtime-message-classification.v1"
    )
    message_kind: Literal[
        "emergency_stop",
        "mission_amendment",
        "motion_adjustment",
        "informational",
    ]
    requested_action: Literal[
        "land",
        "replan",
        "adjust_motion",
        "resume",
        "redirect",
        "set_speed",
        "pause",
        "return_home",
        "safe_land",
        "set_return_point",
        "set_coverage",
        "camera_control",
        "payload_control",
        "set_avoidance",
        "follow_target",
        "operator_takeover",
    ]
    target_entity: str | None = Field(default=None, max_length=160)
    requires_plan_revision: bool
    summary: str = Field(min_length=1, max_length=400)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RuntimeAmendmentDirective(StrictModel):
    schema_version: Literal["dronedream.runtime-amendment-directive.v1"] = (
        "dronedream.runtime-amendment-directive.v1"
    )
    action: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_stable_hold: bool = True
    requires_plan_revision: bool = True
    requires_core_authorization: bool = True
    issue_codes: list[str] = Field(default_factory=list, max_length=32)


class RuntimeInterruptionDecision(StrictModel):
    schema_version: Literal["dronedream.runtime-interruption-decision.v1"] = (
        "dronedream.runtime-interruption-decision.v1"
    )
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hold_ack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: RuntimeMessageClassification
    model_call: ModelCallRecord
    authorized_action: Literal[
        "resume_original", "hold", "hold_for_replan", "apply_command", "land"
    ]
    authorization_gates: dict[str, bool] = Field(min_length=1, max_length=32)
    decision_reason: str = Field(min_length=1, max_length=400)
    plugin_hook_receipts: list[PluginHookReceipt] = Field(default_factory=list)
    amendment_directive: RuntimeAmendmentDirective | None = None


class RuntimeToolReceipt(StrictModel):
    tool_id: str
    plugin_id: str | None = None
    plugin_package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["accepted", "rejected", "failed"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CoveragePlanRequest(StrictModel):
    schema_version: Literal["dronedream.coverage-plan-request.v1"] = (
        "dronedream.coverage-plan-request.v1"
    )
    center_enu_m: Vector3
    polygon_enu_m: list[Vector3] = Field(default_factory=list, max_length=128)
    width_m: float = Field(default=6.0, ge=1.0, le=5000.0)
    height_m: float = Field(default=6.0, ge=1.0, le=5000.0)
    lane_spacing_m: float = Field(ge=0.2, le=100.0)
    boundary_margin_m: float = Field(default=0.5, ge=0.0, le=50.0)
    altitude_m: float = Field(ge=0.2, le=500.0)

    @model_validator(mode="after")
    def validate_polygon(self) -> CoveragePlanRequest:
        if self.polygon_enu_m and len(self.polygon_enu_m) < 3:
            raise ValueError("coverage polygon requires at least three vertices")
        return self


class CoveragePattern(StrictModel):
    schema_version: Literal["dronedream.coverage-pattern.v1"] = "dronedream.coverage-pattern.v1"
    pattern: Literal["lawnmower", "inward-spiral"]
    points_enu_m: list[Vector3] = Field(min_length=2, max_length=10_000)
    lane_count: int = Field(ge=1, le=10_000)
    estimated_area_m2: float = Field(gt=0.0)
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)


class RuntimeAuthorizedCommand(StrictModel):
    """A hash-bound peripheral or flight-policy command issued only from stable hold."""

    schema_version: Literal["dronedream.runtime-authorized-command.v1"] = (
        "dronedream.runtime-authorized-command.v1"
    )
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    action: Literal["camera_control", "payload_control", "set_avoidance"]
    parameters: dict[str, Any]
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hold_ack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)
    plugin_hook_receipts: list[PluginHookReceipt] = Field(default_factory=list)
    generated_at: datetime


class RuntimeCommandAdoption(StrictModel):
    schema_version: Literal["dronedream.runtime-command-adoption.v1"] = (
        "dronedream.runtime-command-adoption.v1"
    )
    artifact_kind: Literal["runtime-command"] = "runtime-command"
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    action: Literal["camera_control", "payload_control", "set_avoidance"]
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    success: Literal[True] = True
    observed_result: dict[str, Any]
    adopted_at: datetime


class RuntimeOperatorTakeoverGrant(StrictModel):
    """One-time, hash-bound authority for bounded manual velocity commands."""

    schema_version: Literal["dronedream.runtime-operator-takeover-grant.v1"] = (
        "dronedream.runtime-operator-takeover-grant.v1"
    )
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    operator_id: str = Field(min_length=1, max_length=160)
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hold_ack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    grant_token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    maximum_horizontal_speed_mps: float = Field(gt=0.0, le=3.0)
    maximum_vertical_speed_mps: float = Field(gt=0.0, le=2.0)
    maximum_yaw_rate_dps: float = Field(gt=0.0, le=180.0)
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def expiry_after_issue(self) -> RuntimeOperatorTakeoverGrant:
        if self.expires_at <= self.issued_at:
            raise ValueError("operator takeover grant must expire after it is issued")
        return self


class RuntimeOperatorControlCommand(StrictModel):
    """Short-lived manual command written only after the app authenticates a grant token."""

    schema_version: Literal["dronedream.runtime-operator-control-command.v1"] = (
        "dronedream.runtime-operator-control-command.v1"
    )
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    grant_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sequence: int = Field(ge=1)
    action: Literal["velocity", "release"]
    velocity_ned_mps: Vector3 = Field(default_factory=lambda: Vector3(x=0.0, y=0.0, z=0.0))
    yaw_rate_dps: float = Field(ge=-180.0, le=180.0)
    duration_seconds: float = Field(gt=0.0, le=0.5)
    issued_at: datetime


class RuntimeOperatorTakeoverAdoption(StrictModel):
    schema_version: Literal["dronedream.runtime-operator-takeover-adoption.v1"] = (
        "dronedream.runtime-operator-takeover-adoption.v1"
    )
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    grant_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    success: Literal[True] = True
    adopted_at: datetime


class RuntimeReplacementTrack(StrictModel):
    """A code-validated track that may supersede the active track during stable hold."""

    schema_version: Literal["dronedream.runtime-replacement-track.v1"] = (
        "dronedream.runtime-replacement-track.v1"
    )
    message_id: str = Field(pattern=r"^runtime-msg-[0-9a-f]{32}$")
    execution_id: str = Field(pattern=r"^execution-[0-9a-f]{32}$")
    replacement_sequence: int = Field(ge=1)
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hold_ack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prior_track_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    amendment_action: Literal[
        "replan",
        "redirect",
        "set_speed",
        "return_home",
        "set_return_point",
        "set_coverage",
        "follow_target",
    ] = "replan"
    amendment_parameters: dict[str, Any] = Field(default_factory=dict)
    target_node: str
    return_node: str
    route: GraphRoute
    clearance: RouteClearanceReport
    track: Px4Track
    plugin_tool_receipts: list[RuntimeToolReceipt] = Field(default_factory=list)
    plugin_hook_receipts: list[PluginHookReceipt] = Field(default_factory=list)
    deterministic_gates: dict[str, bool] = Field(min_length=1, max_length=32)
    generated_at: datetime


class CompletionAssessment(StrictModel):
    schema_version: Literal["dronedream.completion-assessment.v1"] = (
        "dronedream.completion-assessment.v1"
    )
    accepted: bool
    issue_codes: list[str] = Field(default_factory=list, max_length=32)


class ConversationEvent(StrictModel):
    schema_version: Literal["dronedream.conversation-event.v1"] = "dronedream.conversation-event.v1"
    event_id: str = Field(pattern=r"^event-[0-9a-f]{24}$")
    conversation_id: str
    sequence: int = Field(ge=1)
    role: Literal["user", "assistant", "tool", "system"]
    event_type: str = Field(min_length=1, max_length=96)
    payload: dict[str, Any]
    created_at: datetime


class ConversationWindow(StrictModel):
    schema_version: Literal["dronedream.conversation-window.v1"] = (
        "dronedream.conversation-window.v1"
    )
    conversation_id: str
    summary: str | None = None
    recent_events: list[ConversationEvent]
    previous_response_ids: dict[str, str] = Field(default_factory=dict)


class PluginInvocation(StrictModel):
    tool_id: str = Field(pattern=r"^[a-z][a-z0-9._-]*$")
    arguments_json: str = Field(min_length=2, max_length=65_536)
    purpose: str = Field(min_length=1, max_length=300)

    def parsed_arguments(self) -> dict[str, Any]:
        value = json.loads(self.arguments_json)
        if not isinstance(value, dict):
            raise ValueError("plugin invocation arguments_json must encode an object")
        return value


class PluginInvocationPlan(StrictModel):
    schema_version: Literal["dronedream.plugin-invocation-plan.v1"] = (
        "dronedream.plugin-invocation-plan.v1"
    )
    calls: list[PluginInvocation] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def unique_tools(self) -> PluginInvocationPlan:
        tool_ids = [call.tool_id for call in self.calls]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("a plugin tool may be invoked only once per routing stage")
        return self


class ToolReceipt(StrictModel):
    schema_version: Literal["dronedream.tool-receipt.v1"] = "dronedream.tool-receipt.v1"
    call_id: str = Field(pattern=r"^tool-[0-9a-f]{24}$")
    tool_id: str = Field(pattern=r"^[a-z][a-z0-9._-]*$")
    tool_version: str
    plugin_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9._-]*$")
    plugin_package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["accepted", "rejected", "failed"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output: dict[str, Any]
    issue_codes: list[str] = Field(default_factory=list, max_length=32)


class ModelCallRecord(StrictModel):
    schema_version: Literal["dronedream.model-call.v1"] = "dronedream.model-call.v1"
    call_id: str = Field(pattern=r"^model-[0-9a-f]{24}$")
    role: ModelRole
    attempt: int = Field(ge=1, le=100)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema: str
    provider: str
    model: str
    response_id: str | None = None
    previous_response_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    created_at: datetime


class EvidenceRecord(StrictModel):
    schema_version: Literal["dronedream.evidence-record.v1"] = "dronedream.evidence-record.v1"
    sequence: int = Field(ge=1)
    created_at: datetime
    event_type: str = Field(min_length=1, max_length=96)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any]


class PreparedMission(StrictModel):
    schema_version: Literal["dronedream.prepared-mission.v1", "dronedream.prepared-mission.v2"] = (
        "dronedream.prepared-mission.v2"
    )
    status: Literal["awaiting_confirmation"] = "awaiting_confirmation"
    intent: IntentArtifact
    intent_critique: IntentCritique
    contract: MissionContract
    domain_actions: DomainActionCatalog
    simulation_capabilities: dict[str, Any] = Field(default_factory=dict)
    task_graph: TaskGraph
    semantic_plan: SemanticPlan
    plan: FlightPlan
    plan_critique: PlanCritique
    execution_route: GraphRoute
    route_clearance: RouteClearanceReport
    px4_track: Px4Track
    runtime_checkpoints: RuntimeCheckpointContract | None = None
    planning_attempts: int = Field(ge=1)
    model_calls: list[ModelCallRecord]
    plugin_snapshot: PluginSnapshot
    harness_topology: HarnessTopology
    harness_stage_receipts: list[HarnessStageReceipt]
    plugin_hook_receipts: list[PluginHookReceipt] = Field(default_factory=list)
    tool_receipts: list[ToolReceipt]
    evidence: list[EvidenceRecord]


class Px4UlogArtifact(StrictModel):
    path: str
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Px4GazeboArtifactBindings(StrictModel):
    world_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    vehicle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    track_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    clearance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    controller_params_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    executor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    px4_ulogs: list[Px4UlogArtifact] = Field(min_length=1)
    ros_workspace: str


class Px4GazeboGates(StrictModel):
    executor_completed: bool
    offboard_timing_complete: bool
    runtime_pose_samples_present: bool
    ros_observations_present: bool
    goal_observed: bool
    landing_confirmed: bool
    native_terminal_lifecycle_published: bool
    no_live_abort: bool
    px4_ulog_present: bool
    static_route_clearance_bound: bool


class Px4GazeboMeasurements(StrictModel):
    pose_sample_count: int = Field(ge=0)
    ros_observation_rows: int = Field(ge=0)
    minimum_goal_distance_m: float | None = Field(default=None, ge=0.0)
    landing_state: str | None = None
    abort_reason: str | None = None
    executor_return_code: int | None = None
    tolerated_landing_contact_samples: int = Field(default=0, ge=0)
    minimum_tolerated_landing_clearance_m: float | None = None


class Px4GazeboRunEvidence(StrictModel):
    schema_version: Literal["dronedream.generic-px4-gazebo-run.v1"]
    status: Literal["verified", "failed"]
    world: str
    vehicle: str
    gates: Px4GazeboGates
    measurements: Px4GazeboMeasurements
    artifacts: Px4GazeboArtifactBindings


class SimulationWorkflowResult(StrictModel):
    schema_version: Literal["dronedream.simulation-workflow-result.v1"] = (
        "dronedream.simulation-workflow-result.v1"
    )
    status: Literal["verified", "failed"]
    contract_id: str
    prepared_mission_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_evidence: Px4GazeboRunEvidence
    completion_assessment: CompletionAssessment
    completion_model_call: ModelCallRecord
    checkpoint_decisions: list[RuntimeCheckpointDecision] = Field(default_factory=list)
    runtime_interruption_decisions: list[RuntimeInterruptionDecision] = Field(default_factory=list)
    plugin_hook_receipts: list[PluginHookReceipt] = Field(default_factory=list)
    workflow_evidence_chain_head: str = Field(pattern=r"^[0-9a-f]{64}$")
