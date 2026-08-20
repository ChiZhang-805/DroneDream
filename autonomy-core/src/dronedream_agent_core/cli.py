"""Development CLI for real model and runtime acceptance operations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .assets import load_school_map_catalog
from .collision import validate_route_clearance
from .context import ContextStore
from .contracts import (
    GraphRoute,
    IntentArtifact,
    IntentCritique,
    MapAsset,
    MissionRequest,
    RouteQuery,
    VehicleAsset,
)
from .execution import execute_prepared_mission, reverify_prepared_run
from .gazebo_adapter import run_px4_gazebo_track
from .model_port import StructuredModelPort
from .navigation import build_school_map_graph, shortest_route
from .orchestrator import MissionOrchestrator, PreparationConfig
from .prompts import INTENT_CRITIC, INTENT_PARSER
from .px4_track import route_to_px4_track
from .runtime_interrupt import submit_runtime_message


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _model_probe(args: argparse.Namespace) -> int:
    request = MissionRequest.model_validate(_read_json(args.request))
    map_catalog = _read_json(args.map_catalog)
    port = StructuredModelPort(args.provider, max_attempts=args.max_attempts)
    result = port.call(
        role="intent_parser",
        output_type=IntentArtifact,
        instructions=INTENT_PARSER,
        input_artifact={
            "mission_request": request.model_dump(mode="json"),
            "map_catalog": map_catalog,
        },
        context_id=request.conversation_id,
    )
    output = {
        "artifact": result.artifact.model_dump(mode="json"),
        "model_call": result.record.model_dump(mode="json"),
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _export_map_catalog(args: argparse.Namespace) -> int:
    catalog = load_school_map_catalog(args.semantic)
    rendered = catalog.model_dump_json(indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"MAP_CATALOG_EXPORTED entities={len(catalog.entities)} "
        f"topology_available={catalog.topology_available} output={args.output}"
    )
    return 0


def _intent_critic(args: argparse.Namespace) -> int:
    request = MissionRequest.model_validate(_read_json(args.request))
    intent_document = _read_json(args.intent)
    intent_value = intent_document.get("artifact", intent_document)
    intent = IntentArtifact.model_validate(intent_value)
    map_catalog = _read_json(args.map_catalog)
    port = StructuredModelPort(args.provider, max_attempts=args.max_attempts)
    result = port.call(
        role="intent_critic",
        output_type=IntentCritique,
        instructions=INTENT_CRITIC,
        input_artifact={
            "mission_request": request.model_dump(mode="json"),
            "candidate_intent": intent.model_dump(mode="json"),
            "map_catalog": map_catalog,
        },
        context_id=request.conversation_id,
    )
    output = {
        "artifact": result.artifact.model_dump(mode="json"),
        "candidate_intent_sha256": intent_document.get("model_call", {}).get("output_sha256"),
        "model_call": result.record.model_dump(mode="json"),
    }
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


def _export_navigation_graph(args: argparse.Namespace) -> int:
    graph = build_school_map_graph(args.semantic, args.verified_track, args.mission_evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(graph.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"NAVIGATION_GRAPH_EXPORTED nodes={len(graph.nodes)} edges={len(graph.edges)} "
        f"entities={len(graph.named_entities)} output={args.output}"
    )
    return 0


def _plan_graph_route(args: argparse.Namespace) -> int:
    graph = MapAsset.model_validate(_read_json(args.graph))
    start_node = graph.named_entities.get(args.start, args.start)
    goal_node = graph.named_entities.get(args.goal, args.goal)
    route = shortest_route(
        graph,
        RouteQuery(
            start_node=start_node,
            goal_node=goal_node,
            require_flight_verified_edges=args.require_flight_verified,
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(route.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"GRAPH_ROUTE_PLANNED points={len(route.node_ids)} "
        f"length_m={route.route_length_m:.3f} "
        f"all_edges_flight_verified={route.all_edges_flight_verified} output={args.output}"
    )
    return 0


def _validate_route(args: argparse.Namespace) -> int:
    route = GraphRoute.model_validate(_read_json(args.route))
    report = validate_route_clearance(
        route,
        args.semantic,
        vehicle_diameter_m=args.vehicle_diameter_m,
        vehicle_height_m=args.vehicle_height_m,
        sample_interval_m=args.sample_interval_m,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"ROUTE_CLEARANCE accepted={report.accepted} samples={report.sample_count} "
        f"collisions={report.collision_count} minimum_m={report.minimum_clearance_m:.6f} "
        f"output={args.output}"
    )
    return 0 if report.accepted else 2


def _export_px4_track(args: argparse.Namespace) -> int:
    route = GraphRoute.model_validate(_read_json(args.route))
    graph = MapAsset.model_validate(_read_json(args.graph))
    track = route_to_px4_track(
        route,
        graph,
        args.semantic,
        waypoint_hold_seconds=args.waypoint_hold_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(track.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"PX4_TRACK_EXPORTED points={len(track.points)} output={args.output}")
    return 0


def _run_px4_track(args: argparse.Namespace) -> int:
    evidence = run_px4_gazebo_track(
        run_dir=args.run_dir,
        world_sdf=args.world_sdf,
        semantic_path=args.semantic,
        vehicle_sdf=args.vehicle_sdf,
        route_path=args.route,
        track_path=args.track,
        clearance_path=args.clearance,
        controller_params_path=args.controller_params,
        px4_root=args.px4_root,
        executor_path=args.executor,
        ros_workspace=args.ros_workspace,
    )
    print(
        f"PX4_GAZEBO_RUN status={evidence['status']} "
        f"output={args.run_dir / 'mission_evidence.json'}"
    )
    return 0 if evidence["status"] == "verified" else 2


def _prepare_mission(args: argparse.Namespace) -> int:
    request = MissionRequest.model_validate(_read_json(args.request))
    graph = MapAsset.model_validate(_read_json(args.graph))
    vehicle = VehicleAsset.model_validate(_read_json(args.vehicle_metadata))
    catalog = load_school_map_catalog(args.semantic)
    context = ContextStore(args.context_db)
    try:
        orchestrator = MissionOrchestrator(
            config=PreparationConfig(
                provider=args.provider,
                critic_provider=args.critic_provider,
                max_provider_attempts=args.max_provider_attempts,
                max_intent_rounds=args.max_intent_rounds,
                max_planning_rounds=args.max_planning_rounds,
                model_timeout_seconds=args.model_timeout_seconds,
                vehicle_diameter_m=args.vehicle_diameter_m,
                vehicle_height_m=args.vehicle_height_m,
                waypoint_hold_seconds=args.waypoint_hold_seconds,
            ),
            map_catalog=catalog,
            map_graph=graph,
            semantic_path=args.semantic,
            vehicle_sdf=args.vehicle_sdf,
            vehicle_asset_id=vehicle.asset_id,
            vehicle=vehicle,
            context_store=context,
        )
        prepared = orchestrator.prepare(request, args.output_dir)
    finally:
        context.close()
    print(
        f"MISSION_PREPARED status={prepared.status} "
        f"model_calls={len(prepared.model_calls)} "
        f"planning_attempts={prepared.planning_attempts} "
        f"route_points={len(prepared.execution_route.node_ids)} "
        f"output={args.output_dir / 'prepared-mission.json'}"
    )
    return 0


def _execute_prepared_mission(args: argparse.Namespace) -> int:
    context = ContextStore(args.context_db)
    try:
        result = execute_prepared_mission(
            prepared_path=args.prepared,
            confirm_contract_id=args.confirm_contract_id,
            run_dir=args.run_dir,
            world_sdf=args.world_sdf,
            semantic_path=args.semantic,
            vehicle_sdf=args.vehicle_sdf,
            controller_params_path=args.controller_params,
            executor_path=args.executor,
            px4_root=args.px4_root,
            ros_workspace=args.ros_workspace,
            completion_provider=args.completion_provider,
            context_store=context,
            model_timeout_seconds=args.model_timeout_seconds,
            checkpoint_provider=args.checkpoint_provider,
            checkpoint_executor_path=args.checkpoint_executor,
            checkpoint_timeout_seconds=args.checkpoint_timeout_seconds,
            runtime_interrupt_provider=args.runtime_interrupt_provider,
            runtime_hold_timeout_seconds=args.runtime_hold_timeout_seconds,
            runtime_decision_timeout_seconds=args.runtime_decision_timeout_seconds,
            runtime_replan_hold_seconds=args.runtime_replan_hold_seconds,
            map_graph_path=args.map_graph,
            vehicle_metadata_path=args.vehicle_metadata,
        )
    finally:
        context.close()
    print(
        f"MISSION_WORKFLOW status={result.status} contract={result.contract_id} "
        f"output={args.run_dir / 'workflow-result.json'}"
    )
    return 0 if result.status == "verified" else 2


def _submit_runtime_message(args: argparse.Namespace) -> int:
    message = submit_runtime_message(control_dir=args.run_dir / "runtime-control", text=args.text)
    print(
        f"RUNTIME_MESSAGE_ACCEPTED message_id={message.message_id} "
        f"mission_id={message.mission_id} execution_id={message.execution_id}"
    )
    return 0


def _reverify_prepared_run(args: argparse.Namespace) -> int:
    context = ContextStore(args.context_db)
    try:
        result = reverify_prepared_run(
            prepared_path=args.prepared,
            confirm_contract_id=args.confirm_contract_id,
            run_dir=args.run_dir,
            semantic_path=args.semantic,
            vehicle_sdf=args.vehicle_sdf,
            completion_provider=args.completion_provider,
            context_store=context,
            model_timeout_seconds=args.model_timeout_seconds,
        )
    finally:
        context.close()
    print(
        f"MISSION_REVERIFIED status={result.status} contract={result.contract_id} "
        f"output={args.run_dir / 'workflow-result-r2.json'}"
    )
    return 0 if result.status == "verified" else 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dronedream-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe = subparsers.add_parser("model-probe", help="call one real structured intent role")
    probe.add_argument("--provider", required=True)
    probe.add_argument("--request", type=Path, required=True)
    probe.add_argument("--map-catalog", type=Path, required=True)
    probe.add_argument("--output", type=Path)
    probe.add_argument("--max-attempts", type=int, default=3)
    probe.set_defaults(handler=_model_probe)
    catalog = subparsers.add_parser(
        "export-map-catalog", help="import the real School Map semantic artifact"
    )
    catalog.add_argument("--semantic", type=Path, required=True)
    catalog.add_argument("--output", type=Path, required=True)
    catalog.set_defaults(handler=_export_map_catalog)
    critic = subparsers.add_parser(
        "intent-critic", help="independently review a structured intent with a real model"
    )
    critic.add_argument("--provider", required=True)
    critic.add_argument("--request", type=Path, required=True)
    critic.add_argument("--intent", type=Path, required=True)
    critic.add_argument("--map-catalog", type=Path, required=True)
    critic.add_argument("--output", type=Path, required=True)
    critic.add_argument("--max-attempts", type=int, default=3)
    critic.set_defaults(handler=_intent_critic)
    graph = subparsers.add_parser(
        "export-navigation-graph", help="build a provenance-bound graph from real artifacts"
    )
    graph.add_argument("--semantic", type=Path, required=True)
    graph.add_argument("--verified-track", type=Path, required=True)
    graph.add_argument("--mission-evidence", type=Path, required=True)
    graph.add_argument("--output", type=Path, required=True)
    graph.set_defaults(handler=_export_navigation_graph)
    route = subparsers.add_parser("plan-graph-route", help="run generic Dijkstra routing")
    route.add_argument("--graph", type=Path, required=True)
    route.add_argument("--start", required=True)
    route.add_argument("--goal", required=True)
    route.add_argument("--require-flight-verified", action="store_true")
    route.add_argument("--output", type=Path, required=True)
    route.set_defaults(handler=_plan_graph_route)
    clearance = subparsers.add_parser(
        "validate-route", help="sample a route against real School Map collision primitives"
    )
    clearance.add_argument("--route", type=Path, required=True)
    clearance.add_argument("--semantic", type=Path, required=True)
    clearance.add_argument("--vehicle-diameter-m", type=float, default=0.76)
    clearance.add_argument("--vehicle-height-m", type=float, default=0.43)
    clearance.add_argument("--sample-interval-m", type=float, default=0.1)
    clearance.add_argument("--output", type=Path, required=True)
    clearance.set_defaults(handler=_validate_route)
    track = subparsers.add_parser(
        "export-px4-track", help="convert a validated ENU route for the real PX4 executor"
    )
    track.add_argument("--route", type=Path, required=True)
    track.add_argument("--graph", type=Path, required=True)
    track.add_argument("--semantic", type=Path, required=True)
    track.add_argument("--waypoint-hold-seconds", type=float, default=0.4)
    track.add_argument("--output", type=Path, required=True)
    track.set_defaults(handler=_export_px4_track)
    runtime = subparsers.add_parser(
        "run-px4-track", help="execute a validated track in real PX4 SITL and Gazebo"
    )
    runtime.add_argument("--run-dir", type=Path, required=True)
    runtime.add_argument("--world-sdf", type=Path, required=True)
    runtime.add_argument("--semantic", type=Path, required=True)
    runtime.add_argument("--vehicle-sdf", type=Path, required=True)
    runtime.add_argument("--route", type=Path, required=True)
    runtime.add_argument("--track", type=Path, required=True)
    runtime.add_argument("--clearance", type=Path, required=True)
    runtime.add_argument("--controller-params", type=Path, required=True)
    runtime.add_argument("--px4-root", type=Path, default=Path("/opt/PX4-Autopilot"))
    runtime.add_argument(
        "--executor",
        type=Path,
        default=Path("/opt/dronedream/source/scripts/simulators/px4_offboard_track_executor.py"),
    )
    runtime.add_argument(
        "--ros-workspace",
        type=Path,
        default=Path(os.environ.get("DRONEDREAM_AUTONOMY_ROS_WORKSPACE", "ros_ws")),
    )
    runtime.set_defaults(handler=_run_px4_track)
    prepare = subparsers.add_parser(
        "prepare-mission",
        help="run the real multi-call model and qualified-tool preparation workflow",
    )
    prepare.add_argument("--provider", required=True)
    prepare.add_argument("--critic-provider", required=True)
    prepare.add_argument("--request", type=Path, required=True)
    prepare.add_argument("--graph", type=Path, required=True)
    prepare.add_argument("--semantic", type=Path, required=True)
    prepare.add_argument("--vehicle-sdf", type=Path, required=True)
    prepare.add_argument("--vehicle-metadata", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument(
        "--context-db", type=Path, default=Path("artifacts/state/conversations.sqlite3")
    )
    prepare.add_argument("--max-provider-attempts", type=int, default=3)
    prepare.add_argument("--max-intent-rounds", type=int, default=3)
    prepare.add_argument("--max-planning-rounds", type=int, default=5)
    prepare.add_argument("--model-timeout-seconds", type=float, default=180.0)
    prepare.add_argument("--vehicle-diameter-m", type=float, default=0.76)
    prepare.add_argument("--vehicle-height-m", type=float, default=0.43)
    prepare.add_argument("--waypoint-hold-seconds", type=float, default=0.4)
    prepare.set_defaults(handler=_prepare_mission)
    execute = subparsers.add_parser(
        "execute-prepared-mission",
        help="confirm a hash-bound package and run it in real PX4 SITL and Gazebo",
    )
    execute.add_argument("--prepared", type=Path, required=True)
    execute.add_argument("--confirm-contract-id", required=True)
    execute.add_argument(
        "--completion-provider",
        required=True,
    )
    execute.add_argument("--run-dir", type=Path, required=True)
    execute.add_argument("--world-sdf", type=Path, required=True)
    execute.add_argument("--semantic", type=Path, required=True)
    execute.add_argument("--map-graph", type=Path)
    execute.add_argument("--vehicle-sdf", type=Path, required=True)
    execute.add_argument("--vehicle-metadata", type=Path)
    execute.add_argument("--controller-params", type=Path, required=True)
    execute.add_argument("--px4-root", type=Path, default=Path("/opt/PX4-Autopilot"))
    execute.add_argument("--executor", type=Path, required=True)
    execute.add_argument(
        "--ros-workspace",
        type=Path,
        default=Path(os.environ.get("DRONEDREAM_AUTONOMY_ROS_WORKSPACE", "ros_ws")),
    )
    execute.add_argument(
        "--context-db", type=Path, default=Path("artifacts/state/conversations.sqlite3")
    )
    execute.add_argument("--model-timeout-seconds", type=float, default=180.0)
    execute.add_argument("--checkpoint-provider")
    execute.add_argument("--checkpoint-executor", type=Path)
    execute.add_argument("--checkpoint-timeout-seconds", type=float, default=180.0)
    execute.add_argument("--runtime-interrupt-provider")
    execute.add_argument("--runtime-hold-timeout-seconds", type=float, default=12.0)
    execute.add_argument("--runtime-decision-timeout-seconds", type=float, default=180.0)
    execute.add_argument("--runtime-replan-hold-seconds", type=float, default=30.0)
    execute.set_defaults(handler=_execute_prepared_mission)
    interrupt = subparsers.add_parser(
        "submit-runtime-message",
        help="atomically interrupt the exact active task execution before model reasoning",
    )
    interrupt.add_argument("--run-dir", type=Path, required=True)
    interrupt.add_argument("--text", required=True)
    interrupt.set_defaults(handler=_submit_runtime_message)
    reverify = subparsers.add_parser(
        "reverify-prepared-run",
        help="re-run completion review over an immutable finished PX4/Gazebo run",
    )
    reverify.add_argument("--prepared", type=Path, required=True)
    reverify.add_argument("--confirm-contract-id", required=True)
    reverify.add_argument(
        "--completion-provider",
        required=True,
    )
    reverify.add_argument("--run-dir", type=Path, required=True)
    reverify.add_argument("--semantic", type=Path, required=True)
    reverify.add_argument("--vehicle-sdf", type=Path, required=True)
    reverify.add_argument(
        "--context-db", type=Path, default=Path("artifacts/state/conversations.sqlite3")
    )
    reverify.add_argument("--model-timeout-seconds", type=float, default=180.0)
    reverify.set_defaults(handler=_reverify_prepared_run)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
