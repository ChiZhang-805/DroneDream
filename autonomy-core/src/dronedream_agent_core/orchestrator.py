"""Multi-call mission preparation bound to real model APIs and qualified geometry."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .context import ContextStore
from .contracts import (
    ConversationWindow,
    DomainActionCatalog,
    FlightPlan,
    GraphRoute,
    IntentArtifact,
    IntentCritique,
    MapAsset,
    MapCatalog,
    MissionContract,
    MissionRequest,
    ModelCallRecord,
    PlanCritique,
    PlannerContribution,
    PlannerValidation,
    PlanSegment,
    PluginInvocationPlan,
    PreparedMission,
    Px4Track,
    Px4TrackRequest,
    RouteAlternativeCandidate,
    RouteAlternativeDecision,
    RouteAlternativeSet,
    RouteClearanceReport,
    RoutePoint,
    RouteQuery,
    RuntimeCheckpoint,
    RuntimeCheckpointContract,
    SemanticPlan,
    TaskGraph,
    TaskGraphArtifact,
    ToolReceipt,
    VehicleAsset,
)
from .domain_actions import action_by_id, action_ids, merge_action_packs, movement_action_ids
from .evidence import EvidenceChain
from .extensions import ExtensionExecutionError, ExtensionRegistry
from .harness_graph import (
    HarnessGraphError,
    HarnessStageRuntime,
    HarnessTopology,
    resolve_harness_runtime_policy,
)
from .hashing import sha256_json
from .lifecycle import LifecycleTransitionError
from .model_port import (
    ModelInvocationError,
    ProviderName,
    StructuredCallResult,
    StructuredModelPort,
)
from .plugin_api import (
    ToolEnvironment,
    build_discovered_extension_registry,
    build_discovered_tool_registry,
)
from .plugin_contracts import PluginHookReceipt, PluginSnapshot
from .prompts import (
    GLOBAL_PLANNER,
    INTENT_CRITIC,
    INTENT_PARSER,
    PLAN_CRITIC,
    PLUGIN_ROUTER,
    TASK_DECOMPOSER,
)
from .tools import ToolExecutionError, ToolRegistry

MOVEMENT_ACTIONS = frozenset({"traverse", "navigate", "return"})
CORE_PLANNING_SLOTS = frozenset(
    {
        "planning.route-strategy",
        "planning.route-candidates",
        "planning.alternative-ranker",
        "safety.route-clearance",
        "flight-control.track-export",
        "runtime.track-export",
    }
)
IMMUTABLE_SAFETY_RULES = [
    "Model output never has direct actuator authority.",
    "Unknown or unavailable critical telemetry causes hold or abort.",
    "Every executable route must pass continuous vehicle-envelope collision checks.",
    "Execution must remain inside the qualified map and vehicle asset hashes.",
    "Landing or abort remains available at every runtime phase.",
]
EXPLICIT_CONSTRAINT_PHRASES = {
    "safety_priority": ("安全优先", "safety first", "prioritize safety"),
    "plan_only": ("先给我看计划", "plan only", "show me the plan"),
    "do_not_execute": ("不要立刻执行", "计划先不要执行", "do not execute"),
}


def _recommended_plugin_tools(
    catalog: list[dict[str, object]], contract: MissionContract
) -> list[str]:
    recommended: list[str] = []
    constraints = set(contract.constraints)
    for item in catalog:
        metadata = item.get("routing_metadata")
        if not isinstance(metadata, dict):
            continue
        condition = metadata.get("recommended_when")
        if not isinstance(condition, dict) or not condition:
            continue
        if set(condition) - {"payload_action_in", "constraints_any"}:
            continue
        matches = True
        payload_actions = condition.get("payload_action_in")
        if payload_actions is not None:
            matches = (
                isinstance(payload_actions, list) and contract.payload_action in payload_actions
            )
        constraint_values = condition.get("constraints_any")
        if matches and constraint_values is not None:
            matches = isinstance(constraint_values, list) and bool(
                constraints.intersection(str(value) for value in constraint_values)
            )
        if matches:
            recommended.append(str(item["tool_id"]))
    return sorted(recommended)


class MissionPreparationBlocked(RuntimeError):
    """A bounded planning stage could not produce a safe executable package."""


@dataclass(frozen=True)
class PreparationConfig:
    provider: ProviderName
    critic_provider: ProviderName
    max_provider_attempts: int = 3
    max_intent_rounds: int = 3
    max_planning_rounds: int = 5
    plugin_router_rounds: int = 2
    maximum_plugin_calls: int = 8
    intent_reviews_per_round: int = 1
    plan_reviews_per_round: int = 1
    maximum_model_calls: int = 48
    maximum_optional_tool_calls: int = 16
    model_timeout_seconds: float = 180.0
    vehicle_diameter_m: float = 0.76
    vehicle_height_m: float = 0.43
    waypoint_hold_seconds: float = 0.4
    persisted_task_context: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.max_intent_rounds <= 5:
            raise ValueError("max_intent_rounds must be between 1 and 5")
        if not 1 <= self.max_planning_rounds <= 5:
            raise ValueError("max_planning_rounds must be between 1 and 5")
        if not 1 <= self.plugin_router_rounds <= 5:
            raise ValueError("plugin_router_rounds must be between 1 and 5")
        if not 0 <= self.maximum_plugin_calls <= 16:
            raise ValueError("maximum_plugin_calls must be between 0 and 16")
        if not 1 <= self.intent_reviews_per_round <= 3:
            raise ValueError("intent_reviews_per_round must be between 1 and 3")
        if not 1 <= self.plan_reviews_per_round <= 3:
            raise ValueError("plan_reviews_per_round must be between 1 and 3")
        if not 8 <= self.maximum_model_calls <= 256:
            raise ValueError("maximum_model_calls must be between 8 and 256")
        if not 0 <= self.maximum_optional_tool_calls <= 64:
            raise ValueError("maximum_optional_tool_calls must be between 0 and 64")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artifact(path: Path, artifact: Any) -> None:
    if hasattr(artifact, "model_dump_json"):
        rendered = artifact.model_dump_json(indent=2)
    else:
        rendered = json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(rendered + "\n", encoding="utf-8")


def _compact_context(window: Any) -> dict[str, object]:
    """Keep durable history while excluding bulky tool payloads from model prompts."""

    recent: list[dict[str, object]] = []
    for event in window.recent_events:
        payload = event.payload
        if event.role == "tool":
            payload = {
                key: payload.get(key)
                for key in (
                    "tool_id",
                    "tool_version",
                    "outcome",
                    "input_sha256",
                    "output_sha256",
                    "issue_codes",
                )
            }
        elif event.event_type.startswith("model."):
            record = payload.get("record", {})
            payload = {
                "artifact": payload.get("artifact"),
                "record": {
                    key: record.get(key)
                    for key in (
                        "role",
                        "provider",
                        "model",
                        "input_sha256",
                        "output_sha256",
                    )
                }
                if isinstance(record, dict)
                else {},
            }
        recent.append(
            {
                "sequence": event.sequence,
                "role": event.role,
                "event_type": event.event_type,
                "payload": payload,
            }
        )
    return {
        "conversation_id": window.conversation_id,
        "summary": window.summary,
        "recent_events": recent,
    }


def _explicit_constraint_hints(request: MissionRequest) -> list[str]:
    normalized = request.message.casefold()
    return [
        canonical
        for canonical, phrases in EXPLICIT_CONSTRAINT_PHRASES.items()
        if any(phrase.casefold() in normalized for phrase in phrases)
    ]


def _missing_explicit_constraints(
    intent: IntentArtifact, explicit_constraint_hints: list[str]
) -> list[str]:
    present = {constraint.casefold() for constraint in intent.constraints}
    return [hint for hint in explicit_constraint_hints if hint.casefold() not in present]


def _resolve_entity(entity: str, catalog: MapCatalog, graph: MapAsset) -> str:
    if entity in {node.node_id for node in graph.nodes}:
        return entity
    direct = graph.named_entities.get(entity)
    if direct:
        return direct
    normalized = entity.casefold().strip()
    catalog_entity_id: str | None = None
    for item in catalog.entities:
        candidates = {item.entity_id.casefold(), *(alias.casefold() for alias in item.aliases)}
        if normalized in candidates:
            catalog_entity_id = item.entity_id
            break
    if catalog_entity_id and catalog_entity_id in graph.named_entities:
        return graph.named_entities[catalog_entity_id]
    raise MissionPreparationBlocked(f"UNRESOLVED_MAP_ENTITY: {entity}")


def _validate_task_graph(
    graph: TaskGraph,
    contract: MissionContract,
    map_graph: MapAsset,
    domain_actions: DomainActionCatalog | None = None,
) -> None:
    known_nodes = {node.node_id for node in map_graph.nodes}
    if any(task.target_node not in known_nodes for task in graph.nodes):
        raise MissionPreparationBlocked("TASK_GRAPH_UNKNOWN_NODE")
    authorized_actions = (
        action_ids(domain_actions)
        if domain_actions is not None
        else set(contract.authorized_actions)
    )
    unknown_actions = sorted({task.action for task in graph.nodes} - authorized_actions)
    if unknown_actions:
        raise MissionPreparationBlocked(
            "TASK_GRAPH_UNAUTHORIZED_ACTION:" + ",".join(unknown_actions)
        )
    movement_actions = (
        movement_action_ids(domain_actions) if domain_actions is not None else set(MOVEMENT_ACTIONS)
    )
    contract_movement_targets = {contract.target_node, contract.return_node}
    if any(
        task.action in movement_actions and task.target_node not in contract_movement_targets
        for task in graph.nodes
    ):
        raise MissionPreparationBlocked("TASK_GRAPH_UNAUTHORIZED_MOVEMENT_TARGET")
    if domain_actions is not None:
        for task in graph.nodes:
            definition = action_by_id(domain_actions, task.action)
            if task.fallback not in definition.allowed_fallbacks:
                raise MissionPreparationBlocked(
                    f"TASK_GRAPH_ACTION_FALLBACK_UNAUTHORIZED:{task.action}:{task.fallback}"
                )
            required = set(definition.required_success_evidence)
            provided = {item.casefold() for item in task.success_evidence}
            if not all(
                any(token.casefold() in evidence for evidence in provided) for token in required
            ):
                raise MissionPreparationBlocked(f"TASK_GRAPH_ACTION_EVIDENCE_MISSING:{task.action}")
    actions = [task.action for task in graph.nodes]
    if "takeoff" not in actions or "land" not in actions:
        raise MissionPreparationBlocked("TASK_GRAPH_MISSING_FLIGHT_BOUNDARY")
    if not any(
        task.action == "takeoff" and task.target_node == contract.start_node for task in graph.nodes
    ):
        raise MissionPreparationBlocked("TASK_GRAPH_WRONG_TAKEOFF_NODE")
    if not any(
        task.action in MOVEMENT_ACTIONS and task.target_node == contract.target_node
        for task in graph.nodes
    ):
        raise MissionPreparationBlocked("TASK_GRAPH_MISSING_TARGET_MOVEMENT")
    if contract.payload_action == "pickup" and not any(
        task.action == "pickup" and task.target_node == contract.target_node for task in graph.nodes
    ):
        raise MissionPreparationBlocked("TASK_GRAPH_MISSING_PICKUP")
    if not any(
        task.action == "land" and task.target_node == contract.return_node for task in graph.nodes
    ):
        raise MissionPreparationBlocked("TASK_GRAPH_WRONG_LANDING_NODE")


def _validate_semantic_plan(plan: SemanticPlan, contract: MissionContract, graph: MapAsset) -> None:
    known = {node.node_id for node in graph.nodes}
    if any(target not in known for target in plan.ordered_targets):
        raise MissionPreparationBlocked("SEMANTIC_PLAN_UNKNOWN_NODE")
    if any(
        target not in {contract.target_node, contract.return_node}
        for target in plan.ordered_targets
    ):
        raise MissionPreparationBlocked("SEMANTIC_PLAN_UNAUTHORIZED_TARGET")
    if plan.ordered_targets[0] == contract.start_node:
        raise MissionPreparationBlocked("SEMANTIC_PLAN_REPEATS_START")
    if contract.target_node not in plan.ordered_targets:
        raise MissionPreparationBlocked("SEMANTIC_PLAN_MISSING_TARGET")
    if plan.ordered_targets[-1] != contract.return_node:
        raise MissionPreparationBlocked("SEMANTIC_PLAN_WRONG_FINAL_NODE")
    if any(
        first == second
        for first, second in zip(plan.ordered_targets, plan.ordered_targets[1:], strict=False)
    ):
        raise MissionPreparationBlocked("SEMANTIC_PLAN_CONSECUTIVE_DUPLICATE")


def _combine_routes(routes: list[GraphRoute]) -> GraphRoute:
    if not routes:
        raise MissionPreparationBlocked("NO_MOVEMENT_ROUTE")
    node_ids = list(routes[0].node_ids)
    edge_ids = list(routes[0].edge_ids)
    positions = list(routes[0].positions_m)
    for previous, route in zip(routes, routes[1:], strict=False):
        if previous.goal_node != route.start_node:
            raise MissionPreparationBlocked("ROUTE_TOOL_DISCONTINUITY")
        node_ids.extend(route.node_ids[1:])
        edge_ids.extend(route.edge_ids)
        positions.extend(route.positions_m[1:])
    return GraphRoute(
        start_node=routes[0].start_node,
        goal_node=routes[-1].goal_node,
        node_ids=node_ids,
        edge_ids=edge_ids,
        positions_m=positions,
        route_length_m=sum(route.route_length_m for route in routes),
        all_edges_flight_verified=all(route.all_edges_flight_verified for route in routes),
    )


def _route_objectives(route: GraphRoute, clearance: RouteClearanceReport) -> dict[str, float]:
    climb_m = sum(
        max(0.0, second.z - first.z)
        for first, second in zip(route.positions_m, route.positions_m[1:], strict=False)
    )
    return {
        "distance_m": route.route_length_m,
        "minimum_clearance_m": clearance.minimum_clearance_m,
        "energy_proxy": route.route_length_m + climb_m * 2.5 + len(route.edge_ids) * 0.05,
        "transition_count": float(len(route.edge_ids)),
        "qualification_penalty": 0.0 if route.all_edges_flight_verified else 1.0,
    }


def _validate_plugin_track_tightening(
    track: Px4Track, route: GraphRoute, vehicle: VehicleAsset
) -> None:
    """Plugins may lower speed or add holds; they may not alter cleared geometry."""

    if len(track.source_world_points) != len(route.positions_m):
        raise MissionPreparationBlocked("PLUGIN_TRACK_GEOMETRY_CHANGED")
    root_east, root_north, root_up = track.coordinate_contract.model_root_world_enu_m
    center_offset = track.coordinate_contract.collision_center_above_model_root_m
    for source, point, expected in zip(
        track.source_world_points, track.points, route.positions_m, strict=True
    ):
        gates = (
            math.dist(
                (source.east_m, source.north_m, source.up_m),
                (expected.x, expected.y, expected.z),
            )
            <= 1e-6,
            math.dist(
                (
                    point.y + root_east,
                    point.x + root_north,
                    point.z + root_up + center_offset,
                ),
                (expected.x, expected.y, expected.z),
            )
            <= 1e-6,
            point.speed_limit_mps <= vehicle.max_speed_mps,
        )
        if not all(gates):
            raise MissionPreparationBlocked("PLUGIN_TRACK_SAFETY_ENVELOPE_RELAXED")
    if not track.stop_at_waypoints:
        raise MissionPreparationBlocked("PLUGIN_TRACK_STOP_POLICY_RELAXED")


def _flight_plan(
    contract: MissionContract,
    task_graph: TaskGraph,
    semantic_plan: SemanticPlan,
    routes: list[GraphRoute],
    map_graph: MapAsset,
    validated_clearance_m: float,
) -> FlightPlan:
    edges = {edge.edge_id: edge for edge in map_graph.edges}
    movement_tasks = [task for task in task_graph.nodes if task.action in MOVEMENT_ACTIONS]
    used_task_ids: set[str] = set()
    segments: list[PlanSegment] = []
    for index, (target, route) in enumerate(
        zip(semantic_plan.ordered_targets, routes, strict=True), start=1
    ):
        task = next(
            (
                item
                for item in movement_tasks
                if item.target_node == target and item.task_id not in used_task_ids
            ),
            None,
        )
        if task is None:
            raise MissionPreparationBlocked(f"NO_MOVEMENT_TASK_FOR_TARGET: {target}")
        used_task_ids.add(task.task_id)
        route_edges = [edges[edge_id] for edge_id in route.edge_ids]
        segments.append(
            PlanSegment(
                segment_id=f"segment-{index:03d}",
                task_id=task.task_id,
                from_node=route.start_node,
                to_node=route.goal_node,
                path=[
                    RoutePoint(node_id=node_id, position_m=position)
                    for node_id, position in zip(route.node_ids, route.positions_m, strict=True)
                ],
                speed_limit_mps=min(edge.speed_limit_mps for edge in route_edges),
                # The conservative continuous collision tool is authoritative.
                # Graph-edge clearance metadata can be zero when not yet qualified.
                minimum_clearance_m=validated_clearance_m,
                success_evidence=task.success_evidence,
            )
        )
    return FlightPlan(
        revision=1,
        contract_id=contract.contract_id,
        segments=segments,
        semantic_plan_sha256=sha256_json(semantic_plan),
    )


def _runtime_checkpoints(
    contract: MissionContract, flight_plan: FlightPlan
) -> RuntimeCheckpointContract:
    checkpoints: list[RuntimeCheckpoint] = []
    track_point_index = 0
    for index, segment in enumerate(flight_plan.segments, start=1):
        track_point_index += len(segment.path) - 1
        checkpoints.append(
            RuntimeCheckpoint(
                checkpoint_id=f"checkpoint-{index:03d}",
                segment_id=segment.segment_id,
                task_id=segment.task_id,
                track_point_index=track_point_index,
                target_node=segment.to_node,
            )
        )
    return RuntimeCheckpointContract(contract_id=contract.contract_id, checkpoints=checkpoints)


class MissionOrchestrator:
    """Prepare, but never silently actuate, a hash-bound simulated mission."""

    def __init__(
        self,
        *,
        config: PreparationConfig,
        map_catalog: MapCatalog,
        map_graph: MapAsset,
        semantic_path: Path,
        vehicle_sdf: Path,
        vehicle_asset_id: str,
        vehicle: VehicleAsset,
        context_store: ContextStore,
        primary_port: StructuredModelPort | None = None,
        critic_port: StructuredModelPort | None = None,
        model_ports: dict[str, StructuredModelPort] | None = None,
        tool_registry: ToolRegistry | None = None,
        extension_registry: ExtensionRegistry | None = None,
        plugin_snapshot: PluginSnapshot | None = None,
        initial_hook_receipts: list[PluginHookReceipt] | None = None,
    ) -> None:
        self.config = config
        self.map_catalog = map_catalog
        self.map_graph = map_graph
        self.semantic_path = semantic_path
        self.vehicle_sdf = vehicle_sdf
        self.vehicle_asset_id = vehicle_asset_id
        if vehicle.asset_id != vehicle_asset_id:
            raise ValueError("vehicle metadata does not match vehicle_asset_id")
        self.vehicle = vehicle
        self.context_store = context_store
        self.primary = primary_port or StructuredModelPort(
            config.provider,
            max_attempts=config.max_provider_attempts,
            timeout_seconds=config.model_timeout_seconds,
        )
        self.critic = critic_port or StructuredModelPort(
            config.critic_provider,
            max_attempts=config.max_provider_attempts,
            timeout_seconds=config.model_timeout_seconds,
        )
        self.model_ports = {"primary": self.primary, "critic": self.critic}
        self.model_ports.update(model_ports or {})
        if (tool_registry is None) != (plugin_snapshot is None):
            raise ValueError("tool_registry and plugin_snapshot must be supplied together")
        if tool_registry is None or plugin_snapshot is None:
            tool_registry, plugin_snapshot = build_discovered_tool_registry(
                ToolEnvironment(
                    map_graph=map_graph,
                    semantic_path=semantic_path,
                    vehicle_diameter_m=config.vehicle_diameter_m,
                    vehicle_height_m=config.vehicle_height_m,
                    waypoint_hold_seconds=config.waypoint_hold_seconds,
                )
            )
        self.tool_registry = tool_registry
        self.plugin_snapshot = plugin_snapshot
        self.extension_registry = extension_registry or build_discovered_extension_registry(
            plugin_snapshot
        )
        self._hook_receipts: list[PluginHookReceipt] = []
        self._initial_hook_receipts = list(initial_hook_receipts or [])
        self._model_call_count = 0
        self._model_call_budget = config.maximum_model_calls
        self._model_media: list[dict[str, object]] = []

    def _record_hook_receipts(
        self, receipts: list[PluginHookReceipt], evidence: EvidenceChain
    ) -> None:
        for receipt in receipts:
            self._hook_receipts.append(receipt)
            evidence.append(
                f"plugin-hook.{receipt.slot_id}.{receipt.hook}",
                receipt.model_dump(mode="json"),
            )

    def _invoke_single_extension(
        self,
        slot_id: str,
        hook: str,
        *,
        evidence: EvidenceChain,
        required: bool = False,
        **kwargs: Any,
    ) -> Any | None:
        try:
            output, receipts = self.extension_registry.invoke_single(
                slot_id, hook, required=required, **kwargs
            )
        except ExtensionExecutionError as error:
            self._record_hook_receipts([error.receipt], evidence)
            raise MissionPreparationBlocked(str(error)) from error
        self._record_hook_receipts(receipts, evidence)
        return output

    def _invoke_multiple_extensions(
        self,
        slot_id: str,
        hook: str,
        *,
        evidence: EvidenceChain,
        **kwargs: Any,
    ) -> list[Any]:
        try:
            outputs, receipts = self.extension_registry.invoke_multiple(slot_id, hook, **kwargs)
        except ExtensionExecutionError as error:
            self._record_hook_receipts([error.receipt], evidence)
            raise MissionPreparationBlocked(str(error)) from error
        self._record_hook_receipts(receipts, evidence)
        return outputs

    def _invoke_extension_pipeline(
        self,
        slot_id: str,
        hook: str,
        value: Any,
        *,
        evidence: EvidenceChain,
        **kwargs: Any,
    ) -> Any:
        try:
            output, receipts = self.extension_registry.invoke_pipeline(
                slot_id, hook, value, **kwargs
            )
        except ExtensionExecutionError as error:
            self._record_hook_receipts([error.receipt], evidence)
            raise MissionPreparationBlocked(str(error)) from error
        self._record_hook_receipts(receipts, evidence)
        return output

    def _call(
        self,
        *,
        port: StructuredModelPort,
        role: str,
        output_type: Any,
        instructions: str,
        input_artifact: dict[str, object],
        conversation_id: str,
        evidence: EvidenceChain,
    ) -> StructuredCallResult[Any]:
        requested_port = "critic" if port is self.critic else "primary"
        role_policy = self._invoke_single_extension(
            "models.role-policy",
            "select_port",
            evidence=evidence,
            role=role,
            requested_port=requested_port,
        )
        if isinstance(role_policy, dict):
            selected = role_policy.get("port")
            if isinstance(selected, str) and selected in self.model_ports:
                requested_port = selected
                port = self.model_ports[selected]
        route_policy = self._invoke_single_extension(
            "models.runtime-router",
            "route_model",
            evidence=evidence,
            required=True,
            role=role,
            requested_port=requested_port,
            available_ports=sorted(self.model_ports),
        )
        if not isinstance(route_policy, dict):
            raise MissionPreparationBlocked("MODEL_ROUTER_INVALID")
        candidates = route_policy.get("candidates")
        if not isinstance(candidates, list):
            raise MissionPreparationBlocked("MODEL_ROUTER_CANDIDATES_INVALID")
        candidate_ports = [
            value for value in candidates if isinstance(value, str) and value in self.model_ports
        ]
        if not candidate_ports:
            raise MissionPreparationBlocked("MODEL_ROUTER_NO_AVAILABLE_PORT")
        consensus = self._invoke_single_extension(
            "models.consensus-policy",
            "select_consensus",
            evidence=evidence,
            required=True,
            role=role,
            candidates=candidate_ports,
        )
        if not isinstance(consensus, dict):
            raise MissionPreparationBlocked("MODEL_CONSENSUS_INVALID")
        minimum_responses = int(consensus.get("minimum_responses", 1))
        maximum_responses = int(consensus.get("maximum_responses", 1))
        if not 1 <= minimum_responses <= maximum_responses <= 3:
            raise MissionPreparationBlocked("MODEL_CONSENSUS_BOUNDS_INVALID")
        instructions = self._invoke_extension_pipeline(
            "models.prompt-packs",
            "augment_prompt",
            instructions,
            evidence=evidence,
            role=role,
        )
        if not isinstance(instructions, str) or not instructions.strip():
            raise MissionPreparationBlocked("PLUGIN_PROMPT_PIPELINE_INVALID")
        results: list[StructuredCallResult[Any]] = []
        failures: list[str] = []
        for port_name in candidate_ports[:maximum_responses]:
            if self._model_call_count >= self._model_call_budget:
                raise MissionPreparationBlocked("HARNESS_MODEL_CALL_BUDGET_EXCEEDED")
            self._model_call_count += 1
            candidate_port = self.model_ports[port_name]
            role_context = f"{conversation_id}::{role}::{port_name}"
            provider_context_key = f"{candidate_port.settings.name}:{candidate_port.settings.model}"
            if self.config.persisted_task_context:
                stored = self.context_store.window(role_context)
                previous = stored.previous_response_ids.get(provider_context_key)
                if previous and candidate_port.supports_provider_context:
                    candidate_port.restore_provider_context(role_context, previous)
            try:
                candidate_result = candidate_port.call(
                    role=role,
                    output_type=output_type,
                    instructions=instructions,
                    input_artifact=input_artifact,
                    context_id=role_context,
                    multimodal=(self._model_media if role == "intent_parser" else []),
                )
            except ModelInvocationError as error:
                failures.append(f"{port_name}:{type(error).__name__}")
                continue
            if (
                self.config.persisted_task_context
                and candidate_result.record.response_id
                and candidate_port.supports_provider_context
            ):
                self.context_store.set_response_id(
                    role_context, provider_context_key, candidate_result.record.response_id
                )
            results.append(candidate_result)
        if len(results) < minimum_responses:
            raise MissionPreparationBlocked(
                "MODEL_CONSENSUS_INSUFFICIENT_RESPONSES:" + ",".join(failures)
            )
        output_hashes = [sha256_json(item.artifact) for item in results]
        evidence.append(
            f"model.{role}.consensus",
            {
                "policy": consensus,
                "candidate_ports": candidate_ports[:maximum_responses],
                "response_hashes": output_hashes,
                "failures": failures,
            },
        )
        if consensus.get("require_identical") is True and len(set(output_hashes)) != 1:
            raise MissionPreparationBlocked("MODEL_CONSENSUS_DISSENT")
        result = results[0]
        output_envelope = {
            "artifact": result.artifact.model_dump(mode="json"),
            "record": result.record.model_dump(mode="json"),
        }
        guarded_output = self._invoke_extension_pipeline(
            "models.structured-output-guards",
            "validate_output",
            output_envelope,
            evidence=evidence,
            role=role,
            expected_schema=output_type.__name__,
        )
        if guarded_output != output_envelope:
            raise MissionPreparationBlocked("PLUGIN_MODEL_OUTPUT_MUTATION_FORBIDDEN")
        metering = self._invoke_multiple_extensions(
            "models.token-meters",
            "measure_tokens",
            evidence=evidence,
            role=role,
            record=result.record,
        )
        self.context_store.append(
            conversation_id,
            role="assistant",
            event_type=f"model.{role}",
            payload={
                "artifact": result.artifact.model_dump(mode="json"),
                "record": result.record.model_dump(mode="json"),
                "metering": metering,
            },
        )
        evidence.append(
            f"model.{role}",
            {
                "artifact": result.artifact.model_dump(mode="json"),
                "record": result.record.model_dump(mode="json"),
                "metering": metering,
            },
        )
        return result

    @staticmethod
    def _record_tool(
        receipt: ToolReceipt,
        *,
        conversation_id: str,
        context_store: ContextStore,
        evidence: EvidenceChain,
    ) -> None:
        payload = receipt.model_dump(mode="json")
        context_store.append(
            conversation_id, role="tool", event_type=f"tool.{receipt.tool_id}", payload=payload
        )
        evidence.append(f"tool.{receipt.tool_id}", payload)

    def prepare(self, request: MissionRequest, output_dir: Path) -> PreparedMission:
        if output_dir.exists() and any(output_dir.iterdir()):
            raise FileExistsError(f"preparation directory is not empty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        thread = self.context_store.lifecycle.ensure_thread(request.conversation_id)
        if thread.state in {"executing", "holding", "landing"}:
            raise LifecycleTransitionError("ACTIVE_EXECUTION_REJECTS_PREFLIGHT_REPLAN")
        evidence = EvidenceChain(output_dir / "evidence.jsonl")
        self._hook_receipts = list(self._initial_hook_receipts)
        for receipt in self._initial_hook_receipts:
            evidence.append(
                f"plugin-hook.{receipt.slot_id}.{receipt.hook}",
                receipt.model_dump(mode="json"),
            )
        self._model_call_count = 0
        self.tool_registry.configure_extensions(
            self.extension_registry,
            receipt_sink=lambda receipts: self._record_hook_receipts(receipts, evidence),
        )
        harness_profile = self._invoke_single_extension(
            "harness.profile",
            "resolve_profile",
            evidence=evidence,
            required=True,
            request=request,
            map_catalog=self.map_catalog,
            map_graph=self.map_graph,
        )
        if not isinstance(harness_profile, dict):
            raise MissionPreparationBlocked("HARNESS_PROFILE_INVALID")
        evidence.append("harness.profile", harness_profile)
        topology_value = self._invoke_single_extension(
            "harness.workflow-topology",
            "resolve_topology",
            evidence=evidence,
            required=True,
            request=request,
            harness_profile=harness_profile,
            map_catalog=self.map_catalog,
            map_graph=self.map_graph,
        )
        try:
            harness_topology = HarnessTopology.model_validate(topology_value)
        except ValueError as error:
            raise MissionPreparationBlocked("HARNESS_TOPOLOGY_INVALID") from error
        policy_hooks = {
            "scheduler": ("harness.scheduler", "resolve_schedule"),
            "retry": ("harness.retry-policy", "resolve_retry"),
            "timeout": ("harness.timeout-policy", "resolve_timeout"),
            "budget": ("harness.budget-policy", "resolve_budget"),
            "fallback": ("harness.fallback-policy", "resolve_fallback"),
            "cache": ("harness.cache-policy", "resolve_cache"),
        }
        harness_policies: dict[str, dict[str, object]] = {}
        for policy_name, (slot_id, hook_name) in policy_hooks.items():
            policy_value = self._invoke_single_extension(
                slot_id,
                hook_name,
                evidence=evidence,
                required=True,
                request=request,
                harness_profile=harness_profile,
                harness_topology=harness_topology,
            )
            if not isinstance(policy_value, dict):
                raise MissionPreparationBlocked(f"HARNESS_POLICY_INVALID:{policy_name}")
            harness_policies[policy_name] = policy_value
        try:
            runtime_policy = resolve_harness_runtime_policy(
                harness_topology,
                harness_policies,
                maximum_model_calls=self.config.maximum_model_calls,
                maximum_tool_calls=self.config.maximum_optional_tool_calls,
                model_timeout_seconds=self.config.model_timeout_seconds,
            )
        except (TypeError, ValueError) as error:
            raise MissionPreparationBlocked("HARNESS_RUNTIME_POLICY_INVALID") from error
        harness_topology = runtime_policy.topology
        stage_runtime = HarnessStageRuntime(harness_topology)
        self._model_call_budget = runtime_policy.maximum_model_calls
        for port in self.model_ports.values():
            configure = getattr(port, "configure_execution_policy", None)
            if callable(configure):
                configure(
                    maximum_attempts=runtime_policy.provider_attempts,
                    timeout_seconds=runtime_policy.model_timeout_seconds,
                )
        self.tool_registry.configure_runtime_limits(
            maximum_calls=runtime_policy.maximum_tool_calls,
            timeout_seconds=runtime_policy.tool_timeout_seconds,
            maximum_total_calls=256,
            budget_exempt_slot_ids=CORE_PLANNING_SLOTS,
        )
        evidence.append("harness.topology", harness_topology.model_dump(mode="json"))
        evidence.append("harness.policies", harness_policies)
        evidence.append("harness.runtime-policy", runtime_policy.model_dump(mode="json"))
        simulator_descriptor = self._invoke_single_extension(
            "simulation.simulator-descriptor",
            "describe_simulator",
            evidence=evidence,
            required=True,
            request=request,
        )
        simulation_capabilities = {
            "simulator": simulator_descriptor,
            "physics": self._invoke_multiple_extensions(
                "simulation.physics-models",
                "describe_physics",
                evidence=evidence,
                request=request,
            ),
            "sensors": self._invoke_multiple_extensions(
                "simulation.sensor-models",
                "describe_sensor",
                evidence=evidence,
                request=request,
            ),
            "environment": self._invoke_multiple_extensions(
                "simulation.environment-models",
                "describe_environment",
                evidence=evidence,
                request=request,
            ),
            "clock": self._invoke_single_extension(
                "simulation.clock-policy",
                "resolve_clock",
                evidence=evidence,
                required=True,
                request=request,
            ),
            "monte_carlo": self._invoke_single_extension(
                "simulation.monte-carlo-policy",
                "resolve_monte_carlo",
                evidence=evidence,
                required=True,
                request=request,
            ),
        }
        simulation_capabilities["native_runtime"] = {
            "transport": self._invoke_single_extension(
                "native.transport",
                "transport_message",
                evidence=evidence,
                required=True,
                request=request,
            ),
            "state_estimator": self._invoke_single_extension(
                "native.state-estimator",
                "estimate_state",
                evidence=evidence,
                required=True,
                request=request,
            ),
            "localization": self._invoke_single_extension(
                "native.localization",
                "localize",
                evidence=evidence,
                required=True,
                request=request,
            ),
            "controller": self._invoke_single_extension(
                "native.controller",
                "control_policy",
                evidence=evidence,
                required=True,
                request=request,
            ),
            "watchdog": self._invoke_single_extension(
                "native.watchdog",
                "resolve_watchdog",
                evidence=evidence,
                required=True,
                request=request,
            ),
            "telemetry": self._invoke_multiple_extensions(
                "native.telemetry",
                "normalize_telemetry",
                evidence=evidence,
                request=request,
            ),
            "perception": self._invoke_multiple_extensions(
                "native.perception",
                "normalize_telemetry",
                evidence=evidence,
                request=request,
            ),
            "payload": self._invoke_multiple_extensions(
                "native.payload-drivers",
                "payload_command",
                evidence=evidence,
                request=request,
            ),
            "blackbox": self._invoke_multiple_extensions(
                "native.blackbox",
                "normalize_telemetry",
                evidence=evidence,
                request=request,
            ),
        }
        evidence.append("simulation.capabilities", simulation_capabilities)
        event_output = self._invoke_single_extension(
            "harness.event-bus",
            "transport_message",
            evidence=evidence,
            required=True,
            event="mission.preparation.started",
            payload={
                "conversation_id": request.conversation_id,
                "topology_id": harness_topology.topology_id,
                "profile_id": harness_profile.get("profile_id"),
            },
        )
        observer_outputs = self._invoke_multiple_extensions(
            "harness.observers",
            "observe_harness",
            evidence=evidence,
            event="mission.preparation.started",
            payload={
                "conversation_id": request.conversation_id,
                "topology_id": harness_topology.topology_id,
            },
        )
        evidence.append(
            "harness.event",
            {"transport": event_output, "observers": observer_outputs},
        )
        action_pack_outputs = self._invoke_multiple_extensions(
            "mission.action-packs",
            "declare_actions",
            evidence=evidence,
            request=request,
            harness_profile=harness_profile,
            map_catalog=self.map_catalog,
            map_graph=self.map_graph,
        )
        try:
            domain_actions = merge_action_packs(action_pack_outputs)
        except (ValueError, RuntimeError) as error:
            raise MissionPreparationBlocked("DOMAIN_ACTION_CATALOG_INVALID") from error
        evidence.append("mission.domain-actions", domain_actions.model_dump(mode="json"))
        self.context_store.append(
            request.conversation_id,
            role="user",
            event_type="mission.request",
            payload=request.model_dump(mode="json"),
        )
        evidence.append("mission.request", request.model_dump(mode="json"))
        try:
            request_stage = stage_runtime.complete(
                "mission.request-ingest",
                inputs={"request": request.model_dump(mode="json")},
                output={"conversation_id": request.conversation_id},
            )
        except HarnessGraphError as error:
            raise MissionPreparationBlocked(error.code) from error
        evidence.append("harness.stage", request_stage.model_dump(mode="json"))
        channel_outputs = self._invoke_multiple_extensions(
            "input.channels",
            "ingest_input",
            evidence=evidence,
            request=request,
        )
        accepted_channels = [
            output
            for output in channel_outputs
            if isinstance(output, dict) and output.get("accepted") is True
        ]
        if len(accepted_channels) != 1:
            raise MissionPreparationBlocked("INPUT_CHANNEL_NOT_ACCEPTED")
        language_features = self._invoke_extension_pipeline(
            "input.locale-pipeline",
            "resolve_locale",
            {
                "message": request.message,
                "locale": request.locale,
            },
            evidence=evidence,
            request=request,
        )
        entity_features = self._invoke_extension_pipeline(
            "input.entity-pipeline",
            "resolve_entity",
            language_features,
            evidence=evidence,
            request=request,
            map_catalog=self.map_catalog,
            map_graph=self.map_graph,
        )
        request_features = self._invoke_extension_pipeline(
            "input.request-features",
            "enrich_request",
            {
                **entity_features,
                "start_entity": request.start_entity,
                "input_channel": accepted_channels[0],
            },
            evidence=evidence,
            request=request,
        )
        if not isinstance(request_features, dict):
            raise MissionPreparationBlocked("PLUGIN_REQUEST_FEATURES_INVALID")
        evidence.append("mission.request-features", request_features)
        multimodal = self._invoke_extension_pipeline(
            "models.multimodal-preprocessors",
            "preprocess_multimodal",
            {"media": []},
            evidence=evidence,
            attachments=request.attachments,
        )
        if not isinstance(multimodal, dict) or not isinstance(multimodal.get("media"), list):
            raise MissionPreparationBlocked("MODEL_MULTIMODAL_PREPROCESSOR_INVALID")
        self._model_media = [item for item in multimodal["media"] if isinstance(item, dict)][:4]
        evidence.append(
            "mission.multimodal-input",
            {
                "count": len(self._model_media),
                "sha256": sha256_json(
                    [
                        {key: value for key, value in item.items() if key != "path"}
                        for item in self._model_media
                    ]
                ),
            },
        )
        context_store_policy = self._invoke_single_extension(
            "context.store",
            "resolve_context_store",
            evidence=evidence,
            required=True,
            conversation_id=request.conversation_id,
        )
        if (
            not isinstance(context_store_policy, dict)
            or context_store_policy.get("backend") != "sqlite-wal"
        ):
            raise MissionPreparationBlocked("CONTEXT_STORE_UNAVAILABLE")
        retrieval_policy = self._invoke_single_extension(
            "context.retrieval-policy",
            "retrieve_context",
            evidence=evidence,
            required=True,
            conversation_id=request.conversation_id,
        )
        if not isinstance(retrieval_policy, dict):
            raise MissionPreparationBlocked("CONTEXT_RETRIEVAL_POLICY_INVALID")
        maximum_recent_events = int(retrieval_policy.get("maximum_recent_events", 24))
        context_window = self.context_store.window(
            request.conversation_id,
            max_recent_events=max(1, min(200, maximum_recent_events)),
        )
        if not self.config.persisted_task_context:
            context_window = ConversationWindow(
                conversation_id=request.conversation_id,
                summary=None,
                recent_events=context_window.recent_events[-1:],
                previous_response_ids={},
            )
        compact_context = self._invoke_single_extension(
            "context.compaction-strategy",
            "compact_context",
            evidence=evidence,
            window=context_window,
        )
        if compact_context is None:
            compact_context = _compact_context(context_window)
        compact_context = self._invoke_extension_pipeline(
            "context.enrichment",
            "enrich_context",
            compact_context,
            evidence=evidence,
            request=request,
            map_catalog=self.map_catalog,
            map_graph=self.map_graph,
        )
        if not isinstance(compact_context, dict):
            raise MissionPreparationBlocked("PLUGIN_CONTEXT_PIPELINE_INVALID")
        try:
            context_stage = stage_runtime.complete(
                "mission.context-prepare",
                inputs={"request_context": request_features},
                output=compact_context,
            )
        except HarnessGraphError as error:
            raise MissionPreparationBlocked(error.code) from error
        evidence.append("harness.stage", context_stage.model_dump(mode="json"))
        explicit_constraint_hints = _explicit_constraint_hints(request)
        model_calls: list[ModelCallRecord] = []
        tool_receipts: list[ToolReceipt] = []

        intent: IntentArtifact | None = None
        intent_critique: IntentCritique | None = None
        prior_intent: dict[str, object] | None = None
        prior_critique: dict[str, object] | None = None
        for intent_round in range(1, self.config.max_intent_rounds + 1):
            parsed = self._call(
                port=self.primary,
                role="intent_parser",
                output_type=IntentArtifact,
                instructions=INTENT_PARSER,
                input_artifact={
                    "round": intent_round,
                    "mission_request": request.model_dump(mode="json"),
                    "explicit_constraint_hints": explicit_constraint_hints,
                    "workflow_scope": {
                        "environment": "simulation-only",
                        "operator_authorized": True,
                        "physical_hardware_authority": False,
                        "one_way_return_entity_semantics": (
                            "final landing entity equals target entity"
                        ),
                    },
                    "harness_profile": harness_profile,
                    "request_features": request_features,
                    "conversation_window": compact_context,
                    "map_catalog": self.map_catalog.model_dump(mode="json"),
                    "domain_action_catalog": domain_actions.model_dump(mode="json"),
                    "previous_candidate": prior_intent,
                    "critic_feedback": prior_critique,
                },
                conversation_id=request.conversation_id,
                evidence=evidence,
            )
            model_calls.append(parsed.record)
            intent = self._invoke_extension_pipeline(
                "input.intent-normalizers",
                "normalize_intent",
                parsed.artifact,
                evidence=evidence,
                request=request,
                map_catalog=self.map_catalog,
            )
            intent = IntentArtifact.model_validate(intent)
            if intent.payload_action not in action_ids(domain_actions):
                prior_intent = intent.model_dump(mode="json")
                prior_critique = {
                    "schema_version": "dronedream.intent-critique.v1",
                    "accepted": False,
                    "issue_codes": ["PAYLOAD_ACTION_NOT_REGISTERED"],
                    "repair_instructions": ["Select payload_action from domain_action_catalog."],
                }
                evidence.append("intent.validation-rejected", prior_critique)
                continue
            intent_reviews: list[IntentCritique] = []
            topology_review_count = len(
                [
                    item
                    for item in harness_topology.nodes
                    if item.node_id.startswith("mission.intent-review-")
                ]
            )
            intent_review_count = max(self.config.intent_reviews_per_round, topology_review_count)
            for review_index in range(1, intent_review_count + 1):
                reviewed = self._call(
                    port=self.critic,
                    role="intent_critic",
                    output_type=IntentCritique,
                    instructions=INTENT_CRITIC,
                    input_artifact={
                        "review_index": review_index,
                        "review_count": intent_review_count,
                        "independent_review": intent_review_count > 1,
                        "mission_request": request.model_dump(mode="json"),
                        "workflow_scope": {
                            "environment": "simulation-only",
                            "operator_authorized": True,
                            "physical_hardware_authority": False,
                            "one_way_return_entity_semantics": (
                                "final landing entity equals target entity"
                            ),
                        },
                        "harness_profile": harness_profile,
                        "request_features": request_features,
                        "candidate_intent": intent.model_dump(mode="json"),
                        "explicit_constraint_hints": explicit_constraint_hints,
                        "map_catalog": self.map_catalog.model_dump(mode="json"),
                        "domain_action_catalog": domain_actions.model_dump(mode="json"),
                    },
                    conversation_id=request.conversation_id,
                    evidence=evidence,
                )
                model_calls.append(reviewed.record)
                intent_reviews.append(reviewed.artifact)
            intent_critique = IntentCritique(
                accepted=all(review.accepted for review in intent_reviews),
                issue_codes=list(
                    dict.fromkeys(code for review in intent_reviews for code in review.issue_codes)
                )[:16],
                repair_instructions=list(
                    dict.fromkeys(
                        instruction
                        for review in intent_reviews
                        for instruction in review.repair_instructions
                    )
                )[:16],
            )
            missing_explicit_constraints = _missing_explicit_constraints(
                intent, explicit_constraint_hints
            )
            if (
                intent_critique.accepted
                and not intent.missing_critical_fields
                and not missing_explicit_constraints
            ):
                break
            prior_intent = intent.model_dump(mode="json")
            if missing_explicit_constraints:
                prior_critique = {
                    "schema_version": "dronedream.intent-critique.v1",
                    "accepted": False,
                    "issue_codes": ["MISSING_EXPLICIT_CONSTRAINT"],
                    "repair_instructions": [
                        "Add these canonical values to constraints: "
                        + ", ".join(missing_explicit_constraints)
                    ],
                }
                evidence.append("intent.validation-rejected", prior_critique)
            else:
                prior_critique = intent_critique.model_dump(mode="json")
        else:
            raise MissionPreparationBlocked("INTENT_REVIEW_EXHAUSTED")
        assert intent is not None and intent_critique is not None
        try:
            intent_stage = stage_runtime.complete(
                "mission.intent-parse",
                inputs={"context": compact_context, "request_features": request_features},
                output=intent.model_dump(mode="json"),
            )
            review_stage_receipts = []
            for review_index, review in enumerate(intent_reviews, start=1):
                stage_id = f"mission.intent-review-{review_index}"
                if stage_runtime.contains(stage_id):
                    review_stage_receipts.append(
                        stage_runtime.complete(
                            stage_id,
                            inputs={"intent": intent.model_dump(mode="json")},
                            output=review.model_dump(mode="json"),
                        )
                    )
            consensus_stage = stage_runtime.complete(
                "mission.intent-consensus",
                inputs={"reviews": [item.model_dump(mode="json") for item in intent_reviews]},
                output=intent_critique.model_dump(mode="json"),
            )
        except HarnessGraphError as error:
            raise MissionPreparationBlocked(error.code) from error
        for stage_receipt in [intent_stage, *review_stage_receipts, consensus_stage]:
            evidence.append("harness.stage", stage_receipt.model_dump(mode="json"))
        _write_artifact(output_dir / "01-intent.json", intent)
        _write_artifact(output_dir / "02-intent-critique.json", intent_critique)

        contract = MissionContract(
            contract_id=f"mission-{uuid4().hex[:24]}",
            conversation_id=request.conversation_id,
            goal=intent.goal,
            start_node=_resolve_entity(intent.start_entity, self.map_catalog, self.map_graph),
            target_node=_resolve_entity(intent.target_entity, self.map_catalog, self.map_graph),
            return_node=_resolve_entity(intent.return_entity, self.map_catalog, self.map_graph),
            payload_action=intent.payload_action,
            domain_ids=domain_actions.domain_ids,
            authorized_actions=sorted(action_ids(domain_actions)),
            action_catalog_sha256=sha256_json(domain_actions),
            map_asset_id=self.map_graph.asset_id,
            map_sha256=sha256_json(self.map_graph),
            map_semantic_sha256=_file_sha256(self.semantic_path),
            vehicle_asset_id=self.vehicle_asset_id,
            vehicle_sha256=_file_sha256(self.vehicle_sdf),
            constraints=intent.constraints,
            immutable_safety_rules=IMMUTABLE_SAFETY_RULES,
        )
        _write_artifact(output_dir / "03-mission-contract.json", contract)
        evidence.append("mission.contract", contract.model_dump(mode="json"))
        try:
            contract_stage = stage_runtime.complete(
                "mission.contract-freeze",
                inputs={"accepted_intent": intent.model_dump(mode="json")},
                output=contract.model_dump(mode="json"),
            )
        except HarnessGraphError as error:
            raise MissionPreparationBlocked(error.code) from error
        evidence.append("harness.stage", contract_stage.model_dump(mode="json"))

        registry = self.tool_registry
        plugin_advice: list[dict[str, object]] = []
        optional_catalog = (
            [
                item
                for item in registry.catalog()
                if item.get("slot_id") not in CORE_PLANNING_SLOTS
                and item["authority"] in {"read", "plan", "simulate"}
            ][:32]
            if stage_runtime.contains("mission.tool-advice")
            else []
        )
        if optional_catalog:
            recommended_tool_ids = _recommended_plugin_tools(optional_catalog, contract)
            router_policy = self._invoke_single_extension(
                "tools.router-policy",
                "recommend_tools",
                evidence=evidence,
                contract=contract,
                catalog=optional_catalog,
                recommended_tool_ids=recommended_tool_ids,
            )
            if isinstance(router_policy, dict):
                candidate_ids = router_policy.get("recommended_tool_ids")
                if isinstance(candidate_ids, list):
                    available_ids = {str(item["tool_id"]) for item in optional_catalog}
                    recommended_tool_ids = sorted(
                        {str(tool_id) for tool_id in candidate_ids if str(tool_id) in available_ids}
                    )
            router_feedback: dict[str, object] | None = None
            routed: StructuredCallResult[PluginInvocationPlan]
            missing_recommended: list[str] = []
            for router_round in range(1, self.config.plugin_router_rounds + 1):
                routed = self._call(
                    port=self.primary,
                    role="plugin_router",
                    output_type=PluginInvocationPlan,
                    instructions=PLUGIN_ROUTER,
                    input_artifact={
                        "round": router_round,
                        "mission_contract": contract.model_dump(mode="json"),
                        "optional_tool_catalog": optional_catalog,
                        "recommended_tool_ids": recommended_tool_ids,
                        "maximum_calls": min(
                            self.config.maximum_plugin_calls,
                            self.config.maximum_optional_tool_calls,
                            int(
                                harness_policies["budget"].get(
                                    "maximum_tool_calls",
                                    self.config.maximum_optional_tool_calls,
                                )
                            ),
                        ),
                        "advisory_only": True,
                        "harness_profile": harness_profile,
                        "router_feedback": router_feedback,
                    },
                    conversation_id=request.conversation_id,
                    evidence=evidence,
                )
                model_calls.append(routed.record)
                selected_tools = {call.tool_id for call in routed.artifact.calls}
                missing_recommended = sorted(set(recommended_tool_ids) - selected_tools)
                if not missing_recommended:
                    break
                router_feedback = {
                    "issue_code": "RECOMMENDED_PLUGIN_NOT_SELECTED",
                    "missing_tool_ids": missing_recommended,
                    "repair": "Select each matching recommended tool with schema-valid JSON.",
                }
            if missing_recommended:
                evidence.append(
                    "plugin.routing-recommendation-unmet",
                    {"tool_ids": missing_recommended},
                )
            available_optional_tools = {str(item["tool_id"]): item for item in optional_catalog}
            for invocation in routed.artifact.calls:
                if invocation.tool_id not in available_optional_tools:
                    evidence.append(
                        "plugin.invocation-rejected",
                        {
                            "tool_id": invocation.tool_id,
                            "issue_code": "PLUGIN_TOOL_NOT_IN_ROUTING_CATALOG",
                        },
                    )
                    continue
                try:
                    arguments = invocation.parsed_arguments()
                except ValueError:
                    evidence.append(
                        "plugin.invocation-rejected",
                        {
                            "tool_id": invocation.tool_id,
                            "issue_code": "PLUGIN_ARGUMENTS_JSON_INVALID",
                        },
                    )
                    continue
                try:
                    output, receipt = registry.call(invocation.tool_id, arguments)
                except ToolExecutionError as error:
                    receipt = error.receipt
                    self._record_tool(
                        receipt,
                        conversation_id=request.conversation_id,
                        context_store=self.context_store,
                        evidence=evidence,
                    )
                    tool_receipts.append(receipt)
                    plugin_advice.append(
                        {
                            "tool_id": invocation.tool_id,
                            "purpose": invocation.purpose,
                            "accepted": False,
                            "issue_codes": receipt.issue_codes,
                        }
                    )
                    continue
                self._record_tool(
                    receipt,
                    conversation_id=request.conversation_id,
                    context_store=self.context_store,
                    evidence=evidence,
                )
                tool_receipts.append(receipt)
                plugin_advice.append(
                    {
                        "tool_id": invocation.tool_id,
                        "purpose": invocation.purpose,
                        "accepted": True,
                        "output": (
                            output.model_dump(mode="json")
                            if hasattr(output, "model_dump")
                            else output
                        ),
                        "output_sha256": receipt.output_sha256,
                    }
                )
            _write_artifact(output_dir / "03a-plugin-advice.json", plugin_advice)
            evidence.append("plugin.advice", {"results": plugin_advice})
        plugin_advice = self._invoke_extension_pipeline(
            "tools.result-fusion",
            "fuse_results",
            plugin_advice,
            evidence=evidence,
            contract=contract,
            domain_actions=domain_actions,
        )
        if not isinstance(plugin_advice, list) or any(
            not isinstance(item, dict) for item in plugin_advice
        ):
            raise MissionPreparationBlocked("PLUGIN_RESULT_FUSION_INVALID")
        _write_artifact(output_dir / "03b-plugin-advice-fused.json", plugin_advice)
        if stage_runtime.contains("mission.tool-advice"):
            try:
                advice_stage = stage_runtime.complete(
                    "mission.tool-advice",
                    inputs={"contract": contract.model_dump(mode="json")},
                    output=plugin_advice,
                )
            except HarnessGraphError as error:
                raise MissionPreparationBlocked(error.code) from error
            evidence.append("harness.stage", advice_stage.model_dump(mode="json"))
        planning_contributions = [
            PlannerContribution.model_validate(value)
            for value in self._invoke_multiple_extensions(
                "planning.specialists",
                "contribute_planning",
                evidence=evidence,
                contract=contract,
                map_graph=self.map_graph,
                vehicle=self.vehicle,
                simulator_descriptor=simulator_descriptor,
                simulation_components=simulation_capabilities,
            )
        ]
        if not planning_contributions or any(
            not all(contribution.deterministic_gates.values())
            for contribution in planning_contributions
        ):
            raise MissionPreparationBlocked("PLANNING_SPECIALIST_CONTRIBUTION_REJECTED")
        _write_artifact(
            output_dir / "03c-planning-contributions.json",
            [value.model_dump(mode="json") for value in planning_contributions],
        )
        evidence.append(
            "planning.specialists",
            {"contributions": [value.model_dump(mode="json") for value in planning_contributions]},
        )
        plan_feedback: dict[str, object] | None = None
        accepted_values: (
            tuple[
                TaskGraph,
                SemanticPlan,
                FlightPlan,
                PlanCritique,
                GraphRoute,
                RouteClearanceReport,
                Px4Track,
            ]
            | None
        ) = None
        planning_attempts = 0
        for planning_attempts in range(1, self.config.max_planning_rounds + 1):
            decomposed = self._call(
                port=self.primary,
                role="task_decomposer",
                output_type=TaskGraphArtifact,
                instructions=TASK_DECOMPOSER,
                input_artifact={
                    "round": planning_attempts,
                    "mission_contract": contract.model_dump(mode="json"),
                    "available_node_ids": [node.node_id for node in self.map_graph.nodes],
                    "domain_action_catalog": domain_actions.model_dump(mode="json"),
                    "optional_plugin_advice": plugin_advice,
                    "harness_profile": harness_profile,
                    "planning_specialists": [
                        value.model_dump(mode="json") for value in planning_contributions
                    ],
                    "previous_plan_critique": plan_feedback,
                },
                conversation_id=request.conversation_id,
                evidence=evidence,
            )
            model_calls.append(decomposed.record)
            task_graph = self._invoke_extension_pipeline(
                "planning.task-transformers",
                "transform_task_graph",
                decomposed.artifact.graph,
                evidence=evidence,
                contract=contract,
                map_graph=self.map_graph,
                planning_round=planning_attempts,
            )
            task_graph = TaskGraph.model_validate(task_graph)
            try:
                _validate_task_graph(task_graph, contract, self.map_graph, domain_actions)
            except MissionPreparationBlocked as exc:
                plan_feedback = {
                    "accepted": False,
                    "issue_codes": [str(exc)],
                    "repair_instructions": [
                        "Repair the task graph using only the grounded contract nodes."
                    ],
                }
                evidence.append("planning.validation-rejected", plan_feedback)
                continue

            planned = self._call(
                port=self.primary,
                role="global_planner",
                output_type=SemanticPlan,
                instructions=GLOBAL_PLANNER,
                input_artifact={
                    "round": planning_attempts,
                    "mission_contract": contract.model_dump(mode="json"),
                    "task_graph": task_graph.model_dump(mode="json"),
                    "available_node_ids": [node.node_id for node in self.map_graph.nodes],
                    "hard_output_rules": {
                        "first_target_must_not_equal": contract.start_node,
                        "must_include_target": contract.target_node,
                        "final_target_must_equal": contract.return_node,
                        "only_allowed_targets": list(
                            dict.fromkeys([contract.target_node, contract.return_node])
                        ),
                    },
                    "previous_plan_critique": plan_feedback,
                    "tool_catalog": registry.catalog(),
                    "optional_plugin_advice": plugin_advice,
                    "harness_profile": harness_profile,
                    "planning_specialists": [
                        value.model_dump(mode="json") for value in planning_contributions
                    ],
                },
                conversation_id=request.conversation_id,
                evidence=evidence,
            )
            model_calls.append(planned.record)
            semantic_plan = self._invoke_extension_pipeline(
                "planning.semantic-optimizers",
                "optimize_semantic_plan",
                planned.artifact,
                evidence=evidence,
                contract=contract,
                task_graph=task_graph,
                map_graph=self.map_graph,
            )
            semantic_plan = SemanticPlan.model_validate(semantic_plan)
            try:
                _validate_semantic_plan(semantic_plan, contract, self.map_graph)
            except MissionPreparationBlocked as exc:
                plan_feedback = {
                    "accepted": False,
                    "issue_codes": [str(exc)],
                    "repair_instructions": [
                        "Repair the ordered targets; geometry remains tool-owned."
                    ],
                }
                evidence.append("planning.validation-rejected", plan_feedback)
                continue

            attempt_receipts: list[ToolReceipt] = []
            primary_strategy = registry.tool_for_slot("planning.route-strategy")
            strategy_tools = list(
                dict.fromkeys(
                    [
                        primary_strategy,
                        *registry.tool_ids_for_slot("planning.route-candidates"),
                    ]
                )
            )
            route_alternatives: list[RouteAlternativeCandidate] = []
            alternative_segments: dict[str, list[GraphRoute]] = {}
            for strategy_tool_id in strategy_tools:
                candidate_routes: list[GraphRoute] = []
                current = contract.start_node
                strategy_failed = False
                for target in semantic_plan.ordered_targets:
                    try:
                        route_value, receipt = registry.call(
                            strategy_tool_id,
                            RouteQuery(start_node=current, goal_node=target),
                        )
                    except ToolExecutionError as error:
                        attempt_receipts.append(error.receipt)
                        self._record_tool(
                            error.receipt,
                            conversation_id=request.conversation_id,
                            context_store=self.context_store,
                            evidence=evidence,
                        )
                        evidence.append(
                            "planning.route-candidate-failed",
                            {
                                "strategy_tool_id": strategy_tool_id,
                                "target": target,
                                "issue_codes": error.receipt.issue_codes,
                            },
                        )
                        strategy_failed = True
                        break
                    route = GraphRoute.model_validate(route_value)
                    candidate_routes.append(route)
                    attempt_receipts.append(receipt)
                    self._record_tool(
                        receipt,
                        conversation_id=request.conversation_id,
                        context_store=self.context_store,
                        evidence=evidence,
                    )
                    current = target
                if strategy_failed:
                    continue
                candidate_route = _combine_routes(candidate_routes)
                try:
                    clearance_value, clearance_receipt = registry.call_slot(
                        "safety.route-clearance", candidate_route
                    )
                except ToolExecutionError as error:
                    attempt_receipts.append(error.receipt)
                    self._record_tool(
                        error.receipt,
                        conversation_id=request.conversation_id,
                        context_store=self.context_store,
                        evidence=evidence,
                    )
                    evidence.append(
                        "planning.route-candidate-clearance-failed",
                        {
                            "strategy_tool_id": strategy_tool_id,
                            "issue_codes": error.receipt.issue_codes,
                        },
                    )
                    continue
                candidate_clearance = RouteClearanceReport.model_validate(clearance_value)
                attempt_receipts.append(clearance_receipt)
                self._record_tool(
                    clearance_receipt,
                    conversation_id=request.conversation_id,
                    context_store=self.context_store,
                    evidence=evidence,
                )
                gates = {
                    "continuous_clearance": candidate_clearance.accepted,
                    "contract_start": candidate_route.start_node == contract.start_node,
                    "contract_return": candidate_route.goal_node == contract.return_node,
                    "all_targets_present": all(
                        target in candidate_route.node_ids
                        for target in semantic_plan.ordered_targets
                    ),
                }
                issue_codes = [
                    f"ROUTE_ALTERNATIVE_{name.upper()}_REJECTED"
                    for name, accepted in gates.items()
                    if not accepted
                ]
                alternative_id = (
                    "route-alternative-"
                    + sha256_json(
                        {
                            "strategy_tool_id": strategy_tool_id,
                            "route": candidate_route,
                            "clearance": candidate_clearance,
                        }
                    )[:20]
                )
                candidate = RouteAlternativeCandidate(
                    alternative_id=alternative_id,
                    strategy_tool_id=strategy_tool_id,
                    route=candidate_route,
                    clearance=candidate_clearance,
                    objectives=_route_objectives(candidate_route, candidate_clearance),
                    hard_gates=gates,
                    feasible=all(gates.values()),
                    issue_codes=issue_codes,
                )
                route_alternatives.append(candidate)
                alternative_segments[alternative_id] = candidate_routes
            if not route_alternatives or not any(
                candidate.feasible for candidate in route_alternatives
            ):
                raise MissionPreparationBlocked("ROUTE_ALTERNATIVE_NO_FEASIBLE_CANDIDATE")
            alternative_set = RouteAlternativeSet(
                contract_id=contract.contract_id,
                candidates=route_alternatives,
                objective_weights={
                    "distance_m": 0.20,
                    "minimum_clearance_m": 0.46,
                    "energy_proxy": 0.14,
                    "transition_count": 0.10,
                    "qualification_penalty": 0.10,
                },
            )
            decision_value, decision_receipt = registry.call_slot(
                "planning.alternative-ranker", alternative_set
            )
            alternative_decision = RouteAlternativeDecision.model_validate(decision_value)
            attempt_receipts.append(decision_receipt)
            self._record_tool(
                decision_receipt,
                conversation_id=request.conversation_id,
                context_store=self.context_store,
                evidence=evidence,
            )
            feasible_ids = {
                candidate.alternative_id for candidate in route_alternatives if candidate.feasible
            }
            if (
                alternative_decision.selected_alternative_id not in feasible_ids
                or alternative_decision.ranked_alternative_ids[0]
                != alternative_decision.selected_alternative_id
                or set(alternative_decision.ranked_alternative_ids) != feasible_ids
                or set(alternative_decision.normalized_scores) != feasible_ids
            ):
                raise MissionPreparationBlocked("ROUTE_ALTERNATIVE_DECISION_INVALID")
            selected_alternative = next(
                candidate
                for candidate in route_alternatives
                if candidate.alternative_id == alternative_decision.selected_alternative_id
            )
            routes = alternative_segments[selected_alternative.alternative_id]
            execution_route = selected_alternative.route
            clearance = selected_alternative.clearance
            alternative_artifact = {
                "candidate_set": alternative_set.model_dump(mode="json"),
                "decision": alternative_decision.model_dump(mode="json"),
            }
            _write_artifact(output_dir / "05a-route-alternatives.json", alternative_artifact)
            evidence.append("planning.route-alternatives", alternative_artifact)
            flight_plan = _flight_plan(
                contract,
                task_graph,
                semantic_plan,
                routes,
                self.map_graph,
                clearance.minimum_clearance_m,
            )
            track_value, track_receipt = registry.call_slot(
                "flight-control.track-export",
                Px4TrackRequest(
                    route=execution_route,
                    waypoint_hold_seconds=self.config.waypoint_hold_seconds,
                ),
            )
            px4_track = Px4Track.model_validate(track_value)
            px4_track = self._invoke_extension_pipeline(
                "planning.track-optimizers",
                "optimize_track",
                px4_track,
                evidence=evidence,
                contract=contract,
                task_graph=task_graph,
                semantic_plan=semantic_plan,
                route=execution_route,
                clearance=clearance,
            )
            px4_track = Px4Track.model_validate(px4_track)
            _validate_plugin_track_tightening(px4_track, execution_route, self.vehicle)
            attempt_receipts.append(track_receipt)
            self._record_tool(
                track_receipt,
                conversation_id=request.conversation_id,
                context_store=self.context_store,
                evidence=evidence,
            )
            tool_receipts.extend(attempt_receipts)

            plan_scores = self._invoke_multiple_extensions(
                "planning.plan-scorers",
                "score_plan",
                evidence=evidence,
                contract=contract,
                task_graph=task_graph,
                semantic_plan=semantic_plan,
                flight_plan=flight_plan,
                vehicle=self.vehicle,
                route=execution_route,
                clearance=clearance,
                px4_track=px4_track,
            )
            validation_results = self._invoke_multiple_extensions(
                "validation.plan-gates",
                "validate_plan",
                evidence=evidence,
                contract=contract,
                task_graph=task_graph,
                semantic_plan=semantic_plan,
                flight_plan=flight_plan,
                vehicle=self.vehicle,
                route=execution_route,
                clearance=clearance,
                px4_track=px4_track,
            )
            specialist_validations = [
                PlannerValidation.model_validate(value)
                for value in self._invoke_multiple_extensions(
                    "planning.specialists",
                    "validate_planning",
                    evidence=evidence,
                    contract=contract,
                    map_graph=self.map_graph,
                    vehicle=self.vehicle,
                    task_graph=task_graph,
                    semantic_plan=semantic_plan,
                    flight_plan=flight_plan,
                    route=execution_route,
                    clearance=clearance,
                    px4_track=px4_track,
                )
            ]
            validation_results.extend(
                value.model_dump(mode="json") for value in specialist_validations
            )
            rejected_validators = [
                value
                for value in validation_results
                if isinstance(value, dict) and value.get("accepted") is False
            ]
            if rejected_validators:
                plan_feedback = {
                    "accepted": False,
                    "issue_codes": [
                        str(code)
                        for value in rejected_validators
                        for code in value.get("issue_codes", ["PLUGIN_PLAN_GATE_REJECTED"])
                    ],
                    "repair_instructions": [
                        str(item)
                        for value in rejected_validators
                        for item in value.get("repair_instructions", [])
                    ],
                }
                evidence.append("planning.plugin-validation-rejected", plan_feedback)
                continue

            plan_reviews: list[PlanCritique] = []
            plan_review_input = {
                "mission_contract": contract.model_dump(mode="json"),
                "task_graph": task_graph.model_dump(mode="json"),
                "semantic_plan": semantic_plan.model_dump(mode="json"),
                "flight_plan_scope": (
                    "movement segments only; takeoff, pickup, and land are explicit "
                    "TaskGraph actions executed by dedicated runtime adapters"
                ),
                "flight_plan_summary": {
                    "contract_id": flight_plan.contract_id,
                    "semantic_plan_sha256": flight_plan.semantic_plan_sha256,
                    "segments": [
                        {
                            "segment_id": segment.segment_id,
                            "task_id": segment.task_id,
                            "from_node": segment.from_node,
                            "to_node": segment.to_node,
                            "path_point_count": len(segment.path),
                            "path_sha256": sha256_json(segment.path),
                            "speed_limit_mps": segment.speed_limit_mps,
                            "minimum_clearance_m": segment.minimum_clearance_m,
                            "success_evidence": segment.success_evidence,
                        }
                        for segment in flight_plan.segments
                    ],
                },
                "semantic_plan_binding": {
                    "semantic_plan_sha256": sha256_json(semantic_plan),
                    "flight_plan_semantic_plan_sha256": flight_plan.semantic_plan_sha256,
                    "hash_matches": (
                        flight_plan.semantic_plan_sha256 == sha256_json(semantic_plan)
                    ),
                },
                "execution_route_summary": {
                    "start_node": execution_route.start_node,
                    "goal_node": execution_route.goal_node,
                    "point_count": len(execution_route.node_ids),
                    "route_length_m": execution_route.route_length_m,
                    "all_edges_flight_verified": (execution_route.all_edges_flight_verified),
                    "route_sha256": sha256_json(execution_route),
                },
                "route_clearance_summary": {
                    "accepted": clearance.accepted,
                    "route_sha256": clearance.route_sha256,
                    "semantic_sha256": clearance.semantic_sha256,
                    "sample_count": clearance.sample_count,
                    "primitive_count": clearance.primitive_count,
                    "collision_count": clearance.collision_count,
                    "minimum_clearance_m": clearance.minimum_clearance_m,
                },
                "deterministic_gates": {
                    "semantic_plan_hash_matches_flight_plan": (
                        flight_plan.semantic_plan_sha256 == sha256_json(semantic_plan)
                    ),
                    "clearance_route_hash_matches": (
                        clearance.route_sha256 == sha256_json(execution_route)
                    ),
                    "clearance_semantic_hash_matches_contract": (
                        clearance.semantic_sha256 == contract.map_semantic_sha256
                    ),
                    "route_starts_at_contract_start": (
                        execution_route.start_node == contract.start_node
                    ),
                    "route_ends_at_contract_return": (
                        execution_route.goal_node == contract.return_node
                    ),
                    "all_tool_receipts_accepted": all(
                        item.outcome == "accepted" for item in attempt_receipts
                    ),
                },
                "tool_receipts": [
                    {
                        "tool_id": item.tool_id,
                        "outcome": item.outcome,
                        "input_sha256": item.input_sha256,
                        "output_sha256": item.output_sha256,
                    }
                    for item in attempt_receipts
                ],
                "planning_evidence_scope": {
                    "phase": "pre_execution_planning",
                    "present_evidence_must_be_hash_bound": True,
                    "future_runtime_evidence_is_expected_after_confirmation": True,
                    "future_runtime_evidence": [
                        "telemetry-continuity",
                        "payload-identity",
                        "payload-mass-and-attachment",
                        "runtime-checkpoints",
                        "execution-confirmation",
                        "landing-confirmation",
                        "completion-assessment",
                    ],
                    "future_runtime_evidence_declared_by_accepted_tool_receipts": all(
                        item.outcome == "accepted" for item in attempt_receipts
                    ),
                },
                "optional_plugin_advice": plugin_advice,
                "plugin_plan_scores": plan_scores,
                "plugin_validation_results": validation_results,
                "route_alternative_decision": alternative_decision.model_dump(mode="json"),
                "harness_profile": harness_profile,
            }
            for review_index in range(1, self.config.plan_reviews_per_round + 1):
                critique = self._call(
                    port=self.critic,
                    role="plan_critic",
                    output_type=PlanCritique,
                    instructions=PLAN_CRITIC,
                    input_artifact={
                        **plan_review_input,
                        "review_index": review_index,
                        "review_count": self.config.plan_reviews_per_round,
                        "independent_review": self.config.plan_reviews_per_round > 1,
                    },
                    conversation_id=request.conversation_id,
                    evidence=evidence,
                )
                model_calls.append(critique.record)
                plan_reviews.append(critique.artifact)
            plan_critique = PlanCritique(
                accepted=all(review.accepted for review in plan_reviews),
                issue_codes=list(
                    dict.fromkeys(code for review in plan_reviews for code in review.issue_codes)
                )[:32],
                repair_instructions=list(
                    dict.fromkeys(
                        instruction
                        for review in plan_reviews
                        for instruction in review.repair_instructions
                    )
                )[:32],
            )
            if plan_critique.accepted:
                accepted_values = (
                    task_graph,
                    semantic_plan,
                    flight_plan,
                    plan_critique,
                    execution_route,
                    clearance,
                    px4_track,
                )
                break
            plan_feedback = plan_critique.model_dump(mode="json")
        if accepted_values is None:
            raise MissionPreparationBlocked("PLAN_REVIEW_EXHAUSTED")
        (
            task_graph,
            semantic_plan,
            flight_plan,
            plan_critique,
            execution_route,
            clearance,
            px4_track,
        ) = accepted_values
        try:
            preparation_stages = [
                stage_runtime.complete(
                    "mission.task-decompose",
                    inputs={
                        "contract": contract.model_dump(mode="json"),
                        "tool_advice": plugin_advice,
                    },
                    output=task_graph.model_dump(mode="json"),
                ),
                stage_runtime.complete(
                    "mission.semantic-plan",
                    inputs={"task_graph": task_graph.model_dump(mode="json")},
                    output=semantic_plan.model_dump(mode="json"),
                ),
                stage_runtime.complete(
                    "mission.route-resolve",
                    inputs={"semantic_plan": semantic_plan.model_dump(mode="json")},
                    output=execution_route.model_dump(mode="json"),
                ),
                stage_runtime.complete(
                    "mission.clearance-gate",
                    inputs={"route": execution_route.model_dump(mode="json")},
                    output=clearance.model_dump(mode="json"),
                ),
                stage_runtime.complete(
                    "mission.track-export",
                    inputs={"clearance": clearance.model_dump(mode="json")},
                    output=px4_track.model_dump(mode="json"),
                ),
                stage_runtime.complete(
                    "mission.plan-evaluation",
                    inputs={"track": px4_track.model_dump(mode="json")},
                    output={
                        "scores": plan_scores,
                        "validation_results": validation_results,
                    },
                ),
                stage_runtime.complete(
                    "mission.plan-review",
                    inputs={"track": px4_track.model_dump(mode="json")},
                    output=plan_critique.model_dump(mode="json"),
                ),
            ]
        except HarnessGraphError as error:
            raise MissionPreparationBlocked(error.code) from error
        for stage_receipt in preparation_stages:
            evidence.append("harness.stage", stage_receipt.model_dump(mode="json"))
        runtime_checkpoints = self._invoke_single_extension(
            "runtime.checkpoint-policy",
            "build_checkpoints",
            evidence=evidence,
            contract=contract,
            domain_actions=domain_actions,
            flight_plan=flight_plan,
        )
        if runtime_checkpoints is None:
            runtime_checkpoints = _runtime_checkpoints(contract, flight_plan)
        runtime_checkpoints = RuntimeCheckpointContract.model_validate(runtime_checkpoints)
        try:
            checkpoints_stage = stage_runtime.complete(
                "mission.runtime-checkpoints",
                inputs={"plan_review": plan_critique.model_dump(mode="json")},
                output=runtime_checkpoints.model_dump(mode="json"),
            )
            finalize_stage = stage_runtime.complete(
                "mission.evidence-finalize",
                inputs={"checkpoints": runtime_checkpoints.model_dump(mode="json")},
                output={
                    "contract_id": contract.contract_id,
                    "route_sha256": sha256_json(execution_route),
                    "track_sha256": sha256_json(px4_track),
                },
            )
            harness_stage_receipts = stage_runtime.finish()
        except HarnessGraphError as error:
            raise MissionPreparationBlocked(error.code) from error
        for stage_receipt in [checkpoints_stage, finalize_stage]:
            evidence.append("harness.stage", stage_receipt.model_dump(mode="json"))
        completed_event_payload = {
            "conversation_id": request.conversation_id,
            "topology_id": harness_topology.topology_id,
            "stage_receipts": [item.model_dump(mode="json") for item in harness_stage_receipts],
        }
        completed_transport = self._invoke_single_extension(
            "harness.event-bus",
            "transport_message",
            evidence=evidence,
            required=True,
            event="mission.preparation.completed",
            payload=completed_event_payload,
        )
        completed_observers = self._invoke_multiple_extensions(
            "harness.observers",
            "observe_harness",
            evidence=evidence,
            event="mission.preparation.completed",
            payload=completed_event_payload,
        )
        evidence.append(
            "harness.event",
            {"transport": completed_transport, "observers": completed_observers},
        )

        evaluations = self._invoke_multiple_extensions(
            "evaluation.preflight",
            "evaluate_preflight",
            evidence=evidence,
            contract=contract,
            task_graph=task_graph,
            semantic_plan=semantic_plan,
            flight_plan=flight_plan,
            route=execution_route,
            clearance=clearance,
            px4_track=px4_track,
            runtime_checkpoints=runtime_checkpoints,
        )
        if evaluations:
            _write_artifact(output_dir / "11a-plugin-evaluations.json", evaluations)
            evidence.append("evaluation.preflight", {"results": evaluations})
        simulation_campaign = self._invoke_single_extension(
            "simulation.campaign-generator",
            "generate_campaign",
            evidence=evidence,
            contract=contract,
            task_graph=task_graph,
            semantic_plan=semantic_plan,
            flight_plan=flight_plan,
            route=execution_route,
            clearance=clearance,
            px4_track=px4_track,
        )
        fault_library = self._invoke_multiple_extensions(
            "simulation.fault-library",
            "describe_fault",
            evidence=evidence,
            contract=contract,
            task_graph=task_graph,
            semantic_plan=semantic_plan,
            flight_plan=flight_plan,
            route=execution_route,
            clearance=clearance,
            px4_track=px4_track,
        )
        if simulation_campaign is not None or fault_library:
            campaign_artifact = {
                "schema_version": "dronedream.simulation-campaign.v1",
                "generator": simulation_campaign,
                "fault_library": fault_library,
                "execution_contract": (
                    "Fault entries are typed simulator-adapter inputs. They do not alter the "
                    "confirmed mission unless an explicit evaluation run selects them."
                ),
            }
            _write_artifact(output_dir / "11b-simulation-campaign.json", campaign_artifact)
            evidence.append("simulation.campaign", campaign_artifact)
        for name, artifact in (
            ("04-task-graph.json", task_graph),
            ("05-semantic-plan.json", semantic_plan),
            ("06-flight-plan.json", flight_plan),
            ("07-plan-critique.json", plan_critique),
            ("08-execution-route.json", execution_route),
            ("09-route-clearance.json", clearance),
            ("10-px4-track.json", px4_track),
            ("11-runtime-checkpoints.json", runtime_checkpoints),
        ):
            _write_artifact(output_dir / name, artifact)

        summary_policy = self._invoke_single_extension(
            "context.summarization-policy",
            "summarize_context",
            evidence=evidence,
            required=True,
            window=self.context_store.window(request.conversation_id, max_recent_events=200),
        )
        if not isinstance(summary_policy, dict):
            raise MissionPreparationBlocked("CONTEXT_SUMMARY_POLICY_INVALID")
        summary_text = summary_policy.get("summary")
        through_sequence = summary_policy.get("through_sequence")
        if isinstance(summary_text, str) and summary_text and isinstance(through_sequence, int):
            self.context_store.set_summary(request.conversation_id, summary_text, through_sequence)
        retention_policy = self._invoke_single_extension(
            "context.retention-policy",
            "resolve_retention",
            evidence=evidence,
            required=True,
            conversation_id=request.conversation_id,
        )
        if not isinstance(retention_policy, dict):
            raise MissionPreparationBlocked("CONTEXT_RETENTION_POLICY_INVALID")
        removed_events = self.context_store.apply_retention(
            request.conversation_id,
            maximum_events=int(retention_policy.get("maximum_events", 10_000)),
        )
        evidence.append(
            "context.maintenance",
            {
                "store": context_store_policy,
                "retrieval": retrieval_policy,
                "summary_through_sequence": through_sequence,
                "retention": retention_policy,
                "removed_events": removed_events,
            },
        )

        prepared = PreparedMission(
            intent=intent,
            intent_critique=intent_critique,
            contract=contract,
            domain_actions=domain_actions,
            simulation_capabilities=simulation_capabilities,
            task_graph=task_graph,
            semantic_plan=semantic_plan,
            plan=flight_plan,
            plan_critique=plan_critique,
            execution_route=execution_route,
            route_clearance=clearance,
            px4_track=px4_track,
            runtime_checkpoints=runtime_checkpoints,
            planning_attempts=planning_attempts,
            model_calls=model_calls,
            plugin_snapshot=self.plugin_snapshot,
            harness_topology=harness_topology,
            harness_stage_receipts=harness_stage_receipts,
            plugin_hook_receipts=list(self._hook_receipts),
            tool_receipts=tool_receipts,
            evidence=evidence.read(),
        )
        _write_artifact(output_dir / "prepared-mission.json", prepared)
        lifecycle_binding = self.context_store.lifecycle.record_plan_revision(
            conversation_id=request.conversation_id,
            contract_id=prepared.contract.contract_id,
            prepared_mission_sha256=sha256_json(prepared),
            source_message_sha256=sha256_json({"message": request.message}),
        )
        _write_artifact(output_dir / "mission-lifecycle.json", lifecycle_binding)
        return prepared
