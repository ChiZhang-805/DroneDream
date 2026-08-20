from __future__ import annotations

from dronedream_agent_core.contracts import (
    FlightPlan,
    GraphRoute,
    MapAsset,
    MapEdge,
    MapNode,
    MissionContract,
    PlannerContribution,
    PlannerValidation,
    PlanSegment,
    Px4CoordinateContract,
    Px4Track,
    Px4TrackPoint,
    RouteClearanceReport,
    RoutePoint,
    SemanticPlan,
    TaskGraph,
    TaskNode,
    Vector3,
    VehicleAsset,
    WorldTrackPoint,
)
from dronedream_agent_core.plugin_api import build_discovered_extension_registry


def _fixtures() -> tuple[
    MissionContract,
    MapAsset,
    VehicleAsset,
    TaskGraph,
    GraphRoute,
    RouteClearanceReport,
    Px4Track,
]:
    graph = MapAsset(
        asset_id="map-a",
        name="Map",
        nodes=[
            MapNode(
                node_id="start",
                label="Start",
                position_m=Vector3(x=0, y=0, z=1),
                semantic="office",
            ),
            MapNode(
                node_id="target",
                label="Target",
                position_m=Vector3(x=2, y=0, z=1),
                semantic="pickup",
            ),
        ],
        edges=[
            MapEdge(
                edge_id="start-target",
                from_node="start",
                to_node="target",
                distance_m=2,
                minimum_clearance_m=1,
                speed_limit_mps=1,
                qualification="flight-verified",
                evidence_sha256="1" * 64,
            )
        ],
        named_entities={"start": "start", "target": "target"},
    )
    contract = MissionContract(
        contract_id="mission-" + "a" * 24,
        conversation_id="conversation-a",
        goal="Pick up and return",
        start_node="start",
        target_node="target",
        return_node="start",
        payload_action="pickup",
        map_asset_id=graph.asset_id,
        map_sha256="2" * 64,
        map_semantic_sha256="3" * 64,
        vehicle_asset_id="vehicle-a",
        vehicle_sha256="4" * 64,
        constraints=["simulation", "safety_priority"],
        immutable_safety_rules=["Unknown telemetry causes hold or abort."],
    )
    vehicle = VehicleAsset(
        asset_id="vehicle-a",
        name="Vehicle",
        dry_mass_kg=1,
        max_takeoff_mass_kg=2,
        body_radius_m=0.2,
        body_height_m=0.2,
        max_speed_mps=2,
        max_acceleration_mps2=2,
        reserve_battery_percent=20,
        qualified_range_m=100,
        max_pickup_payload_kg=0.5,
        sensors=["camera"],
    )
    task_graph = TaskGraph(
        nodes=[
            TaskNode(
                task_id="pickup",
                action="pickup",
                target_node="target",
                success_evidence=["payload attached"],
                fallback="hold",
            )
        ]
    )
    route = GraphRoute(
        start_node="start",
        goal_node="start",
        node_ids=["start", "target", "start"],
        edge_ids=["start-target", "start-target"],
        positions_m=[
            Vector3(x=0, y=0, z=1),
            Vector3(x=2, y=0, z=1),
            Vector3(x=0, y=0, z=1),
        ],
        route_length_m=4,
        all_edges_flight_verified=True,
    )
    clearance = RouteClearanceReport(
        accepted=True,
        route_sha256="5" * 64,
        semantic_sha256="6" * 64,
        sample_interval_m=0.1,
        sample_count=41,
        primitive_count=1,
        collision_count=0,
        minimum_clearance_m=1,
        minimum_clearance_point=Vector3(x=1, y=0, z=1),
        minimum_clearance_primitive="wall",
    )
    track = Px4Track(
        coordinate_contract=Px4CoordinateContract(
            model_root_world_enu_m=[0, 0, 0],
            collision_center_above_model_root_m=0.2,
        ),
        points=[
            Px4TrackPoint(x=0, y=0, z=0.8, phase="launch", speed_limit_mps=1),
            Px4TrackPoint(x=0, y=2, z=0.8, phase="pickup", speed_limit_mps=1),
            Px4TrackPoint(x=0, y=0, z=0.8, phase="land", speed_limit_mps=1),
        ],
        source_world_points=[
            WorldTrackPoint(east_m=0, north_m=0, up_m=1),
            WorldTrackPoint(east_m=2, north_m=0, up_m=1),
            WorldTrackPoint(east_m=0, north_m=0, up_m=1),
        ],
        waypoint_hold_seconds=0.2,
    )
    return contract, graph, vehicle, task_graph, route, clearance, track


def test_all_planning_layers_contribute_and_validate() -> None:
    registry = build_discovered_extension_registry()
    contract, graph, vehicle, task_graph, route, clearance, track = _fixtures()
    contributions, _ = registry.invoke_multiple(
        "planning.specialists",
        "contribute_planning",
        contract=contract,
        map_graph=graph,
        vehicle=vehicle,
    )
    validations, _ = registry.invoke_multiple(
        "planning.specialists",
        "validate_planning",
        contract=contract,
        map_graph=graph,
        vehicle=vehicle,
        task_graph=task_graph,
        semantic_plan=SemanticPlan(
            ordered_targets=["target", "start"], rationale_summary="Bound route"
        ),
        flight_plan=FlightPlan(
            revision=1,
            contract_id=contract.contract_id,
            semantic_plan_sha256="7" * 64,
            segments=[
                PlanSegment(
                    segment_id="segment-001",
                    task_id="pickup",
                    from_node="start",
                    to_node="target",
                    path=[
                        RoutePoint(node_id="start", position_m=Vector3(x=0, y=0, z=1)),
                        RoutePoint(node_id="target", position_m=Vector3(x=2, y=0, z=1)),
                    ],
                    speed_limit_mps=1,
                    minimum_clearance_m=1,
                    success_evidence=["target reached"],
                )
            ],
        ),
        route=route,
        clearance=clearance,
        px4_track=track,
    )

    parsed_contributions = [PlannerContribution.model_validate(value) for value in contributions]
    parsed_validations = [PlannerValidation.model_validate(value) for value in validations]
    assert {value.layer for value in parsed_contributions} == {
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
    }
    assert len(parsed_validations) == 11
    assert all(value.accepted for value in parsed_validations)
